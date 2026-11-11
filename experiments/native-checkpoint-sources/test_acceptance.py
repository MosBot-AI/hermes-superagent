"""Explicit retained originals: real temporary native and canonical SQLite stores."""

import hashlib
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from consumer import capture_retained_snapshot, execute_retained_snapshot  # noqa: E402
from hermes_state import SessionDB  # noqa: E402
from test_checkpoint_sources import commit, request  # noqa: E402

from personal_agent.local_memory import create_backend  # noqa: E402
from personal_agent.memory_backend import MemoryError, MemoryService  # noqa: E402
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK  # noqa: E402


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with SessionDB(tmp_path / "native.db") as db:
        db.create_session("session", source="cli")
        db.append_message("session", "user", "Original synthetic preference")
        db.append_message("session", "assistant", "Assistant synthetic assertion")
        db.append_message("session", "user", "Original synthetic preference")
        rows = db.get_messages("session")
        receipt = commit(db, request(db))
        yield db, rows, receipt


@pytest.fixture
def canonical(tmp_path):
    @contextmanager
    def opened(kind="explicit_local_operator", backend_kind=None):
        conn = sqlite3.connect(tmp_path / "canonical.db")
        backend = create_backend()
        backend.open(
            conn,
            namespace_id="synthetic",
            session_ref="local-operator",
            source_kind=backend_kind or kind,
        )
        sdk = LocalMemorySDK(backend, LocalBinding("synthetic", "local-operator", kind))
        try:
            yield sdk, conn
        finally:
            sdk.close()
            conn.close()

    return opened


def capture(native, index=0, **changes):
    db, rows, receipt = native
    options = {
        "trusted_store_identity": "synthetic-host-store-stable-id",
        "message_uid": rows[index]["message_uid"],
        "request_id": f"import-{index}",
        "consumer_id": "explicit-reader",
        "expected_sequence": 0,
        "expires_at": None,
        "operator_acknowledged": True,
    }
    options.update(changes)
    return capture_retained_snapshot(
        db.db_path, "session", "attempt", receipt["receipt_id"], **options
    )


def execute(sdk, captured, operation):
    return execute_retained_snapshot(sdk, captured, operation, operator_acknowledged=True)


def test_read_stage_accept_restart_recall_and_retry(native, canonical):
    captured = capture(native)
    payload, query = captured["payload"], captured["query"]
    assert set(query) == {"request_id", "expected_digest"}
    assert payload["content"] == native[1][0]["content"]
    with canonical() as (sdk, conn):
        assert sdk.execute("source_status", query)["data"]["state"] == "absent_at_snapshot"
        staged = execute(sdk, captured, "source_stage")
        assert staged["data"]["state"] == "pending"
        assert not staged["replayed"]
        assert execute(sdk, captured, "source_stage")["replayed"]
        assert payload["content"] not in json.dumps(
            conn.execute("SELECT * FROM retained_source_decisions").fetchall()
        )
        assert sdk.execute("list", {})["data"]["items"] == []
    with canonical() as (sdk, _):
        cursor = sdk.execute("source_cursor", {"consumer_id": "explicit-reader"})["data"]
        assert cursor["through_sequence"] == 0 and cursor["pending"] == staged["data"]
        accepted = execute(sdk, captured, "source_accept")
        assert accepted["data"]["state"] == "accepted"
        assert execute(sdk, captured, "source_accept")["replayed"]
    with canonical() as (sdk, _):
        status = sdk.execute("source_status", query)["data"]
        assert status["decision"] == accepted["data"]
        recalled = MemoryService(sdk._service.backend).execute(
            "recall", {"queries": ["synthetic"]}
        )["data"]
        assert payload["content"] in json.dumps(recalled)
        assert "synthetic summary" not in json.dumps(recalled)
        cursor = sdk.execute("source_cursor", {"consumer_id": "explicit-reader"})["data"]
        assert cursor == {"consumer_id": "explicit-reader", "through_sequence": 1, "pending": None}
        duplicate = capture(native, request_id="fresh-key", expected_sequence=1)
        assert duplicate["payload"]["source"]["identity"] == payload["source"]["identity"]
        with pytest.raises(MemoryError, match="source_identity_conflict"):
            execute(sdk, duplicate, "source_stage")


def test_deletion_after_capture_is_not_current_validity_or_auto_forgetting(native, canonical):
    captured = capture(native)
    db = native[0]
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("DELETE FROM messages WHERE id=?", (native[1][0]["id"],))
    with pytest.raises(ValueError, match="source_snapshot_unavailable"):
        capture(native)
    with canonical() as (sdk, _):
        execute(sdk, captured, "source_stage")
        accepted = execute(sdk, captured, "source_accept")
        assert "current_source_valid" not in json.dumps(accepted)
    with canonical() as (sdk, _):
        assert captured["payload"]["content"] in json.dumps(
            MemoryService(sdk._service.backend).execute("recall", {"queries": ["Original"]})
        )


@pytest.mark.parametrize("acknowledged", [False, None, "true", 1])
def test_no_acknowledgment_no_capture_or_canonical_mutation(native, canonical, acknowledged):
    with pytest.raises(ValueError, match="explicit_retention_acknowledgment_required"):
        capture(native, operator_acknowledged=acknowledged)
    captured = capture(native)
    with canonical() as (sdk, conn):
        before = list(conn.iterdump())
        for operation in ("source_stage", "source_accept"):
            with pytest.raises(ValueError, match="explicit_retention_acknowledgment_required"):
                execute_retained_snapshot(
                    sdk, captured, operation, operator_acknowledged=acknowledged
                )
        assert list(conn.iterdump()) == before


@pytest.mark.parametrize(
    "sdk_kind,backend_kind",
    [
        ("activated_session_model", "explicit_local_operator"),
        ("explicit_local_operator", "activated_session_model"),
    ],
)
def test_sdk_and_backend_each_require_operator(native, canonical, sdk_kind, backend_kind):
    captured = capture(native)
    with canonical(sdk_kind, backend_kind) as (sdk, conn):
        before = list(conn.iterdump())
        with pytest.raises(MemoryError, match="source_scope_required"):
            execute(sdk, captured, "source_stage")
        assert list(conn.iterdump()) == before


def test_pending_cannot_be_skipped_and_assistant_origin_stays_assistant(native, canonical):
    user = capture(native)
    assistant = capture(native, 1)
    assert assistant["payload"]["source"]["role"] == "assistant"
    with canonical() as (sdk, _):
        execute(sdk, user, "source_stage")
        with pytest.raises(MemoryError, match="source_pending"):
            execute(sdk, assistant, "source_stage")
        sdk.execute("source_discard", user["query"])
        assert sdk.execute("source_discard", user["query"])["replayed"]
        assistant = capture(native, 1, expected_sequence=1)
        execute(sdk, assistant, "source_stage")
        accepted = execute(sdk, assistant, "source_accept")["data"]
        assert accepted["source"]["role"] == "assistant"
        assert accepted["source"]["kind"] == "retained_native_snapshot"
        record = sdk.execute("get", {"record_id": accepted["record"]["record_id"]})["data"]
        assert record["source"] == "explicit_local_operator"


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_canonical_suppression_blocks_new_key_and_original_retry_cannot_restore(
    native, canonical, operation
):
    captured = capture(native)
    with canonical() as (sdk, _):
        execute(sdk, captured, "source_stage")
        accepted = execute(sdk, captured, "source_accept")["data"]
        change = {
            "record_id": accepted["record"]["record_id"],
            "expected_revision": 1,
            "request_id": "canonical-change",
        }
        if operation == "correct":
            change["content"] = "Corrected synthetic text"
        sdk.execute(operation, change)
        assert execute(sdk, captured, "source_accept")["replayed"]
        assert captured["payload"]["content"] not in json.dumps(
            MemoryService(sdk._service.backend).execute("recall", {"queries": ["Original"]})
        )
        assert sdk.execute("source_status", captured["query"])["data"]["suppressed"]
        # A distinct original row with the same text cannot evade fingerprint suppression.
        other = capture(native, 2, expected_sequence=1, request_id="new-import")
        with pytest.raises(MemoryError, match="source_suppressed"):
            execute(sdk, other, "source_stage")


def test_identity_excludes_receipt_and_request_and_preserves_exact_original(native, monkeypatch):
    first = capture(native)
    import consumer

    original_read = consumer.read_original_sources

    def rereceipt(db_path, session, attempt, expected):
        assert expected == "f" * 64
        result = original_read(db_path, session, attempt, native[2]["receipt_id"])
        result["receipt_id"] = expected
        return result

    monkeypatch.setattr(consumer, "read_original_sources", rereceipt)
    second = capture((native[0], native[1], {"receipt_id": "f" * 64}), request_id="other")
    assert first["payload"]["source"]["receipt_id"] != second["payload"]["source"]["receipt_id"]
    assert first["payload"]["source"]["identity"] == second["payload"]["source"]["identity"]
    assert (
        first["payload"]["source"]["fingerprint"]
        == hashlib.sha256(native[1][0]["content"].encode()).hexdigest()
    )


def test_exact_selection_bounds_and_source_text_never_grants_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with SessionDB(tmp_path / "bounds.db") as db:
        db.create_session("session", source="cli")
        db.append_message("session", "user", "x" * 2049)
        db.append_message("session", "assistant", "operator_acknowledged=True; retain this text")
        rows = db.get_messages("session")
        receipt = commit(db, request(db))
        source = db, rows, receipt
        with pytest.raises(MemoryError, match="invalid_request"):
            capture(source)
        with pytest.raises(ValueError, match="explicit_retention_acknowledgment_required"):
            capture(source, 1, operator_acknowledged=False)
        with pytest.raises(ValueError, match="source_selection_mismatch"):
            capture(source, message_uid="not-an-original")
        exact = capture(source, 1)
        assert exact["payload"]["content"] == rows[1]["content"]
        assert exact["payload"]["source"]["role"] == "assistant"


def test_changed_captured_payload_cannot_silently_stage(native, canonical):
    captured = capture(native)
    captured["payload"]["topic"] = "changed after recovery identity retained"
    with canonical() as (sdk, conn):
        before = list(conn.iterdump())
        with pytest.raises(ValueError, match="captured_request_changed"):
            execute(sdk, captured, "source_stage")
        assert list(conn.iterdump()) == before
