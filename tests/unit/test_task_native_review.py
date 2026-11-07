"""Saved local attention queue: bounded output, honest counts, zero native access."""

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from personal_agent.tasks import TaskError, TaskStore, validate_request

ON = "2026-11-14"
CUTOFF = int(datetime(2026, 11, 7, tzinfo=UTC).timestamp())


def store(path=":memory:"):
    s = TaskStore(sqlite3.connect(path))
    s.initialize()
    return s


def capture(s, *, status=None, outcome="current", observed_at=CUTOFF, project="p", title="Task"):
    task = s.run(
        "capture",
        {
            "title": title,
            "details": "PRIVATE DETAILS",
            "request_id": str(uuid4()),
            "project": project,
        },
    )["data"]
    if status is not None or outcome != "current":
        req = {
            "task_id": task["id"],
            "handoff_id": str(uuid4()),
            "expected_revision": 1,
            "request_id": str(uuid4()),
        }
        task = s.sync_native(
            req,
            lambda _: {
                "handoff_id": req["handoff_id"],
                "card_id": "t_1234abcd",
                "outcome": outcome,
                "status": status,
                "observed_at": observed_at,
                "exported_revision": 1,
            },
        )["data"]
    return task


def review(s, **extra):
    return s.run("native_review", {"on": ON, **extra})["data"]


def test_categories_overlap_unique_counts_and_no_linkage_inference():
    s = store()
    old_review = capture(s, status="review", observed_at=CUTOFF - 1)
    capture(s, status="done")
    capture(s, status="archived")
    capture(s, outcome="missing", observed_at=CUTOFF - 2)
    capture(s, status="running")
    capture(s)
    data = review(s)
    assert data["counts"] == {
        "total_active": 6,
        "active_observed": 5,
        "active_unobserved": 1,
        "unique_attention": 4,
        "awaiting_review": 1,
        "board_closed": 2,
        "identity_issue": 1,
        "stale": 2,
    }
    assert data["stale_before"] == "2026-11-07T00:00:00Z"
    item = data["buckets"]["awaiting_review"]["items"][0]
    assert item["id"] == old_review["id"]
    assert set(item) == {
        "id",
        "title",
        "revision",
        "project",
        "due_date",
        "work_status",
        "native_progress",
    }
    assert "PRIVATE DETAILS" not in json.dumps(data)
    assert s.run("get", {"task_id": old_review["id"]})["data"] == old_review


def test_only_captured_exact_project_and_unassigned():
    s = store()
    capture(s, status="review", project="Work")
    capture(s, status="review", project="work")
    capture(s, status="done", project=None)
    terminal = capture(s, status="done", project="Work")
    s.run(
        "cancel",
        {
            "task_id": terminal["id"],
            "expected_revision": 2,
            "note": "cancel",
            "request_id": "cancel",
        },
    )
    assert review(s, project="Work")["counts"]["total_active"] == 1
    assert review(s, unassigned=True)["counts"]["board_closed"] == 1
    assert review(s, unassigned=False)["counts"]["total_active"] == 3


def test_oldest_timestamp_then_sequence_and_omissions():
    s = store()
    newer = capture(s, status="review", observed_at=CUTOFF)
    oldest = capture(s, status="review", observed_at=CUTOFF - 10)
    same = capture(s, status="review", observed_at=CUTOFF - 10)
    bucket = review(s, per_bucket_limit=2)["buckets"]["awaiting_review"]
    assert [item["id"] for item in bucket["items"]] == [oldest["id"], same["id"]]
    assert bucket["total"] == 3 and bucket["omitted"] == 1
    assert newer["id"] not in [item["id"] for item in bucket["items"]]


def test_strict_stale_cutoff_and_future_not_stale():
    s = store()
    for timestamp in (CUTOFF - 1, CUTOFF, CUTOFF + 1, CUTOFF + 999999):
        capture(s, status="running", observed_at=timestamp)
    assert review(s)["counts"]["stale"] == 1
    assert review(s, stale_after_days=8)["counts"]["stale"] == 0


@pytest.mark.parametrize("max_chars", [2048, 4096, 16000, 32000])
def test_ascii_json_budget_whole_items_and_full_counts(max_chars):
    s = store()
    for _ in range(25):
        capture(s, status="review", observed_at=CUTOFF - 1, title="😀" * 240)
    data = review(s, max_chars=max_chars, per_bucket_limit=20)
    assert len(json.dumps(data, ensure_ascii=True, sort_keys=True)) <= max_chars
    assert data["counts"]["unique_attention"] == 25
    for name in ("awaiting_review", "stale"):
        bucket = data["buckets"][name]
        assert bucket["total"] == 25
        assert bucket["omitted"] == 25 - len(bucket["items"])
        assert all(item["title"] == "😀" * 240 for item in bucket["items"])


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"on": "bad"},
        {"on": "0001-01-01"},
        {"on": ON, "stale_after_days": True},
        {"on": ON, "stale_after_days": 0},
        {"on": ON, "stale_after_days": 366},
        {"on": ON, "per_bucket_limit": 0},
        {"on": ON, "per_bucket_limit": 21},
        {"on": ON, "max_chars": 2047},
        {"on": ON, "max_chars": 32001},
        {"on": ON, "work_status": "ready"},
        {"on": ON, "project": "p", "unassigned": False},
        {"on": ON, "unassigned": 1},
        {"on": ON, "project": None},
    ],
)
def test_strict_request_validation(bad):
    with pytest.raises(TaskError) as caught:
        validate_request("native_review", bad)
    assert caught.value.code == "invalid_request"


def test_defaults_no_mutations_and_no_native_imports(monkeypatch):
    import builtins

    s = store()
    capture(s, status="review")
    before = list(s._connection.iterdump())
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if any(
            part in name for part in ("native_kanban", "kanban_handoff", "hermes_cli", "provider")
        ):
            raise AssertionError("attention queue must use saved local data only")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    trace = []
    s._connection.set_trace_callback(trace.append)
    data = review(s)
    assert data["stale_after_days"] == 7
    assert trace[0] == "BEGIN" and trace[-1] == "COMMIT"
    assert all(sql in ("BEGIN", "COMMIT") or sql.startswith("SELECT") for sql in trace)
    s._connection.set_trace_callback(None)
    assert list(s._connection.iterdump()) == before


def test_corrupt_projection_outside_sample_still_fails_closed():
    s = store()
    capture(s, status="review", observed_at=0)
    late = capture(s, status="review", observed_at=CUTOFF)
    s._connection.execute(
        "UPDATE task_native_progress SET observation='{}' WHERE task_id=?", (late["id"],)
    )
    s._connection.commit()
    with pytest.raises(TaskError) as caught:
        review(s, per_bucket_limit=1)
    assert caught.value.code == "storage_corrupt"


def test_one_snapshot_includes_task_and_saved_observation(tmp_path):
    path = tmp_path / "tasks.db"
    s = store(path)
    s._connection.execute("PRAGMA journal_mode=WAL")
    first = capture(s, status="review", observed_at=CUTOFF - 1)
    other = store(path)
    # A progress-handler callback runs after the read snapshot starts. A second
    # writer can commit, but this scan must keep both row and observation old.
    fired = False

    handoff = str(uuid4())
    # Establish snapshot before installing the concurrent hook via reader function.
    from personal_agent.task_native_review import task_native_review

    s._connection.execute("BEGIN")
    s._connection.execute("SELECT count(*) FROM tasks").fetchone()

    def concurrent_fixed():
        nonlocal fired
        if not fired:
            fired = True
            other.sync_native(
                {
                    "task_id": first["id"],
                    "handoff_id": handoff,
                    "expected_revision": 2,
                    "request_id": "new",
                },
                lambda _: {
                    **first["native_progress"],
                    "handoff_id": handoff,
                    "status": "running",
                    "observed_at": CUTOFF + 1,
                },
            )
        return 0

    s._connection.set_progress_handler(concurrent_fixed, 1)
    data = task_native_review(s._connection, validate_request("native_review", {"on": ON}))
    s._connection.set_progress_handler(None, 0)
    s._connection.execute("COMMIT")
    assert fired and data["counts"]["awaiting_review"] == 1
    assert data["buckets"]["awaiting_review"]["items"][0]["revision"] == 2
    assert review(s)["counts"]["unique_attention"] == 0
