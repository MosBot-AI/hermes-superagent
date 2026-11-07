"""Review-only consumer on native command/turn/SQLite/lifecycle and real SDK wire.

httpx.MockTransport returns synthetic JSON without binding/listening/connecting.
Never run against an installed host or a personal profile.
"""

import asyncio
import json
import shutil
import socket
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI
from test_local_conversation_tasks import command, database, make_host
from test_local_conversation_tasks import native as native  # noqa: F401
from test_session_task_tools import turn

HERE = Path(__file__).resolve().parent
PLUGIN_ID = "hermes-personal-agent"
PROVIDER = "opencode-go"
MODEL = "deepseek-v4.1-flash"
BASE_URL = "https://synthetic.invalid/v1"


@pytest.fixture
def host(native, monkeypatch):  # noqa: F811
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    entry = config["plugins"]["entries"][PLUGIN_ID]
    entry["settings"].update(local_model_tools=True, experimental_text_worker=True)
    entry["text_workers"] = {
        "enabled": True,
        "routes": [{"provider": PROVIDER, "model": MODEL, "base_url": BASE_URL}],
    }
    (home / "config.yaml").write_text(json.dumps(config))
    plugin = home / "plugins" / PLUGIN_ID
    shutil.copy2(HERE / "consumer.py", plugin / "worker_consumer.py")
    with (plugin / "__init__.py").open("a") as file:
        file.write(
            "\n    from .worker_consumer import register as register_experiment\n"
            "    register_experiment(ctx)\n"
        )

    def load(manager):
        manager.discover_and_load()
        assert manager._plugins[PLUGIN_ID].error is None
        assert "personal-plan-worker" in manager._plugin_commands

    monkeypatch.setattr("test_local_conversation_tasks.load", load)
    host = make_host(home, manager)
    host.requests = []
    host.wire_response = {"role": "assistant", "content": "Draft: clarify the first milestone."}

    def reply(request):
        host.requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "created": 1,
                "model": MODEL,
                "choices": [{"index": 0, "message": host.wire_response, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    def deny_network(*args, **kwargs):
        raise AssertionError("No socket operation is allowed in this experiment")

    for name in ("connect", "connect_ex", "bind", "listen"):
        monkeypatch.setattr(socket.socket, name, deny_network)
    client = OpenAI(
        api_key="synthetic-fixture-only",
        base_url=BASE_URL,
        http_client=httpx.Client(transport=httpx.MockTransport(reply)),
    )
    host.parent = SimpleNamespace(
        session_id=host.ref.session_id,
        platform="cli",
        parent_session_id=None,
        provider=PROVIDER,
        model=MODEL,
        api_mode="chat_completions",
        base_url=BASE_URL,
        client=client,
        request_overrides={},
        reasoning_config=None,
        conversation_history=[{"role": "user", "content": "EXCLUDED_PARENT_HISTORY"}],
        tools=[{"function": {"name": "terminal"}}],
        enabled_toolsets=["terminal", "delegation", "mcp-fixture"],
        _delegate_depth=0,
    )
    host.consumer = manager._plugin_commands["personal-plan-worker"]["handler"].__self__
    try:
        yield host
    finally:
        client.close()


def consent(host, text):
    from gateway.session_commands import execute_command

    return json.loads(
        asyncio.run(
            execute_command(host.connection, host.ref, {"command": "personal-plan-worker " + text})
        )["output"]
    )


@contextmanager
def native_turn(host, **changes):
    from agent.subagent_lifecycle import bind_subagent_parent

    with turn(host, **changes), bind_subagent_parent(host.parent):
        yield


def invoke(host, *, action="launch", key="plan-1", **extra):
    from model_tools import handle_function_call

    return json.loads(
        handle_function_call(
            "personal_task_plan_preview",
            {"action": action, "request_id": key, **extra},
            session_id=host.ref.session_id,
            task_id="native-task",
        )
    )


def allow(host):
    task = command(host, 'add "Task to plan" --details "Selected details" --request-id seed')[
        "data"
    ]
    result = consent(host, f"allow {task['id']} 1 plan-1")
    assert result["status"] == "ok", result
    return task


def wait(host):
    handle = next(iter(host.consumer.grants.values())).handle
    assert handle is not None
    return host.consumer.service.wait(handle, timeout_seconds=5)


def test_native_task_grant_to_real_host_worker_and_draft_without_task_mutation(host):
    task = allow(host)
    before = database(host.home).read_bytes()
    assert host.requests == []
    with native_turn(host):
        assert invoke(host)["status"] == "ok"
        assert wait(host).completed
        result = invoke(host, action="result")
        assert result["data"]["ready"]
        assert result["data"]["state"] == "SUCCEEDED", result
        assert result["data"]["draft"] == "Draft: clarify the first milestone."
        assert result["data"]["snapshot_revision"] == 1
        assert result["data"]["task_id"] == task["id"]
        assert result["data"]["result_hash"]
        assert not result["data"]["stale"]
        assert invoke(host)["data"] == result["data"]
    assert len(host.requests) == 1
    wire = host.requests[0]
    assert wire["model"] == MODEL
    assert not wire.get("tools")
    assert wire["max_tokens"] == 1024
    assert "Selected details" in json.dumps(wire)
    assert "EXCLUDED_PARENT_HISTORY" not in json.dumps(wire)
    assert database(host.home).read_bytes() == before
    assert "capability" not in json.dumps(result)


def test_no_native_grant_means_no_worker(host):
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "no_task_worker_grant"
    assert host.requests == []
    assert not database(host.home).exists()


@pytest.mark.parametrize("extra", [{"goal": "forged"}, {"provider": "other"}, {"approved": True}])
def test_model_cannot_change_granted_payload(host, extra):
    allow(host)
    with native_turn(host):
        assert invoke(host, **extra)["status"] == "error"
    assert host.requests == []


@pytest.mark.parametrize(
    "change",
    [{"platform": "subagent"}, {"key": "wrong-route"}, {"parent": "foreign-parent"}],
)
def test_grant_does_not_cross_native_turn_boundary(host, change):
    allow(host)
    with native_turn(host, **change):
        assert invoke(host)["status"] == "error"
    assert host.requests == []


def test_grant_needs_real_turn_and_native_command_control(host):
    from gateway.session_commands import execute_command

    host.connection.actor = replace(host.connection.actor, capabilities=frozenset({"session:read"}))
    from hermes_state_runtime import RuntimeStoreError

    with pytest.raises(RuntimeStoreError):
        asyncio.run(
            execute_command(host.connection, host.ref, {"command": "personal-plan-worker help"})
        )
    assert invoke(host)["error"]["code"] == "no_active_local_turn"
    assert host.requests == []


def test_revoked_or_expired_grant_does_not_rearm_on_repeated_command(host):
    task = allow(host)
    assert consent(host, "revoke plan-1")["data"]["state"] == "revoked"
    again = consent(host, f"allow {task['id']} 1 plan-1")
    assert again["replayed"] and again["data"]["state"] == "revoked"
    with native_turn(host):
        assert invoke(host)["data"]["state"] == "revoked"
    assert host.requests == []
    assert consent(host, f"allow {task['id']} 1 plan-2")["status"] == "ok"
    host.consumer.grants[(host.ref.session_id, host.live.route, "plan-2")].expires_at = 0
    with native_turn(host):
        assert invoke(host, key="plan-2")["error"]["code"] == "grant_expired"
    assert host.requests == []


def test_changed_task_rejects_launch_and_late_changes_label_draft_stale(host):
    task = allow(host)
    command(host, f"update {task['id']} --expected-revision 1 --title Changed --request-id edit")
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "task_revision_or_state_changed"
    assert host.requests == []
    consent(host, f"allow {task['id']} 2 plan-2")
    with native_turn(host):
        assert invoke(host, key="plan-2")["status"] == "ok"
        handle = host.consumer.grants[(host.ref.session_id, host.live.route, "plan-2")].handle
        assert host.consumer.service.wait(handle, timeout_seconds=5).completed
    command(host, f"update {task['id']} --expected-revision 2 --title Latest --request-id edit-2")
    with native_turn(host):
        result = invoke(host, action="result", key="plan-2")["data"]
    assert result["stale"] and result["snapshot_revision"] == 2 and result["current_revision"] == 3
    assert len(host.requests) == 1


def test_host_route_refusal_consumes_grant_without_automatic_retry(host):
    allow(host)
    host.parent.model = "unauthorized-model"
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "worker_unavailable"
    host.parent.model = MODEL
    with native_turn(host):
        assert invoke(host)["data"]["state"] == "launch_outcome_unknown"
    assert host.requests == []


def test_unload_revokes_retained_consumer(host):
    allow(host)
    consumer = host.consumer
    host.manager.unload()
    with native_turn(host):
        value = json.loads(
            consumer.run(
                {"action": "launch", "request_id": "plan-1"},
                session_id=host.ref.session_id,
                task_id="native-task",
            )
        )
    assert value["status"] == "error"
    assert host.requests == []


def test_uncertain_host_launch_is_never_automatically_repeated(host, monkeypatch):
    allow(host)
    launch = host.consumer.service.launch_text

    def launch_then_lose_reply(request):
        handle = launch(request)
        assert host.consumer.service.wait(handle, timeout_seconds=5).completed
        raise RuntimeError("Synthetic lost acknowledgement")

    monkeypatch.setattr(host.consumer.service, "launch_text", launch_then_lose_reply)
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "worker_unavailable"
        assert invoke(host)["data"]["state"] == "launch_outcome_unknown"
    assert len(host.requests) == 1


def test_request_key_conflict_cannot_replace_selected_task(host):
    allow(host)
    other = command(host, 'add "Other task" --request-id other')["data"]
    assert consent(host, f"allow {other['id']} 1 plan-1")["error"]["code"] == "request_id_conflict"
    with native_turn(host):
        assert invoke(host)["status"] == "ok"
        assert wait(host).completed
    assert "Other task" not in json.dumps(host.requests)


def test_configuration_revoke_prevents_task_dispatch(host):
    allow(host)
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["experimental_text_worker"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "experimental_worker_disabled"
    assert host.requests == []
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["experimental_text_worker"] = True
    (host.home / "config.yaml").write_text(json.dumps(config))
    with native_turn(host):
        assert invoke(host)["data"]["state"] == "revoked"
    assert host.requests == []


def test_model_tool_reply_cannot_execute_or_complete_task(host):
    task = allow(host)
    host.wire_response = {
        "role": "assistant",
        "content": "I completed everything",
        "tool_calls": [
            {
                "id": "forged",
                "type": "function",
                "function": {"name": "terminal", "arguments": '{"command":"must-not-execute"}'},
            }
        ],
    }
    with native_turn(host):
        invoke(host)
        assert wait(host).completed
        result = invoke(host, action="result")["data"]
    assert result["state"] == "FAILED" and result["draft"] is None
    current = command(host, f"show {task['id']}")["data"]
    assert current["state"] == "captured" and current["revision"] == 1
    assert len(host.requests) == 1


def test_completed_task_cannot_be_authorized(host):
    task = command(host, 'add "Done task" --request-id done-seed')["data"]
    command(host, f"done {task['id']} --expected-revision 1 --note Done --request-id done")
    assert (
        consent(host, f"allow {task['id']} 2 plan-1")["error"]["code"]
        == "task_revision_or_state_changed"
    )
    assert host.requests == []
