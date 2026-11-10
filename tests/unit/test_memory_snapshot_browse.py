"""Explicit digest-bound historical reads; no current-state resurrection."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
import test_memory_snapshot as shared

from personal_agent import memory_snapshot
from personal_agent.memory_backend import MemoryError

store = shared.store
remember = shared.remember
run = shared.run


def browse(home, digest, operation="list", **fields):
    return memory_snapshot.snapshot(
        home, "snapshot_" + operation, {"name": "before-change", "sha256": digest, **fields}
    )["data"]


def test_list_show_after_forget_are_historical_not_current(store):
    service, conn, path, home = store
    rid = remember(service)
    digest = run(home)["sha256"]
    service.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    before = list(conn.iterdump())
    listing = browse(home, digest)
    assert "content" not in listing["historical_records"]["items"][0]
    shown = browse(home, digest, "show", record_id=rid)
    assert shown["historical_records"]["record"]["content"] == "私密 historical memory"
    assert "later-forgotten" in shown["notice"] and "host history" in shown["notice"]
    assert "expired" not in shown["historical_records"]["record"]
    assert service.execute("list", {})["data"]["items"] == []
    assert service.execute("recall", {"queries": ["私密"]})["data"]["items"] == []
    assert list(conn.iterdump()) == before
    assert shown["restorable"] is False


def test_digest_mismatch_is_checked_before_reader(store, monkeypatch):
    service, _, _, home = store
    rid = remember(service)
    run(home)

    def denied(*args):
        pytest.fail("must not read historical fields before digest matches")

    monkeypatch.setattr(memory_snapshot, "_read_records", denied)
    with pytest.raises(MemoryError, match="snapshot_changed"):
        browse(home, "0" * 64, "show", record_id=rid)


def test_cursor_pages_and_missing_record(store):
    service, _, _, home = store
    ids = [remember(service, key=str(i)) for i in range(3)]
    digest = run(home)["sha256"]
    page = browse(home, digest, limit=2)["historical_records"]
    assert [x["record_id"] for x in page["items"]] == ids[:0:-1]
    assert page["has_more"] and page["next_cursor"] == ids[1]
    last = browse(home, digest, limit=2, after=page["next_cursor"])["historical_records"]
    assert [x["record_id"] for x in last["items"]] == ids[:1]
    assert not last["has_more"] and last["next_cursor"] is None
    with pytest.raises(MemoryError, match="invalid_cursor"):
        browse(home, digest, after=str(uuid4()))
    with pytest.raises(MemoryError, match="snapshot_record_not_found"):
        browse(home, digest, "show", record_id=str(uuid4()))


@pytest.mark.parametrize(
    "change",
    [
        {"sha256": "bad"},
        {"sha256": None},
        {"limit": True},
        {"limit": 21},
        {"after": "bad"},
        {"name": "../escape"},
        {"unexpected": "field"},
    ],
)
def test_invalid_request_does_not_create_storage(store, change):
    _, _, path, home = store
    with pytest.raises(MemoryError, match="invalid_request"):
        memory_snapshot.snapshot(
            home, "snapshot_list", {"name": "before-change", "sha256": "a" * 64, **change}
        )
    assert not (path.parent / "snapshots").exists()


def test_missing_snapshot_does_not_create_directory(store):
    _, _, path, home = store
    with pytest.raises(MemoryError, match="snapshot_not_found"):
        browse(home, "a" * 64)
    assert not (path.parent / "snapshots").exists()


@pytest.mark.parametrize(
    "column,value,error",
    [
        ("content", "x" * 12001, "snapshot_record_too_large"),
        ("content", sqlite3.Binary(b"blob"), "snapshot_record_invalid"),
        ("created_at", "not-a-time", "snapshot_record_invalid"),
        ("content", "x" * 2049, "snapshot_record_invalid"),
    ],
)
def test_selected_malformed_record_fails_without_partial_result(store, column, value, error):
    service, _, path, home = store
    rid = remember(service)
    run(home)
    target = path.parent / "snapshots/before-change.sqlite3"
    with sqlite3.connect(target) as db:
        db.execute(f"UPDATE records SET {column}=?", (value,))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    with pytest.raises(MemoryError, match=error):
        browse(home, digest, "show", record_id=rid)


def test_budget_refusal_before_selected_payload_fetch(store, monkeypatch):
    service, _, _, home = store
    remember(service)
    digest = run(home)["sha256"]
    statements = []
    connect = memory_snapshot._connect

    def traced(*args):
        conn = connect(*args)
        conn.set_trace_callback(statements.append)
        return conn

    monkeypatch.setattr(memory_snapshot, "_connect", traced)
    monkeypatch.setattr(memory_snapshot, "MAX_RESULT_CHARS", 100)
    with pytest.raises(MemoryError, match="snapshot_result_too_large"):
        browse(home, digest)
    assert not any(sql.startswith("SELECT record_id,revision,status,topic") for sql in statements)


def test_real_writer_cannot_commit_during_historical_reader(store, monkeypatch):
    service, _, path, home = store
    rid = remember(service)
    digest = run(home)["sha256"]
    target = path.parent / "snapshots/before-change.sqlite3"
    writer = """import sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=.05,isolation_level=None)
try:
 c.execute('BEGIN IMMEDIATE'); c.execute("UPDATE records SET topic='changed'")
 c.execute('COMMIT'); print('committed')
except sqlite3.OperationalError as e:
 if 'locked' not in str(e): raise
 print('blocked')
finally: c.close()
"""

    def write():
        return subprocess.run(
            [sys.executable, "-c", writer, str(target)],
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        ).stdout.strip()

    real = memory_snapshot._read_records

    def reader(*args):
        assert write() == "blocked"
        return real(*args)

    monkeypatch.setattr(memory_snapshot, "_read_records", reader)
    assert (
        browse(home, digest, "show", record_id=rid)["historical_records"]["record"]["record_id"]
        == rid
    )
    assert write() == "committed"
    with pytest.raises(MemoryError, match="snapshot_changed"):
        browse(home, digest)


def test_v10_historical_browse_does_not_migrate(store):
    service, _, path, home = store
    rid = remember(service)
    run(home)
    target = path.parent / "snapshots/before-change.sqlite3"
    with sqlite3.connect(target) as db:
        db.execute("DROP TABLE memory_source_lineage")
        db.execute("DROP TABLE memory_source_suppressions")
        db.execute("PRAGMA user_version=10")
    before = target.read_bytes()
    result = browse(home, hashlib.sha256(before).hexdigest(), "show", record_id=rid)
    assert result["schema_version"] == 10
    assert target.read_bytes() == before
    assert "source_digest" not in json.dumps(result)


def test_historical_read_does_not_bypass_current_source_suppression(store):
    from test_memory_candidates import accept_args, propose

    service, conn, _, home = store
    backend = service.backend
    cid = propose(backend)["data"]["candidate_id"]
    rid = service.execute("candidate_accept", accept_args(cid))["data"]["record"]["record_id"]
    digest = run(home)["sha256"]
    service.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    before = list(conn.iterdump())
    shown = browse(home, digest, "show", record_id=rid)
    assert shown["historical_records"]["record"]["content"] == "偏好中文"
    with pytest.raises(MemoryError, match="candidate_source_suppressed"):
        propose(backend, key="new", source_turn="f" * 64)
    assert service.execute("recall", {"queries": ["中文"]})["data"]["items"] == []
    assert list(conn.iterdump()) == before


def test_tombstone_is_payload_free_historical_record(store):
    service, _, _, home = store
    rid = remember(service)
    service.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    digest = run(home)["sha256"]
    record = browse(home, digest, "show", record_id=rid)["historical_records"]["record"]
    assert record["status"] == "forgotten"
    assert record["content"] is record["topic"] is record["expires_at"] is None


def test_historical_reader_error_releases_connection_and_gate(store, monkeypatch):
    service, _, _, home = store
    remember(service)
    digest = run(home)["sha256"]
    real = memory_snapshot._read_records

    def fail(*args):
        raise OSError("private path must not escape")

    monkeypatch.setattr(memory_snapshot, "_read_records", fail)
    with pytest.raises(MemoryError, match="snapshot_unavailable") as caught:
        browse(home, digest)
    assert "private path" not in str(caught.value)
    assert not memory_snapshot._METADATA_LOCK.locked()
    monkeypatch.setattr(memory_snapshot, "_read_records", real)
    assert len(browse(home, digest)["historical_records"]["items"]) == 1
