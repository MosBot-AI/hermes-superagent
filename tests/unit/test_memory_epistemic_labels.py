"""Explicit classifications are unverified data, never model-supplied authority."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_epistemic_label_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from personal_agent.memory_tool_contract import normalize_memory_tool_request


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    backend = create_backend()
    backend.open(connection, namespace_id="labels", session_ref="synthetic")
    yield backend, connection
    backend.close()
    connection.close()


def typed(backend, rid):
    return backend.execute("get", {"record_id": rid, "record_format": "epistemic_v1"})


def test_label_cas_reset_legacy_shape_and_terminal_replay(store):
    backend, _ = store
    request = {"request_id": "create", "content": "alpha", "assertion_kind": "claim"}
    receipt = backend.execute("remember", request)
    rid = receipt["data"]["record_id"]
    record = typed(backend, rid)
    assert record["assertion_kind"] == "claim"
    assert record["record_format"] == "epistemic_v1"
    assert backend.execute("get", {"record_id": rid}) == {
        k: v for k, v in record.items() if k not in {"assertion_kind", "record_format"}
    }
    with pytest.raises(MemoryError, match="idempotency_conflict"):
        backend.execute("remember", {**request, "assertion_kind": "inference"})
    backend.execute(
        "correct",
        {
            "record_id": rid,
            "expected_revision": 1,
            "request_id": "label",
            "assertion_kind": "inference",
        },
    )
    assert typed(backend, rid)["assertion_kind"] == "inference"
    backend.execute(
        "correct",
        {"record_id": rid, "expected_revision": 2, "request_id": "topic", "topic": "new topic"},
    )
    assert typed(backend, rid)["assertion_kind"] == "inference"
    backend.execute(
        "correct",
        {"record_id": rid, "expected_revision": 3, "request_id": "content", "content": "beta"},
    )
    assert typed(backend, rid)["assertion_kind"] == "unspecified"
    backend.execute("forget", {"record_id": rid, "expected_revision": 4, "request_id": "forget"})
    assert typed(backend, rid)["assertion_kind"] is None
    assert backend.execute("remember", request)["replayed"]
    assert typed(backend, rid)["status"] == "forgotten"


def test_model_refused_before_internal_receipt_replay(store):
    backend, connection = store
    request = {"request_id": "create", "content": "alpha", "topic": "", "assertion_kind": "claim"}
    backend.execute("remember", request)
    backend._source_kind = "activated_session_model"
    with pytest.raises(MemoryError, match="assertion_scope_required"):
        backend._mutate(connection, "remember", request, datetime.now())
    with pytest.raises(MemoryError, match="assertion_scope_required"):
        backend.execute("remember", request)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("assertion_kind", "claim", "assertion_scope_required"),
        ("record_format", "epistemic_v1", "invalid_request"),
    ],
)
def test_model_fields_refused_before_dispatch(field, value, code):
    with pytest.raises(MemoryError, match=code):
        normalize_memory_tool_request("personal_memory_read", {"action": "list", field: value})


def test_current_schema_reopens_and_typed_recall_counts_budget(store):
    backend, connection = store
    backend.execute(
        "remember", {"request_id": "create", "content": "alpha", "assertion_kind": "claim"}
    )
    backend.close()
    backend.open(connection, namespace_id="labels", session_ref="reopened")
    result = backend.execute("recall", {"queries": ["alpha"], "record_format": "epistemic_v1"})
    assert result["schema_version"] == "personal.memory.epistemic_recall.v1"
    assert result["items"][0]["assertion_kind"] == "claim"
    assert result["items_json_chars"] <= result["max_chars"]


def test_sdk_labels_conformance(tmp_path):
    @contextmanager
    def factory():
        connection = sqlite3.connect(tmp_path / "label-conformance.db", isolation_level=None)
        backend = create_backend()
        backend.open(connection, namespace_id="labels", session_ref="synthetic")
        sdk = LocalMemorySDK(
            backend, LocalBinding("labels", "synthetic", "explicit_local_operator")
        )
        try:
            yield sdk
        finally:
            sdk.close()
            connection.close()

    assert len(run_epistemic_label_conformance(factory, isolated_synthetic=True).passed) == 3


def test_sdk_validates_typed_recall_and_admits_legacy_adapter(store, monkeypatch):
    backend, _ = store
    binding = LocalBinding("labels", "synthetic", "explicit_local_operator")
    sdk = LocalMemorySDK(backend, binding)
    saved = sdk.execute(
        "remember", {"request_id": "create", "content": "alpha", "assertion_kind": "claim"}
    )
    key = {"record_id": saved["data"]["record_id"]}
    query = {"queries": ["alpha"], "record_format": "epistemic_v1"}
    assert sdk.execute("recall", query)["data"]["items"][0]["assertion_kind"] == "claim"
    execute = backend.execute

    def malformed(operation, payload):
        result = execute(operation, payload)
        if operation == "recall":
            result["items"][0]["assertion_kind"] = "verified"
        return result

    with monkeypatch.context() as scope:
        scope.setattr(backend, "execute", malformed)
        with pytest.raises(MemoryError, match="invalid_result"):
            sdk.execute("recall", query)
    description = backend.describe()
    description["capabilities"].remove("epistemic_labels")
    monkeypatch.setattr(backend, "describe", lambda: description)
    legacy = LocalMemorySDK(backend, binding)
    assert "assertion_kind" not in legacy.execute("get", key)["data"]
    with pytest.raises(MemoryError, match="capability_unavailable"):
        legacy.execute("get", {**key, "record_format": "epistemic_v1"})


def test_v13_reader_projects_unspecified_without_migrating_and_retry_stays_exact(tmp_path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    backend.open(connection, namespace_id="labels", session_ref="old")
    request = {"request_id": "old", "content": "migration control"}
    receipt = backend.execute("remember", request)
    rid = receipt["data"]["record_id"]
    backend.close()
    connection.execute("ALTER TABLE records DROP COLUMN assertion_kind")
    connection.execute("PRAGMA user_version=13")
    connection.close()
    before = path.read_bytes()

    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    backend.open_readonly(connection, namespace_id="labels", session_ref="new")
    assert typed(backend, rid)["assertion_kind"] == "unspecified"
    backend.close()
    connection.close()
    assert path.read_bytes() == before

    connection = sqlite3.connect(path, isolation_level=None)
    connection.set_authorizer(
        lambda action, table, column, *_: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_UPDATE and (table, column) == ("records", "assertion_kind")
            else sqlite3.SQLITE_OK
        )
    )
    with pytest.raises(MemoryError, match="storage_error"):
        backend.open(connection, namespace_id="labels", session_ref="new")
    connection.set_authorizer(None)
    assert not connection.in_transaction
    assert connection.execute("PRAGMA user_version").fetchone() == (13,)
    assert path.read_bytes() == before
    backend.open(connection, namespace_id="labels", session_ref="new")
    assert connection.execute("PRAGMA user_version").fetchone() == (14,)
    assert backend.execute("remember", request) == {**receipt, "replayed": True}
    assert typed(backend, rid)["assertion_kind"] == "unspecified"
    backend.close()
    connection.close()
