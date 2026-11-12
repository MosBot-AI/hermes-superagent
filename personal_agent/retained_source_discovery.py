"""Bounded operator discovery of historical source decisions, never source reads."""

import hashlib
import json

from .memory_backend import MemoryError, _text, validate_expiry
from .memory_mutation_status import receipt_valid
from .retained_sources import _current, _digest, _match, _metadata, _record_key, _sequence

ORDER = "consumer_id_source_sequence"
MAX_OUTPUT_CHARS = 65536


def _require(condition):
    if not condition:
        raise MemoryError("invalid_result")


def validate(payload):
    if type(payload) is not dict or payload.keys() - {
        "state",
        "consumer_id",
        "limit",
        "offset",
        "expected_snapshot",
    }:
        raise MemoryError("invalid_request")
    request = {
        "state": "pending",
        "consumer_id": None,
        "limit": 20,
        "offset": 0,
        "expected_snapshot": None,
        **payload,
    }
    if type(request["state"]) is not str or request["state"] not in {
        "pending",
        "accepted",
        "discarded",
        "all",
    }:
        raise MemoryError("invalid_request")
    if request["consumer_id"] is not None:
        _match(request["consumer_id"], r"[a-z][a-z0-9_.-]{0,63}")
    if type(request["limit"]) is not int or not 1 <= request["limit"] <= 50:
        raise MemoryError("invalid_request")
    if (
        type(request["offset"]) is not int
        or not 0 <= request["offset"] <= 1000
        or request["offset"] % request["limit"]
    ):
        raise MemoryError("invalid_request")
    if request["expected_snapshot"] is not None:
        _digest(request["expected_snapshot"])
    elif request["offset"]:
        raise MemoryError("invalid_request")
    return request


def _item_valid(item):
    _require(
        type(item) is dict
        and set(item)
        == {"query", "consumer_id", "source_sequence", "state", "record", "current", "suppressed"}
    )
    query = item["query"]
    _require(type(query) is dict and set(query) == {"request_id", "expected_digest"})
    _match(query["request_id"], r"[A-Za-z0-9._-]{1,128}")
    _digest(query["expected_digest"])
    _match(item["consumer_id"], r"[a-z][a-z0-9_.-]{0,63}")
    _require(1 <= _sequence(item["source_sequence"]) <= 1000)
    _require(type(item["state"]) is str and item["state"] in {"pending", "accepted", "discarded"})
    _require(type(item["suppressed"]) is bool)
    _require(item["state"] != "discarded" or item["suppressed"])
    record, current = item["record"], item["current"]
    if item["state"] != "accepted":
        _require(record is None and current is None)
        return
    receipt_valid(record)
    _require(record["operation"] == "remember")
    _require(record["request_id"] == _record_key(query["request_id"]))
    _require(
        type(current) is dict and set(current) == {"record_id", "revision", "status", "expired"}
    )
    _require(current["record_id"] == record["record_id"])
    _require(type(current["revision"]) is int and 1 <= current["revision"] < 2**63)
    _require(type(current["status"]) is str and current["status"] in {"active", "forgotten"})
    _require(type(current["expired"]) is bool)
    _require(current["status"] != "forgotten" or not current["expired"])
    _require(current["revision"] != 1 or current["status"] == "active")
    _require(current["revision"] == 1 or item["suppressed"])


def validate_result(request, data):
    _require(
        type(data) is dict
        and set(data)
        == {
            "namespace_id",
            "state",
            "consumer_id",
            "order",
            "limit",
            "offset",
            "total",
            "next_offset",
            "snapshot",
            "evaluated_at",
            "items",
        }
    )
    _text(data["namespace_id"], 256)
    for key in ("state", "consumer_id", "limit", "offset"):
        _require(type(data[key]) is type(request[key]) and data[key] == request[key])
    _require(data["order"] == ORDER)
    _digest(data["snapshot"])
    if request["expected_snapshot"] is not None:
        _require(data["snapshot"] == request["expected_snapshot"])
    _require(type(data["evaluated_at"]) is str)
    _require(validate_expiry(data["evaluated_at"]) is not None)
    total, offset, limit = data["total"], data["offset"], data["limit"]
    _require(type(total) is int and 0 <= total <= 1000)
    _require(offset == 0 or offset < total)
    if request["state"] == "pending":
        _require(total <= (1 if request["consumer_id"] is not None else 64))
    items = data["items"]
    _require(type(items) is list and len(items) == min(limit, total - offset))
    expected_next = offset + len(items) if offset + len(items) < total else None
    _require(
        type(data["next_offset"]) is type(expected_next) and data["next_offset"] == expected_next
    )
    previous, keys, records, pending_consumers = None, set(), set(), set()
    for item in items:
        _item_valid(item)
        _require(item["consumer_id"] not in pending_consumers)
        if item["state"] == "pending":
            pending_consumers.add(item["consumer_id"])
        identity = (item["consumer_id"], item["source_sequence"])
        _require(previous is None or previous < identity)
        previous = identity
        key = item["query"]["request_id"]
        _require(key not in keys)
        keys.add(key)
        _require(request["state"] == "all" or item["state"] == request["state"])
        _require(request["consumer_id"] is None or item["consumer_id"] == request["consumer_id"])
        if item["record"] is not None:
            rid = item["record"]["record_id"]
            _require(rid not in records)
            records.add(rid)
    _require(len(json.dumps(data, ensure_ascii=False, separators=(",", ":"))) <= MAX_OUTPUT_CHARS)


def discover(backend, conn, request, now, rows):
    """Caller owns the validated canonical read snapshot; no payload is hydrated."""
    from .retained_sources import is_suppressed

    items = []
    for row in rows.values():
        decision = _metadata(row)
        items.append(
            {
                "query": {
                    "request_id": row["request_id"],
                    "expected_digest": row["request_digest"],
                },
                **{
                    key: decision[key]
                    for key in ("consumer_id", "source_sequence", "state", "record")
                },
                "current": _current(conn, row["record_id"], now),
                "suppressed": bool(row["suppressed"])
                or is_suppressed(conn, row["source_fingerprint"])
                or bool(
                    conn.execute(
                        "SELECT 1 FROM memory_source_suppressions WHERE source_digest=?",
                        (row["source_fingerprint"],),
                    ).fetchone()
                ),
            }
        )
    items.sort(key=lambda item: (item["consumer_id"], item["source_sequence"]))
    binding = {
        "namespace_id": backend._namespace,
        "order": ORDER,
        **{key: request[key] for key in ("state", "consumer_id", "limit")},
    }
    snapshot = hashlib.sha256(
        json.dumps(
            ["retained-source-discovery-v1", binding, items],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if request["expected_snapshot"] is not None and request["expected_snapshot"] != snapshot:
        raise MemoryError("source_discovery_changed")
    selected = [
        item
        for item in items
        if (request["state"] == "all" or item["state"] == request["state"])
        and (request["consumer_id"] is None or item["consumer_id"] == request["consumer_id"])
    ]
    offset, limit, total = request["offset"], request["limit"], len(selected)
    if offset and offset >= total:
        raise MemoryError("invalid_cursor")
    data = {
        **binding,
        "offset": offset,
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "snapshot": snapshot,
        "evaluated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "items": selected[offset : offset + limit],
    }
    validate_result(request, data)
    return data
