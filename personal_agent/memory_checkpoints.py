"""Durable local record-metadata checkpoints, never native transcript coverage.

The backend holds its owned SQLite transaction throughout capture and receipt
publication. No payload text, content hash, source/session label or derived file
is retained. A checkpoint is an integrity/recovery marker, not a restorable copy.
"""

import hashlib
import json
from uuid import uuid4

from .memory_backend import MemoryError

CHECKPOINT_SCHEMA = {
    "record_checkpoints": """CREATE TABLE record_checkpoints (
        checkpoint_id TEXT PRIMARY KEY NOT NULL,
        request_id TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, receipt TEXT NOT NULL)""",
}
MAX_CHECKPOINTS = 256


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _state(conn):
    """Bounded, metadata-only validation of retained event and current-state linkage."""
    records = conn.execute(
        "SELECT record_id,revision,status FROM records ORDER BY record_id LIMIT 1001"
    ).fetchall()
    events = conn.execute(
        "SELECT sequence,record_id,revision,operation FROM events ORDER BY sequence LIMIT 11001"
    ).fetchall()
    if len(records) > 1000 or len(events) > 11000:
        raise MemoryError("checkpoint_state_limit")
    latest = {}
    nonterminal = 0
    for sequence, rid, revision, operation in events:
        previous = latest.get(rid)
        if (
            type(sequence) is not int
            or sequence < 1
            or type(revision) is not int
            or (previous is None and (revision != 1 or operation != "remember"))
            or (
                previous is not None
                and (
                    previous[1] == "forgotten"
                    or revision != previous[0] + 1
                    or operation not in {"correct", "forget"}
                )
            )
        ):
            raise MemoryError("checkpoint_state_inconsistent")
        status = "forgotten" if operation == "forget" else "active"
        latest[rid] = (revision, status)
        nonterminal += operation != "forget"
    if nonterminal > 10000:
        raise MemoryError("checkpoint_state_limit")
    if {rid: (revision, status) for rid, revision, status in records} != latest:
        raise MemoryError("checkpoint_state_inconsistent")
    return {
        "through_sequence": events[-1][0] if events else 0,
        "event_count": len(events),
        "record_count": len(records),
        "active_count": sum(status == "active" for _, _, status in records),
        "forgotten_count": sum(status == "forgotten" for _, _, status in records),
        "metadata_sha256": _digest({"records": records, "events": events}),
    }


def create_checkpoint(conn, request):
    digest = _digest(request)
    old = conn.execute(
        "SELECT digest,receipt FROM record_checkpoints WHERE request_id=?", (request["request_id"],)
    ).fetchone()
    if old:
        if old[0] != digest:
            raise MemoryError("idempotency_conflict")
        # Historical receipt only. Replay is deliberately not a current-state check.
        return {"data": json.loads(old[1]), "replayed": True}
    state = _state(conn)
    if state["through_sequence"] != request["expected_watermark"]:
        raise MemoryError("watermark_conflict")
    if conn.execute("SELECT count(*) FROM record_checkpoints").fetchone()[0] >= MAX_CHECKPOINTS:
        raise MemoryError("checkpoint_limit")
    receipt = {
        "schema_version": "personal.memory.metadata_checkpoint.v1",
        "checkpoint_id": str(uuid4()),
        "request_id": request["request_id"],
        **state,
        "scope": "local_record_metadata_not_native_conversation",
        "restorable": False,
        "native_checkpoint": False,
    }
    conn.execute(
        "INSERT INTO record_checkpoints VALUES (?,?,?,?)",
        (
            receipt["checkpoint_id"],
            request["request_id"],
            digest,
            json.dumps(receipt, sort_keys=True),
        ),
    )
    return {"data": receipt, "replayed": False}


def checkpoint_status(conn, checkpoint_id):
    row = conn.execute(
        "SELECT receipt FROM record_checkpoints WHERE checkpoint_id=?", (checkpoint_id,)
    ).fetchone()
    if row is None:
        raise MemoryError("checkpoint_not_found")
    receipt = json.loads(row[0])
    state = _state(conn)
    return {
        "checkpoint": receipt,
        "is_current": all(receipt[key] == value for key, value in state.items()),
        "current_watermark": state["through_sequence"],
        "scope": "metadata_comparison_at_this_read_snapshot_not_restore_or_authority",
    }
