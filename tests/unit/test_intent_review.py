"""Bounded internal review snapshots never authorize any effect."""

import sqlite3
from datetime import timedelta

import pytest
from test_action_intents import KEY, NOW, SPEC, fail
from test_action_intents import store as store

from personal_agent.action_intents import ActionIntentStore

SCOPE = {name: KEY[name] for name in ("owner_id", "profile_id")}


def test_empty_snapshot(store):
    result = store.review_pending(SCOPE)
    assert result == {
        "items": [],
        "pending_count": 0,
        "truncated": False,
        "observed_at": NOW.isoformat(timespec="microseconds"),
    }


@pytest.mark.parametrize(
    "scope,limit",
    [
        ({}, 1),
        ({**SCOPE, "request_id": "x"}, 1),
        ({**SCOPE, "owner_id": ""}, 1),
        ([], 1),
        (SCOPE, True),
        (SCOPE, 0),
        (SCOPE, 101),
        (SCOPE, 1.0),
    ],
)
def test_invalid_review(store, scope, limit):
    fail("invalid_request", lambda: store.review_pending(scope, limit=limit))


def test_order_boundaries_and_scope(store):
    for name, offset in [("z", 60), ("a", 60), ("micro", 60.000001), ("later", 120)]:
        store.prepare({**SPEC, "request_id": name, "expires_at": NOW + timedelta(seconds=offset)})
    store.prepare({**SPEC, "profile_id": "other"})
    result = store.review_pending(SCOPE, limit=2)
    assert [r["request_id"] for r in result["items"]] == ["a", "z"]
    assert result["pending_count"] == 4 and result["truncated"] is True
    assert [r["request_id"] for r in store.review_pending(SCOPE)["items"]] == [
        "a",
        "z",
        "micro",
        "later",
    ]
    assert all("payload" not in r and "target" not in r for r in result["items"])


def test_expiry_reconciles_outside_limit_and_is_terminal(store):
    for n in range(4):
        store.prepare(
            {
                **SPEC,
                "request_id": str(n),
                "expires_at": NOW + timedelta(seconds=10 if n < 3 else 20),
            }
        )
    store.prepare({**SPEC, "profile_id": "other", "expires_at": NOW + timedelta(seconds=10)})
    store._clock = lambda: NOW + timedelta(seconds=10)
    result = store.review_pending(SCOPE, limit=1)
    assert result["pending_count"] == 1 and not result["truncated"]
    assert result["items"][0]["request_id"] == "3"
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 8
    assert store.review_pending(SCOPE) == result
    store._clock = lambda: NOW + timedelta(seconds=1)
    assert store.review_pending(SCOPE)["pending_count"] == 1
    assert (
        store._connection.execute("SELECT state FROM intents WHERE profile_id='other'").fetchone()[
            0
        ]
        == "draft"
    )


def test_cancelled_excluded_and_returned_data_not_live(store):
    store.prepare(SPEC)
    record = store.review_pending(SCOPE)["items"][0]
    record["operation"] = "mutated"
    assert store.inspect(KEY)["operation"] == SPEC["operation"]
    store.cancel(KEY, expected_revision=1)
    assert store.review_pending(SCOPE)["pending_count"] == 0


def test_full_selected_scope_validated_before_expiry(store):
    for name in ["a", "z"]:
        store.prepare({**SPEC, "request_id": name})
    store._connection.execute(
        "UPDATE intents SET binding_digest=? WHERE request_id='z'", ("0" * 64,)
    )
    store._connection.commit()
    store._clock = lambda: SPEC["expires_at"]
    fail("invalid_record", lambda: store.review_pending(SCOPE, limit=1))
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2


def test_event_failure_rolls_back_all_expiry(store, monkeypatch):
    for name in ["a", "b"]:
        store.prepare({**SPEC, "request_id": name})
    original = store._event

    def broken(record, outcome, now):
        original(record, outcome, now)
        if record["request_id"] == "b":
            raise sqlite3.OperationalError("synthetic-private-error")

    monkeypatch.setattr(store, "_event", broken)
    store._clock = lambda: SPEC["expires_at"]
    fail("storage_error", lambda: store.review_pending(SCOPE))
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
    assert set(r[0] for r in store._connection.execute("SELECT state FROM intents")) == {"draft"}


def test_clock_once_after_lock(store):
    store.prepare(SPEC)
    calls = []

    def clock():
        calls.append(store._connection.in_transaction)
        return NOW

    store._clock = clock
    store.review_pending(SCOPE)
    assert calls == [True]


def test_restart_recovers_pending_without_known_request_ids(tmp_path):
    path = tmp_path / "intent.sqlite"
    with sqlite3.connect(path) as connection:
        original = ActionIntentStore(connection, clock=lambda: NOW)
        original.initialize()
        record = original.prepare(SPEC)
    with sqlite3.connect(path) as connection:
        restarted = ActionIntentStore(connection, clock=lambda: NOW)
        restarted.initialize()
        assert restarted.review_pending(SCOPE)["items"] == [record]


def test_clock_regression_and_corruption_outside_output_fail_closed(store):
    store.prepare(SPEC)
    store._clock = lambda: NOW - timedelta(seconds=1)
    fail("clock_regressed", lambda: store.review_pending(SCOPE))


def test_expiry_write_commit_failure_has_no_partial_result(tmp_path):
    class Connection(sqlite3.Connection):
        reject = False

        def execute(self, sql, *args, **kwargs):
            if sql == "COMMIT" and self.reject:
                raise sqlite3.OperationalError("private commit error")
            return super().execute(sql, *args, **kwargs)

    connection = sqlite3.connect(tmp_path / "commit.sqlite", factory=Connection)
    try:
        ledger = ActionIntentStore(connection, clock=lambda: NOW)
        ledger.initialize()
        ledger.prepare(SPEC)
        ledger._clock = lambda: SPEC["expires_at"]
        connection.reject = True
        fail("storage_error", lambda: ledger.review_pending(SCOPE))
        assert connection.execute("SELECT state FROM intents").fetchone()[0] == "draft"
    finally:
        connection.close()


def test_concurrent_committed_cancel_precedes_review(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    path = tmp_path / "concurrent.sqlite"
    connection = sqlite3.connect(path)
    ledger = ActionIntentStore(connection, clock=lambda: NOW)
    ledger.initialize()
    ledger.prepare(SPEC)
    connection.execute("BEGIN IMMEDIATE")
    started = Event()

    def review():
        with sqlite3.connect(path, timeout=5) as other:
            observer = ActionIntentStore(other, clock=lambda: NOW)
            # Initialization also obtains the same lock.
            started.set()
            observer.initialize()
            return observer.review_pending(SCOPE)

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(review)
            assert started.wait(2)
            record = ledger._record(KEY)
            ledger._terminal(record, "cancelled", NOW)
            connection.commit()
            assert future.result(timeout=5)["items"] == []
    finally:
        connection.close()
