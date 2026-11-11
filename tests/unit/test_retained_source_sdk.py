"""Retained snapshot SDK admission and hostile-result tests on synthetic stores."""

import hashlib
import sqlite3
from contextlib import contextmanager
from copy import deepcopy

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_retained_source_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, source_request_identity


@pytest.fixture
def factory(tmp_path):
    @contextmanager
    def opened():
        conn = sqlite3.connect(tmp_path / "synthetic.sqlite")
        backend = create_backend()
        backend.open(conn, namespace_id="synthetic", session_ref="synthetic-session")
        sdk = LocalMemorySDK(backend, LocalBinding("synthetic", "synthetic-session"))
        try:
            yield sdk
        finally:
            sdk.close()
            conn.close()

    return opened


def request():
    return {
        "request_id": "synthetic-source",
        "consumer_id": "synthetic-reader",
        "expected_sequence": 0,
        "content": "Synthetic 中文 snapshot",
        "expires_at": None,
        "retention": "independent_snapshot",
        "source": {
            "identity": "a" * 64,
            "fingerprint": hashlib.sha256("Synthetic 中文 snapshot".encode()).hexdigest(),
            "role": "user",
            "receipt_id": "b" * 64,
        },
    }


class Wrapper:
    def __init__(self, backend, *, omit=None, error=None, transform=None, before=False):
        self.backend = backend
        self.omit = omit
        self.error = error
        self.transform = transform
        self.before = before
        self.calls = []

    def describe(self):
        result = deepcopy(self.backend.describe())
        if self.omit:
            result["capabilities"] = [cap for cap in result["capabilities"] if cap != self.omit]
        return result

    def execute(self, operation, payload):
        if operation == "export":
            return self.backend.execute(operation, payload)
        self.calls.append(operation)
        if self.error and self.before:
            raise self.error
        result = self.backend.execute(operation, payload)
        if self.error:
            raise self.error
        return self.transform(result) if self.transform else result

    def close(self):
        pass


def test_identity_normalizes_topic_and_does_not_mutate():
    payload = request()
    original = deepcopy(payload)
    identity = source_request_identity(payload)
    assert payload == original
    assert set(identity) == {"request_id", "expected_digest"}
    assert identity == source_request_identity({**payload, "topic": ""})
    assert identity != source_request_identity({**payload, "consumer_id": "another"})


def test_optional_conformance_and_guards(factory):
    with pytest.raises(MemoryError, match="synthetic_store_required"):
        run_retained_source_conformance(factory)
    assert len(run_retained_source_conformance(factory, isolated_synthetic=True).passed) == 8
    with pytest.raises(MemoryError, match="empty_store_required"):
        run_retained_source_conformance(factory, isolated_synthetic=True)


@pytest.mark.parametrize(
    "operation",
    ["source_stage", "source_accept", "source_discard", "source_status", "source_cursor"],
)
def test_capability_required_before_dispatch(factory, operation):
    with factory() as sdk:
        backend = Wrapper(sdk._service.backend, omit="retained_source_acceptance")
        wrapped = LocalMemorySDK(backend, sdk.binding)
        payload = request()
        if operation in {"source_discard", "source_status"}:
            payload = source_request_identity(payload)
        elif operation == "source_cursor":
            payload = {"consumer_id": payload["consumer_id"]}
        with pytest.raises(MemoryError, match="capability_unavailable"):
            wrapped.execute(operation, payload)
        assert backend.calls == []
        assert sdk.execute("list", {})["data"]["items"] == []


@pytest.mark.parametrize("operation", ["source_stage", "source_accept", "source_discard"])
def test_model_cannot_write_sources(factory, operation):
    with factory() as sdk:
        backend = Wrapper(sdk._service.backend)
        wrapped = LocalMemorySDK(
            backend, LocalBinding("synthetic", "synthetic-session", "activated_session_model")
        )
        payload = source_request_identity(request()) if operation == "source_discard" else request()
        with pytest.raises(MemoryError, match="source_scope_required"):
            wrapped.execute(operation, payload)
        assert backend.calls == []


@pytest.mark.parametrize("operation", ["source_stage", "source_accept"])
@pytest.mark.parametrize("capability", ["durable_write", "cas", "idempotency", "record_expiry"])
def test_write_dependencies_required(factory, operation, capability):
    with factory() as sdk:
        backend = Wrapper(sdk._service.backend, omit=capability)
        wrapped = LocalMemorySDK(backend, sdk.binding)
        with pytest.raises(MemoryError, match="capability_unavailable"):
            wrapped.execute(operation, request())
        assert backend.calls == []


@pytest.mark.parametrize("operation", ["source_stage", "source_accept", "source_discard"])
@pytest.mark.parametrize("malformed", [False, True])
def test_committed_write_ack_loss_remains_unknown(factory, operation, malformed):
    with factory() as sdk:
        payload = request()
        if operation != "source_stage":
            sdk.execute("source_stage", payload)
        if operation == "source_discard":
            payload = source_request_identity(payload)
        backend = Wrapper(
            sdk._service.backend,
            error=None if malformed else RuntimeError("private backend text"),
            transform=(lambda result: {**result, "private": "extra"}) if malformed else None,
        )
        wrapped = LocalMemorySDK(backend, sdk.binding)
        with pytest.raises(MemoryError) as caught:
            wrapped.execute(operation, payload)
        assert caught.value.code == "outcome_unknown"
        assert "private" not in str(caught.value)
        assert backend.calls == [operation]
        status = sdk.execute("source_status", source_request_identity(request()))["data"]
        assert (
            status["decision"]["state"]
            == {
                "source_stage": "pending",
                "source_accept": "accepted",
                "source_discard": "discarded",
            }[operation]
        )


@pytest.mark.parametrize("operation", ["source_status", "source_cursor"])
@pytest.mark.parametrize("error", [RuntimeError("private"), MemoryError("source_pending")])
def test_reads_redact_backend_errors(factory, operation, error):
    with factory() as sdk:
        backend = Wrapper(sdk._service.backend, error=error, before=True)
        wrapped = LocalMemorySDK(backend, sdk.binding)
        payload = (
            source_request_identity(request())
            if operation == "source_status"
            else {"consumer_id": "synthetic"}
        )
        with pytest.raises(MemoryError, match="backend_failure"):
            wrapped.execute(operation, payload)
        assert backend.calls == [operation]


@pytest.mark.parametrize("operation", ["source_status", "source_cursor"])
def test_read_replay_flag_rejected(factory, operation):
    with factory() as sdk:
        backend = Wrapper(
            sdk._service.backend, transform=lambda result: {**result, "replayed": True}
        )
        wrapped = LocalMemorySDK(backend, sdk.binding)
        payload = (
            source_request_identity(request())
            if operation == "source_status"
            else {"consumer_id": "synthetic"}
        )
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute(operation, payload)


@pytest.mark.parametrize(
    "code",
    [
        "source_pending",
        "source_not_staged",
        "source_identity_conflict",
        "source_suppressed",
        "source_terminal",
        "source_cursor_conflict",
        "source_limit",
        "source_consumer_limit",
        "idempotency_conflict",
    ],
)
def test_known_write_rejections_preserved(factory, code):
    with factory() as sdk:
        backend = Wrapper(sdk._service.backend, error=MemoryError(code), before=True)
        wrapped = LocalMemorySDK(backend, sdk.binding)
        with pytest.raises(MemoryError) as caught:
            wrapped.execute("source_stage", request())
        assert caught.value.code == code
        assert backend.calls == ["source_stage"]


def test_invalid_source_request_never_dispatched(factory):
    with factory() as sdk:
        backend = Wrapper(sdk._service.backend)
        wrapped = LocalMemorySDK(backend, sdk.binding)
        payload = request()
        payload["source"]["fingerprint"] = "f" * 64
        with pytest.raises(MemoryError, match="invalid_request"):
            wrapped.execute("source_stage", payload)
        assert backend.calls == []


@pytest.mark.parametrize(
    "damage", ["extra", "sequence_bool", "source_role", "record", "request_id"]
)
def test_hostile_stage_decision_fails_closed(factory, damage):
    def transform(result):
        data = result["data"]
        if damage == "extra":
            data["content"] = "private injected text"
        elif damage == "sequence_bool":
            data["source_sequence"] = True
        elif damage == "source_role":
            data["source"]["role"] = "system"
        elif damage == "record":
            data["record"] = {}
        else:
            data["request_id"] = "another-request"
        return result

    with factory() as sdk:
        backend = Wrapper(sdk._service.backend, transform=transform)
        wrapped = LocalMemorySDK(backend, sdk.binding)
        with pytest.raises(MemoryError, match="outcome_unknown"):
            wrapped.execute("source_stage", request())
        assert backend.calls == ["source_stage"]


def test_request_snapshot_not_mutated_by_adapter(factory):
    class Mutator(Wrapper):
        def execute(self, operation, payload):
            result = super().execute(operation, payload)
            if operation == "source_stage":
                payload["source"]["identity"] = "f" * 64
                result["data"]["source"]["identity"] = "f" * 64
            return result

    with factory() as sdk:
        payload = request()
        original = deepcopy(payload)
        wrapped = LocalMemorySDK(Mutator(sdk._service.backend), sdk.binding)
        with pytest.raises(MemoryError, match="outcome_unknown"):
            wrapped.execute("source_stage", payload)
        assert payload == original


def test_readonly_source_metadata_has_no_payload(tmp_path):
    path = tmp_path / "synthetic-readonly.sqlite"
    conn = sqlite3.connect(path)
    backend = create_backend()
    backend.open(conn, namespace_id="synthetic", session_ref="private-session")
    sdk = LocalMemorySDK(backend, LocalBinding("synthetic", "private-session"))
    payload = {**request(), "topic": "private-topic"}
    identity = source_request_identity(payload)
    sdk.execute("source_stage", payload)
    accepted = sdk.execute("source_accept", payload)
    sdk.close()
    conn.close()

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    backend = create_backend()
    backend.open_readonly(conn, namespace_id="synthetic", session_ref="private-session")
    sdk = LocalMemorySDK(backend, LocalBinding("synthetic", "private-session"))
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        import json

        status = sdk.execute("source_status", identity)["data"]
        cursor = sdk.execute("source_cursor", {"consumer_id": payload["consumer_id"]})["data"]
        assert status["decision"] == accepted["data"]
        assert cursor["through_sequence"] == 1
        assert conn.total_changes == 0
        encoded = json.dumps([status, cursor], ensure_ascii=False)
        for secret in (
            payload["content"],
            payload["topic"],
            "private-session",
            identity["expected_digest"],
        ):
            assert secret not in encoded
        reads = [sql.lower() for sql in statements if sql.lstrip().lower().startswith("select")]
        assert not any("content" in sql or "topic" in sql or "session_ref" in sql for sql in reads)
    finally:
        sdk.close()
        conn.close()


def test_terminal_identity_and_fingerprint_cannot_be_reimported(factory):
    with factory() as sdk:
        payload = request()
        sdk.execute("source_stage", payload)
        accepted = sdk.execute("source_accept", payload)["data"]
        duplicate = {**payload, "request_id": "fresh-key", "expected_sequence": 1}
        with pytest.raises(MemoryError, match="source_identity_conflict"):
            sdk.execute("source_stage", duplicate)
        sdk.execute(
            "forget",
            {
                "request_id": "forget-source",
                "record_id": accepted["record"]["record_id"],
                "expected_revision": 1,
            },
        )
        duplicate["source"] = {**payload["source"], "identity": "c" * 64}
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_stage", duplicate)
        assert (
            sdk.execute("source_cursor", {"consumer_id": payload["consumer_id"]})["data"][
                "through_sequence"
            ]
            == 1
        )
