"""Bounded review drafts, not canonical facts or durable transcript checkpoints."""

import hashlib
import json
import re
from datetime import datetime, timedelta
from uuid import uuid4

from .memory_backend import MemoryError, _identifier, _text, validate_expiry

OPERATIONS = frozenset(
    {
        "candidate_propose",
        "candidate_list",
        "candidate_get",
        "candidate_discard",
        "candidate_accept",
        "candidate_purge_expired",
    }
)
NOTICE = "Unverified draft from current native input, not verified authorship, fact or permission."
SCHEMA = {
    "memory_candidates": """CREATE TABLE memory_candidates (
    candidate_id TEXT PRIMARY KEY NOT NULL, request_id TEXT UNIQUE NOT NULL,
    proposal_digest TEXT NOT NULL, source_turn TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision IN (1,2)),
    state TEXT NOT NULL CHECK(state IN ('pending','accepted','discarded','expired')),
    content TEXT, topic TEXT, quote TEXT, quote_start INTEGER, source_digest TEXT,
    session_ref TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
    action_digest TEXT, receipt TEXT,
    CHECK((state='pending' AND revision=1 AND content IS NOT NULL AND topic IS NOT NULL
       AND quote IS NOT NULL AND quote_start IS NOT NULL AND source_digest IS NOT NULL
       AND session_ref IS NOT NULL AND action_digest IS NULL AND receipt IS NULL)
      OR (state!='pending' AND revision=2 AND content IS NULL AND topic IS NULL
       AND quote IS NULL AND quote_start IS NULL AND source_digest IS NULL
       AND session_ref IS NULL)))"""
}
COLUMNS = (
    "candidate_id",
    "request_id",
    "proposal_digest",
    "source_turn",
    "revision",
    "state",
    "content",
    "topic",
    "quote",
    "quote_start",
    "source_digest",
    "session_ref",
    "created_at",
    "expires_at",
    "action_digest",
    "receipt",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate(operation, payload):
    fields = {
        "candidate_propose": (
            {"request_id", "content", "quote", "quote_start", "source_digest", "source_turn"},
            {"topic"},
        ),
        "candidate_list": (set(), {"limit", "after"}),
        "candidate_get": ({"candidate_id"}, set()),
        "candidate_discard": ({"candidate_id", "expected_revision"}, set()),
        "candidate_accept": ({"candidate_id", "expected_revision", "expires_at"}, set()),
        "candidate_purge_expired": (set(), set()),
    }
    if operation not in fields or type(payload) is not dict:
        raise MemoryError("invalid_request")
    required, optional = fields[operation]
    if not required <= payload.keys() or payload.keys() - required - optional:
        raise MemoryError("invalid_request")
    value = dict(payload)
    if operation == "candidate_propose":
        value.setdefault("topic", "")
        for key, size in (("content", 2048), ("quote", 1024), ("topic", 128)):
            value[key] = _text(value[key], size, empty=key == "topic", multiline=key != "topic")
        if type(value["quote_start"]) is not int or not 0 <= value["quote_start"] <= 8192:
            raise MemoryError("invalid_request")
        for key in ("source_digest", "source_turn"):
            if type(value[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", value[key]):
                raise MemoryError("invalid_request")
        if type(value["request_id"]) is not str or not re.fullmatch(
            r"[A-Za-z0-9._-]{1,128}", value["request_id"]
        ):
            raise MemoryError("invalid_request")
    if "candidate_id" in value:
        value["candidate_id"] = _identifier(value["candidate_id"])
    if "expected_revision" in value:
        if (
            type(value["expected_revision"]) is not int
            or not 1 <= value["expected_revision"] < 2**63 - 1
        ):
            raise MemoryError("invalid_request")
    if "expires_at" in value:
        value["expires_at"] = validate_expiry(value["expires_at"])
    if operation == "candidate_list":
        value = {"limit": 20, "after": None, **value}
        if type(value["limit"]) is not int or not 1 <= value["limit"] <= 50:
            raise MemoryError("invalid_request")
        if value["after"] is not None:
            value["after"] = _identifier(value["after"])
    return value


def row_data(row):
    if row is None:
        raise MemoryError("candidate_not_found")
    result = dict(zip(COLUMNS, row, strict=True))
    try:
        _identifier(result["candidate_id"])
        expected_revision = 1 if result["state"] == "pending" else 2
        if type(result["revision"]) is not int or result["revision"] != expected_revision:
            raise ValueError()
        if result["state"] != "pending" and any(
            result[key] is not None
            for key in ("content", "topic", "quote", "quote_start", "source_digest", "session_ref")
        ):
            raise ValueError()
        for field in ("proposal_digest", "source_turn"):
            if type(result[field]) is not str or not re.fullmatch(r"[0-9a-f]{64}", result[field]):
                raise ValueError()
        for field in ("created_at", "expires_at"):
            if result[field] is None:
                raise ValueError()
            validate_expiry(result[field])
        if datetime.fromisoformat(result["expires_at"]) - datetime.fromisoformat(
            result["created_at"]
        ) != timedelta(days=7):
            raise ValueError()
        if result["state"] == "pending":
            if result["action_digest"] is not None or result["receipt"] is not None:
                raise ValueError()
            validate(
                "candidate_propose",
                {
                    key: result[key]
                    for key in (
                        "request_id",
                        "content",
                        "topic",
                        "quote",
                        "quote_start",
                        "source_digest",
                        "source_turn",
                    )
                },
            )
            _text(result["session_ref"], 256)
        elif result["state"] in {"accepted", "discarded"}:
            if type(result["action_digest"]) is not str or not re.fullmatch(
                r"[0-9a-f]{64}", result["action_digest"]
            ):
                raise ValueError()
            if type(result["receipt"]) is not str or len(result["receipt"]) > 2048:
                raise ValueError()
            receipt = json.loads(result["receipt"])
            expected = {
                key: result[key]
                for key in ("candidate_id", "revision", "state", "created_at", "expires_at")
            }
            record = receipt.pop("record", None)
            if receipt != expected:
                raise ValueError()
            if result["state"] == "accepted":
                if type(record) is not dict or set(record) != {
                    "record_id",
                    "revision",
                    "status",
                    "operation",
                    "request_id",
                    "event_sequence",
                }:
                    raise ValueError()
                _identifier(record["record_id"])
                if (
                    type(record["revision"]) is not int
                    or record["revision"] != 1
                    or record["status"] != "active"
                    or record["operation"] != "remember"
                    or record["request_id"] != "candidate.accept." + result["candidate_id"]
                    or type(record["event_sequence"]) is not int
                    or record["event_sequence"] < 1
                ):
                    raise ValueError()
            elif record is not None:
                raise ValueError()
        elif (
            result["state"] != "expired"
            or result["receipt"] is not None
            or result["action_digest"] is not None
        ):
            raise ValueError()
    except MemoryError, ValueError, TypeError, AttributeError:
        raise MemoryError("storage_corrupt") from None
    return result


def metadata(row):
    return {k: row[k] for k in ("candidate_id", "revision", "state", "created_at", "expires_at")}


def terminal(conn, row, state, action_digest=None, receipt=None):
    conn.execute(
        "UPDATE memory_candidates SET revision=2,state=?,content=NULL,topic=NULL,"
        "quote=NULL,quote_start=NULL,source_digest=NULL,session_ref=NULL,"
        "action_digest=?,receipt=? WHERE candidate_id=?",
        (
            state,
            action_digest,
            json.dumps(receipt, sort_keys=True) if receipt else None,
            row["candidate_id"],
        ),
    )
    return {**metadata(row), "revision": 2, "state": state}


def purge(conn, now):
    timestamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    rows = conn.execute(
        "SELECT * FROM memory_candidates WHERE state='pending' AND expires_at<=?", (timestamp,)
    ).fetchall()
    for row in rows:
        terminal(conn, row_data(row), "expired")
    return len(rows)


def execute(backend, conn, operation, request, now):
    required = (
        "activated_session_model" if operation == "candidate_propose" else "explicit_local_operator"
    )
    if backend._source_kind != required:
        raise MemoryError("candidate_scope_required")
    rows = conn.execute("SELECT * FROM memory_candidates LIMIT 1001").fetchall()
    if len(rows) > 1000:
        raise MemoryError("candidate_limit")
    for row in rows:
        row_data(row)
    purged = purge(conn, now)
    if operation == "candidate_purge_expired":
        return {"data": {"purged": purged}, "replayed": False}
    if operation == "candidate_propose":
        identity = digest([request, backend._session])
        old = conn.execute(
            "SELECT * FROM memory_candidates WHERE request_id=?", (request["request_id"],)
        ).fetchone()
        if old:
            row = row_data(old)
            if row["proposal_digest"] != identity:
                raise MemoryError("idempotency_conflict")
            return {"data": metadata(row), "replayed": True}
        if conn.execute("SELECT count(*) FROM memory_candidates").fetchone()[0] >= 1000:
            raise MemoryError("candidate_limit")
        if (
            conn.execute(
                "SELECT count(*) FROM memory_candidates WHERE source_turn=?",
                (request["source_turn"],),
            ).fetchone()[0]
            >= 3
        ):
            raise MemoryError("candidate_turn_limit")
        timestamp = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        expiry = (now + timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
        conn.execute(
            "INSERT INTO memory_candidates VALUES (?,?,?,?,1,'pending',?,?,?,?,?,?,?,?,NULL,NULL)",
            (
                str(uuid4()),
                request["request_id"],
                identity,
                request["source_turn"],
                request["content"],
                request["topic"],
                request["quote"],
                request["quote_start"],
                request["source_digest"],
                backend._session,
                timestamp,
                expiry,
            ),
        )
        row = row_data(
            conn.execute(
                "SELECT * FROM memory_candidates WHERE request_id=?", (request["request_id"],)
            ).fetchone()
        )
        return {"data": metadata(row), "replayed": False}
    if operation == "candidate_list":
        rows = conn.execute(
            "SELECT * FROM memory_candidates WHERE state='pending' AND candidate_id>? "
            "ORDER BY candidate_id LIMIT ?",
            (request["after"] or "", request["limit"] + 1),
        ).fetchall()
        items = [metadata(row_data(row)) for row in rows[: request["limit"]]]
        remaining = conn.execute(
            "SELECT count(*) FROM memory_candidates WHERE state='pending' AND candidate_id>?",
            (items[-1]["candidate_id"] if items else request["after"] or "",),
        ).fetchone()[0]
        return {
            "data": {
                "items": items,
                "omitted_records": remaining,
                "next_cursor": items[-1]["candidate_id"] if len(rows) > request["limit"] else None,
            },
            "replayed": False,
        }
    row = row_data(
        conn.execute(
            "SELECT * FROM memory_candidates WHERE candidate_id=?", (request["candidate_id"],)
        ).fetchone()
    )
    if operation == "candidate_get":
        result = metadata(row)
        if row["state"] == "pending":
            result.update(
                {
                    key: row[key]
                    for key in (
                        "content",
                        "topic",
                        "quote",
                        "quote_start",
                        "source_digest",
                        "source_turn",
                        "session_ref",
                    )
                }
            )
            result.update(source="unverified_current_native_input", notice=NOTICE)
        return {"data": result, "replayed": False}
    action = digest([operation, request])
    if row["state"] != "pending":
        if row["action_digest"] == action and row["receipt"]:
            return {"data": json.loads(row["receipt"]), "replayed": True}
        if row["state"] == "accepted":
            raise MemoryError("idempotency_conflict")
        raise MemoryError("candidate_terminal")
    if row["revision"] != request["expected_revision"]:
        raise MemoryError("revision_conflict")
    receipt = {**metadata(row), "revision": 2, "state": "discarded"}
    if operation == "candidate_accept":
        key = "candidate.accept." + row["candidate_id"]
        if conn.execute("SELECT 1 FROM receipts WHERE request_id=?", (key,)).fetchone():
            raise MemoryError("idempotency_conflict")
        remembered = backend._mutate(
            conn,
            "remember",
            {
                "request_id": key,
                "content": row["content"],
                "topic": row["topic"],
                "expires_at": request["expires_at"],
            },
            now,
        )
        receipt.update(state="accepted", record=remembered["data"])
    terminal(conn, row, receipt["state"], action, receipt)
    return {"data": receipt, "replayed": False}
