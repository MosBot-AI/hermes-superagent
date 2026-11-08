"""Pending records cannot become authenticated identities or read grants."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from personal_agent.enrollment import EnrollmentError, EnrollmentStore

KEY = {"owner_id": "owner", "profile_id": "profile", "enrollment_id": "enrollment"}
SCOPE = {
    "operation": "personal.tasks.read",
    "target": "exact_tasks",
    "resource_ids": ("task-one",),
    "data_scope": "tasks.summary",
}
CREATE = {
    **KEY,
    "transport_id": "telegram",
    "transport_receiver_id": "bot",
    "principal_id": "actor",
    "scope": SCOPE,
}
CAS = {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1}


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    result = EnrollmentStore(connection)
    result.initialize()
    yield result
    connection.close()


def fails(code, call):
    with pytest.raises(EnrollmentError) as error:
        call()
    assert error.value.code == code
    assert "actor" not in str(error.value)


def test_pending_policy_revoke_and_terminal(store):
    initial = store.run("create", CREATE)
    assert initial["state"] == "pending"
    assert (initial["enrollment_revision"], initial["policy_revision"], initial["epoch"]) == (
        1,
        1,
        0,
    )
    changed = store.run("set_policy", {**CAS, "scope": SCOPE})
    assert (changed["enrollment_revision"], changed["policy_revision"], changed["epoch"]) == (
        1,
        2,
        1,
    )
    fails("revision_conflict", lambda: store.run("set_policy", {**CAS, "scope": SCOPE}))
    revoked = store.run("revoke", {**CAS, "expected_revision": 2})
    assert (revoked["state"], revoked["enrollment_revision"], revoked["epoch"]) == ("revoked", 2, 2)
    fails(
        "revoked",
        lambda: store.run(
            "set_policy",
            {
                **CAS,
                "expected_revision": 2,
                "expected_enrollment_revision": 2,
                "scope": SCOPE,
            },
        ),
    )
    fails(
        "revoked",
        lambda: store.run(
            "revoke",
            {
                **CAS,
                "expected_revision": 2,
                "expected_enrollment_revision": 2,
            },
        ),
    )
    fails("already_exists", lambda: store.run("create", CREATE))
    assert store.run("get", KEY) == revoked
    events = store._connection.execute("SELECT * FROM events").fetchall()
    assert [event[4] for event in events] == ["create", "set_policy", "revoke"]
    assert not any(value in repr(events) for value in ("actor", "bot", "task-one"))


@pytest.mark.parametrize("field", ["owner_id", "profile_id", "enrollment_id"])
@pytest.mark.parametrize("operation", ["get", "set_policy", "revoke"])
def test_scoped_not_found(store, field, operation):
    store.run("create", CREATE)
    payload = dict(KEY if operation == "get" else CAS)
    payload[field] = "different"
    if operation == "set_policy":
        payload["scope"] = SCOPE
    fails("not_found", lambda: store.run(operation, payload))
    assert store.run("get", KEY)["epoch"] == 0


def test_same_id_isolated_across_owners_profiles(store):
    for owner, profile in (("one", "a"), ("one", "b"), ("two", "a")):
        record = store.run("create", {**CREATE, "owner_id": owner, "profile_id": profile})
        assert record["owner_id"] == owner
    store.run("revoke", {**CAS, "owner_id": "one", "profile_id": "a"})
    assert store.run("get", {**KEY, "owner_id": "one", "profile_id": "b"})["state"] == "pending"


@pytest.mark.parametrize(
    "payload",
    [
        {**CREATE, "active": True},
        {**CREATE, "owner_id": True},
        {**CREATE, "owner_id": "*"},
        {**CREATE, "scope": {**SCOPE, "extra": 1}},
        {**CREATE, "scope": {**SCOPE, "resource_ids": ["task-one"]}},
        {**CREATE, "scope": {**SCOPE, "resource_ids": ("task-one", "task-one")}},
        {**CREATE, "scope": {**SCOPE, "resource_ids": ()}},
        {**CREATE, "scope": {**SCOPE, "operation": "personal.tasks.write"}},
        {**CREATE, "scope": {**SCOPE, "target": "own_inbox"}},
        {**CREATE, "scope": {**SCOPE, "resource_ids": tuple(str(i) for i in range(1025))}},
    ],
)
def test_invalid_create(store, payload):
    fails("invalid_request", lambda: store.run("create", payload))
    assert store._connection.execute("SELECT count(*) FROM enrollments").fetchone()[0] == 0


@pytest.mark.parametrize("value", [True, False, -1, 0, 2**63, "1", 1.0])
@pytest.mark.parametrize("field", ["expected_revision", "expected_enrollment_revision"])
def test_invalid_revisions(store, value, field):
    fails("invalid_request", lambda: store.run("revoke", {**CAS, field: value}))


@pytest.mark.parametrize(
    "scope",
    [
        {**SCOPE, "target": "own_inbox", "resource_ids": ()},
        {
            "operation": "personal.primary_binding.inspect",
            "target": "primary_binding",
            "resource_ids": (),
            "data_scope": "primary_binding.metadata",
        },
    ],
)
def test_supported_exact_scopes(store, scope):
    assert store.run("create", {**CREATE, "scope": scope})["scope"] == scope


def test_input_output_detached(store):
    scope = dict(SCOPE)
    record = store.run("create", {**CREATE, "scope": scope})
    scope["target"] = "changed"
    record["scope"]["target"] = "changed"
    assert store.run("get", KEY)["scope"] == SCOPE


@pytest.mark.parametrize("field", ["epoch", "policy_revision", "enrollment_revision"])
def test_exhaustion_never_wraps(store, field):
    store.run("create", CREATE)
    store._connection.execute(f"UPDATE enrollments SET {field}=?", (2**63 - 1,))
    store._connection.commit()
    payload = {**CAS, "scope": SCOPE}
    operation = "set_policy"
    if field == "policy_revision":
        payload["expected_revision"] = 2**63 - 1
    if field == "enrollment_revision":
        operation = "revoke"
        payload = {**CAS, "expected_enrollment_revision": 2**63 - 1}
    fails("revision_exhausted", lambda: store.run(operation, payload))
    assert store.run("get", KEY)[field] == 2**63 - 1


@pytest.mark.parametrize("operation", ["create", "set_policy", "revoke"])
def test_atomic_rollback_on_audit_failure(store, monkeypatch, operation):
    if operation != "create":
        store.run("create", CREATE)
    before = store._connection.execute("SELECT * FROM enrollments").fetchall()
    events = store._connection.execute("SELECT * FROM events").fetchall()

    def fail(*args):
        raise sqlite3.OperationalError("private-secret")

    monkeypatch.setattr(store, "_audit", fail)
    payload = CREATE if operation == "create" else dict(CAS)
    if operation == "set_policy":
        payload["scope"] = SCOPE
    fails("storage_error", lambda: store.run(operation, payload))
    assert store._connection.execute("SELECT * FROM enrollments").fetchall() == before
    assert store._connection.execute("SELECT * FROM events").fetchall() == events
    assert not store._connection.in_transaction


def test_persistence_and_concurrent_cas(tmp_path):
    path = tmp_path / "enrollment.sqlite3"
    with sqlite3.connect(path) as conn:
        store = EnrollmentStore(conn)
        store.initialize()
        store.run("create", CREATE)
    barrier = Barrier(2)

    def update():
        conn = sqlite3.connect(path)
        try:
            store = EnrollmentStore(conn)
            store.initialize()
            barrier.wait()
            try:
                return store.run("set_policy", {**CAS, "scope": SCOPE})["policy_revision"]
            except EnrollmentError as error:
                return error.code
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: update(), range(2)), key=str) == [2, "revision_conflict"]
    with sqlite3.connect(path) as conn:
        store = EnrollmentStore(conn)
        store.initialize()
        assert store.run("get", KEY)["epoch"] == 1
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2


@pytest.mark.parametrize(
    "sql,code",
    [
        ("CREATE TABLE unrelated (id INTEGER)", "foreign_database"),
        ("PRAGMA application_id=123", "foreign_database"),
        ("PRAGMA user_version=999", "foreign_database"),
    ],
)
def test_foreign_database(sql, code):
    with sqlite3.connect(":memory:") as conn:
        conn.execute(sql)
        fails(code, EnrollmentStore(conn).initialize)
        assert not conn.in_transaction


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE other (id INTEGER)",
        "CREATE TEMP TABLE enrollments (id INTEGER)",
        "CREATE INDEX unknown_index ON enrollments(principal_id)",
        "PRAGMA user_version=3",
        "CREATE TRIGGER surprise AFTER INSERT ON enrollments BEGIN SELECT 1; END",
    ],
)
def test_schema_tampering_rejected(store, sql):
    store._connection.execute(sql)
    fails("unsupported_schema", lambda: store.run("create", CREATE))
    fails("unsupported_schema", store.initialize)
    fails("not_initialized", lambda: store.run("get", KEY))


def test_caller_transaction_not_rolled_back(store):
    store._connection.execute("BEGIN")
    fails("connection_in_transaction", lambda: store.run("create", CREATE))
    assert store._connection.in_transaction
    store._connection.rollback()


def test_corrupt_record_fails_closed(store):
    store.run("create", CREATE)
    store._connection.execute("UPDATE enrollments SET resource_ids='{}'")
    store._connection.commit()
    fails("invalid_record", lambda: store.run("get", KEY))
    fails("invalid_record", lambda: store.run("revoke", CAS))


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("activate", KEY),
        ("get", {**KEY, "scope": SCOPE}),
        ("set_policy", {**CAS, "scope": SCOPE, "principal_id": "replacement"}),
        ("set_policy", {**CAS, "scope": SCOPE, "transport_receiver_id": "replacement"}),
        ("revoke", {**CAS, "expected_enrollment_revision": 2}),
    ],
)
def test_no_activation_identity_mutation_or_stale_enrollment(store, operation, payload):
    store.run("create", CREATE)
    code = "revision_conflict" if operation == "revoke" else "invalid_request"
    fails(code, lambda: store.run(operation, payload))
    assert store.run("get", KEY)["epoch"] == 0


def test_interruption_rolls_back(store, monkeypatch):
    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(store, "_audit", interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.run("create", CREATE)
    assert not store._connection.in_transaction
    assert store._connection.execute("SELECT count(*) FROM enrollments").fetchone()[0] == 0


def test_schema_initialization_failure_atomic():
    conn = sqlite3.connect(":memory:")
    conn.set_authorizer(
        lambda operation, name, *rest: (
            sqlite3.SQLITE_DENY
            if operation == sqlite3.SQLITE_CREATE_TABLE and name == "events"
            else sqlite3.SQLITE_OK
        )
    )
    store = EnrollmentStore(conn)
    fails("storage_error", store.initialize)
    conn.set_authorizer(None)
    assert conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] == 0
    assert conn.execute("PRAGMA application_id").fetchone()[0] == 0
    assert not conn.in_transaction
    store.initialize()
    assert store.run("create", CREATE)["state"] == "pending"
    conn.close()


@pytest.mark.parametrize("first", ["set_policy", "revoke"])
def test_policy_revoke_serialized_race(tmp_path, first):
    """Hold the winning write open while an independent contender starts."""
    from threading import Event

    path = tmp_path / "race.sqlite3"
    with sqlite3.connect(path) as conn:
        store = EnrollmentStore(conn)
        store.initialize()
        store.run("create", CREATE)
    writer_entered = Event()
    contender_started = Event()
    barrier = Barrier(2)
    second = "revoke" if first == "set_policy" else "set_policy"

    def mutate(operation):
        conn = sqlite3.connect(path)
        try:
            store = EnrollmentStore(conn)
            store.initialize()
            if operation == first:
                audit = store._audit

                def delayed_audit(record, action):
                    writer_entered.set()
                    assert contender_started.wait(5)
                    audit(record, action)

                store._audit = delayed_audit
            barrier.wait()
            if operation == second:
                assert writer_entered.wait(5)
                contender_started.set()
            payload = {**CAS, "scope": SCOPE} if operation == "set_policy" else CAS
            try:
                return store.run(operation, payload)
            except EnrollmentError as error:
                return error.code
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        winner = pool.submit(mutate, first)
        loser = pool.submit(mutate, second)
        assert winner.result()["epoch"] == 1
        assert loser.result() == "revision_conflict"
    with sqlite3.connect(path) as conn:
        store = EnrollmentStore(conn)
        store.initialize()
        current = store.run("get", KEY)
        assert current["state"] == ("revoked" if first == "revoke" else "pending")
        assert conn.execute("SELECT operation FROM events ORDER BY epoch").fetchall() == [
            ("create",),
            (first,),
        ]
        if first == "revoke":
            fails(
                "revoked",
                lambda: store.run(
                    "set_policy",
                    {
                        **CAS,
                        "expected_enrollment_revision": 2,
                        "scope": SCOPE,
                    },
                ),
            )
        else:
            # A fresh explicit CAS can revoke the current pending policy.
            assert store.run("revoke", {**CAS, "expected_revision": 2})["state"] == "revoked"


def test_duplicate_create_contention(tmp_path):
    path = tmp_path / "create-race.sqlite3"
    with sqlite3.connect(path) as conn:
        EnrollmentStore(conn).initialize()
    barrier = Barrier(2)

    def create():
        conn = sqlite3.connect(path)
        try:
            store = EnrollmentStore(conn)
            store.initialize()
            barrier.wait()
            try:
                return store.run("create", CREATE)["state"]
            except EnrollmentError as error:
                return error.code
        finally:
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: create(), range(2))) == ["already_exists", "pending"]
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM enrollments").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1


def test_busy_is_retryable_without_automatic_retry(tmp_path):
    path = tmp_path / "locked.sqlite3"
    first = sqlite3.connect(path)
    second = sqlite3.connect(path, timeout=0)
    try:
        store = EnrollmentStore(second)
        store.initialize()
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(EnrollmentError) as error:
            store.run("create", CREATE)
        assert error.value.code == "storage_busy"
        assert error.value.retryable is True
        assert not second.in_transaction
        first.rollback()
        assert second.execute("SELECT count(*) FROM enrollments").fetchone()[0] == 0
        assert store.run("create", CREATE)["state"] == "pending"
    finally:
        first.close()
        second.close()
