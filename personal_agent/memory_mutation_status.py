"""Read-only reconciliation of retained mutation identities, never source authority."""

import hashlib
import json
import re
from datetime import datetime

from .memory_backend import MemoryError, _identifier, validate_expiry, validate_request

MUTATIONS = frozenset({"remember", "correct", "forget"})
RECEIPT_FIELDS = {"record_id", "revision", "status", "operation", "request_id", "event_sequence"}


def mutation_request_identity(operation: str, payload: dict) -> dict:
    """Pure bounded identity preparation; retain before writing, not authorization.

    Preserve the historical normalized JSON identity, including omitted versus
    explicit-null expiry. No store, clock, binding or payload retention is used.
    """
    if type(operation) is not str or operation not in MUTATIONS:
        raise MemoryError("invalid_request")
    request = validate_request(operation, payload)
    return {
        "operation": operation,
        "request_id": request["request_id"],
        "expected_digest": normalized_request_digest(operation, request),
    }


def normalized_request_digest(operation, request):
    """Exact existing identity for validated public or trusted internal requests."""
    return hashlib.sha256(
        json.dumps(
            [operation, request], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def validate_query(payload):
    if type(payload) is not dict or set(payload) != {"operation", "request_id", "expected_digest"}:
        raise MemoryError("invalid_request")
    if type(payload["operation"]) is not str or payload["operation"] not in MUTATIONS:
        raise MemoryError("invalid_request")
    for key, pattern, maximum in (
        ("request_id", r"[A-Za-z0-9._-]{1,128}", 128),
        ("expected_digest", r"[0-9a-f]{64}", 64),
    ):
        value = payload[key]
        if type(value) is not str or len(value) > maximum or re.fullmatch(pattern, value) is None:
            raise MemoryError("invalid_request")
    return dict(payload)


def require(condition):
    if not condition:
        raise MemoryError("invalid_result")


def integer(value, minimum=1):
    require(type(value) is int and minimum <= value < 2**63)


def receipt_valid(receipt, *, internal=False):
    require(type(receipt) is dict and set(receipt) == RECEIPT_FIELDS)
    require(type(receipt["record_id"]) is str and len(receipt["record_id"]) == 36)
    _identifier(receipt["record_id"])
    integer(receipt["revision"])
    integer(receipt["event_sequence"])
    key = receipt["request_id"]
    if internal and type(key) is str and key.startswith("retention:"):
        parts = key.split(":")
        require(len(parts) == 3 and parts[2] == receipt["record_id"])
        require(receipt["operation"] == "forget")
        key = parts[1]
    validate_query(
        {"operation": receipt["operation"], "request_id": key, "expected_digest": "0" * 64}
    )
    require(receipt["status"] == ("forgotten" if receipt["operation"] == "forget" else "active"))
    require(
        receipt["revision"] == 1 if receipt["operation"] == "remember" else receipt["revision"] >= 2
    )


def validate_result(data, request):
    require(type(data) is dict and type(data.get("state")) is str)
    if data["state"] == "absent_at_snapshot":
        require(set(data) == {"state", "evaluated_at"})
    else:
        require(data["state"] == "committed")
        require(set(data) == {"state", "evaluated_at", "receipt", "current"})
        receipt, current = data["receipt"], data["current"]
        receipt_valid(receipt)
        require(receipt["operation"] == request["operation"])
        require(receipt["request_id"] == request["request_id"])
        require(
            type(current) is dict and set(current) == {"record_id", "revision", "status", "expired"}
        )
        require(current["record_id"] == receipt["record_id"])
        integer(current["revision"])
        require(type(current["status"]) is str and current["status"] in {"active", "forgotten"})
        require(type(current["expired"]) is bool)
        require(current["status"] != "forgotten" or current["expired"] is False)
        require(current["revision"] >= receipt["revision"])
        if current["revision"] == receipt["revision"]:
            require(current["status"] == receipt["status"])
        if receipt["status"] == "forgotten":
            require(current["revision"] == receipt["revision"])
    require(type(data["evaluated_at"]) is str)
    validate_expiry(data["evaluated_at"])
    require(data["evaluated_at"] is not None)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def inspect_status(backend, conn, request, now):
    """Caller owns one read transaction. Scan bounded metadata, never record text."""
    try:
        return _inspect_status(backend, conn, request, now)
    except (ValueError, TypeError, KeyError, RecursionError, MemoryError) as error:
        if isinstance(error, MemoryError) and error.code == "idempotency_conflict":
            raise
        raise MemoryError("storage_corrupt") from None


def _inspect_status(backend, conn, request, now):
    # Revalidate the already bound store, including writable-open adapters.
    from .local_memory import _APPLICATION_ID, _SCHEMA_VERSION

    require(conn.execute("PRAGMA application_id").fetchone()[0] == _APPLICATION_ID)
    require(conn.execute("PRAGMA user_version").fetchone()[0] == _SCHEMA_VERSION)
    require(
        backend._valid_schema(
            _SCHEMA_VERSION,
            conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall(),
        )
    )
    require(conn.execute("SELECT id FROM namespace LIMIT 2").fetchall() == [(backend._namespace,)])
    rows = conn.execute(
        "SELECT CASE WHEN length(CAST(record_id AS BLOB))<=36 THEN record_id END,revision,"
        "CASE WHEN length(CAST(status AS BLOB))<=9 THEN status END,"
        "CASE WHEN expires_at IS NULL OR length(CAST(expires_at AS BLOB))<=20 "
        "THEN expires_at ELSE 0 END FROM records LIMIT 1001"
    ).fetchall()
    require(len(rows) <= 1000)
    records = {}
    for rid, revision, status, expiry in rows:
        require(type(rid) is str and len(rid) == 36)
        _identifier(rid)
        integer(revision)
        require(status in {"active", "forgotten"})
        validate_expiry(expiry)
        require(status != "forgotten" or expiry is None)
        records[rid] = {
            "record_id": rid,
            "revision": revision,
            "status": status,
            "expired": expiry is not None and datetime.fromisoformat(expiry) <= now,
        }
    events = conn.execute(
        "SELECT sequence,CASE WHEN length(CAST(record_id AS BLOB))<=36 THEN record_id END,"
        "revision,CASE WHEN length(CAST(operation AS BLOB))<=8 THEN operation END "
        "FROM events ORDER BY sequence LIMIT 11001"
    ).fetchall()
    require(len(events) <= 11000)
    latest, event_map = {}, {}
    previous_sequence = 0
    for sequence, rid, revision, operation in events:
        integer(sequence)
        integer(revision)
        require(sequence > previous_sequence)
        previous_sequence = sequence
        require(type(rid) is str and rid in records)
        require(type(operation) is str and operation in MUTATIONS)
        previous = latest.get(rid)
        require(
            (revision == 1 and operation == "remember")
            if previous is None
            else (
                previous[1] != "forgotten"
                and revision == previous[0] + 1
                and operation in {"correct", "forget"}
            )
        )
        latest[rid] = (revision, "forgotten" if operation == "forget" else "active")
        event_map[sequence] = (rid, revision, operation)
    require(sum(event[3] != "forget" for event in events) <= 10000)
    require(latest == {rid: (row["revision"], row["status"]) for rid, row in records.items()})
    # Bound strings before fetching/parsing JSON. Check ALL links so a deleted
    # receipt cannot turn a committed event into a false missing-key result.
    receipts = conn.execute(
        "SELECT CASE WHEN length(CAST(request_id AS BLOB))<=175 THEN request_id END,"
        "CASE WHEN length(CAST(digest AS BLOB))<=64 THEN digest END,"
        "CASE WHEN length(CAST(receipt AS BLOB))<=16384 THEN receipt END "
        "FROM receipts LIMIT 12001"
    ).fetchall()
    require(len(receipts) <= 12000)
    seen, found, batches, children = set(), None, [], {}
    for key, digest, raw in receipts:
        require(type(raw) is str and len(raw) <= 16384)
        receipt = json.loads(raw, object_pairs_hook=_unique_object)
        require(type(receipt) is dict)
        if receipt.get("operation") == "forget_expired":
            _batch_valid(receipt, key, digest)
            batches.append(receipt)
            if key == request["request_id"]:
                raise MemoryError("idempotency_conflict")
            continue
        require(len(raw) <= 2048)
        receipt_valid(receipt, internal=True)
        require(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None)
        require(receipt["request_id"] == key)
        if key.startswith("retention:"):
            children[key] = receipt
        sequence = receipt["event_sequence"]
        require(sequence not in seen)
        seen.add(sequence)
        require(
            event_map.get(sequence)
            == (receipt["record_id"], receipt["revision"], receipt["operation"])
        )
        if key == request["request_id"]:
            if digest != request["expected_digest"] or receipt["operation"] != request["operation"]:
                raise MemoryError("idempotency_conflict")
            found = receipt
    require(seen == set(event_map))
    linked_children = {}
    for batch in batches:
        for child in batch["records"]:
            key = child["request_id"]
            require(key not in linked_children and children.get(key) == child)
            linked_children[key] = child
    require(linked_children == children)
    result = {
        "state": "absent_at_snapshot" if found is None else "committed",
        "evaluated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if found is not None:
        result.update(receipt=found, current=records[found["record_id"]])
    validate_result(result, request)
    return result


def _batch_valid(receipt, key, digest):
    """Recognize existing retention receipts sharing this table, without exposure."""
    from . import memory_retention

    require(
        set(receipt)
        == {
            "schema_version",
            "operation",
            "request_id",
            "before",
            "limit",
            "snapshot",
            "evaluated_at",
            "previous_watermark",
            "watermark",
            "forgotten_count",
            "remaining_count",
            "records",
            "scope",
            "notice",
        }
    )
    require(receipt["schema_version"] == "personal.memory.expired-forget.v1")
    require(receipt["request_id"] == key)
    request = memory_retention.validate(
        "forget_expired",
        {
            "before": receipt["before"],
            "limit": receipt["limit"],
            "expected_snapshot": receipt["snapshot"],
            "request_id": key,
        },
    )
    require(digest == memory_retention._digest(["forget_expired", request]))
    require(receipt["scope"] == "historical_batch_metadata_not_current_state")
    require(receipt["notice"] == memory_retention.NOTICE)
    require(type(receipt["evaluated_at"]) is str and len(receipt["evaluated_at"]) <= 32)
    evaluated = datetime.fromisoformat(receipt["evaluated_at"])
    offset = evaluated.utcoffset()
    require(offset is not None and offset.total_seconds() == 0)
    integer(receipt["previous_watermark"], 0)
    integer(receipt["watermark"])
    integer(receipt["forgotten_count"])
    integer(receipt["remaining_count"], 0)
    require(receipt["remaining_count"] <= 1000)
    records = receipt["records"]
    require(type(records) is list and 1 <= len(records) <= receipt["limit"])
    require(receipt["forgotten_count"] == len(records))
    previous = receipt["previous_watermark"]
    for child in records:
        receipt_valid(child, internal=True)
        require(child["operation"] == "forget")
        require(child["request_id"] == memory_retention._child_key(key, child["record_id"]))
        require(child["event_sequence"] > previous)
        previous = child["event_sequence"]
    require(previous == receipt["watermark"])
