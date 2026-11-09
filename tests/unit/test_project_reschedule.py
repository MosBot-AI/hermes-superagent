"""Synthetic complete-project date review, atomic apply and historical retry."""

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent import task_project_reschedule
from personal_agent.conversation_tasks import _parse
from personal_agent.task_presentation import render_task_result
from personal_agent.tasks import TaskError, TaskStore, validate_request


def store(path=":memory:"):
    s = TaskStore(sqlite3.connect(path))
    s.initialize()
    return s


def capture(s, due="2028-02-28", project="中文项目", title="Synthetic"):
    p = {"title": title, "project": project, "request_id": str(uuid4())}
    if due is not None:
        p["due_date"] = due
    return s.run("capture", p)["data"]


def mutate(s, t, op="update", **kw):
    return s.run(
        op,
        {"task_id": t["id"], "expected_revision": t["revision"], "request_id": str(uuid4()), **kw},
    )["data"]


def preview(s, days=2):
    return s.run("project_reschedule_preview", {"project": "中文项目", "days": days})["data"]


def intent(s, days=2, key="shift"):
    return {
        "project": "中文项目",
        "days": days,
        "expected_snapshot": preview(s, days)["snapshot"],
        "request_id": key,
    }


def error(code, call):
    with pytest.raises(TaskError) as caught:
        call()
    assert caught.value.code == code


def snapshot(s):
    return {
        t: s._connection.execute(f"SELECT * FROM {t}").fetchall()
        for t in ("tasks", "events", "receipts", "task_dependencies")
    }


def test_full_dates_preserve_graph_progress_terminal_and_undated():
    s = store()
    a = mutate(s, capture(s), "complete", note="accepted")
    b = mutate(s, capture(s), "set_dependencies", dependency_ids=[a["id"]])
    b = mutate(s, b, "progress", work_status="in_progress", note="working")
    c = mutate(s, capture(s), "cancel", note="cancelled")
    undated = capture(s, None)
    other = capture(s, project="other")
    before = snapshot(s)
    p = preview(s)
    assert snapshot(s) == before
    assert p["task_count"] == 4 and p["affected_count"] == 1
    assert p["excluded_counts"] == {"terminal": 2, "undated": 1}
    assert p["items"] == [
        {
            "id": b["id"],
            "title": "Synthetic",
            "revision": b["revision"],
            "old_due_date": "2028-02-28",
            "new_due_date": "2028-03-01",
        }
    ]
    s.run("reschedule_project", intent(s))
    current = s.run("get", {"task_id": b["id"]})["data"]
    for key in b:
        if key not in {"due_date", "revision", "updated_at"}:
            assert current[key] == b[key]
    assert current["due_date"] == "2028-03-01" and current["revision"] == b["revision"] + 1
    for unchanged in (a, c, undated, other):
        assert s.run("get", {"task_id": unchanged["id"]})["data"] == unchanged
    assert (
        s.run("history", {"task_id": b["id"]})["data"]["items"][-1]["operation"]
        == "reschedule_project"
    )
    error("revision_conflict", lambda: mutate(s, b, title="stale"))


@pytest.mark.parametrize(
    "change", ["add", "move_out", "date", "title", "progress", "complete", "undated", "terminal"]
)
def test_snapshot_binds_all_members_even_excluded(change):
    s = store()
    t = capture(s)
    u = capture(s, None)
    terminal = mutate(s, capture(s), "complete", note="done")
    req = intent(s)
    if change == "add":
        capture(s, None)
    elif change == "move_out":
        mutate(s, t, project="other")
    elif change == "date":
        mutate(s, t, due_date="2029-01-01")
    elif change == "title":
        mutate(s, t, title="new")
    elif change == "progress":
        mutate(s, t, "progress", work_status="waiting", note="wait")
    elif change == "complete":
        mutate(s, t, "complete", note="done")
    elif change == "undated":
        mutate(s, u, due_date="2029-01-01")
    else:
        # Terminal members can change through explicit whole-project rename.
        s._connection.execute("UPDATE tasks SET revision=revision+1 WHERE id=?", (terminal["id"],))
        s._connection.commit()
    before = snapshot(s)
    error("project_snapshot_conflict", lambda: s.run("reschedule_project", req))
    assert snapshot(s) == before


@pytest.mark.parametrize(
    "due,days,want",
    [
        ("2028-03-01", -1, "2028-02-29"),
        ("2027-03-01", -1, "2027-02-28"),
        ("2028-12-31", 1, "2029-01-01"),
    ],
)
def test_date_only_calendar_boundaries(due, days, want):
    s = store()
    capture(s, due)
    assert preview(s, days)["items"][0]["new_due_date"] == want


@pytest.mark.parametrize("due,days", [("0001-01-01", -1), ("9999-12-31", 1)])
def test_overflow_refuses_entire_review(due, days):
    s = store()
    capture(s)
    capture(s, due)
    before = snapshot(s)
    error("project_date_range", lambda: preview(s, days))
    assert snapshot(s) == before


@pytest.mark.parametrize("days", [0, True, False, 1.5, "1", -3651, 3651, None])
def test_invalid_days_do_not_touch_storage(days):
    error(
        "invalid_request",
        lambda: validate_request("project_reschedule_preview", {"project": "p", "days": days}),
    )


def test_limits_refuse_whole_review_and_empty_apply_is_explicit(monkeypatch):
    s = store()
    capture(s, None)
    p = preview(s)
    assert p["items"] == [] and p["excluded_counts"]["undated"] == 1
    error("project_no_dated_tasks", lambda: s.run("reschedule_project", intent(s)))
    capture(s)
    monkeypatch.setattr(task_project_reschedule, "MAX_PROJECT_TASKS", 1)
    error("project_reschedule_limit", lambda: preview(s))
    monkeypatch.setattr(task_project_reschedule, "MAX_PROJECT_TASKS", 100)
    monkeypatch.setattr(task_project_reschedule, "MAX_PREVIEW_CHARS", 1)
    error("project_reschedule_limit", lambda: preview(s))


@pytest.mark.parametrize("phase", ["task", "event", "receipt"])
def test_fault_rolls_back_whole_group(phase):
    s = store()
    capture(s)
    capture(s)
    req = intent(s)
    last = s._connection.execute("SELECT MAX(id) FROM tasks").fetchone()[0]
    trigger = {
        "task": f"BEFORE UPDATE ON tasks WHEN NEW.id='{last}'",
        "event": (
            f"BEFORE INSERT ON events WHEN NEW.task_id='{last}' "
            "AND NEW.operation='reschedule_project'"
        ),
        "receipt": "BEFORE INSERT ON receipts WHEN NEW.request_id='shift'",
    }[phase]
    s._connection.execute(
        f"CREATE TEMP TRIGGER fail {trigger} BEGIN SELECT RAISE(ABORT,'fault'); END"
    )
    before = snapshot(s)
    with pytest.raises(TaskError):
        s.run("reschedule_project", req)
    assert snapshot(s) == before
    s._connection.execute("DROP TRIGGER fail")
    assert s.run("reschedule_project", req)["data"]["affected_count"] == 2


def test_historical_replay_does_not_move_new_members_after_restart(tmp_path):
    path = tmp_path / "tasks.sqlite"
    s = store(path)
    t = capture(s)
    req = intent(s)
    result = s.run("reschedule_project", req)
    mutate(s, s.run("get", {"task_id": t["id"]})["data"], project="other")
    newcomer = capture(s)
    s._connection.close()
    s = store(path)
    assert s.run("reschedule_project", req) == {**result, "replayed": True}
    assert s.run("get", {"task_id": newcomer["id"]})["data"] == newcomer
    error("idempotency_conflict", lambda: s.run("reschedule_project", {**req, "days": 3}))


def test_identical_concurrent_apply_moves_once(tmp_path):
    path = tmp_path / "tasks.sqlite"
    s = store(path)
    capture(s)
    req = intent(s)
    s._connection.close()
    barrier = Barrier(2)

    def apply():
        local = store(path)
        barrier.wait()
        try:
            return local.run("reschedule_project", req)
        finally:
            local._connection.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: apply(), range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert results[0]["data"] == results[1]["data"]


@pytest.mark.parametrize("after", [False, True])
def test_process_commit_crash_retry_is_exactly_once(tmp_path, after):
    path = tmp_path / "tasks.sqlite"
    s = store(path)
    t = capture(s)
    req = intent(s)
    s._connection.close()
    child = """
import json,os,sqlite3,sys
from personal_agent.tasks import TaskStore
class Crash(sqlite3.Connection):
    armed=False
    def execute(self,sql,*args):
        if self.armed and sql=='COMMIT' and sys.argv[3]=='False':os._exit(73)
        value=super().execute(sql,*args)
        if self.armed and sql=='COMMIT':os._exit(73)
        return value
c=sqlite3.connect(sys.argv[1],factory=Crash);s=TaskStore(c);s.initialize();c.armed=True
s.run('reschedule_project',json.loads(sys.argv[2]))
"""
    result = subprocess.run(
        [sys.executable, "-c", child, str(path), json.dumps(req), str(after)], capture_output=True
    )
    assert result.returncode == 73, result.stderr
    s = store(path)
    assert s.run("get", {"task_id": t["id"]})["data"]["revision"] == (2 if after else 1)
    assert s.run("reschedule_project", req)["replayed"] is after
    assert s.run("get", {"task_id": t["id"]})["data"]["due_date"] == "2028-03-01"
    assert s._connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def test_native_parser_and_complete_readable_review():
    operation, payload, _ = _parse('project-reschedule-preview --project "中文项目" --days -2')
    assert operation == "project_reschedule_preview" and payload["days"] == -2
    s = store()
    t = capture(s)
    result = {"status": "ok", **s.run(operation, payload)}
    text = render_task_result(result, operation=operation, payload=payload)
    assert t["id"] in text and "2028-02-28 -> 2028-02-26" in text
    assert "Snapshot:" in text and "nothing changed" in text


@pytest.mark.parametrize("count,title", [(101, "small"), (12, "中" * 240)])
def test_actual_member_and_escaped_output_caps(count, title):
    s = store()
    for _ in range(count):
        capture(s, title=title)
    before = snapshot(s)
    error("project_reschedule_limit", lambda: preview(s))
    assert snapshot(s) == before


def test_exact_label_and_delta_are_bound_and_corrupt_date_is_not_repaired():
    s = store()
    t = capture(s)
    capture(s, project="中文项目A")
    request = intent(s)
    assert preview(s)["task_count"] == 1
    error("project_snapshot_conflict", lambda: s.run("reschedule_project", {**request, "days": -2}))
    s._connection.execute("UPDATE tasks SET due_date='20280228' WHERE id=?", (t["id"],))
    s._connection.commit()
    before = snapshot(s)
    error("storage_corrupt", lambda: preview(s))
    assert snapshot(s) == before
