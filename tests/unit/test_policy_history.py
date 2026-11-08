"""Administrative history is bounded metadata, never an identity/grant issuer."""

import json
import sqlite3

import pytest

from personal_agent.enrollment import EnrollmentError, EnrollmentStore

KEY = {"owner_id": "owner", "profile_id": "profile", "enrollment_id": "entry"}
SCOPE = {
    "operation": "personal.tasks.read",
    "target": "exact_tasks",
    "resource_ids": ("secret-task",),
    "data_scope": "tasks.summary",
}
CREATE = {
    **KEY,
    "transport_id": "transport-secret",
    "transport_receiver_id": "receiver-secret",
    "principal_id": "principal-secret",
    "scope": SCOPE,
}


def initialized(connection):
    store = EnrollmentStore(connection)
    store.initialize()
    return store


def populate(store):
    store.run("create", CREATE)
    for revision in range(1, 4):
        store.run(
            "set_policy",
            {
                **KEY,
                "expected_revision": revision,
                "expected_enrollment_revision": 1,
                "scope": SCOPE,
            },
        )


def revoke(store):
    store.run("revoke", {**KEY, "expected_revision": 4, "expected_enrollment_revision": 1})


def fails(store, code, **kwargs):
    with pytest.raises(EnrollmentError) as error:
        store.policy_history(KEY, **kwargs)
    assert error.value.code == code
    assert "secret" not in str(error.value)


def test_restart_pagination_watermark_and_redaction(tmp_path):
    path = tmp_path / "history.db"
    with sqlite3.connect(path) as conn:
        store = initialized(conn)
        populate(store)
        before = conn.total_changes
        page = store.policy_history(KEY, limit=2)
        assert conn.total_changes == before
        assert [item["epoch"] for item in page["items"]] == [0, 1]
        assert page["has_more"] and page["next_after_epoch"] == 1
        assert page["current_epoch"] == 3 and page["current_state"] == "pending"
        revoke(store)
    with sqlite3.connect(path) as conn:
        store = initialized(conn)
        page = store.policy_history(KEY, after_epoch=1, limit=2)
        assert [item["epoch"] for item in page["items"]] == [2, 3]
        assert page["current_epoch"] == 4 and page["has_more"]
        page = store.policy_history(KEY, after_epoch=3, limit=2)
        assert page["items"] == [
            {"epoch": 4, "operation": "revoke", "enrollment_revision": 2, "policy_revision": 4}
        ]
        assert not page["has_more"] and page["next_after_epoch"] == 4
        assert page["current_state"] == "revoked"
        assert page["current_enrollment_revision"] == 2
        assert page["current_policy_revision"] == 4
        assert "secret" not in json.dumps(page)
        empty = store.policy_history(KEY, after_epoch=4)
        assert empty["items"] == [] and empty["next_after_epoch"] == 4
        assert not empty["has_more"]
        fails(store, "invalid_cursor", after_epoch=5)


@pytest.mark.parametrize("field", list(KEY))
def test_exact_scope(field):
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        populate(store)
        other = {**KEY, field: "other"}
        with pytest.raises(EnrollmentError, match="not_found"):
            store.policy_history(other)
        store.run("create", {**CREATE, **other})
        assert len(store.policy_history(other)["items"]) == 1
        assert len(store.policy_history(KEY)["items"]) == 4


@pytest.mark.parametrize(
    "kwargs",
    [
        {"after_epoch": True},
        {"after_epoch": -2},
        {"after_epoch": 2**63},
        {"after_epoch": None},
        {"after_epoch": "0"},
        {"limit": True},
        {"limit": 0},
        {"limit": 101},
        {"limit": 1.0},
    ],
)
def test_invalid_requests(kwargs):
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        populate(store)
        fails(store, "invalid_request", **kwargs)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM events WHERE epoch=0",
        "DELETE FROM events WHERE epoch=2",
        "DELETE FROM events WHERE epoch=3",
        "UPDATE events SET policy_revision=99 WHERE epoch=1",
        "UPDATE events SET enrollment_revision=2 WHERE epoch=1",
        "UPDATE events SET operation='revoke' WHERE epoch=1",
        "UPDATE events SET operation='set_policy' WHERE epoch=0",
        "UPDATE events SET epoch=9 WHERE epoch=2",
        "UPDATE enrollments SET policy_revision=99",
        "UPDATE enrollments SET enrollment_revision=2",
        "INSERT INTO events VALUES ('owner','profile','entry',4,'set_policy',1,5)",
    ],
)
def test_malformed_selected_history_and_tail_fail_closed(sql):
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        populate(store)
        conn.execute(sql)
        conn.commit()
        fails(store, "invalid_policy_audit")
        assert not conn.in_transaction


def test_even_empty_page_checks_current_tail():
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        populate(store)
        conn.execute("DELETE FROM events WHERE epoch=3")
        conn.commit()
        fails(store, "invalid_policy_audit", after_epoch=3)


def test_lookahead_validation_and_documented_range_limit():
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        populate(store)
        conn.execute("UPDATE events SET policy_revision=99 WHERE epoch=1")
        conn.commit()
        fails(store, "invalid_policy_audit", limit=1)
        # A later page validates its selected range and tail, not all old rows.
        assert store.policy_history(KEY, after_epoch=1)["current_epoch"] == 3


def test_not_initialized_and_caller_transaction_preserved():
    with sqlite3.connect(":memory:") as conn:
        fails(EnrollmentStore(conn), "not_initialized")
        store = initialized(conn)
        populate(store)
        conn.execute("BEGIN")
        fails(store, "connection_in_transaction")
        assert conn.in_transaction
        conn.rollback()


@pytest.mark.parametrize("denied", ["select", "commit"])
def test_storage_failure_does_not_return_page(denied):
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        populate(store)

        def authorizer(action, arg1, arg2, db, trigger):
            if (denied == "select" and action == sqlite3.SQLITE_READ and arg1 == "events") or (
                denied == "commit" and action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT"
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorizer)
        fails(store, "storage_error")
        assert not conn.in_transaction
        conn.set_authorizer(None)
        assert len(store.policy_history(KEY)["items"]) == 4


def test_maximum_page_output_bound():
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        store.run("create", CREATE)
        for revision in range(1, 105):
            store.run(
                "set_policy",
                {
                    **KEY,
                    "expected_revision": revision,
                    "expected_enrollment_revision": 1,
                    "scope": SCOPE,
                },
            )
        page = store.policy_history(KEY, limit=100)
        assert len(page["items"]) == 100 and page["has_more"]
        assert page["current_epoch"] == 104 and page["next_after_epoch"] == 99


def test_direct_revoke_and_corrupt_terminal_audit():
    with sqlite3.connect(":memory:") as conn:
        store = initialized(conn)
        store.run("create", CREATE)
        store.run("revoke", {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1})
        page = store.policy_history(KEY)
        assert [item["operation"] for item in page["items"]] == ["create", "revoke"]
        assert page["current_epoch"] == 1 and page["current_policy_revision"] == 1
        conn.execute("UPDATE events SET operation='set_policy' WHERE epoch=1")
        conn.commit()
        fails(store, "invalid_policy_audit", after_epoch=1)
