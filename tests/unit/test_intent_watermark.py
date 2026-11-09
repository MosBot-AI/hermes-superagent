"""Review separates sampled time from committed scoped history."""

import sqlite3
from datetime import timedelta

import pytest
from test_action_intents import KEY, NOW, SPEC

from personal_agent.action_intents import ActionIntentStore

SCOPE = {name: KEY[name] for name in ("owner_id", "profile_id")}


@pytest.mark.parametrize("state", ["cancelled", "expired"])
def test_restart_watermark_preserves_terminal_retry(tmp_path, state):
    path = tmp_path / "intents.db"
    conn = sqlite3.connect(path)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    store.prepare(SPEC)
    terminal_time = NOW + timedelta(minutes=6 if state == "expired" else 2)
    store._clock = lambda: terminal_time
    terminal = store.cancel(KEY, expected_revision=1)
    assert terminal["state"] == state
    conn.close()
    conn = sqlite3.connect(path)
    clock = [NOW + timedelta(seconds=1)]
    store = ActionIntentStore(conn, clock=lambda: clock[0])
    store.initialize()
    assert store.prepare(SPEC) == terminal
    snapshot = store.review_pending(SCOPE)
    assert snapshot["items"] == []
    assert snapshot["observed_at"] == clock[0].isoformat(timespec="microseconds")
    assert snapshot["latest_event_at"] == terminal_time.isoformat(timespec="microseconds")
    assert snapshot["clock_behind_events"] is True
    clock[0] = terminal_time
    assert store.review_pending(SCOPE)["clock_behind_events"] is False
    conn.close()


def test_watermark_includes_expiry_outside_limit_but_not_other_scope():
    conn = sqlite3.connect(":memory:")
    clock = [NOW]
    store = ActionIntentStore(conn, clock=lambda: clock[0])
    store.initialize()
    for number in range(3):
        store.prepare({**SPEC, "request_id": str(number)})
    store.prepare({**SPEC, "request_id": "expired", "expires_at": NOW + timedelta(seconds=1)})
    store.prepare({**SPEC, "profile_id": "other"})
    clock[0] = NOW + timedelta(minutes=3)
    store.cancel({**KEY, "profile_id": "other"}, expected_revision=1)
    clock[0] = NOW + timedelta(minutes=1)
    snapshot = store.review_pending(SCOPE, limit=1)
    assert snapshot["pending_count"] == 3 and snapshot["truncated"]
    assert snapshot["latest_event_at"] == clock[0].isoformat(timespec="microseconds")
    assert snapshot["clock_behind_events"] is False
    conn.close()
