"""Atomic batch-local dependencies with stable historical plan receipts."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest

from personal_agent.tasks import TaskError, TaskStore, validate_request


def store(path=":memory:", factory=sqlite3.Connection):
    result = TaskStore(sqlite3.connect(path, factory=factory))
    result.initialize()
    return result


def plan(**extra):
    return {
        "project": "Demo",
        "tasks": [
            {"title": "Last", "depends_on": [3, 2]},
            {"title": "Middle", "depends_on": [3]},
            {"title": "First"},
        ],
        "request_id": "plan",
        **extra,
    }


def counts(s):
    return [
        s._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("tasks", "task_dependencies", "events", "receipts")
    ]


def test_forward_references_revision_one_and_live_readiness():
    s = store()
    request = plan()
    before = deepcopy(request)
    result = s.run("capture_plan", request)
    assert request == before
    items = result["data"]["items"]
    assert [item["title"] for item in items] == ["Last", "Middle", "First"]
    assert all(item["revision"] == 1 and item["work_status"] == "ready" for item in items)
    assert [item["unsatisfied_dependency_count"] for item in items] == [2, 1, 0]
    assert {row["task_id"] for row in items[0]["dependencies"]} == {items[1]["id"], items[2]["id"]}
    assert counts(s) == [3, 3, 3, 1]
    assert s.run("ready", {})["data"]["items"] == [items[2]]
    for operation, extra in (("complete", {}), ("progress", {"work_status": "in_progress"})):
        with pytest.raises(TaskError, match="dependencies_unsatisfied"):
            s.run(
                operation,
                {
                    "task_id": items[0]["id"],
                    "expected_revision": 1,
                    "request_id": operation,
                    "note": "Explicit",
                    **extra,
                },
            )
    s.run(
        "complete",
        {
            "task_id": items[2]["id"],
            "expected_revision": 1,
            "request_id": "first-done",
            "note": "Explicit",
        },
    )
    ready = s.run("ready", {})["data"]["items"]
    assert [item["id"] for item in ready] == [items[1]["id"]]
    assert ready[0]["revision"] == 1
    assert s.run("capture_plan", request) == {**result, "replayed": True}
    assert s._connection.execute("PRAGMA user_version").fetchone()[0] == 8


@pytest.mark.parametrize(
    "references", [None, "1", [True], [False], [0], [-1], [4], [1.0], ["2"], [2, 2]]
)
def test_invalid_reference_values_precede_transaction(references):
    s = store()
    request = plan(tasks=[{"title": "A", "depends_on": references}, {"title": "B"}, {"title": "C"}])
    trace = []
    s._connection.set_trace_callback(trace.append)
    with pytest.raises(TaskError, match="invalid_request"):
        s.run("capture_plan", request)
    assert trace == []


@pytest.mark.parametrize(
    "tasks",
    [
        [{"title": "self", "depends_on": [1]}],
        [{"title": "A", "depends_on": [2]}, {"title": "B", "depends_on": [1]}],
        [
            {"title": "A", "depends_on": [2]},
            {"title": "B", "depends_on": [3]},
            {"title": "C", "depends_on": [1]},
        ],
    ],
)
def test_cycles_rejected_before_begin(tasks):
    s = store()
    trace = []
    s._connection.set_trace_callback(trace.append)
    with pytest.raises(TaskError, match="dependency_cycle"):
        s.run("capture_plan", plan(tasks=tasks))
    assert trace == []


def test_sorted_references_same_retry_empty_references_preserve_old_digest():
    s = store()
    request = plan()
    result = s.run("capture_plan", request)
    normalized = deepcopy(request)
    normalized["tasks"][0]["depends_on"] = [2, 3]
    normalized["tasks"][2]["depends_on"] = []
    assert s.run("capture_plan", normalized) == {**result, "replayed": True}
    old = plan(tasks=[{"title": "Old"}], request_id="old")
    original = s.run("capture_plan", old)
    empty = plan(tasks=[{"title": "Old", "depends_on": []}], request_id="old")
    assert validate_request("capture_plan", old) == validate_request("capture_plan", empty)
    assert s.run("capture_plan", empty) == {**original, "replayed": True}
    changed = deepcopy(request)
    changed["tasks"][0]["depends_on"] = [3]
    with pytest.raises(TaskError, match="idempotency_conflict"):
        s.run("capture_plan", changed)


@pytest.mark.parametrize("stage", ["edge", "event", "receipt"])
def test_failure_rolls_back_all_batch_parts(stage):
    class Failing(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and (
                (stage == "event" and sql.startswith("INSERT INTO events"))
                or (stage == "receipt" and sql.startswith("INSERT INTO receipts"))
            ):
                raise sqlite3.OperationalError("synthetic")
            return super().execute(sql, *args)

        def executemany(self, sql, parameters):
            result = super().executemany(sql, parameters)
            if self.armed and stage == "edge" and sql.startswith("INSERT INTO task_dependencies"):
                raise sqlite3.OperationalError("synthetic after edge writes")
            return result

    s = store(factory=Failing)
    s._connection.armed = True
    with pytest.raises(TaskError, match="storage_error"):
        s.run("capture_plan", plan())
    assert counts(s) == [0, 0, 0, 0]
    s._connection.armed = False
    assert not s.run("capture_plan", plan())["replayed"]
    assert counts(s) == [3, 3, 3, 1]


def test_concurrent_identical_plan_commits_one_graph(tmp_path):
    path = tmp_path / "tasks.db"
    store(path)._connection.close()
    barrier = Barrier(2)

    def run(_):
        s = store(path)
        barrier.wait()
        try:
            return s.run("capture_plan", plan())
        finally:
            s._connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (0, 1)))
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert results[0]["data"] == results[1]["data"]
    assert counts(store(path)) == [3, 3, 3, 1]


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_process_crash_before_or_after_commit(tmp_path, boundary):
    path = tmp_path / "crash.db"
    store(path)._connection.close()
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
s.run('capture_plan',json.loads(sys.argv[3]))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(path), boundary, json.dumps(plan())],
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
    assert counts(s) == ([0, 0, 0, 0] if boundary == "before" else [3, 3, 3, 1])
    receipt = s.run("capture_plan", plan())
    assert receipt["replayed"] is (boundary == "after")
    assert counts(s) == [3, 3, 3, 1]
    assert [item["unsatisfied_dependency_count"] for item in receipt["data"]["items"]] == [2, 1, 0]


def test_legacy_receipt_without_dependency_metadata_replays_exactly():
    s = store()
    request = plan(tasks=[{"title": "Old"}])
    result = s.run("capture_plan", request)
    historical = deepcopy(result["data"])
    for item in historical["items"]:
        for field in (
            "dependencies",
            "dependencies_satisfied",
            "unsatisfied_dependency_count",
            "native_progress",
        ):
            item.pop(field)
    s._connection.execute(
        "UPDATE receipts SET receipt=? WHERE request_id='plan'", (json.dumps(historical),)
    )
    s._connection.commit()
    request["tasks"][0]["depends_on"] = []
    assert s.run("capture_plan", request) == {"data": historical, "replayed": True}
    assert counts(s) == [1, 0, 1, 1]


def test_maximum_batch_dense_dag_without_implicit_edges():
    s = store()
    batch = [
        {"title": str(position), "depends_on": list(range(position + 1, 21))}
        for position in range(1, 21)
    ]
    items = s.run("capture_plan", plan(tasks=batch))["data"]["items"]
    assert counts(s) == [20, 190, 20, 1]
    assert [item["unsatisfied_dependency_count"] for item in items] == list(range(19, -1, -1))
    independent = s.run(
        "capture_plan", plan(tasks=[{"title": "A"}, {"title": "B"}], request_id="independent")
    )["data"]["items"]
    assert all(item["dependencies"] == [] for item in independent)
