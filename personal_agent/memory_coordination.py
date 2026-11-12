"""Cooperative POSIX memory maintenance fence for updated controlled openers.

Old runtimes must be stopped before upgrading. This is not authority against
unmanaged same-UID code. The fixed lock inode must never be removed or replaced.
"""

import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from . import PLUGIN_ID
from .memory_backend import MemoryError
from .memory_sessions import ResourceScope
from .task_cli import _private_storage_directory
from .tasks import TaskError

LOCK_NAME = ".coordination.lock"
JOURNAL_NAME = ".maintenance.json"
LOCK_TIMEOUT_SECONDS = 5.0


@contextmanager
def memory_lock(
    bound_home: Path,
    *,
    exclusive: bool = False,
    create_directory: bool = False,
    timeout: float | None = None,
):
    """Hold shared access for a complete opener, or exclusive maintenance.

    Exclusive callers own journal validation/recovery; shared callers refuse any
    journal entry, including malformed files/symlinks. Never recursively acquire.
    Creating a coordination inode is allowed for an existing read-only store,
    but this helper never creates or opens a database.
    """
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise MemoryError("unsupported_storage_platform")
    import fcntl

    from .memory_storage import current_profile_home

    if not bound_home.is_dir() or current_profile_home() != bound_home:
        raise MemoryError("profile_context_changed")
    directory = bound_home / "plugin-data" / PLUGIN_ID / "memory"
    resources = ResourceScope()
    entered = False
    primary = None
    try:
        for item in (bound_home, directory.parent.parent, directory.parent, directory):
            _private_storage_directory(item)
        if create_directory:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            for item in (directory.parent.parent, directory.parent, directory):
                _private_storage_directory(item)
        if not directory.is_dir():
            raise MemoryError("memory_store_missing")
        path = directory / LOCK_NAME
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        resources.register(lambda: os.close(fd))
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise MemoryError("unsafe_storage_file")
        deadline = time.monotonic() + (LOCK_TIMEOUT_SECONDS if timeout is None else timeout)
        while True:
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MemoryError("memory_maintenance_busy", retryable=True) from None
                time.sleep(min(0.01, remaining))
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise MemoryError("unsafe_storage_file")
        if not exclusive:
            try:
                (directory / JOURNAL_NAME).lstat()
            except FileNotFoundError:
                pass
            else:
                raise MemoryError("memory_maintenance_pending")
        entered = True
        yield directory
    except TaskError as error:
        primary = error
        if entered:
            raise
        raise MemoryError(error.code) from None
    except OSError as error:
        primary = error
        if entered:
            raise
        raise MemoryError("memory_coordination_unavailable") from None
    except BaseException as error:
        primary = error
        raise
    finally:
        resources.close(primary=primary)


@contextmanager
def coordination(bound_home: Path, *, exclusive=False, allow_pending=False):
    """Maintenance engine entry; only exclusive recovery may bypass pending guard."""
    if allow_pending and not exclusive:
        raise MemoryError("invalid_request")
    with memory_lock(bound_home, exclusive=exclusive) as directory:
        if exclusive and not allow_pending:
            try:
                (directory / JOURNAL_NAME).lstat()
            except FileNotFoundError:
                pass
            else:
                raise MemoryError("memory_maintenance_pending")
        yield directory
