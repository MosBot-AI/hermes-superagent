"""Reviewed expiry cleanup through the pinned host's real local command gates."""

import json
from dataclasses import replace

import pytest
import test_local_memory_commands as memory
import test_session_memory_tools as model
from test_memory_workbench import raw_command

native = memory.native
host = memory.host
CUTOFF = "2001-01-01T00:00:00Z"


def test_native_complete_review_bounded_batch_historical_retry_and_config_preserved(host):
    before = (host.home / "config.yaml").read_bytes()
    ids = []
    for i in range(3):
        saved = memory.command(
            host,
            f'remember "中文到期记录{i}" --expires-at 2000-01-01T00:00:00Z --request-id seed{i}',
        )
        ids.append(saved["data"]["record_id"])
    output = raw_command(host, f"expired-preview --before {CUTOFF} --limit 2")
    assert output.isascii()
    preview = json.loads(output)
    assert preview["status"] == "ok"
    data = preview["data"]
    assert data["selected_count"] == 2 and data["remaining_count"] == 1
    assert data["items"][0]["content"] == "中文到期记录0"
    assert len(json.dumps(data, ensure_ascii=True, sort_keys=True)) <= 64000
    command = (
        f"forget-expired --before {CUTOFF} --limit 2 "
        f"--expected-snapshot {data['snapshot']} --request-id cleanup"
    )
    result = json.loads(raw_command(host, command))
    assert result["status"] == "ok" and result["data"]["forgotten_count"] == 2
    assert memory.command(host, command) == {**result, "replayed": True}
    assert memory.command(host, f"show {ids[2]}")["data"]["status"] == "active"
    assert memory.command(host, f"show {ids[0]}")["data"]["content"] is None
    assert (host.home / "config.yaml").read_bytes() == before
    assert not (host.home / "memories" / "MEMORY.md").exists()


@pytest.mark.parametrize(
    "raw",
    [
        "expired-preview",
        f"expired-preview --before {CUTOFF} --limit 21",
        f"forget-expired --before {CUTOFF} --expected-snapshot " + "a" * 64,
    ],
)
def test_native_invalid_or_missing_explicit_fields_do_not_open_storage(host, raw):
    memory.assert_error(memory.command(host, raw), "invalid_request")
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize(
    "raw",
    [
        f"expired-preview --before {CUTOFF}",
        f"forget-expired --before {CUTOFF} --expected-snapshot "
        + "a" * 64
        + " --request-id stable",
    ],
)
def test_native_foreign_actor_rejected_before_storage(host, raw):
    from hermes_state_runtime import RuntimeStoreError

    host.connection.actor = replace(host.connection.actor, subject="foreign")
    with pytest.raises(RuntimeStoreError):
        memory.command(host, raw)
    assert not memory.database(host.home).exists()


def test_native_model_cannot_invoke_expired_review_or_cleanup(native, monkeypatch):
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
        for action in ("expired_preview", "forget_expired"):
            assert model.call(host, {"action": action})["error"]["code"] == "invalid_request"
    assert not memory.database(home).exists()
