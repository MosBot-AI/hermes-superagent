"""Native local bridge batching with synthetic effects, not connector-wide authority.

Model client/metadata endpoints are doubled, caching/compression/trajectory saving
are disabled, and the discovered fixture supplies synthetic policy/effects.
Real AIAgent initialization,
local batch expansion, segment planning, admission, hooks and registry dispatch
run unchanged. Retries are explicitly emitted by the synthetic model endpoint,
not selected by a real model. The connector-only case substitutes a gateway
client endpoint while preserving native availability and per-item admission.
No remote account or external write is exercised.
"""

import json
import shutil
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "batch_worker_probe"


def response(calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="" if calls else "done", tool_calls=calls),
                finish_reason="tool_calls" if calls else "stop",
            )
        ],
        model="test/model",
        usage=None,
    )


def batch(items, call_id="batch"):
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(
            name="tool_call",
            arguments=json.dumps(
                {"calls": [{"name": "batch_worker_probe", "arguments": item} for item in items]}
            ),
        ),
    )


@pytest.fixture(params=["primary", "delegated-child"])
def runtime(tmp_path, monkeypatch, request):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("Offline contract attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_network)
    home = tmp_path / "home"
    shutil.copytree(
        FIXTURE,
        home / "plugins" / "batch-worker-probe",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "plugins": {"enabled": ["batch-worker-probe"], "hook_callback_timeout": 0},
                "delegation": {"backend": "default"},
                "model": {"context_length": 128000},
            }
        ),
        encoding="utf-8",
    )
    from hermes_cli.plugins import get_plugin_manager
    from run_agent import AIAgent

    manager = get_plugin_manager()
    manager.discover_and_load()
    loaded = manager._plugins["batch-worker-probe"]
    assert loaded.enabled and loaded.error is None
    monkeypatch.setattr("agent.process_bootstrap.OpenAI", MagicMock())
    monkeypatch.setattr("agent.model_metadata.fetch_model_metadata", lambda *a, **k: {})
    agent = AIAgent(
        model="test/model",
        api_key="synthetic-not-a-credential",
        base_url="http://127.0.0.1:1/v1",
        enabled_toolsets=["batch_worker_probe"],
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        max_iterations=4,
    )
    parent = agent
    if request.param == "delegated-child":
        from tools.delegate_tool import _build_child_agent

        agent = _build_child_agent(
            task_index=0,
            goal="Run synthetic fixture calls",
            context=None,
            toolsets=["batch_worker_probe", "terminal"],
            model=None,
            max_iterations=4,
            task_count=1,
            parent_agent=parent,
        )
        assert agent._delegate_depth == 1
        assert "batch_worker_probe" in agent.enabled_toolsets
        assert "terminal" not in agent.enabled_toolsets
    agent.client = MagicMock()
    agent._cached_system_prompt = "Exercise synthetic batch items."
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    agent.save_trajectories = False
    try:
        yield agent, loaded.module
    finally:
        agent.close()
        if parent is not agent:
            parent.close()
        manager.unload()


def tool_results(result):
    return [m for m in result["messages"] if m["role"] == "tool"]


def test_native_local_batch_veto_preserves_other_items_and_pairing(runtime):
    agent, probe = runtime
    agent.client.chat.completions.create.side_effect = [
        response(
            [
                batch(
                    [
                        {"item": "first"},
                        {"item": "denied"},
                        {"item": "last"},
                    ]
                )
            ]
        ),
        response(),
    ]
    result = agent.run_conversation("Run the synthetic local batch.")
    assert result["final_response"] == "done"
    assert probe.EFFECTS == ["first", "last"]
    assert [args["item"] for args, _ in probe.HOOKS] == ["first", "denied", "last"]
    assert {session for _, session in probe.HOOKS} == {agent.session_id}
    rows = tool_results(result)
    assert len(rows) == 3
    assert "synthetic item veto" in rows[1]["content"]
    assistant = next(m for m in result["messages"] if m.get("tool_calls"))
    ids = [c["id"] for c in assistant["tool_calls"]]
    assert len(set(ids)) == 3
    assert [row["tool_call_id"] for row in rows] == ids


def test_native_local_batch_uncertain_item_retry_is_not_deduplicated(runtime):
    agent, probe = runtime
    items = [{"item": "uncertain", "lose_response": True}, {"item": "denied"}]
    agent.client.chat.completions.create.side_effect = [
        response([batch(items)]),
        response([batch(items, "retry")]),
        response(),
    ]
    result = agent.run_conversation("Exercise a synthetic response-loss retry.")
    assert result["final_response"] == "done"
    assert probe.EFFECTS == ["uncertain", "uncertain"]
    assert [args["item"] for args, _ in probe.HOOKS] == [
        "uncertain",
        "denied",
        "uncertain",
        "denied",
    ]
    rows = tool_results(result)
    assert len(rows) == 4
    assert all("synthetic response lost after effect" in rows[i]["content"] for i in (0, 2))
    assert all("synthetic item veto" in rows[i]["content"] for i in (1, 3))


def test_native_local_batch_retry_rechecks_changed_fixture_policy(runtime):
    """A new model turn uses the current callback, not the prior item's allow result.

    Mutating this test plugin's in-memory policy is not persistent revocation.
    """
    agent, probe = runtime
    items = [{"item": "first"}, {"item": "denied"}]
    replies = iter([response([batch(items)]), response([batch(items, "retry")]), response()])
    calls = 0

    def model_endpoint(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            assert probe.EFFECTS == ["first"]
            probe.DENIED.add("first")
        return next(replies)

    agent.client.chat.completions.create.side_effect = model_endpoint
    result = agent.run_conversation("Retry synthetic items after a fixture policy change.")
    assert result["final_response"] == "done"
    assert probe.EFFECTS == ["first"]
    assert [args["item"] for args, _ in probe.HOOKS] == [
        "first",
        "denied",
        "first",
        "denied",
    ]
    rows = tool_results(result)
    assert len(rows) == 4
    assert all("synthetic item veto" in row["content"] for row in rows[1:])


@pytest.mark.parametrize("runtime", ["primary"], indirect=True)
def test_connector_only_batch_veto_partial_result_and_explicit_retry(runtime, monkeypatch):
    """Real connector dispatch/availability and plugin admission; offline client endpoint.

    This does not exercise ToolGatewayClient transport retries or server deduplication.
    The client records effects independently and omits the uncertain result slot.
    """
    from model_tools import handle_function_call
    from tools.connectors.gateway.config import connectors_available

    agent, probe = runtime
    effects = []
    acquired = []

    class OfflineClient:
        def schemas(self, _names):
            return {"schemas": {}}

        def execute(self, plans, **_kwargs):
            effects.extend(plan.arguments["item"] for plan in plans)
            if plans[0].arguments["item"] == "uncertain":
                return []
            return [{"data": {"effect": plan.arguments["item"]}} for plan in plans]

    def client_endpoint(call):
        acquired.append(call.tool_call_id)
        return OfflineClient()

    monkeypatch.setattr("tools.connectors.gateway.bridge._default_client_factory", client_endpoint)
    assert connectors_available(), "isolated uncredentialed guest discovery should be available"
    calls = [
        {"name": "connectors__batchfixture__effect", "arguments": {"item": item}}
        for item in ("first", "denied", "uncertain")
    ]
    results = []
    for call_id in ("connector-batch", "connector-retry"):
        results.append(
            json.loads(
                handle_function_call(
                    "tool_call",
                    {"calls": calls},
                    tool_call_id=call_id,
                    session_id=agent.session_id,
                    enabled_toolsets=["connections"],
                )
            )
        )
    assert effects == ["first", "uncertain", "first", "uncertain"]
    assert acquired == [
        "connector-batch#0",
        "connector-batch#2",
        "connector-retry#0",
        "connector-retry#2",
    ]
    assert [args["item"] for args, _ in probe.HOOKS] == [
        "first",
        "denied",
        "uncertain",
        "first",
        "denied",
        "uncertain",
    ]
    for result in results:
        assert [entry["index"] for entry in result["results"]] == [0, 1, 2]
        assert result["results"][0]["response"] == {"effect": "first"}
        assert "synthetic item veto" in result["results"][1]["error"]["message"]
        assert result["results"][2]["error"]["code"] == "PROVIDER_ERROR"
