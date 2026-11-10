"""Real SQLite SDK execution and hostile-result boundary tests."""

import sqlite3
from contextlib import contextmanager
from dataclasses import FrozenInstanceError

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK


@pytest.fixture
def factory(tmp_path):
    @contextmanager
    def opened():
        connection = sqlite3.connect(tmp_path / "isolated.sqlite")
        backend = create_backend()
        backend.open(connection, namespace_id="synthetic-sdk", session_ref="synthetic-session")
        sdk = LocalMemorySDK(backend, LocalBinding("synthetic-sdk", "synthetic-session"))
        try:
            yield sdk
        finally:
            sdk.close()
            connection.close()

    return opened


def test_real_sqlite_conformance(factory):
    assert len(run_conformance(factory, isolated_synthetic=True).passed) == 7


def test_conformance_requires_explicit_empty_store(factory):
    with pytest.raises(MemoryError, match="synthetic_store_required"):
        run_conformance(factory)
    with factory() as sdk:
        sdk.execute("remember", {"content": "existing", "request_id": "r"})
    with pytest.raises(MemoryError, match="empty_store_required"):
        run_conformance(factory, isolated_synthetic=True)
    with factory() as sdk:
        assert len(sdk.execute("list", {})["data"]["items"]) == 1


def test_binding_and_lifecycle(factory):
    with factory() as sdk:
        with pytest.raises(FrozenInstanceError):
            sdk.binding.namespace_id = "other"
        with pytest.raises(MemoryError, match="unsupported_operation"):
            sdk.execute("import_snapshot", {})
        for key in ("namespace_id", "url", "path", "sql", "source", "session_ref"):
            with pytest.raises(MemoryError, match="invalid_request"):
                sdk.execute("remember", {"content": "test", "request_id": "r", key: "forged"})
        sdk.close()
        sdk.close()
        with pytest.raises(MemoryError, match="closed"):
            sdk.execute("list", {})


class CorruptBackend:
    def __init__(self, backend, transform=None, error=None):
        self.backend, self.transform, self.error = backend, transform, error

    def describe(self):
        return self.backend.describe()

    def execute(self, operation, payload):
        result = self.backend.execute(operation, payload)
        if operation == "export":
            return result
        if self.error:
            raise self.error
        return self.transform(result)

    def close(self):
        pass


@pytest.mark.parametrize("error", [RuntimeError("private secret"), MemoryError("private secret")])
def test_unknown_mutation_outcome_never_retried(factory, error):
    with factory() as sdk:
        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, error=error), sdk.binding)
        with pytest.raises(MemoryError) as caught:
            wrapped.execute("remember", {"content": "written", "request_id": "r"})
        assert caught.value.code == "outcome_unknown" and not caught.value.retryable
        assert "private" not in str(caught.value)
        assert len(sdk.execute("list", {})["data"]["items"]) == 1
        assert sdk.execute("remember", {"content": "written", "request_id": "r"})["replayed"]


@pytest.mark.parametrize(
    "operation,payload", [("list", {}), ("remember", {"content": "x", "request_id": "r"})]
)
def test_invalid_result_redacted(factory, operation, payload):
    with factory() as sdk:
        wrapped = LocalMemorySDK(
            CorruptBackend(
                sdk._service.backend, transform=lambda result: {**result, "secret": "x"}
            ),
            sdk.binding,
        )
        with pytest.raises(MemoryError) as caught:
            wrapped.execute(operation, payload)
        assert caught.value.code == (
            "outcome_unknown" if operation == "remember" else "invalid_result"
        )


def test_wrong_export_binding_rejected(factory):
    with factory() as sdk:
        with pytest.raises(MemoryError, match="unsupported_backend"):
            LocalMemorySDK(sdk._service.backend, LocalBinding("wrong", "session"))


def test_request_snapshot_survives_backend_mutation(factory):
    with factory() as sdk:
        backend = sdk._service.backend

        class Mutator(CorruptBackend):
            def execute(self, operation, payload):
                result = self.backend.execute(operation, payload)
                if operation == "export":
                    return result
                payload["request_id"] = "forged"
                result["data"]["request_id"] = "forged"
                return result

        wrapped = LocalMemorySDK(Mutator(backend), sdk.binding)
        with pytest.raises(MemoryError, match="outcome_unknown"):
            wrapped.execute("remember", {"content": "x", "request_id": "r"})


@pytest.mark.parametrize("corruption", ["duplicate", "extra", "expired", "cursor", "over_limit"])
def test_page_result_semantics(factory, corruption):
    with factory() as sdk:
        sdk.execute("remember", {"content": "x", "request_id": "r"})

        def damage(result):
            if corruption == "duplicate":
                result["items"] *= 2
            elif corruption == "extra":
                result["items"][0]["secret"] = "bad"
            elif corruption == "expired":
                result["items"][0]["expired"] = True
            elif corruption == "cursor":
                result["next_cursor"] = result["items"][0]["record_id"]
            else:
                result["items"] *= 51
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, damage), sdk.binding)
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("list", {})


def test_wrong_record_receipt_and_no_secret_error(factory):
    with factory() as sdk:
        r = sdk.execute("remember", {"content": "x", "request_id": "r"})

        def damage(result):
            result["data"]["revision"] += 1
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, damage), sdk.binding)
        with pytest.raises(MemoryError, match="outcome_unknown"):
            wrapped.execute(
                "correct",
                {
                    "record_id": r["data"]["record_id"],
                    "expected_revision": 1,
                    "request_id": "c",
                    "content": "y",
                },
            )


def test_admission_checks_binding_before_other_reads_or_writes(factory):
    with factory() as sdk:
        calls = []

        class Observed(CorruptBackend):
            def execute(self, operation, payload):
                calls.append((operation, payload.copy()))
                return self.backend.execute(operation, payload)

        with pytest.raises(MemoryError, match="unsupported_backend"):
            LocalMemorySDK(Observed(sdk._service.backend), LocalBinding("wrong", "session"))
        assert calls == [("export", {"limit": 1, "after": None})]
        assert sdk.execute("list", {})["data"]["items"] == []


def test_known_rejection_is_trusted_no_commit_contract(factory):
    with factory() as sdk:
        receipt = sdk.execute("remember", {"content": "original", "request_id": "r"})
        with pytest.raises(MemoryError) as caught:
            sdk.execute("remember", {"content": "changed", "request_id": "r"})
        assert caught.value.code == "idempotency_conflict"
        assert (
            sdk.execute("get", {"record_id": receipt["data"]["record_id"]})["data"]["content"]
            == "original"
        )


def test_admission_requires_bounded_export_capability(factory):
    with factory() as sdk:
        calls = []

        class NoExport(CorruptBackend):
            def describe(self):
                descriptor = self.backend.describe()
                descriptor["capabilities"].remove("bounded_record_export")
                return descriptor

            def execute(self, operation, payload):
                calls.append(operation)
                return self.backend.execute(operation, payload)

        with pytest.raises(MemoryError, match="unsupported_backend"):
            LocalMemorySDK(NoExport(sdk._service.backend), sdk.binding)
        assert calls == []
