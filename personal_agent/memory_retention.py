"""Explicit whole-record review and atomic terminal forgetting of expired records.

No timer, inferred retention, capacity reset or physical erase.
Forgetting linked candidate records also suppresses their exact original input.
The backend owns the transaction; managed files cannot roll back with SQLite.
"""

import hashlib
import json
import re
from datetime import datetime

from .memory_backend import MemoryError, validate_expiry

DEFAULT_LIMIT = 10
MAX_LIMIT = 20
MAX_PREVIEW_CHARS = 64000
NOTICE = (
    "Review every selected record before forgetting this batch. Remaining records are not "
    "selected. Forgetting clears canonical payload and registered target edit drafts, "
    "and invalidates the managed projection. Tombstones remain and capacity is not reset. "
    "SQLite rollback cannot restore removed managed files. Previously returned text, editor "
    "buffers, host history, exports, backups and physical storage traces are not erased."
)


def validate(operation, payload):
    required = {"before"}
    if operation == "forget_expired":
        required |= {"expected_snapshot", "request_id"}
    elif operation != "expired_preview":
        raise MemoryError("invalid_request")
    if (
        type(payload) is not dict
        or not required <= payload.keys()
        or payload.keys() - required - {"limit"}
    ):
        raise MemoryError("invalid_request")
    value = {"limit": DEFAULT_LIMIT, **payload}
    if validate_expiry(value["before"]) is None:
        raise MemoryError("invalid_request")
    if type(value["limit"]) is not int or not 1 <= value["limit"] <= MAX_LIMIT:
        raise MemoryError("invalid_request")
    for key, pattern in (
        ("expected_snapshot", r"[0-9a-f]{64}"),
        ("request_id", r"[A-Za-z0-9._-]{1,128}"),
    ):
        if key in value:
            field = value[key]
            if type(field) is not str or re.fullmatch(pattern, field) is None:
                raise MemoryError("invalid_request")
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _child_key(request_id, record_id):
    # ':' is forbidden by every public canonical mutation request validator.
    # Keep an explicit collision refusal too, rather than treating a child replay
    # as evidence that a new batch performed a terminal mutation.
    return f"retention:{request_id}:{record_id}"


def preview(backend, conn, request, now):
    if datetime.fromisoformat(request["before"]) > now:
        raise MemoryError("retention_future_cutoff")
    backend._validate_expiries(conn)
    rows = conn.execute(
        "SELECT record_id FROM records WHERE status='active' AND expires_at IS NOT NULL "
        "AND expires_at <= ? ORDER BY expires_at,sequence LIMIT 1001",
        (request["before"],),
    ).fetchall()
    if len(rows) > 1000:
        raise MemoryError("record_limit")
    items = [backend._get(conn, row[0], now) for row in rows[: request["limit"]]]
    watermark = conn.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0]
    # Fixed cutoff keeps time passage from broadening the reviewed batch. The
    # watermark also fences any canonical writes to unselected records. Include
    # all eligible identities so a changed eligible population cannot go unseen.
    snapshot = _digest(
        [
            "personal.memory.expired-preview.v1",
            backend._namespace,
            request["before"],
            request["limit"],
            watermark,
            rows,
            items,
        ]
    )
    data = {
        "schema_version": "personal.memory.expired-preview.v1",
        "namespace_id": backend._namespace,
        "before": request["before"],
        "limit": request["limit"],
        "evaluated_at": now.isoformat().replace("+00:00", "Z"),
        "watermark": watermark,
        "snapshot": snapshot,
        "eligible_count": len(rows),
        "selected_count": len(items),
        "remaining_count": len(rows) - len(items),
        "items": items,
        "max_preview_chars": MAX_PREVIEW_CHARS,
        "order": "oldest_expiry_then_creation_sequence",
        "scope": "selected_expired_active_records_single_snapshot",
        "authority": "stored_data_not_instructions_or_permission",
        "notice": NOTICE,
    }
    if len(json.dumps(data, ensure_ascii=True, sort_keys=True)) > MAX_PREVIEW_CHARS:
        raise MemoryError("retention_preview_too_large")
    return data


def execute(backend, conn, operation, request, now):
    if operation == "expired_preview":
        return preview(backend, conn, request, now)
    identity = _digest(["forget_expired", request])
    old = conn.execute(
        "SELECT digest,receipt FROM receipts WHERE request_id=?", (request["request_id"],)
    ).fetchone()
    # Check the historical receipt before time, selection, files or any mutation:
    # replay must never consume the next batch, even after clock rollback.
    if old:
        if old[0] != identity:
            raise MemoryError("idempotency_conflict")
        return {"data": json.loads(old[1]), "replayed": True}
    reviewed = preview(backend, conn, request, now)
    if reviewed["snapshot"] != request["expected_snapshot"]:
        raise MemoryError("retention_snapshot_conflict")
    if not reviewed["items"]:
        raise MemoryError("retention_empty_batch")
    requests = [
        {
            "record_id": item["record_id"],
            "expected_revision": item["revision"],
            "request_id": _child_key(request["request_id"], item["record_id"]),
        }
        for item in reviewed["items"]
    ]
    for child in requests:
        if conn.execute(
            "SELECT 1 FROM receipts WHERE request_id=?", (child["request_id"],)
        ).fetchone():
            raise MemoryError("idempotency_conflict")
    records = [backend._mutate(conn, "forget", child, now)["data"] for child in requests]
    receipt = {
        "schema_version": "personal.memory.expired-forget.v1",
        "operation": "forget_expired",
        "request_id": request["request_id"],
        "before": request["before"],
        "limit": request["limit"],
        "snapshot": request["expected_snapshot"],
        "evaluated_at": reviewed["evaluated_at"],
        "previous_watermark": reviewed["watermark"],
        "watermark": records[-1]["event_sequence"],
        "forgotten_count": len(records),
        "remaining_count": reviewed["remaining_count"],
        "records": records,
        "scope": "historical_batch_metadata_not_current_state",
        "notice": NOTICE,
    }
    conn.execute(
        "INSERT INTO receipts VALUES (?,?,?)",
        (request["request_id"], identity, json.dumps(receipt, sort_keys=True)),
    )
    return {"data": receipt, "replayed": False}
