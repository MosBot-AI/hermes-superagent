"""Atomic local breakdown, prerequisite inheritance, and durable no-double-create retries."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent.tasks import TaskError, TaskStore


def store(path=":memory:", factory=sqlite3.Connection):
    result = TaskStore(sqlite3.connect(path, factory=factory))
    result.initialize()
    return result


def capture(s, project="P"):
    return s.run(
        "capture",
        {
            "title": "Parent private",
            "details": "DO NOT COPY",
            "project": project,
            "due_date": "2026-11-09",
            "request_id": str(uuid4()),
        },
    )["data"]


def request(parent, **changes):
    return {
        "task_id": parent["id"],
        "expected_revision": parent["revision"],
        "tasks": [{"title": "Later", "depends_on": [2]}, {"title": "First"}],
        "request_id": "break",
        **changes,
    }


def mutate(s, op, task, **extra):
    return s.run(
        op,
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": str(uuid4()),
            **extra,
        },
    )["data"]


def counts(s):
    return [
        s._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("tasks", "task_dependencies", "events", "receipts")
    ]


def test_inherited_prerequisites_gate_steps_and_parent_without_auto_completion():
    s = store()
    old = capture(s)
    parent = mutate(s, "set_dependencies", capture(s), dependency_ids=[old["id"]])
    before = dict(parent)
    result = s.run("breakdown", request(parent))["data"]
    steps, current = result["items"], result["parent"]
    assert result["project"] == "P" and result["inherited_dependency_ids"] == [old["id"]]
    assert [x["title"] for x in steps] == ["Later", "First"]
    assert all(x["revision"] == 1 and x["details"] == "" and x["due_date"] is None for x in steps)
    assert all(x["state"] == "captured" and x["work_status"] == "ready" for x in steps)
    assert current["revision"] == before["revision"] + 1
    for key in ("title", "details", "due_date", "project", "state", "work_status", "progress_note"):
        assert current[key] == before[key]
    assert {x["task_id"] for x in current["dependencies"]} == {old["id"], *(x["id"] for x in steps)}
    assert [x["unsatisfied_dependency_count"] for x in steps] == [2, 1]
    assert [x["id"] for x in s.run("ready", {})["data"]["items"]] == [old["id"]]
    with pytest.raises(TaskError, match="dependencies_unsatisfied"):
        mutate(s, "complete", current, note="not yet")
    mutate(s, "complete", old, note="done")
    mutate(s, "complete", steps[1], note="done")
    mutate(s, "complete", steps[0], note="done")
    latest = s.run("get", {"task_id": current["id"]})["data"]
    assert latest["dependencies_satisfied"] and latest["state"] == "captured"
    assert latest["revision"] == current["revision"]
    assert mutate(s, "complete", latest, note="explicit")["state"] == "done"


@pytest.mark.parametrize("work_status", ["ready", "waiting", "blocked"])
def test_allowed_parent_statuses_remain_unchanged(work_status):
    s = store()
    parent = mutate(s, "progress", capture(s), work_status=work_status, note="keep note")
    data = s.run("breakdown", request(parent))["data"]
    assert data["parent"]["work_status"] == work_status
    assert data["parent"]["progress_note"] == "keep note"


@pytest.mark.parametrize(
    "case,code",
    [
        ("in_progress", "breakdown_in_progress"),
        ("cancelled", "terminal_state"),
        ("done", "terminal_state"),
        ("unassigned", "dependency_project_required"),
        ("revision", "revision_conflict"),
    ],
)
def test_parent_preconditions_leave_everything_unchanged(case, code):
    s = store()
    parent = capture(s, None if case == "unassigned" else "P")
    if case in ("done", "cancelled"):
        parent = mutate(s, "complete" if case == "done" else "cancel", parent, note="terminal")
    if case == "in_progress":
        parent = mutate(s, "progress", parent, work_status="in_progress", note="started")
    req = request(parent)
    if case == "revision":
        req["expected_revision"] += 1
    before = list(s._connection.iterdump())
    with pytest.raises(TaskError, match=code):
        s.run("breakdown", req)
    assert list(s._connection.iterdump()) == before


def test_cancelled_prerequisite_is_inherited_and_still_blocks():
    s = store()
    old = mutate(s, "cancel", capture(s), note="cancelled")
    parent = mutate(s, "set_dependencies", capture(s), dependency_ids=[old["id"]])
    result = s.run("breakdown", request(parent))["data"]
    assert all(not item["dependencies_satisfied"] for item in result["items"])
    assert all(
        any(dep["state"] == "cancelled" for dep in item["dependencies"]) for item in result["items"]
    )


def test_combined_capacity_exact_boundary_and_no_silent_drops():
    s = store()
    old = [capture(s) for _ in range(19)]
    parent = mutate(s, "set_dependencies", capture(s), dependency_ids=[x["id"] for x in old])
    before = counts(s)
    with pytest.raises(TaskError, match="dependency_limit"):
        s.run("breakdown", request(parent))
    assert counts(s) == before
    result = s.run("breakdown", request(parent, tasks=[{"title": "One"}]))["data"]
    assert len(result["parent"]["dependencies"]) == 20
    assert len(result["items"][0]["dependencies"]) == 19


def test_receipt_first_historical_retry_after_terminal_and_sorted_references():
    s = store()
    parent = capture(s)
    req = request(
        parent,
        tasks=[{"title": "Last", "depends_on": [3, 2]}, {"title": "Two"}, {"title": "Three"}],
    )
    original = s.run("breakdown", req)
    mutate(s, "cancel", original["data"]["parent"], note="cancel")
    req["tasks"][0]["depends_on"] = [2, 3]
    req["tasks"][1]["depends_on"] = []
    assert s.run("breakdown", req) == {**original, "replayed": True}
    with pytest.raises(TaskError, match="idempotency_conflict"):
        s.run("breakdown", {**req, "expected_revision": 2})


@pytest.mark.parametrize(
    "changes",
    [
        {"project": "other"},
        {"tasks": []},
        {"tasks": [{"title": "x", "depends_on": [True]}]},
        {"tasks": [{"title": "x", "depends_on": [1]}]},
        {"tasks": [{"title": "x", "depends_on": [2]}, {"title": "y", "depends_on": [1]}]},
        {"tasks": [{"title": "x", "project": "other"}]},
    ],
)
def test_validation_precedes_transaction(changes):
    s = store()
    parent = capture(s)
    trace = []
    s._connection.set_trace_callback(trace.append)
    with pytest.raises(TaskError):
        s.run("breakdown", request(parent, **changes))
    assert trace == []


@pytest.mark.parametrize("stage", ["edge", "parent", "event", "receipt"])
def test_all_or_none_failures(stage):
    class Failing(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and (
                (stage == "parent" and sql.startswith("UPDATE tasks"))
                or (stage == "event" and sql.startswith("INSERT INTO events"))
                or (stage == "receipt" and sql.startswith("INSERT INTO receipts"))
            ):
                raise sqlite3.OperationalError("synthetic failure after write")
            return result

        def executemany(self, sql, values):
            result = super().executemany(sql, values)
            if self.armed and stage == "edge":
                raise sqlite3.OperationalError("synthetic edge failure")
            return result

    s = store(factory=Failing)
    parent = capture(s)
    before = list(s._connection.iterdump())
    s._connection.armed = True
    with pytest.raises(TaskError):
        s.run("breakdown", request(parent))
    assert list(s._connection.iterdump()) == before


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_breakdown_serializes_parent_revision(tmp_path, same_key):
    path = tmp_path / "tasks.db"
    s = store(path)
    req = request(capture(s))
    barrier = Barrier(2)

    def run(index):
        child = store(path)
        barrier.wait()
        try:
            return child.run(
                "breakdown", {**req, "request_id": "break" if same_key else f"key{index}"}
            )
        except TaskError as exc:
            return exc.code
        finally:
            child._connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (0, 1)))
    if same_key:
        assert sorted(x["replayed"] for x in results) == [False, True]
        assert results[0]["data"] == results[1]["data"]
    else:
        assert sum(x == "revision_conflict" for x in results) == 1
    assert counts(s) == [3, 3, 4, 2]


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_abrupt_process_commit_boundaries(tmp_path, boundary):
    path = tmp_path / "crash.db"
    s = store(path)
    parent = capture(s)
    s._connection.close()
    script = r"""
import json,os,sqlite3,sys
from personal_agent.tasks import TaskStore
class Crash(sqlite3.Connection):
    armed=False
    def execute(self,sql,*args):
        if self.armed and sql=='COMMIT':
            if sys.argv[2]=='before': os._exit(71)
            super().execute(sql,*args)
            os._exit(72)
        return super().execute(sql,*args)
c=sqlite3.connect(sys.argv[1],factory=Crash)
s=TaskStore(c);s.initialize();c.armed=True
s.run('breakdown',json.loads(sys.argv[3]))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(path), boundary, json.dumps(request(parent))],
        env={
            "HOME": str(tmp_path),
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == (71 if boundary == "before" else 72), result.stderr
    s = store(path)
    assert counts(s) == ([1, 0, 1, 1] if boundary == "before" else [3, 3, 4, 2])
    result = s.run("breakdown", request(parent))
    assert result["replayed"] is (boundary == "after")
    assert counts(s) == [3, 3, 4, 2]
    assert result["data"]["parent"]["revision"] == 2
