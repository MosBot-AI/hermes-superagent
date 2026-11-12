"""Explicit retained native snapshots, independent from native lifecycle authority.

One durable pending slot per consumer prevents an admitted source being overtaken.
Only metadata survives staging; the caller owns any separately retained plaintext.
"""

import hashlib
import json
import re
from datetime import datetime

from .memory_backend import MemoryError, _text, validate_expiry
from .memory_mutation_status import _unique_object, normalized_request_digest, receipt_valid

OPERATIONS = frozenset(
    {
        "source_stage",
        "source_accept",
        "source_discard",
        "source_status",
        "source_cursor",
        "source_discover",
    }
)
WRITES = frozenset({"source_stage", "source_accept", "source_discard"})
SCHEMA_V12 = {
    "retained_source_decisions": """CREATE TABLE retained_source_decisions (
        request_id TEXT PRIMARY KEY NOT NULL,
        consumer_id TEXT NOT NULL, source_sequence INTEGER NOT NULL CHECK(source_sequence>=1),
        request_digest TEXT NOT NULL, source_identity TEXT UNIQUE NOT NULL,
        source_fingerprint TEXT NOT NULL, source_role TEXT NOT NULL,
        source_receipt TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','accepted','discarded')),
        record_id TEXT UNIQUE REFERENCES records(record_id), receipt TEXT,
        suppressed INTEGER NOT NULL CHECK(suppressed IN (0,1)),
        UNIQUE(consumer_id,source_sequence),
        CHECK((state='accepted' AND record_id IS NOT NULL AND receipt IS NOT NULL)
            OR (state!='accepted' AND record_id IS NULL AND receipt IS NULL)))"""
}
# Keep the historical definition exact: schema admission compares sqlite_master SQL.
SCHEMA = {
    "retained_source_decisions": SCHEMA_V12["retained_source_decisions"]
    .replace(
        "source_receipt TEXT NOT NULL,",
        """source_receipt TEXT,
        source_kind TEXT NOT NULL,
        source_observation TEXT,
        """,
    )
    .replace(
        "UNIQUE(consumer_id,source_sequence),",
        """UNIQUE(consumer_id,source_sequence),
        CHECK((source_kind='retained_native_snapshot' AND source_receipt IS NOT NULL
            AND source_observation IS NULL)
            OR (source_kind='observed_native_snapshot' AND source_receipt IS NULL
            AND source_observation IS NOT NULL)),""",
    )
}

COLUMNS = (
    "request_id",
    "consumer_id",
    "source_sequence",
    "request_digest",
    "source_identity",
    "source_fingerprint",
    "source_role",
    "source_receipt",
    "source_kind",
    "source_observation",
    "state",
    "record_id",
    "receipt",
    "suppressed",
)


def _match(value, pattern):
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise MemoryError("invalid_request")
    return value


def _digest(value):
    return _match(value, r"[0-9a-f]{64}")


def _sequence(value):
    if type(value) is not int or not 0 <= value < 2**63 - 1:
        raise MemoryError("invalid_request")
    return value


def validate(operation, payload):
    if type(operation) is not str or operation not in OPERATIONS or type(payload) is not dict:
        raise MemoryError("invalid_request")
    if operation == "source_discover":
        from .retained_source_discovery import validate as validate_discovery

        return validate_discovery(payload)
    if operation == "source_cursor":
        fields = {"consumer_id"}
    elif operation in {"source_status", "source_discard"}:
        fields = {"request_id", "expected_digest"}
    else:
        fields = {
            "request_id",
            "consumer_id",
            "expected_sequence",
            "content",
            "expires_at",
            "retention",
            "source",
        }
    optional = {"topic"} if operation in {"source_stage", "source_accept"} else set()
    if not fields <= payload.keys() or payload.keys() - fields - optional:
        raise MemoryError("invalid_request")
    request = dict(payload)
    if "request_id" in request:
        _match(request["request_id"], r"[A-Za-z0-9._-]{1,128}")
    if "consumer_id" in request:
        _match(request["consumer_id"], r"[a-z][a-z0-9_.-]{0,63}")
    if "expected_digest" in request:
        _digest(request["expected_digest"])
    if "expected_sequence" in request:
        _sequence(request["expected_sequence"])
        _text(request["content"], 2048, multiline=True)
        request["topic"] = _text(request.get("topic", ""), 128, empty=True)
        validate_expiry(request["expires_at"])
        if request["retention"] != "independent_snapshot":
            raise MemoryError("invalid_request")
        source = request["source"]
        _validate_source(source, output=False)
        if source["fingerprint"] != hashlib.sha256(request["content"].encode()).hexdigest():
            raise MemoryError("invalid_request")
        request["source"] = dict(source)
    return request


def _validate_source(source, *, output):
    if type(source) is not dict:
        raise MemoryError("invalid_request")
    observed = source.get("kind") == "observed_native_snapshot"
    provenance = "observation_id" if observed else "receipt_id"
    fields = {"identity", "fingerprint", "role", provenance}
    if output or observed:
        fields.add("kind")
    if set(source) != fields:
        raise MemoryError("invalid_request")
    if output and not observed and source["kind"] != "retained_native_snapshot":
        raise MemoryError("invalid_request")
    for key in ("identity", "fingerprint", provenance):
        _digest(source[key])
    if type(source["role"]) is not str or source["role"] not in {"user", "assistant"}:
        raise MemoryError("invalid_request")


def source_request_identity(payload):
    """Pure import identity to retain before admission; never an authorization token."""
    request = validate("source_stage", payload)
    return {
        "request_id": request["request_id"],
        "expected_digest": normalized_request_digest("retained_source_import", request),
    }


def _require(condition):
    if not condition:
        raise MemoryError("invalid_result")


def _decision(value):
    _require(
        type(value) is dict
        and set(value)
        == {"request_id", "consumer_id", "source_sequence", "state", "source", "record"}
    )
    _match(value["request_id"], r"[A-Za-z0-9._-]{1,128}")
    _match(value["consumer_id"], r"[a-z][a-z0-9_.-]{0,63}")
    _require(_sequence(value["source_sequence"]) >= 1)
    _require(type(value["state"]) is str and value["state"] in {"pending", "accepted", "discarded"})
    source = value["source"]
    _validate_source(source, output=True)
    if value["state"] == "accepted":
        receipt_valid(value["record"])
        _require(value["record"]["operation"] == "remember")
        _require(value["record"]["request_id"] == _record_key(value["request_id"]))
    else:
        _require(value["record"] is None)


def validate_result(operation, request, data):
    """Validate additive SDK result data; envelope/replay classification is separate."""
    if operation == "source_discover":
        from .retained_source_discovery import validate_result as validate_discovery_result

        return validate_discovery_result(request, data)
    if operation in WRITES:
        _decision(data)
        _require(data["request_id"] == request["request_id"])
        if operation in {"source_stage", "source_accept"}:
            _require(data["consumer_id"] == request["consumer_id"])
            _require(data["source_sequence"] == request["expected_sequence"] + 1)
            _require(data["source"] == {"kind": "retained_native_snapshot", **request["source"]})
        if operation == "source_accept":
            _require(data["state"] == "accepted")
        if operation == "source_discard":
            _require(data["state"] == "discarded")
        return
    if operation == "source_cursor":
        _require(type(data) is dict and set(data) == {"consumer_id", "through_sequence", "pending"})
        _require(data["consumer_id"] == request["consumer_id"])
        _sequence(data["through_sequence"])
        if data["pending"] is not None:
            _decision(data["pending"])
            _require(data["pending"]["state"] == "pending")
            _require(data["pending"]["consumer_id"] == data["consumer_id"])
            _require(data["pending"]["source_sequence"] == data["through_sequence"] + 1)
        return
    _require(type(data) is dict and type(data.get("state")) is str)
    if data["state"] == "absent_at_snapshot":
        _require(set(data) == {"state", "evaluated_at"})
    else:
        _require(
            data["state"] == "found"
            and set(data) == {"state", "decision", "current", "suppressed", "evaluated_at"}
        )
        _decision(data["decision"])
        _require(data["decision"]["request_id"] == request["request_id"])
        _require(type(data["suppressed"]) is bool)
        record, current = data["decision"]["record"], data["current"]
        if record is None:
            _require(current is None)
        else:
            _require(
                type(current) is dict
                and set(current) == {"record_id", "revision", "status", "expired"}
            )
            _require(current["record_id"] == record["record_id"])
            _require(type(current["revision"]) is int and 1 <= current["revision"] < 2**63)
            _require(
                type(current["status"]) is str and current["status"] in {"active", "forgotten"}
            )
            _require(type(current["expired"]) is bool)
            _require(current["status"] != "forgotten" or not current["expired"])
            _require(current["revision"] != 1 or current["status"] == "active")
            _require(current["revision"] == 1 or data["suppressed"])
    _require(type(data["evaluated_at"]) is str)
    _require(validate_expiry(data["evaluated_at"]) is not None)


def _record_key(request_id):
    return "source.accept." + hashlib.sha256(request_id.encode()).hexdigest()


def _metadata(row):
    return {
        "request_id": row["request_id"],
        "consumer_id": row["consumer_id"],
        "source_sequence": row["source_sequence"],
        "state": row["state"],
        "source": {
            "kind": row["source_kind"],
            "identity": row["source_identity"],
            "fingerprint": row["source_fingerprint"],
            "role": row["source_role"],
            **(
                {"receipt_id": row["source_receipt"]}
                if row["source_kind"] == "retained_native_snapshot"
                else {"observation_id": row["source_observation"]}
            ),
        },
        "record": json.loads(row["receipt"], object_pairs_hook=_unique_object)
        if row["receipt"] is not None
        else None,
    }


def _current(conn, record_id, now):
    if record_id is None:
        return None
    raw = conn.execute(
        "SELECT revision,CASE WHEN length(CAST(status AS BLOB))<=9 THEN status END, "
        "CASE WHEN expires_at IS NULL OR length(CAST(expires_at AS BLOB))<=20 "
        "THEN expires_at ELSE 0 END FROM records WHERE record_id=?",
        (record_id,),
    ).fetchone()
    _require(raw is not None)
    revision, status, expiry = raw
    _require(type(revision) is int and 1 <= revision < 2**63)
    _require(status in {"active", "forgotten"})
    validate_expiry(expiry)
    _require(status != "forgotten" or expiry is None)
    return {
        "record_id": record_id,
        "revision": revision,
        "status": status,
        "expired": expiry is not None and now is not None and datetime.fromisoformat(expiry) <= now,
    }


def validate_store(conn, now):
    """Bounded metadata-only validation. Never reads candidates or record payloads."""
    try:
        maxima = (128, 64, None, 64, 64, 64, 9, 64, 24, 64, 9, 36, 2048, None)
        columns = [
            name
            if limit is None
            else (
                f"CASE WHEN {name} IS NULL OR length(CAST({name} AS BLOB))<={limit} "
                f"THEN {name} ELSE 0 END"
            )
            for name, limit in zip(COLUMNS, maxima, strict=True)
        ]
        raw = conn.execute(
            f"SELECT {','.join(columns)} FROM retained_source_decisions "
            "ORDER BY consumer_id,source_sequence LIMIT 1001"
        ).fetchall()
        _require(len(raw) <= 1000)
        rows, cursors, identities, records = {}, {}, set(), set()
        for values in raw:
            row = dict(zip(COLUMNS, values, strict=True))
            _require(
                (
                    row["source_kind"] == "retained_native_snapshot"
                    and row["source_receipt"] is not None
                    and row["source_observation"] is None
                )
                or (
                    row["source_kind"] == "observed_native_snapshot"
                    and row["source_receipt"] is None
                    and row["source_observation"] is not None
                )
            )
            metadata = _metadata(row)
            _decision(metadata)
            _digest(row["request_digest"])
            _require(type(row["suppressed"]) is int and row["suppressed"] in {0, 1})
            _require(row["state"] != "discarded" or row["suppressed"] == 1)
            _require(row["request_id"] not in rows and row["source_identity"] not in identities)
            identities.add(row["source_identity"])
            cursor = cursors.setdefault(
                row["consumer_id"],
                {"consumer_id": row["consumer_id"], "through_sequence": 0, "pending": None},
            )
            _require(
                cursor["pending"] is None
                and row["source_sequence"] == cursor["through_sequence"] + 1
            )
            if row["state"] == "pending":
                cursor["pending"] = metadata
            else:
                cursor["through_sequence"] = row["source_sequence"]
            if row["state"] == "accepted":
                receipt = metadata["record"]
                _require(
                    row["record_id"] == receipt["record_id"] and row["record_id"] not in records
                )
                records.add(row["record_id"])
                old = conn.execute(
                    "SELECT CASE WHEN length(CAST(receipt AS BLOB))<=2048 THEN receipt END "
                    "FROM receipts WHERE request_id=?",
                    (receipt["request_id"],),
                ).fetchone()
                _require(
                    old is not None
                    and type(old[0]) is str
                    and len(old[0]) <= 2048
                    and json.loads(old[0], object_pairs_hook=_unique_object) == receipt
                )
                event = conn.execute(
                    "SELECT record_id,revision,operation FROM events WHERE sequence=?",
                    (receipt["event_sequence"],),
                ).fetchone()
                _require(event == (row["record_id"], 1, "remember"))
                current = _current(conn, row["record_id"], now)
                _require(current["revision"] != 1 or current["status"] == "active")
                _require(current["revision"] == 1 or row["suppressed"] == 1)
            else:
                _require(row["record_id"] is None and row["receipt"] is None)
            rows[row["request_id"]] = row
        _require(len(cursors) <= 64)
        return rows, cursors
    except MemoryError, ValueError, TypeError, KeyError, RecursionError:
        raise MemoryError("storage_corrupt") from None


def is_suppressed(conn, fingerprint):
    return (
        conn.execute(
            "SELECT 1 FROM retained_source_decisions "
            "WHERE source_fingerprint=? AND suppressed=1 LIMIT 1",
            (fingerprint,),
        ).fetchone()
        is not None
    )


def suppress_record(conn, record_id):
    from .memory_sources import discard_pending

    row = conn.execute(
        "SELECT source_fingerprint FROM retained_source_decisions WHERE record_id=?",
        (record_id,),
    ).fetchone()
    if row:
        discard_pending(conn, row[0])
    conn.execute(
        "UPDATE retained_source_decisions SET suppressed=1 WHERE record_id=?", (record_id,)
    )


def _check_suppression(conn, fingerprint):
    from . import memory_sources

    if (
        is_suppressed(conn, fingerprint)
        or conn.execute(
            "SELECT 1 FROM memory_source_suppressions WHERE source_digest=?", (fingerprint,)
        ).fetchone()
    ):
        raise MemoryError("source_suppressed")
    memory_sources.check(conn, fingerprint)


def execute(backend, conn, operation, request, now):
    if operation in WRITES and backend._source_kind != "explicit_local_operator":
        raise MemoryError("source_scope_required")
    from .memory_mutation_status import validate_metadata

    validate_metadata(backend, conn, now)
    rows, cursors = validate_store(conn, now)
    if operation == "source_discover":
        from .retained_source_discovery import discover

        return discover(backend, conn, request, now, rows)
    if operation == "source_cursor":
        return cursors.get(
            request["consumer_id"],
            {"consumer_id": request["consumer_id"], "through_sequence": 0, "pending": None},
        )
    identity = (
        source_request_identity(request)
        if operation in {"source_stage", "source_accept"}
        else request
    )
    row = rows.get(request["request_id"])
    if row and row["request_digest"] != identity["expected_digest"]:
        raise MemoryError("idempotency_conflict")
    if operation == "source_status":
        evaluated = now.isoformat(timespec="seconds").replace("+00:00", "Z")
        if row is None:
            return {"state": "absent_at_snapshot", "evaluated_at": evaluated}
        return {
            "state": "found",
            "decision": _metadata(row),
            "current": _current(conn, row["record_id"], now),
            "suppressed": bool(row["suppressed"])
            or is_suppressed(conn, row["source_fingerprint"])
            or bool(
                conn.execute(
                    "SELECT 1 FROM memory_source_suppressions WHERE source_digest=?",
                    (row["source_fingerprint"],),
                ).fetchone()
            ),
            "evaluated_at": evaluated,
        }
    if operation == "source_stage":
        if row:
            return {"data": _metadata(row), "replayed": True}
        cursor = cursors.get(request["consumer_id"])
        if cursor and cursor["pending"] is not None:
            raise MemoryError("source_pending")
        if request["expected_sequence"] != (cursor["through_sequence"] if cursor else 0):
            raise MemoryError("source_cursor_conflict")
        if any(
            value["source_identity"] == request["source"]["identity"] for value in rows.values()
        ):
            raise MemoryError("source_identity_conflict")
        _check_suppression(conn, request["source"]["fingerprint"])
        if len(rows) >= 1000:
            raise MemoryError("source_limit")
        if not cursor and len(cursors) >= 64:
            raise MemoryError("source_consumer_limit")
        conn.execute(
            "INSERT INTO retained_source_decisions VALUES "
            "(?,?,?,?,?,?,?,?,?,?,'pending',NULL,NULL,0)",
            (
                request["request_id"],
                request["consumer_id"],
                request["expected_sequence"] + 1,
                identity["expected_digest"],
                request["source"]["identity"],
                request["source"]["fingerprint"],
                request["source"]["role"],
                request["source"].get("receipt_id"),
                request["source"].get("kind", "retained_native_snapshot"),
                request["source"].get("observation_id"),
            ),
        )
        rows, _ = validate_store(conn, now)
        return {"data": _metadata(rows[request["request_id"]]), "replayed": False}
    if row is None:
        raise MemoryError("source_not_staged")
    wanted = "accepted" if operation == "source_accept" else "discarded"
    if row["state"] != "pending":
        if row["state"] != wanted:
            raise MemoryError("source_terminal")
        return {"data": _metadata(row), "replayed": True}
    if operation == "source_accept":
        _check_suppression(conn, row["source_fingerprint"])
        key = _record_key(request["request_id"])
        if conn.execute("SELECT 1 FROM receipts WHERE request_id=?", (key,)).fetchone():
            raise MemoryError("idempotency_conflict")
        result = backend._mutate(
            conn,
            "remember",
            {
                "request_id": key,
                "content": request["content"],
                "topic": request["topic"],
                "expires_at": request["expires_at"],
            },
            now,
        )
        receipt = result["data"]
        conn.execute(
            "UPDATE retained_source_decisions SET state='accepted',record_id=?,receipt=? "
            "WHERE request_id=?",
            (receipt["record_id"], json.dumps(receipt, sort_keys=True), request["request_id"]),
        )
    else:
        from .memory_sources import discard_pending

        discard_pending(conn, row["source_fingerprint"])
        conn.execute(
            "UPDATE retained_source_decisions SET state='discarded',suppressed=1 "
            "WHERE request_id=?",
            (request["request_id"],),
        )
    rows, _ = validate_store(conn, now)
    return {"data": _metadata(rows[request["request_id"]]), "replayed": False}
