"""Real pinned Hermes discovery/dispatch against an offline SDK stdio server.

Session-expiry tests inject only the post-RPC error boundary: stdio cannot emit
an HTTP transport 404. Discovery, sessions, reconnect and replay remain real.
These tests establish fixture behavior, not connector isolation or live safety.
"""

import importlib.metadata
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_local_task_cli import configure, entry
from test_local_task_cli import native as native

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "tests/fixtures/synthetic_connectors/stdio.py"
SERVER = "synthetic_contract"
SPEC = {
    "account_ref": "account-a",
    "operation": "message.send",
    "target": "recipient-a@fixture.invalid",
    "payload": "SYNTHETIC_BODY_A",
    "effect_key": "effect-1",
    "prepared_version": 1,
}


def dispatch(tool, args=None):
    from model_tools import handle_function_call
    from tools.mcp_tool_schema import mcp_prefixed_tool_name

    return json.loads(handle_function_call(mcp_prefixed_tool_name(SERVER, tool), args or {}))


def payload(tool, args=None):
    result = dispatch(tool, args)
    assert "error" not in result, result
    value = result["result"]
    return json.loads(value) if isinstance(value, str) else value


def effect_count(database):
    # Independent durable observation, not a server-reported count or receipt.
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT count(*) FROM effects").fetchone()[0]


@pytest.fixture
def connector(tmp_path, monkeypatch, request):
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    home = tmp_path / "hermes-home"
    home.mkdir()
    os_home = tmp_path / "os-home"
    os_home.mkdir()
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(os_home))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    monkeypatch.setattr(Path, "home", lambda: os_home)
    database = tmp_path / "remote.sqlite3"
    config = {
        "plugins": {"enabled": []},
        "delegation": {"backend": "default"},
        "mcp_servers": {
            SERVER: {
                "command": sys.executable,
                "args": [
                    str(FACADE),
                    "--database",
                    str(database),
                    "--mode",
                    getattr(request, "param", "normal"),
                ],
                "timeout": 20,
                "trust": "full",
            }
        },
    }
    (home / "config.yaml").write_text(json.dumps(config))
    try:
        names = discover_mcp_tools()
        assert any("fixture_prepare" in name for name in names), names
        yield database, names
    finally:
        shutdown_mcp_servers()


def test_sdk_and_host_are_exact_pins():
    import tomllib

    import tools.mcp_tool

    host = Path(tools.mcp_tool.__file__).resolve().parents[1]
    expected = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    actual = subprocess.run(
        ["git", "-C", str(host), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    assert actual == expected
    project = tomllib.loads((host / "pyproject.toml").read_text())
    pin = next(
        item
        for item in project["project"]["optional-dependencies"]["mcp"]
        if item.startswith("mcp==")
    )
    assert importlib.metadata.version("mcp") == pin.split("==")[1]


def test_discovery_and_model_dispatch_reach_real_stdio(connector):
    from tools.mcp_tool_handlers import _tool_is_read_only
    from tools.registry import registry

    database, names = connector
    for name in names:
        assert registry.get_entry(name) is not None
    assert _tool_is_read_only(SERVER, "fixture_read") is True
    assert _tool_is_read_only(SERVER, "fixture_execute") is False
    payload("fixture_describe")
    payload("fixture_health")
    payload("fixture_read", {"request": {"account_ref": "account-a", "cursor": 0, "limit": 4}})
    prepared = payload("fixture_prepare", {"spec": SPEC})
    assert effect_count(database) == 0
    payload("fixture_execute", {"envelope": prepared})
    assert effect_count(database) == 1
    payload("fixture_execute", {"envelope": prepared})
    assert effect_count(database) == 1
    reconciled = payload("fixture_reconcile", {"envelope": prepared})
    assert reconciled["status"] == "accepted"
    assert reconciled["delivered"] is False
    assert effect_count(database) == 1
    cancelled = payload(
        "fixture_prepare", {"spec": {**SPEC, "effect_key": "effect-cancel-before-send"}}
    )
    result = payload("fixture_cancel", {"envelope": cancelled})
    assert result["status"] == "cancel_requested"
    assert result["reason"] == "unsupported"
    assert effect_count(database) == 1


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ('{"account_ref":"account-a","account_ref":"account-b"}', "duplicate_key"),
        ('{"account_ref":', "invalid_json"),
        (json.dumps({**SPEC, "unknown_field": "synthetic"}), "invalid_fields"),
        ('{"nested":' + "[" * 12 + "0" + "]" * 12 + "}", "input_too_deep"),
        (json.dumps({**SPEC, "payload": "X" * 9000}), "input_too_large"),
    ],
    ids=["duplicate", "malformed", "unknown-field", "deep", "oversized"],
)
def test_raw_fixture_json_rejection_through_native_dispatch(connector, raw, error):
    """Validate the raw fixture-input string, NOT outer JSON-RPC duplicate handling.

    The SDK already decoded the surrounding arguments object before this fixture
    sees it. Only the explicitly supplied raw string retains duplicate keys.
    """
    database, _ = connector
    canonical_spec = json.dumps(SPEC, sort_keys=True, separators=(",", ":"))
    prepared = payload("fixture_prepare_json", {"raw": canonical_spec})
    assert prepared["effect_key"] == SPEC["effect_key"]
    assert effect_count(database) == 0
    rejected = dispatch("fixture_prepare_json", {"raw": raw})
    assert rejected["error"] == error
    assert effect_count(database) == 0


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [("fixture_lying_read", {}), ("fixture_impure_prepare", {"spec": SPEC})],
)
def test_native_read_only_hint_and_prepare_name_do_not_enforce_purity(connector, tool, arguments):
    from tools.mcp_tool_handlers import _tool_is_read_only

    database, _ = connector
    assert _tool_is_read_only(SERVER, tool) is True
    assert effect_count(database) == 0
    payload(tool, arguments)
    assert effect_count(database) == 1


@pytest.mark.parametrize(
    ("connector", "expected_effects"),
    [("precommit_loss", 0), ("postcommit_loss", 1)],
    indirect=["connector"],
)
def test_real_stdio_death_is_unknown_without_replay(connector, expected_effects):
    from tools.mcp_tool_discovery import discover_mcp_tools
    from tools.mcp_tool_lifecycle import shutdown_mcp_servers

    database, _ = connector
    prepared = payload("fixture_prepare", {"spec": SPEC})
    result = dispatch("fixture_execute", {"envelope": prepared})
    assert result.get("outcome_uncertain") is True, result
    assert effect_count(database) == expected_effects
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM attempts WHERE operation='execute'"
            ).fetchone()[0]
            == 1
        )
    # A fresh process must reconcile persisted state after response loss.
    shutdown_mcp_servers()
    assert discover_mcp_tools()
    reconciled = payload("fixture_reconcile", {"envelope": prepared})
    assert reconciled["status"] == ("accepted" if expected_effects else "unknown_outcome")
    if expected_effects:
        assert reconciled["delivered"] is False
    assert effect_count(database) == expected_effects


@pytest.mark.parametrize(
    ("tool", "expected_effects"),
    [("fixture_session_write", 1), ("fixture_session_lying_read", 2)],
)
def test_session_expiry_boundary_obeys_declaration_not_real_effects(
    connector, monkeypatch, tool, expected_effects
):
    from tools import mcp_tool_handlers as handlers

    database, _ = connector
    original = handlers._call_tool_racing_stdio_death
    calls = []

    async def lose_first_response(server, server_name, tool_name, args, progress_callback=None):
        result = await original(server, server_name, tool_name, args, progress_callback)
        if tool_name == tool:
            calls.append(tool_name)
            if len(calls) == 1:
                # Inject AFTER a real SDK response and durable synthetic write.
                # This is NOT evidence of actual HTTP session expiry over stdio.
                raise RuntimeError("HTTP 404: session not found (synthetic boundary)")
        return result

    monkeypatch.setattr(handlers, "_call_tool_racing_stdio_death", lose_first_response)
    result = dispatch(tool)
    assert effect_count(database) == expected_effects
    assert len(calls) == expected_effects
    if expected_effects == 1:
        assert result.get("outcome_uncertain") is True, result
    else:
        assert "error" not in result, result
        assert handlers._tool_is_read_only(SERVER, tool) is True


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_normal_plugin_load_never_exposes_fixture_or_execution(native, capsys, mode):
    from test_local_task_cli import invoke

    home, manager = native
    configure(home, mode)
    command = entry(manager)
    _, status = invoke(command, capsys, "status")
    assert status["enrollment_policy"]["production_adapter_enabled"] is False
    loaded = manager._plugins["hermes-personal-agent"]
    assert all("fixture" not in name for name in loaded.tools_registered)
    assert not (home / "plugin-data").exists()
    assert not list(home.rglob("*.sqlite3"))
    module = __import__(
        loaded.module.__name__ + ".personal_agent.action_intents", fromlist=["ActionIntentStore"]
    )
    assert not hasattr(module.ActionIntentStore, "approve")
    assert not hasattr(module.ActionIntentStore, "execute")
