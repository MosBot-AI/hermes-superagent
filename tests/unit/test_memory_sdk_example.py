"""Independent example evidence, limited to an owned synthetic store."""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from personal_agent.memory_backend import MemoryError, MemoryService
from personal_agent.memory_sdk_example import SyntheticMemoryAdapter
from tests.unit.test_memory_adapter_conformance import ExplicitRecordConformance


@pytest.fixture
def open_adapter(tmp_path):
    @contextmanager
    def opened():
        backend = SyntheticMemoryAdapter(tmp_path)
        try:
            yield backend
        finally:
            backend.close()

    return opened


class TestIndependentExample(ExplicitRecordConformance):
    pass


def test_correction_is_persistent_and_forget_purges_current_payload(tmp_path):
    backend = SyntheticMemoryAdapter(tmp_path)
    service = MemoryService(backend)
    created = service.execute("remember", {"content": "original", "request_id": "create"})
    rid = created["data"]["record_id"]
    request = {
        "record_id": rid,
        "content": "revised",
        "topic": "synthetic",
        "expected_revision": 1,
        "request_id": "correct",
    }
    receipt = service.execute("correct", request)
    backend.close()
    backend = SyntheticMemoryAdapter(tmp_path)
    service = MemoryService(backend)
    assert service.execute("correct", request) == {"data": receipt["data"], "replayed": True}
    assert service.execute("get", {"record_id": rid})["data"]["content"] == "revised"
    service.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"})
    backend.close()
    # Read the committed file independently, not an in-process cached dictionary.
    with sqlite3.connect(tmp_path / "synthetic-memory.sqlite3") as connection:
        state = json.loads(connection.execute("SELECT body FROM synthetic_state").fetchone()[0])
    assert state["records"][0]["revision"] == 3
    assert "revised" not in json.dumps(state)
    assert "original" not in json.dumps(state)


def test_example_rejects_unsupported_expiry_and_closed_use(tmp_path):
    backend = SyntheticMemoryAdapter(tmp_path)
    with pytest.raises(MemoryError) as caught:
        backend.execute(
            "remember",
            {"content": "synthetic", "request_id": "a", "expires_at": "2030-01-01T00:00:00Z"},
        )
    assert caught.value.code == "capability_unavailable"
    backend.close()
    with pytest.raises(MemoryError) as caught:
        backend.execute("list", {})
    assert caught.value.code == "not_open"


def test_standalone_sdk_conformance_on_independent_example(tmp_path):
    from personal_agent.memory_conformance import run_conformance
    from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK

    @contextmanager
    def opened():
        backend = SyntheticMemoryAdapter(tmp_path)
        try:
            yield LocalMemorySDK(backend, LocalBinding("synthetic-example", "synthetic-session"))
        finally:
            backend.close()

    report = run_conformance(opened, isolated_synthetic=True)
    assert report.sdk_version == 1
    assert report.passed
