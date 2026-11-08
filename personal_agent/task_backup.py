"""Explicit local-operator task snapshots; no restore, automatic export or model tool."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
import time
from pathlib import Path

from . import PLUGIN_ID
from .task_cli import (
    _private_database_file,
    _private_storage_directory,
    current_profile_home,
)
from .tasks import _COLUMNS, TaskError, _task_id, inspect_task_snapshot

MAX_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 30
MAX_RESULT_CHARS = 80000
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def setup_backup_cli(parent: argparse._SubParsersAction) -> None:
    parser = parent.add_parser(
        "task-backup", help="Create, inspect or read historical tasks from private local snapshots"
    )
    commands = parser.add_subparsers(dest="backup_operation", required=True)
    for operation in ("create", "inspect", "tasks", "show"):
        command = commands.add_parser(operation)
        command.add_argument("--name", required=True, help="1-64 ASCII letters, digits, _ or -")
        if operation in ("tasks", "show"):
            command.add_argument("--sha256", required=True, help="Digest from create or inspect")
        if operation == "tasks":
            command.add_argument("--after", help="Task ID from the preceding page")
            command.add_argument("--limit", type=int, default=10)
        if operation == "show":
            command.add_argument("--task-id", required=True)


def _check_file(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        raise TaskError("backup_not_found")
    _private_database_file(path, create=False)
    if path.stat().st_size > MAX_BYTES:
        raise TaskError("backup_size_limit")


def _connection(path: Path, deadline: float) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=1, isolation_level=None
    )
    connection.execute("PRAGMA trusted_schema=OFF")
    connection.execute("PRAGMA query_only=ON")
    connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    return connection


def _metadata(path: Path, deadline: float, *, reader=None, expected_digest=None) -> dict:
    _check_file(path)
    # Published snapshots use DELETE journaling. Refuse sidecars rather than
    # silently inspecting a changed, concurrently written or incomplete backup.
    if any(
        path.with_name(path.name + suffix).exists()
        or path.with_name(path.name + suffix).is_symlink()
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise TaskError("backup_sidecar_present")
    # Even mode=ro can create WAL/SHM files for a closed WAL-mode database.
    # Published snapshots must be DELETE-journal files before SQLite opens them.
    with path.open("rb") as stream:
        header = stream.read(20)
    if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
        raise TaskError("backup_not_standalone")
    connection = _connection(path, deadline)
    try:
        connection.execute("BEGIN")
        result = inspect_task_snapshot(connection)
        # Keep the read lock while hashing and reading payload. Ordinary SQLite
        # writers cannot commit a different DELETE-journal snapshot underneath us.
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                if time.monotonic() >= deadline:
                    raise TaskError("backup_timeout")
                digest.update(block)
        sha256 = digest.hexdigest()
        if expected_digest is not None and sha256 != expected_digest:
            raise TaskError("backup_changed")
        if reader is not None:
            result["historical_tasks"] = reader(connection)
        return {**result, "bytes": path.stat().st_size, "sha256": sha256}
    finally:
        connection.close()


def _read_tasks(connection, operation, *, after, limit, task_id):
    # No receipts or native observations: historical task data is not execution
    # authority. Bound values in SQL before materializing potentially altered data.
    columns = (
        ("id", "title", "state", "revision", "due_date", "project", "work_status")
        if operation == "tasks"
        else _COLUMNS
    )
    args = []
    if operation == "show":
        clause = " WHERE id = ?"
        args.append(task_id)
    elif after is not None:
        cursor = connection.execute("SELECT sequence FROM tasks WHERE id = ?", (after,)).fetchone()
        if cursor is None:
            raise TaskError("invalid_cursor")
        clause = " WHERE sequence < ?"
        args.append(cursor[0])
    else:
        clause = ""
    args.append(limit + 1 if operation == "tasks" else 1)
    lengths = "+".join(f"coalesce(length(CAST({column} AS BLOB)),0)" for column in columns)
    # Only bounded rows are loaded; an oversized row fails rather than silently
    # disappearing from recovery results or being truncated into a different task.
    rows = connection.execute(
        f"SELECT sequence,({lengths}) FROM tasks{clause} ORDER BY sequence DESC LIMIT ?", args
    ).fetchall()
    if operation == "show" and not rows:
        raise TaskError("not_found")
    more = operation == "tasks" and len(rows) > limit
    items = []
    for sequence, size in rows[:limit]:
        if size > 32000:
            raise TaskError("backup_record_too_large")
        row = connection.execute(
            f"SELECT {','.join(columns)} FROM tasks WHERE sequence=?", (sequence,)
        ).fetchone()
        items.append(dict(zip(columns, row, strict=True)))
    output = (
        {"items": items, "has_more": more, "next_cursor": items[-1]["id"] if more else None}
        if operation == "tasks"
        else {"task": items[0]}
    )
    try:
        if len(json.dumps(output, ensure_ascii=True)) > MAX_RESULT_CHARS:
            raise TaskError("backup_result_too_large")
    except TypeError, ValueError:
        raise TaskError("storage_corrupt") from None
    return output


def task_backup(
    bound_home: Path, operation: str, name: str, *, sha256=None, after=None, limit=10, task_id=None
) -> dict:
    """Create without replacement, inspect metadata or read historical task fields."""
    if (
        operation not in ("create", "inspect", "tasks", "show")
        or type(name) is not str
        or not _NAME.fullmatch(name)
    ):
        raise TaskError("invalid_request")
    if operation in ("tasks", "show"):
        if type(sha256) is not str or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
            raise TaskError("invalid_request")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise TaskError("invalid_request")
        if after is not None:
            _task_id(after)
        if operation == "show":
            _task_id(task_id)
            if after is not None or limit != 10:
                raise TaskError("invalid_request")
        elif task_id is not None:
            raise TaskError("invalid_request")
    elif sha256 is not None or after is not None or task_id is not None or limit != 10:
        raise TaskError("invalid_request")
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise TaskError("unsupported_storage_platform")
    if not bound_home.is_dir() or current_profile_home() != bound_home:
        raise TaskError("profile_context_changed")
    directory = bound_home / "plugin-data" / PLUGIN_ID
    backups = directory / "task-backups"
    for parent in (bound_home, directory.parent, directory, backups):
        _private_storage_directory(parent)
    if not directory.is_dir():
        raise TaskError("backup_not_found")
    if operation == "create":
        backups.mkdir(mode=0o700, exist_ok=True)
    if not backups.is_dir():
        raise TaskError("backup_not_found")
    if stat.S_IMODE(backups.stat().st_mode) & 0o077:
        raise TaskError("unsafe_storage_path")
    destination = backups / (name + ".sqlite3")
    deadline = time.monotonic() + TIMEOUT_SECONDS
    if operation in ("inspect", "tasks", "show"):
        reader = None
        if operation in ("tasks", "show"):

            def reader(connection):
                return _read_tasks(connection, operation, after=after, limit=limit, task_id=task_id)

        metadata = _metadata(destination, deadline, reader=reader, expected_digest=sha256)
    else:
        if destination.exists() or destination.is_symlink():
            raise TaskError("backup_exists")
        source = directory / "tasks.sqlite3"
        _check_file(source)
        for suffix in ("-journal", "-wal", "-shm"):
            _private_database_file(source.with_name(source.name + suffix), create=False)
        connection = _connection(source, deadline)
        temporary = None
        try:
            connection.execute("BEGIN")
            # Read/validate in the same transaction used by the backup API.
            # No initialization, migration or checkpoint is performed.
            inspect_task_snapshot(connection)
            size = connection.execute("PRAGMA page_size").fetchone()[0]
            pages = connection.execute("PRAGMA page_count").fetchone()[0]
            if size * pages > MAX_BYTES:
                raise TaskError("backup_size_limit")
            fd, filename = tempfile.mkstemp(prefix=".pending-", suffix=".sqlite3", dir=backups)
            os.close(fd)
            temporary = Path(filename)
            target = sqlite3.connect(temporary, isolation_level=None)
            try:

                def progress(status, remaining, total):
                    if time.monotonic() >= deadline:
                        raise TaskError("backup_timeout")
                    if total * size > MAX_BYTES:
                        raise TaskError("backup_size_limit")

                connection.backup(target, pages=128, progress=progress, sleep=0.01)
                # A WAL source must produce a standalone, sidecar-free snapshot.
                target.execute("PRAGMA journal_mode=DELETE")
                target.execute("PRAGMA synchronous=FULL")
            finally:
                target.close()
            metadata = _metadata(temporary, deadline)
            with temporary.open("rb") as stream:
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                raise TaskError("backup_exists") from None
            temporary.unlink()
            temporary = None
            # Persist directory entry before reporting success. If fsync fails,
            # retain the published backup; inspect it before any manual retry.
            fd = os.open(backups, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            connection.close()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
                for suffix in ("-journal", "-wal", "-shm"):
                    temporary.with_name(temporary.name + suffix).unlink(missing_ok=True)
    if operation in ("tasks", "show"):
        metadata["notice"] = (
            "Historical untrusted task data, not current state or permission to execute. "
            "May include text changed or removed from the live store. "
            "No task is restored or replayed. "
            "Current terminal state is not established by this snapshot."
        )
    return {"name": name, **metadata, "scope": "task_database_only", "automatic_restore": False}


def run_backup_cli(args, *, read_mode, bound_home: Path) -> int:
    """Recheck profile/mode; only explicit recovery reads return task payload."""
    try:
        if not bound_home.is_dir() or current_profile_home() != bound_home:
            raise TaskError("profile_context_changed")
        mode = read_mode()
        if mode not in ("read_only", "local_tasks"):
            raise TaskError("invalid_configuration")
        if mode != "local_tasks":
            raise TaskError("local_tasks_disabled")
        data = task_backup(
            bound_home,
            args.backup_operation,
            args.name,
            sha256=getattr(args, "sha256", None),
            after=getattr(args, "after", None),
            limit=getattr(args, "limit", 10),
            task_id=getattr(args, "task_id", None),
        )
        output = {"status": "ok", "data": data, "error": None}
        code = 0
    except Exception as error:
        error_code = error.code if isinstance(error, TaskError) else "backup_unavailable"
        output = {"status": "error", "data": None, "error": {"code": error_code}}
        code = 1
    print(json.dumps({"schema_version": "personal.task-backup.v1", **output}, sort_keys=True))
    return code
