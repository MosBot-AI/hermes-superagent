"""Optional SDK progress conformance and hostile adapter boundaries."""

import pytest

from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_progress_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from tests.unit import test_memory_sdk
from tests.unit.test_memory_sdk import CorruptBackend

factory = test_memory_sdk.factory


def test_progress_conformance(factory):
    assert len(run_progress_conformance(factory, isolated_synthetic=True).passed) == 6


def test_progress_requires_empty_isolated_store(factory):
    with pytest.raises(MemoryError, match="synthetic_store_required"):
        run_progress_conformance(factory)
    with factory() as sdk:
        sdk.execute("remember", {"content": "existing", "request_id": "existing"})
    with pytest.raises(MemoryError, match="empty_store_required"):
        run_progress_conformance(factory, isolated_synthetic=True)


@pytest.mark.parametrize(
    "capability",
    ["metadata_changes", "durable_consumer_cursor", "durable_write", "cas", "idempotency"],
)
def test_missing_capability_denied_before_dispatch(factory, capability):
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
        calls.clear()
        with pytest.raises(MemoryError, match="capability_unavailable"):
            wrapped.execute(
                "consumer_advance",
                {
                    "consumer_id": "projection",
                    "expected_revision": 0,
                    "through_sequence": 0,
                    "request_id": "r",
                },
            )
        assert not calls


def test_model_binding_cannot_dispatch_even_replay(factory):
    with factory() as sdk:
        request = {
            "consumer_id": "projection",
            "expected_revision": 0,
            "through_sequence": 0,
            "request_id": "r",
        }
        sdk.execute("consumer_advance", request)
        calls = []

        class Observed(CorruptBackend):
            def execute(self, operation, payload):
                calls.append(operation)
                return self.backend.execute(operation, payload)

        wrapped = LocalMemorySDK(
            Observed(sdk._service.backend),
            LocalBinding("synthetic-sdk", "synthetic-session", "activated_session_model"),
        )
        calls.clear()
        with pytest.raises(MemoryError, match="consumer_scope_required"):
            wrapped.execute("consumer_advance", request)
        assert not calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("scope", "native_checkpoint"),
        ("retention_floor", 1),
        ("has_more", 1),
        ("next_sequence", 0),
        ("through_sequence", True),
        ("current_watermark", 0),
        ("items", []),
        ("secret", "private"),
    ],
)
def test_malformed_change_pages(factory, field, value):
    with factory() as sdk:
        sdk.execute("remember", {"content": "private", "request_id": "r"})
        wrapped = LocalMemorySDK(
            CorruptBackend(sdk._service.backend, lambda result: {**result, field: value}),
            sdk.binding,
        )
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("changes", {})


@pytest.mark.parametrize(
    "damage",
    [
        lambda item: {**item, "content": "private"},
        lambda item: {**item, "sequence": True},
        lambda item: {**item, "revision": 0},
        lambda item: {**item, "operation": "checkpoint"},
        lambda item: {**item, "record_id": "bad"},
    ],
)
def test_malformed_change_items(factory, damage):
    with factory() as sdk:
        sdk.execute("remember", {"content": "private", "request_id": "r"})

        def transform(result):
            result["items"] = [damage(result["items"][0])]
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("changes", {})


@pytest.mark.parametrize("operation", ["consumer_get", "consumer_advance"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("consumer_id", "wrong"),
        ("revision", True),
        ("registered", 1),
        ("scope", "checkpoint"),
        ("through_sequence", -1),
        ("content", "secret"),
    ],
)
def test_malformed_consumers(factory, operation, field, value):
    with factory() as sdk:

        def transform(result):
            target = result["data"] if operation == "consumer_advance" else result
            target[field] = value
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        request = {"consumer_id": "projection"}
        if operation == "consumer_advance":
            request.update(expected_revision=0, through_sequence=0, request_id="r")
        with pytest.raises(
            MemoryError,
            match=("outcome_unknown" if operation == "consumer_advance" else "invalid_result"),
        ):
            wrapped.execute(operation, request)
        if operation == "consumer_advance":
            assert sdk.execute(operation, request)["replayed"]


def test_lost_progress_acknowledgement_reconciles_same_key(factory):
    with factory() as sdk:
        wrapped = LocalMemorySDK(
            CorruptBackend(sdk._service.backend, error=RuntimeError("private secret")), sdk.binding
        )
        request = {
            "consumer_id": "projection",
            "expected_revision": 0,
            "through_sequence": 0,
            "request_id": "r",
        }
        with pytest.raises(MemoryError, match="outcome_unknown") as caught:
            wrapped.execute("consumer_advance", request)
        assert not caught.value.retryable
        assert sdk.execute("consumer_advance", request)["replayed"]
        assert sdk.execute("consumer_get", {"consumer_id": "projection"})["data"]["revision"] == 1


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate",
        "reversed",
        "read_replayed",
        "receipt_revision",
        "receipt_request",
        "receipt_sequence",
        "unknown_registered",
    ],
)
def test_additional_progress_relations(factory, damage):
    with factory() as sdk:
        for index in range(2):
            sdk.execute("remember", {"content": "x", "request_id": f"r{index}"})
        operation = "changes"
        request = {}
        if damage.startswith("receipt"):
            operation = "consumer_advance"
            request = {
                "consumer_id": "projection",
                "expected_revision": 0,
                "through_sequence": 1,
                "request_id": "advance",
            }
        elif damage == "unknown_registered":
            operation = "consumer_get"
            request = {"consumer_id": "projection"}

        def transform(result):
            if damage == "duplicate":
                result["items"][1] = result["items"][0].copy()
            elif damage == "reversed":
                result["items"].reverse()
            elif damage == "read_replayed":
                return {"data": result, "replayed": True}
            elif damage == "unknown_registered":
                result["registered"] = True
            else:
                field = {
                    "receipt_revision": "revision",
                    "receipt_request": "request_id",
                    "receipt_sequence": "through_sequence",
                }[damage]
                result["data"][field] = "wrong" if field == "request_id" else 2
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        with pytest.raises(
            MemoryError,
            match=("outcome_unknown" if operation == "consumer_advance" else "invalid_result"),
        ):
            wrapped.execute(operation, request)


def test_crud_only_adapter_still_admitted(factory):
    with factory() as sdk:

        class CrudOnly(CorruptBackend):
            def describe(self):
                descriptor = self.backend.describe()
                for capability in ("metadata_changes", "durable_consumer_cursor"):
                    descriptor["capabilities"].remove(capability)
                return descriptor

            def execute(self, operation, payload):
                return self.backend.execute(operation, payload)

        wrapped = LocalMemorySDK(CrudOnly(sdk._service.backend), sdk.binding)
        assert wrapped.execute("list", {})["data"]["items"] == []
        for operation, payload in (("changes", {}), ("consumer_get", {"consumer_id": "p"})):
            with pytest.raises(MemoryError, match="capability_unavailable"):
                wrapped.execute(operation, payload)


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("changes", {"after_sequence": True}),
        ("changes", {"through_sequence": -1}),
        ("changes", {"limit": 51}),
        ("consumer_get", {"consumer_id": "../private"}),
        (
            "consumer_advance",
            {
                "consumer_id": "projection",
                "expected_revision": True,
                "through_sequence": 0,
                "request_id": "r",
            },
        ),
        (
            "consumer_advance",
            {
                "consumer_id": "projection",
                "expected_revision": 0,
                "through_sequence": 0,
                "request_id": "r",
                "namespace_id": "other",
            },
        ),
    ],
)
def test_progress_invalid_requests_do_not_dispatch(factory, operation, payload):
    with factory() as sdk:
        calls = []

        class Observed(CorruptBackend):
            def execute(self, operation, payload):
                calls.append(operation)
                return self.backend.execute(operation, payload)

        wrapped = LocalMemorySDK(Observed(sdk._service.backend), sdk.binding)
        calls.clear()
        with pytest.raises(MemoryError, match="invalid_request"):
            wrapped.execute(operation, payload)
        assert not calls


@pytest.mark.parametrize(
    "damage",
    [
        "false_terminal",
        "more_at_bound",
        "empty_nonterminal",
        "boolean_revision",
        "duplicate_revision",
        "regressive_revision",
        "after_forget",
    ],
)
def test_feed_pagination_and_record_history_invariants(factory, damage):
    with factory() as sdk:
        created = sdk.execute("remember", {"content": "x", "request_id": "r"})
        sdk.execute(
            "correct",
            {
                "record_id": created["data"]["record_id"],
                "expected_revision": 1,
                "content": "y",
                "request_id": "c",
            },
        )

        def transform(result):
            if damage == "false_terminal":
                result["items"] = result["items"][:1]
                result["next_sequence"] = result["items"][0]["sequence"]
            elif damage == "more_at_bound":
                result["has_more"] = True
            elif damage == "empty_nonterminal":
                result.update(items=[], next_sequence=0, has_more=True)
            elif damage == "boolean_revision":
                result["items"][0]["revision"] = True
            elif damage == "duplicate_revision":
                result["items"][0].update(revision=2, operation="correct")
            elif damage == "regressive_revision":
                result["items"][0].update(revision=3, operation="correct")
            else:
                result["items"][0].update(revision=2, operation="forget")
                result["items"][1]["revision"] = 3
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        with pytest.raises(MemoryError, match="invalid_result"):
            wrapped.execute("changes", {"limit": 2})


def test_sparse_increasing_feed_is_valid(factory):
    with factory() as sdk:
        created = sdk.execute("remember", {"content": "x", "request_id": "r"})
        rid = created["data"]["record_id"]

        def transform(result):
            result.update(
                items=[
                    {"sequence": 5, "record_id": rid, "revision": 2, "operation": "correct"},
                    {"sequence": 9, "record_id": rid, "revision": 7, "operation": "forget"},
                ],
                through_sequence=9,
                current_watermark=9,
                next_sequence=9,
            )
            return result

        wrapped = LocalMemorySDK(CorruptBackend(sdk._service.backend, transform), sdk.binding)
        assert wrapped.execute("changes", {})["data"]["next_sequence"] == 9
