"""Private ledger opener checks using synthetic profile paths only."""

import os
import sqlite3
import sys
from types import ModuleType

import pytest

from personal_agent import PLUGIN_ID
from personal_agent import kanban_handoff_storage as storage
from personal_agent.kanban_handoff_store import HandoffError
from personal_agent.tasks import TaskError


@pytest.fixture
def home(monkeypatch, tmp_path):
    tmp_path.chmod(0o700)
    monkeypatch.setattr(storage, "current_profile_home", lambda: tmp_path)
    parent = ModuleType("plugins")
    module = ModuleType("plugins.plugin_storage")

    def plugin_data_dir(plugin):
        assert plugin == PLUGIN_ID
        path = tmp_path / "plugin-data" / plugin
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        return path

    module.plugin_data_dir = plugin_data_dir
    monkeypatch.setitem(sys.modules, "plugins", parent)
    monkeypatch.setitem(sys.modules, "plugins.plugin_storage", module)
    return tmp_path


def ledger_path(home):
    return home / "plugin-data" / PLUGIN_ID / "kanban-handoff" / "receipts.sqlite3"


def test_private_owned_store_reopens_and_never_changes_journal(home):
    with storage.open_handoff_store(home) as store:
        assert store.list(1, None, 0)["items"] == []
        assert store.connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert store.connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
    assert ledger_path(home).stat().st_mode & 0o777 == 0o600
    with storage.open_handoff_store(home) as store:
        assert store.list(1, None, 0)["items"] == []


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "public", "directory"])
def test_unsafe_main_file_refused_unchanged(home, kind):
    path = ledger_path(home)
    path.parent.mkdir(parents=True, mode=0o700)
    other = home / "other"
    other.write_text("synthetic")
    other.chmod(0o600)
    if kind == "symlink":
        path.symlink_to(other)
    elif kind == "hardlink":
        os.link(other, path)
    elif kind == "public":
        path.write_text("synthetic")
        path.chmod(0o644)
    else:
        path.mkdir()
    with pytest.raises(HandoffError, match="unsafe_storage_file"):
        with storage.open_handoff_store(home):
            pytest.fail("unsafe opened")
    assert other.read_text() == "synthetic"


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
def test_unsafe_sidecars_refused(home, suffix):
    path = ledger_path(home)
    path.parent.mkdir(parents=True, mode=0o700)
    sidecar = path.with_name(path.name + suffix)
    sidecar.write_text("synthetic")
    sidecar.chmod(0o644)
    with pytest.raises(HandoffError, match="unsafe_storage_file"):
        with storage.open_handoff_store(home):
            pytest.fail("unsafe sidecar opened")
    assert not path.exists()


def test_profile_change_before_creating_any_storage(home, monkeypatch):
    monkeypatch.setattr(storage, "current_profile_home", lambda: home / "other")
    with pytest.raises(HandoffError, match="profile_context_changed"):
        with storage.open_handoff_store(home):
            pytest.fail("wrong profile")
    assert not (home / "plugin-data").exists()


def test_unsafe_directory_and_foreign_database_refused(home):
    path = ledger_path(home)
    path.parent.mkdir(parents=True, mode=0o700)
    path.parent.chmod(0o777)
    with pytest.raises(TaskError, match="unsafe_storage_path"):
        with storage.open_handoff_store(home):
            pytest.fail("unsafe directory")
    path.parent.chmod(0o700)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE foreign_data(x)")
    path.chmod(0o600)
    with pytest.raises(HandoffError, match="foreign_database"):
        with storage.open_handoff_store(home):
            pytest.fail("foreign database")


def test_existing_inode_check_does_not_open_close_file(home, monkeypatch):
    path = ledger_path(home)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    path.chmod(0o600)

    def forbidden(*args, **kwargs):
        pytest.fail("existing SQLite inode must not be opened/closed by safety check")

    monkeypatch.setattr(storage.os, "open", forbidden)
    storage._file(path, create=True)
