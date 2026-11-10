"""Current-store repack under native local admission, never historical restore."""

import json
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_session_memory_tools as model

native = memory.native
host = memory.host


def test_native_repack_retains_receipts_and_terminal_forgetting(host):
    before = (host.home / "config.yaml").read_bytes()
    request = 'remember "repack 私密 synthetic" --request-id repack-seed'
    receipt = memory.command(host, request)
    rid = receipt["data"]["record_id"]
    memory.command(host, f"forget {rid} --expected-revision 1 --request-id repack-forget")
    preview = memory.command(host, "maintenance-preview")
    assert preview["status"] == "ok", preview
    prepared = memory.command(host, "maintenance-prepare native-repack --expected-watermark 2")
    assert prepared["status"] == "ok", prepared
    blocked = memory.command(host, "list")
    assert blocked["status"] == "error" and "maintenance" in blocked["error"]["code"]
    committed = memory.command(host, "maintenance-commit native-repack")
    assert committed["status"] == "ok", committed
    assert memory.command(host, "maintenance-status native-repack")["status"] == "ok"
    assert memory.command(host, request)["replayed"] is True
    current = memory.command(host, f"show {rid}")
    assert current["data"]["status"] == "forgotten" and current["data"]["content"] is None
    assert memory.command(host, "list")["data"]["items"] == []
    assert (host.home / "config.yaml").read_bytes() == before


@pytest.mark.parametrize(
    "text",
    [
        "maintenance-prepare ../escape --expected-watermark 0",
        "maintenance-commit /tmp/foreign",
        "maintenance-recover old --snapshot before",
        "maintenance-prepare old --expected-watermark -1",
    ],
)
def test_native_invalid_maintenance_before_storage(host, text):
    memory.assert_error(memory.command(host, text), "invalid_request")
    assert not memory.database(host.home).exists()


def test_native_disabled_remote_and_foreign_maintenance_refused(host):
    memory.configure(host.home, local_memory=False)
    memory.assert_error(memory.command(host, "maintenance-preview"), "local_memory_disabled")
    value = json.loads(
        memory.handler(host)(
            "--json maintenance-preview",
            platform="telegram",
            session_id="remote",
            session_key="remote",
        )
    )
    memory.assert_error(value, "unsupported_origin")
    memory.configure(host.home, local_memory=True)
    host.connection.actor = replace(host.connection.actor, subject="foreign")
    from hermes_state_runtime import RuntimeStoreError

    with pytest.raises(RuntimeStoreError):
        memory.command(host, "maintenance-prepare test --expected-watermark 0")
    assert not memory.database(host.home).exists()


def test_native_model_has_no_maintenance_authority(native, monkeypatch):
    import test_local_conversation_tasks as local

    home, manager = native
    memory.configure(home, memory_model_tools=True, local_model_tools=True)
    monkeypatch.setattr(local, "load", lambda manager: manager.discover_and_load())
    host = local.make_host(home, manager)
    model.activate(host)
    with model.turn(host):
        for action in (
            "maintenance_preview",
            "maintenance_prepare",
            "maintenance_commit",
            "maintenance_status",
            "maintenance_recover",
        ):
            assert model.call(host, {"action": action})["error"]["code"] == "invalid_request"
    assert not memory.database(home).exists()
