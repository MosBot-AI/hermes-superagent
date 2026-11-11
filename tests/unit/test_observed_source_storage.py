"""Observed provenance never manufactures native receipts or rewrites legacy identity."""

import sqlite3
from copy import deepcopy

import pytest

from personal_agent.memory_backend import MemoryError
from personal_agent.memory_mutation_status import normalized_request_digest
from personal_agent.memory_sdk import LocalMemorySDK, source_request_identity
from personal_agent.retained_sources import SCHEMA_V12, validate
from tests.unit.test_retained_source_recovery import (
    counts,
    cursor,
    opened,
    request,
    status,
)
from tests.unit.test_retained_source_sdk import Wrapper


def observed(payload=None):
    payload = deepcopy(payload or request())
    source = payload["source"]
    source["kind"] = "observed_native_snapshot"
    source["observation_id"] = source.pop("receipt_id")
    return payload


def downgrade(conn):
    conn.execute("ALTER TABLE retained_source_decisions RENAME TO new_decisions")
    conn.execute(SCHEMA_V12["retained_source_decisions"])
    conn.execute(
        "INSERT INTO retained_source_decisions SELECT request_id,consumer_id,source_sequence,"
        "request_digest,source_identity,source_fingerprint,source_role,source_receipt,"
        "state,record_id,receipt,suppressed FROM new_decisions"
    )
    conn.execute("DROP TABLE new_decisions")
    conn.execute("PRAGMA user_version=12")


@pytest.mark.parametrize("terminal", ["pending", "accepted", "discarded"])
def test_schema12_migration_preserves_exact_legacy_digest_and_replay(tmp_path, terminal):
    path, payload = tmp_path / "legacy.db", request()
    original_digest = normalized_request_digest("retained_source_import", payload)
    assert source_request_identity(payload)["expected_digest"] == original_digest
    assert validate("source_stage", payload) == payload
    with opened(path) as (sdk, _, conn):
        decision = sdk.execute("source_stage", payload)["data"]
        if terminal != "pending":
            operation = "source_accept" if terminal == "accepted" else "source_discard"
            argument = payload if terminal == "accepted" else source_request_identity(payload)
            decision = sdk.execute(operation, argument)["data"]
        before = conn.execute(
            "SELECT request_digest,source_receipt,receipt FROM retained_source_decisions"
        ).fetchall()
        downgrade(conn)
        dump = list(conn.iterdump())
    # Read-only callers cannot silently migrate even an otherwise valid legacy database.
    with pytest.raises(MemoryError, match="readonly_schema_unavailable"):
        with opened(path, readonly=True):
            pytest.fail("legacy store admitted by current-schema reader")
    with sqlite3.connect(path) as conn:
        assert list(conn.iterdump()) == dump
        assert conn.execute("PRAGMA user_version").fetchone() == (12,)
    with opened(path) as (sdk, _, conn):
        assert conn.execute("PRAGMA user_version").fetchone() == (13,)
        assert (
            conn.execute(
                "SELECT request_digest,source_receipt,receipt FROM retained_source_decisions"
            ).fetchall()
            == before
        )
        assert conn.execute(
            "SELECT source_kind,source_observation FROM retained_source_decisions"
        ).fetchone() == ("retained_native_snapshot", None)
        assert status(sdk, payload)["decision"] == decision
        assert sdk.execute("source_stage", payload) == {"data": decision, "replayed": True}
        if terminal != "pending":
            assert sdk.execute(operation, argument)["data"] == decision
        changed = observed(payload)
        with pytest.raises(MemoryError, match="idempotency_conflict"):
            sdk.execute("source_stage", changed)


def test_schema12_migration_failure_rolls_back_every_byte_of_evidence(tmp_path):
    path = tmp_path / "rollback.db"
    with opened(path) as (sdk, _, conn):
        sdk.execute("source_stage", request())
        downgrade(conn)
        before = list(conn.iterdump())

    class Failure(sqlite3.Connection):
        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if sql == "PRAGMA user_version=13":
                raise sqlite3.OperationalError("synthetic migration failure")
            return result

    with pytest.raises(MemoryError):
        with opened(path, factory=Failure):
            pytest.fail("migration unexpectedly committed")
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone() == (12,)
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize("terminal", ["source_accept", "source_discard"])
def test_observed_restart_pending_terminal_replay_and_metadata_only_reads(tmp_path, terminal):
    path, payload = tmp_path / "observed.db", observed()
    with opened(path) as (sdk, _, conn):
        decision = sdk.execute("source_stage", payload)["data"]
        assert decision["source"] == payload["source"]
        assert conn.execute(
            "SELECT source_receipt,source_observation FROM retained_source_decisions"
        ).fetchone() == (None, payload["source"]["observation_id"])
        assert counts(conn) == (0, 0, 0, 1)
    with opened(path) as (sdk, _, _):
        assert cursor(sdk)["pending"] == decision
        with pytest.raises(MemoryError, match="source_pending"):
            sdk.execute("source_stage", request("next"))
        argument = payload if terminal == "source_accept" else source_request_identity(payload)
        resolved = sdk.execute(terminal, argument)["data"]
        assert sdk.execute(terminal, argument)["replayed"]
        assert sdk.execute("source_stage", payload)["data"] == resolved
    with opened(path, readonly=True) as (sdk, _, conn):
        statements = []
        conn.set_trace_callback(statements.append)
        assert status(sdk, payload)["decision"] == resolved
        assert cursor(sdk)["through_sequence"] == 1
        assert conn.total_changes == 0
        assert not any(
            any(name in sql.lower() for name in ("content", "topic", "session_ref"))
            for sql in statements
            if sql.startswith("SELECT")
        )


@pytest.mark.parametrize("mutation", ["correct", "forget", "source_discard"])
@pytest.mark.parametrize("observed_first", [True, False])
def test_cross_provenance_suppression_blocks_pending_and_fresh_sources(
    tmp_path, mutation, observed_first
):
    path = tmp_path / "suppress.db"
    first, second = request(), request("other", consumer="other")
    if observed_first:
        first = observed(first)
    else:
        second = observed(second)
    with opened(path) as (sdk, _, _):
        sdk.execute("source_stage", first)
        sdk.execute("source_stage", second)
        if mutation == "source_discard":
            sdk.execute(mutation, source_request_identity(first))
        else:
            receipt = sdk.execute("source_accept", first)["data"]["record"]
            sdk.execute(
                mutation,
                {
                    "request_id": mutation,
                    "record_id": receipt["record_id"],
                    "expected_revision": 1,
                    **({"content": "Corrected"} if mutation == "correct" else {}),
                },
            )
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_accept", second)
        fresh = deepcopy(second)
        fresh.update(request_id="fresh", consumer_id="fresh")
        fresh["source"]["identity"] = "f" * 64
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_stage", fresh)
        assert status(sdk, second)["suppressed"]
        assert cursor(sdk, "other")["through_sequence"] == 0
        sdk.execute("source_discard", source_request_identity(second))
        assert cursor(sdk, "other")["through_sequence"] == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"receipt_id": "c" * 64},
        {"observation_id": None},
        {"observation_id": "z" * 64},
        {"kind": "retained_native_snapshot"},
        {"kind": None},
        {"role": "system"},
        {"observation_id": "a" * 100000},
        {"extra": "private"},
    ],
)
def test_malformed_observed_requests_rejected_before_dispatch(tmp_path, patch):
    with opened(tmp_path / "request.db") as (sdk, backend, _):
        wrapper = Wrapper(backend)
        checked = LocalMemorySDK(wrapper, sdk.binding)
        payload = observed()
        payload["source"].update(patch)
        with pytest.raises(MemoryError, match="invalid_request"):
            checked.execute("source_stage", payload)
        assert wrapper.calls == []


@pytest.mark.parametrize(
    "sql",
    [
        "source_receipt='" + "a" * 64 + "'",
        "source_observation=NULL",
        "source_observation=printf('%0100000d',1)",
        "source_kind='retained_native_snapshot'",
        "source_kind='unknown'",
    ],
)
@pytest.mark.parametrize("operation", ["source_status", "source_cursor"])
def test_corrupt_mixed_observed_fields_fail_closed(tmp_path, sql, operation):
    payload = observed()
    with opened(tmp_path / "corrupt.db") as (sdk, _, conn):
        sdk.execute("source_stage", payload)
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE retained_source_decisions SET " + sql)
        before = list(conn.iterdump())
        argument = (
            source_request_identity(payload)
            if operation == "source_status"
            else {"consumer_id": "importer"}
        )
        with pytest.raises(MemoryError, match="backend_failure"):
            sdk.execute(operation, argument)
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize(
    "patch",
    [
        {"receipt_id": "a" * 64},
        {"kind": "retained_native_snapshot"},
        {"observation_id": "c" * 64},
        {"observation_id": None},
    ],
)
def test_hostile_observed_result_does_not_fake_a_receipt(tmp_path, patch):
    with opened(tmp_path / "result.db") as (sdk, backend, _):

        def transform(result):
            result["data"]["source"].update(patch)
            return result

        checked = LocalMemorySDK(Wrapper(backend, transform=transform), sdk.binding)
        with pytest.raises(MemoryError, match="outcome_unknown"):
            checked.execute("source_stage", observed())


@pytest.mark.parametrize("provenance", ["legacy", "observed"])
def test_identity_is_shared_across_routes_but_attempt_ids_bind_request_digest(tmp_path, provenance):
    payload = request() if provenance == "legacy" else observed()
    with opened(tmp_path / "identity.db") as (sdk, _, _):
        sdk.execute("source_stage", payload)
        sdk.execute("source_accept", payload)
        same_identity = observed(request("different", consumer="other"))
        same_identity["source"]["identity"] = payload["source"]["identity"]
        with pytest.raises(MemoryError, match="source_identity_conflict"):
            sdk.execute("source_stage", same_identity)
        changed_attempt = deepcopy(payload)
        key = "receipt_id" if provenance == "legacy" else "observation_id"
        changed_attempt["source"][key] = "c" * 64
        with pytest.raises(MemoryError, match="idempotency_conflict"):
            sdk.execute("source_accept", changed_attempt)


def test_legacy_provenance_rejects_hidden_observation_column(tmp_path):
    with opened(tmp_path / "mixed.db") as (sdk, _, conn):
        sdk.execute("source_stage", request())
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE retained_source_decisions SET source_observation=?", ("a" * 64,))
        with pytest.raises(MemoryError, match="backend_failure"):
            cursor(sdk)


def test_legacy_input_cannot_inject_a_default_kind_or_observation():
    for patch in ({"kind": "retained_native_snapshot"}, {"observation_id": "c" * 64}):
        payload = request()
        payload["source"].update(patch)
        with pytest.raises(MemoryError, match="invalid_request"):
            source_request_identity(payload)
