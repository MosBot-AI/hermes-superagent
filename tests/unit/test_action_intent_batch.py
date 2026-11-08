"""Explicit internal batch cancellation is atomic, bounded and non-authorizing."""

import sqlite3
from datetime import timedelta

import pytest

from personal_agent.action_intents import ActionIntentStore, IntentError
from tests.unit.test_action_intents import KEY, NOW, SPEC, fail


def selection(record):
    return {name: record[name] for name in (*KEY, "binding_digest")}


@pytest.fixture
def store():
    conn = sqlite3.connect(":memory:")
    result = ActionIntentStore(conn, clock=lambda: NOW)
    result.initialize()
    yield result
    conn.close()


def prepare(store, number=3):
    return [store.prepare({**SPEC, "request_id": f"r{index}"}) for index in range(number)]


def test_cancel_explicit_subset_and_exact_retry(store):
    records = prepare(store)
    selected = [selection(records[2]), selection(records[0])]
    result = store.cancel_many(selected)
    assert [r["request_id"] for r in result] == ["r2", "r0"]
    assert all((r["state"], r["revision"]) == ("cancelled", 2) for r in result)
    assert store.cancel_many(selected) == result
    assert store.inspect({**KEY, "request_id": "r1"})["state"] == "draft"
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 5


def test_mixed_terminal_outcomes_are_truthful(store):
    expired = store.prepare(
        {**SPEC, "request_id": "expired", "expires_at": NOW + timedelta(seconds=1)}
    )
    cancelled, pending = prepare(store, 2)
    store.cancel({k: cancelled[k] for k in KEY}, expected_revision=1)
    store._clock = lambda: NOW + timedelta(seconds=2)
    selected = [selection(r) for r in (expired, cancelled, pending)]
    result = store.cancel_many(selected)
    assert [r["state"] for r in result] == ["expired", "cancelled", "cancelled"]
    assert store.cancel_many(selected) == result


@pytest.mark.parametrize("problem", ["missing", "digest", "event", "clock"])
def test_any_invalid_member_rolls_back_whole_batch(store, problem):
    records = prepare(store)
    selected = [selection(r) for r in records]
    if problem == "missing":
        selected[-1]["request_id"] = "missing"
    elif problem == "digest":
        selected[-1]["binding_digest"] = "0" * 64
    elif problem == "event":
        store._connection.execute("DELETE FROM events WHERE request_id='r2'")
        store._connection.commit()
    else:
        # Earlier records can be transitioned before a later record detects a
        # regressed clock; no partial terminal state may escape the transaction.
        store._clock = lambda: NOW + timedelta(seconds=1)
        last = store.prepare({**SPEC, "request_id": "later"})
        selected.append(selection(last))
        store._clock = lambda: NOW
    before = "\n".join(store._connection.iterdump())
    with pytest.raises(IntentError):
        store.cancel_many(selected)
    assert "\n".join(store._connection.iterdump()) == before


@pytest.mark.parametrize(
    "mutate",
    [
        lambda items: [],
        lambda items: tuple(items),
        lambda items: items * 101,
        lambda items: items * 2,
        lambda items: [{**items[0], "binding_digest": "bad"}],
        lambda items: [{**items[0], "extra": True}],
        lambda items: [{k: v for k, v in items[0].items() if k != "binding_digest"}],
    ],
)
def test_bad_selection_fails_without_mutation(store, mutate):
    selected = [selection(prepare(store, 1)[0])]
    before = "\n".join(store._connection.iterdump())
    fail("invalid_request", lambda: store.cancel_many(mutate(selected)))
    assert "\n".join(store._connection.iterdump()) == before


@pytest.mark.parametrize("field", ["owner_id", "profile_id"])
def test_cross_scope_rejected_even_if_both_records_exist(store, field):
    first = store.prepare(SPEC)
    second = store.prepare({**SPEC, field: "other"})
    fail("scope_mismatch", lambda: store.cancel_many([selection(first), selection(second)]))
    assert store.inspect(KEY)["state"] == "draft"


def test_full_bound_and_event_failure(store):
    records = prepare(store, 100)
    store._connection.execute("PRAGMA query_only=ON")
    fail("storage_error", lambda: store.cancel_many([selection(r) for r in records]))
    store._connection.execute("PRAGMA query_only=OFF")
    assert all(
        r["state"] == "cancelled" for r in store.cancel_many([selection(r) for r in records])
    )


def test_reopen_exact_retry(tmp_path):
    path = tmp_path / "intent.sqlite"
    with sqlite3.connect(path) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        selected = [selection(r) for r in prepare(store)]
        expected = store.cancel_many(selected)
    with sqlite3.connect(path) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        assert store.cancel_many(selected) == expected


@pytest.mark.parametrize("stage", ["second_event", "commit"])
def test_partial_writes_and_commit_failure_roll_back(stage):
    class FailSecond(sqlite3.Connection):
        armed = False
        event_count = 0

        def execute(self, sql, parameters=()):
            if self.armed:
                if sql.startswith("INSERT INTO main.events"):
                    self.event_count += 1
                    if stage == "second_event" and self.event_count == 2:
                        raise sqlite3.OperationalError("sensitive synthetic error")
                if stage == "commit" and sql == "COMMIT":
                    raise sqlite3.OperationalError("sensitive synthetic error")
            return super().execute(sql, parameters)

    with sqlite3.connect(":memory:", factory=FailSecond) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        records = prepare(store)
        before = "\n".join(conn.iterdump())
        conn.armed = True
        fail("storage_error", lambda: store.cancel_many([selection(r) for r in records]))
        conn.armed = False
        assert "\n".join(conn.iterdump()) == before


@pytest.mark.parametrize("stage", ["first_event", "before_commit", "after_commit"])
def test_process_crash_never_leaves_half_cancelled(tmp_path, stage):
    import subprocess
    import sys

    path = tmp_path / "crash.sqlite"
    with sqlite3.connect(path) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        prepare(store)
    script = """
import os,sqlite3,sys
from personal_agent.action_intents import ActionIntentStore
from tests.unit.test_action_intents import NOW,KEY
class Crash(sqlite3.Connection):
    armed=False
    def execute(self,sql,parameters=()):
        if self.armed:
            if sys.argv[2]=='first_event' and sql.startswith('INSERT INTO main.events'):
                super().execute(sql,parameters)
                os._exit(23)
            if sql=='COMMIT':
                if sys.argv[2]=='after_commit':
                    super().execute(sql,parameters)
                os._exit(23)
        return super().execute(sql,parameters)
conn=sqlite3.connect(sys.argv[1],factory=Crash)
store=ActionIntentStore(conn,clock=lambda:NOW)
store.initialize()
records=[store.inspect({**KEY,'request_id':f'r{i}'}) for i in range(3)]
requests=[{k:r[k] for k in (*KEY,'binding_digest')} for r in records]
conn.armed=True
store.cancel_many(requests)
"""
    result = subprocess.run([sys.executable, "-c", script, str(path), stage], check=False)
    assert result.returncode == 23
    with sqlite3.connect(path) as conn:
        states = conn.execute("SELECT state FROM intents").fetchall()
        expected = "cancelled" if stage == "after_commit" else "draft"
        assert states == [(expected,)] * 3
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        records = [store.inspect({**KEY, "request_id": f"r{i}"}) for i in range(3)]
        assert all(
            r["state"] == "cancelled" for r in store.cancel_many([selection(r) for r in records])
        )
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 6


def test_overlapping_batches_serialize_without_duplicate_events(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "concurrent.sqlite"
    with sqlite3.connect(path) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        records = prepare(store)
    barrier = Barrier(2)

    def worker(indices):
        with sqlite3.connect(path, timeout=5) as conn:
            store = ActionIntentStore(conn, clock=lambda: NOW)
            store.initialize()
            barrier.wait()
            return store.cancel_many([selection(records[i]) for i in indices])

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(worker, [(0, 1), (1, 2)]))
    assert results[0][1] == results[1][0]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 6
        assert conn.execute("SELECT state FROM intents").fetchall() == [("cancelled",)] * 3
