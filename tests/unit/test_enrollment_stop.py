"""Terminal private-store stop, including actual transaction races and restart."""

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event

import pytest
from test_enrollment import CAS, CREATE, KEY
from test_read_admission_audit import V1_SCHEMA, V2_AUDIT_SCHEMA

from personal_agent.enrollment import EnrollmentError, EnrollmentStore

ROOT = Path(__file__).resolve().parents[2]
SCOPE = {"owner_id": KEY["owner_id"], "profile_id": KEY["profile_id"]}


def current(store, key=KEY, callback=lambda _: True):
    return store.with_current_record(
        key,
        expected_revision=1,
        expected_enrollment_revision=1,
        expected_epoch=0,
        operation=callback,
    )


def opened(db):
    store = EnrollmentStore(db)
    store.initialize()
    return store


def test_stop_is_idempotent_and_exact_across_current_and_future_enrollments():
    with closing(sqlite3.connect(":memory:")) as db:
        store = opened(db)
        store.run("create", CREATE)
        assert not store.admissions_stopped(SCOPE)
        assert current(store)
        assert store.stop_admissions(SCOPE) is True
        assert store.stop_admissions(SCOPE) is False
        for alternate in (
            {"enrollment_id": "second"},
            {"owner_id": "other-owner"},
            {"profile_id": "other-profile"},
        ):
            store.run("create", {**CREATE, **alternate})
        for blocked in (KEY, {**KEY, "enrollment_id": "second"}):
            with pytest.raises(EnrollmentError, match="admissions_stopped"):
                current(store, blocked, lambda _: pytest.fail("Stopped admission was entered"))
        assert current(store, {**KEY, "owner_id": "other-owner"})
        assert current(store, {**KEY, "profile_id": "other-profile"})
        assert store.run("get", KEY)["state"] == "pending"
        assert store.run("pause", CAS)["state"] == "paused"
        assert store.run("resume", {**CAS, "expected_revision": 2})["state"] == "pending"
        with pytest.raises(EnrollmentError, match="admissions_stopped"):
            store.with_current_record(
                KEY,
                expected_revision=3,
                expected_enrollment_revision=1,
                expected_epoch=2,
                operation=lambda _: pytest.fail("Record resume cleared a scope stop"),
            )
        assert store.run("revoke", {**CAS, "expected_revision": 3})["state"] == "revoked"
        assert [item["operation"] for item in store.policy_history(KEY)["items"]] == [
            "create",
            "pause",
            "resume",
            "revoke",
        ]
        assert db.execute("SELECT * FROM emergency_stops").fetchall() == [
            (SCOPE["owner_id"], SCOPE["profile_id"])
        ]


@pytest.mark.parametrize(
    "scope", [{}, KEY, {**SCOPE, "owner_id": True}, {**SCOPE, "profile_id": ""}]
)
def test_stop_validates_exact_scope_before_opening_transaction(scope):
    with closing(sqlite3.connect(":memory:")) as db:
        store = opened(db)
        statements = []
        db.set_trace_callback(statements.append)
        for method in (store.stop_admissions, store.admissions_stopped):
            with pytest.raises(EnrollmentError, match="invalid_request"):
                method(scope)
        assert statements == []
        with pytest.raises(EnrollmentError, match="invalid_request"):
            store.run("stop_admissions", SCOPE)


def test_stop_commit_error_rolls_back_and_retry_can_apply():
    with closing(sqlite3.connect(":memory:")) as db:
        store = opened(db)
        store.run("create", CREATE)
        db.set_authorizer(
            lambda action, value, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_TRANSACTION and value == "COMMIT"
                else sqlite3.SQLITE_OK
            )
        )
        with pytest.raises(EnrollmentError, match="storage_error"):
            store.stop_admissions(SCOPE)
        db.set_authorizer(None)
        assert not store.admissions_stopped(SCOPE)
        assert current(store)
        assert store.stop_admissions(SCOPE)


def test_stop_transaction_already_in_progress_denies_waiting_reader(tmp_path):
    path = tmp_path / "policy.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        opened(db).run("create", CREATE)
    writer_ready, reader_ready, reader_waiting = Event(), Event(), Event()

    class WaitAtStopCommit(sqlite3.Connection):
        armed = False

        def execute(self, sql, parameters=(), /):
            if self.armed and sql == "COMMIT":
                writer_ready.set()
                assert reader_waiting.wait(5)
            return super().execute(sql, parameters)

    def writer():
        with closing(sqlite3.connect(path, factory=WaitAtStopCommit)) as db:
            store = opened(db)
            assert reader_ready.wait(5)
            db.armed = True
            return store.stop_admissions(SCOPE)

    def reader():
        with closing(sqlite3.connect(path)) as db:
            store = opened(db)
            reader_ready.set()
            assert writer_ready.wait(5)
            db.set_trace_callback(
                lambda statement: reader_waiting.set() if statement == "BEGIN IMMEDIATE" else None
            )
            with pytest.raises(EnrollmentError, match="admissions_stopped"):
                current(store, callback=lambda _: pytest.fail("Waiting reader missed stop"))
            assert store.read_admission_history(KEY)["items"] == []

    with ThreadPoolExecutor(max_workers=2) as pool:
        stop = pool.submit(writer)
        read = pool.submit(reader)
        assert stop.result(timeout=12) is True
        read.result(timeout=12)


CHILD = """
import json
import os
import sqlite3
import sys

from personal_agent.enrollment import EnrollmentStore

class CommitFault(sqlite3.Connection):
    armed = False
    def execute(self, sql, parameters=(), /):
        if self.armed and sql == "COMMIT":
            if sys.argv[2] == "after_commit":
                super().execute(sql, parameters)
            os._exit(71)
        return super().execute(sql, parameters)

db = sqlite3.connect(sys.argv[1], factory=CommitFault)
store = EnrollmentStore(db)
store.initialize()
db.armed = True
store.stop_admissions(json.loads(sys.argv[3]))
raise AssertionError("Did not reach the stop commit")
"""


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_stop_is_recoverable_after_abrupt_exit(tmp_path, phase):
    import json

    path = tmp_path / "policy.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        opened(db).run("create", CREATE)
    child = subprocess.run(
        [sys.executable, "-c", CHILD, str(path), phase, json.dumps(SCOPE)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    )
    assert child.returncode == 71, child.stderr
    with closing(sqlite3.connect(path)) as db:
        store = opened(db)
        committed = phase == "after_commit"
        assert store.admissions_stopped(SCOPE) is committed
        if not committed:
            assert current(store)
        assert store.stop_admissions(SCOPE) is (not committed)
        with pytest.raises(EnrollmentError, match="admissions_stopped"):
            current(store)
        assert store.read_admission_history(KEY)["items"] == []
        assert db.execute("SELECT count(*) FROM emergency_stops").fetchone() == (1,)
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_exact_v3_upgrade_preserves_paused_state_and_both_audit_tables():
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute(V1_SCHEMA[0].replace("'pending','revoked'", "'pending','paused','revoked'"))
        db.execute(
            V1_SCHEMA[1].replace("'set_policy','revoke'", "'set_policy','pause','resume','revoke'")
        )
        db.execute(V2_AUDIT_SCHEMA)
        db.execute("PRAGMA application_id=1346454862")
        db.execute("PRAGMA user_version=3")
        db.execute(
            "INSERT INTO enrollments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "owner",
                "profile",
                "enrollment",
                "telegram",
                "bot",
                "actor",
                "paused",
                1,
                2,
                1,
                "personal.tasks.read",
                "exact_tasks",
                '["task-one"]',
                "tasks.summary",
            ),
        )
        db.execute("INSERT INTO events VALUES ('owner','profile','enrollment',0,'create',1,1)")
        db.execute("INSERT INTO events VALUES ('owner','profile','enrollment',1,'pause',1,2)")
        db.execute(
            "INSERT INTO read_admissions VALUES "
            "(14,'owner','profile','enrollment',1,1,0,'2026-01-01T00:00:00+00:00',1,'snapshot_prepared')"
        )
        db.commit()
        store = opened(db)
        assert db.execute("PRAGMA user_version").fetchone() == (4,)
        assert store.run("get", KEY)["state"] == "paused"
        assert [row["operation"] for row in store.policy_history(KEY)["items"]] == [
            "create",
            "pause",
        ]
        assert [row["sequence"] for row in store.read_admission_history(KEY)["items"]] == [14]
        assert not store.admissions_stopped(SCOPE)
        assert store.stop_admissions(SCOPE)


def test_hostile_v3_stop_table_is_rejected_before_migration():
    with closing(sqlite3.connect(":memory:")) as db:
        opened(db)
        db.execute("PRAGMA user_version=3")
        before = list(db.iterdump())
        with pytest.raises(EnrollmentError, match="unsupported_schema"):
            opened(db)
        assert list(db.iterdump()) == before
