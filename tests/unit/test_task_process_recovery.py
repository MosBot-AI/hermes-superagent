"""Crash inside task transactions, not just recoverable Python exceptions."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from personal_agent.tasks import TaskError, TaskStore

CHILD = r"""
import json, os, sqlite3, sys
from personal_agent.tasks import TaskStore
stage = sys.argv[2]
class Crash(sqlite3.Connection):
    armed = False
    def execute(self, sql, *args):
        if self.armed and stage == 'before_commit' and sql == 'COMMIT':
            os._exit(73)
        result = super().execute(sql, *args)
        markers = {
            'record': ('INSERT INTO tasks ', 'UPDATE tasks SET'),
            'event': ('INSERT INTO events ',),
            'receipt': ('INSERT INTO receipts ',),
            'edge_delete': ('DELETE FROM task_dependencies ',),
            'edge_insert': ('INSERT INTO task_dependencies',),
            'after_commit': ('COMMIT',),
        }
        if self.armed and any(sql.startswith(m) for m in markers.get(stage, ())):
            os._exit(73)
        return result
    def executemany(self, sql, parameters):
        if (self.armed and stage == 'edge_insert'
                and sql.startswith('INSERT INTO task_dependencies')):
            # Stop after the first genuine edge write, before the remaining rows.
            iterator = iter(parameters)
            first = next(iterator, None)
            if first is not None:
                self.execute(sql, first)
        return super().executemany(sql, parameters)
c = sqlite3.connect(sys.argv[1], factory=Crash)
s = TaskStore(c); s.initialize(); c.armed = True
s.run(sys.argv[3], json.loads(sys.argv[4]))
raise RuntimeError('crash point not reached')
"""


def opened(path):
    connection = sqlite3.connect(path)
    store = TaskStore(connection)
    store.initialize()
    return store, connection


def capture(store, key):
    return store.run("capture", {"title": key, "project": "测试", "request_id": key})["data"]


def prepare(store, operation):
    if operation == "capture":
        return {"title": "任务", "project": "测试", "request_id": "crash"}
    if operation == "capture_plan":
        return {
            "project": "测试",
            "tasks": [{"title": "第二步", "depends_on": [2]}, {"title": "第一步"}],
            "request_id": "crash",
        }
    old = capture(store, "old")
    new = capture(store, "new")
    task = capture(store, "target")
    if operation in ("set_dependencies", "breakdown"):
        task = store.run(
            "set_dependencies",
            {
                "task_id": task["id"],
                "expected_revision": 1,
                "dependency_ids": [old["id"]],
                "request_id": "original-edge",
            },
        )["data"]
    payload = {
        "task_id": task["id"],
        "expected_revision": task["revision"],
        "request_id": "crash",
    }
    payload.update(
        {
            "update": {"title": "changed", "details": "新内容"},
            "complete": {"note": "finished"},
            "cancel": {"note": "cancelled"},
            "progress": {"work_status": "in_progress", "note": "working"},
            "set_dependencies": {"dependency_ids": [new["id"]]},
            "breakdown": {"tasks": [{"title": "child", "depends_on": [2]}, {"title": "base"}]},
        }[operation]
    )
    return payload


OPERATIONS = (
    "capture",
    "update",
    "complete",
    "cancel",
    "progress",
    "set_dependencies",
    "capture_plan",
    "breakdown",
)
CASES = [
    (op, stage)
    for op in OPERATIONS
    for stage in ("record", "event", "receipt", "before_commit", "after_commit")
]
CASES += [(op, "edge_insert") for op in ("set_dependencies", "capture_plan", "breakdown")]
CASES += [("set_dependencies", "edge_delete")]


@pytest.mark.parametrize("journal", ["delete", "wal"])
@pytest.mark.parametrize("operation,stage", CASES)
def test_task_transaction_survives_abrupt_process_exit(tmp_path, journal, operation, stage):
    path = tmp_path / "tasks.sqlite"
    store, conn = opened(path)
    assert conn.execute(f"PRAGMA journal_mode={journal}").fetchone()[0] == journal
    request = prepare(store, operation)
    before = list(conn.iterdump())
    conn.close()
    result = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(path), stage, operation, json.dumps(request)],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 73, result.stderr
    assert not result.stdout
    store, conn = opened(path)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    committed = stage == "after_commit"
    if not committed:
        assert list(conn.iterdump()) == before
    else:
        assert conn.execute(
            "SELECT count(*) FROM receipts WHERE request_id='crash'"
        ).fetchone() == (1,)
    response = store.run(operation, request)
    assert response["replayed"] is committed
    after = list(conn.iterdump())
    conn.close()

    store, conn = opened(path)
    assert store.run(operation, request) == {**response, "replayed": True}
    assert list(conn.iterdump()) == after
    # Same key with different intent must not be accepted after a lost response.
    changed = dict(request)
    if operation in ("capture_plan", "breakdown"):
        changed["tasks"] = [{"title": "different"}]
    elif operation == "set_dependencies":
        changed["dependency_ids"] = []
    elif operation in ("capture", "update"):
        changed["title"] = "different"
    else:
        changed["note"] = "different"
    with pytest.raises(TaskError, match="idempotency_conflict"):
        store.run(operation, changed)
    assert list(conn.iterdump()) == after
    data = response["data"]
    tasks = data["items"] if operation in ("capture_plan", "breakdown") else [data]
    for task in tasks:
        assert store.run("get", {"task_id": task["id"]})["data"] == task
    if operation == "breakdown":
        assert store.run("get", {"task_id": request["task_id"]})["data"] == data["parent"]
    conn.close()
