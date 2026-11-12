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
from .memory_coordination import memory_lock
from .memory_edits import PrivateEdits
from .memory_projection import PrivateProjection
from .memory_sessions import LocalBinding, ResourceScope, SessionMode, managed_backend
from .task_cli import _private_database_file, _private_storage_directory, current_profile_home
from .tasks import TaskError


@contextmanager
def _open_memory_backend(
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
    binding = _binding(bound_home, session_ref, source_kind)
    with managed_backend(SQLiteMemoryFactory(path, directory), binding, mode="writable") as opened:
        yield opened[0]


def existing_memory_path(bound_home: Path, *, allow_journal: bool = False) -> Path:
    """Validate existing paths without opening/closing the database inode.

    Closing a raw descriptor can release another connection's POSIX locks.
    Maintenance permits a safe rollback journal for SQLite's own recovery only.
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
            if allow_journal and suffix == "-journal":
                _private_database_file(sidecar, create=False)
                continue
            if sidecar.exists() or sidecar.is_symlink():
                raise MemoryError("memory_reader_busy", retryable=True)
        _private_database_file(path, create=False)
        if not path.exists():
            raise MemoryError("memory_store_missing")
        return path
    except TaskError as error:
        raise MemoryError(error.code, retryable=error.retryable) from None
    except OSError:
        raise MemoryError("memory_reader_unavailable") from None


@contextmanager
def _open_existing_memory_reader(bound_home: Path, session_ref: str) -> Generator[MemoryBackend]:
    """No canonical writes, creation or migration; require the owned rollback store.

    Existing sidecars and WAL are refused, not repaired. SQLite can still create
    sidecars if another process races this opener by switching to WAL; the backend
    rechecks journal mode before reading records and refuses that unsupported mode.
    This is not a VFS/filesystem read-only sandbox against unrelated same-UID code.
    """
    path = existing_memory_path(bound_home)
    header_resources = ResourceScope()
    header_primary = None
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
            header_resources.register(lambda: os.close(descriptor))
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
        except BaseException as error:
            header_primary = error
            raise
        finally:
            header_resources.close(primary=header_primary)
    except TaskError as error:
        raise MemoryError(error.code, retryable=error.retryable) from None
    except OSError:
        raise MemoryError("memory_reader_unavailable") from None
    entered = False
    try:
        with managed_backend(
            SQLiteMemoryFactory(path, path.parent),
            _binding(bound_home, session_ref),
            mode="readonly",
        ) as opened:
            entered = True
            yield opened[0]
    except sqlite3.Error:
        if entered:
            raise
        raise MemoryError("memory_reader_unavailable") from None


def _binding(bound_home, session_ref, source_kind="explicit_local_operator"):
    namespace = "trusted-profile:" + hashlib.sha256(str(bound_home).encode()).hexdigest()
    return LocalBinding(namespace, session_ref, source_kind)


class SQLiteMemoryFactory:
    """Bundled resource factory for paths already admitted by the storage boundary.

    This is trusted internal code, not a path validation or profile authorization
    API. Direct callers must supply separately reviewed, isolated resources.
    Maintenance, projection and source authority remain SQLite-specific.
    """

    factory_version = 1

    def __init__(self, path: Path, directory: Path):
        self.path, self.directory = path, directory

    def acquire(
        self, resources: ResourceScope, binding: LocalBinding, mode: SessionMode
    ) -> MemoryBackend:
        if mode == "readonly":
            connection = sqlite3.connect(
                self.path.as_uri() + "?mode=ro", uri=True, timeout=0.1, isolation_level=None
            )
        else:
            connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        resources.register(connection.close)
        backend = create_backend()
        resources.register(backend.close)
        connection.execute("PRAGMA trusted_schema=OFF")
        if mode == "readonly":
            backend.open_readonly(
                connection, namespace_id=binding.namespace_id, session_ref=binding.session_ref
            )
        else:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA secure_delete=ON")
            backend.open(
                connection,
                namespace_id=binding.namespace_id,
                session_ref=binding.session_ref,
                source_kind=binding.source_kind,
                projection=PrivateProjection(self.directory),
                edits=PrivateEdits(self.directory),
            )
        return backend


@contextmanager
def open_memory_backend(
    bound_home: Path, session_ref: str, *, source_kind="explicit_local_operator"
):
    """Coordinate the entire backend and derivative publication lifetime."""
    with memory_lock(bound_home, create_directory=True):
        with _open_memory_backend(bound_home, session_ref, source_kind=source_kind) as backend:
            yield backend


@contextmanager
def open_existing_memory_reader(bound_home: Path, session_ref: str):
    """Existing-only database read held behind the maintenance fence."""
    with memory_lock(bound_home):
        with _open_existing_memory_reader(bound_home, session_ref) as backend:
            yield backend
