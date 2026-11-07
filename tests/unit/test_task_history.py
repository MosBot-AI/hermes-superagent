"""Task recovery metadata: bounded reads, durable events and unchanged schema."""

import json
import sqlite3
from uuid import uuid4

import pytest
from test_task_agenda import MigrationFailure, snapshot
from test_task_projects import seed_legacy

from personal_agent.task_tool_contract import normalize_task_tool_request
from personal_agent.tasks import TaskError, TaskStore, validate_request


def capture(store, key="capture"):
    return store.run(
        "capture",
        {"title": "Private title", "details": "Private details", "request_id": key},
    )["data"]


def update(store, task, key="update"):
    return store.run(
        "update",
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": key,
            "title": "Private edited title",
        },
    )["data"]


@pytest.fixture
def store():
    with sqlite3.connect(":memory:") as connection:
        result = TaskStore(connection)
        result.initialize()
        yield result


@pytest.mark.parametrize("terminal,state", [("complete", "done"), ("cancel", "cancelled")])
def test_history_is_chronological_metadata_only_and_durable(tmp_path, terminal, state):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        task = update(store, capture(store))
        request = {
            "task_id": task["id"],
            "expected_revision": 2,
            "request_id": "resolution",
            "note": "Private completion note",
        }
        done = store.run(terminal, request)["data"]
        assert store.run(terminal, request)["replayed"]
        before = snapshot(connection)
        first = store.run("history", {"task_id": task["id"], "limit": 2})
        assert first["replayed"] is False
        data = first["data"]
        assert data["task_id"] == task["id"]
        assert data["current_revision"] == 3 and data["current_state"] == state
        assert data["has_more"] and data["next_cursor"] == 2
        assert [item["operation"] for item in data["items"]] == ["capture", "update"]
        assert [item["revision"] for item in data["items"]] == [1, 2]
        assert all(set(item) == {"revision", "operation", "timestamp"} for item in data["items"])
        assert snapshot(connection) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
    raw = path.read_bytes()
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        page = store.run("history", {"task_id": task["id"], "after_revision": 2})["data"]
        assert page["items"] == [
            {"revision": 3, "operation": terminal, "timestamp": done["updated_at"]}
        ]
        assert not page["has_more"] and page["next_cursor"] is None
        assert "Private" not in json.dumps([data, page])
        assert (
            store.run("history", {"task_id": task["id"], "after_revision": 3})["data"]["items"]
            == []
        )
    assert path.read_bytes() == raw


def test_task_isolation_live_pages_and_failed_writes_add_no_events(store):
    task = capture(store)
    other = update(store, capture(store, "other"), "other-update")
    task = update(store, task)
    first = store.run("history", {"task_id": task["id"], "limit": 1})["data"]
    assert first["current_revision"] == 2 and first["next_cursor"] == 1
    task = update(store, task, "later")
    with pytest.raises(TaskError, match="revision_conflict"):
        update(store, {**task, "revision": 1}, "stale")
    with pytest.raises(TaskError, match="idempotency_conflict"):
        capture(store, "later")
    page = store.run("history", {"task_id": task["id"], "after_revision": first["next_cursor"]})[
        "data"
    ]
    assert page["current_revision"] == 3
    assert [item["revision"] for item in page["items"]] == [2, 3]
    assert store.run("history", {"task_id": other["id"]})["data"]["current_revision"] == 2
    assert len(store.run("history", {"task_id": task["id"]})["data"]["items"]) == 3


def test_default_and_maximum_page_bounds(store):
    task = capture(store)
    for index in range(101):
        task = update(store, task, f"update-{index}")
    default = store.run("history", {"task_id": task["id"]})["data"]
    assert len(default["items"]) == 20 and default["next_cursor"] == 20
    maximum = store.run("history", {"task_id": task["id"], "limit": 100})["data"]
    assert len(maximum["items"]) == 100 and maximum["next_cursor"] == 100
    assert (
        len(store.run("history", {"task_id": task["id"], "after_revision": 100})["data"]["items"])
        == 2
    )


@pytest.mark.parametrize("after", [1, 2, 2**63 - 1])
def test_unknown_task_is_not_found_before_cursor_validation(store, after):
    with pytest.raises(TaskError, match="not_found"):
        store.run("history", {"task_id": str(uuid4()), "after_revision": after})


def test_future_or_missing_cursor_is_rejected_without_leaking_text(store):
    task = capture(store)
    with pytest.raises(TaskError, match="invalid_cursor"):
        store.run("history", {"task_id": task["id"], "after_revision": 2})
    task = update(store, task)
    store._connection.execute("DELETE FROM events WHERE revision = 1")
    store._connection.commit()
    with pytest.raises(TaskError, match="invalid_cursor"):
        store.run("history", {"task_id": task["id"], "after_revision": 1})


@pytest.mark.parametrize(
    "extra",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"limit": "2"},
        {"limit": 1.0},
        {"after_revision": -1},
        {"after_revision": 2**63},
        {"after_revision": True},
        {"after_revision": "1"},
        {"after_revision": 1.0},
        {"after_revision": None},
        {"after": str(uuid4())},
        {"state": "all"},
        {"project": "Private"},
        {"request_id": "history"},
        {"owner": "Private"},
        {"task_id": "invalid"},
    ],
)
def test_invalid_requests_fail_before_storage(extra):
    request = {"task_id": str(uuid4()), **extra}
    with pytest.raises(TaskError, match="invalid_request"):
        TaskStore(sqlite3.connect(":memory:")).run("history", request)
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_read", {"action": "history", **request})


def test_history_requires_id_and_normalizes_without_mutation():
    with pytest.raises(TaskError, match="invalid_request"):
        validate_request("history", {})
    request = {"task_id": str(uuid4())}
    normalized = validate_request("history", request)
    assert normalized == {**request, "limit": 20, "after_revision": 0}
    assert len(request) == 1
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_write", {"action": "history", **request})


def test_history_metadata_and_events_share_one_read_snapshot(tmp_path):
    class InterleavedConnection(sqlite3.Connection):
        append = None

        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT revision, operation") and self.append is not None:
                callback, self.append = self.append, None
                callback()
            return super().execute(sql, parameters)

    path = tmp_path / "concurrent.sqlite3"
    with sqlite3.connect(path, factory=InterleavedConnection) as connection:
        # Synthetic WAL fixture permits a second writer during the reader's
        # snapshot. This does not alter the production rollback-journal policy.
        connection.execute("PRAGMA journal_mode=WAL")
        reader = TaskStore(connection)
        reader.initialize()
        task = capture(reader)
        with sqlite3.connect(path) as writer_connection:
            writer = TaskStore(writer_connection)
            writer.initialize()
            connection.append = lambda: update(writer, task)
            first = reader.run("history", {"task_id": task["id"]})["data"]
            assert first["current_revision"] == 1
            assert [item["revision"] for item in first["items"]] == [1]
            later = reader.run("history", {"task_id": task["id"]})["data"]
            assert later["current_revision"] == 2
            assert [item["revision"] for item in later["items"]] == [1, 2]


@pytest.mark.parametrize("version", [1, 2])
def test_history_reads_preexisting_events_after_migration(version):
    with sqlite3.connect(":memory:") as connection:
        old = seed_legacy(connection, version)
        store = TaskStore(connection)
        store.initialize()
        task_id = old[0][2]["id"]
        expected = connection.execute(
            "SELECT revision, operation, timestamp FROM events WHERE task_id=? ORDER BY revision",
            (task_id,),
        ).fetchall()
        history = store.run("history", {"task_id": task_id})["data"]
        assert [tuple(item.values()) for item in history["items"]] == expected
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6


@pytest.mark.parametrize(
    "failure", ["SELECT revision, state", "SELECT revision, operation", "COMMIT"]
)
def test_failed_history_releases_read_transaction(failure):
    with sqlite3.connect(":memory:", factory=MigrationFailure) as connection:
        store = TaskStore(connection)
        store.initialize()
        task = capture(store)
        before = snapshot(connection)
        connection.fail_at = failure
        with pytest.raises(TaskError, match="storage_error"):
            store.run("history", {"task_id": task["id"]})
        connection.fail_at = None
        assert not connection.in_transaction
        assert snapshot(connection) == before
        assert update(store, task)["revision"] == 2
