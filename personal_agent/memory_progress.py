"""Local event cursors, not evidence that a native transcript was checkpointed.

Only the trusted adapter invokes these functions inside its owned transaction.
There is no background consumer, payload copy, model tool or external side effect.
"""

import hashlib
import json

from .memory_backend import MemoryError

PROGRESS_SCHEMA = {
    "consumer_cursors": """CREATE TABLE consumer_cursors (
        consumer_id TEXT PRIMARY KEY NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        through_sequence INTEGER NOT NULL CHECK(through_sequence >= 0))""",
    "consumer_receipts": """CREATE TABLE consumer_receipts (
        request_id TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, receipt TEXT NOT NULL)""",
}
MAX_CONSUMERS = 32
MAX_CURSOR_MUTATIONS = 10000


def _watermark(conn):
    return conn.execute("SELECT coalesce(max(sequence),0) FROM events").fetchone()[0]


def _known_sequence(conn, sequence):
    if (
        sequence
        and conn.execute("SELECT 1 FROM events WHERE sequence=?", (sequence,)).fetchone() is None
    ):
        raise MemoryError("invalid_sequence")


def get_changes(conn, request):
    watermark = _watermark(conn)
    through = request["through_sequence"]
    if through is None:
        through = watermark
    if through > watermark:
        raise MemoryError("future_watermark")
    after = request["after_sequence"]
    if after > through:
        raise MemoryError("invalid_sequence")
    _known_sequence(conn, after)
    _known_sequence(conn, through)
    rows = conn.execute(
        "SELECT sequence,record_id,revision,operation FROM events "
        "WHERE sequence>? AND sequence<=? ORDER BY sequence LIMIT ?",
        (after, through, request["limit"] + 1),
    ).fetchall()
    more = len(rows) > request["limit"]
    items = [
        dict(zip(("sequence", "record_id", "revision", "operation"), row, strict=True))
        for row in rows[: request["limit"]]
    ]
    return {
        "schema_version": "personal.memory.changes.v1",
        "items": items,
        "through_sequence": through,
        "current_watermark": watermark,
        "next_sequence": items[-1]["sequence"] if items else after,
        "has_more": more,
        "retention_floor": 0,
        "scope": "committed_record_event_metadata_no_historical_payload",
    }


def get_consumer(conn, consumer_id):
    row = conn.execute(
        "SELECT revision,through_sequence FROM consumer_cursors WHERE consumer_id=?", (consumer_id,)
    ).fetchone()
    return {
        "consumer_id": consumer_id,
        "revision": row[0] if row else 0,
        "through_sequence": row[1] if row else 0,
        "registered": row is not None,
        "scope": "caller_reported_local_record_progress_not_native_checkpoint",
    }


def advance_consumer(conn, request):
    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    old = conn.execute(
        "SELECT digest,receipt FROM consumer_receipts WHERE request_id=?", (request["request_id"],)
    ).fetchone()
    if old:
        if old[0] != digest:
            raise MemoryError("idempotency_conflict")
        return {"data": json.loads(old[1]), "replayed": True}
    current = get_consumer(conn, request["consumer_id"])
    if current["revision"] != request["expected_revision"]:
        raise MemoryError("revision_conflict")
    through = request["through_sequence"]
    if through > _watermark(conn):
        raise MemoryError("future_watermark")
    _known_sequence(conn, through)
    if current["registered"] and through <= current["through_sequence"]:
        raise MemoryError("cursor_not_advanced")
    if (
        not current["registered"]
        and conn.execute("SELECT count(*) FROM consumer_cursors").fetchone()[0] >= MAX_CONSUMERS
    ):
        raise MemoryError("consumer_limit")
    if conn.execute("SELECT count(*) FROM consumer_receipts").fetchone()[0] >= MAX_CURSOR_MUTATIONS:
        raise MemoryError("consumer_mutation_limit")
    receipt = {
        **current,
        "registered": True,
        "revision": current["revision"] + 1,
        "through_sequence": through,
        "request_id": request["request_id"],
    }
    conn.execute(
        "INSERT INTO consumer_cursors VALUES (?,?,?) ON CONFLICT(consumer_id) DO UPDATE "
        "SET revision=excluded.revision,through_sequence=excluded.through_sequence",
        (request["consumer_id"], receipt["revision"], through),
    )
    conn.execute(
        "INSERT INTO consumer_receipts VALUES (?,?,?)",
        (request["request_id"], digest, json.dumps(receipt, sort_keys=True)),
    )
    return {"data": receipt, "replayed": False}
