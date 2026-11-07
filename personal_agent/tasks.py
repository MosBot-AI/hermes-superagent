"""Opt-in local presentation inbox; no host, path, scheduler, or network access."""

import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from .task_review import task_review

_APPLICATION_ID = 0x5041544B
_SCHEMA_VERSION = 3
_COLUMNS = (
    "id",
    "title",
    "details",
    "state",
    "revision",
    "created_at",
    "updated_at",
    "resolved_at",
    "resolution_note",
    "source",
    "due_date",
    "project",
)
_SCHEMA_V1 = {
    "tasks": """CREATE TABLE tasks (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, details TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('captured','done','cancelled')),
        revision INTEGER NOT NULL CHECK(revision >= 1),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT,
        resolution_note TEXT, source TEXT NOT NULL CHECK(source = 'local_cli'))""",
    "receipts": """CREATE TABLE receipts (
        request_id TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, receipt TEXT NOT NULL)""",
    "events": """CREATE TABLE events (
        task_id TEXT NOT NULL, revision INTEGER NOT NULL,
        operation TEXT NOT NULL, timestamp TEXT NOT NULL,
        PRIMARY KEY(task_id, revision))""",
}

# Match SQLite ADD COLUMN serialization so fresh and migrated stores validate identically.
_SCHEMA_V2 = {**_SCHEMA_V1, "tasks": _SCHEMA_V1["tasks"][:-1] + ", due_date TEXT)"}
_SCHEMA = {**_SCHEMA_V2, "tasks": _SCHEMA_V2["tasks"][:-1] + ", project TEXT)"}


class TaskError(Exception):
    """A stable redacted error suitable for presentation at the CLI boundary."""

    def __init__(self, code: str, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(f"Local task operation failed ({code}).")


def _text(value: Any, maximum: int, *, required: bool, multiline: bool) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise TaskError("invalid_request")
    if required and not value.strip():
        raise TaskError("invalid_request")
    for char in value:
        if multiline and char in "\n\t":
            continue
        if unicodedata.category(char) in {"Cc", "Cf", "Cs", "Zl", "Zp"}:
            raise TaskError("invalid_request")
    return value


def _project(value: Any) -> str:
    value = _text(value, 80, required=True, multiline=False)
    if value != value.strip():
        raise TaskError("invalid_request")
    return value


def _project_filter(request: dict, clauses: list, arguments: list) -> None:
    if "project" in request:
        clauses.append("project = ? COLLATE BINARY")
        arguments.append(request["project"])
    elif request.get("unassigned"):
        clauses.append("project IS NULL")


def _task_id(value: Any) -> str:
    if not isinstance(value, str):
        raise TaskError("invalid_request")
    try:
        parsed = UUID(value)
    except ValueError:
        raise TaskError("invalid_request") from None
    if parsed.version != 4 or str(parsed) != value:
        raise TaskError("invalid_request")
    return value


def _date(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise TaskError("invalid_request")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise TaskError("invalid_request") from None
    return value


def validate_request(operation: str, payload: dict) -> dict:
    """Validate without touching storage; return an independent normalized mapping."""
    fields = {
        "capture": ({"title", "request_id"}, {"details", "due_date", "project"}),
        "update": (
            {"task_id", "expected_revision", "request_id"},
            {"title", "details", "due_date", "project"},
        ),
        "complete": ({"task_id", "expected_revision", "request_id", "note"}, set()),
        "cancel": ({"task_id", "expected_revision", "request_id", "note"}, set()),
        "get": ({"task_id"}, set()),
        "history": ({"task_id"}, {"limit", "after_revision"}),
        "list": (set(), {"state", "limit", "after", "project", "unassigned"}),
        "search": ({"query"}, {"state", "limit", "after", "project", "unassigned"}),
        "agenda": ({"on"}, {"limit", "after", "project", "unassigned"}),
        "projects": (set(), {"limit", "after"}),
        "review": (
            {"on"},
            {"lookahead_days", "per_bucket_limit", "max_chars", "project", "unassigned"},
        ),
    }
    if not isinstance(operation, str) or operation not in fields or not isinstance(payload, dict):
        raise TaskError("invalid_request")
    required, optional = fields[operation]
    if not required <= payload.keys() or payload.keys() - required - optional:
        raise TaskError("invalid_request")
    result: dict = dict(payload)
    if operation == "capture":
        result.setdefault("details", "")
    if operation == "update" and not ({"title", "details", "due_date", "project"} & result.keys()):
        raise TaskError("invalid_request")
    for key, maximum, needed, multiline in (
        ("title", 240, True, False),
        ("query", 240, True, False),
        ("details", 5000, False, True),
        ("note", 2000, True, True),
    ):
        if key in result:
            result[key] = _text(result[key], maximum, required=needed, multiline=multiline)
    if "project" in result:
        if not (operation in ("capture", "update") and result["project"] is None):
            result["project"] = _project(result["project"])
    if "unassigned" in result:
        if type(result["unassigned"]) is not bool or "project" in result:
            raise TaskError("invalid_request")
    if "due_date" in result and not (operation == "update" and result["due_date"] is None):
        result["due_date"] = _date(result["due_date"])
    if "on" in result:
        result["on"] = _date(result["on"])
    if "task_id" in result:
        result["task_id"] = _task_id(result["task_id"])
    if "request_id" in result:
        value = result["request_id"]
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value) is None:
            raise TaskError("invalid_request")
    if "expected_revision" in result:
        value = result["expected_revision"]
        if type(value) is not int or not 1 <= value < 2**63 - 1:
            raise TaskError("invalid_request")
    if operation == "review":
        result = {"lookahead_days": 7, "per_bucket_limit": 5, "max_chars": 16000, **result}
        for key, minimum, maximum in (
            ("lookahead_days", 0, 90),
            ("per_bucket_limit", 1, 20),
            ("max_chars", 2048, 64000),
        ):
            if type(result[key]) is not int or not minimum <= result[key] <= maximum:
                raise TaskError("invalid_request")
        try:
            date.fromisoformat(result["on"]) + timedelta(days=result["lookahead_days"])
        except OverflowError:
            raise TaskError("invalid_request") from None
    if operation == "history":
        result = {"limit": 20, "after_revision": 0, **result}
        if type(result["limit"]) is not int or not 1 <= result["limit"] <= 100:
            raise TaskError("invalid_request")
        value = result["after_revision"]
        if type(value) is not int or not 0 <= value < 2**63:
            raise TaskError("invalid_request")
    if operation in ("list", "search", "agenda", "projects"):
        result = {"limit": 20, "after": None, **result}
        if operation in ("list", "search"):
            result.setdefault("state", "captured")
        if operation in ("list", "search") and result["state"] not in (
            "captured",
            "done",
            "cancelled",
            "all",
        ):
            raise TaskError("invalid_request")
        if type(result["limit"]) is not int or not 1 <= result["limit"] <= 100:
            raise TaskError("invalid_request")
        if result["after"] is not None:
            result["after"] = (
                _project(result["after"]) if operation == "projects" else _task_id(result["after"])
            )
    return result


def _database_error(error: sqlite3.Error) -> TaskError:
    code = getattr(error, "sqlite_errorcode", 0) or 0
    if code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return TaskError("storage_busy", retryable=True)
    if code & 255 in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
        return TaskError("storage_corrupt")
    return TaskError("storage_error")


class TaskStore:
    """Own transactions on a dedicated supplied connection; never open or close it."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._initialized = False

    def _begin(self) -> None:
        if self._connection.in_transaction:
            raise TaskError("connection_in_transaction")
        self._connection.execute("BEGIN IMMEDIATE")

    def _rollback(self) -> None:
        try:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
        except sqlite3.Error:
            # Preserve the redacted original failure, never raw rollback diagnostics.
            pass

    def initialize(self) -> None:
        """Create v3, atomically migrate exact owned v1/v2, or verify v3."""
        self._initialized = False
        began = False
        try:
            self._begin()
            began = True
            conn = self._connection
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            rows = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall()
            if app_id == 0 and version == 0 and not rows:
                for statement in _SCHEMA.values():
                    conn.execute(statement)
                conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif app_id != _APPLICATION_ID:
                raise TaskError("foreign_database")
            elif version in (1, 2):
                legacy = _SCHEMA_V1 if version == 1 else _SCHEMA_V2
                if dict(rows) != legacy or len(rows) != len(legacy):
                    raise TaskError("unsupported_schema")
                if version == 1:
                    conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
                conn.execute("ALTER TABLE tasks ADD COLUMN project TEXT")
                conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            elif version != _SCHEMA_VERSION:
                raise TaskError("unsupported_schema")
            elif dict(rows) != _SCHEMA or len(rows) != len(_SCHEMA):
                raise TaskError("unsupported_schema")
            rows = conn.execute(
                "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall()
            if dict(rows) != _SCHEMA or len(rows) != len(_SCHEMA):
                raise TaskError("unsupported_schema")
            conn.execute("COMMIT")
            self._initialized = True
        except BaseException as error:
            if began:
                self._rollback()
            if isinstance(error, sqlite3.Error):
                raise _database_error(error) from None
            raise

    def _get(self, task_id: str) -> dict:
        row = self._connection.execute(
            f"SELECT {','.join(_COLUMNS)} FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskError("not_found")
        return dict(zip(_COLUMNS, row, strict=True))

    def _list(self, request: dict) -> dict:
        clauses, arguments = [], []
        _project_filter(request, clauses, arguments)
        if "query" in request:
            # Literal, case-sensitive matching; bind text without normalization.
            clauses.append("(instr(title, ?) > 0 OR instr(details, ?) > 0)")
            arguments.extend((request["query"], request["query"]))
        if request["state"] != "all":
            clauses.append("state = ?")
            arguments.append(request["state"])
        if request["after"] is not None:
            row = self._connection.execute(
                "SELECT sequence FROM tasks WHERE id = ?", (request["after"],)
            ).fetchone()
            if row is None:
                raise TaskError("invalid_cursor")
            clauses.append("sequence < ?")
            arguments.append(row[0])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        arguments.append(request["limit"] + 1)
        rows = self._connection.execute(
            f"SELECT {','.join(_COLUMNS)} FROM tasks{where} ORDER BY sequence DESC LIMIT ?",
            arguments,
        ).fetchall()
        more = len(rows) > request["limit"]
        items = [dict(zip(_COLUMNS, row, strict=True)) for row in rows[: request["limit"]]]
        return {"items": items, "next_cursor": items[-1]["id"] if more else None, "has_more": more}

    def _agenda(self, request: dict) -> dict:
        """Read live keyset pages; edits between pages may change membership."""
        clauses = ["state = 'captured'", "due_date IS NOT NULL", "due_date <= ?"]
        arguments = [request["on"]]
        _project_filter(request, clauses, arguments)
        if request["after"] is not None:
            row = self._connection.execute(
                "SELECT due_date, sequence FROM tasks WHERE id = ?", (request["after"],)
            ).fetchone()
            if row is None or row[0] is None or row[0] > request["on"]:
                raise TaskError("invalid_cursor")
            clauses.append("(due_date > ? OR (due_date = ? AND sequence > ?))")
            arguments.extend((row[0], row[0], row[1]))
        arguments.append(request["limit"] + 1)
        rows = self._connection.execute(
            f"SELECT {','.join(_COLUMNS)} FROM tasks WHERE {' AND '.join(clauses)}"
            " ORDER BY due_date ASC, sequence ASC LIMIT ?",
            arguments,
        ).fetchall()
        more = len(rows) > request["limit"]
        items = [dict(zip(_COLUMNS, row, strict=True)) for row in rows[: request["limit"]]]
        return {
            "on": request["on"],
            "items": items,
            "next_cursor": items[-1]["id"] if more else None,
            "has_more": more,
        }

    def _projects(self, request: dict) -> dict:
        """Live label buckets, binary keyset order; no persistent project entities."""
        counts = "sum(state = 'captured'), sum(state = 'done'), sum(state = 'cancelled'), count(*)"
        where = "project IS NOT NULL"
        arguments = []
        if request["after"] is not None:
            where += " AND project COLLATE BINARY > ?"
            arguments.append(request["after"])
        arguments.append(request["limit"] + 1)
        rows = self._connection.execute(
            f"SELECT project, {counts} FROM tasks WHERE {where}"
            " GROUP BY project COLLATE BINARY ORDER BY project COLLATE BINARY ASC LIMIT ?",
            arguments,
        ).fetchall()
        keys = ("captured", "done", "cancelled", "total")
        items = [
            {"project": row[0], **dict(zip(keys, row[1:], strict=True))}
            for row in rows[: request["limit"]]
        ]
        unassigned = self._connection.execute(
            f"SELECT {counts} FROM tasks WHERE project IS NULL"
        ).fetchone()
        more = len(rows) > request["limit"]
        return {
            "items": items,
            "unassigned_counts": dict(zip(keys, (value or 0 for value in unassigned), strict=True)),
            "next_cursor": items[-1]["project"] if more else None,
            "has_more": more,
        }

    def _history(self, request: dict) -> dict:
        """Bounded append-only metadata in one read snapshot, never task text."""
        task_id = request["task_id"]
        row = self._connection.execute(
            "SELECT revision, state FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskError("not_found")
        revision, state = row
        after = request["after_revision"]
        if after and (
            after > revision
            or self._connection.execute(
                "SELECT 1 FROM events WHERE task_id = ? AND revision = ?", (task_id, after)
            ).fetchone()
            is None
        ):
            raise TaskError("invalid_cursor")
        rows = self._connection.execute(
            "SELECT revision, operation, timestamp FROM events WHERE task_id = ?"
            " AND revision > ? AND revision <= ? ORDER BY revision ASC LIMIT ?",
            (task_id, after, revision, request["limit"] + 1),
        ).fetchall()
        more = len(rows) > request["limit"]
        items = [
            dict(zip(("revision", "operation", "timestamp"), item, strict=True))
            for item in rows[: request["limit"]]
        ]
        return {
            "task_id": task_id,
            "current_revision": revision,
            "current_state": state,
            "items": items,
            "next_cursor": items[-1]["revision"] if more else None,
            "has_more": more,
        }

    def run(self, operation: str, payload: dict) -> dict:
        """Execute a validated operation with atomic mutations and durable replay receipts."""
        request = validate_request(operation, payload)
        if not self._initialized:
            raise TaskError("not_initialized")
        began = False
        try:
            if self._connection.in_transaction:
                raise TaskError("connection_in_transaction")
            if operation in ("get", "list", "search", "agenda", "projects", "history", "review"):
                if operation == "get":
                    data = self._get(request["task_id"])
                elif operation in ("projects", "history", "review"):
                    # Related queries share one read snapshot. A deferred
                    # transaction avoids acquiring an unnecessary write lock.
                    self._connection.execute("BEGIN")
                    began = True
                    if operation == "review":
                        data = task_review(self._connection, request)
                    elif operation == "projects":
                        data = self._projects(request)
                    else:
                        data = self._history(request)
                    self._connection.execute("COMMIT")
                elif operation == "agenda":
                    data = self._agenda(request)
                else:
                    data = self._list(request)
                return {"data": data, "replayed": False}
            self._begin()
            began = True
            digest = hashlib.sha256(
                json.dumps(
                    [operation, {k: v for k, v in request.items() if k != "request_id"}],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ).hexdigest()
            receipt = self._connection.execute(
                "SELECT digest, receipt FROM receipts WHERE request_id = ?",
                (request["request_id"],),
            ).fetchone()
            if receipt is not None:
                if receipt[0] != digest:
                    raise TaskError("idempotency_conflict")
                try:
                    data = json.loads(receipt[1])
                except ValueError, TypeError:
                    raise TaskError("storage_corrupt") from None
                self._connection.execute("COMMIT")
                return {"data": data, "replayed": True}
            now = datetime.now(UTC).isoformat(timespec="microseconds")
            if operation == "capture":
                task_id = str(uuid4())
                self._connection.execute(
                    "INSERT INTO tasks (id,title,details,state,revision,"
                    "created_at,updated_at,source,due_date,project)"
                    " VALUES (?,?,?,'captured',1,?,?,'local_cli',?,?)",
                    (
                        task_id,
                        request["title"],
                        request["details"],
                        now,
                        now,
                        request.get("due_date"),
                        request.get("project"),
                    ),
                )
            else:
                task_id = request["task_id"]
                task = self._get(task_id)
                if task["revision"] != request["expected_revision"]:
                    raise TaskError("revision_conflict")
                if task["state"] != "captured":
                    raise TaskError("terminal_state")
                state = {"complete": "done", "cancel": "cancelled"}.get(operation, "captured")
                cursor = self._connection.execute(
                    "UPDATE tasks SET title=?, details=?, due_date=?, project=?, state=?,"
                    " revision=revision+1,"
                    " updated_at=?, resolved_at=?, resolution_note=? WHERE id=? AND revision=?",
                    (
                        request.get("title", task["title"]),
                        request.get("details", task["details"]),
                        request.get("due_date", task["due_date"]),
                        request.get("project", task["project"]),
                        state,
                        now,
                        now if state != "captured" else None,
                        request.get("note"),
                        task_id,
                        request["expected_revision"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise TaskError("revision_conflict")
            data = self._get(task_id)
            self._connection.execute(
                "INSERT INTO events (task_id,revision,operation,timestamp) VALUES (?,?,?,?)",
                (task_id, data["revision"], operation, now),
            )
            self._connection.execute(
                "INSERT INTO receipts (request_id,digest,receipt) VALUES (?,?,?)",
                (request["request_id"], digest, json.dumps(data, ensure_ascii=True)),
            )
            self._connection.execute("COMMIT")
            return {"data": data, "replayed": False}
        except BaseException as error:
            if began:
                self._rollback()
            if isinstance(error, sqlite3.Error):
                raise _database_error(error) from None
            raise
