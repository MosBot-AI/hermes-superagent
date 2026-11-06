"""Unwired, default-disabled persistence for prospective enrollment records.

This is an internal developer/storage boundary, not an identity adapter. No
plugin config, command, tool or handler calls it. ``enabled=True`` permits local
storage I/O only; it cannot authenticate anyone or enable protected reads.
POSIX ownership/mode checks reduce accidental exposure, not malicious same-UID
processes, filesystem races, database tampering or restored/cloned authorities.
"""

import os
import sqlite3
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from . import PLUGIN_ID
from .enrollment import EnrollmentError, EnrollmentStore


def _profile_home() -> Path:
    from hermes_constants import get_hermes_home  # ty: ignore[unresolved-import]

    return get_hermes_home().resolve()


def _directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise EnrollmentError("unsafe_storage_path")


def _file(path: Path, *, create: bool = False) -> None:
    flags = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if create:
        flags |= os.O_CREAT
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileNotFoundError:
        if not create:
            return
        raise
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise EnrollmentError("unsafe_storage_file")
    finally:
        os.close(descriptor)


@contextmanager
def open_enrollment_store(bound_home: Path, *, enabled: bool = False) -> Generator[EnrollmentStore]:
    """Explicit internal opt-in; never treat a profile path as owner proof.

    Validate every open against the host's current profile. Reject unsafe files
    without repairing permissions, following links, or importing old task data.
    No path/database-name override or WAL opt-in is offered. Existing records are
    prospective metadata, not current authenticated authorization after restart.
    """
    if type(enabled) is not bool:
        raise EnrollmentError("invalid_configuration")
    if not enabled:
        raise EnrollmentError("enrollment_storage_disabled")
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise EnrollmentError("unsupported_storage_platform")
    connection = None
    try:
        if (
            not isinstance(bound_home, Path)
            or not bound_home.is_absolute()
            or not bound_home.is_dir()
            or bound_home.resolve() != bound_home
            or _profile_home() != bound_home
        ):
            raise EnrollmentError("profile_context_changed")
        expected = bound_home / "plugin-data" / PLUGIN_ID
        for directory in (bound_home, expected.parent, expected):
            _directory(directory)
        from plugins.plugin_storage import plugin_data_dir  # ty: ignore[unresolved-import]

        directory = plugin_data_dir(PLUGIN_ID)
        if (
            directory != expected
            or directory.resolve() != expected
            or _profile_home() != bound_home
        ):
            raise EnrollmentError("profile_context_changed")
        for directory in (bound_home, expected.parent, expected):
            _directory(directory)
        path = expected / "enrollment.sqlite3"
        for suffix in ("-journal", "-wal", "-shm"):
            _file(path.with_name(path.name + suffix))
        _file(path, create=True)
        connection = sqlite3.connect(path, timeout=5, isolation_level=None)
        # Refuse rather than silently convert a store created in an unsupported
        # mode. Do not bypass the host's WAL compatibility gate.
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise EnrollmentError("unsupported_storage_journal")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        store = EnrollmentStore(connection)
        store.initialize()
    except BaseException as error:
        if connection is not None:
            connection.close()
        if isinstance(error, EnrollmentError) or not isinstance(error, Exception):
            raise
        raise EnrollmentError("enrollment_storage_unavailable") from None
    try:
        yield store
    finally:
        connection.close()
