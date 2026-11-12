"""Explicit LOCAL retention of one reviewed original, never automatic capture.

Native observation and canonical acceptance have independent lifetimes. A saved
request identity supports metadata-only recovery without reopening native text.
"""

import hashlib

from .memory_backend import MemoryError, MemoryService
from .memory_storage import open_existing_memory_reader, open_memory_backend
from .native_source_workbench import run as review
from .native_source_workbench import validate as validate_review
from .retained_sources import source_request_identity
from .retained_sources import validate as validate_source

OPERATIONS = frozenset(
    {
        "source_preview",
        "source_retain",
        "source_status",
        "source_discard",
        "source_cursor",
        "source_discover",
    }
)


def validate(operation, payload):
    if type(operation) is not str or operation not in OPERATIONS or type(payload) is not dict:
        raise MemoryError("invalid_request")
    if operation in {"source_status", "source_discard", "source_cursor", "source_discover"}:
        return validate_source(operation, payload)
    fields = {
        "message_uid",
        "expected_snapshot",
        "consumer_id",
        "expected_sequence",
        "request_id",
        "retention",
        "expires_at",
        "topic",
    }
    if operation == "source_retain":
        fields.add("expected_digest")
    if set(payload) != fields:
        raise MemoryError("invalid_request")
    validate_review("source_show", {k: payload[k] for k in ("message_uid", "expected_snapshot")})
    # Reuse the strict canonical request-field validator without reading sources
    # or introducing a second subtly different admission contract.
    validate_source(
        "source_stage",
        {
            **{
                k: payload[k]
                for k in (
                    "consumer_id",
                    "expected_sequence",
                    "request_id",
                    "retention",
                    "expires_at",
                    "topic",
                )
            },
            "content": "validation",
            "source": {
                "identity": "0" * 64,
                "fingerprint": hashlib.sha256(b"validation").hexdigest(),
                "role": "user",
                "kind": "observed_native_snapshot",
                "observation_id": "0" * 64,
            },
        },
    )
    if operation == "source_retain":
        validate_source(
            "source_status",
            {"request_id": payload["request_id"], "expected_digest": payload["expected_digest"]},
        )
    return dict(payload)


def run(home, session_id, operation, payload):
    """Called only after native LOCAL/configuration admission; no model entry."""
    payload = validate(operation, payload)
    if operation in {"source_status", "source_cursor", "source_discard", "source_discover"}:
        opener = (
            open_memory_backend if operation == "source_discard" else open_existing_memory_reader
        )
        with opener(home, session_id) as backend:
            return MemoryService(backend).execute(operation, payload)
    observed = review(
        home,
        session_id,
        "source_show",
        {k: payload[k] for k in ("message_uid", "expected_snapshot")},
        capture=True,
    )["data"]
    request = {
        **{
            k: payload[k]
            for k in (
                "consumer_id",
                "expected_sequence",
                "request_id",
                "retention",
                "expires_at",
                "topic",
            )
        },
        "content": observed["item"]["content"],
        "source": observed["retained_source"],
    }
    query = source_request_identity(request)
    if operation == "source_preview":
        return {
            "data": {
                "payload": request,
                "query": query,
                "selection": {
                    k: observed[k]
                    for k in (
                        "snapshot",
                        "read_consistency",
                        "scanned_row_count",
                        "eligible_count",
                        "excluded_count",
                    )
                },
                "message_uid": payload["message_uid"],
                "absorbed_message_uids": observed["item"]["absorbed_message_uids"],
                "canonical_admission": False,
                "automatic_ingestion": False,
            },
            "replayed": False,
        }
    if query["expected_digest"] != payload["expected_digest"]:
        raise MemoryError("source_preview_changed")
    # No text is persisted in the pending slot. Once captured and explicitly
    # authorized, this independent snapshot may outlive its native row. This is
    # not a distributed transaction or native-current-at-commit guarantee.
    with open_memory_backend(home, session_id) as backend:
        service = MemoryService(backend)
        service.execute("source_stage", request)
        return service.execute("source_accept", request)
