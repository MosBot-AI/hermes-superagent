"""Explicit local progress, exact legacy migration and durable retry contracts."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from test_task_agenda import MigrationFailure, snapshot
from test_task_projects import seed_legacy

from personal_agent.conversation_tasks import _parse
from personal_agent.task_tool_contract import normalize_task_tool_request
from personal_agent.tasks import TaskError, TaskStore, validate_request

STATUSES = ("ready", "in_progress", "waiting", "blocked")
ON = "2026-11-07"


@pytest.fixture
def store():
    with sqlite3.connect(":memory:") as connection:
        result = TaskStore(connection)
        result.initialize()
        yield result


def capture(store, **extra):
    return store.run("capture", {"title": "Synthetic", "request_id": str(uuid4()), **extra})["data"]


def request(task, work_status="blocked", note="Waiting for input", **extra):
    return {
        "task_id": task["id"],
        "expected_revision": task["revision"],
        "request_id": str(uuid4()),
        "work_status": work_status,
        "note": note,
        **extra,
    }


def progress(store, task, **extra):
    return store.run("progress", request(task, **extra))["data"]


def test_progress_lifecycle_does_not_execute_or_resolve_and_preserves_updates(store):
    task = capture(store, due_date=ON, project="Demo")
    assert task["work_status"] == "ready" and task["progress_note"] == ""
    assert task["progress_updated_at"] is None
    for index, status in enumerate(("in_progress", "waiting", "blocked", "ready"), 2):
        task = progress(store, task, work_status=status, note=f"Explicit {status}")
        assert task["work_status"] == status and task["progress_note"] == f"Explicit {status}"
        assert task["revision"] == index and task["state"] == "captured"
        assert task["progress_updated_at"] == task["updated_at"]
        assert task["resolved_at"] is None and task["resolution_note"] is None
        assert task["due_date"] == ON and task["project"] == "Demo"
    old = dict(task)
    task = store.run(
        "update",
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": "edit",
            "title": "Edited",
        },
    )["data"]
    for key in ("work_status", "progress_note", "progress_updated_at"):
        assert task[key] == old[key]
    history = store.run("history", {"task_id": task["id"]})["data"]
    assert [item["operation"] for item in history["items"]] == [
        "capture",
        *(["progress"] * 4),
        "update",
    ]
    assert "Explicit" not in json.dumps(history)


@pytest.mark.parametrize("operation", ["complete", "cancel"])
def test_terminal_state_preserves_last_progress_but_refuses_new_progress(store, operation):
    task = progress(store, capture(store))
    done = store.run(
        operation,
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": "finish",
            "note": "Resolved",
        },
    )["data"]
    assert done["work_status"] == "blocked"
    assert done["progress_note"] == task["progress_note"]
    assert done["progress_updated_at"] == task["progress_updated_at"]
    assert done["resolution_note"] == "Resolved"
    with pytest.raises(TaskError, match="terminal_state"):
        progress(store, done, work_status="ready")
    assert store.run("list", {"work_status": "blocked"})["data"]["items"] == []
    assert store.run("review", {"on": ON})["data"]["progress_counts"]["blocked"] == 0


def test_durable_replay_unchanged_after_later_edits_and_restart(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        task = capture(store)
        args = request(task, request_id="stable")
        first = store.run("progress", args)
        assert not first["replayed"]
        assert store.run("progress", args) == {**first, "replayed": True}
        task = progress(store, first["data"], work_status="in_progress", note="Resumed")
        before = snapshot(connection)
        with pytest.raises(TaskError, match="idempotency_conflict"):
            store.run("progress", {**args, "note": "Different"})
        with pytest.raises(TaskError, match="revision_conflict"):
            store.run("progress", {**args, "request_id": "stale"})
        assert snapshot(connection) == before
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        assert store.run("progress", args) == {**first, "replayed": True}
        assert store.run("get", {"task_id": task["id"]})["data"] == task
        assert len(store.run("history", {"task_id": task["id"]})["data"]["items"]) == 3


@pytest.mark.parametrize(
    "operation,extra",
    [
        ("list", {}),
        ("search", {"query": "Synthetic"}),
        ("agenda", {"on": ON}),
        ("review", {"on": ON}),
    ],
)
def test_work_status_filters_combine_with_exact_project_without_note_search(
    store, operation, extra
):
    tasks = {}
    for status in STATUSES:
        tasks[status] = progress(
            store,
            capture(store, project="Demo", due_date=ON),
            work_status=status,
            note="Secret blocker note",
        )
        progress(store, capture(store, project="demo", due_date=ON), work_status=status)
    progress(store, capture(store, due_date=ON))
    for status, task in tasks.items():
        result = store.run(operation, {**extra, "work_status": status, "project": "Demo"})["data"]
        if operation == "review":
            assert result["filters"] == {"project": "Demo", "work_status": status}
            assert result["counts"]["total_active"] == 1
            assert sum(result["progress_counts"].values()) == 1
            assert result["progress_counts"][status] == 1
            assert result["buckets"]["due_today"]["items"][0]["work_status"] == status
            assert "Secret" not in json.dumps(result)
        else:
            assert result["items"] == [task]
    assert store.run("search", {"query": "Secret blocker"})["data"]["items"] == []
    plain = store.run("list", {"unassigned": True, "work_status": "blocked"})["data"]
    assert len(plain["items"]) == 1
    if operation == "review":
        totals = store.run("review", {"on": ON})["data"]["progress_counts"]
        assert totals == {"ready": 2, "in_progress": 2, "waiting": 2, "blocked": 3}


@pytest.mark.parametrize(
    "field,value",
    [
        ("work_status", None),
        ("work_status", True),
        ("work_status", []),
        ("work_status", "done"),
        ("work_status", "active"),
        ("work_status", " blocked"),
        ("work_status", "BLOCKED"),
        ("note", ""),
        ("note", " "),
        ("note", "x" * 2001),
        ("note", None),
        ("note", "unsafe\u200bnote"),
        ("expected_revision", True),
        ("expected_revision", 0),
        ("request_id", ""),
        ("task_id", "invented"),
        ("title", "extra"),
        ("project", "extra"),
        ("due_date", ON),
        ("approved", True),
    ],
)
def test_invalid_progress_rejected_before_storage(field, value):
    args = (
        request({"id": str(uuid4()), "revision": 1}, **{field: value})
        if field not in ("work_status", "note")
        else request({"id": str(uuid4()), "revision": 1}) | {field: value}
    )
    with pytest.raises(TaskError, match="invalid_request"):
        TaskStore(sqlite3.connect(":memory:")).run("progress", args)
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_write", {"action": "progress", **args})


@pytest.mark.parametrize(
    "field", ["task_id", "expected_revision", "request_id", "work_status", "note"]
)
def test_every_progress_field_is_required(field):
    args = request({"id": str(uuid4()), "revision": 1})
    del args[field]
    with pytest.raises(TaskError, match="invalid_request"):
        validate_request("progress", args)


def test_entrypoint_normalization_stable_keys_and_no_accidental_update_access(store):
    task = capture(store)
    args = request(task, request_id="explicit")
    original = dict(args)
    assert normalize_task_tool_request("personal_tasks_write", {"action": "progress", **args}) == (
        "progress",
        args,
    )
    assert args == original
    raw = (
        f"progress {task['id']} --expected-revision 1 --work-status blocked "
        '--note "Waiting for input"'
    )
    operation, implicit, output_format = _parse(raw)
    assert output_format is None
    assert operation == "progress" and len(implicit["request_id"]) == 36
    assert _parse(raw + " --request-id explicit") == ("progress", args, None)
    assert _parse(f"review --on {ON} --work-status waiting")[1]["work_status"] == "waiting"
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_read", {"action": "progress", **args})
    for action in ("capture", "update"):
        payload = {"title": "Synthetic", "request_id": "bad", "work_status": "blocked"}
        if action == "update":
            payload.update(task_id=task["id"], expected_revision=1)
        with pytest.raises(TaskError, match="invalid_request"):
            validate_request(action, payload)
    for operation in ("list", "search"):
        for state in ("all", "done", "cancelled"):
            with pytest.raises(TaskError, match="invalid_request"):
                validate_request(
                    operation,
                    {
                        "state": state,
                        "work_status": "blocked",
                        **({"query": "x"} if operation == "search" else {}),
                    },
                )


def test_concurrent_progress_only_one_revision_wins(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        task = capture(store)
    barrier = Barrier(2)

    def mutate(index):
        with sqlite3.connect(path, timeout=5) as connection:
            store = TaskStore(connection)
            store.initialize()
            barrier.wait(timeout=10)
            try:
                return progress(store, task, note=f"Competing {index}")["revision"]
            except TaskError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(map(str, pool.map(mutate, range(2)))) == ["2", "revision_conflict"]
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM receipts").fetchone()[0] == 2


@pytest.mark.parametrize(
    "failure", ["UPDATE tasks", "INSERT INTO events", "INSERT INTO receipts", "COMMIT"]
)
def test_progress_failures_roll_back_every_change_and_allow_identical_retry(failure):
    with sqlite3.connect(":memory:", factory=MigrationFailure) as connection:
        store = TaskStore(connection)
        store.initialize()
        task = capture(store)
        before = snapshot(connection)
        args = request(task)
        connection.fail_at = failure
        with pytest.raises(TaskError, match="storage_error"):
            store.run("progress", args)
        connection.fail_at = None
        assert not connection.in_transaction and snapshot(connection) == before
        assert store.run("progress", args)["data"]["revision"] == 2


def seed_old(connection, version):
    # Build independent shipped v1/v2 DDL and append exactly the v3 project column.
    history = seed_legacy(connection, min(version, 2))
    if version == 3:
        connection.execute("ALTER TABLE tasks ADD COLUMN project TEXT")
        connection.execute("PRAGMA user_version = 3")
        task = {**history[-1][2], "project": "Legacy", "revision": 3}
        args = {
            "task_id": task["id"],
            "expected_revision": 2,
            "request_id": "v3",
            "project": "Legacy",
        }
        digest = hashlib.sha256(
            json.dumps(
                ["update", {k: v for k, v in args.items() if k != "request_id"}],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).hexdigest()
        connection.execute(
            "UPDATE tasks SET project=?,revision=3 WHERE id=?", ("Legacy", task["id"])
        )
        connection.execute("INSERT INTO receipts VALUES (?,?,?)", ("v3", digest, json.dumps(task)))
        connection.execute("INSERT INTO events VALUES (?,3,'update','synthetic')", (task["id"],))
        history.append(("update", args, task))
        connection.commit()
    return history


@pytest.mark.parametrize("version", [1, 2, 3])
def test_exact_old_upgrade_preserves_receipts_events_order_and_supports_progress(tmp_path, version):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path) as connection:
        history = seed_old(connection, version)
        before = snapshot(connection)
        store = TaskStore(connection)
        store.initialize()
        after = snapshot(connection)
        assert after["version"] == 5
        for table in ("events", "receipts", "sqlite_sequence"):
            assert before[table] == after[table]
        assert after["tasks"] == [
            (*row, *((None,) * (3 - version)), "ready", "", None) for row in before["tasks"]
        ]
        for operation, args, receipt in history:
            assert store.run(operation, args) == {"data": receipt, "replayed": True}
        task = store.run("list", {})["data"]["items"][0]
        assert progress(store, task)["progress_note"] == "Waiting for input"
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        assert store.run("list", {"work_status": "blocked"})["data"]["items"]


@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize(
    "failure",
    [
        "ALTER TABLE tasks ADD COLUMN work_status",
        "ALTER TABLE tasks ADD COLUMN progress_note",
        "ALTER TABLE tasks ADD COLUMN progress_updated_at",
        "PRAGMA user_version = 5",
        "COMMIT",
    ],
)
def test_progress_migration_failure_is_atomic(tmp_path, version, failure):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path, factory=MigrationFailure) as connection:
        history = seed_old(connection, version)
        before, raw = snapshot(connection), path.read_bytes()
        connection.fail_at = failure
        store = TaskStore(connection)
        with pytest.raises(TaskError, match="storage_error"):
            store.initialize()
        connection.fail_at = None
        assert snapshot(connection) == before and path.read_bytes() == raw
        assert not connection.in_transaction
        store.initialize()
        assert store.run("capture", history[0][1])["replayed"]


def test_review_progress_counts_and_summaries_share_current_snapshot(tmp_path):
    class Interleaved(sqlite3.Connection):
        mutate = None

        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT id,title,project") and self.mutate:
                callback, self.mutate = self.mutate, None
                callback()
            return super().execute(sql, parameters)

    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path, factory=Interleaved) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        reader = TaskStore(connection)
        reader.initialize()
        task = capture(reader, due_date=ON)
        with sqlite3.connect(path) as writer_connection:
            writer = TaskStore(writer_connection)
            writer.initialize()
            connection.mutate = lambda: progress(writer, task)
            first = reader.run("review", {"on": ON})["data"]
            assert first["progress_counts"]["ready"] == 1
            assert first["buckets"]["due_today"]["items"][0]["work_status"] == "ready"
            second = reader.run("review", {"on": ON})["data"]
            assert second["progress_counts"]["blocked"] == 1
            assert second["buckets"]["due_today"]["items"][0]["work_status"] == "blocked"


@pytest.mark.parametrize(
    "operation,extra",
    [
        ("list", {}),
        ("search", {"query": "Synthetic"}),
        ("agenda", {"on": ON}),
        ("review", {"on": ON}),
    ],
)
@pytest.mark.parametrize("status", [None, True, [], "done", " active", "BLOCKED"])
def test_invalid_read_status_filter_rejected_before_storage(operation, extra, status):
    with pytest.raises(TaskError, match="invalid_request"):
        TaskStore(sqlite3.connect(":memory:")).run(operation, {**extra, "work_status": status})


def test_minimum_review_budget_preserves_progress_counts_and_complete_summaries(store):
    task = capture(store, project="\U0001f4cb" * 80, title="\U0001f4cb" * 240, due_date=ON)
    progress(store, task, work_status="in_progress", note="Private progress note")
    result = store.run(
        "review",
        {"on": ON, "work_status": "in_progress", "project": "\U0001f4cb" * 80, "max_chars": 2048},
    )["data"]
    assert len(json.dumps(result, ensure_ascii=True, sort_keys=True)) <= 2048
    assert result["progress_counts"]["in_progress"] == 1
    assert result["buckets"]["due_today"] == {"total": 1, "items": [], "omitted": 1}
    assert "Private" not in json.dumps(result)
