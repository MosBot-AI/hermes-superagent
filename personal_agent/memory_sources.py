"""Exact-input candidate suppression; fingerprints are not anonymous or authority."""

import json
import re

from .memory_backend import MemoryError, _identifier

SCHEMA = {
    "memory_source_lineage": """CREATE TABLE memory_source_lineage (
        candidate_id TEXT PRIMARY KEY NOT NULL REFERENCES memory_candidates(candidate_id),
        record_id TEXT UNIQUE NOT NULL REFERENCES records(record_id),
        source_digest TEXT NOT NULL CHECK(length(source_digest)=64))""",
    "memory_source_suppressions": """CREATE TABLE memory_source_suppressions (
        source_digest TEXT PRIMARY KEY NOT NULL CHECK(length(source_digest)=64),
        candidate_id TEXT UNIQUE NOT NULL REFERENCES memory_candidates(candidate_id))""",
}


def validate(conn):
    try:
        _validate(conn)
    except MemoryError, ValueError, TypeError, KeyError:
        raise MemoryError("storage_corrupt") from None


def _validate(conn):
    # Every retained marker is anchored to a never-evicted candidate; there is no
    # separate quota which could make forgetting fail when capacity is reached.
    for table in SCHEMA:
        rows = conn.execute(f"SELECT * FROM {table} LIMIT 1001").fetchall()
        if len(rows) > 1000:
            raise MemoryError("storage_corrupt")
        for row in rows:
            if table == "memory_source_lineage":
                candidate, record, fingerprint = row
                _identifier(record)
                if not conn.execute(
                    "SELECT 1 FROM records WHERE record_id=?", (record,)
                ).fetchone():
                    raise MemoryError("storage_corrupt")
            else:
                fingerprint, candidate = row
            _identifier(candidate)
            if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                raise MemoryError("storage_corrupt")
            from .memory_candidate_store import row_data

            parent = row_data(
                conn.execute(
                    "SELECT * FROM memory_candidates WHERE candidate_id=?", (candidate,)
                ).fetchone()
            )
            if table == "memory_source_lineage":
                if (
                    parent["state"] != "accepted"
                    or json.loads(parent["receipt"])["record"]["record_id"] != record
                ):
                    raise MemoryError("storage_corrupt")
            elif parent["state"] not in {"accepted", "discarded"}:
                raise MemoryError("storage_corrupt")


def check(conn, fingerprint):
    if conn.execute(
        "SELECT 1 FROM memory_source_suppressions WHERE source_digest=?", (fingerprint,)
    ).fetchone():
        raise MemoryError("candidate_source_suppressed")


def suppress(conn, fingerprint, candidate, *, target=None, action=None):
    from .memory_candidate_store import digest, metadata, row_data, terminal

    conn.execute(
        "INSERT INTO memory_source_suppressions VALUES (?,?) ON CONFLICT(source_digest) DO NOTHING",
        (fingerprint, candidate),
    )
    for raw in conn.execute(
        "SELECT * FROM memory_candidates WHERE state='pending' AND source_digest=?", (fingerprint,)
    ).fetchall():
        row = row_data(raw)
        receipt = {**metadata(row), "revision": 2, "state": "discarded"}
        terminal(
            conn,
            row,
            "discarded",
            action
            if row["candidate_id"] == target
            else digest(["source_suppressed", row["candidate_id"]]),
            receipt,
        )


def suppress_record(conn, record_id):
    row = conn.execute(
        "SELECT source_digest,candidate_id FROM memory_source_lineage WHERE record_id=?",
        (record_id,),
    ).fetchone()
    if row:
        suppress(conn, *row)
