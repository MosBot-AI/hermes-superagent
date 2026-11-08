"""Exact internal replacement, no approval or execution authority."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from test_action_intents import KEY, NOW, SPEC, fail

from personal_agent import action_intents as api
from personal_agent.action_intents import ActionIntentStore

NEW = {**SPEC, "request_id": "replacement", "payload": b"changed"}


def setup(path=":memory:", connection=sqlite3.Connection):
    conn = sqlite3.connect(path, factory=connection, isolation_level=None)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    old = store.prepare(SPEC)
    selected = {**KEY, "binding_digest": old["binding_digest"]}
    return conn, store, selected


def test_replace_and_restart_retry(tmp_path):
    path = tmp_path / "intents.db"
    conn, store, selected = setup(path)
    result = store.replace(selected, NEW)
    assert result["previous"]["state"] == "cancelled"
    assert result["replacement"]["state"] == "draft"
    assert store.prepare(SPEC)["state"] == "cancelled"
    assert store.replace(selected, NEW) == result
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 3
    conn.close()
    conn = sqlite3.connect(path)
    restarted = ActionIntentStore(conn, clock=lambda: NOW)
    restarted.initialize()
    assert restarted.replace(selected, NEW) == result
    assert conn.execute("SELECT count(*) FROM replacements").fetchone()[0] == 1
    assert b"changed" not in path.read_bytes()
    conn.close()


@pytest.mark.parametrize(
    "change,code",
    [
        ({"owner_id": "other"}, "scope_mismatch"),
        ({"profile_id": "other"}, "scope_mismatch"),
        ({"request_id": SPEC["request_id"]}, "request_conflict"),
        ({"expires_at": NOW}, "invalid_expiry"),
        ({"expires_at": NOW + timedelta(days=2)}, "invalid_expiry"),
    ],
)
def test_invalid_new_leaves_old_live(change, code):
    conn, store, selected = setup()
    fail(code, lambda: store.replace(selected, {**NEW, **change}))
    assert store.inspect(KEY)["state"] == "draft"
    assert conn.execute("SELECT count(*) FROM intents").fetchone()[0] == 1


@pytest.mark.parametrize(
    "selected",
    [None, {}, {**KEY, "binding_digest": "bad"}, {**KEY, "binding_digest": "0" * 64, "extra": 1}],
)
def test_invalid_selection(selected):
    _, store, _ = setup()
    fail("invalid_request", lambda: store.replace(selected, NEW))


def test_missing_or_mismatched_old():
    _, store, selected = setup()
    fail("not_found", lambda: store.replace({**selected, "request_id": "missing"}, NEW))
    fail("request_conflict", lambda: store.replace({**selected, "binding_digest": "0" * 64}, NEW))


def test_no_adoption_of_existing_target_or_cancelled_old():
    _, store, selected = setup()
    store.prepare(NEW)
    fail("request_conflict", lambda: store.replace(selected, NEW))
    assert store.inspect(KEY)["state"] == "draft"
    store.cancel(KEY, expected_revision=1)
    fail("not_pending", lambda: store.replace(selected, NEW))


def test_expired_and_clock_regression():
    _, store, selected = setup()
    store._clock = lambda: NOW - timedelta(seconds=1)
    fail("clock_regressed", lambda: store.replace(selected, NEW))
    store._clock = lambda: NOW + timedelta(minutes=5)
    fail(
        "not_pending",
        lambda: store.replace(selected, {**NEW, "expires_at": NOW + timedelta(hours=1)}),
    )
    assert store.inspect(KEY)["state"] == "expired"


def test_retry_preserves_replacement_terminal_state():
    conn, store, selected = setup()
    store.replace(selected, NEW)
    new_key = {name: NEW[name] for name in KEY}
    store.cancel(new_key, expected_revision=1)
    assert store.replace(selected, NEW)["replacement"]["state"] == "cancelled"
    fail("request_conflict", lambda: store.replace(selected, {**NEW, "payload": b"another"}))
    fail("request_conflict", lambda: store.replace(selected, {**NEW, "request_id": "another"}))
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 4


def test_chain_is_not_reactivated():
    _, store, selected = setup()
    middle = store.replace(selected, NEW)["replacement"]
    choice = {**{name: NEW[name] for name in KEY}, "binding_digest": middle["binding_digest"]}
    store.replace(choice, {**NEW, "request_id": "third"})
    assert store.replace(selected, NEW)["replacement"]["state"] == "cancelled"


def test_capacity_rolls_back(monkeypatch):
    _, store, selected = setup()
    monkeypatch.setattr(api, "MAX_INTENTS", 1)
    fail("capacity_exhausted", lambda: store.replace(selected, NEW))
    assert store.inspect(KEY)["state"] == "draft"


@pytest.mark.parametrize(
    "point",
    [
        "INSERT INTO main.intents",
        "INSERT INTO main.events",
        "INSERT INTO main.replacements",
        "COMMIT",
    ],
)
def test_failure_rolls_back(point):
    class Failing(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and sql.startswith(point):
                raise sqlite3.OperationalError("secret")
            return super().execute(sql, *args)

    conn, store, selected = setup(connection=Failing)
    conn.armed = True
    fail("storage_error", lambda: store.replace(selected, NEW))
    conn.armed = False
    assert store.inspect(KEY)["state"] == "draft"
    assert conn.execute("SELECT count(*) FROM intents").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM replacements").fetchone()[0] == 0


def test_exact_v1_migration(tmp_path):
    conn, store, selected = setup(tmp_path / "old.db")
    conn.execute("DROP TABLE replacements")
    conn.execute("PRAGMA user_version=1")
    store.initialize()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert store.replace(selected, NEW)["replacement"]["state"] == "draft"


def test_v1_unknown_schema_refused():
    conn, store, _ = setup()
    conn.execute("DROP TABLE replacements")
    conn.execute("PRAGMA user_version=1")
    conn.execute("CREATE TABLE surprise(x)")
    fail("unsupported_schema", store.initialize)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1


def test_competing_replacements_serialize(tmp_path):
    path = tmp_path / "race.db"
    conn, _, selected = setup(path)
    conn.close()
    barrier = Barrier(2)

    def run(identifier):
        c = sqlite3.connect(path)
        s = ActionIntentStore(c, clock=lambda: NOW)
        s.initialize()
        barrier.wait()
        try:
            return s.replace(selected, {**NEW, "request_id": identifier})["replacement"]["state"]
        except api.IntentError as error:
            return error.code
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ["a", "b"])) == ["draft", "request_conflict"]


@pytest.mark.parametrize("point", ["middle", "before_commit", "after_commit"])
def test_process_exit_atomicity(tmp_path, point):
    path = tmp_path / "crash.db"
    conn, _, selected = setup(path)
    conn.close()
    script = """
import os, sqlite3, sys
from datetime import UTC, datetime, timedelta
from personal_agent.action_intents import ActionIntentStore
now=datetime(2026,11,8,12,tzinfo=UTC)
class Crash(sqlite3.Connection):
    armed=False
    def execute(self, sql, *args):
        if self.armed and sys.argv[2]=='before_commit' and sql=='COMMIT': os._exit(47)
        result=super().execute(sql,*args)
        middle = sys.argv[2]=='middle' and sql.startswith('INSERT INTO main.intents')
        committed = sys.argv[2]=='after_commit' and sql=='COMMIT'
        if self.armed and (middle or committed): os._exit(47)
        return result
c=sqlite3.connect(sys.argv[1],factory=Crash)
s=ActionIntentStore(c,clock=lambda: now); s.initialize()
k={'owner_id':'owner','profile_id':'profile','request_id':'request'}
r=s.inspect(k)
n={**k,'request_id':'replacement','operation':'example.send','policy_revision':7,'epoch':2,'resource_revision':3,'expires_at':now+timedelta(minutes=5),'target':b'synthetic-recipient-not-real','payload':b'changed'}
c.armed=True
s.replace({**k,'binding_digest':r['binding_digest']},n)
"""
    result = subprocess.run([sys.executable, "-c", script, str(path), point], check=False)
    assert result.returncode == 47
    conn = sqlite3.connect(path)
    store = ActionIntentStore(conn, clock=lambda: NOW)
    store.initialize()
    assert store.inspect(KEY)["state"] == ("cancelled" if point == "after_commit" else "draft")
    assert store.replace(selected, NEW)["replacement"]["state"] == "draft"
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 3


@pytest.mark.parametrize(
    "field,value", [("recorded_at", "bad"), ("new_digest", "0" * 64), ("old_digest", "0" * 64)]
)
def test_corrupt_link_fails_closed(field, value):
    conn, store, selected = setup()
    store.replace(selected, NEW)
    conn.execute(f"UPDATE replacements SET {field}=?", (value,))
    with pytest.raises(api.IntentError):
        store.replace(selected, NEW)
    assert conn.execute("SELECT count(*) FROM intents").fetchone()[0] == 2


def test_retry_after_expiry_reconciles_new_without_resurrection():
    conn, store, selected = setup()
    store.replace(selected, NEW)
    store._clock = lambda: NOW + timedelta(minutes=5)
    assert store.replace(selected, NEW)["replacement"]["state"] == "expired"
    assert store.replace(selected, NEW)["replacement"]["state"] == "expired"
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 4


def test_migration_commit_failure_is_atomic():
    class Failing(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and sql == "COMMIT":
                raise sqlite3.OperationalError("synthetic")
            return super().execute(sql, *args)

    conn, store, _ = setup(connection=Failing)
    conn.execute("DROP TABLE replacements")
    conn.execute("PRAGMA user_version=1")
    conn.armed = True
    fail("storage_error", store.initialize)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='replacements'").fetchall() == []


def test_replacement_races_cancellation(tmp_path):
    path = tmp_path / "cancel-race.db"
    conn, _, selected = setup(path)
    conn.close()
    barrier = Barrier(2)

    def run(replace):
        c = sqlite3.connect(path)
        s = ActionIntentStore(c, clock=lambda: NOW)
        s.initialize()
        barrier.wait()
        try:
            if replace:
                return s.replace(selected, NEW)["replacement"]["state"]
            return s.cancel(KEY, expected_revision=1)["state"]
        except api.IntentError as error:
            return error.code
        finally:
            c.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(run, [True, False]))
    assert result in (["draft", "cancelled"], ["not_pending", "cancelled"])
    c = sqlite3.connect(path)
    s = ActionIntentStore(c, clock=lambda: NOW)
    s.initialize()
    assert s.inspect(KEY)["state"] == "cancelled"
    assert c.execute("SELECT count(*) FROM replacements").fetchone()[0] == (result[0] == "draft")
    c.close()
