"""Optional SDK checkpoint conformance and hostile adapter boundaries."""

from uuid import uuid4

import pytest

from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_checkpoint_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from tests.unit import test_memory_sdk
from tests.unit.test_memory_sdk import CorruptBackend

factory = test_memory_sdk.factory
CREATE = {"expected_watermark": 0, "request_id": "checkpoint"}


def test_checkpoint_conformance(factory):
    assert len(run_checkpoint_conformance(factory, isolated_synthetic=True).passed) == 6


def test_requires_empty_isolated_store(factory):
    with pytest.raises(MemoryError, match="synthetic_store_required"):
        run_checkpoint_conformance(factory)
    with factory() as sdk:
        sdk.execute("remember", {"content": "existing", "request_id": "existing"})
    with pytest.raises(MemoryError, match="empty_store_required"):
        run_checkpoint_conformance(factory, isolated_synthetic=True)


@pytest.mark.parametrize(
    "capability", ["local_metadata_checkpoint", "durable_write", "cas", "idempotency"]
)
def test_capabilities_before_dispatch(factory, capability):
    with factory() as sdk:
        calls = []

        class Restricted(CorruptBackend):
            def describe(self):
                descriptor = self.backend.describe()
                descriptor["capabilities"].remove(capability)
                return descriptor

            def execute(self, operation, payload):
                calls.append(operation)
                return self.backend.execute(operation, payload)

        wrapped = LocalMemorySDK(Restricted(sdk._service.backend), sdk.binding)
        assert wrapped.execute("list", {})["data"]["items"] == []
        calls.clear()
        with pytest.raises(MemoryError, match="capability_unavailable"):
            wrapped.execute("checkpoint_create", CREATE)
        assert not calls
        if capability == "local_metadata_checkpoint":
            with pytest.raises(MemoryError, match="capability_unavailable"):
                wrapped.execute("checkpoint_status", {"checkpoint_id": str(uuid4())})
            assert not calls


def test_model_cannot_create_or_replay_but_can_inspect(factory):
    with factory() as sdk:
        receipt = sdk.execute("checkpoint_create", CREATE)["data"]
        calls = []

        class Observed(CorruptBackend):
            def execute(self, operation, payload):
                calls.append(operation)
                return self.backend.execute(operation, payload)

        wrapped = LocalMemorySDK(
            Observed(sdk._service.backend),
            LocalBinding(
                "synthetic-sdk",
                "synthetic-session",
                "activated_session_model",
            ),
        )
        calls.clear()
        for request in (CREATE, {**CREATE, "request_id": "new"}):
            with pytest.raises(MemoryError, match="checkpoint_scope_required"):
                wrapped.execute("checkpoint_create", request)
        assert not calls
        assert wrapped.execute("checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]})[
            "data"
        ]["is_current"]


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("checkpoint_create", {}),
        ("checkpoint_create", {**CREATE, "expected_watermark": True}),
        ("checkpoint_create", {**CREATE, "expected_watermark": -1}),
        ("checkpoint_create", {**CREATE, "expected_watermark": 2**63 - 1}),
        ("checkpoint_create", {**CREATE, "request_id": "x" * 129}),
        ("checkpoint_create", {**CREATE, "request_id": "../secret"}),
        ("checkpoint_create", {**CREATE, "namespace_id": "other"}),
        ("checkpoint_status", {"checkpoint_id": "bad"}),
        ("checkpoint_status", {"checkpoint_id": str(uuid4()), "extra": 1}),
    ],
)
def test_invalid_request_never_dispatches(factory, operation, payload):
    with factory() as sdk:

        class NoDispatch(CorruptBackend):
            def execute(self, operation, payload):
                assert operation == "export"
                return self.backend.execute(operation, payload)

        wrapped = LocalMemorySDK(NoDispatch(sdk._service.backend), sdk.binding)
        with pytest.raises(MemoryError, match="invalid_request"):
            wrapped.execute(operation, payload)


BAD_RECEIPT = [
    ("schema_version", "native.v2"),
    ("checkpoint_id", "invalid"),
    ("request_id", "../secret"),
    ("request_id", "x" * 129),
    ("metadata_sha256", "A" * 64),
    ("metadata_sha256", "a" * 63),
    ("metadata_sha256", 1),
    ("scope", "native"),
    ("restorable", 0),
    ("restorable", True),
    ("native_checkpoint", True),
    ("through_sequence", True),
    ("through_sequence", -1),
    ("through_sequence", 2**63),
    ("event_count", True),
    ("record_count", -1),
    ("active_count", True),
    ("forgotten_count", 1),
    ("event_count", 1),
    ("record_count", 1),
    ("content", "secret"),
    ("source", "secret"),
    ("session_ref", "secret"),
]


@pytest.mark.parametrize("operation", ["checkpoint_create", "checkpoint_status"])
@pytest.mark.parametrize("field,value", BAD_RECEIPT)
def test_hostile_receipt(factory, operation, field, value):
    with factory() as sdk:
        receipt = sdk.execute("checkpoint_create", CREATE)["data"]

        def transform(result):
            target = result["data"] if operation == "checkpoint_create" else result["checkpoint"]
            target[field] = value
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        with pytest.raises(
            MemoryError,
            match="outcome_unknown" if operation == "checkpoint_create" else "invalid_result",
        ):
            wrapped.execute(
                operation,
                CREATE
                if operation == "checkpoint_create"
                else {"checkpoint_id": receipt["checkpoint_id"]},
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("is_current", 1),
        ("current_watermark", True),
        ("current_watermark", -1),
        ("current_watermark", 2**63),
        ("scope", "restore"),
        ("payload", "secret"),
        ("current_watermark", 1),
    ],
)
def test_hostile_status(factory, field, value):
    with factory() as sdk:
        receipt = sdk.execute("checkpoint_create", CREATE)["data"]
        wrapped = LocalMemorySDK(
            CorruptBackend(sdk._service.backend, lambda r: {**r, field: value}), sdk.binding
        )
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]})


@pytest.mark.parametrize("operation", ["checkpoint_create", "checkpoint_status"])
@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "envelope",
        "id",
        "fence",
        "count",
        "record_limit",
        "event_limit",
        "nonterminal_limit",
        "minimum_events",
        "nonempty_zero",
    ],
)
def test_receipt_relations(factory, operation, damage):
    with factory() as sdk:
        record = sdk.execute("remember", {"content": "secret", "request_id": "r"})["data"]
        request = {**CREATE, "expected_watermark": record["event_sequence"]}
        receipt = sdk.execute("checkpoint_create", request)["data"]

        def transform(result):
            target = result["data"] if operation == "checkpoint_create" else result["checkpoint"]
            if damage == "missing":
                del target["metadata_sha256"]
            elif damage == "envelope":
                if operation == "checkpoint_create":
                    result["replayed"] = 1
                else:
                    return {"data": result, "replayed": True}
            elif damage == "id":
                target["request_id" if operation == "checkpoint_create" else "checkpoint_id"] = str(
                    uuid4()
                )
            elif damage == "fence":
                if operation == "checkpoint_create":
                    target["through_sequence"] = 2
                else:
                    result["current_watermark"] = 0
            elif damage == "count":
                target["active_count"] = 0
            elif damage == "record_limit":
                target.update(
                    record_count=1001, active_count=1001, event_count=1001, through_sequence=1001
                )
            elif damage == "event_limit":
                target.update(event_count=11001, through_sequence=11001)
            elif damage == "nonterminal_limit":
                target.update(event_count=10001, through_sequence=10001)
            elif damage == "minimum_events":
                target.update(active_count=0, forgotten_count=1)
            else:
                target.update(event_count=0, through_sequence=0)
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        with pytest.raises(
            MemoryError,
            match="outcome_unknown" if operation == "checkpoint_create" else "invalid_result",
        ):
            wrapped.execute(
                operation,
                request
                if operation == "checkpoint_create"
                else {"checkpoint_id": receipt["checkpoint_id"]},
            )


@pytest.mark.parametrize("error", [RuntimeError("private secret"), MemoryError("private secret")])
def test_lost_ack_reconciles_without_retry(factory, error):
    with factory() as sdk:
        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, error=error), sdk.binding)
        with pytest.raises(MemoryError, match="outcome_unknown") as caught:
            wrapped.execute("checkpoint_create", CREATE)
        assert not caught.value.retryable and "private" not in str(caught.value)
        replay = sdk.execute("checkpoint_create", CREATE)
        assert replay["replayed"]
        assert sdk.execute("checkpoint_status", {"checkpoint_id": replay["data"]["checkpoint_id"]})[
            "data"
        ]["is_current"]


@pytest.mark.parametrize(
    "code",
    [
        "checkpoint_scope_required",
        "checkpoint_not_found",
        "watermark_conflict",
        "checkpoint_limit",
        "checkpoint_state_limit",
        "checkpoint_state_inconsistent",
        "idempotency_conflict",
    ],
)
def test_expected_rejections_redacted(factory, code):
    with factory() as sdk:

        class Reject(CorruptBackend):
            def execute(self, operation, payload):
                if operation == "export":
                    return self.backend.execute(operation, payload)
                error = MemoryError(code)
                error.args = ("private secret",)
                raise error

        wrapped = LocalMemorySDK(Reject(sdk._service.backend), sdk.binding)
        with pytest.raises(MemoryError) as caught:
            wrapped.execute("checkpoint_create", CREATE)
        assert caught.value.code == code and "private" not in str(caught.value)


def test_sparse_and_same_watermark_stale_are_valid(factory):
    with factory() as sdk:
        sdk.execute("remember", {"content": "secret", "request_id": "r"})
        receipt = sdk.execute("checkpoint_create", {**CREATE, "expected_watermark": 1})["data"]

        def transform(result):
            result["checkpoint"]["through_sequence"] = 9
            result.update(current_watermark=9, is_current=False)
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        data = wrapped.execute("checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]})[
            "data"
        ]
        assert not data["is_current"] and data["checkpoint"]["event_count"] == 1


def test_status_unknown_error_is_redacted_read_failure(factory):
    with factory() as sdk:
        receipt = sdk.execute("checkpoint_create", CREATE)["data"]
        wrapped = LocalMemorySDK(
            CorruptBackend(sdk._service.backend, error=RuntimeError("secret")), sdk.binding
        )
        with pytest.raises(MemoryError, match="backend_failure"):
            wrapped.execute("checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]})
        with pytest.raises(MemoryError, match="checkpoint_not_found"):
            sdk.execute("checkpoint_status", {"checkpoint_id": str(uuid4())})


@pytest.mark.parametrize(
    "limit,values",
    [
        ("max_total_records", {"record_count": 2, "active_count": 2, "event_count": 2}),
        ("max_total_mutations", {"event_count": 3, "active_count": 0, "forgotten_count": 1}),
        ("max_nonterminal_mutations", {"event_count": 2}),
    ],
)
def test_descriptor_limits_are_used(factory, limit, values):
    with factory() as sdk:
        sdk.execute("remember", {"content": "secret", "request_id": "r"})
        receipt = sdk.execute("checkpoint_create", {**CREATE, "expected_watermark": 1})["data"]

        class Narrow(CorruptBackend):
            def describe(self):
                descriptor = self.backend.describe()
                descriptor[limit] = 1
                if limit == "max_total_mutations":
                    descriptor[limit] = 2
                    descriptor["max_nonterminal_mutations"] = 2
                return descriptor

        def transform(result):
            result["checkpoint"].update(**values, through_sequence=3)
            result.update(current_watermark=3)
            return result

        wrapped = LocalMemorySDK(Narrow(sdk._service.backend, transform), sdk.binding)
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]})


def test_malformed_new_write_ack_is_unknown_and_replay_recovers(factory):
    with factory() as sdk:
        calls = []

        class Lost(CorruptBackend):
            def execute(self, operation, payload):
                calls.append(operation)
                result = self.backend.execute(operation, payload)
                return result if operation == "export" else {"data": result["data"], "replayed": 1}

        wrapped = LocalMemorySDK(Lost(sdk._service.backend), sdk.binding)
        calls.clear()
        with pytest.raises(MemoryError, match="outcome_unknown"):
            wrapped.execute("checkpoint_create", CREATE)
        assert calls == ["checkpoint_create"]
        replay = sdk.execute("checkpoint_create", CREATE)
        assert replay["replayed"]
        assert sdk.execute("export", {})["data"]["watermark"] == 0


def test_cursor_progress_does_not_stale_checkpoint(factory):
    with factory() as sdk:
        receipt = sdk.execute("checkpoint_create", CREATE)["data"]
        sdk.execute(
            "consumer_advance",
            {
                "consumer_id": "projection",
                "expected_revision": 0,
                "through_sequence": 0,
                "request_id": "cursor",
            },
        )
        assert sdk.execute("checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]})[
            "data"
        ]["is_current"]
