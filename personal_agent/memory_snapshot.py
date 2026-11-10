"""Explicit consistent private memory snapshots. No import, restore or model API."""

import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import threading
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from . import PLUGIN_ID
from .local_memory import LocalMemoryBackend
from .memory_backend import MemoryError, _identifier, _text, validate_expiry
from .memory_coordination import memory_lock
from .memory_storage import existing_memory_path
from .task_cli import _private_database_file, _private_storage_directory, current_profile_home
from .tasks import TaskError

_METADATA_LOCK = threading.Lock()

MAX_BYTES = 128 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_ROW_BYTES = 12000
MAX_RESULT_CHARS = 80000
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
NOTICE = (
    "Plaintext historical memory snapshot: includes private records, pending candidates, "
    "source metadata and receipts. Later corrections or forgetting do not erase this copy. "
    "No import/restore, provider selection or external file publication is performed. "
    "Managed Markdown/draft files are not included; this is not a runnable profile backup. "
    "Active count includes expired but not forgotten records, not just recallable memories."
)


def validate(operation, payload):
    fields = {
        "snapshot_create": ({"name"}, set()),
        "snapshot_inspect": ({"name"}, set()),
        "snapshot_list": ({"name", "sha256"}, {"limit", "after"}),
        "snapshot_show": ({"name", "sha256", "record_id"}, set()),
    }
    if type(operation) is not str or operation not in fields or type(payload) is not dict:
        raise MemoryError("invalid_request")
    required, optional = fields[operation]
    if not required <= payload.keys() or payload.keys() - required - optional:
        raise MemoryError("invalid_request")
    if type(payload["name"]) is not str or _NAME.fullmatch(payload["name"]) is None:
        raise MemoryError("invalid_request")
    request = dict(payload)
    if "sha256" in request and (
        type(request["sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", request["sha256"]) is None
    ):
        raise MemoryError("invalid_request")
    if operation == "snapshot_list":
        request = {"limit": 10, "after": None, **request}
        if type(request["limit"]) is not int or not 1 <= request["limit"] <= 20:
            raise MemoryError("invalid_request")
        if request["after"] is not None:
            _identifier(request["after"])
    if "record_id" in request:
        _identifier(request["record_id"])
    return request


def _read_records(conn, operation, request):
    # Only canonical fields. No candidate quotes, receipts, lineage or sessions.
    fields = ("record_id", "revision", "status", "topic", "created_at", "updated_at", "expires_at")
    if operation == "snapshot_show":
        fields += ("content",)
        clause, args, limit = " WHERE record_id=?", [request["record_id"]], 1
    else:
        clause, args, limit = "", [], request["limit"]
        if request["after"] is not None:
            cursor = conn.execute(
                "SELECT sequence FROM records WHERE record_id=?", (request["after"],)
            ).fetchone()
            if cursor is None:
                raise MemoryError("invalid_cursor")
            clause, args = " WHERE sequence<?", [cursor[0]]
    sizes = "+".join(f"coalesce(length(CAST({field} AS BLOB)),0)" for field in fields)
    rows = conn.execute(
        f"SELECT sequence,({sizes}) FROM records{clause} ORDER BY sequence DESC LIMIT ?",
        [*args, limit + (operation == "snapshot_list")],
    ).fetchall()
    if not rows and operation == "snapshot_show":
        raise MemoryError("snapshot_record_not_found")
    selected = rows[:limit]
    if any(size > MAX_ROW_BYTES for _, size in selected):
        raise MemoryError("snapshot_record_too_large")
    # Worst-case ASCII JSON escaping, plus generous fixed key/envelope overhead.
    # Bound the entire selection BEFORE materializing any selected text.
    if 6 * sum(size for _, size in selected) + 1024 * len(selected) + 2048 > MAX_RESULT_CHARS:
        raise MemoryError("snapshot_result_too_large")
    items = []
    for sequence, _ in selected:
        row = conn.execute(
            f"SELECT {','.join(fields)} FROM records WHERE sequence=?", (sequence,)
        ).fetchone()
        record = dict(zip(fields, row, strict=True))
        try:
            _identifier(record["record_id"])
            if type(record["revision"]) is not int or not 1 <= record["revision"] < 2**63 - 1:
                raise ValueError()
            if record["status"] not in {"active", "forgotten"}:
                raise ValueError()
            for field in ("created_at", "updated_at"):
                value = record[field]
                if (
                    type(value) is not str
                    or re.fullmatch(
                        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)",
                        value,
                    )
                    is None
                ):
                    raise ValueError()
                datetime.fromisoformat(value)
            validate_expiry(record["expires_at"])
            if record["status"] == "forgotten":
                if any(record.get(k) is not None for k in ("topic", "content", "expires_at")):
                    raise ValueError()
            else:
                _text(record["topic"], 128, empty=True)
                if "content" in record:
                    _text(record["content"], 2048, multiline=True)
        except MemoryError, ValueError, TypeError:
            raise MemoryError("snapshot_record_invalid") from None
        items.append(record)
    more = len(rows) > limit
    result = (
        {"record": items[0]}
        if operation == "snapshot_show"
        else {
            "items": items,
            "has_more": more,
            "next_cursor": items[-1]["record_id"] if more else None,
        }
    )
    if len(json.dumps(result, ensure_ascii=True)) > MAX_RESULT_CHARS:
        raise MemoryError("snapshot_result_too_large")
    return result


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
    try:
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA query_only=ON")
        conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        return conn
    except BaseException:
        conn.close()
        raise


def _summary(conn, namespace):
    LocalMemoryBackend._validate_readonly(conn, namespace, historical_snapshot=True)
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


def _metadata(path, namespace, deadline, *, reader=None, expected_digest=None):
    # A raw fd close in another inspector can release this process's SQLite locks.
    if not _METADATA_LOCK.acquire(timeout=max(0, deadline - time.monotonic())):
        raise MemoryError("snapshot_timeout")
    try:
        return _locked_metadata(
            path, namespace, deadline, reader=reader, expected_digest=expected_digest
        )
    finally:
        _METADATA_LOCK.release()


def _locked_metadata(path, namespace, deadline, *, reader=None, expected_digest=None):
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
        sha256 = digest.hexdigest()
        if expected_digest is not None and sha256 != expected_digest:
            raise MemoryError("snapshot_changed")
        if reader is not None:
            result["historical_records"] = reader(conn)
        after = os.stat(path, follow_symlinks=False)
        if (after.st_dev, after.st_ino) != identity or after.st_size != total:
            raise MemoryError("snapshot_changed")
        return {**result, "bytes": total, "sha256": sha256}
    finally:
        try:
            if conn is not None:
                conn.close()
        finally:
            os.close(fd)


def _snapshot(bound_home: Path, operation: str, payload: dict) -> dict:
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
        if operation != "snapshot_create":
            reader = None
            if operation in {"snapshot_list", "snapshot_show"}:

                def reader(connection):
                    return _read_records(connection, operation, request)

            metadata = _metadata(
                destination,
                namespace,
                deadline,
                reader=reader,
                expected_digest=request.get("sha256"),
            )
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
                "notice": (
                    NOTICE + " Historical untrusted records only, not current status or "
                    "authority. May include later-forgotten text; output may enter host history. "
                    "Stored expiry is historical, not a current validity determination."
                    if operation in {"snapshot_list", "snapshot_show"}
                    else NOTICE
                ),
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


def snapshot(bound_home: Path, operation: str, payload: dict) -> dict:
    # Historical inspection remains available during interrupted live maintenance.
    validate(operation, payload)
    if operation == "snapshot_create":
        with memory_lock(bound_home):
            return _snapshot(bound_home, operation, payload)
    return _snapshot(bound_home, operation, payload)
