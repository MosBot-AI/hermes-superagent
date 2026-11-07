"""Exact local labels, bounded grouping and atomic v1/v2-to-v3 migration."""

import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from test_task_agenda import (
    APPLICATION_ID,
    V1_SCHEMA,
    MigrationFailure,
    expect_error,
    seed_v1,
    snapshot,
)

from personal_agent.tasks import TaskStore, validate_request


@pytest.fixture
def store():
    with sqlite3.connect(":memory:") as conn:
        result = TaskStore(conn)
        result.initialize()
        yield result


def capture(store, **fields):
    return store.run(
        "capture", {"title": "Synthetic literal %_", "request_id": str(uuid4()), **fields}
    )["data"]


def change(store, task, operation="update", **fields):
    return store.run(
        operation,
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": str(uuid4()),
            **fields,
        },
    )["data"]


@pytest.mark.parametrize("label", ["", " ", " x", "x ", "x\n", "x\tx", "x\u200bx", "x" * 81, 1])
@pytest.mark.parametrize("operation", ["capture", "update", "list", "search", "agenda", "projects"])
def test_invalid_labels_before_storage(label, operation):
    payload = {
        "capture": {"title": "Synthetic", "request_id": "a"},
        "update": {"task_id": str(uuid4()), "expected_revision": 1, "request_id": "a"},
        "search": {"query": "Synthetic"},
        "agenda": {"on": "2028-02-29"},
        "list": {},
        "projects": {},
    }[operation]
    payload["after" if operation == "projects" else "project"] = label
    expect_error("invalid_request", lambda: validate_request(operation, payload))


@pytest.mark.parametrize(
    "operation,extra",
    [("list", {}), ("search", {"query": "Synthetic"}), ("agenda", {"on": "2028-02-29"})],
)
def test_exact_filters(store, operation, extra):
    records = [
        capture(store, project=label, due_date="2028-02-29")
        for label in [None, "Alpha", "alpha", "%_", "é", "e\u0301", "x" * 80]
    ]
    for record in records:
        filters = (
            {"unassigned": True} if record["project"] is None else {"project": record["project"]}
        )
        assert store.run(operation, {**extra, **filters})["data"]["items"] == [record]
    assert len(store.run(operation, extra)["data"]["items"]) == len(records)
    for filters in [
        {"project": None},
        {"project": "Alpha", "unassigned": False},
        {"unassigned": 1},
    ]:
        expect_error(
            "invalid_request", lambda filters=filters: store.run(operation, {**extra, **filters})
        )


def test_groups_counts_disappearing_cursor_and_null(store):
    empty = store.run("projects", {})["data"]
    assert empty == {
        "items": [],
        "unassigned_counts": dict(captured=0, done=0, cancelled=0, total=0),
        "has_more": False,
        "next_cursor": None,
    }
    plain = capture(store)
    a = capture(store, project="A")
    capture(store, project="a")
    done = capture(store, project="a")
    cancelled = capture(store, project="a")
    change(store, done, "complete", note="Synthetic done")
    change(store, cancelled, "cancel", note="Synthetic cancelled")
    first = store.run("projects", {"limit": 1})["data"]
    assert first["items"] == [dict(project="A", captured=1, done=0, cancelled=0, total=1)]
    assert first["unassigned_counts"] == dict(captured=1, done=0, cancelled=0, total=1)
    assert first["next_cursor"] == "A" and first["has_more"]
    cleared = change(store, a, project=None)
    assert cleared["project"] is None and cleared["revision"] == 2
    page = store.run("projects", {"after": "A"})["data"]
    assert page["items"] == [dict(project="a", captured=1, done=1, cancelled=1, total=3)]
    assert page["unassigned_counts"]["total"] == 2
    assert not page["has_more"] and page["next_cursor"] is None
    assert store.run("projects", {"after": "never existed"})["data"]["items"] == []
    assert store.run("get", {"task_id": plain["id"]})["data"]["project"] is None


def test_revision_replay_omitted_null_and_bounds(store):
    request = {"title": "Synthetic", "request_id": "capture"}
    first = store.run("capture", request)
    assert store.run("capture", request) == {**first, "replayed": True}
    expect_error("idempotency_conflict", lambda: store.run("capture", {**request, "project": None}))
    record = first["data"]
    update = dict(task_id=record["id"], expected_revision=1, request_id="assign", project="A")
    assigned = store.run("update", update)
    assert store.run("update", update) == {**assigned, "replayed": True}
    expect_error("revision_conflict", lambda: change(store, record, project="B"))
    assert change(store, assigned["data"], title="Updated")["project"] == "A"
    for index in range(102):
        capture(store, project=f"label-{index:03}")
    assert len(store.run("projects", {})["data"]["items"]) == 20
    assert len(store.run("projects", {"limit": 100})["data"]["items"]) == 100
    for limit in [0, 101, True, "2"]:
        expect_error("invalid_request", lambda limit=limit: store.run("projects", {"limit": limit}))


def seed_legacy(conn, version):
    history = seed_v1(conn)
    if version == 2:
        conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        conn.execute("PRAGMA user_version = 2")
        # Genuine v2 update with the prior request normalization and receipt shape.
        record = dict(history[0][2], due_date="2028-02-29", revision=2)
        request = dict(
            task_id=record["id"], expected_revision=1, request_id="v2", due_date=record["due_date"]
        )
        digest = hashlib.sha256(
            json.dumps(
                ["update", {k: v for k, v in request.items() if k != "request_id"}],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        conn.execute(
            "UPDATE tasks SET due_date=?,revision=2 WHERE id=?", (record["due_date"], record["id"])
        )
        conn.execute("INSERT INTO receipts VALUES (?,?,?)", ("v2", digest, json.dumps(record)))
        conn.execute("INSERT INTO events VALUES (?,2,'update','synthetic')", (record["id"],))
        history.append(("update", request, record))
        conn.commit()
    return history


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_migration_receipts_sequences_and_reopen(tmp_path, version):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        history = seed_legacy(conn, version)
        before = snapshot(conn)
        store = TaskStore(conn)
        store.initialize()
        after = snapshot(conn)
        assert after["version"] == 4
        for table in ("receipts", "events", "sqlite_sequence"):
            assert after[table] == before[table]
        assert after["tasks"] == [
            (*row, *((None,) * (3 - version)), "ready", "", None) for row in before["tasks"]
        ]
        for operation, request, receipt in history:
            assert store.run(operation, request) == {"data": receipt, "replayed": True}
        assert all(
            row["project"] is None for row in store.run("list", {"state": "all"})["data"]["items"]
        )
        capture(store, project="New")
        assert conn.execute("SELECT max(sequence) FROM tasks").fetchone()[0] == 3
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        assert store.run("projects", {})["data"]["items"][0]["project"] == "New"


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "failure", ["ALTER TABLE tasks ADD COLUMN project", "PRAGMA user_version = 4", "COMMIT"]
)
def test_atomic_migration_failure(tmp_path, version, failure):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path, factory=MigrationFailure) as conn:
        seed_legacy(conn, version)
        before = snapshot(conn)
        raw = path.read_bytes()
        conn.fail_at = failure
        expect_error("storage_error", TaskStore(conn).initialize)
        assert snapshot(conn) == before and path.read_bytes() == raw
        conn.fail_at = None
        TaskStore(conn).initialize()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4


@pytest.mark.parametrize("version", [1, 2])
def test_wrong_legacy_constraints_refused(tmp_path, version):
    path = tmp_path / "wrong.sqlite"
    with sqlite3.connect(path) as conn:
        for name, sql in V1_SCHEMA.items():
            if name == "tasks":
                sql = sql.replace("CHECK(revision >= 1)", "CHECK(revision >= 0)")
            conn.execute(sql)
        if version == 2:
            conn.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version = {version}")
    before = path.read_bytes()
    with sqlite3.connect(path) as conn:
        expect_error("unsupported_schema", TaskStore(conn).initialize)
    assert path.read_bytes() == before


def test_project_mutation_failure_rolls_back_receipt_and_assignment():
    with sqlite3.connect(":memory:", factory=MigrationFailure) as conn:
        store = TaskStore(conn)
        store.initialize()
        record = capture(store, project="Before")
        before = snapshot(conn)
        request = dict(
            task_id=record["id"], expected_revision=1, request_id="retry", project="After"
        )
        conn.fail_at = "INSERT INTO receipts"
        expect_error("storage_error", lambda: store.run("update", request))
        assert snapshot(conn) == before
        conn.fail_at = None
        updated = store.run("update", request)
        assert updated["data"]["project"] == "After" and updated["data"]["revision"] == 2
        assert store.run("update", request) == {**updated, "replayed": True}


def test_projects_uses_one_deferred_read_transaction(store):
    capture(store, project="Synthetic")
    traced = []
    store._connection.set_trace_callback(traced.append)
    store.run("projects", {})
    assert traced[0] == "BEGIN" and traced[-1] == "COMMIT"
    assert len(traced) == 4
    assert all(sql.startswith("SELECT") for sql in traced[1:-1])
    assert not store._connection.in_transaction


@pytest.mark.parametrize("failure", ["SELECT project", "SELECT sum", "COMMIT"])
def test_projects_read_failure_rolls_back(failure):
    with sqlite3.connect(":memory:", factory=MigrationFailure) as conn:
        store = TaskStore(conn)
        store.initialize()
        capture(store, project="Synthetic")
        before = snapshot(conn)
        traced = []
        conn.set_trace_callback(traced.append)
        conn.fail_at = failure
        expect_error("storage_error", lambda: store.run("projects", {}))
        assert traced[0] == "BEGIN" and traced[-1] == "ROLLBACK"
        assert not conn.in_transaction
        conn.fail_at = None
        assert snapshot(conn) == before
        assert store.run("projects", {})["data"]["items"][0]["total"] == 1


def test_projects_read_snapshot_blocks_interleaved_commit(tmp_path):
    """Default rollback journal keeps both aggregates on the same committed view."""

    class InterleavedConnection(sqlite3.Connection):
        between_queries = None

        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT sum") and self.between_queries is not None:
                self.between_queries()
            return super().execute(sql, parameters)

    path = tmp_path / "snapshot.sqlite"
    with sqlite3.connect(path, factory=InterleavedConnection) as reader:
        store = TaskStore(reader)
        store.initialize()
        task = capture(store, project="Synthetic")
        with sqlite3.connect(path, timeout=0, isolation_level=None) as writer:
            assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
            attempted = []

            def interleave():
                writer.execute("BEGIN IMMEDIATE")
                writer.execute("UPDATE tasks SET project=NULL WHERE id=?", (task["id"],))
                # The read snapshot is held across the query boundary. Without it,
                # this commit succeeds and the task appears in both aggregates.
                with pytest.raises(sqlite3.OperationalError) as error:
                    writer.execute("COMMIT")
                assert error.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
                writer.execute("ROLLBACK")
                attempted.append(True)

            reader.between_queries = interleave
            result = store.run("projects", {})["data"]
            assert attempted == [True]
            assert result["items"][0]["total"] == 1
            assert result["unassigned_counts"]["total"] == 0
            assert not reader.in_transaction
            reader.between_queries = None
            writer.execute("UPDATE tasks SET project=NULL WHERE id=?", (task["id"],))
            next_page = store.run("projects", {})["data"]
            assert next_page["items"] == []
            assert next_page["unassigned_counts"]["total"] == 1
