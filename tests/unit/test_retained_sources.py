"""Canonical retained-source integrity and cross-family privacy regressions."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, source_request_identity


def request(key="import", content="Synthetic original", *, observed=False, **updates):
    payload = {
        "request_id": key,
        "consumer_id": "native-source",
        "expected_sequence": 0,
        "content": content,
        "topic": "reviewed import",
        "expires_at": None,
        "retention": "independent_snapshot",
        "source": {
            "identity": hashlib.sha256(key.encode()).hexdigest(),
            "fingerprint": hashlib.sha256(content.encode()).hexdigest(),
            "role": "user",
            "receipt_id": "a" * 64,
        },
        **updates,
    }

    if observed:
        source = payload["source"]
        source["kind"] = "observed_native_snapshot"
        source["observation_id"] = source.pop("receipt_id")
    return payload


@contextmanager
def opened():
    connection = sqlite3.connect(":memory:")
    backend = create_backend()
    backend.open(connection, namespace_id="synthetic", session_ref="synthetic-session")
    sdk = LocalMemorySDK(backend, LocalBinding("synthetic", "synthetic-session"))
    try:
        yield sdk, backend, connection
    finally:
        sdk.close()
        connection.close()


def accept(sdk, payload):
    sdk.execute("source_stage", payload)
    return sdk.execute("source_accept", payload)["data"]["record"]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE records SET revision=99",
        "UPDATE records SET status='forgotten',content=NULL,topic=NULL,"
        "source=NULL,session_ref=NULL",
        "DELETE FROM events",
        "DELETE FROM receipts",
        "UPDATE receipts SET digest='invalid'",
        "UPDATE records SET expires_at='2030-01-01T00:00:00Z' || char(0) || 'bad'",
        "UPDATE retained_source_decisions SET request_digest='x'",
        "UPDATE retained_source_decisions SET source_sequence=2",
        "UPDATE retained_source_decisions SET source_role='tool'",
        "UPDATE retained_source_decisions SET receipt='{}'",
        "UPDATE retained_source_decisions SET source_identity=source_identity || char(0)",
        "UPDATE retained_source_decisions SET source_receipt=printf('%0100000d',1)",
        "UPDATE namespace SET id='other'",
    ],
)
@pytest.mark.parametrize("operation", ["source_status", "source_cursor"])
def test_corrupt_evidence_never_success_or_absence(sql, operation):
    with opened() as (sdk, _, connection):
        payload = request()
        accept(sdk, payload)
        connection.execute("UPDATE retained_source_decisions SET suppressed=1")
        connection.execute(sql)
        connection.commit()
        before = list(connection.iterdump())
        query = (
            source_request_identity(payload)
            if operation == "source_status"
            else {"consumer_id": "native-source"}
        )
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute(operation, query)
        assert list(connection.iterdump()) == before


@pytest.mark.parametrize("mutation", ["correct", "forget", "source_discard"])
@pytest.mark.parametrize("observed", [False, True])
def test_retained_suppression_purges_current_input_drafts(mutation, observed):
    with opened() as (sdk, backend, connection):
        payload = request(observed=observed)
        if mutation == "source_discard":
            sdk.execute("source_stage", payload)
        else:
            receipt = accept(sdk, payload)
        backend._source_kind = "activated_session_model"
        service = MemoryService(backend)
        draft = service.execute(
            "candidate_propose",
            {
                "request_id": "draft",
                "content": "unverified derived draft",
                "quote": payload["content"],
                "quote_start": 0,
                "source_digest": payload["source"]["fingerprint"],
                "source_turn": "b" * 64,
            },
        )["data"]
        backend._source_kind = "explicit_local_operator"
        if mutation == "source_discard":
            sdk.execute(mutation, source_request_identity(payload))
        else:
            sdk.execute(
                mutation,
                {
                    "record_id": receipt["record_id"],
                    "expected_revision": 1,
                    "request_id": "mutation",
                    **({"content": "Corrected"} if mutation == "correct" else {}),
                },
            )
        stored = connection.execute(
            "SELECT state,content,quote,source_digest FROM memory_candidates"
        ).fetchone()
        assert stored == ("discarded", None, None, None)
        assert (
            service.execute("candidate_get", {"candidate_id": draft["candidate_id"]})["data"][
                "state"
            ]
            == "discarded"
        )
        backend._source_kind = "activated_session_model"
        with pytest.raises(MemoryError, match="candidate_source_suppressed"):
            service.execute(
                "candidate_propose",
                {
                    "request_id": "new-key",
                    "content": "new draft",
                    "quote": payload["content"],
                    "quote_start": 0,
                    "source_digest": payload["source"]["fingerprint"],
                    "source_turn": "c" * 64,
                },
            )


@pytest.mark.parametrize("observed", [False, True])
def test_candidate_suppression_blocks_previously_staged_source(observed):
    with opened() as (sdk, backend, _):
        payload = request(observed=observed)
        sdk.execute("source_stage", payload)
        backend._source_kind = "activated_session_model"
        service = MemoryService(backend)
        draft = service.execute(
            "candidate_propose",
            {
                "request_id": "draft",
                "content": "derived draft",
                "quote": payload["content"],
                "quote_start": 0,
                "source_digest": payload["source"]["fingerprint"],
                "source_turn": "b" * 64,
            },
        )["data"]
        backend._source_kind = "explicit_local_operator"
        service.execute(
            "candidate_suppress_source",
            {"candidate_id": draft["candidate_id"], "expected_revision": 1},
        )
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_accept", payload)
        status = sdk.execute("source_status", source_request_identity(payload))["data"]
        assert status["decision"]["state"] == "pending" and status["suppressed"]
        assert (
            sdk.execute("source_cursor", {"consumer_id": "native-source"})["data"][
                "through_sequence"
            ]
            == 0
        )
        assert (
            sdk.execute("source_discard", source_request_identity(payload))["data"]["state"]
            == "discarded"
        )


@pytest.mark.parametrize("stage", ["before_lineage", "before_receipt"])
def test_acceptance_failure_rolls_back_every_canonical_table(stage):
    with opened() as (sdk, _, connection):
        payload = request()
        sdk.execute("source_stage", payload)
        before = list(connection.iterdump())
        table = "retained_source_decisions" if stage == "before_lineage" else "receipts"
        action = sqlite3.SQLITE_UPDATE if stage == "before_lineage" else sqlite3.SQLITE_INSERT
        connection.set_authorizer(
            lambda code, name, *_: (
                sqlite3.SQLITE_DENY if code == action and name == table else sqlite3.SQLITE_OK
            )
        )
        with pytest.raises(MemoryError, match="outcome_unknown"):
            sdk.execute("source_accept", payload)
        connection.set_authorizer(None)
        assert list(connection.iterdump()) == before
        assert (
            sdk.execute("source_status", source_request_identity(payload))["data"]["decision"][
                "state"
            ]
            == "pending"
        )


def test_internal_receipt_collision_cannot_relabel_existing_memory():
    from personal_agent.retained_sources import _record_key

    with opened() as (sdk, _, connection):
        payload = request()
        sdk.execute("remember", {"request_id": _record_key("import"), "content": "Unrelated"})
        sdk.execute("source_stage", payload)
        before = list(connection.iterdump())
        with pytest.raises(MemoryError, match="idempotency_conflict"):
            sdk.execute("source_accept", payload)
        assert list(connection.iterdump()) == before
        assert "Unrelated" in json.dumps(sdk.execute("list", {}))
