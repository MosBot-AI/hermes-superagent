"""Pinned, existing-board native creation. No dispatcher, initializer or CLI startup.

Compatibility checks are not a sandbox against malicious code in this process.
Any creation exception may follow a successful native commit: never auto-retry.
"""

import ast
import contextlib
import hashlib
import importlib
import inspect
import json
import os
import re
import sqlite3
import stat
import sys
import time
import types
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

from .native_kanban_pin import SCHEMA_SHA256, SOURCE_SHA256
from .tasks import TaskError


def _fail(code="native_unavailable") -> NoReturn:
    raise TaskError(code)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def payload_digest(title: str, body: str) -> str:
    if (
        type(title) is not str
        or not title.strip()
        or title != title.strip()
        or len(title) > 240
        or type(body) is not str
        or len(body) > 12000
    ):
        _fail("invalid_request")
    return _digest([title, body])


def _code(code):
    # Compilation uses the real source path; normalize nested code recursively.
    return code.replace(
        co_filename="<pinned>",
        co_consts=tuple(
            _code(item) if isinstance(item, types.CodeType) else item for item in code.co_consts
        ),
    )


def _verify_definitions(module, namespace, nodes, compiled):
    codes = {code.co_name: code for code in compiled.co_consts if isinstance(code, types.CodeType)}
    for node in nodes:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        expected = codes[node.name]
        value = namespace.get(node.name)
        if isinstance(node, ast.ClassDef):
            if not inspect.isclass(value) or value.__module__ != module.__name__:
                _fail()
            _verify_definitions(module, vars(value), node.body, expected)
            continue
        if isinstance(value, (staticmethod, classmethod)):
            value = value.__func__
        if not inspect.isfunction(value):
            _fail()
        original = inspect.unwrap(value)
        if value is not original:
            wrapper = contextlib.contextmanager(original)
            if (
                value.__code__ != getattr(wrapper, "__code__", None)
                or not value.__closure__
                or tuple(cell.cell_contents for cell in value.__closure__) != (original,)
            ):
                _fail()
        if original.__globals__ is not module.__dict__ or _code(original.__code__) != _code(
            expected
        ):
            _fail()


def _host():
    modules = {}
    root = None
    for relative, expected in SOURCE_SHA256.items():
        module = importlib.import_module(relative[:-3].replace("/", "."))
        if not isinstance(module.__file__, str):
            _fail()
        path = Path(module.__file__)
        if path.is_symlink() or path.suffix != ".py":
            _fail()
        current_root = path.resolve().parents[1]
        if root is not None and current_root != root:
            _fail()
        root = current_root
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            _fail()
        compiled = compile(raw, str(path), "exec", optimize=sys.flags.optimize)
        _verify_definitions(module, module.__dict__, ast.parse(raw).body, compiled)
        modules[module.__name__] = module
    kb = modules["hermes_cli.kanban_db"]
    if kb.write_txn is not modules["hermes_cli.kanban_db_connect"].write_txn:
        _fail()
    if (
        kb.read_board_metadata is not modules["hermes_cli.kanban_db_boards"].read_board_metadata
        or modules["hermes_cli.kanban_db_connect"]._kb is not kb
    ):
        _fail()
    return kb, modules["hermes_cli.sqlite_safe_read"]


def _context(kb, path):
    dc = importlib.import_module("agent.delegation_context")
    current_cron_execution = importlib.import_module(
        "cron.execution_identity"
    ).current_cron_execution
    is_managed = importlib.import_module("hermes_cli.config").is_managed

    if (
        dc.is_delegated_child_process_context()
        or not dc.is_dispatcher_owned_worker_context()
        or dc.explicit_board_intent_is_pinned()
        or dc.kanban_path_is_fenced(path)
        or current_cron_execution() is not None
        or is_managed()
    ):
        _fail("native_context_denied")


def _private(path, *, directory=False):
    info = path.lstat()
    if (
        info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or (not stat.S_ISDIR(info.st_mode) if directory else not stat.S_ISREG(info.st_mode))
        or (not directory and info.st_nlink != 1)
    ):
        _fail("native_unsafe_path")
    return info


def _binding(kb, board, *, owned_write=False):
    if type(board) is not str or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", board) is None:
        _fail("invalid_request")
    root = Path(kb.kanban_home()).absolute()
    if root != root.resolve():
        _fail("native_unsafe_path")
    _private(root, directory=True)
    intended = (
        root / "kanban.db"
        if board == "default"
        else root / "kanban" / "boards" / board / "kanban.db"
    )
    if Path(kb.kanban_db_path(board=board)).absolute() != intended:
        _fail("native_destination_changed")
    _context(kb, intended)
    for parent in reversed(intended.parent.relative_to(root).parents):
        _private(root / parent, directory=True)
    if intended.parent != root:
        _private(intended.parent, directory=True)
        meta = intended.parent / "board.json"
        _private(meta)
        if kb.read_board_metadata(board).get("archived"):
            _fail("native_destination_changed")
    info = _private(intended)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(intended) + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            _private(sidecar)
            if suffix == "-journal" and not owned_write:
                _fail("native_unsafe_storage")
    return {
        "root": str(root),
        "board": board,
        "path": str(intended),
        "device": info.st_dev,
        "inode": info.st_ino,
        "schema": SCHEMA_SHA256,
        "source": _digest(SOURCE_SHA256),
    }


def _check(binding, kb, *, owned_write_connection=None):
    owned_write = False
    if owned_write_connection is not None:
        # Only the post-insert check inside our native write_txn supplies this
        # connection. BEGIN IMMEDIATE owns the writer lock; a DELETE-mode
        # journal created by these inserts is expected, not a pre-existing hot
        # journal to recover. Before opening/starting and after COMMIT, journal
        # presence is still refused. Never read/close a raw journal descriptor.
        conn = owned_write_connection
        databases = conn.execute("PRAGMA database_list").fetchall()
        owned_write = (
            conn.in_transaction
            and conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            # SQLite integrity_check may initialize its unnamed temp schema.
            # It is not an attached file, and the authorizer still denies temp
            # SQL. No other database or nonempty temp filename is admitted.
            and [(row[1], row[2]) for row in databases if row[1] != "temp"]
            == [("main", binding["path"])]
            and all(row[2] == "" for row in databases if row[1] == "temp")
        )
        if not owned_write:
            _fail("native_unsafe_storage")
    if (
        type(binding) is not dict
        or _binding(kb, binding.get("board"), owned_write=owned_write) != binding
    ):
        _fail("native_destination_changed")


def _schema(conn):
    rows = conn.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name LIMIT 129"
    ).fetchall()
    if _digest([list(row) for row in rows]) != SCHEMA_SHA256:
        _fail("native_schema_mismatch")


def _authorizer(write):
    def allow(action, arg1, arg2, database, source):
        if source is not None or database not in (None, "main"):
            return sqlite3.SQLITE_DENY
        if action in (
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_TRANSACTION,
            sqlite3.SQLITE_SAVEPOINT,
            sqlite3.SQLITE_RECURSIVE,
        ):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION and arg2 in {"count", "max", "coalesce"}:
            return sqlite3.SQLITE_OK
        if (
            action == sqlite3.SQLITE_PRAGMA
            and arg2 is None
            and arg1 in {"database_list", "journal_mode", "page_count", "page_size"}
        ):
            return sqlite3.SQLITE_OK
        if write and action == sqlite3.SQLITE_INSERT and arg1 in {"tasks", "task_events"}:
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    return allow


@contextmanager
def _connection(binding, write=False):
    kb, safe = _host()
    _check(binding, kb)
    conn = safe.connect_tracked(
        Path(binding["path"]).as_uri() + ("?mode=rw" if write else "?mode=ro"),
        uri=True,
        isolation_level=None,
        timeout=1.0,
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65536)
        deadline = time.monotonic() + 3.0
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() in {"off", "memory"}:
            _fail("native_unsafe_storage")
        for pragma, value in (("foreign_keys", 1), ("cell_size_check", 1), ("trusted_schema", 0)):
            conn.execute(f"PRAGMA {pragma}={value}")
            if conn.execute(f"PRAGMA {pragma}").fetchone()[0] != value:
                _fail()
        if write:
            conn.execute("PRAGMA synchronous=FULL")
            if conn.execute("PRAGMA synchronous").fetchone()[0] != 2:
                _fail()
        else:
            conn.execute("PRAGMA query_only=ON")
        if [tuple(row) for row in conn.execute("PRAGMA integrity_check(1)")] != [("ok",)]:
            _fail("native_unsafe_storage")
        _schema(conn)
        _check(binding, kb)
        conn.set_authorizer(_authorizer(write))
        yield kb, conn
    finally:
        conn.close()


def destination(board: str) -> dict:
    try:
        kb, _ = _host()
        binding = _binding(kb, board)
        with _connection(binding):
            pass
        return binding
    except TaskError:
        raise
    except Exception:
        _fail()


def _matches(conn, key):
    if type(key) is not str or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", key) is None:
        _fail("invalid_request")
    return conn.execute("SELECT * FROM tasks WHERE idempotency_key=? LIMIT 2", (key,)).fetchall()


def _observation(conn, rows, digest):
    if not rows:
        return {"outcome": "missing"}
    if len(rows) != 1:
        return {"outcome": "duplicate"}
    row = dict(rows[0])
    if type(row["id"]) is not str or re.fullmatch(r"t_[0-9a-f]{8}", row["id"]) is None:
        _fail("native_unsafe_storage")
    if row["status"] not in {"triage", "todo", "ready", "running", "blocked", "done", "archived"}:
        _fail("native_unsafe_storage")
    result = {"card_id": row["id"], "status": row["status"]}
    if row["status"] == "archived":
        return {**result, "outcome": "archived"}
    nulls = (
        "assignee",
        "workspace_path",
        "branch_name",
        "project_id",
        "tenant",
        "session_id",
        "model_override",
        "provider_override",
        "reasoning_effort",
        "skills",
        "goal_max_turns",
        "current_run_id",
        "worker_pid",
        "worker_started_at",
        "claim_lock",
        "claim_expires",
        "started_at",
        "completed_at",
        "result",
        "max_runtime_seconds",
        "max_retries",
        "workflow_template_id",
        "current_step_key",
        "last_failure_error",
        "last_heartbeat_at",
        "block_kind",
    )
    valid = (
        row["status"] == "blocked"
        and row["workspace_kind"] == "scratch"
        and row["created_by"] == "personal-agent"
        and row["priority"] == 0
        and row["completion_contract"] == "local-only"
        and row["goal_mode"] == 0
        and row["consecutive_failures"] == 0
        and row["block_recurrences"] == 0
        and all(row[key] is None for key in nulls)
    )
    try:
        valid = valid and payload_digest(row["title"], row["body"]) == digest
    except TaskError:
        valid = False
    for table in ("task_runs", "kanban_notify_subs", "task_comments", "task_attachments"):
        if conn.execute(f"SELECT 1 FROM {table} WHERE task_id=? LIMIT 1", (row["id"],)).fetchone():
            valid = False
    if conn.execute(
        "SELECT 1 FROM task_links WHERE parent_id=? OR child_id=? LIMIT 1", (row["id"], row["id"])
    ).fetchone():
        valid = False
    events = conn.execute(
        "SELECT kind,payload,run_id FROM task_events WHERE task_id=? ORDER BY id LIMIT 3",
        (row["id"],),
    ).fetchall()
    valid = valid and len(events) == 2 and [event[0] for event in events] == ["created", "blocked"]
    if valid:
        expected = {"reason": "initial_status", "status": "blocked", "actor": "personal-agent"}
        created = {
            "assignee": None,
            "status": "blocked",
            "parents": [],
            "creator_task_id": None,
            "tenant": None,
            "workspace_kind": "scratch",
            "workspace_path": None,
            "branch_name": None,
            "project_id": None,
            "skills": None,
            "goal_mode": None,
            "model_override": None,
            "provider_override": None,
        }
        valid = (
            events[0][2] is None
            and events[1][2] is None
            and json.loads(events[1][1]) == expected
            and json.loads(events[0][1]) == created
        )
    return {**result, "outcome": "parked" if valid else "changed"}


def observe(binding: dict, *, key: str, payload_digest: str, admit) -> dict:
    try:
        if type(payload_digest) is not str or re.fullmatch(r"[0-9a-f]{64}", payload_digest) is None:
            _fail("invalid_request")
        admit()
        with _connection(binding) as (kb, conn):
            conn.execute("BEGIN")
            _schema(conn)
            result = _observation(conn, _matches(conn, key), payload_digest)
            _host()
            _check(binding, kb)
            admit()
            conn.execute("COMMIT")
            return result
    except TaskError:
        raise
    except Exception:
        _fail()


def create_parked(binding: dict, *, key: str, title: str, body: str, admit) -> dict:
    try:
        digest = payload_digest(title, body)
        admit()
        with _connection(binding, write=True) as (kb, conn):
            with kb.write_txn(conn):
                _host()
                _schema(conn)
                _check(binding, kb)
                admit()
                if _matches(conn, key):
                    _fail("native_key_conflict")
                card_id = kb.create_task(
                    conn,
                    title=title,
                    body=body,
                    assignee=None,
                    created_by="personal-agent",
                    workspace_kind="scratch",
                    initial_status="blocked",
                    idempotency_key=key,
                )
                result = _observation(conn, _matches(conn, key), digest)
                if result != {"outcome": "parked", "card_id": card_id, "status": "blocked"}:
                    _fail("native_result_invalid")
                _host()
                # WAL has no rollback journal; DELETE needs the narrow owned
                # journal allowance only while this write transaction is live.
                if conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete":
                    _check(binding, kb, owned_write_connection=conn)
                else:
                    _check(binding, kb)
                admit()
            _check(binding, kb)
            admit()
            return result
    except TaskError:
        raise
    except Exception:
        _fail()
