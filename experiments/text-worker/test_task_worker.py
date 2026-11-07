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
    shutil.copy2(HERE / "worker_ledger.py", plugin / "worker_ledger.py")
    shutil.copy2(HERE / "worker_presentation.py", plugin / "worker_presentation.py")
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
    host.child_clients = []

    def fresh_client(timeout):
        client = httpx.Client(
            transport=httpx.MockTransport(reply),
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        )
        host.child_clients.append(client)
        return client

    monkeypatch.setattr("agent.text_subagent._new_http_client", fresh_client)
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
            execute_command(
                host.connection, host.ref, {"command": "personal-plan-worker --json " + text}
            )
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
    from agent.subagent_lifecycle import bind_subagent_parent

    handle = next(iter(host.consumer.grants.values())).handle
    assert handle is not None
    # Some callers just exited native_turn(). Lifecycle wait requires the active
    # parent: UNKNOWN_HANDLE also reports completed=True and is NOT completion.
    # Bind only the parent, preserving an existing turn rather than nesting one.
    with bind_subagent_parent(host.parent):
        terminal = host.consumer.service.wait(handle, timeout_seconds=5)
        assert terminal.state.value != "UNKNOWN", terminal
        assert terminal.completed and not terminal.timed_out, terminal
        result = host.consumer.service.result(handle)
        assert result.ready and result.terminal_state.value != "UNKNOWN", result
        return terminal


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
    assert host.child_clients and all(client.is_closed for client in host.child_clients)
    assert not host.parent.client.is_closed()
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


def test_host_route_refusal_before_claim_sends_no_data(host):
    allow(host)
    host.parent.model = "unauthorized-model"
    with native_turn(host):
        assert invoke(host)["error"]["code"] == "worker_unavailable"
    host.parent.model = MODEL
    with native_turn(host):
        assert invoke(host, action="result")["data"]["state"] == "authorized"
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


def fresh_consumer(host):
    old = host.consumer
    return type(old)(service=old.service, bound_home=old.bound_home, read_config=old.read_config)


def direct(host, consumer, action="launch", key="plan-1"):
    with native_turn(host):
        return json.loads(
            consumer.run(
                {"action": action, "request_id": key},
                session_id=host.ref.session_id,
                task_id="native-task",
            )
        )


def current_fingerprint(host):
    with native_turn(host):
        return host.consumer._authorize_route(host.ref.session_id)


def test_fresh_instance_cannot_adopt_live_grant_but_original_owner_can_launch(host):
    allow(host)
    other = fresh_consumer(host)
    assert direct(host, other)["data"]["state"] == "authorization_owner_unavailable"
    assert host.requests == []
    # Reading through a competing owner did not revoke or steal a live grant.
    assert direct(host, host.consumer)["status"] == "ok"
    assert wait(host).completed
    assert direct(host, host.consumer, "result")["data"]["ready"]
    assert direct(host, other, "result")["data"]["draft"] == "Draft: clarify the first milestone."
    assert len(host.requests) == 1


def test_lost_launch_reply_tombstone_survives_fresh_instance(host, monkeypatch):
    task = allow(host)
    launch = host.consumer.service.launch_text

    def lose(request):
        handle = launch(request)
        assert host.consumer.service.wait(handle, timeout_seconds=5).completed
        raise RuntimeError("lost reply")

    monkeypatch.setattr(host.consumer.service, "launch_text", lose)
    assert direct(host, host.consumer)["status"] == "error"
    other = fresh_consumer(host)
    assert direct(host, other)["data"]["state"] == "launch_outcome_unknown"
    assert (
        consent(host, f"allow {task['id']} 1 plan-1")["data"]["state"] == "launch_outcome_unknown"
    )
    assert len(host.requests) == 1


def test_observed_draft_survives_plugin_reload(host):
    allow(host)
    direct(host, host.consumer)
    assert wait(host).completed
    expected = direct(host, host.consumer, "result")["data"]
    host.manager.discover_and_load(force=True)
    host.consumer = host.manager._plugin_commands["personal-plan-worker"]["handler"].__self__
    assert direct(host, host.consumer, "result")["data"] == expected
    assert direct(host, host.consumer)["data"] == expected
    assert len(host.requests) == 1


def test_revocation_latches_even_if_ledger_temporarily_fails(host, monkeypatch):
    allow(host)
    config = json.loads((host.home / "config.yaml").read_text())
    settings = config["plugins"]["entries"][PLUGIN_ID]["settings"]
    settings["experimental_text_worker"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    original = host.consumer.ledger.revoke_owned

    def fail():
        raise OSError("synthetic ledger unavailable")

    monkeypatch.setattr(host.consumer.ledger, "revoke_owned", fail)
    assert direct(host, host.consumer)["status"] == "error"
    monkeypatch.setattr(host.consumer.ledger, "revoke_owned", original)
    settings["experimental_text_worker"] = True
    (host.home / "config.yaml").write_text(json.dumps(config))
    assert direct(host, host.consumer)["data"]["state"] == "revoked"
    assert host.requests == []


def test_concurrent_claims_commit_only_one_owner_transition(host):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    allow(host)
    ledger = host.consumer.ledger
    key = (host.ref.session_id, host.live.route, "plan-1")
    context_hash = ledger.get(key)["context_hash"]
    fingerprint = current_fingerprint(host)
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        return ledger.claim(key, context_hash, fingerprint)[1]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: claim(), range(2))) == [False, True]
    assert direct(host, fresh_consumer(host))["data"]["state"] == "launch_outcome_unknown"
    assert host.requests == []


def test_crash_after_durable_claim_before_submission_never_rearms(host):
    import os
    import subprocess
    import sys

    allow(host)
    ledger = host.consumer.ledger
    key = (host.ref.session_id, host.live.route, "plan-1")
    row = ledger.get(key)
    code = """
import importlib.util, os, sys
spec=importlib.util.spec_from_file_location("isolated_ledger", sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
from pathlib import Path
ledger=module.Ledger(Path(sys.argv[2]), sys.argv[3])
assert ledger.claim(tuple(sys.argv[4:7]),sys.argv[7],sys.argv[8])[1]
os._exit(23)
"""
    env = {**os.environ, "HERMES_HOME": str(host.home), "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            str(HERE / "worker_ledger.py"),
            str(host.home),
            ledger.owner,
            *key,
            row["context_hash"],
            current_fingerprint(host),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 23, result.stderr
    assert ledger.get(key)["state"] == "claimed"
    assert direct(host, fresh_consumer(host))["data"]["state"] == "launch_outcome_unknown"
    assert direct(host, host.consumer)["data"]["state"] == "launch_outcome_unknown"
    assert host.requests == []


def test_durable_capacity_refuses_without_evicting_after_new_owner(host):
    allow(host)
    ledger = host.consumer.ledger
    key = (host.ref.session_id, host.live.route, "plan-1")
    row = ledger.get(key)
    for n in range(63):
        ledger.authorize((key[0], key[1], f"extra-{n}"), row["task_id"], 1, row["context_hash"], 0)
    from personal_agent.tasks import TaskError

    other = fresh_consumer(host)
    with pytest.raises(TaskError, match="grant_capacity_reached"):
        other.ledger.authorize(
            (key[0], key[1], "overflow"), row["task_id"], 1, row["context_hash"], 0
        )
    assert other.ledger.get(key)["owner"] == ledger.owner


def test_corrupt_persisted_receipt_is_not_exposed_or_relaunched(host):
    allow(host)
    direct(host, host.consumer)
    assert wait(host).completed
    assert direct(host, host.consumer, "result")["data"]["ready"]
    with host.consumer.ledger.connection() as conn:
        conn.execute("UPDATE grants SET result=?", ('{"data":{"draft":"forged"}}',))
    assert direct(host, fresh_consumer(host), "result")["error"]["code"] == "worker_ledger_corrupt"
    assert direct(host, host.consumer)["status"] == "error"
    assert len(host.requests) == 1


def test_explicit_revoke_latches_before_failed_durable_write(host, monkeypatch):
    allow(host)
    original = host.consumer.ledger.revoke

    def fail(*args):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(host.consumer.ledger, "revoke", fail)
    assert consent(host, "revoke plan-1")["status"] == "error"
    monkeypatch.setattr(host.consumer.ledger, "revoke", original)
    assert direct(host, host.consumer)["data"]["state"] == "revoked"
    assert host.requests == []


def test_expiry_while_claim_waits_never_submits(host, monkeypatch):
    allow(host)
    original = host.consumer.ledger.claim

    def claim(*args):
        result = original(*args)
        next(iter(host.consumer.grants.values())).expires_at = 0
        return result

    monkeypatch.setattr(host.consumer.ledger, "claim", claim)
    assert direct(host, host.consumer)["error"]["code"] == "grant_expired"
    assert direct(host, fresh_consumer(host))["data"]["state"] == "launch_outcome_unknown"
    assert host.requests == []


def test_unsafe_ledger_permissions_are_refused_not_repaired(host):
    import stat

    allow(host)
    path = host.home / "plugin-data" / PLUGIN_ID / "text-worker-ledger.sqlite3"
    path.chmod(0o644)
    try:
        assert direct(host, host.consumer)["error"]["code"] == "unsafe_storage_file"
        assert stat.S_IMODE(path.stat().st_mode) == 0o644
        assert host.requests == []
    finally:
        path.chmod(0o600)


@pytest.mark.parametrize("target", ["main", "journal"])
def test_ledger_refuses_symlink_or_unsafe_sidecar_without_repair(host, tmp_path, target):
    allow(host)
    path = host.home / "plugin-data" / PLUGIN_ID / "text-worker-ledger.sqlite3"
    if target == "main":
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)

        def restore():
            path.unlink()
            saved.rename(path)
    else:
        saved = path.with_name(path.name + "-journal")
        saved.write_text("synthetic sidecar")
        saved.chmod(0o644)
        restore = saved.unlink
    try:
        assert direct(host, host.consumer)["status"] == "error"
        if target == "main":
            assert path.is_symlink()
        else:
            assert saved.read_text() == "synthetic sidecar"
        assert host.requests == []
    finally:
        restore()


def test_foreign_ledger_schema_is_refused_without_adoption(host):
    import sqlite3

    allow(host)
    path = host.home / "plugin-data" / PLUGIN_ID / "text-worker-ledger.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE foreign_data (value TEXT)")
        conn.execute("INSERT INTO foreign_data VALUES ('keep')")
    assert direct(host, host.consumer)["error"]["code"] == "worker_ledger_schema_mismatch"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT value FROM foreign_data").fetchone()[0] == "keep"
    assert host.requests == []
    # Cleanup only the synthetic added table so fixture unload can revoke normally.
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE foreign_data")


def test_profile_global_key_cannot_cross_session_or_route(host):
    from personal_agent.tasks import TaskError

    allow(host)
    ledger = host.consumer.ledger
    for key in (
        ("other-session", host.live.route, "plan-1"),
        (host.ref.session_id, "other-route", "plan-1"),
    ):
        with pytest.raises(TaskError, match="request_id_scope_conflict"):
            ledger.get(key)
        with pytest.raises(TaskError, match="request_id_scope_conflict"):
            ledger.claim(key, "forged", "0" * 64)
    assert host.requests == []


def test_invalid_terminal_receipt_rolls_back_to_consumed_claim(host):
    from personal_agent.tasks import TaskError

    allow(host)
    ledger = host.consumer.ledger
    key = (host.ref.session_id, host.live.route, "plan-1")
    row = ledger.get(key)
    assert ledger.claim(key, row["context_hash"], current_fingerprint(host))[1]
    with pytest.raises(TaskError, match="worker_ledger_corrupt"):
        ledger.complete(key, {"draft": "must not expose"})
    assert ledger.get(key)["state"] == "claimed"
    assert direct(host, fresh_consumer(host))["data"]["state"] == "launch_outcome_unknown"
    assert host.requests == []


@pytest.mark.parametrize("persisted", [False, True])
@pytest.mark.parametrize("change", ["provider", "model", "endpoint"])
def test_live_and_persisted_drafts_never_cross_changed_model_route(
    host, monkeypatch, persisted, change
):
    allow(host)
    original_result = host.consumer.service.result
    monkeypatch.setattr(
        host.consumer.service,
        "result",
        lambda _: SimpleNamespace(
            terminal_state=SimpleNamespace(value="RUNNING"),
            ready=False,
            summary=None,
            result_hash=None,
        ),
    )
    assert direct(host, host.consumer)["status"] == "ok"
    monkeypatch.setattr(host.consumer.service, "result", original_result)
    assert wait(host).completed
    if persisted:
        assert direct(host, host.consumer, "result")["data"]["draft"]
        reader = fresh_consumer(host)
    else:
        reader = host.consumer
    config_bytes = (host.home / "config.yaml").read_bytes()
    original = (
        host.parent.provider,
        host.parent.model,
        host.parent.base_url,
        host.parent.client.base_url,
    )
    if change == "provider":
        host.parent.provider = "openai"
    elif change == "model":
        host.parent.model = "other-model"
    else:
        endpoint = "https://other-synthetic.invalid/v1"
        host.parent.base_url = endpoint
        host.parent.client.base_url = endpoint
        config = json.loads(config_bytes)
        config["plugins"]["entries"][PLUGIN_ID]["text_workers"]["routes"] = [
            {"provider": PROVIDER, "model": MODEL, "base_url": endpoint}
        ]
        (host.home / "config.yaml").write_text(json.dumps(config))
    try:
        for action in ("result", "launch"):
            reply = direct(host, reader, action)
            assert reply["status"] == "error" and reply["data"] is None
        assert len(host.requests) == 1
    finally:
        (
            host.parent.provider,
            host.parent.model,
            host.parent.base_url,
            host.parent.client.base_url,
        ) = original
        (host.home / "config.yaml").write_bytes(config_bytes)
    result = direct(host, reader, "result")
    assert result["data"]["draft"] == "Draft: clarify the first milestone.", result
    assert len(host.requests) == 1


def test_route_rechecked_after_cached_receipt_read_before_disclosure(host, monkeypatch):
    allow(host)
    direct(host, host.consumer)
    assert wait(host).completed
    assert direct(host, host.consumer, "result")["data"]["draft"]
    original = host.consumer._task

    def read_then_change(task_id):
        task = original(task_id)
        host.parent.model = "changed-during-read"
        return task

    monkeypatch.setattr(host.consumer, "_task", read_then_change)
    try:
        reply = direct(host, host.consumer, "result")
        assert reply["status"] == "error" and reply["data"] is None
    finally:
        host.parent.model = MODEL
    assert len(host.requests) == 1


def test_native_workbench_scoped_pagination_contains_only_request_metadata(host):
    task = allow(host)
    ledger = host.consumer.ledger
    for n in range(12):
        assert consent(host, f"allow {task['id']} 1 page-{n:02}")["status"] == "ok"
    ledger.authorize(("foreign-session", host.live.route, "page-00-foreign"), task["id"], 1, "x", 0)
    ledger.authorize(
        (host.ref.session_id, "foreign-route", "page-01-foreign"), task["id"], 1, "x", 0
    )
    before = database(host.home).read_bytes()
    first = consent(host, "list")["data"]
    assert first["scope_count"] == 13 and len(first["items"]) == 10
    assert first["next_cursor"] == "page-09"
    second = consent(host, "list --after " + first["next_cursor"])["data"]
    assert second["next_cursor"] is None and len(second["items"]) == 3
    items = first["items"] + second["items"]
    assert [item["request_id"] for item in items] == [f"page-{n:02}" for n in range(12)] + [
        "plan-1"
    ]
    for item in items:
        assert set(item) == {"request_id", "task_id", "snapshot_revision", "state"}
        assert item["task_id"] == task["id"] and item["snapshot_revision"] == 1
    assert "Selected details" not in json.dumps(first)
    assert "Task to plan" not in json.dumps(first)
    assert "foreign" not in json.dumps(first) + json.dumps(second)
    assert len(json.dumps(first)) < 8000
    assert database(host.home).read_bytes() == before and host.requests == []
    for verb in ("status", "draft", "stop"):
        response = consent(host, verb + " page-00-foreign")
        assert response["error"]["code"] == "unknown_grant" and response["data"] is None


def test_native_status_and_stop_do_not_launch_or_rearm(host):
    task = allow(host)
    status = consent(host, "status plan-1")["data"]
    assert status["state"] == "authorized"
    assert status["task_id"] == task["id"] and "draft" not in status
    stopped = consent(host, "stop plan-1")["data"]
    assert stopped["state"] == "revoked"
    assert consent(host, "stop plan-1")["data"]["state"] == "revoked"
    assert consent(host, f"allow {task['id']} 1 plan-1")["data"]["state"] == "revoked"
    assert direct(host, host.consumer)["data"]["state"] == "revoked"
    assert host.requests == []


def test_native_stop_unknown_is_not_cancellation_or_retry(host, monkeypatch):
    allow(host)
    ledger = host.consumer.ledger
    key = (host.ref.session_id, host.live.route, "plan-1")
    assert ledger.claim(key, ledger.get(key)["context_hash"], current_fingerprint(host))[1]

    def forbidden(*args, **kwargs):
        raise AssertionError("No host lifecycle call from workbench")

    for name in ("launch_text", "result", "cancel", "status", "wait"):
        monkeypatch.setattr(host.consumer.service, name, forbidden)
    before = ledger.get(key)
    stopped = consent(host, "stop plan-1")["data"]
    assert stopped["state"] == "launch_outcome_unknown"
    assert not stopped["cancellation_available"] and "Cannot cancel" in stopped["notice"]
    assert ledger.get(key) == before
    assert consent(host, "draft plan-1")["data"]["state"] == "launch_outcome_unknown"
    assert host.requests == []


def test_native_human_draft_is_direct_client_output_not_model_turn_or_history(host, monkeypatch):
    from copy import deepcopy

    from gateway.session_commands import execute_command

    task = allow(host)
    host.wire_response["content"] = "Draft: \x1b[31mred\x07\nReview the milestone."
    direct(host, host.consumer)
    assert wait(host).completed
    assert direct(host, host.consumer, "result")["data"]["ready"]
    command(
        host, f"update {task['id']} --expected-revision 1 --title Changed --request-id edit-view"
    )
    before = database(host.home).read_bytes()
    history = deepcopy(host.parent.conversation_history)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Native viewer must not create a model turn or harvest live results")

    monkeypatch.setattr("agent.relay_runtime.RelaySessionCoordinator.begin_turn", forbidden)
    monkeypatch.setattr("model_tools.handle_function_call", forbidden)
    for name in ("launch_text", "result", "cancel", "authorize_text_route"):
        monkeypatch.setattr(host.consumer.service, name, forbidden)
    # Human view is a separate explicit disclosure contract, not model route bypass.
    host.parent.model = "different-model"
    reply = asyncio.run(
        execute_command(
            host.connection,
            host.ref,
            {
                "command": "personal-plan-worker --json draft plan-1",
            },
        )
    )
    assert reply["type"] == "exec" and "prompt" not in reply
    assert "\x1b" not in reply["output"] and "\x07" not in reply["output"]
    assert len(reply["output"]) < 40000
    data = json.loads(reply["output"])["data"]
    assert data["native_client_view"] and data["draft"] == host.wire_response["content"]
    assert data["stale"] and data["snapshot_revision"] == 1 and data["current_revision"] == 2
    assert "result_hash" not in data and "route_fingerprint" not in data
    assert not calls and host.parent.conversation_history == history
    assert database(host.home).read_bytes() == before and len(host.requests) == 1


@pytest.mark.parametrize(
    "text",
    [
        "list --limit 99",
        "list --after",
        "list --after bad/key",
        "status",
        "draft p extra",
        "stop bad/key",
    ],
)
def test_native_workbench_rejects_invalid_arguments(host, text):
    assert consent(host, text)["error"]["code"] == "invalid_request"
    assert host.requests == []


def test_native_stop_latches_before_failed_write(host, monkeypatch):
    allow(host)
    original = host.consumer.ledger.revoke

    def fail(*args):
        raise OSError("Synthetic storage failure")

    monkeypatch.setattr(host.consumer.ledger, "revoke", fail)
    assert consent(host, "stop plan-1")["status"] == "error"
    monkeypatch.setattr(host.consumer.ledger, "revoke", original)
    assert consent(host, "status plan-1")["data"]["state"] == "revoked"
    assert direct(host, host.consumer)["data"]["state"] == "revoked"
    assert host.requests == []


@pytest.mark.parametrize("verb", ["list", "status plan-1", "draft plan-1", "stop plan-1"])
def test_native_workbench_requires_control_and_enabled_configuration(host, verb):
    from hermes_state_runtime import RuntimeStoreError

    allow(host)
    original_actor = host.connection.actor
    host.connection.actor = replace(original_actor, capabilities=frozenset({"session:read"}))
    with pytest.raises(RuntimeStoreError):
        consent(host, verb)
    host.connection.actor = original_actor
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["experimental_text_worker"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    response = consent(host, verb)
    assert response["error"]["code"] == "experimental_worker_disabled"
    assert response["data"] is None and host.requests == []


def test_native_draft_after_reload_and_completed_stop_are_read_only(host):
    allow(host)
    direct(host, host.consumer)
    assert wait(host).completed
    assert direct(host, host.consumer, "result")["data"]["draft"]
    host.manager.discover_and_load(force=True)
    host.consumer = host.manager._plugin_commands["personal-plan-worker"]["handler"].__self__
    before = database(host.home).read_bytes()
    assert consent(host, "status plan-1")["data"]["state"] == "receipt_saved"
    assert consent(host, "stop plan-1")["data"]["state"] == "receipt_saved"
    assert consent(host, "draft plan-1")["data"]["draft"] == "Draft: clarify the first milestone."
    assert database(host.home).read_bytes() == before and len(host.requests) == 1


@pytest.mark.parametrize(
    "column,value",
    [
        ("request_id", "x" * 81),
        ("task_id", "not-a-uuid"),
        ("revision", "wrong-type"),
        ("owner", "bad-owner"),
        ("expires_at", "not-a-date"),
    ],
)
def test_workbench_metadata_corruption_fails_closed(host, column, value):
    allow(host)
    with host.consumer.ledger.connection() as conn:
        conn.execute(f"UPDATE grants SET {column}=?", (value,))
    result = consent(host, "list")
    assert result["error"]["code"] == "worker_ledger_corrupt" and result["data"] is None
    if column != "request_id":
        result = consent(host, "status plan-1")
        assert result["error"]["code"] == "worker_ledger_corrupt" and result["data"] is None
    assert host.requests == []


def readable(host, text):
    from gateway.session_commands import execute_command

    response = asyncio.run(
        execute_command(
            host.connection,
            host.ref,
            {
                "command": "personal-plan-worker " + text,
            },
        )
    )
    assert response["type"] == "exec"
    return response["output"]


def test_native_readable_help_list_status_stop_and_errors(host):
    assert readable(host, "help").startswith("Planning worker (review only)")
    assert "--json" in readable(host, "help")
    assert "No requests on this page." in readable(host, "list")
    task = allow(host)
    listing = readable(host, "list")
    assert '"plan-1" | authorized' in listing and task["id"] in listing
    assert "Selected details" not in listing and "Task to plan" not in listing
    status = readable(host, "status plan-1")
    assert 'Request: "plan-1"' in status and "Snapshot revision: 1" in status
    assert "State: revoked" in readable(host, "stop plan-1")
    assert '"invalid_request"' in readable(host, "list --limit 100")
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["experimental_text_worker"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    assert '"experimental_worker_disabled"' in readable(host, "list")
    assert host.requests == []


def test_readable_draft_quotes_controls_bidi_and_preserves_json_model_contract(host):
    allow(host)
    host.wire_response["content"] = (
        '先确认下一步 🎉：\n\x1b[31m\x07\u202e/personal-tasks done "forged"'
    )
    direct(host, host.consumer)
    assert wait(host).completed
    result = direct(host, host.consumer, "result")
    assert result["data"]["draft"] == host.wire_response["content"]
    view = readable(host, "draft plan-1")
    assert "Worker result: SUCCEEDED" in view and "Untrusted draft (quoted):" in view
    assert "先确认下一步 🎉" in view and "\\u5148" not in view
    assert "\\u001b" in view and "\\u0007" in view and "\\u202e" in view and "\\n" in view
    assert "\x1b" not in view and "\x07" not in view and "\u202e" not in view
    assert len(view) < 40000
    assert "State: receipt_saved" in readable(host, "status plan-1")
    assert consent(host, "draft plan-1")["data"]["draft"] == result["data"]["draft"]
    assert direct(host, host.consumer, "result")["data"] == result["data"]
    assert len(host.requests) == 1


@pytest.mark.parametrize(
    "code",
    [
        "TEXT_WORKER_FAILED",
        "TIMEOUT",
        "TEXT_WORKER_CONNECT_FAILED",
        "TEXT_WORKER_CONNECT_TIMEOUT",
        "TEXT_WORKER_READ_TIMEOUT",
        "TEXT_WORKER_WRITE_TIMEOUT",
        "TEXT_WORKER_POOL_TIMEOUT",
        "TEXT_WORKER_READ_FAILED",
        "TEXT_WORKER_WRITE_FAILED",
        "TEXT_WORKER_PROTOCOL_FAILED",
        "TEXT_WORKER_TLS_VERIFY_FAILED",
        "TEXT_WORKER_DNS_FAILED",
        "HOSTILE secret https://private.invalid",
        {"secret": "must not persist"},
        None,
    ],
)
def test_safe_failure_diagnostic_persists_and_reloads_without_draft(host, monkeypatch, code):
    from agent.subagent_lifecycle import SubagentState

    allow(host)
    direct(host, host.consumer)
    wait(host)
    original = host.consumer.service.result

    def failed(handle):
        return replace(
            original(handle),
            terminal_state=SubagentState.FAILED,
            summary="HOSTILE failed draft",
            error_classification=code,
            usage_metadata={"api_calls": 1},
        )

    monkeypatch.setattr(host.consumer.service, "result", failed)
    result = direct(host, host.consumer, "result")
    assert result["status"] == "ok", result
    data = result["data"]
    expected = (
        code
        if type(code) is str
        and code
        in {
            "TEXT_WORKER_FAILED",
            "TIMEOUT",
            "TEXT_WORKER_CONNECT_FAILED",
            "TEXT_WORKER_CONNECT_TIMEOUT",
            "TEXT_WORKER_READ_TIMEOUT",
            "TEXT_WORKER_WRITE_TIMEOUT",
            "TEXT_WORKER_POOL_TIMEOUT",
            "TEXT_WORKER_READ_FAILED",
            "TEXT_WORKER_WRITE_FAILED",
            "TEXT_WORKER_PROTOCOL_FAILED",
            "TEXT_WORKER_TLS_VERIFY_FAILED",
            "TEXT_WORKER_DNS_FAILED",
        }
        else "TEXT_WORKER_FAILED"
    )
    assert data["diagnostic"] == {"code": expected, "submission_attempts": 1}
    assert data["draft"] is None and data["state"] == "FAILED"
    assert "HOSTILE" not in json.dumps(data)
    host.manager.discover_and_load(force=True)
    host.consumer = host.manager._plugin_commands["personal-plan-worker"]["handler"].__self__
    assert direct(host, host.consumer, "result")["data"] == data
    view = readable(host, "draft plan-1")
    assert expected in view and "No draft" in view
    assert (
        "No retry or key reset was performed. Do not use a new key to retry an uncertain outcome."
    ) in view
    assert "Not proof of provider execution, charges or delivery" in view
    assert len(host.requests) == 1


@pytest.mark.parametrize("count", [0, 1, None, True, False, -1, 2, "1", [], 1.0])
def test_success_diagnostic_normalizes_local_callback_count(host, monkeypatch, count):
    allow(host)
    direct(host, host.consumer)
    wait(host)
    original = host.consumer.service.result
    monkeypatch.setattr(
        host.consumer.service,
        "result",
        lambda handle: replace(
            original(handle), error_classification="HOSTILE", usage_metadata={"api_calls": count}
        ),
    )
    result = direct(host, host.consumer, "result")["data"]
    assert result["diagnostic"] == {
        "code": None,
        "submission_attempts": count if type(count) is int and count in (0, 1) else None,
    }
    assert consent(host, "draft plan-1")["data"]["diagnostic"] == result["diagnostic"]


def rewrite_diagnostic(host, diagnostic, *, remove=False):
    import hashlib

    ledger = host.consumer.ledger
    with ledger.connection() as conn:
        value = json.loads(conn.execute("SELECT result FROM grants").fetchone()[0])
        if remove:
            value["data"].pop("diagnostic")
        else:
            value["data"]["diagnostic"] = diagnostic
        encoded = json.dumps(value["data"], ensure_ascii=True, sort_keys=True)
        value["sha256"] = hashlib.sha256(
            (value["route_fingerprint"] + encoded).encode("ascii")
        ).hexdigest()
        conn.execute("UPDATE grants SET result=?", (json.dumps(value),))


def test_old_receipt_without_diagnostic_remains_readable_without_rearming(host):
    allow(host)
    direct(host, host.consumer)
    wait(host)
    expected = direct(host, host.consumer, "result")["data"]
    expected.pop("diagnostic")
    rewrite_diagnostic(host, None, remove=True)
    other = fresh_consumer(host)
    assert direct(host, other, "result")["data"] == expected
    assert direct(host, other)["data"] == expected
    assert "diagnostic" not in consent(host, "draft plan-1")["data"]
    assert len(host.requests) == 1


@pytest.mark.parametrize(
    "diagnostic",
    [
        None,
        [],
        {},
        {"code": None},
        {"code": None, "submission_attempts": True},
        {"code": None, "submission_attempts": 2},
        {"code": None, "submission_attempts": "1"},
        {"code": None, "submission_attempts": None, "secret": "extra"},
        {"code": [], "submission_attempts": 1},
        {"code": "HOSTILE", "submission_attempts": 1},
        {"code": "TEXT_WORKER_FAILED", "submission_attempts": 1},
        {"code": "CANCELLED", "submission_attempts": 1},
    ],
)
def test_corrupt_diagnostic_even_with_recomputed_hash_is_rejected(host, diagnostic):
    allow(host)
    direct(host, host.consumer)
    wait(host)
    assert direct(host, host.consumer, "result")["data"]["state"] == "SUCCEEDED"
    rewrite_diagnostic(host, diagnostic)
    other = fresh_consumer(host)
    for action in ("result", "launch"):
        result = direct(host, other, action)
        assert result["error"]["code"] == "worker_ledger_corrupt" and result["data"] is None
    assert consent(host, "draft plan-1")["error"]["code"] == "worker_ledger_corrupt"
    assert len(host.requests) == 1


@pytest.mark.parametrize(
    "state,code,expected",
    [
        ("SUCCEEDED", {"hostile": "secret"}, None),
        ("CANCELLED", "HOSTILE", "CANCELLED"),
        ("FAILED", "CANCELLED", "TEXT_WORKER_FAILED"),
        ("FAILED", "TIMEOUT", "TIMEOUT"),
        ("INTERRUPTED", "TEXT_WORKER_READ_FAILED", "TEXT_WORKER_FAILED"),
    ],
)
def test_diagnostic_state_alignment_and_non_dict_usage(host, state, code, expected):
    import importlib

    module = importlib.import_module(type(host.consumer.ledger).__module__)
    result = SimpleNamespace(
        terminal_state=SimpleNamespace(value=state),
        error_classification=code,
        usage_metadata=[("api_calls", 1)],
    )
    diagnostic = module.terminal_diagnostic(result)
    assert diagnostic == {"code": expected, "submission_attempts": None}
    assert module.valid_diagnostic(state, diagnostic)
    assert module.DIAGNOSTIC_EXPLANATIONS["CANCELLED"] == (
        "The local worker result was cancelled; remote cancellation is not confirmed."
    )
    assert not module.valid_diagnostic(state, {"code": ["HOSTILE"], "submission_attempts": 1})
    for other in ("SUCCEEDED", "CANCELLED", "FAILED", "INTERRUPTED"):
        if other == "SUCCEEDED" and state != other:
            assert not module.valid_diagnostic(other, diagnostic)
        if other == "CANCELLED" and state != other:
            assert not module.valid_diagnostic(other, diagnostic)
