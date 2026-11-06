"""Opt-in, local-operator task commands. Never registered as model tools."""

import argparse
import json
import os
import sqlite3
import stat
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from . import PLUGIN_ID
from .tasks import TaskError, TaskStore, validate_request


def setup_tasks_cli(parent: argparse._SubParsersAction) -> None:
    parser = parent.add_parser("tasks", help="Manage the opt-in, profile-local task inbox")
    commands = parser.add_subparsers(dest="task_operation", required=True)
    capture = commands.add_parser("capture", help="Capture a local task without dispatching it")
    capture.add_argument("--title", required=True)
    capture.add_argument("--details", default="")
    capture.add_argument("--request-id", required=True)
    capture.add_argument("--due-date", default=argparse.SUPPRESS, help="Explicit YYYY-MM-DD date")
    show = commands.add_parser("show", help="Read one local task")
    show.add_argument("task_id")
    listing = commands.add_parser("list", help="Read a bounded local task page, newest first")
    listing.add_argument(
        "--state", choices=("captured", "done", "cancelled", "all"), default="captured"
    )
    listing.add_argument("--limit", type=int, default=20)
    listing.add_argument("--after", default=None)
    search = commands.add_parser("search", help="Search literal task text, newest first")
    search.add_argument("--query", required=True)
    search.add_argument(
        "--state", choices=("captured", "done", "cancelled", "all"), default="captured"
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--after", default=None)
    agenda = commands.add_parser(
        "agenda", help="List active tasks due on or before an explicit date"
    )
    agenda.add_argument("--on", required=True, help="Explicit YYYY-MM-DD date; no clock inference")
    agenda.add_argument("--limit", type=int, default=20)
    agenda.add_argument("--after", default=None)
    for name in ("update", "complete", "cancel"):
        command = commands.add_parser(name, help=f"{name.capitalize()} a local task explicitly")
        command.add_argument("task_id")
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--request-id", required=True)
        if name == "update":
            command.add_argument("--title", default=argparse.SUPPRESS)
            command.add_argument("--details", default=argparse.SUPPRESS)
            dates = command.add_mutually_exclusive_group()
            dates.add_argument("--due-date", default=argparse.SUPPRESS)
            dates.add_argument(
                "--clear-due",
                dest="due_date",
                action="store_const",
                const=None,
                default=argparse.SUPPRESS,
            )
        else:
            command.add_argument("--note", required=True)


def command_request(args: argparse.Namespace) -> tuple[str, dict]:
    operation = "get" if args.task_operation == "show" else args.task_operation
    fields = {
        "capture": ("title", "details", "request_id", "due_date"),
        "get": ("task_id",),
        "list": ("state", "limit", "after"),
        "search": ("query", "state", "limit", "after"),
        "agenda": ("on", "limit", "after"),
        "update": ("task_id", "expected_revision", "request_id", "title", "details", "due_date"),
        "complete": ("task_id", "expected_revision", "request_id", "note"),
        "cancel": ("task_id", "expected_revision", "request_id", "note"),
    }
    if operation not in fields:
        raise TaskError("invalid_request")
    payload = {key: getattr(args, key) for key in fields[operation] if hasattr(args, key)}
    return operation, validate_request(operation, payload)


def current_profile_home() -> Path:
    """Use the public host profile resolver; never accept a CLI path override."""
    # Supplied by the pinned host, verified by the real-host contract suite.
    from hermes_constants import get_hermes_home  # ty: ignore[unresolved-import]

    return get_hermes_home().resolve()


def _private_database_file(path: Path, *, create: bool = True) -> None:
    """Check main/sidecar files; never repair, chmod or truncate existing data."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        raise TaskError("unsupported_storage_platform")
    flags = os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if create:
        flags |= os.O_CREAT
    try:
        fd = os.open(path, flags, 0o600)
    except FileNotFoundError:
        if not create:
            return
        raise
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise TaskError("unsafe_storage_file")
    finally:
        os.close(fd)


def _private_storage_directory(path: Path) -> None:
    """Refuse existing unsafe directories without changing their permissions."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise TaskError("unsafe_storage_path")


@contextmanager
def open_task_store(bound_home: Path) -> Generator[TaskStore]:
    """Only this plugin's own database is opened, after opt-in and validation."""
    if not bound_home.is_dir() or current_profile_home() != bound_home:
        raise TaskError("profile_context_changed")
    if os.name != "posix":
        raise TaskError("unsupported_storage_platform")
    expected = bound_home / "plugin-data" / PLUGIN_ID
    for directory in (bound_home, expected.parent, expected):
        _private_storage_directory(directory)

    from plugins.plugin_storage import plugin_data_dir  # ty: ignore[unresolved-import]

    directory = plugin_data_dir(PLUGIN_ID)
    if directory.resolve() != expected:
        raise TaskError("unsafe_storage_path")
    for directory in (expected.parent, expected):
        _private_storage_directory(directory)
    path = directory / "tasks.sqlite3"
    # SQLite may reuse a journal inode and write earlier private pages into it.
    # Checking only the main database is insufficient, even in rollback mode.
    for suffix in ("-journal", "-wal", "-shm"):
        _private_database_file(path.with_name(path.name + suffix), create=False)
    _private_database_file(path)
    connection = sqlite3.connect(path, timeout=5, isolation_level=None)
    try:
        # Retain SQLite's default rollback journal. Do not bypass Hermes's WAL
        # compatibility gate with a private PRAGMA journal_mode=WAL.
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA synchronous=FULL")
        store = TaskStore(connection)
        store.initialize()
        yield store
    finally:
        connection.close()


def run_tasks_cli(
    args: argparse.Namespace, *, read_mode: Callable[[], object], bound_home: Path
) -> int:
    """Print one redacted JSON result; a host handler's integer is its exit code."""
    try:
        # get_config can recreate a missing profile in this host version.
        # Refuse before consulting configuration, not just before storage opens.
        if not bound_home.is_dir() or current_profile_home() != bound_home:
            raise TaskError("profile_context_changed")
        mode = read_mode()
        if mode not in ("read_only", "local_tasks"):
            raise TaskError("invalid_configuration")
        if mode != "local_tasks":
            raise TaskError("local_tasks_disabled")
        operation, payload = command_request(args)
        with open_task_store(bound_home) as store:
            result = store.run(operation, payload)
        output = {
            "schema_version": "personal.local-tasks.v1",
            "status": "ok",
            "scope": "trusted_local_cli_only",
            **result,
            "error": None,
        }
        code = 0
    except Exception as error:
        if not isinstance(error, TaskError):
            # Host configuration, paths and SQLite failures can contain private
            # data. Do not expose raw messages or retry unknown outcomes blindly.
            error = TaskError("local_tasks_unavailable")
        output = {
            "schema_version": "personal.local-tasks.v1",
            "status": "error",
            "scope": "trusted_local_cli_only",
            "data": None,
            "replayed": False,
            "error": {"code": error.code, "retryable": error.retryable},
        }
        code = 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return code
