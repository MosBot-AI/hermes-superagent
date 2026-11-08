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
from .tasks import TaskError, inspect_task_snapshot

MAX_BYTES = 512 * 1024 * 1024
TIMEOUT_SECONDS = 30
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def setup_backup_cli(parent: argparse._SubParsersAction) -> None:
    parser = parent.add_parser(
        "task-backup", help="Create or inspect private task snapshots locally"
    )
    commands = parser.add_subparsers(dest="backup_operation", required=True)
    for operation in ("create", "inspect"):
        command = commands.add_parser(operation)
        command.add_argument("--name", required=True, help="1-64 ASCII letters, digits, _ or -")


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


def _metadata(path: Path, deadline: float) -> dict:
    _check_file(path)
    # Published snapshots use DELETE journaling. Refuse sidecars rather than
    # silently inspecting a changed, concurrently written or incomplete backup.
    if any(
        path.with_name(path.name + suffix).exists()
        or path.with_name(path.name + suffix).is_symlink()
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise TaskError("backup_sidecar_present")
    connection = _connection(path, deadline)
    try:
        connection.execute("BEGIN")
        result = inspect_task_snapshot(connection)
    finally:
        connection.close()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            if time.monotonic() >= deadline:
                raise TaskError("backup_timeout")
            digest.update(block)
    return {**result, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def task_backup(bound_home: Path, operation: str, name: str) -> dict:
    """Create without replacement or inspect a bounded current-schema snapshot."""
    if operation not in ("create", "inspect") or type(name) is not str or not _NAME.fullmatch(name):
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
    if operation == "inspect":
        metadata = _metadata(destination, deadline)
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
    return {"name": name, **metadata, "scope": "task_database_only", "automatic_restore": False}


def run_backup_cli(args, *, read_mode, bound_home: Path) -> int:
    """Recheck current profile/mode; no task payload, SQL or paths in output."""
    try:
        if not bound_home.is_dir() or current_profile_home() != bound_home:
            raise TaskError("profile_context_changed")
        mode = read_mode()
        if mode not in ("read_only", "local_tasks"):
            raise TaskError("invalid_configuration")
        if mode != "local_tasks":
            raise TaskError("local_tasks_disabled")
        data = task_backup(bound_home, args.backup_operation, args.name)
        output = {"status": "ok", "data": data, "error": None}
        code = 0
    except Exception as error:
        error_code = error.code if isinstance(error, TaskError) else "backup_unavailable"
        output = {"status": "error", "data": None, "error": {"code": error_code}}
        code = 1
    print(json.dumps({"schema_version": "personal.task-backup.v1", **output}, sort_keys=True))
    return code
