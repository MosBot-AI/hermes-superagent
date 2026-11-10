"""Actual process coordination, not a claim about old runtimes or same-UID code."""

import os
import subprocess
import sys
from contextlib import contextmanager

import pytest

from personal_agent import PLUGIN_ID, memory_index, memory_snapshot, memory_storage
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_coordination import JOURNAL_NAME, LOCK_NAME, coordination, memory_lock


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "plugin-data" / PLUGIN_ID / "memory").mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(memory_storage, "current_profile_home", lambda: home)
    return home


@contextmanager
def child_lock(home, exclusive=False):
    code = """
import sys
from pathlib import Path
from personal_agent import memory_storage
from personal_agent.memory_coordination import memory_lock
home=Path(sys.argv[1])
memory_storage.current_profile_home=lambda:home
with memory_lock(home, exclusive=sys.argv[2]=='yes'):
 print('locked',flush=True)
 sys.stdin.readline()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(home), "yes" if exclusive else "no"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout.readline().strip() == "locked"
        yield child
    finally:
        child.communicate("release\n", timeout=5)
        assert child.returncode == 0


def test_process_shared_access_blocks_exclusive_maintenance(home):
    with child_lock(home):
        with pytest.raises(MemoryError, match="memory_maintenance_busy"):
            with memory_lock(home, exclusive=True, timeout=0.05):
                pytest.fail("maintenance admitted while opener holds shared lock")
        with memory_lock(home, timeout=0.05):
            pass
    with memory_lock(home, exclusive=True, timeout=0.05) as directory:
        inode = (directory / LOCK_NAME).stat().st_ino
    assert (directory / LOCK_NAME).stat().st_ino == inode


def test_process_exclusive_blocks_new_reader(home):
    with child_lock(home, exclusive=True):
        with pytest.raises(MemoryError, match="memory_maintenance_busy"):
            with memory_lock(home, timeout=0.05):
                pytest.fail("reader admitted")


@pytest.mark.parametrize("kind", ["file", "symlink", "directory"])
def test_pending_marker_refuses_every_live_path(home, kind):
    directory = home / "plugin-data" / PLUGIN_ID / "memory"
    marker = directory / JOURNAL_NAME
    if kind == "file":
        marker.write_text("malformed interrupted state")
    elif kind == "symlink":
        marker.symlink_to(directory / "missing")
    else:
        marker.mkdir()
    for call in (
        lambda: memory_storage.open_memory_backend(home, "synthetic"),
        lambda: memory_storage.open_existing_memory_reader(home, "synthetic"),
    ):
        with pytest.raises(MemoryError, match="memory_maintenance_pending"):
            with call():
                pytest.fail("live opener admitted")
    for call in (
        lambda: memory_index.maintain(home, "index_status", {}),
        lambda: memory_snapshot.snapshot(home, "snapshot_create", {"name": "synthetic"}),
    ):
        with pytest.raises(MemoryError, match="memory_maintenance_pending"):
            call()
    assert not (directory / "records.sqlite3").exists()
    with coordination(home, exclusive=True, allow_pending=True):
        pass


def test_existing_reader_does_not_create_missing_database(home):
    with pytest.raises(MemoryError, match="memory_store_missing"):
        with memory_storage.open_existing_memory_reader(home, "synthetic"):
            pytest.fail("missing database opened")
    assert not (home / "plugin-data" / PLUGIN_ID / "memory/records.sqlite3").exists()


@pytest.mark.parametrize("kind", ["symlink", "public", "hardlink"])
def test_unsafe_lock_inode_refused(home, kind):
    directory = home / "plugin-data" / PLUGIN_ID / "memory"
    lock = directory / LOCK_NAME
    if kind == "symlink":
        lock.symlink_to(directory / "missing")
    else:
        lock.write_text("")
        lock.chmod(0o600 if kind == "hardlink" else 0o644)
        if kind == "hardlink":
            os.link(lock, directory / "alias")
    with pytest.raises(MemoryError):
        with memory_lock(home):
            pytest.fail("unsafe lock accepted")


@pytest.mark.parametrize("reader", [False, True])
def test_wrapper_holds_lock_through_backend_cleanup(home, monkeypatch, reader):
    # A separate child attempts EX on the actual inode during yield AND cleanup.
    code = """
import sys
from pathlib import Path
from personal_agent import memory_storage
from personal_agent.memory_coordination import memory_lock
from personal_agent.memory_backend import MemoryError
home=Path(sys.argv[1]);memory_storage.current_profile_home=lambda:home
try:
 with memory_lock(home,exclusive=True,timeout=0.03):pass
except MemoryError as error:
 assert error.code=='memory_maintenance_busy';sys.exit(0)
sys.exit(1)
"""

    def verify_blocked():
        result = subprocess.run([sys.executable, "-c", code, str(home)], timeout=5)
        assert result.returncode == 0

    @contextmanager
    def inner(*args, **kwargs):
        try:
            yield object()
        finally:
            verify_blocked()

    name = "_open_existing_memory_reader" if reader else "_open_memory_backend"
    monkeypatch.setattr(memory_storage, name, inner)
    opened = (
        memory_storage.open_existing_memory_reader if reader else memory_storage.open_memory_backend
    )
    with opened(home, "synthetic"):
        verify_blocked()
    with memory_lock(home, exclusive=True, timeout=0.03):
        pass


@pytest.mark.parametrize("exclusive", [False, True])
def test_body_io_error_keeps_identity_and_releases_lock(home, exclusive):
    error = OSError("synthetic body failure after possible mutation")
    with pytest.raises(OSError) as caught:
        with memory_lock(home, exclusive=exclusive):
            raise error
    assert caught.value is error
    with memory_lock(home, exclusive=True, timeout=0.03):
        pass
