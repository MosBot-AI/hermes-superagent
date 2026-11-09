"""Fixed private projection through actual pinned native operator admission."""

import json
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_session_memory_tools as model
from test_memory_workbench import raw_command

native = memory.native
host = memory.host


def test_native_explicit_projection_lifecycle_preserves_host_memory_and_configuration(host):
    before = (host.home / "config.yaml").read_bytes()
    status = memory.command(host, "projection-status")
    assert status["status"] == "ok" and not status["data"]["enabled"]
    target = memory.database(host.home).parent / "records.md"
    assert not target.exists()
    saved = memory.command(host, 'remember "私人中文内容" --request-id projection-native')
    rid = saved["data"]["record_id"]
    refreshed = memory.command(host, "projection-refresh")
    assert refreshed["status"] == "ok" and refreshed["data"]["refresh_completed"]
    assert "私人中文内容" in target.read_text()
    assert memory.command(host, "projection-status")["data"]["current"]
    forgotten = memory.command(
        host, f"forget {rid} --expected-revision 1 --request-id native-forget"
    )
    assert forgotten["status"] == "ok" and not target.exists()
    assert memory.command(host, "projection-status")["data"]["dirty"]
    memory.command(host, "projection-refresh")
    assert "私人中文内容" not in target.read_text()
    assert (host.home / "config.yaml").read_bytes() == before
    assert not (host.home / "memories" / "MEMORY.md").exists()


def test_projection_commands_keep_structured_metadata_even_default_text(host):
    result = json.loads(raw_command(host, "projection-refresh"))
    assert result["status"] == "ok" and result["data"]["refresh_completed"]
    assert json.loads(raw_command(host, "projection-status"))["data"]["current"]


@pytest.mark.parametrize(
    "command", ["projection-refresh", "projection-status", "projection-disable"]
)
def test_projection_native_admission_and_command_scope_unchanged(host, command):
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, subject="foreign")
    with pytest.raises(RuntimeStoreError):
        memory.command(host, command)
    assert not memory.database(host.home).exists()


def test_projection_does_not_register_model_file_actions(native, monkeypatch):
    # Build the same actual native model-enabled host as existing memory-tool contracts.
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][memory.PLUGIN_ID]["settings"].update(
        local_memory=True, memory_model_tools=True, local_model_tools=True
    )
    (home / "config.yaml").write_text(json.dumps(config))
    import test_local_conversation_tasks as local

    monkeypatch.setattr(local, "load", lambda manager: manager.discover_and_load())
    host = local.make_host(home, manager)
    model.activate(host)
    with model.turn(host):
        for action in ("projection_refresh", "projection_status", "projection_disable"):
            denied = model.call(host, {"action": action})
            assert denied["error"]["code"] == "invalid_request"
    assert not memory.database(home).exists()


def test_native_projection_disable_removes_only_managed_view_and_preserves_records(host):
    saved = memory.command(host, 'remember "保留正文" --request-id disable-native')
    memory.command(host, "projection-refresh")
    target = memory.database(host.home).parent / "records.md"
    assert target.exists()
    for _ in range(2):
        result = memory.command(host, "projection-disable")
        assert result["status"] == "ok" and result["data"]["canonical_records_unchanged"]
        assert not result["data"]["enabled"] and not target.exists()
    assert (
        memory.command(host, f"show {saved['data']['record_id']}")["data"]["content"] == "保留正文"
    )
    assert not memory.command(host, "projection-status")["data"]["enabled"]
