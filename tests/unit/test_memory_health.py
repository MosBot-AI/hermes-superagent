"""Optional SDK capacity report with bounded, redacted failure semantics."""

import json
from dataclasses import replace

import pytest
from test_memory_sdk import CorruptBackend
from test_memory_sdk import factory as factory

from personal_agent.memory_backend import MemoryError
from personal_agent.memory_sdk import LocalMemorySDK


def test_health_reports_current_capacity_including_tombstones_across_reopen(factory):
    with factory() as sdk:
        first = sdk.execute("health", {})
        assert first == {
            "data": {
                "schema_version": "personal.memory.health.v1",
                "store_schema_version": 13,
                "capacity": {
                    "records": {"used": 0, "limit": 1000},
                    "nonterminal_mutations": {"used": 0, "limit": 10000},
                    "mutations": {"used": 0, "limit": 11000},
                },
            },
            "replayed": False,
        }
        request = {"content": "private synthetic note", "request_id": "add"}
        record = sdk.execute("remember", request)["data"]
        sdk.execute("remember", request)
        key = {"record_id": record["record_id"]}
        sdk.execute(
            "correct", {**key, "expected_revision": 1, "topic": "private", "request_id": "edit"}
        )
        sdk.execute("forget", {**key, "expected_revision": 2, "request_id": "erase"})
    with factory() as sdk:
        result = sdk.execute("health", {})
        assert result["replayed"] is False
        capacity = result["data"]["capacity"]
        assert {name: quota["used"] for name, quota in capacity.items()} == {
            "records": 1,
            "nonterminal_mutations": 2,
            "mutations": 3,
        }
        encoded = json.dumps(result)
        for value in ("private", "synthetic-sdk", "synthetic-session", record["record_id"]):
            assert value not in encoded


def test_capability_operator_scope_and_request_validation_precede_dispatch(factory):
    class Probe(CorruptBackend):
        def __init__(self, backend, *, advertise):
            super().__init__(backend)
            self.advertise = advertise

        def describe(self):
            descriptor = super().describe()
            if not self.advertise:
                descriptor["capabilities"].remove("local_health")
            return descriptor

        def execute(self, operation, payload):
            assert operation == "export", "Health was dispatched before checking its gate"
            return super().execute(operation, payload)

    with factory() as sdk:
        backend = sdk._service.backend
        missing = LocalMemorySDK(Probe(backend, advertise=False), sdk.binding)
        with pytest.raises(MemoryError, match="capability_unavailable"):
            missing.execute("health", {})
        model = LocalMemorySDK(
            Probe(backend, advertise=True),
            replace(sdk.binding, source_kind="activated_session_model"),
        )
        with pytest.raises(MemoryError, match="health_scope_required"):
            model.execute("health", {})
        operator = LocalMemorySDK(Probe(backend, advertise=True), sdk.binding)
        with pytest.raises(MemoryError, match="invalid_request"):
            operator.execute("health", {"path": "synthetic"})


@pytest.mark.parametrize(
    "change",
    [
        lambda result: result.update(secret="private"),
        lambda result: result.update(schema_version="personal.memory.health.v2"),
        lambda result: result.update(store_schema_version=True),
        lambda result: result["capacity"]["records"].update(used=True),
        lambda result: result["capacity"]["records"].update(used=1001),
        lambda result: result["capacity"]["records"].update(limit=999),
        lambda result: result["capacity"]["mutations"].update(used=2),
        lambda result: result["capacity"].update(unreported={"used": 0, "limit": 1}),
    ],
)
def test_out_of_contract_health_does_not_return_adapter_details(factory, change):
    def transform(result):
        change(result)
        return result

    with factory() as sdk:
        adapter = CorruptBackend(sdk._service.backend, transform=transform)
        outer = LocalMemorySDK(adapter, sdk.binding)
        with pytest.raises(MemoryError, match="invalid_result") as failure:
            outer.execute("health", {})
        assert "private" not in str(failure.value)
