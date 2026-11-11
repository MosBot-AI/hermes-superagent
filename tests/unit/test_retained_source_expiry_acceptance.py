"""Adversarial checks for deadline, history, write and suppression acceptance oracles."""

import json
import sqlite3
from contextlib import contextmanager
from copy import deepcopy

import pytest

from acceptance.memory import expiry, retained
from personal_agent import memory_expiry, retained_sources
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_edits import PrivateEdits
from personal_agent.memory_projection import PrivateProjection


def test_fixture_original_deadline_and_distinct_provenance():
    fixture = json.loads(expiry.FIXTURE.read_text())
    assert fixture["accepted_at"] < fixture["before"] < fixture["deadline"] < fixture["after"]
    legacy, observed = expiry.requests(fixture)
    assert legacy["expires_at"] == observed["expires_at"] == fixture["deadline"]
    assert "receipt_id" in legacy["source"] and "observation_id" not in legacy["source"]
    assert "observation_id" in observed["source"] and "receipt_id" not in observed["source"]


@pytest.fixture
def terminal(tmp_path, monkeypatch):
    fixture = json.loads(expiry.FIXTURE.read_text())
    home = tmp_path / "home"
    directory = retained._path(home).parent
    directory.mkdir(parents=True, mode=0o700)
    connection = sqlite3.connect(retained._path(home), isolation_level=None)
    backend = create_backend()
    backend.open(
        connection,
        namespace_id="test",
        session_ref="synthetic-expiry",
        edits=PrivateEdits(directory),
        projection=PrivateProjection(directory),
    )
    service = MemoryService(backend)
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: fixture["accepted_at"])
    sources = expiry.requests(fixture)
    receipts = []
    for request in sources:
        service.execute("source_stage", request)
        receipts.append(service.execute("source_accept", request)["data"])
    monkeypatch.setattr(memory_expiry, "utc_now", lambda: fixture["after"])
    preview = service.execute("expired_preview", {"before": fixture["deadline"]})["data"]
    cleanup = {
        "request_id": "cleanup",
        "before": preview["before"],
        "limit": preview["limit"],
        "expected_snapshot": preview["snapshot"],
    }
    receipt = service.execute("forget_expired", cleanup)["data"]
    guard = service.execute(
        "remember",
        {"request_id": "later", "content": "Later expired row", "expires_at": fixture["deadline"]},
    )["data"]["record_id"]

    @contextmanager
    def opened(_home, _clock, source_kind="explicit_local_operator"):
        previous = backend._source_kind
        backend._source_kind = source_kind
        try:
            yield service
        finally:
            backend._source_kind = previous

    monkeypatch.setattr(expiry, "opened", opened)
    yield home, (fixture["after"], sources, receipts, cleanup, receipt), service, connection, guard
    backend.close()
    connection.close()


def test_terminal_receipts_suppression_and_unconsumed_later_batch(terminal):
    home, args, service, _, guard = terminal
    expiry.verify_terminal(home, *args)
    assert service.execute("get", {"record_id": guard})["data"]["status"] == "active"


@pytest.mark.parametrize(
    "damage",
    [
        "DELETE FROM receipts",
        "UPDATE retained_source_decisions SET receipt='{}' WHERE request_id='legacy'",
        "UPDATE retained_source_decisions SET source_sequence=2 WHERE request_id='observed'",
        "UPDATE retained_source_decisions SET suppressed=0",
        "UPDATE records SET revision=revision+1 WHERE status='active'",
        "DELETE FROM memory_fts",
    ],
)
def test_state_oracle_rejects_writes_receipt_cursor_or_suppression_damage(terminal, damage):
    home, _, _, connection, _ = terminal
    before = expiry.evidence(home)
    connection.execute(damage)
    with pytest.raises(AssertionError, match="logical state/receipts/cursors changed"):
        expiry.unchanged(home, before)


def test_terminal_probe_rejects_cross_route_suppression_bypass(terminal, monkeypatch):
    home, args, _, _, _ = terminal
    monkeypatch.setattr(retained_sources, "_check_suppression", lambda *_: None)
    with pytest.raises(AssertionError, match="unsafe operation succeeded"):
        expiry.verify_terminal(home, *args)


def test_terminal_probe_rejects_history_current_conflation(terminal, monkeypatch):
    home, args, service, _, _ = terminal
    execute = service.execute

    def conflated(operation, payload):
        result = execute(operation, payload)
        if operation == "source_status":
            result = deepcopy(result)
            result["data"]["decision"]["record"].update(revision=2, status="forgotten")
        return result

    monkeypatch.setattr(service, "execute", conflated)
    with pytest.raises(AssertionError, match="historical source receipt changed"):
        expiry.verify_terminal(home, *args)


def test_terminal_probe_rejects_retry_consuming_next_batch(terminal, monkeypatch):
    home, args, service, _, guard = terminal
    execute = service.execute

    def broadened(operation, payload):
        result = execute(operation, payload)
        if operation == "forget_expired":
            execute(
                "forget",
                {
                    "record_id": guard,
                    "expected_revision": 1,
                    "request_id": "unsafe-retry-side-effect",
                },
            )
        return result

    monkeypatch.setattr(service, "execute", broadened)
    with pytest.raises(AssertionError, match="logical state/receipts/cursors changed"):
        expiry.verify_terminal(home, *args)


def test_deadline_oracle_rejects_equality_recall():
    # Reuse the independently defined full-envelope counterexample, not production formatting.
    from test_longitudinal_memory_acceptance import sample

    record, context = sample()
    record["expires_at"] = "2030-01-01T00:00:00Z"
    record["expired"] = True
    context["memory"]["items"] = [dict(record)]
    context["memory"]["items_json_chars"] = len(
        json.dumps([record], ensure_ascii=True, sort_keys=True)
    )
    result = {
        "records": {record["record_id"]: record},
        "rows": [
            {
                "retrieved": ["expired"],
                "context": context,
            }
        ],
    }
    with pytest.raises(AssertionError, match="expired recall"):
        expiry.verify_sample(
            result,
            result["records"],
            record["expires_at"],
            {"expired": record["record_id"]},
            ["expired"],
        )


def test_refusal_probe_rejects_silent_success():
    class Broken:
        def execute(self, *_):
            return {"data": {}}

    with pytest.raises(AssertionError, match="unsafe operation succeeded"):
        expiry.refuse(Broken(), "forget_expired", {}, "retention_snapshot_conflict")


def test_refusal_probe_rejects_wrong_failure():
    class Broken:
        def execute(self, *_):
            raise MemoryError("storage_error")

    with pytest.raises(AssertionError, match="expected retention_snapshot_conflict"):
        expiry.refuse(Broken(), "forget_expired", {}, "retention_snapshot_conflict")


@pytest.mark.parametrize("field,value", [("status", "forgotten"), ("revision", 2)])
def test_initial_historical_receipt_cannot_define_its_own_oracle(terminal, field, value):
    _, args, _, _, _ = terminal
    request, receipt = args[1][0], deepcopy(args[2][0])
    receipt["record"][field] = value
    with pytest.raises(AssertionError, match="original receipt is not historical"):
        expiry.check_receipt(request, receipt)


@pytest.mark.parametrize("field", ["kind", "identity", "fingerprint", "role", "receipt_id"])
def test_initial_provenance_cannot_define_its_own_oracle(terminal, field):
    _, args, _, _, _ = terminal
    request, receipt = args[1][0], deepcopy(args[2][0])
    receipt["source"][field] = "wrong"
    with pytest.raises(AssertionError, match="original receipt provenance mismatch"):
        expiry.check_receipt(request, receipt)


@pytest.mark.parametrize(
    "field,value",
    [("content", "truncated"), ("expired", False), ("revision", 9), ("source", "other")],
)
def test_preview_rejects_partial_or_corrupted_review(field, value):
    record = {
        "record_id": "one",
        "content": "Complete source content",
        "expired": True,
        "revision": 1,
        "source": "explicit_local_operator",
    }
    preview = {
        "items": [dict(record)],
        "selected_count": 1,
        "eligible_count": 1,
        "remaining_count": 0,
    }
    expiry.check_preview(preview, {"one": record}, ["one"])
    preview["items"][0][field] = value
    with pytest.raises(AssertionError, match="complete canonical SQL oracle"):
        expiry.check_preview(preview, {"one": record}, ["one"])


def test_fts_oracle_rejects_forgotten_payload_left_in_index(terminal):
    home, _, _, connection, _ = terminal
    sequence = connection.execute(
        "SELECT sequence FROM records WHERE status='forgotten' LIMIT 1"
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO memory_fts(rowid,content,topic) VALUES (?,?,?)",
        (sequence, "Forgotten retained payload", "synthetic"),
    )
    with pytest.raises(AssertionError, match="forgotten payload remains in FTS"):
        expiry.check_forgotten_fts(home)
