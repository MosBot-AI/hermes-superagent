"""Private projection publication, recovery and canonical-writer fencing."""

import os
import sqlite3
import subprocess
import sys

import pytest

from personal_agent import memory_expiry
from personal_agent.local_memory import _APPLICATION_ID, _SCHEMA_V7, create_backend
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_projection import FILENAME, TEMP, PrivateProjection


@pytest.fixture
def store(tmp_path):
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)
    backend, conn = opened(directory)
    try:
        yield backend, conn, directory
    finally:
        backend.close()
        conn.close()


def opened(directory, *, projection=True, namespace="test", factory=sqlite3.Connection):
    conn = sqlite3.connect(directory / "records.sqlite3", isolation_level=None, factory=factory)
    backend = create_backend()
    backend.open(
        conn,
        namespace_id=namespace,
        session_ref="session",
        projection=PrivateProjection(directory) if projection else None,
    )
    return backend, conn


def save(backend, key="save", **extra):
    return backend.execute(
        "remember", {"content": "北京 Hermes 私有记忆", "request_id": key, **extra}
    )["data"]


def forget(backend, rid, revision=1):
    return backend.execute(
        "forget", {"record_id": rid, "expected_revision": revision, "request_id": "forget"}
    )


def test_explicit_enable_private_snapshot_and_status_do_not_change_canonical(store):
    backend, conn, directory = store
    assert not backend.execute("projection_status", {})["enabled"]
    assert not (directory / FILENAME).exists()
    receipt = save(backend, topic="工作")
    events = conn.execute("SELECT * FROM events").fetchall()
    result = MemoryService(backend).execute("projection_refresh", {})["data"]
    assert result["refresh_completed"]
    data = (directory / FILENAME).read_text()
    assert "北京 Hermes 私有记忆" in data and receipt["record_id"] in data
    assert "Watermark: 1" in data and 'Namespace: "test"' in data
    assert (directory / FILENAME).stat().st_mode & 0o777 == 0o600
    assert backend.execute("projection_status", {})["current"]
    assert conn.execute("SELECT * FROM events").fetchall() == events
    assert not (directory.parent / "MEMORY.md").exists()


def test_correction_forget_and_idempotent_replay_cannot_restore_file(store):
    backend, _, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    backend.execute(
        "correct",
        {
            "record_id": receipt["record_id"],
            "expected_revision": 1,
            "content": "上海 changed",
            "request_id": "correct",
        },
    )
    assert not (directory / FILENAME).exists()
    assert backend.execute("projection_status", {})["dirty"]
    backend.execute("projection_refresh", {})
    assert "北京" not in (directory / FILENAME).read_text()
    assert "上海" in (directory / FILENAME).read_text()
    forget(backend, receipt["record_id"], 2)
    assert not (directory / FILENAME).exists()
    assert save(backend) == receipt
    assert not (directory / FILENAME).exists()
    backend.execute("projection_refresh", {})
    assert "上海" not in (directory / FILENAME).read_text()
    assert "Records: 0" in (directory / FILENAME).read_text()


def test_bare_backend_cannot_bypass_enabled_projection(store):
    backend, _, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    bare, conn = opened(directory, projection=False)
    try:
        with pytest.raises(MemoryError, match="projection_storage_required"):
            forget(bare, receipt["record_id"])
        assert bare.execute("get", {"record_id": receipt["record_id"]})["status"] == "active"
    finally:
        bare.close()
        conn.close()
    assert (directory / FILENAME).exists()


@pytest.mark.parametrize(
    "operation", ["projection_refresh", "projection_status", "projection_disable"]
)
def test_model_source_does_not_gain_projection_commands(store, operation):
    backend, _, directory = store
    backend._source_kind = "activated_session_model"
    with pytest.raises(MemoryError, match="projection_scope_required"):
        backend.execute(operation, {})
    assert not (directory / FILENAME).exists()


def test_hand_edited_file_is_not_overwritten_and_blocks_mutation(store):
    backend, conn, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    path = directory / FILENAME
    path.write_text("My manual edits")
    before = conn.execute("SELECT * FROM records").fetchall()
    for operation in (
        lambda: backend.execute("projection_refresh", {}),
        lambda: forget(backend, receipt["record_id"]),
        lambda: save(backend, "another"),
    ):
        with pytest.raises(MemoryError, match="projection_conflict"):
            operation()
        assert path.read_text() == "My manual edits"
        assert conn.execute("SELECT * FROM records").fetchall() == before
    path.unlink()  # Operator resolves the conflict explicitly; code never does it.
    forget(backend, receipt["record_id"])
    backend.execute("projection_refresh", {})
    assert "北京" not in path.read_text()


@pytest.mark.parametrize("name", [FILENAME, TEMP])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "directory", "fifo"])
def test_unsafe_files_are_never_followed_repaired_or_removed(store, tmp_path, name, kind):
    backend, _, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    path = directory / name
    if path.exists():
        path.unlink()
    target = tmp_path / "private-target"
    target.write_text("untouched")
    target.chmod(0o600)
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "public":
        path.write_text("public")
        path.chmod(0o644)
    elif kind == "directory":
        path.mkdir(mode=0o700)
    else:
        os.mkfifo(path, 0o600)
    with pytest.raises(MemoryError, match="unsafe_projection_file"):
        forget(backend, receipt["record_id"])
    assert target.read_text() == "untouched"
    assert path.exists() or path.is_symlink()
    assert backend.execute("get", {"record_id": receipt["record_id"]})["status"] == "active"


def test_private_directory_and_database_binding_required(store, tmp_path):
    backend, conn, directory = store
    save(backend)
    directory.chmod(0o755)
    with pytest.raises(MemoryError, match="unsafe_storage_path"):
        backend.execute("projection_refresh", {})
    directory.chmod(0o700)
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    unbound = create_backend()
    with pytest.raises(MemoryError, match="projection_storage_mismatch"):
        unbound.open(
            conn, namespace_id="test", session_ref="s", projection=PrivateProjection(other)
        )
    with pytest.raises(MemoryError, match="namespace_mismatch"):
        opened(directory, namespace="foreign")


def test_expiry_time_progression_marks_snapshot_stale_without_watermark_change(store, monkeypatch):
    backend, _, directory = store
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-01-01T00:00:00Z")
    save(backend, expires_at="2026-01-02T00:00:00Z")
    backend.execute("projection_refresh", {})
    assert backend.execute("projection_status", {})["current"]
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-01-03T00:00:00Z")
    status = backend.execute("projection_status", {})
    assert status["stale_by_time"] and not status["current"] and status["current_watermark"] == 1
    backend.execute("projection_refresh", {})
    assert '"expired": true' in (directory / FILENAME).read_text()
    assert backend.execute("projection_status", {})["current"]


def test_markdown_and_terminal_injection_stays_literal_data(store):
    backend, _, directory = store
    text = "# Header\n<script>alert(1)</script>\n[link](https://example.invalid)\n```"
    save(backend, content=text)
    backend.execute("projection_refresh", {})
    rendered = (directory / FILENAME).read_text()
    assert "\n<script>" not in rendered and "\n[link]" not in rendered and "\n```" not in rendered
    assert "\\n<script>" in rendered


def test_candidate_accept_invalidates_projection_in_same_transaction(store):
    backend, _, directory = store
    backend.execute("projection_refresh", {})
    backend._source_kind = "activated_session_model"
    candidate = backend.execute(
        "candidate_propose",
        {
            "content": "候选内容",
            "quote": "候选",
            "quote_start": 0,
            "source_digest": "a" * 64,
            "source_turn": "b" * 64,
            "request_id": "candidate",
        },
    )["data"]
    backend._source_kind = "explicit_local_operator"
    assert (directory / FILENAME).exists()
    accepted = backend.execute(
        "candidate_accept",
        {"candidate_id": candidate["candidate_id"], "expected_revision": 1, "expires_at": None},
    )
    assert not (directory / FILENAME).exists()
    backend.execute("projection_refresh", {})
    assert "候选内容" in (directory / FILENAME).read_text()
    forget(backend, accepted["data"]["record"]["record_id"])
    backend.execute(
        "candidate_accept",
        {"candidate_id": candidate["candidate_id"], "expected_revision": 1, "expires_at": None},
    )
    assert not (directory / FILENAME).exists()


def test_forget_after_prepare_fences_resumed_old_publication(tmp_path):
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)

    class Interleave(sqlite3.Connection):
        callback = None

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if sql == "COMMIT" and self.callback:
                callback, self.callback = self.callback, None
                callback()
            return result

    backend, conn = opened(directory, factory=Interleave)
    receipt = save(backend)
    other, second = opened(directory)
    try:
        conn.callback = lambda: forget(other, receipt["record_id"])
        with pytest.raises(MemoryError, match="projection_changed"):
            backend.execute("projection_refresh", {})
        assert not (directory / FILENAME).exists()
        assert backend.execute("get", {"record_id": receipt["record_id"]})["status"] == "forgotten"
        backend.execute("projection_refresh", {})
        assert "北京" not in (directory / FILENAME).read_text()
    finally:
        backend.close()
        conn.close()
        other.close()
        second.close()


def test_v7_migration_and_readonly_require_current_schema(tmp_path):
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)
    conn = sqlite3.connect(directory / "records.sqlite3", isolation_level=None)
    # Exact v7 fixture, including FTS shadow schema generated by SQLite.
    from personal_agent import memory_fts

    for key, sql in _SCHEMA_V7.items():
        if key not in memory_fts.SCHEMA:
            conn.execute(sql)
    memory_fts.create_index(conn)
    conn.execute("INSERT INTO namespace VALUES ('test')")
    conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
    conn.execute("PRAGMA user_version=7")
    reader = create_backend()
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        reader.open_readonly(conn, namespace_id="test", session_ref="s")
    conn.execute("PRAGMA query_only=OFF")
    backend = create_backend()
    backend.open(conn, namespace_id="test", session_ref="s")
    assert conn.execute("PRAGMA user_version").fetchone() == (12,)
    assert conn.execute("SELECT * FROM memory_projection").fetchall() == []
    backend.close()
    conn.close()


CHILD = r"""
import os, sqlite3, sys
from pathlib import Path
from personal_agent.local_memory import create_backend
from personal_agent.memory_projection import PrivateProjection
stage, directory, operation, rid = sys.argv[1:]
class Crash(sqlite3.Connection):
    armed=False
    count=0
    def execute(self, sql, *args):
        if self.armed and stage == 'before_receipt_commit' and sql == 'COMMIT' and self.count == 1:
            os._exit(73)
        result=super().execute(sql,*args)
        if self.armed and sql == 'COMMIT':
            self.count += 1
            if stage == 'after_prepare' and self.count == 1: os._exit(73)
        return result
conn=sqlite3.connect(Path(directory)/'records.sqlite3',isolation_level=None,factory=Crash)
b=create_backend()
b.open(conn,namespace_id='test',session_ref='s',projection=PrivateProjection(Path(directory)))
original_replace=os.replace
original_write=os.write
original_unlink=os.unlink
def replace(*args,**kwargs):
    result=original_replace(*args,**kwargs)
    if stage=='after_replace': os._exit(73)
    return result
def write(fd,data):
    if stage=='partial_temp':
        original_write(fd,data[:10]); os._exit(73)
    return original_write(fd,data)
def unlink(*args,**kwargs):
    result=original_unlink(*args,**kwargs)
    if stage=='after_invalidation': os._exit(73)
    return result
os.replace=replace; os.write=write; os.unlink=unlink
conn.armed=True
if operation=='forget':
    b.execute('forget',{'record_id':rid,'expected_revision':1,'request_id':'forget'})
else: b.execute('projection_refresh',{})
raise RuntimeError('crash point not reached')
"""


@pytest.mark.parametrize(
    "stage", ["after_prepare", "partial_temp", "after_replace", "before_receipt_commit"]
)
def test_publication_process_crash_recovers_without_resurrecting_forgotten_text(store, stage):
    backend, _, directory = store
    receipt = save(backend)
    child = subprocess.run(
        [sys.executable, "-c", CHILD, stage, str(directory), "refresh", "unused"],
        capture_output=True,
        text=True,
    )
    assert child.returncode == 73, child.stderr
    # Any renamed file is authenticated by its durable pending intent, not silently adopted.
    assert backend.execute("projection_status", {})["dirty"]
    forget(backend, receipt["record_id"])
    assert not (directory / FILENAME).exists() and not (directory / TEMP).exists()
    backend.execute("projection_refresh", {})
    assert "北京" not in (directory / FILENAME).read_text()


def test_repeated_refresh_recovers_renamed_file_before_previous_metadata_commit(store):
    backend, _, directory = store
    save(backend)
    child = subprocess.run(
        [sys.executable, "-c", CHILD, "after_replace", str(directory), "refresh", "unused"],
        capture_output=True,
        text=True,
    )
    assert child.returncode == 73, child.stderr
    backend.execute("projection_refresh", {})
    assert backend.execute("projection_status", {})["current"]


def test_crash_after_invalidation_rolls_back_canonical_but_leaves_safe_missing_projection(store):
    backend, _, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            CHILD,
            "after_invalidation",
            str(directory),
            "forget",
            receipt["record_id"],
        ],
        capture_output=True,
        text=True,
    )
    assert child.returncode == 73, child.stderr
    assert backend.execute("get", {"record_id": receipt["record_id"]})["status"] == "active"
    assert backend.execute("projection_status", {})["dirty"]
    forget(backend, receipt["record_id"])
    assert not (directory / FILENAME).exists()


def test_clock_rollback_does_not_claim_static_expiry_labels_are_current(store, monkeypatch):
    backend, _, _ = store
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-01-03T00:00:00Z")
    save(backend, expires_at="2026-01-02T00:00:00Z")
    backend.execute("projection_refresh", {})
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: "2026-01-01T00:00:00Z")
    status = backend.execute("projection_status", {})
    assert status["stale_by_time"] and not status["current"]


@pytest.mark.parametrize("operation", ["replace", "write", "fsync", "unlink"])
def test_filesystem_failure_never_claims_publication_or_forgetting(store, monkeypatch, operation):
    backend, _, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    before = backend.execute("get", {"record_id": receipt["record_id"]})

    def fail(*args, **kwargs):
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr(os, operation, fail)
    if operation == "unlink":
        with pytest.raises(MemoryError, match="projection_io_error"):
            forget(backend, receipt["record_id"])
        assert backend.execute("get", {"record_id": receipt["record_id"]}) == before
    else:
        with pytest.raises(MemoryError, match="projection_io_error"):
            backend.execute("projection_refresh", {})
        assert backend.execute("get", {"record_id": receipt["record_id"]}) == before


def test_publication_holds_writer_fence_until_replace_and_metadata_commit(store, monkeypatch):
    import threading
    import time

    backend, _, directory = store
    receipt = save(backend)
    publishing, release, mutation_started = threading.Event(), threading.Event(), threading.Event()
    errors = []
    original = PrivateProjection.publish

    def paused(self, data, saved):
        publishing.set()
        assert release.wait(5)
        return original(self, data, saved)

    monkeypatch.setattr(PrivateProjection, "publish", paused)

    def refresh():
        local, conn = opened(directory)
        try:
            local.execute("projection_refresh", {})
        except Exception as error:
            errors.append(error)
        finally:
            local.close()
            conn.close()

    def mutate():
        mutation_started.set()
        local, conn = opened(directory)
        try:
            forget(local, receipt["record_id"])
        except Exception as error:
            errors.append(error)
        finally:
            local.close()
            conn.close()

    publisher = threading.Thread(target=refresh)
    writer = threading.Thread(target=mutate)
    publisher.start()
    assert publishing.wait(5)
    writer.start()
    assert mutation_started.wait(5)
    time.sleep(0.03)
    assert writer.is_alive()  # Writer cannot pass the publication's SQLite write lock.
    release.set()
    publisher.join(5)
    writer.join(5)
    assert not publisher.is_alive() and not writer.is_alive() and not errors
    assert not (directory / FILENAME).exists()
    assert backend.execute("get", {"record_id": receipt["record_id"]})["status"] == "forgotten"


def test_disable_is_idempotent_preserves_canonical_and_allows_bare_writes_again(store):
    backend, conn, directory = store
    receipt = save(backend)
    backend.execute("projection_refresh", {})
    # Staging is a reserved managed artifact and must be removed too.
    temp = directory / TEMP
    temp.write_bytes(b"partial private staging")
    temp.chmod(0o600)
    before = conn.execute("SELECT * FROM records").fetchall()
    result = backend.execute("projection_disable", {})
    assert not result["enabled"] and result["canonical_records_unchanged"]
    assert not (directory / FILENAME).exists() and not temp.exists()
    assert conn.execute("SELECT * FROM records").fetchall() == before
    assert backend.execute("projection_disable", {}) == result
    assert not backend.execute("projection_status", {})["enabled"]
    bare, second = opened(directory, projection=False)
    try:
        forget(bare, receipt["record_id"])
    finally:
        bare.close()
        second.close()
    backend.execute("projection_refresh", {})
    assert backend.execute("projection_status", {})["current"]
    assert "北京" not in (directory / FILENAME).read_text()


@pytest.mark.parametrize("enabled", [False, True])
def test_disable_refuses_unknown_or_edited_view_without_removing_it(store, enabled):
    backend, _, directory = store
    if enabled:
        backend.execute("projection_refresh", {})
    path = directory / FILENAME
    path.write_text("Unowned edits")
    path.chmod(0o600)
    with pytest.raises(MemoryError, match="projection_conflict"):
        backend.execute("projection_disable", {})
    assert path.read_text() == "Unowned edits"


def test_disable_between_prepare_and_publish_fences_old_refresh(tmp_path):
    directory = tmp_path / "memory"
    directory.mkdir(mode=0o700)

    class Interleave(sqlite3.Connection):
        callback = None

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if sql == "COMMIT" and self.callback:
                callback, self.callback = self.callback, None
                callback()
            return result

    backend, conn = opened(directory, factory=Interleave)
    save(backend)
    other, second = opened(directory)
    try:
        conn.callback = lambda: other.execute("projection_disable", {})
        with pytest.raises(MemoryError, match="projection_changed"):
            backend.execute("projection_refresh", {})
        assert not (directory / FILENAME).exists()
        assert not backend.execute("projection_status", {})["enabled"]
    finally:
        backend.close()
        conn.close()
        other.close()
        second.close()


def test_second_crash_after_retry_prepare_keeps_previous_renamed_file_recognizable(store):
    backend, _, directory = store
    save(backend)
    for stage in ("after_replace", "after_prepare"):
        child = subprocess.run(
            [sys.executable, "-c", CHILD, stage, str(directory), "refresh", "unused"],
            capture_output=True,
            text=True,
        )
        assert child.returncode == 73, child.stderr
    status = backend.execute("projection_status", {})
    assert status["dirty"] and status["file_present"]
    backend.execute("projection_refresh", {})
    assert backend.execute("projection_status", {})["current"]


def test_corrupt_record_identifier_cannot_become_markdown_structure(store):
    backend, conn, directory = store
    receipt = save(backend)
    conn.execute(
        "UPDATE records SET record_id=? WHERE record_id=?",
        ("bad\n<script>bad</script>", receipt["record_id"]),
    )
    with pytest.raises(MemoryError, match="storage_corrupt"):
        backend.execute("projection_refresh", {})
    assert not (directory / FILENAME).exists()
