"""Optional SDK capability, independent adapter results and conformance."""

from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

import pytest
from test_retained_source_recovery import opened as disk_opened
from test_retained_source_sdk import Wrapper
from test_retained_sources import accept, opened, request

from personal_agent.memory_backend import MemoryError
from personal_agent.memory_conformance import run_record_origin_conformance
from personal_agent.memory_expiry import utc_now
from personal_agent.memory_record_origin import NOTICE, SCOPE
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from personal_agent.memory_sdk_example import SyntheticMemoryAdapter


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"record_id": None},
        {"record_id": []},
        {"record_id": "wrong"},
        {"record_id": str(uuid4()), "namespace_id": "foreign"},
    ],
)
def test_invalid_request_before_dispatch(payload):
    with opened() as (_, backend, _):
        wrapper = Wrapper(backend)
        sdk = LocalMemorySDK(wrapper, LocalBinding("synthetic", "session"))
        with pytest.raises(MemoryError, match="invalid_request"):
            sdk.execute("record_origin", payload)
        assert wrapper.calls == []


def test_optional_capability_and_model_binding_before_dispatch():
    with opened() as (_, backend, _):
        wrapper = Wrapper(backend, omit="record_origin")
        sdk = LocalMemorySDK(wrapper, LocalBinding("synthetic", "session"))
        with pytest.raises(MemoryError, match="capability_unavailable"):
            sdk.execute("record_origin", {"record_id": str(uuid4())})
        assert wrapper.calls == []
        wrapper = Wrapper(backend)
        sdk = LocalMemorySDK(
            wrapper, LocalBinding("synthetic", "session", "activated_session_model")
        )
        with pytest.raises(MemoryError, match="source_scope_required"):
            sdk.execute("record_origin", {"record_id": str(uuid4())})
        assert wrapper.calls == []
        backend._source_kind = "activated_session_model"
        with pytest.raises(MemoryError, match="source_scope_required"):
            backend.execute("record_origin", {"record_id": str(uuid4())})


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(extra="private"),
        lambda d: d.update(namespace_id="other"),
        lambda d: d.update(record_id=str(uuid4())),
        lambda d: d.update(evaluated_at=None),
        lambda d: d.update(scope="authority"),
        lambda d: d.update(notice=""),
        lambda d: d.update(current_editing_route="user"),
        lambda d: d.update(current_editing_route=None),
        lambda d: d["current"].update(revision=True),
        lambda d: d["current"].update(record_id=str(uuid4())),
        lambda d: d["current"].update(expires_at="bad"),
        lambda d: d["current"].update(expired=True),
        lambda d: d["current"].update(status="forgotten"),
        lambda d: d["origin"].update(kind="other"),
        lambda d: d["origin"].update(source_sequence=True),
        lambda d: d["origin"].update(source_sequence=1001),
        lambda d: d["origin"].update(role="owner"),
        lambda d: d["origin"].update(consumer_id="x" * 10000),
        lambda d: d["origin"].update(suppressed=1),
        lambda d: d["origin"].update(identity="a" * 64),
        lambda d: d["origin"]["acceptance"].update(revision=True),
        lambda d: d["origin"]["acceptance"].update(revision=2),
        lambda d: d["origin"]["acceptance"].update(record_id=str(uuid4())),
        lambda d: d["origin"]["acceptance"].update(status="forgotten"),
        lambda d: d["origin"]["acceptance"].update(event_sequence=0),
        lambda d: d["current"].update(revision=2),
    ],
)
def test_malformed_adapter_never_becomes_unavailable(change):
    with opened() as (sdk, backend, _):
        rid = accept(sdk, request())["record_id"]

        def transform(data):
            change(data)
            return data

        wrapper = Wrapper(backend, transform=transform)
        outer = LocalMemorySDK(wrapper, LocalBinding("synthetic", "session"))
        with pytest.raises(MemoryError, match="invalid_result"):
            outer.execute("record_origin", {"record_id": rid})


class IndependentOriginAdapter:
    """Test-only metadata index beside the independent example, no SQLite origin code.

    Fixture factory persists the metadata dictionary across reopenings. Origin
    reads only that dictionary; deliberate fixture writes keep it synchronized.
    Not a production resource, storage or concurrency implementation.
    """

    def __init__(self, directory, metadata):
        self.inner = SyntheticMemoryAdapter(directory)
        self.metadata = metadata

    def describe(self):
        descriptor = self.inner.describe()
        descriptor["capabilities"].append("record_origin")
        return descriptor

    def execute(self, operation, payload):
        if operation == "record_origin":
            current = self.metadata.get(payload["record_id"])
            if current is None:
                raise MemoryError("not_found")
            return {
                "namespace_id": "synthetic-example",
                "record_id": current["record_id"],
                "evaluated_at": utc_now(),
                "current": deepcopy(current),
                "current_editing_route": None
                if current["status"] == "forgotten"
                else "explicit_local_operator",
                "origin": {"kind": "unavailable", "reason": "no_durable_lineage"},
                "scope": SCOPE,
                "notice": NOTICE,
            }
        result = self.inner.execute(operation, payload)
        if operation in {"remember", "correct", "forget"} and not result["replayed"]:
            receipt = result["data"]
            self.metadata[receipt["record_id"]] = {
                k: receipt[k] for k in ("record_id", "revision", "status")
            }
            self.metadata[receipt["record_id"]].update(expires_at=None, expired=False)
        return result

    def close(self):
        self.inner.close()


@pytest.mark.parametrize("independent", [False, True])
def test_optional_origin_conformance(tmp_path, independent):
    metadata = {}

    @contextmanager
    def factory():
        if independent:
            backend = IndependentOriginAdapter(tmp_path, metadata)
            sdk = LocalMemorySDK(backend, LocalBinding("synthetic-example", "session"))
            try:
                yield sdk
            finally:
                sdk.close()
        else:
            with disk_opened(tmp_path / "memory.db") as (sdk, _, _):
                yield sdk

    with pytest.raises(MemoryError, match="synthetic_store_required"):
        run_record_origin_conformance(factory)
    assert len(run_record_origin_conformance(factory, isolated_synthetic=True).passed) == 4
    with pytest.raises(MemoryError, match="empty_store_required"):
        run_record_origin_conformance(factory, isolated_synthetic=True)


def test_old_independent_crud_adapter_still_compatible(tmp_path):
    backend = SyntheticMemoryAdapter(tmp_path)
    try:
        sdk = LocalMemorySDK(backend, LocalBinding("synthetic-example", "session"))
        rid = sdk.execute("remember", {"request_id": "a", "content": "synthetic"})["data"][
            "record_id"
        ]
        with pytest.raises(MemoryError, match="capability_unavailable"):
            sdk.execute("record_origin", {"record_id": rid})
        assert sdk.execute("get", {"record_id": rid})["data"]["content"] == "synthetic"
    finally:
        backend.close()


@pytest.mark.parametrize(
    "replacement",
    [
        {"kind": "unavailable"},
        {"kind": "unavailable", "reason": "source_deleted"},
        {"kind": "unavailable", "reason": "no_durable_lineage", "role": "user"},
        {
            "kind": "reviewed_candidate",
            "candidate_id": "bad",
            "acceptance": {},
            "suppressed": False,
        },
    ],
)
def test_invalid_origin_variant_shapes(replacement):
    with opened() as (sdk, backend, _):
        rid = accept(sdk, request())["record_id"]

        def transform(data):
            data["origin"] = replacement
            return data

        outer = LocalMemorySDK(
            Wrapper(backend, transform=transform), LocalBinding("synthetic", "session")
        )
        with pytest.raises(MemoryError, match="invalid_result"):
            outer.execute("record_origin", {"record_id": rid})
