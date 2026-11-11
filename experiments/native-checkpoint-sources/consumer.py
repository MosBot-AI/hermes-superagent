"""Synthetic explicit owner consumer: read-only project resolver -> host commit.

This does not implement the future cross-store memory consumer or enable v2.
"""

from hermes_state import SessionDB
from hermes_state_checkpoint_sources import (
    SourceReceiptError,
    commit_source_request,
    prepare_source_request,
    read_receipt_sources,
    source_receipt_status,
)

from personal_agent.checkpoint_evidence import prepare_checkpoint_evidence
from personal_agent.native_source_resolution import NativeSourceBinding, resolve_checkpoint_sources


def prepare(db_path, session_id, attempt_id, normalized, summary):
    evidence = prepare_checkpoint_evidence(normalized)
    with SessionDB(db_path, read_only=True) as reader:
        resolved = resolve_checkpoint_sources(
            evidence, binding=NativeSourceBinding(reader, session_id)
        )
        candidates = [
            {
                "role": item.role,
                "content": item.content,
                "uids": [item.message_uid, *item.absorbed_message_uids],
            }
            for item in evidence.messages
        ]
        request = prepare_source_request(
            reader, session_id, attempt_id, candidates, [{"role": "assistant", "content": summary}]
        )
        # The host observes again and supplies a stricter raw-row fingerprint.
        # A race across the two preparations must not silently select new rows.
        expected_revision = [list(resolved.observed_revision[0]), *resolved.observed_revision[1:]]
        if request["revision"] != expected_revision or [
            [source["id"] for source in group] for group in request["sources"]
        ] != [list(ref.row_ids) for ref in resolved.references]:
            raise ValueError("source_observation_changed")
        return request


def commit_and_inspect(db_path, session_id, request):
    with SessionDB(db_path) as writer:
        committed = commit_source_request(writer, session_id, request)
    with SessionDB(db_path, read_only=True) as reader:
        availability = source_receipt_status(reader, session_id, request["attempt_id"])
    return committed, availability


def read_original_sources(db_path, session_id, attempt_id, expected_receipt_id):
    """Explicit optional read, no journal/accounting/cursor or memory writes."""
    try:
        with SessionDB(db_path, read_only=True) as reader:
            return read_receipt_sources(reader, session_id, attempt_id, expected_receipt_id)
    except SourceReceiptError:
        raise
    except Exception:
        return {"status": "unavailable", "available": False, "durable_memory_checkpoint": False}
