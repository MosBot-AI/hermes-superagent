"""Contract tests for the bounded explicit local memory adapter."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import (
    MemoryBackend,
    MemoryError,
    MemoryService,
    validate_request,
)


@pytest.fixture
def opened():
    conn = sqlite3.connect(":memory:")
    backend = create_backend()
    backend.open(conn, namespace_id="profile:test", session_ref="session:test")
    yield backend, conn
    backend.close()
    conn.close()


def remember(backend, content="偏好中文 % _", key="first", **kwargs):
    return backend.execute("remember", {"content": content, "request_id": key, **kwargs})


def assert_error(code, call):
    with pytest.raises(MemoryError) as caught:
        call()
    assert caught.value.code == code


def test_factory_service_and_descriptor(opened):
    backend, conn = opened
    assert isinstance(backend, MemoryBackend)
    assert backend.describe()["api_version"] == 1
    assert conn.execute("PRAGMA secure_delete").fetchone()[0] == 1
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
    service = MemoryService(backend)
    assert service.execute("list", {})["data"]["items"] == []
    for method in (backend.changes, backend.checkpoint, backend.import_snapshot):
        assert_error("unsupported", method)
    backend.close()
    assert_error("not_open", lambda: backend.execute("list", {}))
    assert conn.execute("SELECT 1").fetchone() == (1,)


def test_roundtrip_cas_replay_and_terminal_forget(opened):
    backend, conn = opened
    first = remember(backend)
    receipt = first["data"]
    rid = receipt["record_id"]
    assert first["replayed"] is False
    assert remember(backend) == {"data": receipt, "replayed": True}
    assert_error("idempotency_conflict", lambda: remember(backend, "changed"))
    row = backend.execute("get", {"record_id": rid})
    assert row["content"] == "偏好中文 % _"
    assert row["source"] == "explicit_local_operator"
    assert row["session_ref"] == "session:test"
    correction = {
        "record_id": rid,
        "expected_revision": 1,
        "request_id": "edit",
        "content": "new private text",
    }
    updated = backend.execute("correct", correction)
    assert updated["data"]["revision"] == 2
    assert_error(
        "revision_conflict",
        lambda: backend.execute("correct", {**correction, "request_id": "stale"}),
    )
    forgotten = backend.execute(
        "forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"}
    )
    assert forgotten["data"]["status"] == "forgotten"
    assert backend.execute("list", {})["items"] == []
    assert backend.execute("search", {"query": "private"})["items"] == []
    tombstone = backend.execute("get", {"record_id": rid})
    for field in ("content", "topic", "source", "session_ref"):
        assert tombstone[field] is None
    assert backend.execute("correct", correction) == {"data": updated["data"], "replayed": True}
    assert remember(backend) == {"data": receipt, "replayed": True}
    assert_error(
        "record_forgotten",
        lambda: backend.execute(
            "correct", {**correction, "request_id": "resurrect", "expected_revision": 3}
        ),
    )
    assert_error(
        "record_forgotten",
        lambda: backend.execute(
            "forget", {"record_id": rid, "request_id": "forget-again", "expected_revision": 3}
        ),
    )
    logical_dump = "\n".join(conn.iterdump())
    assert "private text" not in logical_dump
    assert "偏好中文" not in logical_dump
    assert len(conn.execute("SELECT * FROM events").fetchall()) == 3


def test_literal_search_pages_and_export(opened):
    backend, _ = opened
    first = remember(backend, "中文%_' OR 1=1", topic="Topic")["data"]
    second = remember(backend, "plain", "second")["data"]
    assert backend.execute("search", {"query": "%_"})["items"][0]["record_id"] == first["record_id"]
    assert backend.execute("search", {"query": "topic"})["items"] == []
    assert backend.execute("search", {"query": "中文"})["items"][0]["content"].startswith("中文")
    page = backend.execute("list", {"limit": 1})
    assert page["next_cursor"] == second["record_id"]
    assert (
        backend.execute("list", {"after": page["next_cursor"]})["items"][0]["record_id"]
        == first["record_id"]
    )
    backend.execute(
        "forget", {"record_id": second["record_id"], "expected_revision": 1, "request_id": "forget"}
    )
    exported = backend.execute("export", {"limit": 1})
    assert exported["items"][0]["status"] == "forgotten"
    assert exported["watermark"] == 3
    assert exported["restorable"] is False
    assert exported["has_more"] is True
    assert "digest" not in json.dumps(exported)
    assert_error("invalid_cursor", lambda: backend.execute("list", {"after": str(uuid4())}))


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("remember", {"content": "x", "request_id": "a", "namespace_id": "evil"}),
        ("remember", {"content": "x" * 2049, "request_id": "a"}),
        ("remember", {"content": "x", "topic": "x" * 129, "request_id": "a"}),
        ("remember", {"content": "x\x00", "request_id": "a"}),
        ("remember", {"content": "x", "request_id": "a\n"}),
        ("remember", {"content": " ", "request_id": "a"}),
        ("search", {"query": "x" * 129}),
        ("list", {"limit": True}),
        ("export", {"limit": 51}),
        (
            "correct",
            {"record_id": str(uuid4()), "expected_revision": True, "request_id": "a", "topic": "t"},
        ),
        ("correct", {"record_id": str(uuid4()), "expected_revision": 1, "request_id": "a"}),
        ("get", {"record_id": "bad"}),
        ("list", {"after": "bad"}),
        ("unknown", {}),
    ],
)
def test_invalid_requests(operation, payload):
    assert_error("invalid_request", lambda: validate_request(operation, payload))


def test_schema_and_namespace_rejection(tmp_path):
    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    backend = create_backend()
    backend.open(conn, namespace_id="a", session_ref="s")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    backend.close()
    assert_error(
        "namespace_mismatch", lambda: backend.open(conn, namespace_id="b", session_ref="s")
    )
    conn.execute("CREATE TABLE foreign_table (data TEXT)")
    assert_error(
        "unsupported_schema", lambda: backend.open(conn, namespace_id="a", session_ref="s")
    )
    conn.close()
    foreign = sqlite3.connect(":memory:")
    foreign.execute("CREATE TABLE other (x)")
    assert_error(
        "foreign_database",
        lambda: create_backend().open(foreign, namespace_id="a", session_ref="s"),
    )
    foreign.close()


def test_outer_transaction_not_committed_or_rolled_back(opened):
    backend, conn = opened
    conn.execute("BEGIN")
    assert_error("connection_in_transaction", lambda: remember(backend))
    assert conn.in_transaction
    conn.rollback()
    assert backend.execute("list", {})["items"] == []


def test_receipt_failure_rolls_back_all(opened):
    backend, conn = opened
    # Authorizer denial simulates a failure after canonical/event writes.
    conn.set_authorizer(
        lambda action, table, *_: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_INSERT and table == "receipts"
            else sqlite3.SQLITE_OK
        )
    )
    assert_error("storage_error", lambda: remember(backend))
    conn.set_authorizer(None)
    assert conn.execute("SELECT count(*) FROM records").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert not conn.in_transaction


def test_two_connections_cas_and_redacted_busy(tmp_path):
    path = tmp_path / "memory.db"
    c1, c2 = sqlite3.connect(path, timeout=0), sqlite3.connect(path, timeout=0)
    b1, b2 = create_backend(), create_backend()
    for backend, conn in ((b1, c1), (b2, c2)):
        backend.open(conn, namespace_id="a", session_ref="s")
    rid = remember(b1)["data"]["record_id"]
    correction = {"record_id": rid, "expected_revision": 1, "request_id": "edit", "topic": "t"}
    b1.execute("correct", correction)
    assert_error(
        "revision_conflict", lambda: b2.execute("correct", {**correction, "request_id": "other"})
    )
    c1.execute("BEGIN IMMEDIATE")
    with pytest.raises(MemoryError) as caught:
        remember(b2, key="blocked")
    assert caught.value.code == "storage_busy" and caught.value.retryable
    c1.rollback()
    c1.close()
    c2.close()


def test_record_cap_counts_tombstones(opened):
    backend, conn = opened
    # Populate fixture efficiently; production writes enforce the same total cap.
    conn.executemany(
        "INSERT INTO records(record_id,revision,status,created_at,updated_at) "
        "VALUES (?,1,'forgotten','t','t')",
        [(str(uuid4()),) for _ in range(1000)],
    )
    conn.commit()
    assert_error("record_limit", lambda: remember(backend))
    assert len(backend.execute("export", {"limit": 50})["items"]) == 50


def test_mutation_cap_preserves_replay_and_forget(opened):
    backend, conn = opened
    first = remember(backend)
    rid = first["data"]["record_id"]
    conn.executemany(
        "INSERT INTO events(record_id,revision,operation) VALUES (?,?,'correct')",
        [(rid, revision) for revision in range(3, 10002)],
    )
    conn.commit()
    assert_error("mutation_limit", lambda: remember(backend, key="new"))
    assert remember(backend)["replayed"] is True
    result = backend.execute(
        "forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"}
    )
    assert result["data"]["status"] == "forgotten"


def test_reopen_replay_is_session_independent_and_metadata_only(tmp_path):
    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    backend = create_backend()
    backend.open(conn, namespace_id="a", session_ref="session-one")
    first = remember(backend, "private content", topic="private topic")
    backend.close()
    conn.close()
    conn = sqlite3.connect(path)
    backend.open(conn, namespace_id="a", session_ref="session-two")
    replay = remember(backend, "private content", topic="private topic")
    assert replay == {"data": first["data"], "replayed": True}
    serialized = json.dumps(replay)
    assert "private" not in serialized and "session-one" not in serialized
    assert conn.execute("SELECT session_ref FROM records").fetchone()[0] == "session-one"
    backend.close()
    conn.close()


def test_exact_schema_rejects_trigger_and_future_version(opened):
    backend, conn = opened
    backend.close()
    conn.execute("PRAGMA user_version=2")
    assert_error(
        "unsupported_schema",
        lambda: backend.open(conn, namespace_id="profile:test", session_ref="s"),
    )
    conn.execute("PRAGMA user_version=1")
    conn.execute("CREATE TRIGGER surprise AFTER INSERT ON events BEGIN SELECT 1; END")
    assert_error(
        "unsupported_schema",
        lambda: backend.open(conn, namespace_id="profile:test", session_ref="s"),
    )


def test_concurrent_first_open_uses_atomic_preflight_snapshot(tmp_path):
    path = tmp_path / "concurrent.db"
    # A pauses after reading application_id. B then attempts a full first open.
    # Without a read transaction B commits, and A mixes the old application_id
    # with the new schema, incorrectly rejecting its own database as foreign.
    rendezvous = Barrier(2, timeout=5)
    attempted = Event()
    reader_done = Event()

    def reader():
        conn = sqlite3.connect(path, timeout=1)
        paused = False

        def trace(sql):
            nonlocal paused
            if sql == "PRAGMA user_version" and not paused:
                paused = True
                rendezvous.wait()
                assert attempted.wait(5)

        conn.set_trace_callback(trace)
        backend = create_backend()
        try:
            backend.open(conn, namespace_id="same", session_ref="reader")
            return backend.execute("list", {})
        finally:
            reader_done.set()
            backend.close()
            conn.close()

    def writer():
        conn = sqlite3.connect(path, timeout=0)
        backend = create_backend()
        rendezvous.wait()
        try:
            try:
                backend.open(conn, namespace_id="same", session_ref="writer")
            except MemoryError as error:
                assert error.code == "storage_busy" and error.retryable
                assert not conn.in_transaction
                attempted.set()
                assert reader_done.wait(5)
                backend.open(conn, namespace_id="same", session_ref="writer")
            return backend.execute("list", {})
        finally:
            attempted.set()
            backend.close()
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(reader), pool.submit(writer)
        assert first.result(timeout=10)["items"] == []
        assert second.result(timeout=10)["items"] == []
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT id FROM namespace").fetchall() == [("same",)]
    conn.close()
