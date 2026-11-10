"""Explicit operator review of untrusted native text; no native access or model action."""

import hashlib
import json
import re
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime

from .task_native_sync import FAILURES, STATUSES

NOTICE = (
    "Untrusted editable card result, not verified execution. "
    "Exported and current revisions may differ; review actual work, not inferred recency. "
    "A null current-run pointer does not prove every worker process stopped. "
    "Manual approval and note required."
)
SCHEMA = "personal-agent.native-result-review.v1"


def _fail(code="invalid_request"):
    from .tasks import TaskError

    raise TaskError(code)


def _keys(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        _fail()


def _int(value, minimum=0, maximum=253402300799):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail()


def _match(value, pattern):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        _fail()


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def preview(task, evidence):
    from .tasks import _task_id

    _keys(evidence, "handoff_id exported_revision destination identity native")
    _task_id(evidence["handoff_id"])
    _task_id(task["id"])
    _int(task["revision"], 1, 2**63 - 2)
    _int(evidence["exported_revision"], 1, task["revision"])
    dest = evidence["destination"]
    _keys(dest, "root board path device inode schema source")
    for key in ("root", "path", "board"):
        val = dest[key]
        if (
            type(val) is not str
            or not val
            or len(val) > 4096
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in val)
        ):
            _fail()
    if not dest["root"].startswith("/") or not dest["path"].startswith("/"):
        _fail()
    for key in ("device", "inode"):
        _int(dest[key], 0, 2**63 - 1)
    for key in ("schema", "source"):
        _match(dest[key], r"[0-9a-f]{64}")
    identity = evidence["identity"]
    _keys(identity, "card_id created_at created_event_id")
    _match(identity["card_id"], r"t_[0-9a-f]{8}")
    _int(identity["created_at"])
    _int(identity["created_event_id"], 1, 2**63 - 1)
    native = evidence["native"]
    _keys(
        native, "card_id outcome status observed_at result_state result completed_at current_run_id"
    )
    if native["card_id"] != identity["card_id"]:
        _fail()
    _int(native["observed_at"])
    if native["completed_at"] is not None:
        _int(native["completed_at"])
    if native["current_run_id"] is not None:
        _int(native["current_run_id"], 1, 2**63 - 1)
    if type(native["outcome"]) is not str or native["outcome"] not in FAILURES | {"current"}:
        _fail()
    if type(native["result_state"]) is not str or native["result_state"] not in {
        "available",
        "empty",
        "too_large",
        "not_done",
        "active_run",
        "unavailable",
    }:
        _fail()
    if native["outcome"] != "current":
        if native["status"] is not None or native["result_state"] != "unavailable":
            _fail()
    elif type(native["status"]) is not str or native["status"] not in STATUSES:
        _fail()
    state = native["result_state"]
    if native["outcome"] != "current":
        if native["completed_at"] is not None or native["current_run_id"] is not None:
            _fail()
    elif native["status"] != "done":
        if (
            state != "not_done"
            or native["completed_at"] is not None
            or native["current_run_id"] is not None
        ):
            _fail()
    elif native["current_run_id"] is not None:
        if state != "active_run" or native["completed_at"] is not None:
            _fail()
    elif state not in {"available", "empty", "too_large", "unavailable"}:
        _fail()
    if native["result_state"] == "available":
        if (
            native["outcome"] != "current"
            or native["status"] != "done"
            or native["current_run_id"] is not None
            or native["completed_at"] is None
            or type(native["result"]) is not str
            or not native["result"].strip()
            or len(native["result"]) > 8000
        ):
            _fail()
    elif native["result"] is not None:
        _fail()
    if len(_json(native)) > 32000:
        _fail()
    bound = deepcopy(evidence)
    del bound["native"]["observed_at"]
    return {
        "task": {
            k: task[k] for k in ("id", "revision", "title", "project", "state", "work_status")
        },
        "evidence": deepcopy(evidence),
        "review_digest": _hash([SCHEMA, task["id"], task["revision"], bound]),
        "can_accept": task["state"] == "captured"
        and task["dependencies_satisfied"] is True
        and native["result_state"] == "available",
        "notice": NOTICE,
    }


def accept(store, request, observe_callback):
    from .tasks import TaskError, _database_error, _task_id, _text

    _keys(request, "task_id handoff_id expected_revision expected_digest request_id note")
    request = dict(request)
    for key in ("task_id", "handoff_id"):
        _task_id(request[key])
    _int(request["expected_revision"], 1, 2**63 - 2)
    _match(request["expected_digest"], r"[0-9a-f]{64}")
    _match(request["request_id"], r"[A-Za-z0-9._-]{1,128}")
    request["note"] = _text(request["note"], 2000, required=True, multiline=True)
    if not store._initialized:
        _fail("not_initialized")
    digest = _hash(
        ["native_review_accept", {k: v for k, v in request.items() if k != "request_id"}]
    )
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
                _keys(data, "task review")
                review = data["review"]
                _keys(
                    review,
                    "handoff_id card_id review_digest observed_at exported_revision "
                    "created_event_id completed_at",
                )
                if (
                    data["task"]["id"] != request["task_id"]
                    or data["task"]["revision"] != request["expected_revision"] + 1
                    or data["task"]["state"] != "done"
                    or data["task"]["resolution_note"] != request["note"]
                    or review["handoff_id"] != request["handoff_id"]
                    or review["review_digest"] != request["expected_digest"]
                ):
                    _fail()
                _match(review["card_id"], r"t_[0-9a-f]{8}")
                for key in ("observed_at", "completed_at"):
                    _int(review[key])
                _int(review["created_event_id"], 1, 2**63 - 1)
                _int(review["exported_revision"], 1, request["expected_revision"])
            except ValueError, TypeError, KeyError, TaskError:
                _fail("storage_corrupt")
            conn.execute("COMMIT")
            return {"data": data, "replayed": True}
        task = store._get(request["task_id"])
        if task["revision"] != request["expected_revision"]:
            _fail("revision_conflict")
        if task["state"] != "captured":
            _fail("terminal_state")
        if not task["dependencies_satisfied"]:
            _fail("dependencies_unsatisfied")
        document = preview(task, observe_callback(deepcopy(task)))
        evidence = document["evidence"]
        if evidence["handoff_id"] != request["handoff_id"]:
            _fail("invalid_native_observation")
        if document["review_digest"] != request["expected_digest"]:
            _fail("native_review_changed")
        if not document["can_accept"]:
            _fail("native_result_unavailable")
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        cursor = conn.execute(
            "UPDATE tasks SET state='done',follow_up_on=NULL,revision=revision+1,"
            "updated_at=?,resolved_at=?,"
            "resolution_note=? WHERE id=? AND revision=? AND state='captured'",
            (now, now, request["note"], task["id"], task["revision"]),
        )
        if cursor.rowcount != 1:
            _fail("revision_conflict")
        updated = store._get(task["id"])
        native = evidence["native"]
        review = {
            "handoff_id": evidence["handoff_id"],
            "card_id": native["card_id"],
            "review_digest": document["review_digest"],
            "observed_at": native["observed_at"],
            "exported_revision": evidence["exported_revision"],
            "created_event_id": evidence["identity"]["created_event_id"],
            "completed_at": native["completed_at"],
        }
        data = {"task": updated, "review": review}
        store._record_event(updated, "native_review_accept", now)
        conn.execute(
            "INSERT INTO receipts(request_id,digest,receipt) VALUES (?,?,?)",
            (request["request_id"], digest, _json(data)),
        )
        conn.execute("COMMIT")
        return {"data": data, "replayed": False}
    except BaseException as error:
        if began:
            store._rollback()
        if isinstance(error, sqlite3.Error):
            raise _database_error(error) from None
        raise
