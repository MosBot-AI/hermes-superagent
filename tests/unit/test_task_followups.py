"""Explicit follow-up dates: no clock polling, reminders, dispatch or hidden writes."""

import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from test_task_priority import legacy

from personal_agent import task_backup, tasks
from personal_agent.tasks import TaskError, TaskStore, validate_request


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    value = TaskStore(connection)
    value.initialize()
    yield value
    connection.close()


def capture(store, key="task", **fields):
    return store.run("capture", {"title": key, "request_id": key, **fields})["data"]


def progress(store, task, status="waiting", **fields):
    return store.run(
        "progress",
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": str(uuid4()),
            "work_status": status,
            "note": "explicit",
            **fields,
        },
    )["data"]


def test_waiting_blocked_preservation_clear_and_replay(store):
    task = capture(store)
    assert task["follow_up_on"] is None
    task = progress(store, task, follow_up_on="2030-01-02")
    assert task["follow_up_on"] == "2030-01-02"
    task = progress(store, task, "blocked")
    assert task["follow_up_on"] == "2030-01-02"
    request = {
        "task_id": task["id"],
        "expected_revision": task["revision"],
        "request_id": "date",
        "follow_up_on": "2030-01-03",
    }
    updated = store.run("update", request)
    assert updated["data"]["follow_up_on"] == "2030-01-03"
    assert store.run("update", request) == {**updated, "replayed": True}
    with pytest.raises(TaskError, match="revision_conflict"):
        store.run("update", {**request, "request_id": "stale"})
    task = progress(store, updated["data"], "waiting", follow_up_on=None)
    assert task["follow_up_on"] is None
    assert store.run("followups", {"on": "9999-12-31"})["data"]["items"] == []


@pytest.mark.parametrize("status", ["ready", "in_progress"])
def test_return_to_actionable_clears_atomically_and_refuses_explicit_date(store, status):
    task = progress(store, capture(store), follow_up_on="2030-01-02")
    with pytest.raises(TaskError, match="follow_up_status_required"):
        progress(store, task, status, follow_up_on="2030-01-03")
    assert store.run("get", {"task_id": task["id"]})["data"] == task
    changed = progress(store, task, status)
    assert changed["follow_up_on"] is None and changed["work_status"] == status


@pytest.mark.parametrize("operation", ["complete", "cancel"])
def test_terminal_mutations_clear_followup(store, operation):
    task = progress(store, capture(store), follow_up_on="2030-01-02")
    result = store.run(
        operation,
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": "terminal",
            "note": "explicit",
        },
    )["data"]
    assert result["follow_up_on"] is None
    assert not store.run("followups", {"on": "9999-12-31"})["data"]["items"]


def test_update_date_requires_waiting_or_blocked(store):
    task = capture(store)
    request = {
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "date",
        "follow_up_on": "2030-01-02",
    }
    with pytest.raises(TaskError, match="follow_up_status_required"):
        store.run("update", request)
    assert store.run("get", {"task_id": task["id"]})["data"] == task
    assert store.run("update", {**request, "follow_up_on": None})["data"]["follow_up_on"] is None


@pytest.mark.parametrize(
    "bad", [True, 1, "2030-1-01", "2030-02-30", "2030-01-01T00:00:00Z", "", [], {}]
)
def test_strict_dates(bad):
    with pytest.raises(TaskError, match="invalid_request"):
        validate_request("followups", {"on": bad})
    with pytest.raises(TaskError, match="invalid_request"):
        validate_request(
            "update",
            {
                "task_id": str(uuid4()),
                "expected_revision": 1,
                "request_id": "r",
                "follow_up_on": bad,
            },
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"on": "2030-01-01", "limit": True},
        {"on": "2030-01-01", "limit": 0},
        {"on": "2030-01-01", "limit": 101},
        {"on": "2030-01-01", "after": None},
        {"on": "2030-01-01", "project": "P", "unassigned": True},
    ],
)
def test_strict_nonpaginated_query(payload):
    with pytest.raises(TaskError, match="invalid_request"):
        validate_request("followups", payload)


def test_capture_plan_breakdown_and_recovery_reject_followup_payload():
    for operation, payload in (
        ("capture", {"title": "x", "request_id": "r", "follow_up_on": None}),
        (
            "capture_plan",
            {"project": "P", "request_id": "r", "tasks": [{"title": "x", "follow_up_on": None}]},
        ),
        (
            "breakdown",
            {
                "task_id": str(uuid4()),
                "expected_revision": 1,
                "request_id": "r",
                "tasks": [{"title": "x", "follow_up_on": None}],
            },
        ),
        (
            "recover_copy",
            {
                "title": "x",
                "request_id": "r",
                "backup_sha256": "a" * 64,
                "original_task_id": str(uuid4()),
                "follow_up_on": None,
            },
        ),
    ):
        with pytest.raises(TaskError, match="invalid_request"):
            validate_request(operation, payload)


def test_followups_order_counts_cutoff_filters_and_read_only(store):
    rows = []
    for key, priority, date in [
        ("early-low", "low", "2029-01-01"),
        ("high1", "high", "2030-01-01"),
        ("normal", "normal", "2030-01-01"),
        ("high2", "high", "2030-01-01"),
        ("future", "high", "2030-01-02"),
    ]:
        rows.append(
            progress(store, capture(store, key, priority=priority, project="P"), follow_up_on=date)
        )
    unassigned = progress(store, capture(store, "unassigned"), "blocked", follow_up_on="2030-01-01")
    capture(store, "ready", priority="high", project="P")
    progress(store, capture(store, "no-date", project="P"))
    before = list(store._connection.iterdump())
    result = store.run("followups", {"on": "2030-01-01", "project": "P", "limit": 2})["data"]
    assert [r["id"] for r in result["items"]] == [rows[0]["id"], rows[1]["id"]]
    assert (result["total"], result["omitted"], result["limit"]) == (4, 2, 2)
    assert result["on"] == "2030-01-01" and "after" not in result and "next_cursor" not in result
    full = store.run("followups", {"on": "2030-01-01", "project": "P"})["data"]
    assert [r["id"] for r in full["items"]] == [rows[i]["id"] for i in (0, 1, 3, 2)]
    assert full["limit"] == 20
    assert store.run("followups", {"on": "2030-01-01", "project": "p"})["data"]["total"] == 0
    assert [
        r["id"]
        for r in store.run("followups", {"on": "2030-01-01", "unassigned": True})["data"]["items"]
    ] == [unassigned["id"]]
    assert list(store._connection.iterdump()) == before
    assert [r["title"] for r in store.run("next", {"project": "P"})["data"]["items"]] == ["ready"]


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5, 6, 7])
def test_legacy_migration_receipt_bytes_and_omitted_followup_digest(version):
    connection = sqlite3.connect(":memory:")
    task_id, request, receipt = legacy(connection, version)
    progress_request = {
        "task_id": task_id,
        "expected_revision": 1,
        "request_id": "old-progress",
        "work_status": "waiting",
        "note": "old",
    }
    digest = hashlib.sha256(
        json.dumps(
            ["progress", {k: v for k, v in progress_request.items() if k != "request_id"}],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    connection.execute(
        "INSERT INTO receipts VALUES (?,?,?)", ("old-progress", digest, ' { "old": true } ')
    )
    connection.commit()
    before = connection.execute("SELECT * FROM receipts").fetchall()
    store = TaskStore(connection)
    store.initialize()
    assert connection.execute("PRAGMA user_version").fetchone() == (8,)
    assert store.run("get", {"task_id": task_id})["data"]["follow_up_on"] is None
    assert store.run("capture", request) == {"data": json.loads(receipt), "replayed": True}
    assert store.run("progress", progress_request) == {"data": {"old": True}, "replayed": True}
    assert connection.execute("SELECT * FROM receipts").fetchall() == before
    assert "follow_up_on" not in validate_request("progress", progress_request)
    connection.close()


@pytest.mark.parametrize("version", [6, 7])
def test_historical_backups_default_null_without_migration(tmp_path, version):
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    task_id, _, _ = legacy(connection, version)
    connection.close()
    before = path.read_bytes()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
    connection.execute("BEGIN")
    assert tasks.inspect_task_snapshot(connection, historical=True)["database_version"] == version
    assert (
        task_backup._read_tasks(connection, "show", after=None, limit=1, task_id=task_id)["task"][
            "follow_up_on"
        ]
        is None
    )
    connection.close()
    assert path.read_bytes() == before


def test_native_review_completion_clears_followup():
    from test_task_result_review import setup, store

    from personal_agent.task_result_review import preview

    value = store()
    task, evidence, request = setup(value)
    task = progress(value, task, follow_up_on="2030-01-02")
    request = {
        **request,
        "expected_revision": task["revision"],
        "expected_digest": preview(task, evidence)["review_digest"],
    }
    value.accept_native_review(request, lambda _: evidence)
    assert value.run("get", {"task_id": task["id"]})["data"]["follow_up_on"] is None


@pytest.mark.parametrize(
    "fail_at", ["ALTER TABLE tasks ADD COLUMN follow_up_on", "PRAGMA user_version = 8", "COMMIT"]
)
def test_v7_followup_migration_is_atomic(tmp_path, fail_at):
    class Failing(sqlite3.Connection):
        failure = None

        def execute(self, sql, *args, **kwargs):
            if self.failure and sql.startswith(self.failure):
                raise sqlite3.OperationalError("synthetic failure")
            return super().execute(sql, *args, **kwargs)

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path, factory=Failing)
    task_id, _, _ = legacy(connection, 7)
    before = path.read_bytes()
    connection.failure = fail_at
    with pytest.raises(TaskError, match="storage_error"):
        TaskStore(connection).initialize()
    assert path.read_bytes() == before
    connection.failure = None
    value = TaskStore(connection)
    value.initialize()
    assert value.run("get", {"task_id": task_id})["data"]["follow_up_on"] is None
    connection.close()


def test_malformed_stored_followup_cannot_hide_behind_cutoff(store):
    task = progress(store, capture(store), follow_up_on="2030-01-01")
    store._connection.execute(
        "UPDATE tasks SET follow_up_on=? WHERE id=?", ("zzzz-invalid", task["id"])
    )
    store._connection.commit()
    with pytest.raises(TaskError, match="storage_corrupt"):
        store.run("followups", {"on": "2020-01-01"})
