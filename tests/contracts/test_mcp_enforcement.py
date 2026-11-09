"""Actual host MCP admission with offline SDK stdio and durable synthetic effects.

The approval UI is a test double, never the admission gate or wrapper. A direct
registry call bypasses plugin hooks but retains the native MCP trust gate. These
contracts prove neither production owner authorization nor transport containment.
"""

import json
import os
import sqlite3
from pathlib import Path

import pytest
from test_enforcement_boundaries import PLUGIN_ID, stage_plugin
from test_synthetic_connectors import SERVER, SPEC, dispatch, effect_count, payload
from test_synthetic_connectors import connector as connector


def execute_attempts(database):
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT count(*) FROM attempts WHERE operation='execute'"
        ).fetchone()[0]


def direct_dispatch(tool, args):
    from tools.mcp_tool_schema import mcp_prefixed_tool_name
    from tools.registry import registry

    return json.loads(registry.dispatch(mcp_prefixed_tool_name(SERVER, tool), args))


@pytest.fixture
def guarded_connector(connector, monkeypatch):
    from hermes_cli.plugins import get_plugin_manager
    from tools.mcp_tool_schema import mcp_prefixed_tool_name

    home = Path(os.environ["HERMES_HOME"])
    stage_plugin(home)
    config_path = home / "config.yaml"
    config = json.loads(config_path.read_text())
    config["plugins"] = {"enabled": [PLUGIN_ID], "hook_callback_timeout": 0}
    config_path.write_text(json.dumps(config))
    manager = get_plugin_manager()
    manager.discover_and_load(force=True)
    loaded = manager._plugins[PLUGIN_ID]
    assert loaded.enabled and loaded.error is None
    module = loaded.module
    assert Path(module.__file__).is_relative_to(home / "plugins" / PLUGIN_ID)
    # Keep the real registered callback; retarget its fixture-only name filter.
    monkeypatch.setattr(module, "TOOL_NAME", mcp_prefixed_tool_name(SERVER, "fixture_execute"))
    try:
        yield connector, module
    finally:
        manager.unload()


@pytest.mark.parametrize(
    ("mode", "error"),
    [("block", "synthetic policy denial"), ("exception", "synthetic policy exception")],
)
def test_registered_plugin_blocks_mcp_but_direct_registry_bypasses_plugin(
    guarded_connector, mode, error
):
    (database, _), probe = guarded_connector
    prepared = payload("fixture_prepare", {"spec": SPEC})
    args = {"envelope": prepared}
    probe.HOOK_MODE = mode
    refused = dispatch("fixture_execute", args)
    assert error in refused["error"]
    assert probe.HOOK_CALLS == [args]
    assert probe.MIDDLEWARE_CALLS == []
    assert execute_attempts(database) == 0
    assert effect_count(database) == 0

    # Scoped counterexample: trust: full, same registered MCP handler and args,
    # real SDK transport. Registry dispatch does not inherit plugin admission.
    result = direct_dispatch("fixture_execute", args)
    assert "error" not in result, result
    assert execute_attempts(database) == 1
    assert effect_count(database) == 1
    assert probe.HOOK_CALLS == [args]
    assert probe.MIDDLEWARE_CALLS == []
    assert probe.HANDLER_CALLS == []


@pytest.fixture
def untrusted_connector(connector):
    from tools import mcp_tool
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_handlers import _trust_granted
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers
    from tools.mcp_tool_scope import _server_key

    # Re-register via actual configuration/discovery, not a patched policy map.
    shutdown_mcp_servers()
    config_path = Path(os.environ["HERMES_HOME"]) / "config.yaml"
    config = json.loads(config_path.read_text())
    config["mcp_servers"][SERVER]["trust"] = "untrusted"
    config_path.write_text(json.dumps(config))
    assert discover_mcp_tools()
    assert mcp_tool._server_trust_levels[_server_key(SERVER)] == "untrusted"
    assert not _trust_granted(SERVER, "fixture_execute")
    yield connector


@pytest.mark.parametrize("route", ["model", "registry"])
@pytest.mark.parametrize("answer", ["deny", "cancel", "exception"])
def test_native_untrusted_gate_stops_before_transport(
    untrusted_connector, monkeypatch, route, answer
):
    from tools import approval_prompt, mcp_tool_handlers

    database, _ = untrusted_connector
    prepared = payload("fixture_prepare", {"spec": SPEC})
    prompts, acquisitions = [], []
    original = mcp_tool_handlers._acquire_call_server

    def observe_acquisition(*args, **kwargs):
        acquisitions.append(args)
        return original(*args, **kwargs)

    def answer_prompt(message, description, **kwargs):
        prompts.append((message, description, kwargs))
        if answer == "exception":
            raise RuntimeError("synthetic approval endpoint unavailable")
        return answer

    monkeypatch.setattr(mcp_tool_handlers, "_acquire_call_server", observe_acquisition)
    monkeypatch.setattr(approval_prompt, "request_elicitation_consent", answer_prompt)
    call = dispatch if route == "model" else direct_dispatch
    result = call("fixture_execute", {"envelope": prepared})
    expected = "approval system was unavailable" if answer == "exception" else "did not approve"
    assert expected in result["error"]
    assert len(prompts) == 1
    assert prompts[0][2]["surface"] == f"mcp-trust/{SERVER}"
    assert prompts[0][2]["remember_key"] == f"mcp:{SERVER}/fixture_execute"
    assert acquisitions == []
    assert execute_attempts(database) == 0
    assert effect_count(database) == 0


def test_untrusted_read_only_hint_is_not_effect_level_authorization(
    untrusted_connector, monkeypatch
):
    from tools import approval_prompt, mcp_tool_handlers

    database, _ = untrusted_connector
    prompts = []

    def deny_prompt(*args, **kwargs):
        prompts.append((args, kwargs))
        return "deny"

    monkeypatch.setattr(approval_prompt, "request_elicitation_consent", deny_prompt)
    assert mcp_tool_handlers._tool_is_read_only(SERVER, "fixture_lying_read") is True
    assert effect_count(database) == 0
    payload("fixture_lying_read")
    assert prompts == []
    assert effect_count(database) == 1
