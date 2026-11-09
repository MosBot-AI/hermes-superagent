"""Real native operator-only editable Markdown draft lifecycle; no live model."""

import json
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_session_memory_tools as model
from test_memory_workbench import raw_command

native = memory.native
host = memory.host


def test_native_edit_draft_workflow_and_retry_preserve_config_and_expiry(host):
    before = (host.home / "config.yaml").read_bytes()
    rid = memory.command(
        host, 'remember "原正文" --expires-at 2030-01-01T00:00:00Z --request-id seed'
    )["data"]["record_id"]
    create = memory.command(host, f"edit-create {rid} --expected-revision 1 --request-id draft")
    assert create["status"] == "ok" and create["data"]["state"] == "ready"
    did = create["data"]["draft_id"]
    target = memory.database(host.home).parent / "edit.md"
    target.write_text(target.read_text().replace("原正文", "更新中文\n# 长正文第二行"))
    preview = memory.command(host, f"edit-preview {did}")["data"]
    assert preview["proposed"]["content"] == "更新中文\n# 长正文第二行"
    command = f"edit-apply {did} --expected-digest {preview['sha256']} --request-id apply"
    applied = memory.command(host, command)
    assert applied["data"]["record"]["revision"] == 2 and not target.exists()
    assert memory.command(host, command)["replayed"]
    current = memory.command(host, f"show {rid}")["data"]
    assert current["content"] == preview["proposed"]["content"]
    assert current["expires_at"] == "2030-01-01T00:00:00Z"
    assert (host.home / "config.yaml").read_bytes() == before
    assert not (host.home / "memories" / "MEMORY.md").exists()


def test_native_status_recovers_id_and_discard_allows_new_draft(host):
    assert json.loads(raw_command(host, "edit-status"))["data"]["active"] is None
    rid = memory.command(host, 'remember "原正文" --request-id seed')["data"]["record_id"]
    memory.command(host, f"edit-create {rid} --expected-revision 1")
    target = memory.database(host.home).parent / "edit.md"
    target.unlink()
    status = memory.command(host, "edit-status")["data"]
    assert not status["file_present"]
    did = status["active"]["draft_id"]
    assert memory.command(host, f"edit-discard {did}")["status"] == "ok"
    assert memory.command(host, f"edit-discard {did}")["replayed"]
    assert memory.command(host, f"edit-create {rid} --expected-revision 1")["status"] == "ok"


@pytest.mark.parametrize(
    "command", ["edit-status", "edit-create", "edit-preview", "edit-apply", "edit-discard"]
)
def test_native_edit_commands_reject_foreign_actor_before_storage(host, command):
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, subject="foreign")
    with pytest.raises(RuntimeStoreError):
        memory.command(host, command)
    assert not memory.database(host.home).exists()


def test_no_model_edit_file_actions(native, monkeypatch):
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
        for action in ("edit_status", "edit_create", "edit_preview", "edit_apply", "edit_discard"):
            assert model.call(host, {"action": action})["error"]["code"] == "invalid_request"
    assert not memory.database(home).exists()
