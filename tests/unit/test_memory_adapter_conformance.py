"""Reusable behavioral gates for an opened API-v1 explicit-record adapter.

An adapter author can reuse ExplicitRecordConformance with an open_adapter
fixture. Each call must return a context manager opening the same fresh, durable,
isolated synthetic store; each test gets a new store. This suite is not a loader
or certification of remote storage, malicious-code isolation or the future SDK.
"""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError, MemoryService


class ExplicitRecordConformance:
    def test_committed_receipt_and_record_survive_reopen(self, open_adapter):
        request = {"content": "synthetic record", "request_id": "commit"}
        with open_adapter() as backend:
            service = MemoryService(backend)
            receipt = service.execute("remember", request)
        with open_adapter() as backend:
            service = MemoryService(backend)
            assert service.execute("remember", request) == {
                "data": receipt["data"],
                "replayed": True,
            }
            assert (
                service.execute("get", {"record_id": receipt["data"]["record_id"]})["data"][
                    "content"
                ]
                == "synthetic record"
            )
        assert "synthetic record" not in json.dumps(receipt)

    def test_changed_retry_and_stale_correction_do_not_write(self, open_adapter):
        with open_adapter() as backend:
            service = MemoryService(backend)
            receipt = service.execute("remember", {"content": "one", "request_id": "same"})
            rid = receipt["data"]["record_id"]
            for operation, payload, code in (
                ("remember", {"content": "two", "request_id": "same"}, "idempotency_conflict"),
                (
                    "correct",
                    {
                        "record_id": rid,
                        "content": "two",
                        "expected_revision": 2,
                        "request_id": "correct",
                    },
                    "revision_conflict",
                ),
            ):
                with pytest.raises(MemoryError) as caught:
                    service.execute(operation, payload)
                assert caught.value.code == code
            record = service.execute("get", {"record_id": rid})["data"]
            assert (record["revision"], record["content"]) == (1, "one")

    def test_forget_is_terminal_and_old_receipt_cannot_revive_content(self, open_adapter):
        request = {"content": "synthetic secret", "request_id": "remember"}
        with open_adapter() as backend:
            service = MemoryService(backend)
            receipt = service.execute("remember", request)
            rid = receipt["data"]["record_id"]
            service.execute(
                "forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
            )
        with open_adapter() as backend:
            service = MemoryService(backend)
            assert service.execute("remember", request)["replayed"] is True
            record = service.execute("get", {"record_id": rid})["data"]
            assert record["status"] == "forgotten"
            assert record["revision"] == 2
            assert all(record[key] is None for key in ("content", "topic", "source", "session_ref"))
            assert service.execute("list", {})["data"]["items"] == []
            assert service.execute("search", {"query": "synthetic"})["data"]["items"] == []
            exported = service.execute("export", {})["data"]
            assert exported["items"] == [record]
            assert exported["restorable"] is False
            assert "synthetic secret" not in json.dumps(exported)
            with pytest.raises(MemoryError) as caught:
                service.execute(
                    "correct",
                    {
                        "record_id": rid,
                        "expected_revision": 2,
                        "content": "revived",
                        "request_id": "revive",
                    },
                )
            assert caught.value.code == "record_forgotten"

    def test_literal_unicode_search_and_bounded_pages(self, open_adapter):
        with open_adapter() as backend:
            service = MemoryService(backend)
            for index, content in enumerate(("中文 Hermes % _", "different")):
                service.execute("remember", {"content": content, "request_id": f"r{index}"})
            for query in ("中", "%", "_", "Hermes"):
                records = service.execute("search", {"query": query})["data"]["items"]
                assert len(records) == 1
                assert records[0]["content"] == "中文 Hermes % _"
            assert service.execute("search", {"query": "hermes"})["data"]["items"] == []
            first = service.execute("list", {"limit": 1})["data"]
            assert len(first["items"]) == 1 and first["has_more"] is True
            second = service.execute("list", {"limit": 1, "after": first["next_cursor"]})["data"]
            assert len(second["items"]) == 1 and second["has_more"] is False
            assert second["next_cursor"] is None
            assert first["items"][0]["record_id"] != second["items"][0]["record_id"]


@pytest.fixture(params=["explicit_local_operator", "activated_session_model"])
def open_adapter(tmp_path, request):
    @contextmanager
    def opened():
        conn = sqlite3.connect(tmp_path / "conformance.sqlite3")
        backend = create_backend()
        try:
            backend.open(
                conn,
                namespace_id="synthetic-conformance",
                session_ref="synthetic-session",
                source_kind=request.param,
            )
            yield backend
        finally:
            backend.close()
            conn.close()

    return opened


class TestLocalAdapterConformance(ExplicitRecordConformance):
    pass
