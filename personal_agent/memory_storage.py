"""Private, opt-in local memory storage. No native memory files are modified."""

import errno
import hashlib
import os
import sqlite3
import stat
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from . import PLUGIN_ID
from .local_memory import create_backend
from .memory_backend import MemoryBackend, MemoryError
from .memory_projection import PrivateProjection
from .task_cli import _private_database_file, _private_storage_directory, current_profile_home
from .tasks import TaskError


@contextmanager
def open_memory_backend(
    bound_home: Path, session_ref: str, *, source_kind: str = "explicit_local_operator"
) -> Generator[MemoryBackend]:
    """Open only the current profile's owned store; reject unsafe existing paths."""
    if not bound_home.is_dir() or current_profile_home() != bound_home:
        raise MemoryError("profile_context_changed")
    if os.name != "posix":
        raise MemoryError("unsupported_storage_platform")
    expected = bound_home / "plugin-data" / PLUGIN_ID
    directory = expected / "memory"
    try:
        for path in (bound_home, expected.parent, expected, directory):
            _private_storage_directory(path)
        from plugins.plugin_storage import plugin_data_dir  # ty: ignore[unresolved-import]

        if plugin_data_dir(PLUGIN_ID).resolve() != expected:
            raise MemoryError("unsafe_storage_path")
        directory.mkdir(mode=0o700, exist_ok=True)
        for path in (expected.parent, expected, directory):
            _private_storage_directory(path)
        path = directory / "records.sqlite3"
        for suffix in ("-journal", "-wal", "-shm"):
            _private_database_file(path.with_name(path.name + suffix), create=False)
        _private_database_file(path)
    except TaskError as error:
        raise MemoryError(error.code, retryable=error.retryable) from None
    except OSError as error:
        code = (
            "unsafe_storage_path"
            if error.errno in {errno.ELOOP, errno.ENOTDIR}
            else "local_memory_unavailable"
        )
        raise MemoryError(code) from None
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    backend = create_backend()
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA secure_delete=ON")
        namespace = "trusted-profile:" + hashlib.sha256(str(bound_home).encode()).hexdigest()
        backend.open(
            connection,
            namespace_id=namespace,
            session_ref=session_ref,
            source_kind=source_kind,
            projection=PrivateProjection(directory),
        )
        yield backend
    finally:
        backend.close()
        connection.close()


@contextmanager
def open_existing_memory_reader(bound_home: Path, session_ref: str) -> Generator[MemoryBackend]:
    """No canonical writes, creation or migration; require the owned rollback store.

    Existing sidecars and WAL are refused, not repaired. SQLite can still create
    sidecars if another process races this opener by switching to WAL; the backend
    rechecks journal mode before reading records and refuses that unsupported mode.
    This is not a VFS/filesystem read-only sandbox against unrelated same-UID code.
    """
    if not bound_home.is_dir() or current_profile_home() != bound_home:
        raise MemoryError("profile_context_changed")
    if os.name != "posix":
        raise MemoryError("unsupported_storage_platform")
    expected = bound_home / "plugin-data" / PLUGIN_ID
    directory = expected / "memory"
    path = directory / "records.sqlite3"
    try:
        for item in (bound_home, expected.parent, expected, directory):
            _private_storage_directory(item)
            if not item.is_dir():
                raise MemoryError("memory_store_missing")
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise MemoryError("memory_reader_busy", retryable=True)
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            raise MemoryError("memory_store_missing") from None
        try:
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077
            ):
                raise MemoryError("unsafe_storage_file")
            header = os.read(descriptor, 100)
            if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
                raise MemoryError("memory_reader_format_unsupported")
        finally:
            os.close(descriptor)
    except TaskError as error:
        raise MemoryError(error.code, retryable=error.retryable) from None
    except OSError:
        raise MemoryError("memory_reader_unavailable") from None
    connection = None
    backend = create_backend()
    try:
        connection = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=0.1, isolation_level=None
        )
        connection.execute("PRAGMA trusted_schema=OFF")
        namespace = "trusted-profile:" + hashlib.sha256(str(bound_home).encode()).hexdigest()
        backend.open_readonly(connection, namespace_id=namespace, session_ref=session_ref)
        yield backend
    except sqlite3.Error:
        raise MemoryError("memory_reader_unavailable") from None
    finally:
        backend.close()
        if connection is not None:
            connection.close()
