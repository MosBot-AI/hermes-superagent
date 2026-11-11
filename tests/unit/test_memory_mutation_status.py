"""Synthetic identity, receipt integrity and hostile adapter boundary checks."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, validate_request
from personal_agent.memory_conformance import run_mutation_status_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, mutation_request_identity


@pytest.fixture
def opened(tmp_path):
    @contextmanager
    def factory():
        conn = sqlite3.connect(tmp_path / "synthetic.sqlite")
        backend = create_backend()
        backend.open(conn, namespace_id="test", session_ref="private-session")
        sdk = LocalMemorySDK(backend, LocalBinding("test", "private-session"))
        try:
            yield sdk, conn
        finally:
            sdk.close()
            conn.close()

    return factory


def seed(sdk):
    request = {"content": "private-content", "topic": "private-topic", "request_id": "key"}
    identity = mutation_request_identity("remember", request)
    receipt = sdk.execute("remember", request)["data"]
    return identity, receipt


def test_pure_normalization_and_historical_digest():
    original = {"content": "中文", "request_id": "r"}
    assert mutation_request_identity("remember", original) == mutation_request_identity(
        "remember", {**original, "topic": ""}
    )
    assert mutation_request_identity("remember", original) != mutation_request_identity(
        "remember", {**original, "expires_at": None}
    )
    for operation, payload in (
        ("remember", original),
        (
            "correct",
            {
                "record_id": "b4f1469c-ea12-4c34-abcf-1233ef97fed0",
                "expected_revision": 1,
                "topic": "",
                "request_id": "c",
            },
        ),
        (
            "forget",
            {
                "record_id": "b4f1469c-ea12-4c34-abcf-1233ef97fed0",
                "expected_revision": 2,
                "request_id": "f",
            },
        ),
    ):
        before = deepcopy(payload)
        identity = mutation_request_identity(operation, payload)
        assert (
            identity["expected_digest"]
            == hashlib.sha256(
                json.dumps(
                    [operation, validate_request(operation, payload)],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        assert payload == before
        assert set(identity) == {"operation", "request_id", "expected_digest"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"operation": "remember"},
        {"operation": [], "request_id": "r", "expected_digest": "a" * 64},
        {"operation": "remember", "request_id": True, "expected_digest": "a" * 64},
        {"operation": "remember", "request_id": "x" * 129, "expected_digest": "a" * 64},
        {"operation": "remember", "request_id": "r", "expected_digest": "A" * 64},
        {"operation": "remember", "request_id": "r", "expected_digest": "a" * 65},
        {"operation": "forget", "request_id": "r", "expected_digest": "a" * 64, "content": "x"},
    ],
)
def test_invalid_query_before_dispatch(opened, payload):
    with opened() as (sdk, conn):
        calls = []
        conn.set_trace_callback(calls.append)
        with pytest.raises(MemoryError, match="invalid_request"):
            sdk.execute("mutation_receipt_status", payload)
        assert calls == []


def test_conformance_and_guards(opened):
    @contextmanager
    def factory():
        with opened() as (sdk, _):
            yield sdk

    with pytest.raises(MemoryError, match="synthetic_store_required"):
        run_mutation_status_conformance(factory)
    assert len(run_mutation_status_conformance(factory, isolated_synthetic=True).passed) == 7
    with pytest.raises(MemoryError, match="empty_store_required"):
        run_mutation_status_conformance(factory, isolated_synthetic=True)


def test_payload_free_and_no_sql_payload_fetch(opened):
    with opened() as (sdk, conn):
        query, receipt = seed(sdk)
        statements = []
        changes = conn.total_changes
        conn.set_trace_callback(statements.append)
        result = sdk.execute("mutation_receipt_status", query)
        assert result["data"]["receipt"] == receipt and result["replayed"] is False
        assert conn.total_changes == changes
        for secret in (
            "private-content",
            "private-topic",
            "private-session",
            query["expected_digest"],
        ):
            assert secret not in json.dumps(result)
        assert not any(
            "content" in sql or "topic" in sql or "session_ref" in sql for sql in statements
        )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM receipts",
        "DELETE FROM events",
        "DELETE FROM records",
        "UPDATE namespace SET id='wrong'",
        "UPDATE events SET operation='forget'",
        "UPDATE events SET revision=2",
        "UPDATE records SET revision=2",
        "UPDATE receipts SET receipt='{}'",
        "UPDATE receipts SET receipt='['",
        "UPDATE receipts SET receipt=printf('%03000d',1)",
        "UPDATE receipts SET digest='x'",
        "UPDATE receipts SET request_id='different'",
    ],
)
@pytest.mark.parametrize("missing", [False, True])
def test_corruption_never_absence(opened, sql, missing):
    with opened() as (sdk, conn):
        query, _ = seed(sdk)
        conn.execute(sql)
        conn.commit()
        if missing:
            query["request_id"] = "missing"
        with pytest.raises(MemoryError) as caught:
            sdk.execute("mutation_receipt_status", query)
        assert caught.value.code == "backend_failure"


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", True),
        ("revision", 2**63),
        ("revision", 0),
        ("event_sequence", True),
        ("event_sequence", 2**63),
        ("event_sequence", 0),
        ("record_id", "invalid"),
        ("operation", "forget"),
        ("status", "forgotten"),
        ("request_id", "different"),
        ("extra", "private"),
    ],
)
def test_bad_receipts_fail_closed(opened, field, value):
    with opened() as (sdk, conn):
        query, receipt = seed(sdk)
        receipt[field] = value
        conn.execute("UPDATE receipts SET receipt=?", (json.dumps(receipt),))
        conn.commit()
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute("mutation_receipt_status", query)


class Wrapper:
    def __init__(self, backend, transform=None, error=None, capability=True):
        self.backend, self.transform, self.error, self.capability = (
            backend,
            transform,
            error,
            capability,
        )
        self.calls = 0

    def describe(self):
        descriptor = self.backend.describe()
        if not self.capability:
            descriptor["capabilities"].remove("mutation_receipt_status")
        return descriptor

    def execute(self, operation, payload):
        if operation != "mutation_receipt_status":
            return self.backend.execute(operation, payload)
        self.calls += 1
        if self.error:
            raise self.error
        return self.transform(self.backend.execute(operation, payload))

    def close(self):
        pass


@pytest.mark.parametrize(
    "transform",
    [
        lambda r: {**r, "secret": "content"},
        lambda r: {**r, "state": "absent_at_snapshot"},
        lambda r: {**r, "evaluated_at": None},
        lambda r: {**r, "current": {**r["current"], "revision": True}},
        lambda r: {**r, "current": {**r["current"], "revision": 0}},
        lambda r: {**r, "current": {**r["current"], "expired": 1}},
        lambda r: {**r, "current": {**r["current"], "status": "forgotten", "expired": True}},
        lambda r: {**r, "receipt": {**r["receipt"], "operation": "forget"}},
        lambda r: {**r, "receipt": {**r["receipt"], "request_id": "other"}},
        lambda r: None,
    ],
)
def test_hostile_status_result(opened, transform):
    with opened() as (sdk, _):
        query, _ = seed(sdk)
        wrapper = Wrapper(sdk._service.backend, transform=transform)
        wrapped = LocalMemorySDK(wrapper, sdk.binding)
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("mutation_receipt_status", query)
        assert wrapper.calls == 1


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("private"),
        MemoryError("storage_error"),
        MemoryError("not_found"),
        MemoryError("outcome_unknown"),
    ],
)
def test_read_errors_are_not_uncertain_writes(opened, error):
    with opened() as (sdk, _):
        query, _ = seed(sdk)
        wrapper = Wrapper(sdk._service.backend, error=error)
        wrapped = LocalMemorySDK(wrapper, sdk.binding)
        with pytest.raises(MemoryError, match="backend_failure"):
            wrapped.execute("mutation_receipt_status", query)
        assert wrapper.calls == 1


def test_optional_capability_gates_before_dispatch(opened):
    with opened() as (sdk, _):
        query, _ = seed(sdk)
        wrapper = Wrapper(sdk._service.backend, capability=False)
        wrapped = LocalMemorySDK(wrapper, sdk.binding)
        with pytest.raises(MemoryError, match="capability_unavailable"):
            wrapped.execute("mutation_receipt_status", query)
        assert wrapper.calls == 0
        assert wrapped.execute("list", {})["data"]["items"]


def test_connection_state_is_error(opened):
    with opened() as (sdk, conn):
        query, _ = seed(sdk)
        conn.execute("BEGIN")
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute("mutation_receipt_status", query)
        assert conn.in_transaction
        conn.rollback()
        conn.close()
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute("mutation_receipt_status", query)


@pytest.mark.parametrize("column", ["request_id", "digest", "receipt"])
def test_embedded_nul_is_not_truncated_into_valid_identity(opened, column):
    with opened() as (sdk, conn):
        query, _ = seed(sdk)
        conn.execute(f"UPDATE receipts SET {column}={column} || ?", ("\x00junk",))
        conn.commit()
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute("mutation_receipt_status", query)


def test_retention_receipts_preserve_status_and_missing_link_detection(opened):
    with opened() as (sdk, conn):
        request = {
            "content": "private",
            "request_id": "expired",
            "expires_at": "2000-01-01T00:00:00Z",
        }
        query = mutation_request_identity("remember", request)
        receipt = sdk.execute("remember", request)["data"]
        backend = sdk._service.backend
        preview = backend.execute("expired_preview", {"before": "2001-01-01T00:00:00Z"})
        backend.execute(
            "forget_expired",
            {
                "before": "2001-01-01T00:00:00Z",
                "request_id": "batch",
                "expected_snapshot": preview["snapshot"],
            },
        )
        result = sdk.execute("mutation_receipt_status", query)["data"]
        assert result["receipt"] == receipt
        assert result["current"]["status"] == "forgotten"
        assert (
            sdk.execute("mutation_receipt_status", {**query, "request_id": "missing"})["data"][
                "state"
            ]
            == "absent_at_snapshot"
        )
        conn.execute("DELETE FROM receipts WHERE request_id LIKE 'retention:%'")
        conn.commit()
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute("mutation_receipt_status", {**query, "request_id": "missing"})


def test_candidate_lineage_does_not_read_payload_columns(opened):
    from test_memory_candidates import accept_args, propose

    with opened() as (sdk, conn):
        query, receipt = seed(sdk)
        backend = sdk._service.backend
        cid = propose(backend)["data"]["candidate_id"]
        accepted = backend.execute("candidate_accept", accept_args(cid))
        sdk.execute(
            "forget",
            {
                "record_id": accepted["data"]["record"]["record_id"],
                "expected_revision": 1,
                "request_id": "candidate-forget",
            },
        )
        propose(backend, key="pending", source_digest="d" * 64)
        reads = []

        def authorizer(action, table, column, database, trigger):
            if action == sqlite3.SQLITE_READ:
                reads.append((table, column))
                if column in {
                    "content",
                    "topic",
                    "quote",
                    "source",
                    "session_ref",
                    "source_digest",
                }:
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorizer)
        try:
            assert sdk.execute("mutation_receipt_status", query)["data"]["receipt"] == receipt
        finally:
            conn.set_authorizer(None)
        assert not any(table == "memory_candidates" for table, column in reads)
