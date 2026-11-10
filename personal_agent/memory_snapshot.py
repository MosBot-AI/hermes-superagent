"""Explicit consistent private memory snapshots. No import, restore or model API."""

import hashlib
import os
import re
import sqlite3
import stat
import tempfile
import time
from contextlib import suppress
from pathlib import Path

from . import PLUGIN_ID
from .local_memory import LocalMemoryBackend
from .memory_backend import MemoryError
from .memory_storage import existing_memory_path
from .task_cli import _private_database_file, _private_storage_directory, current_profile_home
from .tasks import TaskError

MAX_BYTES = 128 * 1024 * 1024
TIMEOUT_SECONDS = 30
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
NOTICE = (
    "Plaintext historical memory snapshot: includes private records, pending candidates, "
    "source metadata and receipts. Later corrections or forgetting do not erase this copy. "
    "No import/restore, provider selection or external file publication is performed. "
    "Managed Markdown/draft files are not included; this is not a runnable profile backup. "
    "Active count includes expired but not forgotten records, not just recallable memories."
)


def validate(operation, payload):
    if (
        type(operation) is not str
        or operation not in {"snapshot_create", "snapshot_inspect"}
        or type(payload) is not dict
        or payload.keys() != {"name"}
        or type(payload["name"]) is not str
        or _NAME.fullmatch(payload["name"]) is None
    ):
        raise MemoryError("invalid_request")
    return dict(payload)


def _check(path):
    _private_database_file(path, create=False)
    if not path.exists():
        raise MemoryError("snapshot_not_found")
    if path.stat().st_size > MAX_BYTES:
        raise MemoryError("snapshot_size_limit")
    if any(
        path.with_name(path.name + s).exists() or path.with_name(path.name + s).is_symlink()
        for s in ("-wal", "-shm", "-journal")
    ):
        raise MemoryError("snapshot_sidecar_present")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise MemoryError("unsafe_storage_file")
        header = os.read(fd, 20)
        if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
            raise MemoryError("snapshot_not_standalone")
        return info.st_dev, info.st_ino
    finally:
        os.close(fd)


def _connect(path, deadline):
    conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1, isolation_level=None)
    conn.execute("PRAGMA trusted_schema=OFF")
    conn.execute("PRAGMA query_only=ON")
    conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    return conn


def _summary(conn, namespace):
    LocalMemoryBackend._validate_readonly(conn, namespace)
    if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise MemoryError("snapshot_corrupt")
    return {
        "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "namespace_id": namespace,
        "watermark": conn.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0],
        "records": conn.execute("SELECT count(*) FROM records").fetchone()[0],
        "active_records": conn.execute(
            "SELECT count(*) FROM records WHERE status='active'"
        ).fetchone()[0],
        "tombstones": conn.execute(
            "SELECT count(*) FROM records WHERE status='forgotten'"
        ).fetchone()[0],
    }


def _metadata(path, namespace, deadline):
    identity = _check(path)
    # Keep this fd open until AFTER SQLite closes: closing another fd to the
    # same inode would drop this process's POSIX SQLite locks.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    conn = None
    try:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != identity or info.st_nlink != 1:
            raise MemoryError("snapshot_changed")
        conn = _connect(path, deadline)
        conn.execute("BEGIN")
        result = _summary(conn, namespace)
        digest = hashlib.sha256()
        total = 0
        while block := os.read(fd, 1024 * 1024):
            total += len(block)
            if total > MAX_BYTES:
                raise MemoryError("snapshot_size_limit")
            if time.monotonic() >= deadline:
                raise MemoryError("snapshot_timeout")
            digest.update(block)
        after = os.stat(path, follow_symlinks=False)
        if (after.st_dev, after.st_ino) != identity or after.st_size != total:
            raise MemoryError("snapshot_changed")
        return {**result, "bytes": total, "sha256": digest.hexdigest()}
    finally:
        if conn is not None:
            conn.close()
        os.close(fd)


def snapshot(bound_home: Path, operation: str, payload: dict) -> dict:
    """Current trusted-profile operator only; caller must recheck mode/config first."""
    request = validate(operation, payload)
    published = False
    temporary = None
    conn = None
    try:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise MemoryError("unsupported_storage_platform")
        if not bound_home.is_dir() or current_profile_home() != bound_home:
            raise MemoryError("profile_context_changed")
        directory = bound_home / "plugin-data" / PLUGIN_ID / "memory"
        snapshots = directory / "snapshots"
        for parent in (bound_home, directory.parent.parent, directory.parent, directory, snapshots):
            _private_storage_directory(parent)
        if not directory.is_dir():
            raise MemoryError("memory_store_missing")
        if operation == "snapshot_create":
            snapshots.mkdir(mode=0o700, exist_ok=True)
        if not snapshots.is_dir():
            raise MemoryError("snapshot_not_found")
        if stat.S_IMODE(snapshots.stat().st_mode) & 0o077:
            raise MemoryError("unsafe_storage_path")
        destination = snapshots / (request["name"] + ".sqlite3")
        namespace = "trusted-profile:" + hashlib.sha256(str(bound_home).encode()).hexdigest()
        deadline = time.monotonic() + TIMEOUT_SECONDS
        if operation == "snapshot_inspect":
            metadata = _metadata(destination, namespace, deadline)
        else:
            if destination.exists() or destination.is_symlink():
                raise MemoryError("snapshot_exists")
            source = existing_memory_path(bound_home)
            # Do not raw-open/close the live inode: that can drop locks held
            # by another SQLite connection in this process. The supported store
            # is DELETE-journal; native SQLite validation below rejects WAL.
            if source.stat().st_size > MAX_BYTES:
                raise MemoryError("snapshot_size_limit")
            conn = _connect(source, deadline)
            conn.execute("BEGIN")
            _summary(conn, namespace)  # establishes one immutable source read snapshot
            size = conn.execute("PRAGMA page_size").fetchone()[0]
            if size * conn.execute("PRAGMA page_count").fetchone()[0] > MAX_BYTES:
                raise MemoryError("snapshot_size_limit")
            fd, filename = tempfile.mkstemp(prefix=".pending-", suffix=".sqlite3", dir=snapshots)
            os.close(fd)
            temporary = Path(filename)
            target = sqlite3.connect(temporary, isolation_level=None)
            try:

                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise MemoryError("snapshot_timeout")
                    if total * size > MAX_BYTES:
                        raise MemoryError("snapshot_size_limit")

                conn.backup(target, pages=128, progress=progress, sleep=0.01)
                target.execute("PRAGMA journal_mode=DELETE")
                target.execute("PRAGMA synchronous=FULL")
            finally:
                target.close()
            metadata = _metadata(temporary, namespace, deadline)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                raise MemoryError("snapshot_exists") from None
            published = True
            temporary.unlink()
            temporary = None
            fd = os.open(snapshots, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return {
            "data": {
                "name": request["name"],
                **metadata,
                "scope": "historical_memory_database",
                "restorable": False,
                "notice": NOTICE,
            },
            "replayed": False,
        }
    except Exception as error:
        if published:
            raise MemoryError("snapshot_outcome_uncertain") from None
        if isinstance(error, MemoryError):
            raise
        if isinstance(error, TaskError):
            raise MemoryError(error.code) from None
        raise MemoryError("snapshot_unavailable") from None
    finally:
        if conn is not None:
            conn.close()
        if temporary is not None:
            # Only our own randomly named staging file, never an unknown target.
            # Best-effort only: cleanup must not replace a redacted uncertain
            # publication result with a raw path-bearing filesystem exception.
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            for suffix in ("-journal", "-wal", "-shm"):
                with suppress(OSError):
                    temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
