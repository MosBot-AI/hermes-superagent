"""Private, opt-in local memory storage. No native memory files are modified."""

import errno
import hashlib
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from . import PLUGIN_ID
from .local_memory import create_backend
from .memory_backend import MemoryBackend, MemoryError
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
        )
        yield backend
    finally:
        backend.close()
        connection.close()
