"""Installed native package retains internal-only intent metadata, never authority."""

import importlib
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from test_local_task_cli import PLUGIN_ID, configure, entry, invoke
from test_local_task_cli import native as native


def api(manager):
    module = manager._plugins[PLUGIN_ID].module
    return importlib.import_module(module.__name__ + ".personal_agent.action_intents")


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_normal_load_does_not_activate_or_persist_intents(native, capsys, mode):
    home, manager = native
    configure(home, mode)
    command = entry(manager)
    _, status = invoke(command, capsys, "status")
    assert status["enrollment_policy"]["production_adapter_enabled"] is False
    assert not (home / "plugin-data").exists()
    assert set(manager._plugin_commands) == {"personal-access"}
    assert set(manager._cli_commands) == {"personal-agent"}
    assert not hasattr(api(manager).ActionIntentStore, "approve")
    assert not hasattr(api(manager).ActionIntentStore, "execute")


def test_internal_metadata_survives_reload_without_activating_host(native, tmp_path, capsys):
    _, manager = native
    command = entry(manager)
    module = api(manager)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    spec = {
        "owner_id": "prospective-owner",
        "profile_id": "synthetic-profile",
        "request_id": "synthetic-request",
        "operation": "synthetic.send",
        "policy_revision": 1,
        "epoch": 0,
        "resource_revision": 1,
        "expires_at": now + timedelta(minutes=10),
        "target": b"synthetic-destination",
        "payload": b"synthetic-private-payload",
    }
    key = {name: spec[name] for name in ("owner_id", "profile_id", "request_id")}
    path = tmp_path / "isolated-internal.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    store = module.ActionIntentStore(connection, clock=lambda: now)
    store.initialize()
    store.prepare(spec)
    cancelled = store.cancel(key, expected_revision=1)
    connection.close()
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        restarted = module.ActionIntentStore(connection, clock=lambda: now)
        restarted.initialize()
        assert restarted.prepare(spec) == cancelled
        assert restarted.inspect(key)["state"] == "cancelled"
    finally:
        connection.close()
    assert b"synthetic-private-payload" not in path.read_bytes()
    assert b"synthetic-destination" not in path.read_bytes()
    _, status = invoke(command, capsys, "status")
    assert status["enrollment_policy"]["activation_supported"] is False
    _, diagnostic = invoke(command, capsys, "access")
    assert diagnostic["decision"] == "deny"
    assert diagnostic["protected_reads_enabled"] is False
