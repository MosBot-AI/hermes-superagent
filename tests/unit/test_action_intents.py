"""Synthetic internal drafts cannot become approvals or execute operations."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from personal_agent import action_intents as intents
from personal_agent.action_intents import ActionIntentStore, IntentError

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
KEY = {"owner_id": "owner", "profile_id": "profile", "request_id": "request"}
SPEC = {
    **KEY,
    "operation": "example.send",
    "policy_revision": 7,
    "epoch": 2,
    "resource_revision": 3,
    "expires_at": NOW + timedelta(minutes=5),
    "target": b"synthetic-recipient-not-real",
    "payload": b"synthetic-content-not-real",
}


@pytest.fixture
def store():
    conn = sqlite3.connect(":memory:")
    result = ActionIntentStore(conn, clock=lambda: NOW)
    result.initialize()
    yield result
    conn.close()


def fail(code, operation):
    with pytest.raises(IntentError) as error:
        operation()
    assert error.value.code == code
    assert SPEC["payload"].decode() not in str(error.value)
    return error.value


def test_prepare_retry_cancel_terminal(store):
    draft = store.prepare(SPEC)
    assert draft["state"] == "draft" and draft["revision"] == 1
    assert store.prepare(dict(SPEC)) == draft
    assert store.inspect(KEY) == draft
    cancelled = store.cancel(KEY, expected_revision=1)
    assert cancelled["state"] == "cancelled" and cancelled["revision"] == 2
    assert store.cancel(KEY, expected_revision=1) == cancelled
    assert store.prepare(SPEC) == cancelled
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    fail("revision_conflict", lambda: store.cancel(KEY, expected_revision=2))


def test_payload_and_target_never_persist(store):
    record = store.prepare(SPEC)
    store.cancel(KEY, expected_revision=1)
    dump = "\n".join(store._connection.iterdump())
    assert SPEC["payload"].decode() not in dump
    assert SPEC["target"].decode() not in dump
    assert "payload" not in record and "target" not in record
    assert "approved" not in record and "authorization" not in record


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "another.action"),
        ("policy_revision", 8),
        ("epoch", 3),
        ("resource_revision", 4),
        ("target", b"other-target"),
        ("payload", b"other-payload"),
        ("expires_at", NOW + timedelta(minutes=6)),
    ],
)
def test_changed_binding_cannot_reuse_id(store, field, value):
    original = store.prepare(SPEC)
    fail("request_conflict", lambda: store.prepare({**SPEC, field: value}))
    assert store.inspect(KEY) == original
    store.cancel(KEY, expected_revision=1)
    fail("request_conflict", lambda: store.prepare({**SPEC, field: value}))


def test_binding_covers_scope_and_request_id(store):
    first = store.prepare(SPEC)
    for field in KEY:
        changed = {**SPEC, field: "other"}
        record = store.prepare(changed)
        assert record["binding_digest"] != first["binding_digest"]
    assert store._connection.execute("SELECT count(*) FROM intents").fetchone()[0] == 4
    fail("not_found", lambda: store.inspect({**KEY, "owner_id": "absent"}))


def test_expiry_persisted_and_does_not_revive(store):
    draft = store.prepare(SPEC)
    store._clock = lambda: SPEC["expires_at"]
    expired = store.inspect(KEY)
    assert expired["state"] == "expired" and expired["revision"] == 2
    assert store.cancel(KEY, expected_revision=1) == expired
    store._clock = lambda: NOW + timedelta(seconds=1)
    assert store.prepare(SPEC) == expired
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    assert expired["binding_digest"] == draft["binding_digest"]


def test_expired_cancel_truthful(store):
    store.prepare(SPEC)
    store._clock = lambda: SPEC["expires_at"]
    assert store.cancel(KEY, expected_revision=1)["state"] == "expired"


@pytest.mark.parametrize("expiry", [NOW, NOW - timedelta(seconds=1), NOW + timedelta(days=2)])
def test_invalid_expiry(store, expiry):
    fail("invalid_expiry", lambda: store.prepare({**SPEC, "expires_at": expiry}))
    assert store._connection.execute("SELECT count(*) FROM intents").fetchone()[0] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", ""),
        ("profile_id", "../bad"),
        ("request_id", "x" * 129),
        ("operation", "space command"),
        ("operation", True),
        ("policy_revision", True),
        ("policy_revision", 0),
        ("epoch", -1),
        ("resource_revision", 2**63),
        ("target", "text"),
        ("target", b""),
        ("target", b"x" * 4097),
        ("payload", bytearray(b"x")),
        ("payload", b""),
        ("payload", b"x" * 65537),
    ],
)
def test_invalid_spec(store, field, value):
    fail("invalid_request", lambda: store.prepare({**SPEC, field: value}))


@pytest.mark.parametrize(
    "expiry", [NOW.replace(tzinfo=None), "2026-11-08", None, NOW.replace(fold=1)]
)
def test_invalid_time(store, expiry):
    fail("invalid_time", lambda: store.prepare({**SPEC, "expires_at": expiry}))


def test_unrecognized_fields_and_types(store):
    fail("invalid_request", lambda: store.prepare({**SPEC, "approved": True}))
    fail("invalid_request", lambda: store.prepare({k: v for k, v in SPEC.items() if k != "epoch"}))
    fail("invalid_request", lambda: store.inspect({**KEY, "policy_revision": 7}))
    fail("invalid_request", lambda: store.inspect([]))
    fail("revision_conflict", lambda: store.cancel(KEY, expected_revision=True))


def test_clock_failures_and_regression(store):
    store.prepare(SPEC)
    store._clock = lambda: NOW - timedelta(seconds=1)
    fail("clock_regressed", lambda: store.inspect(KEY))
    store._clock = lambda: "not-time"
    fail("invalid_time", lambda: store.inspect(KEY))

    def broken():
        raise RuntimeError("private-error")

    store._clock = broken
    assert "private-error" not in str(fail("invalid_time", lambda: store.inspect(KEY)))


def test_clock_sample_after_begin(store):
    sampled = []

    def clock():
        sampled.append(store._connection.in_transaction)
        return NOW

    store._clock = clock
    store.prepare(SPEC)
    store.inspect(KEY)
    store.cancel(KEY, expected_revision=1)
    assert sampled == [True, True, True]


def test_capacity_does_not_evict_or_block_cancellation(store, monkeypatch):
    monkeypatch.setattr(intents, "MAX_INTENTS", 1)
    first = store.prepare(SPEC)
    fail("capacity_exhausted", lambda: store.prepare({**SPEC, "request_id": "second"}))
    assert store.prepare(SPEC) == first
    store.cancel(KEY, expected_revision=1)
    fail("capacity_exhausted", lambda: store.prepare({**SPEC, "request_id": "second"}))
    assert store.inspect(KEY)["state"] == "cancelled"


def test_schema_fail_closed(store):
    store._connection.execute("CREATE TEMP TABLE intents (fake TEXT)")
    fail("unsupported_schema", lambda: store.prepare(SPEC))
    store._connection.execute("DROP TABLE temp.intents")
    store._connection.execute("CREATE TABLE unknown (fake TEXT)")
    fail("unsupported_schema", lambda: store.prepare(SPEC))


def test_new_store_and_foreign_database():
    conn = sqlite3.connect(":memory:")
    store = ActionIntentStore(conn, clock=lambda: NOW)
    fail("not_initialized", lambda: store.prepare(SPEC))
    conn.execute("PRAGMA application_id=1")
    fail("foreign_database", store.initialize)
    assert not store._initialized
    conn.close()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE intents SET binding_digest='bad'",
        "UPDATE intents SET target_digest='" + "a" * 64 + "'",
        "UPDATE intents SET epoch=-1",
        "UPDATE intents SET created_at='wrong'",
        "DELETE FROM events",
        "UPDATE events SET recorded_at='wrong'",
    ],
)
def test_corruption_refused(store, sql):
    store.prepare(SPEC)
    store._connection.execute(sql)
    store._connection.commit()
    fail("invalid_record", lambda: store.inspect(KEY))


class FailingConnection(sqlite3.Connection):
    failure = None

    def execute(self, sql, parameters=()):
        if self.failure is not None and sql.startswith(self.failure):
            raise sqlite3.OperationalError("private-database-error")
        return super().execute(sql, parameters)


@pytest.mark.parametrize("failure", ["INSERT INTO main.events", "COMMIT"])
def test_prepare_atomic_failure(failure):
    conn = sqlite3.connect(":memory:", factory=FailingConnection)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    conn.failure = failure
    assert "private" not in str(fail("storage_error", lambda: store.prepare(SPEC)))
    conn.failure = None
    assert conn.execute("SELECT count(*) FROM intents").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert store.prepare(SPEC)["revision"] == 1
    conn.close()


def test_cancel_commit_failure_rolls_back():
    conn = sqlite3.connect(":memory:", factory=FailingConnection)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    draft = store.prepare(SPEC)
    conn.failure = "COMMIT"
    fail("storage_error", lambda: store.cancel(KEY, expected_revision=1))
    conn.failure = None
    assert store.inspect(KEY) == draft
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    conn.close()


def test_persistence_and_concurrent_retry(tmp_path):
    path = tmp_path / "intents.sqlite3"
    conn = sqlite3.connect(path)
    ActionIntentStore(conn).initialize()
    conn.close()
    barrier = Barrier(2)

    def worker():
        conn = sqlite3.connect(path, timeout=5)
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        barrier.wait()
        result = store.prepare(SPEC)
        conn.close()
        return result

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results[0] == results[1]
    conn = sqlite3.connect(path)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    assert store.inspect(KEY) == results[0]
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize("after_commit", [False, True])
def test_actual_process_exit_commit_boundary(tmp_path, after_commit):
    path = tmp_path / "intents.sqlite3"
    script = """
import os, sqlite3, sys
from datetime import UTC,datetime,timedelta
from personal_agent.action_intents import ActionIntentStore
class Crash(sqlite3.Connection):
    armed=False
    def execute(self,sql,parameters=()):
        if self.armed and sql == 'COMMIT':
            if sys.argv[2] == 'True':
                super().execute(sql,parameters)
            os._exit(23)
        return super().execute(sql,parameters)
conn=sqlite3.connect(sys.argv[1],factory=Crash)
now=datetime(2026,11,8,12,tzinfo=UTC)
store=ActionIntentStore(conn,clock=lambda:now)
store.initialize()
conn.armed=True
store.prepare(dict(owner_id='owner',profile_id='profile',request_id='request',
operation='example.send',policy_revision=7,epoch=2,resource_revision=3,
expires_at=now+timedelta(minutes=5),target=b'synthetic-recipient-not-real',
payload=b'synthetic-content-not-real'))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path), str(after_commit)], check=False
    )
    assert result.returncode == 23
    conn = sqlite3.connect(path)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    assert conn.execute("SELECT count(*) FROM intents").fetchone()[0] == int(after_commit)
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == int(after_commit)
    assert store.prepare(SPEC)["state"] == "draft"
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    conn.close()
