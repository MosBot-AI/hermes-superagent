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
from .task_presentation import render_task_result
from .tasks import MAX_PLAN_CHARS, TaskError, TaskStore, validate_request


def setup_tasks_cli(parent: argparse._SubParsersAction) -> None:
    parser = parent.add_parser("tasks", help="Manage the opt-in, profile-local task inbox")
    commands = parser.add_subparsers(dest="task_operation", required=True)
    capture = commands.add_parser("capture", help="Capture a local task without dispatching it")
    capture.add_argument("--title", required=True)
    capture.add_argument("--details", default="")
    capture.add_argument("--request-id", required=True)
    capture.add_argument("--due-date", default=argparse.SUPPRESS, help="Explicit YYYY-MM-DD date")
    capture.add_argument("--project", default=argparse.SUPPRESS)
    plan = commands.add_parser("plan", help="Atomically capture 1-20 tasks under one project label")
    plan.add_argument("--project", required=True)
    plan.add_argument("--request-id", required=True)
    inputs = plan.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--task", action="append", help="Repeat for each task title in the plan")
    inputs.add_argument("--tasks-json", help="JSON array of title/details/due_date objects")
    show = commands.add_parser("show", help="Read one local task")
    show.add_argument("task_id")
    history = commands.add_parser("history", help="Read bounded task operation metadata")
    history.add_argument("task_id")
    history.add_argument("--limit", type=int, default=20)
    history.add_argument("--after-revision", type=int, default=0)
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
    review = commands.add_parser("review", help="Read a bounded daily task overview")
    review.add_argument("--on", required=True, help="Explicit YYYY-MM-DD date; no clock inference")
    review.add_argument("--lookahead-days", type=int, default=7)
    review.add_argument("--per-bucket-limit", type=int, default=5)
    review.add_argument("--max-chars", type=int, default=16000)
    for reader in (listing, search, agenda, review):
        reader.add_argument(
            "--work-status",
            choices=("ready", "in_progress", "waiting", "blocked"),
            default=argparse.SUPPRESS,
            help="Filter active tasks by recorded work status",
        )
        filters = reader.add_mutually_exclusive_group()
        filters.add_argument("--project", default=argparse.SUPPRESS, help="Exact project label")
        filters.add_argument("--unassigned", action="store_true", default=argparse.SUPPRESS)
    projects = commands.add_parser("projects", help="Count current local task project labels")
    projects.add_argument("--limit", type=int, default=20)
    projects.add_argument("--after", default=None, help="Exclusive binary-order project label")
    for name in ("update", "complete", "cancel", "progress"):
        command = commands.add_parser(name, help=f"{name.capitalize()} a local task explicitly")
        command.add_argument("task_id")
        command.add_argument("--expected-revision", type=int, required=True)
        command.add_argument("--request-id", required=True)
        if name == "update":
            command.add_argument("--title", default=argparse.SUPPRESS)
            command.add_argument("--details", default=argparse.SUPPRESS)
            labels = command.add_mutually_exclusive_group()
            labels.add_argument("--project", default=argparse.SUPPRESS)
            labels.add_argument(
                "--clear-project",
                dest="project",
                action="store_const",
                const=None,
                default=argparse.SUPPRESS,
            )
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
            if name == "progress":
                command.add_argument(
                    "--work-status",
                    required=True,
                    choices=("ready", "in_progress", "waiting", "blocked"),
                )
    for command in commands.choices.values():
        command.add_argument(
            "--format",
            dest="output_format",
            choices=("json", "text"),
            default=None,
            help="Output format; CLI defaults to JSON, native conversation defaults to text",
        )


def command_request(args: argparse.Namespace) -> tuple[str, dict]:
    operation = "get" if args.task_operation == "show" else args.task_operation
    if operation == "plan":
        tasks = (
            [{"title": title} for title in args.task]
            if args.task is not None
            else _parse_plan_json(args.tasks_json)
        )
        return "capture_plan", validate_request(
            "capture_plan", {"project": args.project, "tasks": tasks, "request_id": args.request_id}
        )
    fields = {
        "capture": ("title", "details", "request_id", "due_date", "project"),
        "get": ("task_id",),
        "history": ("task_id", "limit", "after_revision"),
        "projects": ("limit", "after"),
        "review": (
            "on",
            "lookahead_days",
            "per_bucket_limit",
            "max_chars",
            "project",
            "unassigned",
            "work_status",
        ),
        "list": ("state", "limit", "after", "project", "unassigned", "work_status"),
        "search": ("query", "state", "limit", "after", "project", "unassigned", "work_status"),
        "agenda": ("on", "limit", "after", "project", "unassigned", "work_status"),
        "update": (
            "task_id",
            "expected_revision",
            "request_id",
            "title",
            "details",
            "due_date",
            "project",
        ),
        "progress": ("task_id", "expected_revision", "request_id", "work_status", "note"),
        "complete": ("task_id", "expected_revision", "request_id", "note"),
        "cancel": ("task_id", "expected_revision", "request_id", "note"),
    }
    if operation not in fields:
        raise TaskError("invalid_request")
    payload = {key: getattr(args, key) for key in fields[operation] if hasattr(args, key)}
    return operation, validate_request(operation, payload)


def _parse_plan_json(raw: str):
    """One bounded JSON value; duplicate keys/non-JSON constants are rejected."""
    if type(raw) is not str or len(raw) > MAX_PLAN_CHARS:
        raise TaskError("invalid_request")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise TaskError("invalid_request")
            result[key] = value
        return result

    def reject_constant(_value):
        raise TaskError("invalid_request")

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
    except ValueError, TypeError, RecursionError:
        raise TaskError("invalid_request") from None


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
    """Print one redacted result; keep CLI JSON default and existing exit codes."""
    operation, payload = "", {}
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
    if getattr(args, "output_format", None) == "text":
        print(
            render_task_result(
                output, operation=operation, payload=payload, prefix="hermes personal-agent tasks"
            )
        )
    else:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return code
