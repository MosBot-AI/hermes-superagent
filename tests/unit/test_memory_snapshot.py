"""Consistent plaintext snapshots, not restore or live authority."""

import hashlib
import os
import sqlite3
import subprocess
import sys

import pytest

from personal_agent import PLUGIN_ID, memory_snapshot, memory_storage
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService


@pytest.fixture
def store(tmp_path, monkeypatch):
    home = tmp_path / "home"
    directory = home / "plugin-data" / PLUGIN_ID / "memory"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "records.sqlite3"
    conn = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    backend.open(
        conn,
        namespace_id="trusted-profile:" + hashlib.sha256(str(home).encode()).hexdigest(),
        session_ref="test",
    )
    path.chmod(0o600)
    monkeypatch.setattr(memory_snapshot, "current_profile_home", lambda: home)
    monkeypatch.setattr(memory_storage, "current_profile_home", lambda: home)
    yield MemoryService(backend), conn, path, home
    backend.close()
    conn.close()


def remember(service, key="seed"):
    return service.execute(
        "remember", {"content": "私密 historical memory", "topic": "test", "request_id": key}
    )["data"]["record_id"]


def run(home, op="create", name="before-change"):
    return memory_snapshot.snapshot(home, "snapshot_" + op, {"name": name})["data"]


def test_snapshot_is_consistent_historical_not_restore(store):
    service, conn, path, home = store
    rid = remember(service)
    before = conn.execute("SELECT * FROM records").fetchall()
    result = run(home)
    assert result["records"] == result["active_records"] == 1 and result["tombstones"] == 0
    assert result["watermark"] == 1 and result["restorable"] is False
    assert "Plaintext" in result["notice"] and "forgetting" in result["notice"]
    destination = path.parent / "snapshots/before-change.sqlite3"
    with sqlite3.connect(destination) as copied:
        assert copied.execute("SELECT * FROM records").fetchall() == before
    assert result == run(home, "inspect")
    service.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"})
    assert run(home, "inspect")["sha256"] == result["sha256"]
    latest = run(home, name="after-change")
    assert latest["tombstones"] == 1 and latest["active_records"] == 0
    assert latest["watermark"] == 2
    assert not (path.parent / "records.md").exists()
    with pytest.raises(MemoryError, match="snapshot_exists"):
        run(home)


@pytest.mark.parametrize(
    "name", ["../escape", "/tmp/external", "a.sqlite3", "a b", "", "中", "x" * 65]
)
def test_no_arbitrary_paths_or_invalid_names(store, name):
    with pytest.raises(MemoryError, match="invalid_request"):
        run(store[3], name=name)
    assert not (store[2].parent / "snapshots").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "sidecar", "wal"])
def test_unsafe_snapshot_refused(store, kind):
    _, _, path, home = store
    run(home)
    target = path.parent / "snapshots/before-change.sqlite3"
    if kind == "symlink":
        target.unlink()
        target.symlink_to(path)
    elif kind == "hardlink":
        os.link(target, target.with_name("alias"))
    elif kind == "public":
        target.chmod(0o644)
    elif kind == "sidecar":
        target.with_name(target.name + "-wal").write_bytes(b"unsafe")
    else:
        with sqlite3.connect(target) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
    with pytest.raises(MemoryError):
        run(home, "inspect")


def test_current_profile_and_namespace_fences(store, monkeypatch):
    _, conn, _, home = store
    monkeypatch.setattr(memory_snapshot, "current_profile_home", lambda: home.parent)
    with pytest.raises(MemoryError, match="profile_context_changed"):
        run(home)
    monkeypatch.setattr(memory_snapshot, "current_profile_home", lambda: home)
    conn.execute("UPDATE namespace SET id='other'")
    with pytest.raises(MemoryError, match="namespace_mismatch"):
        run(home)


def test_schema_refusal_never_migrates_or_rebuilds(store):
    _, conn, path, home = store
    conn.execute("PRAGMA user_version=9")
    before = path.read_bytes()
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        run(home)
    assert path.read_bytes() == before


@pytest.mark.parametrize("fault", ["size", "time", "file_sync", "directory_sync"])
def test_failure_boundaries_and_published_uncertainty(store, monkeypatch, fault):
    _, _, path, home = store
    real_sync = os.fsync
    count = [0]

    def sync(fd):
        count[0] += 1
        if (fault == "file_sync" and count[0] == 1) or (
            fault == "directory_sync" and count[0] == 2
        ):
            raise OSError("private filesystem detail")
        return real_sync(fd)

    monkeypatch.setattr(memory_snapshot.os, "fsync", sync)
    if fault == "size":
        monkeypatch.setattr(memory_snapshot, "MAX_BYTES", 1)
    if fault == "time":
        monkeypatch.setattr(memory_snapshot, "TIMEOUT_SECONDS", -1)
    with pytest.raises(MemoryError) as caught:
        run(home)
    assert "private" not in str(caught.value)
    published = path.parent / "snapshots/before-change.sqlite3"
    assert published.exists() is (fault == "directory_sync")
    if fault == "directory_sync":
        assert caught.value.code == "snapshot_outcome_uncertain"
        assert run(home, "inspect")["records"] == 0


def test_inspect_hash_keeps_sqlite_read_lock_until_hash_finishes(store, monkeypatch):
    service, _, path, home = store
    remember(service)
    run(home)
    target = path.parent / "snapshots/before-change.sqlite3"
    real_read = os.read
    attempts = []
    writer = """import sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=0,isolation_level=None)
c.execute('BEGIN IMMEDIATE')
c.execute("UPDATE records SET topic='changed'")
try:
 c.execute('COMMIT')
 print('committed')
except sqlite3.OperationalError:
 c.execute('ROLLBACK')
 print('blocked')
c.close()
"""

    def read(fd, size):
        if size == 1024 * 1024 and not attempts:
            completed = subprocess.run(
                [sys.executable, "-c", writer, str(target)],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
            attempts.append(completed.stdout.strip())
        return real_read(fd, size)

    monkeypatch.setattr(memory_snapshot.os, "read", read)
    run(home, "inspect")
    assert attempts == ["blocked"]


def test_inspect_missing_does_not_create_live_store(store):
    service, conn, path, home = store
    service.backend.close()
    conn.close()
    path.unlink()
    with pytest.raises(MemoryError, match="snapshot_not_found"):
        run(home, "inspect")
    assert not path.exists()


def test_post_link_unlink_and_cleanup_failure_stays_uncertain(store, monkeypatch):
    from pathlib import Path

    _, _, path, home = store
    real = Path.unlink

    def fail_pending(self, *args, **kwargs):
        if self.name.startswith(".pending-"):
            raise OSError("private staged file path")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_pending)
    with pytest.raises(MemoryError) as caught:
        run(home)
    assert caught.value.code == "snapshot_outcome_uncertain"
    assert "private" not in str(caught.value)
    destination = path.parent / "snapshots/before-change.sqlite3"
    assert destination.exists() and destination.stat().st_nlink == 2
    # A crash/failed unlink can leave a hardlinked staging alias; inspect refuses
    # it rather than deleting unknown files or pretending publication is durable.
    with pytest.raises(MemoryError, match="unsafe_storage_file"):
        run(home, "inspect")


@pytest.mark.parametrize("phase", ["before_link", "after_link"])
def test_real_process_crash_publication_windows(store, phase):
    _, _, path, home = store
    script = """import os,sys
from pathlib import Path
from personal_agent import memory_snapshot as m, memory_storage
home=Path(sys.argv[1])
m.current_profile_home=lambda: home
memory_storage.current_profile_home=lambda: home
link=m.os.link
def crash_link(*args,**kwargs):
 if sys.argv[2]=='before_link': os._exit(79)
 link(*args,**kwargs)
 os._exit(79)
m.os.link=crash_link
m.snapshot(home,'snapshot_create',{'name':'crash'})
"""
    result = subprocess.run([sys.executable, "-c", script, str(home), phase], timeout=10)
    assert result.returncode == 79
    directory = path.parent / "snapshots"
    pending = list(directory.glob(".pending-*.sqlite3"))
    assert len(pending) == 1
    destination = directory / "crash.sqlite3"
    assert destination.exists() is (phase == "after_link")
    assert pending[0].stat().st_nlink == (2 if phase == "after_link" else 1)
    if destination.exists():
        with pytest.raises(MemoryError, match="unsafe_storage_file"):
            run(home, "inspect", "crash")
    # No background cleanup or implicit recovery of the unknown staged alias.
    assert pending[0].exists()


def test_create_freezes_one_snapshot_before_concurrent_forget(store, monkeypatch):
    import select

    service, _, path, home = store
    rid = remember(service)
    original = memory_snapshot._summary
    script = """import hashlib,sqlite3,sys
from pathlib import Path
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryService
home=Path(sys.argv[1]); path=Path(sys.argv[2])
c=sqlite3.connect(path,timeout=10,isolation_level=None)
b=create_backend()
b.open(c,namespace_id='trusted-profile:'+hashlib.sha256(str(home).encode()).hexdigest(),session_ref='race')
print('READY',flush=True)
assert sys.stdin.readline().strip()=='GO'
def trace(sql):
 if sql=='BEGIN IMMEDIATE': print('FORGET_BEGIN',flush=True)
c.set_trace_callback(trace)
MemoryService(b).execute('forget',{'record_id':sys.argv[3],'expected_revision':1,'request_id':'race-forget'})
c.close()
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", script, str(home), str(path), rid],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = []

    def receive(expected):
        assert select.select([proc.stdout], [], [], 5)[0], "child handshake deadline"
        assert proc.stdout.readline().strip() == expected

    def paused(conn, namespace):
        result = original(conn, namespace)
        if not started:
            started.append(True)
            proc.stdin.write("GO\n")
            proc.stdin.flush()
            receive("FORGET_BEGIN")
            assert proc.poll() is None
        return result

    try:
        receive("READY")  # initialize writer BEFORE source acquires its snapshot
        monkeypatch.setattr(memory_snapshot, "_summary", paused)
        result = run(home)
    finally:
        try:
            stdout, stderr = proc.communicate(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        assert proc.returncode == 0, stderr
    assert started == [True]
    assert result["active_records"] == 1 and result["watermark"] == 1
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT status FROM records WHERE record_id=?", (rid,)).fetchone() == (
            "forgotten",
        )
    assert run(home, "inspect")["active_records"] == 1
