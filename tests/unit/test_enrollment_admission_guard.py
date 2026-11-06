"""Actual SQLite policy/revoke ordering, not host identity authentication."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from test_enrollment import CAS, CREATE, KEY, SCOPE

from personal_agent.enrollment import EnrollmentError, EnrollmentStore


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    instance = EnrollmentStore(connection)
    instance.initialize()
    instance.run("create", CREATE)
    yield instance
    connection.close()


def guarded(store, callback, **changes):
    arguments = {
        "expected_revision": 1,
        "expected_enrollment_revision": 1,
        "expected_epoch": 0,
        "operation": callback,
        **changes,
    }
    return store.with_current_record(KEY, **arguments)


def forbidden(record):
    pytest.fail("Protected callback ran before the current-policy guard")


def test_callback_inside_transaction_result_after_commit_and_no_policy_activation(store):
    def inspect(record):
        assert store._connection.in_transaction
        assert record["state"] == "pending"
        record["principal_id"] = "changed-detached-copy"
        return ("synthetic summary",)

    assert guarded(store, inspect) == ("synthetic summary",)
    assert not store._connection.in_transaction
    assert store.run("get", KEY)["principal_id"] == CREATE["principal_id"]
    assert store.run("get", KEY)["state"] == "pending"
    assert store._connection.execute("SELECT count(*) FROM events").fetchone()[0] == 1


@pytest.mark.parametrize("field", ["owner_id", "profile_id", "enrollment_id"])
def test_guard_requires_exact_scoped_record(store, field):
    with pytest.raises(EnrollmentError, match="not_found"):
        store.with_current_record(
            {**KEY, field: "other"},
            expected_revision=1,
            expected_enrollment_revision=1,
            expected_epoch=0,
            operation=forbidden,
        )


@pytest.mark.parametrize("change", ["revoke", "set_policy"])
def test_committed_revoke_or_policy_change_prevents_callback(store, change):
    payload = {**CAS, "scope": SCOPE} if change == "set_policy" else CAS
    store.run(change, payload)
    with pytest.raises(EnrollmentError, match="revision_conflict"):
        guarded(store, forbidden)
    if change == "revoke":
        with pytest.raises(EnrollmentError, match="revoked"):
            guarded(store, forbidden, expected_enrollment_revision=2, expected_epoch=1)


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_revision": True},
        {"expected_enrollment_revision": 0},
        {"expected_epoch": False},
        {"expected_epoch": -1},
        {"expected_epoch": 2**63},
        {"expected_revision": 2**63},
        {"operation": "untrusted-callback-name"},
    ],
)
def test_guard_validates_versions_and_callable_before_transaction(store, changes):
    with pytest.raises(EnrollmentError, match="invalid_request"):
        guarded(store, forbidden, **changes)
    assert not store._connection.in_transaction


def test_callback_is_not_an_operation_in_public_data_dispatch(store):
    with pytest.raises(EnrollmentError, match="invalid_request"):
        store.run("with_current_record", {**KEY, "operation": forbidden})


def test_outer_transaction_is_not_rolled_back_or_used(store):
    store._connection.execute("BEGIN")
    with pytest.raises(EnrollmentError, match="connection_in_transaction"):
        guarded(store, forbidden)
    assert store._connection.in_transaction
    store._connection.rollback()


@pytest.mark.parametrize("failure", [RuntimeError, KeyboardInterrupt, SystemExit])
def test_callback_failure_never_leaves_transaction_or_result(store, failure):
    returned = []

    def interrupted(record):
        raise failure("synthetic failure")

    with pytest.raises(failure):
        returned.append(guarded(store, interrupted))
    assert returned == []
    assert not store._connection.in_transaction


def test_commit_failure_prevents_summary_return(store):
    returned = []
    store._connection.set_authorizer(
        lambda action, value, *rest: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_TRANSACTION and value == "COMMIT"
            else sqlite3.SQLITE_OK
        )
    )
    with pytest.raises(EnrollmentError, match="storage_error"):
        returned.append(guarded(store, lambda record: ("synthetic summary",)))
    assert returned == []
    assert not store._connection.in_transaction


def test_independent_revoke_waits_for_admitted_operation_to_finish(tmp_path):
    path = tmp_path / "admission.sqlite3"
    with sqlite3.connect(path) as connection:
        instance = EnrollmentStore(connection)
        instance.initialize()
        instance.run("create", CREATE)
    ready = Barrier(2)
    callback_entered, revoke_attempted, revoke_finished = Event(), Event(), Event()

    def reader():
        connection = sqlite3.connect(path)
        try:
            instance = EnrollmentStore(connection)
            instance.initialize()
            ready.wait(timeout=5)

            def snapshot(record):
                callback_entered.set()
                assert revoke_attempted.wait(5)
                assert not revoke_finished.is_set()
                return ("synthetic summary",)

            return guarded(instance, snapshot)
        finally:
            connection.close()

    def revoker():
        connection = sqlite3.connect(path)
        try:
            instance = EnrollmentStore(connection)
            instance.initialize()
            ready.wait(timeout=5)
            assert callback_entered.wait(5)
            connection.set_trace_callback(
                lambda statement: revoke_attempted.set() if statement == "BEGIN IMMEDIATE" else None
            )
            result = instance.run("revoke", CAS)
            revoke_finished.set()
            return result
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_result = pool.submit(reader)
        revoke_result = pool.submit(revoker)
        assert read_result.result(timeout=10) == ("synthetic summary",)
        assert revoke_result.result(timeout=10)["state"] == "revoked"
    assert revoke_finished.is_set()
    with sqlite3.connect(path) as connection:
        instance = EnrollmentStore(connection)
        instance.initialize()
        with pytest.raises(EnrollmentError, match="revision_conflict"):
            guarded(instance, forbidden)
        assert connection.execute("SELECT operation FROM events ORDER BY epoch").fetchall() == [
            ("create",),
            ("revoke",),
        ]
