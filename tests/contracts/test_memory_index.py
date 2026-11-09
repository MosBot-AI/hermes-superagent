"""Native operator maintenance on the pinned host, no model or deployment."""

import sqlite3
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_session_memory_tools as model

native = memory.native
host = memory.host


def test_operator_status_diagnosis_rebuild_and_config_preservation(host):
    before_config = (host.home / "config.yaml").read_bytes()
    record = memory.command(host, 'remember "中文 searchable" --request-id seed')["data"]
    path = memory.database(host.home)
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM memory_fts")
    status = memory.command(host, "index-status")
    assert status["status"] == "ok", status
    assert status["data"]["missing_records"] == 1
    result = memory.command(host, "index-rebuild --expected-watermark 1")
    assert result["data"]["index_current"] and result["data"]["rebuilt"] and not result["replayed"]
    assert memory.command(host, "index-rebuild --expected-watermark 1")["data"]["index_current"]
    found = memory.command(host, "search-terms searchable")["data"]["items"]
    assert [r["record_id"] for r in found] == [record["record_id"]]
    assert (host.home / "config.yaml").read_bytes() == before_config


@pytest.mark.parametrize("command", ["index-status", "index-rebuild --expected-watermark 0"])
def test_missing_store_never_initialized(host, command):
    result = memory.command(host, command)
    assert result["error"]["code"] == "memory_store_missing"
    assert not memory.database(host.home).exists()


def test_revoked_actor_denied_maintenance_after_status(host):
    from hermes_state_runtime import RuntimeStoreError

    memory.command(host, 'remember "test" --request-id seed')
    assert memory.command(host, "index-status")["status"] == "ok"
    before = memory.database(host.home).read_bytes()
    host.connection.actor = replace(host.connection.actor, subject="foreign")
    with pytest.raises(RuntimeStoreError):
        memory.command(host, "index-rebuild --expected-watermark 1")
    assert memory.database(host.home).read_bytes() == before


def test_model_schema_has_no_index_maintenance_actions(native, monkeypatch):
    import json

    import test_local_conversation_tasks as local

    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][memory.PLUGIN_ID]["settings"].update(
        local_memory=True, memory_model_tools=True, local_model_tools=True
    )
    (home / "config.yaml").write_text(json.dumps(config))
    monkeypatch.setattr(local, "load", lambda manager: manager.discover_and_load())
    host = local.make_host(home, manager)
    model.activate(host)
    with model.turn(host):
        for action in ("index_status", "index_rebuild"):
            assert model.call(host, {"action": action})["error"]["code"] == "invalid_request"
    assert not memory.database(home).exists()
