"""Private handoff ledger, separate from native boards. No raw reads of live DBs."""

import os
import sqlite3
import stat
from contextlib import contextmanager

from . import PLUGIN_ID
from .kanban_handoff_store import HandoffError, HandoffStore
from .task_cli import _private_storage_directory, current_profile_home


def _file(path, *, create=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            return
        # Never open/close an existing SQLite inode outside SQLite: that can drop
        # another same-process connection's POSIX locks.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o077
    ):
        raise HandoffError("unsafe_storage_file")


@contextmanager
def open_handoff_store(home):
    if not home.is_dir() or current_profile_home() != home:
        raise HandoffError("profile_context_changed")
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise HandoffError("unsupported_storage_platform")
    expected = home / "plugin-data" / PLUGIN_ID
    directory = expected / "kanban-handoff"
    for item in (home, expected.parent, expected, directory):
        _private_storage_directory(item)
    from plugins.plugin_storage import plugin_data_dir  # ty: ignore[unresolved-import]

    if plugin_data_dir(PLUGIN_ID).resolve() != expected:
        raise HandoffError("unsafe_storage_path")
    directory.mkdir(mode=0o700, exist_ok=True)
    for item in (expected.parent, expected, directory):
        _private_storage_directory(item)
    path = directory / "receipts.sqlite3"
    for suffix in ("-journal", "-wal", "-shm"):
        _file(path.with_name(path.name + suffix))
    _file(path, create=True)
    connection = sqlite3.connect(path, timeout=1, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise HandoffError("unsupported_ledger_journal")
        store = HandoffStore(connection)
        store.initialize()
        yield store
    finally:
        connection.close()
