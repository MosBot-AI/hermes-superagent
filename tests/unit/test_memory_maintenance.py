"""Fresh-source repack, exact state fencing and real process crash recovery."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from personal_agent import PLUGIN_ID, memory_storage
from personal_agent import memory_maintenance as maintenance
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService


@pytest.fixture
def store(tmp_path, monkeypatch):
    home = tmp_path / "home"
    directory = home / "plugin-data" / PLUGIN_ID / "memory"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "records.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    backend.open(
        connection,
        namespace_id="trusted-profile:" + hashlib.sha256(str(home).encode()).hexdigest(),
        session_ref="test",
    )
    service = MemoryService(backend)
    request = {"content": "中文 synthetic private", "request_id": "seed"}
    receipt = service.execute("remember", request)
    service.execute(
        "forget",
        {"record_id": receipt["data"]["record_id"], "expected_revision": 1, "request_id": "forget"},
    )
    backend.close()
    connection.close()
    path.chmod(0o600)
    monkeypatch.setattr(memory_storage, "current_profile_home", lambda: home)
    return home, path, receipt


def run(home, operation, **payload):
    return maintenance.maintain(home, "maintenance_" + operation, payload)["data"]


def test_repack_preserves_all_rows_tombstone_and_exact_receipt(store):
    home, path, receipt = store
    original = path.read_bytes()
    assert run(home, "preview")["watermark"] == 2
    assert run(home, "prepare", name="compact", expected_watermark=2)["phase"] == "prepared"
    with pytest.raises(MemoryError, match="memory_maintenance_pending"):
        with memory_storage.open_existing_memory_reader(home, "test"):
            pass
    assert run(home, "status", name="compact")["pending"]
    assert run(home, "commit", name="compact")["phase"] == "completed"
    assert (path.parent / "maintenance/compact.old.sqlite3").read_bytes() == original
    with memory_storage.open_existing_memory_reader(home, "test") as backend:
        record = backend.execute("get", {"record_id": receipt["data"]["record_id"]})
        assert record["status"] == "forgotten" and record["content"] is None
    conn = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    backend.open(
        conn,
        namespace_id="trusted-profile:" + hashlib.sha256(str(home).encode()).hexdigest(),
        session_ref="new",
    )
    assert MemoryService(backend).execute(
        "remember", {"content": "中文 synthetic private", "request_id": "seed"}
    ) == {"data": receipt["data"], "replayed": True}
    MemoryService(backend).execute("remember", {"content": "new generation", "request_id": "new"})
    backend.close()
    conn.close()
    changed = path.read_bytes()
    assert run(home, "recover", name="compact")["phase"] == "completed"
    assert path.read_bytes() == changed


@pytest.mark.parametrize(
    "cut", ["preparing", "stage", "prepared", "switching", "old", "new", "completed", "receipt"]
)
def test_real_process_crash_cutpoints_finish_without_rollback(store, cut):
    home, path, _ = store
    original = path.read_bytes()
    script = r"""
import os, sys
from pathlib import Path
from personal_agent import memory_maintenance as m, memory_storage
home = Path(sys.argv[1]); cut = sys.argv[2]
memory_storage.current_profile_home = lambda: home
write = m._write_json
rename = m.os.rename
def crash_write(path, data):
    if cut == 'stage' and data['phase'] == 'prepared':
        os._exit(73)
    write(path, data)
    phase_cut = path.name == '.maintenance.json' and data['phase'] == cut
    if phase_cut or (cut == 'receipt' and path.name == 'cut.json'):
        os._exit(73)
def crash_rename(source, destination):
    rename(source, destination)
    old_cut = cut == 'old' and destination.name.endswith('.old.sqlite3')
    if old_cut or (cut == 'new' and destination.name == 'records.sqlite3'):
        os._exit(73)
m._write_json = crash_write
m.os.rename = crash_rename
m.maintain(home, 'maintenance_prepare', {'name':'cut','expected_watermark':2})
m.maintain(home, 'maintenance_commit', {'name':'cut'})
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(home), cut], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 73, result.stderr
    assert (path.parent / ".maintenance.json").exists()
    assert run(home, "status", name="cut")["pending"]
    assert run(home, "recover", name="cut")["phase"] == "completed"
    assert not (path.parent / ".maintenance.json").exists()
    assert (path.parent / "maintenance/cut.old.sqlite3").read_bytes() == original
    assert run(home, "preview")["watermark"] == 2


def test_stale_source_and_changed_stage_fail_closed(store):
    home, path, _ = store
    with pytest.raises(MemoryError, match="revision_conflict"):
        run(home, "prepare", name="stale", expected_watermark=1)
    run(home, "prepare", name="compact", expected_watermark=2)
    stage = path.parent / "maintenance/compact.stage.sqlite3"
    with sqlite3.connect(stage) as conn:
        conn.execute("UPDATE receipts SET receipt='{}'")
    with pytest.raises(MemoryError):
        run(home, "commit", name="compact")
    assert (path.parent / ".maintenance.json").exists()
    assert not (path.parent / "maintenance/compact.old.sqlite3").exists()


def test_malformed_journal_and_conflicting_name(store):
    home, path, _ = store
    run(home, "prepare", name="compact", expected_watermark=2)
    with pytest.raises(MemoryError, match="maintenance_journal_invalid"):
        run(home, "recover", name="other")
    marker = path.parent / ".maintenance.json"
    journal = json.loads(marker.read_text())
    journal["unknown"] = "not accepted"
    marker.write_text(json.dumps(journal))
    with pytest.raises(MemoryError, match="maintenance_journal_invalid"):
        run(home, "recover", name="compact")


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_unsafe_source_refused(store, tmp_path, kind):
    home, path, _ = store
    moved = tmp_path / "other.sqlite3"
    path.rename(moved)
    if kind == "symlink":
        path.symlink_to(moved)
    else:
        os.link(moved, path)
    with pytest.raises(MemoryError):
        run(home, "prepare", name="unsafe", expected_watermark=2)
    assert not (path.parent / ".maintenance.json").exists()


def test_post_switch_io_error_is_unknown_not_rollback(store, monkeypatch):
    home, path, _ = store
    run(home, "prepare", name="compact", expected_watermark=2)
    rename = maintenance.os.rename

    def failure(source, destination):
        rename(source, destination)
        if destination == path:
            raise OSError("private path never returned")

    monkeypatch.setattr(maintenance.os, "rename", failure)
    with pytest.raises(MemoryError, match="maintenance_outcome_unknown"):
        run(home, "commit", name="compact")
    monkeypatch.setattr(maintenance.os, "rename", rename)
    assert run(home, "recover", name="compact")["phase"] == "completed"


def test_size_deadline_and_payload_guards(store, monkeypatch):
    home, path, _ = store
    monkeypatch.setattr(maintenance, "MAX_BYTES", 1)
    with pytest.raises(MemoryError, match="maintenance_size_limit"):
        run(home, "preview")
    monkeypatch.setattr(maintenance, "MAX_BYTES", 128 * 1024 * 1024)
    monkeypatch.setattr(maintenance, "TIMEOUT_SECONDS", -1)
    with pytest.raises(MemoryError):
        run(home, "prepare", name="late", expected_watermark=2)
    for payload in (
        {"name": "../bad", "expected_watermark": 2},
        {"name": "good", "expected_watermark": True},
        {"name": "good", "expected_watermark": 2, "path": "/tmp"},
    ):
        with pytest.raises(MemoryError, match="invalid_request"):
            maintenance.maintain(home, "maintenance_prepare", payload)


def test_nonempty_source_suppression_and_receipts_preserved(store):
    from test_memory_candidates import propose

    home, path, _ = store
    connection = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    namespace = "trusted-profile:" + hashlib.sha256(str(home).encode()).hexdigest()
    backend.open(connection, namespace_id=namespace, session_ref="test")
    candidate = propose(backend)["data"]["candidate_id"]
    MemoryService(backend).execute(
        "candidate_suppress_source", {"candidate_id": candidate, "expected_revision": 1}
    )
    expected = {
        name: connection.execute("SELECT * FROM " + name).fetchall()
        for name in ("memory_source_suppressions", "memory_candidates", "receipts", "events")
    }
    assert expected["memory_source_suppressions"]
    backend.close()
    connection.close()
    run(home, "prepare", name="suppression", expected_watermark=2)
    run(home, "commit", name="suppression")
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        for name, rows in expected.items():
            assert connection.execute("SELECT * FROM " + name).fetchall() == rows
        backend.open(connection, namespace_id=namespace, session_ref="next")
        with pytest.raises(MemoryError, match="candidate_source_suppressed"):
            propose(backend, key="new")
    finally:
        backend.close()
        connection.close()


@pytest.mark.parametrize("change", ["missing", "changed"])
def test_live_source_missing_or_changed_never_restores_stage(store, change):
    home, path, _ = store
    run(home, "prepare", name="compact", expected_watermark=2)
    if change == "missing":
        path.unlink()
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE receipts SET receipt='{}'")
    with pytest.raises(MemoryError, match="maintenance_changed"):
        run(home, "recover", name="compact")
    assert (path.parent / ".maintenance.json").exists()
    assert not (path.parent / "maintenance/compact.old.sqlite3").exists()
    if change == "missing":
        assert not path.exists()


def test_duplicate_journal_keys_refused(store):
    home, path, _ = store
    run(home, "prepare", name="compact", expected_watermark=2)
    marker = path.parent / ".maintenance.json"
    marker.write_text(marker.read_text().replace("{", '{"version":1,', 1))
    with pytest.raises(MemoryError, match="maintenance_journal_invalid"):
        run(home, "recover", name="compact")


def test_interrupted_owned_stage_rebuilt_not_adopted(store, monkeypatch):
    home, path, _ = store
    original = maintenance._prepare_stage

    def interruption(*args):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(maintenance, "_prepare_stage", interruption)
    with pytest.raises(MemoryError, match="maintenance_outcome_unknown"):
        run(home, "prepare", name="compact", expected_watermark=2)
    stage = path.parent / "maintenance/compact.stage.sqlite3"
    stage.write_bytes(b"incomplete SQLite bytes")
    sidecar = stage.with_name(stage.name + "-journal")
    sidecar.write_bytes(b"incomplete rollback")
    sidecar.chmod(0o600)
    monkeypatch.setattr(maintenance, "_prepare_stage", original)
    assert run(home, "recover", name="compact")["phase"] == "completed"
    assert not sidecar.exists()


def test_cutover_directory_sync_publishes_destination_before_source_removal(store, monkeypatch):
    home, path, _ = store
    run(home, "prepare", name="compact", expected_watermark=2)
    events = []
    rename, sync = maintenance.os.rename, maintenance._sync

    def observed_rename(source, destination):
        rename(source, destination)
        events.append(("rename", source, destination))

    def observed_sync(directory):
        sync(directory)
        events.append(("sync", directory))

    monkeypatch.setattr(maintenance.os, "rename", observed_rename)
    monkeypatch.setattr(maintenance, "_sync", observed_sync)
    run(home, "commit", name="compact")
    for index, event in enumerate(events):
        if event[0] == "rename":
            _, source, destination = event
            assert events[index + 1 : index + 3] == [
                ("sync", destination.parent),
                ("sync", source.parent),
            ]
