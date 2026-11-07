"""Bounded daily planning reads, exact counts, privacy and snapshot consistency."""

import json
import sqlite3

import pytest
from test_task_agenda import MigrationFailure, snapshot
from test_task_projects import seed_legacy

from personal_agent.conversation_tasks import _parse
from personal_agent.task_tool_contract import normalize_task_tool_request
from personal_agent.tasks import TaskError, TaskStore, validate_request

ON = "2026-11-07"


@pytest.fixture
def store():
    with sqlite3.connect(":memory:") as connection:
        result = TaskStore(connection)
        result.initialize()
        yield result


def capture(store, key, due=None, **extra):
    args = {"title": key, "details": "Private details not included", "request_id": key, **extra}
    if due is not None:
        args["due_date"] = due
    return store.run("capture", args)["data"]


def review(store, **extra):
    return store.run("review", {"on": ON, **extra})["data"]


def test_all_buckets_counts_date_edges_order_and_minimal_summaries(store):
    # Capture out of due order to verify ordering is not newest-first.
    capture(store, "overdue-newer", "2026-11-06")
    oldest = capture(store, "overdue-oldest", "2020-01-01", project="Work")
    capture(store, "today-first", ON)
    capture(store, "today-second", ON)
    capture(store, "soon-last", "2026-11-14")
    capture(store, "soon-first", "2026-11-08")
    capture(store, "later", "2026-11-15")
    capture(store, "undated-first")
    capture(store, "undated-second")
    for action in ("complete", "cancel"):
        task = capture(store, action, ON)
        store.run(
            action,
            {
                "task_id": task["id"],
                "expected_revision": 1,
                "request_id": action + "-write",
                "note": "Private note",
            },
        )
    before = snapshot(store._connection)
    result = review(store)
    assert result["on"] == ON and result["through"] == "2026-11-14"
    assert result["counts"] == {
        "total_active": 9,
        "overdue": 2,
        "due_today": 2,
        "upcoming": 2,
        "later": 1,
        "undated": 2,
    }
    assert result["filters"] == {}
    assert result["buckets"]["overdue"]["items"][0] == {
        key: oldest[key]
        for key in ("id", "title", "project", "due_date", "revision", "work_status")
    }
    expected = {
        "overdue": ["overdue-oldest", "overdue-newer"],
        "due_today": ["today-first", "today-second"],
        "upcoming": ["soon-first", "soon-last"],
        "undated": ["undated-first", "undated-second"],
    }
    for name, titles in expected.items():
        bucket = result["buckets"][name]
        assert [item["title"] for item in bucket["items"]] == titles
        assert bucket["total"] == 2 and bucket["omitted"] == 0
    assert "Private" not in json.dumps(result)
    assert snapshot(store._connection) == before
    assert not store._connection.in_transaction


def test_empty_and_per_bucket_limits_leave_exact_counts(store):
    empty = review(store)
    assert all(count == 0 for count in empty["counts"].values())
    assert all(
        bucket == {"total": 0, "items": [], "omitted": 0} for bucket in empty["buckets"].values()
    )
    for i in range(22):
        capture(store, f"task-{i}", ON)
    for limit, expected in ((None, 5), (1, 1), (20, 20)):
        result = review(store, **({} if limit is None else {"per_bucket_limit": limit}))
        bucket = result["buckets"]["due_today"]
        assert len(bucket["items"]) == expected
        assert bucket["total"] == 22 and bucket["omitted"] == 22 - expected


def test_budget_counts_ascii_escaping_and_never_truncates_summary(store):
    for i in range(8):
        capture(store, f"long-{i}", ON, title="\U0001f4cb" * 240, project="\U0001f4cb" * 80)
    short = capture(store, "short-undated")
    result = review(store, max_chars=2048, per_bucket_limit=20)
    assert len(json.dumps(result, ensure_ascii=True, sort_keys=True)) <= 2048
    assert result["buckets"]["due_today"] == {"total": 8, "items": [], "omitted": 8}
    assert result["buckets"]["undated"]["items"][0]["id"] == short["id"]
    filtered = review(store, max_chars=2048, project="\U0001f4cb" * 80)
    assert len(json.dumps(filtered, ensure_ascii=True, sort_keys=True)) <= 2048
    assert filtered["counts"]["total_active"] == 8
    wide = review(store, max_chars=64000, per_bucket_limit=20)
    assert len(wide["buckets"]["due_today"]["items"]) == 8
    assert all(
        item["title"] == "\U0001f4cb" * 240 for item in wide["buckets"]["due_today"]["items"]
    )


def test_exact_project_filters_unassigned_and_updated_current_revision(store):
    for key, project in (("upper", "Work"), ("lower", "work"), ("literal", "w%_")):
        capture(store, key, ON, project=project)
    task = capture(store, "unassigned", ON)
    assert review(store, project="Work")["counts"]["total_active"] == 1
    assert review(store, project="w%_")["buckets"]["due_today"]["items"][0]["title"] == "literal"
    assert review(store, project="unknown")["counts"]["total_active"] == 0
    assert review(store, unassigned=False)["counts"]["total_active"] == 4
    assert review(store, unassigned=True)["counts"]["total_active"] == 1
    store.run(
        "update",
        {
            "task_id": task["id"],
            "expected_revision": 1,
            "request_id": "change",
            "project": "Work",
            "due_date": "2026-11-08",
            "title": "Changed",
        },
    )
    changed = review(store, project="Work")
    assert changed["filters"] == {"project": "Work"}
    assert changed["counts"]["total_active"] == 2
    assert changed["buckets"]["upcoming"]["items"][0]["revision"] == 2
    assert review(store, unassigned=True)["counts"]["total_active"] == 0


def test_explicit_dates_lookahead_and_leap_year(store):
    capture(store, "leap", "2028-02-29")
    capture(store, "march", "2028-03-01")
    result = store.run("review", {"on": "2028-02-28", "lookahead_days": 1})["data"]
    assert result["through"] == "2028-02-29" and result["counts"]["upcoming"] == 1
    assert result["counts"]["later"] == 1
    zero = store.run("review", {"on": "2028-02-29", "lookahead_days": 0})["data"]
    assert zero["counts"]["due_today"] == 1 and zero["counts"]["upcoming"] == 0
    assert validate_request("review", {"on": "9999-12-31", "lookahead_days": 0})


@pytest.mark.parametrize(
    "extra",
    [
        {"on": "tomorrow"},
        {"on": "2026-02-29"},
        {"on": "9999-12-31"},
        {"lookahead_days": -1},
        {"lookahead_days": 91},
        {"lookahead_days": True},
        {"lookahead_days": 1.0},
        {"lookahead_days": "7"},
        {"lookahead_days": None},
        {"per_bucket_limit": 0},
        {"per_bucket_limit": 21},
        {"per_bucket_limit": True},
        {"per_bucket_limit": None},
        {"max_chars": 2047},
        {"max_chars": 64001},
        {"max_chars": True},
        {"max_chars": "2048"},
        {"max_chars": None},
        {"project": " Work"},
        {"project": None},
        {"project": "Work", "unassigned": False},
        {"unassigned": 1},
        {"limit": 5},
        {"after": None},
        {"state": "all"},
        {"owner": "x"},
        {"request_id": "read"},
    ],
)
def test_validation_precedes_storage_and_is_shared(extra):
    request = {"on": ON, **extra}
    with pytest.raises(TaskError, match="invalid_request"):
        TaskStore(sqlite3.connect(":memory:")).run("review", request)
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_read", {"action": "review", **request})


def test_cli_slash_and_model_normalization_without_mutation():
    request = {"on": ON, "project": "Work"}
    normalized = validate_request("review", request)
    assert normalized == {**request, "lookahead_days": 7, "per_bucket_limit": 5, "max_chars": 16000}
    assert request == {"on": ON, "project": "Work"}
    assert _parse(f'review --on {ON} --project "Work"') == ("review", normalized)
    assert normalize_task_tool_request("personal_tasks_read", {"action": "review", **request}) == (
        "review",
        normalized,
    )
    for tool in ("personal_tasks_read", "personal_tasks_write"):
        with pytest.raises(TaskError, match="invalid_request"):
            normalize_task_tool_request(tool, {"action": "review"})
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_write", {"action": "review", **request})


def test_counts_and_summaries_share_snapshot_across_concurrent_edit(tmp_path):
    class InterleavedConnection(sqlite3.Connection):
        append = None

        def execute(self, sql, parameters=()):
            if sql.startswith("SELECT id,title,project") and self.append is not None:
                callback, self.append = self.append, None
                callback()
            return super().execute(sql, parameters)

    path = tmp_path / "concurrent.sqlite3"
    with sqlite3.connect(path, factory=InterleavedConnection) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        reader = TaskStore(connection)
        reader.initialize()
        task = capture(reader, "original", ON)
        with sqlite3.connect(path) as writer_connection:
            writer = TaskStore(writer_connection)
            writer.initialize()
            connection.append = lambda: writer.run(
                "complete",
                {
                    "task_id": task["id"],
                    "expected_revision": 1,
                    "request_id": "finish",
                    "note": "Done",
                },
            )
            first = review(reader)
            assert first["counts"]["due_today"] == 1
            assert first["buckets"]["due_today"]["items"][0]["revision"] == 1
            assert review(reader)["counts"]["total_active"] == 0


@pytest.mark.parametrize("failure", ["SELECT count", "SELECT id,title,project", "COMMIT"])
def test_failed_review_releases_transaction_without_mutation(failure):
    with sqlite3.connect(":memory:", factory=MigrationFailure) as connection:
        store = TaskStore(connection)
        store.initialize()
        capture(store, "one", ON)
        before = snapshot(connection)
        connection.fail_at = failure
        with pytest.raises(TaskError, match="storage_error"):
            review(store)
        connection.fail_at = None
        assert not connection.in_transaction
        assert snapshot(connection) == before
        assert review(store)["counts"]["total_active"] == 1


@pytest.mark.parametrize("version", [1, 2])
def test_review_survives_legacy_upgrade_and_restart(tmp_path, version):
    path = tmp_path / "tasks.sqlite3"
    with sqlite3.connect(path) as connection:
        seed_legacy(connection, version)
        store = TaskStore(connection)
        store.initialize()
        before = review(store)
    raw = path.read_bytes()
    with sqlite3.connect(path) as connection:
        store = TaskStore(connection)
        store.initialize()
        assert review(store) == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    assert path.read_bytes() == raw
