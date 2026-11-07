"""Advisory native snapshots and receipt-first local writes, never native execution."""

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime

SCHEMA = {
    "task_native_progress": """CREATE TABLE task_native_progress (
        task_id TEXT PRIMARY KEY NOT NULL, observation TEXT NOT NULL)"""
}
STATUSES = frozenset(
    ("triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived")
)
FAILURES = frozenset(
    ("missing", "duplicate", "identity_changed", "key_changed", "identity_unavailable")
)


def _fail(code="invalid_request"):
    from .tasks import TaskError

    raise TaskError(code)


def validate_observation(value):
    from .tasks import _task_id

    if type(value) is not dict or set(value) != {
        "handoff_id",
        "card_id",
        "outcome",
        "status",
        "observed_at",
        "exported_revision",
    }:
        _fail()
    _task_id(value["handoff_id"])
    if type(value["outcome"]) is not str or value["outcome"] not in FAILURES | {"current"}:
        _fail()
    if (
        type(value["card_id"]) is not str
        or re.fullmatch(r"t_[0-9a-f]{8}", value["card_id"]) is None
    ):
        _fail()
    if value["outcome"] == "current":
        if type(value["status"]) is not str or value["status"] not in STATUSES:
            _fail()
    elif value["status"] is not None:
        _fail()
    for key, minimum, maximum in (
        ("observed_at", 0, 253402300799),
        ("exported_revision", 1, 2**63 - 2),
    ):
        if type(value[key]) is not int or not minimum <= value[key] <= maximum:
            _fail()
    return dict(value)


def metadata(connection, task):
    from .tasks import TaskError

    row = connection.execute(
        "SELECT observation FROM task_native_progress WHERE task_id=?", (task["id"],)
    ).fetchone()
    value = None
    if row is not None:
        try:
            if type(row[0]) is not str or len(row[0]) > 2048:
                _fail()
            value = validate_observation(json.loads(row[0]))
        except ValueError, TypeError, TaskError:
            _fail("storage_corrupt")
    return {**task, "native_progress": value}


def sync(store, request, observe_callback):
    from .tasks import TaskError, _database_error, _task_id

    if type(request) is not dict or set(request) != {
        "task_id",
        "handoff_id",
        "expected_revision",
        "request_id",
    }:
        _fail()
    request = dict(request)
    _task_id(request["task_id"])
    _task_id(request["handoff_id"])
    revision = request["expected_revision"]
    if type(revision) is not int or not 1 <= revision < 2**63 - 1:
        _fail()
    if (
        type(request["request_id"]) is not str
        or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", request["request_id"]) is None
    ):
        _fail()
    if not store._initialized:
        _fail("not_initialized")
    digest = hashlib.sha256(
        json.dumps(
            ["native_sync", {k: v for k, v in request.items() if k != "request_id"}],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    conn = store._connection
    began = False
    try:
        store._begin()
        began = True
        row = conn.execute(
            "SELECT digest,receipt FROM receipts WHERE request_id=?", (request["request_id"],)
        ).fetchone()
        if row is not None:
            if row[0] != digest:
                _fail("idempotency_conflict")
            try:
                data = json.loads(row[1])
                if (
                    type(data) is not dict
                    or data.get("id") != request["task_id"]
                    or data.get("revision") != revision + 1
                ):
                    _fail()
                observation = validate_observation(data["native_progress"])
                if observation["handoff_id"] != request["handoff_id"]:
                    _fail()
            except ValueError, TypeError, KeyError, TaskError:
                _fail("storage_corrupt")
            conn.execute("COMMIT")
            return {"data": data, "replayed": True}
        task = store._get(request["task_id"])
        if task["revision"] != revision:
            _fail("revision_conflict")
        if task["state"] != "captured":
            _fail("terminal_state")
        # Independent copy: a callback cannot mutate the source used for checks.
        observation = validate_observation(observe_callback(json.loads(json.dumps(task))))
        if (
            observation["handoff_id"] != request["handoff_id"]
            or observation["exported_revision"] > revision
        ):
            _fail("invalid_native_observation")
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        cursor = conn.execute(
            "UPDATE tasks SET revision=revision+1,updated_at=? "
            "WHERE id=? AND revision=? AND state='captured'",
            (now, request["task_id"], revision),
        )
        if cursor.rowcount != 1:
            _fail("revision_conflict")
        conn.execute(
            "INSERT INTO task_native_progress(task_id,observation) VALUES (?,?) "
            "ON CONFLICT(task_id) DO UPDATE SET observation=excluded.observation",
            (request["task_id"], json.dumps(observation, ensure_ascii=True, sort_keys=True)),
        )
        data = store._get(request["task_id"])
        store._record_event(data, "native_sync", now)
        conn.execute(
            "INSERT INTO receipts(request_id,digest,receipt) VALUES (?,?,?)",
            (request["request_id"], digest, json.dumps(data, ensure_ascii=True)),
        )
        conn.execute("COMMIT")
        return {"data": data, "replayed": False}
    except BaseException as error:
        if began:
            store._rollback()
        if isinstance(error, sqlite3.Error):
            raise _database_error(error) from None
        raise
