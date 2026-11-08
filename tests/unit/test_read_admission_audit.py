"""Synthetic read admission audit, not authenticated ingress or delivery proof."""

import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from test_enrollment import CAS, CREATE
from test_read_admission import (
    KEY,
    NOW,
    REQUEST,
    SUMMARY,
    SyntheticHost,
    denied,
    read,
)
from test_read_admission import setup as setup

from personal_agent.enrollment import EnrollmentError, EnrollmentStore, PreparedRead
from personal_agent.read_admission import ReadAdmissionService

# Frozen schema from main before this change; not generated from current constants.
V1_SCHEMA = (
    """CREATE TABLE enrollments (
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL,
        enrollment_id TEXT NOT NULL, transport_id TEXT NOT NULL,
        transport_receiver_id TEXT NOT NULL, principal_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','revoked')),
        enrollment_revision INTEGER NOT NULL CHECK(enrollment_revision >= 1),
        policy_revision INTEGER NOT NULL CHECK(policy_revision >= 1),
        epoch INTEGER NOT NULL CHECK(epoch >= 0),
        operation TEXT NOT NULL, target TEXT NOT NULL,
        resource_ids TEXT NOT NULL, data_scope TEXT NOT NULL,
        PRIMARY KEY(owner_id, profile_id, enrollment_id))""",
    """CREATE TABLE events (
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL, enrollment_id TEXT NOT NULL,
        epoch INTEGER NOT NULL, operation TEXT NOT NULL
        CHECK(operation IN ('create','set_policy','revoke')),
        enrollment_revision INTEGER NOT NULL, policy_revision INTEGER NOT NULL,
        PRIMARY KEY(owner_id, profile_id, enrollment_id, epoch))""",
)


def legacy(connection):
    for statement in V1_SCHEMA:
        connection.execute(statement)
    connection.execute("PRAGMA application_id=1346454862")
    connection.execute("PRAGMA user_version=1")
    connection.execute(
        "INSERT INTO enrollments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "owner",
            "profile",
            "enrollment",
            "telegram",
            "bot",
            "actor",
            "revoked",
            2,
            1,
            1,
            "personal.tasks.read",
            "exact_tasks",
            '["task-one"]',
            "tasks.summary",
        ),
    )
    connection.executemany(
        "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
        [
            ("owner", "profile", "enrollment", 0, "create", 1, 1),
            ("owner", "profile", "enrollment", 1, "revoke", 2, 1),
        ],
    )
    connection.commit()


def audit(store):
    return store.read_admission_history(KEY)["items"]


def test_success_metadata_only_and_fresh_confirmation_not_replay(setup):
    store, host, source, service, _ = setup
    assert read(setup) == (SUMMARY,)
    item = audit(store)[0]
    assert item == {
        "sequence": 1,
        **KEY,
        "enrollment_revision": 1,
        "policy_revision": 1,
        "epoch": 0,
        "prepared_at": NOW.isoformat(),
        "resource_count": 1,
        "outcome": "snapshot_prepared",
    }
    assert not any(
        sensitive in repr(item)
        for sensitive in (
            "Small task",
            "2026-12-31",
            "telegram",
            "actor",
            "bot",
            "session",
            "grant",
        )
    )
    assert denied(setup) == "admission_failed"
    assert len(audit(store)) == 1
    fresh = SyntheticHost([])
    service = ReadAdmissionService(
        store, host_authority=fresh, resource_source=source, enabled=True
    )
    assert service.read(KEY, REQUEST, live_handle=fresh.handle) == (SUMMARY,)
    assert [item["sequence"] for item in audit(store)] == [1, 2]
    assert store.run("get", KEY)["state"] == "pending"


@pytest.mark.parametrize("phase", ["insert", "commit"])
def test_failed_audit_or_commit_returns_nothing_and_rolls_back(setup, phase):
    store, _, _, _, _ = setup
    connection = store._connection
    connection.set_authorizer(
        lambda action, name, *rest: (
            sqlite3.SQLITE_DENY
            if (
                (
                    phase == "insert"
                    and action == sqlite3.SQLITE_INSERT
                    and name == "read_admissions"
                )
                or (phase == "commit" and action == sqlite3.SQLITE_TRANSACTION and name == "COMMIT")
            )
            else sqlite3.SQLITE_OK
        )
    )
    assert denied(setup) == "policy_denied"
    connection.set_authorizer(None)
    assert audit(store) == []
    assert not connection.in_transaction
    assert len(connection.execute("SELECT * FROM events").fetchall()) == 1


@pytest.mark.parametrize(
    "failure", ["snapshot_exit", "host_exit", "malformed", "expired", "revoke"]
)
def test_failures_do_not_claim_data_return_or_delivery(setup, failure):
    store, host, source, _, _ = setup
    if failure == "snapshot_exit":
        source.fail_exit = True
    elif failure == "host_exit":
        host.fail_exit = True
    elif failure == "malformed":
        source.rows = (replace(SUMMARY, title=""),)
    elif failure == "expired":
        host.now += timedelta(days=1)
    else:
        store.run("revoke", CAS)
    denied(setup)
    # A host-exit failure is after SQLite commit. The event deliberately does
    # not mean that data returned or reached a user.
    assert len(audit(store)) == (1 if failure == "host_exit" else 0)


def test_final_clock_sample_after_snapshot_exit_is_recorded(setup):
    store, host, source, _, _ = setup
    old = source.open_snapshot

    @contextmanager
    def snapshot(*args):
        with old(*args) as value:
            yield value
        host.now += timedelta(seconds=5)

    source.open_snapshot = snapshot
    assert read(setup) == (SUMMARY,)
    assert audit(store)[0]["prepared_at"] == (NOW + timedelta(seconds=5)).isoformat()


def test_snapshot_exit_invalidation_prevents_audit_and_return(setup):
    store, host, source, _, _ = setup
    old = source.open_snapshot

    @contextmanager
    def snapshot(*args):
        with old(*args) as value:
            yield value
        host.live = False

    source.open_snapshot = snapshot
    denied(setup)
    assert audit(store) == []


def test_capacity_refuses_before_resource_read_without_evicting(setup, monkeypatch):
    store, host, source, service, events = setup
    monkeypatch.setattr("personal_agent.enrollment.MAX_READ_AUDITS", 1)
    read(setup)
    fresh = SyntheticHost(events)
    service = ReadAdmissionService(
        store, host_authority=fresh, resource_source=source, enabled=True
    )
    with pytest.raises(Exception, match="policy_denied"):
        service.read(KEY, REQUEST, live_handle=fresh.handle)
    assert events.count("read") == 1
    assert len(audit(store)) == 1
    assert fresh.used  # The fresh confirmation was consumed, not reusable.


def test_sequence_exhaustion_refuses_before_read(setup):
    store, _, source, _, events = setup
    read(setup)
    store._connection.execute("UPDATE read_admissions SET sequence=?", (2**63 - 1,))
    store._connection.commit()
    fresh = SyntheticHost(events)
    service = ReadAdmissionService(
        store, host_authority=fresh, resource_source=source, enabled=True
    )
    with pytest.raises(Exception, match="policy_denied"):
        service.read(KEY, REQUEST, live_handle=fresh.handle)
    assert events.count("read") == 1
    assert audit(store)[0]["sequence"] == 2**63 - 1


def test_bounded_scope_history_and_revoked_history(setup):
    store, _, source, _, _ = setup
    for _ in range(3):
        fresh = SyntheticHost([])
        ReadAdmissionService(
            store, host_authority=fresh, resource_source=source, enabled=True
        ).read(KEY, REQUEST, live_handle=fresh.handle)
    store.run("create", {**CREATE, "owner_id": "other"})
    assert store.read_admission_history({**KEY, "owner_id": "other"})["items"] == []
    first = store.read_admission_history(KEY, limit=2)
    assert first["has_more"] is True and first["next_after_sequence"] == 2
    last = store.read_admission_history(KEY, after_sequence=2, limit=2)
    assert last["has_more"] is False and last["next_after_sequence"] == 3
    store.run("revoke", CAS)
    assert len(audit(store)) == 3
    with pytest.raises(EnrollmentError, match="invalid_request"):
        store.run("read_admission_history", KEY)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"after_sequence": -1},
        {"after_sequence": True},
        {"after_sequence": 2**63},
    ],
)
def test_invalid_history_bounds(setup, kwargs):
    store, *_ = setup
    with pytest.raises(EnrollmentError, match="invalid_request"):
        store.read_admission_history(KEY, **kwargs)


@pytest.mark.parametrize(
    "value",
    [
        None,
        (SUMMARY,),
        PreparedRead((SUMMARY,), NOW, True),
        PreparedRead((SUMMARY,), NOW, 0),
        PreparedRead((SUMMARY,), NOW, 33),
        PreparedRead((SUMMARY,), datetime(2026, 1, 1), 1),
        PreparedRead((SUMMARY,), NOW.replace(fold=1), 1),
    ],
)
def test_invalid_trusted_callback_metadata_fails_without_audit(setup, value):
    store, *_ = setup
    with pytest.raises(EnrollmentError, match="invalid_read_audit"):
        store.with_audited_read(
            KEY,
            expected_revision=1,
            expected_enrollment_revision=1,
            expected_epoch=0,
            operation=lambda record: value,
        )
    assert audit(store) == []


def test_exact_v1_upgrade_preserves_rows_and_admin_events(tmp_path):
    path = tmp_path / "enrollment.db"
    with sqlite3.connect(path) as connection:
        legacy(connection)
        before = (
            connection.execute("SELECT * FROM enrollments").fetchall(),
            connection.execute("SELECT * FROM events").fetchall(),
        )
        store = EnrollmentStore(connection)
        store.initialize()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert before == (
            connection.execute("SELECT * FROM enrollments").fetchall(),
            connection.execute("SELECT * FROM events").fetchall(),
        )
        assert audit(store) == []
        assert store.run("get", KEY)["state"] == "revoked"
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        assert audit(store) == []


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE surprise (x TEXT)",
        "CREATE INDEX surprise ON events(epoch)",
        "CREATE TEMP TABLE read_admissions (x TEXT)",
        "PRAGMA user_version=99",
        "PRAGMA application_id=123",
    ],
)
def test_migration_refuses_non_exact_predecessor_without_change(sql):
    with sqlite3.connect(":memory:") as connection:
        legacy(connection)
        connection.execute(sql)
        before = list(connection.iterdump())
        with pytest.raises(EnrollmentError):
            EnrollmentStore(connection).initialize()
        assert list(connection.iterdump()) == before
        assert not connection.in_transaction


@pytest.mark.parametrize("failure", ["create_table", "version", "commit"])
def test_failed_upgrade_is_atomic(failure):
    with sqlite3.connect(":memory:") as connection:
        legacy(connection)
        before = list(connection.iterdump())
        connection.set_authorizer(
            lambda action, name, arg, *rest: (
                sqlite3.SQLITE_DENY
                if (
                    (
                        failure == "create_table"
                        and action == sqlite3.SQLITE_CREATE_TABLE
                        and name == "read_admissions"
                    )
                    or (
                        failure == "version"
                        and action == sqlite3.SQLITE_PRAGMA
                        and name == "user_version"
                        and arg == "2"
                    )
                    or (
                        failure == "commit"
                        and action == sqlite3.SQLITE_TRANSACTION
                        and name == "COMMIT"
                    )
                )
                else sqlite3.SQLITE_OK
            )
        )
        store = EnrollmentStore(connection)
        with pytest.raises(EnrollmentError, match="storage_error"):
            store.initialize()
        connection.set_authorizer(None)
        assert list(connection.iterdump()) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not connection.in_transaction
        with pytest.raises(EnrollmentError, match="not_initialized"):
            store.read_admission_history(KEY)


def test_audit_persists_on_reopen_and_is_not_authority(tmp_path):
    path = tmp_path / "enrollment.db"
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        store.run("create", CREATE)
        # Internal low-level API uses synthetic metadata and grants no authority.
        assert (
            store.with_audited_read(
                KEY,
                expected_revision=1,
                expected_enrollment_revision=1,
                expected_epoch=0,
                operation=lambda record: PreparedRead("detached", NOW, 1),
            )
            == "detached"
        )
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        assert len(audit(store)) == 1
        with pytest.raises(Exception, match="unavailable"):
            ReadAdmissionService(store, enabled=True).read(
                KEY, REQUEST, live_handle=audit(store)[0]
            )


@pytest.mark.parametrize(
    "field,value",
    [
        ("prepared_at", "private-raw-payload"),
        ("prepared_at", "2026-01-01"),
        ("policy_revision", 0),
        ("epoch", -1),
    ],
)
def test_malformed_audit_rows_do_not_escape_internal_history(setup, field, value):
    store, *_ = setup
    read(setup)
    store._connection.execute(f"UPDATE read_admissions SET {field}=?", (value,))
    store._connection.commit()
    with pytest.raises(EnrollmentError, match="invalid_read_audit") as error:
        store.read_admission_history(KEY)
    assert "private-raw-payload" not in str(error.value)


def test_fresh_and_upgraded_schema_are_identical():
    with sqlite3.connect(":memory:") as fresh, sqlite3.connect(":memory:") as old:
        EnrollmentStore(fresh).initialize()
        legacy(old)
        EnrollmentStore(old).initialize()
        query = "SELECT name,sql FROM sqlite_master ORDER BY name"
        assert fresh.execute(query).fetchall() == old.execute(query).fetchall()


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_process_exit_around_commit_preserves_truthful_prepared_event(tmp_path, phase):
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path / "crash.db"
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        store.run("create", CREATE)
    child = r"""
import os, sqlite3, sys
from datetime import UTC, datetime
from personal_agent.enrollment import EnrollmentStore, PreparedRead
class Connection(sqlite3.Connection):
    armed = False
    def execute(self, sql, parameters=()):
        if self.armed and sql == "COMMIT" and sys.argv[2] == "before_commit":
            os._exit(71)
        result = super().execute(sql, parameters)
        if self.armed and sql == "COMMIT" and sys.argv[2] == "after_commit":
            os._exit(72)
        return result
connection = sqlite3.connect(sys.argv[1], factory=Connection)
store = EnrollmentStore(connection)
store.initialize()
connection.armed = True
store.with_audited_read(
    {"owner_id":"owner","profile_id":"profile","enrollment_id":"enrollment"},
    expected_revision=1, expected_enrollment_revision=1, expected_epoch=0,
    operation=lambda record: PreparedRead("synthetic payload", datetime(2026,1,1,tzinfo=UTC), 1),
)
raise AssertionError("No successful return is expected")
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(path), phase],
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(Path(__file__).parents[2])},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == (71 if phase == "before_commit" else 72), result.stderr
    assert not result.stdout
    with sqlite3.connect(path) as connection:
        store = EnrollmentStore(connection)
        store.initialize()
        assert len(audit(store)) == (0 if phase == "before_commit" else 1)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
