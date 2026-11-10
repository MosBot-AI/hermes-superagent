"""Snapshot create/inspect under native trusted-local command admission."""

import json
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_session_memory_tools as model

native = memory.native
host = memory.host


def directory(home):
    return memory.database(home).parent / "snapshots"


def test_native_snapshot_create_inspect_without_provider_or_config_change(host):
    before = (host.home / "config.yaml").read_bytes()
    saved = memory.command(host, 'remember "私密记录" --request-id seed')["data"]
    result = memory.command(host, "snapshot-create before")
    assert result["status"] == "ok" and result["data"]["records"] == 1
    assert result["data"]["restorable"] is False
    assert "Plaintext" in result["data"]["notice"]
    memory.command(host, f"forget {saved['record_id']} --expected-revision 1 --request-id forget")
    assert memory.command(host, "snapshot-inspect before") == result
    assert (host.home / "config.yaml").read_bytes() == before
    assert not (host.home / "memories" / "MEMORY.md").exists()


@pytest.mark.parametrize("text", ["snapshot-create ../bad", "snapshot-inspect /tmp/x"])
def test_native_invalid_name_before_storage(host, text):
    memory.assert_error(memory.command(host, text), "invalid_request")
    assert not directory(host.home).exists()
    assert not memory.database(host.home).exists()


def test_native_disabled_and_remote_request_cannot_create_snapshots(host):
    memory.configure(host.home, local_memory=False)
    memory.assert_error(memory.command(host, "snapshot-create blocked"), "local_memory_disabled")
    assert not directory(host.home).exists()
    value = json.loads(
        memory.handler(host)(
            "--json snapshot-create blocked",
            platform="telegram",
            session_id="remote",
            session_key="remote",
        )
    )
    memory.assert_error(value, "unsupported_origin")
    assert not directory(host.home).exists()


def test_native_foreign_controller_denied_before_snapshot_storage(host):
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, subject="foreign")
    with pytest.raises(RuntimeStoreError):
        memory.command(host, "snapshot-create foreign")
    assert not directory(host.home).exists()


def test_native_model_has_no_snapshot_actions(native, monkeypatch):
    import test_local_conversation_tasks as local

    home, manager = native
    memory.configure(home, memory_model_tools=True, local_model_tools=True)
    monkeypatch.setattr(local, "load", lambda manager: manager.discover_and_load())
    host = local.make_host(home, manager)
    model.activate(host)
    with model.turn(host):
        for action in ("snapshot_create", "snapshot_inspect"):
            assert model.call(host, {"action": action})["error"]["code"] == "invalid_request"
    assert not directory(home).exists()
