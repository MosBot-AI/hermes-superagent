"""Synthetic explicit owner consumer: read-only project resolver -> host commit.

Includes an explicit retained-snapshot experiment, not production hooks or v2.
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


def capture_retained_snapshot(
    db_path,
    session_id,
    attempt_id,
    expected_receipt_id,
    *,
    trusted_store_identity,
    message_uid,
    request_id,
    consumer_id,
    expected_sequence,
    expires_at,
    operator_acknowledged=False,
    topic="",
):
    """Capture ONE original row for an independently authorized retained import.

    All arguments are trusted local operator inputs, never parsed from source
    text. The stable store identity belongs to the host configuration, not a
    receipt, request key or model. Keep it unchanged across reopen/re-receipt.
    This returns caller-owned plaintext plus a metadata-only recovery query;
    retain the query before staging. No canonical storage is opened or written.
    Later native deletion does NOT revoke this explicit snapshot authorization
    or forget canonical text. No current-source-validity fence is claimed.
    """
    import hashlib
    import json

    from personal_agent.memory_sdk import source_request_identity

    _require_operator(operator_acknowledged)
    if (
        type(trusted_store_identity) is not str
        or not trusted_store_identity.strip()
        or len(trusted_store_identity) > 256
        or type(message_uid) is not str
    ):
        raise ValueError("invalid_source_binding")
    snapshot = read_original_sources(db_path, session_id, attempt_id, expected_receipt_id)
    if snapshot.get("status") != "available_at_snapshot" or not snapshot.get("available"):
        raise ValueError("source_snapshot_unavailable")
    rows = [row for row in snapshot["sources"] if row["message_uid"] == message_uid]
    if len(rows) != 1:
        raise ValueError("source_selection_mismatch")
    row = rows[0]
    # Receipt IDs and import keys must not turn one original into new identities.
    identity = hashlib.sha256(
        json.dumps(
            ["native_original_v1", trusted_store_identity, session_id, row["message_uid"]],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    payload = {
        "request_id": request_id,
        "consumer_id": consumer_id,
        "expected_sequence": expected_sequence,
        "content": row["content"],
        "topic": topic,
        "expires_at": expires_at,
        "retention": "independent_snapshot",
        "source": {
            "identity": identity,
            "fingerprint": hashlib.sha256(row["content"].encode()).hexdigest(),
            "role": row["role"],
            "receipt_id": expected_receipt_id,
        },
    }
    # Validates exact content (including the 2,048-character bound), without
    # truncating, merging, summarizing, or relabeling assistant evidence as user.
    return {"payload": payload, "query": source_request_identity(payload)}


def _require_operator(acknowledged):
    if acknowledged is not True:
        raise ValueError("explicit_retention_acknowledgment_required")


def execute_retained_snapshot(sdk, captured, operation, *, operator_acknowledged=False):
    """One explicit stage/accept call; no automatic retries or cursor skipping.

    The caller retains captured['query'] before calling stage, then supplies the
    same payload at accept. Unknown outcomes stay unresolved: inspect source_status
    with the retained query, never invent a fresh request key. The SDK/backend
    separately require explicit_local_operator authority. This does not reopen
    the native source or assert it is still valid at canonical commit time.
    """
    from personal_agent.memory_sdk import source_request_identity

    _require_operator(operator_acknowledged)
    if operation not in {"source_stage", "source_accept"}:
        raise ValueError("invalid_source_operation")
    if source_request_identity(captured["payload"]) != captured["query"]:
        raise ValueError("captured_request_changed")
    return sdk.execute(operation, captured["payload"])
