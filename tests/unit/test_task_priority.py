"""Explicit priorities, top-N snapshots and legacy byte/digest compatibility."""

import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest

from personal_agent import task_backup, tasks
from personal_agent.tasks import TaskError, TaskStore, validate_request


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    value = TaskStore(connection)
    value.initialize()
    yield value
    connection.close()


def capture(store, key, **fields):
    return store.run("capture", {"title": key, "request_id": key, **fields})["data"]


def test_priority_default_update_cas_and_replay(store):
    task = capture(store, "old")
    assert task["priority"] == "normal"
    request = {
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "priority",
        "priority": "high",
    }
    result = store.run("update", request)
    assert result["data"]["priority"] == "high" and result["data"]["revision"] == 2
    assert store.run("update", request) == {**result, "replayed": True}
    with pytest.raises(TaskError, match="revision_conflict"):
        store.run("update", {**request, "request_id": "stale", "priority": "low"})
    assert store.run("get", {"task_id": task["id"]})["data"] == result["data"]
    with pytest.raises(TaskError, match="idempotency_conflict"):
        store.run("capture", {"title": "old", "request_id": "old", "priority": "normal"})


@pytest.mark.parametrize("priority", [None, True, 1, "", "urgent", "High", [], {}])
def test_strict_priority_rejects_before_storage(priority):
    for operation, request in (
        ("capture", {"title": "x", "request_id": "r", "priority": priority}),
        (
            "update",
            {
                "task_id": str(uuid4()),
                "expected_revision": 1,
                "request_id": "r",
                "priority": priority,
            },
        ),
        (
            "capture_plan",
            {"project": "P", "request_id": "r", "tasks": [{"title": "x", "priority": priority}]},
        ),
    ):
        with pytest.raises(TaskError, match="invalid_request"):
            validate_request(operation, request)


def test_next_order_ties_filters_omission_and_ready_unchanged(store):
    values = [
        capture(store, "low", priority="low", due_date="2020-01-01", project="P"),
        capture(store, "normal", project="P"),
        capture(store, "high-undated", priority="high", project="P"),
        capture(store, "high-later", priority="high", due_date="2030-01-01", project="P"),
        capture(store, "high-earlier", priority="high", due_date="2029-01-01", project="P"),
        capture(store, "high-tie", priority="high", due_date="2029-01-01", project="P"),
    ]
    unrelated = capture(store, "unassigned", priority="high")
    result = store.run("next", {"project": "P", "limit": 3})["data"]
    assert [task["id"] for task in result["items"]] == [values[i]["id"] for i in (4, 5, 3)]
    assert (result["total"], result["omitted"], result["limit"]) == (6, 3, 3)
    assert "next_cursor" not in result and "has_more" not in result
    assert [task["id"] for task in store.run("ready", {"project": "P"})["data"]["items"]] == [
        v["id"] for v in values
    ]
    assert [task["id"] for task in store.run("next", {"unassigned": True})["data"]["items"]] == [
        unrelated["id"]
    ]
    assert store.run("next", {"project": "p"})["data"]["total"] == 0
    assert store.run("next", {})["data"]["limit"] == 5


def test_next_excludes_blocked_high_and_nonready_or_terminal(store):
    result = store.run(
        "capture_plan",
        {
            "project": "P",
            "request_id": "plan",
            "tasks": [
                {"title": "blocked", "priority": "high", "depends_on": [2]},
                {"title": "prerequisite", "priority": "low"},
                {"title": "normal"},
            ],
        },
    )["data"]["items"]
    blocked, prerequisite, normal = result
    assert [r["id"] for r in store.run("next", {})["data"]["items"]] == [
        normal["id"],
        prerequisite["id"],
    ]
    store.run(
        "progress",
        {
            "task_id": normal["id"],
            "expected_revision": 1,
            "request_id": "wait",
            "work_status": "waiting",
            "note": "manual",
        },
    )
    store.run(
        "complete",
        {
            "task_id": prerequisite["id"],
            "expected_revision": 1,
            "request_id": "done",
            "note": "explicit",
        },
    )
    assert [r["id"] for r in store.run("next", {})["data"]["items"]] == [blocked["id"]]
    children = store.run(
        "breakdown",
        {
            "task_id": blocked["id"],
            "expected_revision": 1,
            "request_id": "children",
            "tasks": [{"title": "child", "priority": "high"}, {"title": "other"}],
        },
    )["data"]["items"]
    assert [r["priority"] for r in children] == ["high", "normal"]
    assert store.run("get", {"task_id": blocked["id"]})["data"]["priority"] == "high"


@pytest.mark.parametrize(
    "payload",
    [
        {"limit": True},
        {"limit": 0},
        {"limit": 21},
        {"after": None},
        {"project": "P", "unassigned": False},
        {"priority": "high"},
    ],
)
def test_next_strict_nonpaginated_request(payload):
    with pytest.raises(TaskError, match="invalid_request"):
        validate_request("next", payload)


def legacy(connection, version=6):
    schema = getattr(tasks, f"_SCHEMA_V{version}")
    for statement in schema.values():
        connection.execute(statement)
    connection.execute(f"PRAGMA application_id={tasks._APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={version}")
    task_id = str(uuid4())
    connection.execute(
        "INSERT INTO tasks(id,title,details,state,revision,created_at,updated_at,source) "
        "VALUES (?, 'legacy','','captured',1,'then','then','local_cli')",
        (task_id,),
    )
    connection.execute("INSERT INTO events VALUES (?,1,'capture','then')", (task_id,))
    request = {"title": "legacy", "details": "", "request_id": "legacy"}
    digest = hashlib.sha256(
        json.dumps(
            ["capture", {"title": "legacy", "details": ""}],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    receipt = ' { "id": "' + task_id + '", "historical": true } '
    connection.execute("INSERT INTO receipts VALUES (?,?,?)", ("legacy", digest, receipt))
    connection.commit()
    return task_id, request, receipt


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6])
def test_all_legacy_migrations_preserve_exact_receipt_and_omitted_digest(version):
    connection = sqlite3.connect(":memory:")
    task_id, request, receipt = legacy(connection, version)
    before = connection.execute("SELECT * FROM receipts").fetchall()
    store = TaskStore(connection)
    store.initialize()
    assert connection.execute("PRAGMA user_version").fetchone() == (8,)
    assert connection.execute("SELECT * FROM receipts").fetchall() == before
    assert store.run("capture", request) == {"data": json.loads(receipt), "replayed": True}
    assert store.run("get", {"task_id": task_id})["data"]["priority"] == "normal"
    assert "priority" not in validate_request("capture", request)
    assert (
        "priority"
        not in validate_request(
            "capture_plan", {"project": "P", "request_id": "p", "tasks": [{"title": "x"}]}
        )["tasks"][0]
    )
    connection.close()


def test_historical_v6_backup_read_is_nonmigrating(tmp_path):
    path = tmp_path / "snapshot.sqlite3"
    connection = sqlite3.connect(path)
    task_id, _, _ = legacy(connection)
    connection.close()
    before = path.read_bytes()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    connection.execute("BEGIN")
    with pytest.raises(TaskError, match="unsupported_schema"):
        tasks.inspect_task_snapshot(connection)
    assert tasks.inspect_task_snapshot(connection, historical=True)["database_version"] == 6
    row = task_backup._read_tasks(connection, "show", after=None, limit=1, task_id=task_id)["task"]
    assert row["priority"] == "normal"
    connection.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "fail_at", ["ALTER TABLE tasks ADD COLUMN priority", "PRAGMA user_version = 8", "COMMIT"]
)
def test_v6_upgrade_failure_rolls_back_exact_bytes(tmp_path, fail_at):
    class Failing(sqlite3.Connection):
        failure = None

        def execute(self, sql, *args, **kwargs):
            if self.failure and sql.startswith(self.failure):
                raise sqlite3.OperationalError("synthetic failure")
            return super().execute(sql, *args, **kwargs)

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path, factory=Failing)
    task_id, _, _ = legacy(connection)
    before = path.read_bytes()
    connection.failure = fail_at
    with pytest.raises(TaskError, match="storage_error"):
        TaskStore(connection).initialize()
    assert path.read_bytes() == before
    assert connection.execute("PRAGMA user_version").fetchone() == (6,)
    connection.failure = None
    store = TaskStore(connection)
    store.initialize()
    assert store.run("get", {"task_id": task_id})["data"]["priority"] == "normal"
    connection.close()


def test_old_plan_breakdown_update_receipts_replay_without_priority_injection():
    connection = sqlite3.connect(":memory:")
    task_id, _, _ = legacy(connection)
    requests = [
        (
            "capture_plan",
            {"project": "P", "tasks": [{"title": "one", "details": ""}], "request_id": "plan"},
        ),
        (
            "breakdown",
            {
                "task_id": task_id,
                "expected_revision": 1,
                "tasks": [{"title": "child", "details": ""}],
                "request_id": "breakdown",
            },
        ),
        (
            "update",
            {"task_id": task_id, "expected_revision": 1, "details": "edit", "request_id": "update"},
        ),
    ]
    for operation, request in requests:
        digest = hashlib.sha256(
            json.dumps(
                [operation, {k: v for k, v in request.items() if k != "request_id"}],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        connection.execute(
            "INSERT INTO receipts VALUES (?,?,?)",
            (request["request_id"], digest, ' { "legacy": true } '),
        )
    connection.commit()
    before = connection.execute("SELECT * FROM receipts ORDER BY request_id").fetchall()
    store = TaskStore(connection)
    store.initialize()
    for operation, request in requests:
        assert store.run(operation, request) == {"data": {"legacy": True}, "replayed": True}
    assert connection.execute("SELECT * FROM receipts ORDER BY request_id").fetchall() == before
    connection.close()
