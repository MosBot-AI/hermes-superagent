"""Bounded historical origin metadata, never original content or authority."""

import json
from datetime import datetime, timedelta

from .memory_backend import MemoryError, _identifier, _text, validate_expiry
from .memory_mutation_status import (
    _unique_object,
    integer,
    receipt_valid,
    require,
    validate_metadata,
)
from .retained_sources import _digest, _match, is_suppressed, validate_store

MAX_OUTPUT_BYTES = 4096
SCOPE = "historical_acceptance_and_current_metadata_at_read_snapshot"
NOTICE = (
    "Stored roles and lineage are not verified authorship, truth, endorsement or authority. "
    "Suppression prevents source reentry, not necessarily current forgetting. "
    "External source availability is not checked."
)
ROUTES = frozenset({"explicit_local_operator", "activated_session_model"})


def validate(payload):
    if type(payload) is not dict or set(payload) != {"record_id"}:
        raise MemoryError("invalid_request")
    return {"record_id": _identifier(payload["record_id"])}


def validate_result(request, data):
    require(
        type(data) is dict
        and set(data)
        == {
            "namespace_id",
            "record_id",
            "evaluated_at",
            "current",
            "current_editing_route",
            "origin",
            "scope",
            "notice",
        }
    )
    _text(data["namespace_id"], 256)
    require(data["record_id"] == request["record_id"])
    require(data["scope"] == SCOPE and data["notice"] == NOTICE)
    require(type(data["evaluated_at"]) is str)
    validate_expiry(data["evaluated_at"])
    now = datetime.fromisoformat(data["evaluated_at"])
    current = data["current"]
    require(
        type(current) is dict
        and set(current)
        == {
            "record_id",
            "revision",
            "status",
            "expires_at",
            "expired",
        }
    )
    require(current["record_id"] == request["record_id"])
    integer(current["revision"])
    require(type(current["status"]) is str and current["status"] in {"active", "forgotten"})
    expiry = validate_expiry(current["expires_at"])
    require(type(current["expired"]) is bool)
    require(current["expired"] == (expiry is not None and datetime.fromisoformat(expiry) <= now))
    route = data["current_editing_route"]
    if current["status"] == "forgotten":
        require(route is None and expiry is None and current["revision"] >= 2)
    else:
        require(type(route) is str and route in ROUTES)
    origin = data["origin"]
    require(type(origin) is dict and type(origin.get("kind")) is str)
    kind = origin["kind"]
    if kind == "unavailable":
        require(set(origin) == {"kind", "reason"} and origin["reason"] == "no_durable_lineage")
    else:
        base = {"kind", "acceptance", "suppressed"}
        if kind == "reviewed_candidate":
            require(set(origin) == base | {"candidate_id"})
            _identifier(origin["candidate_id"])
        else:
            require(kind in {"observed_native_snapshot", "retained_native_snapshot"})
            require(set(origin) == base | {"role", "consumer_id", "source_sequence"})
            require(type(origin["role"]) is str and origin["role"] in {"user", "assistant"})
            _match(origin["consumer_id"], r"[a-z][a-z0-9_.-]{0,63}")
            integer(origin["source_sequence"])
            require(origin["source_sequence"] <= 1000)
        require(type(origin["suppressed"]) is bool)
        require(current["revision"] == 1 or origin["suppressed"])
        acceptance = origin["acceptance"]
        require(
            type(acceptance) is dict
            and set(acceptance)
            == {
                "record_id",
                "revision",
                "status",
                "event_sequence",
            }
        )
        require(acceptance["record_id"] == request["record_id"])
        require(type(acceptance["revision"]) is int and acceptance["revision"] == 1)
        require(acceptance["status"] == "active")
        integer(acceptance["event_sequence"])
        require(current["revision"] != 1 or current["status"] == "active")
    require(
        len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode())
        <= MAX_OUTPUT_BYTES
    )


def _bounded(column, maximum):
    return (
        f"CASE WHEN {column} IS NULL OR length(CAST({column} AS BLOB))<={maximum} "
        f"THEN {column} ELSE 0 END"
    )


def _parent(conn, candidate, receipts):
    columns = {
        "candidate_id": 36,
        "state": 9,
        "created_at": 20,
        "expires_at": 20,
        "action_digest": 64,
        "receipt": 2048,
    }
    raw = conn.execute(
        "SELECT revision,"
        + ",".join(_bounded(k, v) for k, v in columns.items())
        + " FROM memory_candidates WHERE candidate_id=?",
        (candidate,),
    ).fetchone()
    require(raw is not None)
    row = dict(zip(("revision", *columns), raw, strict=True))
    require(
        row["candidate_id"] == candidate and type(row["revision"]) is int and row["revision"] == 2
    )
    require(row["state"] in {"accepted", "discarded"})
    for field in ("created_at", "expires_at"):
        require(type(row[field]) is str)
        validate_expiry(row[field])
    require(
        datetime.fromisoformat(row["expires_at"]) - datetime.fromisoformat(row["created_at"])
        == timedelta(days=7)
    )
    _digest(row["action_digest"])
    require(type(row["receipt"]) is str)
    receipt = json.loads(row["receipt"], object_pairs_hook=_unique_object)
    expected = {
        k: row[k] for k in ("candidate_id", "revision", "state", "created_at", "expires_at")
    }
    if row["state"] == "accepted":
        require(type(receipt) is dict and set(receipt) == set(expected) | {"record"})
        record = receipt["record"]
        receipt_valid(record)
        require(record["operation"] == "remember")
        key = "candidate.accept." + candidate
        require(record["request_id"] == key and key in receipts and receipts[key][1] == record)
        expected["record"] = record
    require(receipt == expected)
    return receipt


def _lineage(conn, records, receipts):
    """Validate existing anchors, not erased candidate fields or legacy reconstruction."""
    links, suppressions, parents = {}, set(), {}
    candidate_digests = {}
    for table, fields in (
        ("memory_source_lineage", {"candidate_id": 36, "record_id": 36, "source_digest": 64}),
        ("memory_source_suppressions", {"source_digest": 64, "candidate_id": 36}),
    ):
        rows = conn.execute(
            "SELECT "
            + ",".join(_bounded(k, v) for k, v in fields.items())
            + f" FROM {table} LIMIT 1001"
        ).fetchall()
        require(len(rows) <= 1000)
        for raw in rows:
            row = dict(zip(fields, raw, strict=True))
            cid, digest = row["candidate_id"], row["source_digest"]
            _identifier(cid)
            _digest(digest)
            if cid not in parents:
                parents[cid] = _parent(conn, cid, receipts)
            parent = parents[cid]
            if table == "memory_source_lineage":
                rid = _identifier(row["record_id"])
                require(rid in records and rid not in links and parent["state"] == "accepted")
                require(parent["record"]["record_id"] == rid)
                links[rid] = (cid, digest, parent["record"])
                candidate_digests[cid] = digest
            else:
                # A same-candidate lineage retains the exact digest. Legacy
                # candidates without lineage cannot reconstruct this evidence.
                require(cid not in candidate_digests or candidate_digests[cid] == digest)
                suppressions.add(digest)
    return links, suppressions


def inspect_origin(backend, conn, request, now):
    """Caller owns the canonical snapshot, established before sampling the clock."""
    try:
        records, receipts = validate_metadata(backend, conn, now)
        retained, _ = validate_store(conn, now)
        links, suppressions = _lineage(conn, records, receipts)
        retained_links = {
            row["record_id"]: row for row in retained.values() if row["state"] == "accepted"
        }
        require(not (links.keys() & retained_links.keys()))
        for rid, (_, digest, _) in links.items():
            require(
                records[rid]["revision"] == 1
                or digest in suppressions
                or is_suppressed(conn, digest)
            )
        rid = request["record_id"]
        if rid not in records:
            raise MemoryError("not_found")
        raw = conn.execute(
            "SELECT "
            + _bounded("source", 32)
            + ","
            + _bounded("expires_at", 20)
            + " FROM records WHERE record_id=?",
            (rid,),
        ).fetchone()
        # Oversized expiry is already rejected by canonical metadata validation.
        route, expiry = raw
        origin: dict = {"kind": "unavailable", "reason": "no_durable_lineage"}
        if rid in retained_links:
            row = retained_links[rid]
            receipt = json.loads(row["receipt"], object_pairs_hook=_unique_object)
            origin = {
                "kind": row["source_kind"],
                "role": row["source_role"],
                "consumer_id": row["consumer_id"],
                "source_sequence": row["source_sequence"],
                "suppressed": bool(row["suppressed"])
                or is_suppressed(conn, row["source_fingerprint"])
                or row["source_fingerprint"] in suppressions,
            }
        elif rid in links:
            candidate, digest, receipt = links[rid]
            origin = {
                "kind": "reviewed_candidate",
                "candidate_id": candidate,
                "suppressed": digest in suppressions or is_suppressed(conn, digest),
            }
        if origin["kind"] != "unavailable":
            origin["acceptance"] = {
                key: receipt[key] for key in ("record_id", "revision", "status", "event_sequence")
            }
        data = {
            "namespace_id": backend._namespace,
            "record_id": rid,
            "evaluated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "current": {**records[rid], "expires_at": expiry},
            "current_editing_route": route,
            "origin": origin,
            "scope": SCOPE,
            "notice": NOTICE,
        }
        validate_result(request, data)
        return data
    except (ValueError, TypeError, KeyError, RecursionError, MemoryError) as error:
        if isinstance(error, MemoryError) and error.code == "not_found":
            raise
        raise MemoryError("storage_corrupt") from None
