"""Atomic project-plan capture: validation, receipts, crash recovery and all-or-none writes."""

import argparse
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier

import pytest
from test_tasks import store  # noqa: F401

from personal_agent.task_cli import command_request, setup_tasks_cli
from personal_agent.task_presentation import render_task_result
from personal_agent.task_tool_contract import normalize_task_tool_request
from personal_agent.tasks import MAX_PLAN_CHARS, TaskError, TaskStore, validate_request


def plan(**extra):
    return {
        "project": "Demo",
        "tasks": [{"title": "Prepare"}, {"title": "Review", "details": "Review the work"}],
        "request_id": "whole-plan",
        **extra,
    }


def counts(current):
    return [
        current._connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("tasks", "events", "receipts")
    ]


def test_plan_is_one_transaction_with_ordered_ids_and_independent_tasks(store):  # noqa: F811
    request = plan()
    original = deepcopy(request)
    result = store.run("capture_plan", request)
    assert request == original and not result["replayed"]
    data = result["data"]
    assert data["project"] == "Demo"
    assert [task["title"] for task in data["items"]] == ["Prepare", "Review"]
    assert len({task["id"] for task in data["items"]}) == 2
    assert len({task["created_at"] for task in data["items"]}) == 1
    assert all(task["revision"] == 1 and task["work_status"] == "ready" for task in data["items"])
    assert counts(store) == [2, 2, 1]
    first = data["items"][0]
    assert (
        store.run("history", {"task_id": first["id"]})["data"]["items"][0]["operation"]
        == "capture_plan"
    )
    store.run(
        "complete",
        {
            "task_id": first["id"],
            "expected_revision": 1,
            "note": "Explicit completion",
            "request_id": "done",
        },
    )
    assert store.run("capture_plan", request) == {"data": data, "replayed": True}
    assert store.run("get", {"task_id": first["id"]})["data"]["state"] == "done"
    assert counts(store) == [2, 3, 2]
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 6


@pytest.mark.parametrize(
    "changes",
    [
        {"tasks": []},
        {"tasks": [{"title": "A"}] * 21},
        {"tasks": "text"},
        {"tasks": None},
        {"tasks": [{"title": "Good"}, {"title": ""}]},
        {"tasks": [False]},
        {"tasks": [{"details": "Missing title"}]},
        {"tasks": [{"title": "A", "project": "Other"}]},
        {"tasks": [{"title": "A", "due_date": None}]},
        {"tasks": [{"title": "A", "due_date": "tomorrow"}]},
        {"tasks": [{"title": "A", "request_id": "nested"}]},
        {"tasks": [{"title": "A", "depends_on": [0]}]},
        {"tasks": [{"title": "A", "details": "x" * 5001}]},
        {"project": None},
        {"project": ""},
        {"project": " Demo"},
        {"project": 1},
        {"request_id": ""},
        {"request_id": True},
        {"expected_revision": 1},
        {"title": "Top-level title"},
        {"due_date": "2030-01-01"},
        {"approved": True},
    ],
)
def test_invalid_plan_is_rejected_before_any_transaction(store, changes):  # noqa: F811
    with pytest.raises(TaskError, match="invalid_request"):
        store.run("capture_plan", plan(**changes))
    assert counts(store) == [0, 0, 0]
    assert not store._connection.in_transaction


def test_normalized_budget_counts_escaping_and_does_not_modify_nested_input(store):  # noqa: F811
    request = plan(tasks=[{"title": "中文", "details": "字" * 5000}])
    normalized = validate_request("capture_plan", request)
    assert len(json.dumps(normalized, ensure_ascii=True, sort_keys=True)) < MAX_PLAN_CHARS
    store.run("capture_plan", request)
    with pytest.raises(TaskError, match="invalid_request"):
        store.run("capture_plan", plan(tasks=request["tasks"] * 2, request_id="too-large"))
    assert counts(store) == [1, 1, 1]
    original = plan(tasks=[{"title": "A"}])
    copied = validate_request("capture_plan", original)
    copied["tasks"][0]["title"] = "Changed"
    assert original["tasks"] == [{"title": "A"}]


def test_semantic_defaults_replay_but_reordering_or_changed_project_conflicts(store):  # noqa: F811
    request = plan()
    first = store.run("capture_plan", request)
    same = deepcopy(request)
    same["tasks"][0]["details"] = ""
    assert store.run("capture_plan", same)["data"] == first["data"]
    for changed in (
        plan(project="Other"),
        plan(tasks=list(reversed(request["tasks"]))),
        plan(tasks=[{"title": "Different"}]),
    ):
        with pytest.raises(TaskError, match="idempotency_conflict"):
            store.run("capture_plan", changed)
    with pytest.raises(TaskError, match="idempotency_conflict"):
        store.run("capture", {"title": "Single", "request_id": "whole-plan"})
    assert counts(store) == [2, 2, 1]


@pytest.mark.parametrize("stage", ["second_insert", "second_event", "receipt"])
def test_failure_rolls_back_tasks_events_and_receipt(store, monkeypatch, stage):  # noqa: F811
    original_capture, original_event = store._capture, store._record_event
    calls = 0

    def fail_capture(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("PRIVATE insert failure")
        return original_capture(*args)

    def fail_event(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("PRIVATE event failure")
        return original_event(*args)

    if stage == "second_insert":
        monkeypatch.setattr(store, "_capture", fail_capture)
    elif stage == "second_event":
        monkeypatch.setattr(store, "_record_event", fail_event)
    else:
        store._connection.set_authorizer(
            lambda action, arg1, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and arg1 == "receipts"
                else sqlite3.SQLITE_OK
            )
        )
    with pytest.raises(TaskError, match="storage_error") as caught:
        store.run("capture_plan", plan())
    assert "PRIVATE" not in str(caught.value)
    store._connection.set_authorizer(None)
    assert counts(store) == [0, 0, 0]
    monkeypatch.setattr(store, "_capture", original_capture)
    monkeypatch.setattr(store, "_record_event", original_event)
    assert not store.run("capture_plan", plan())["replayed"]
    assert counts(store) == [2, 2, 1]


def test_identical_concurrent_plan_creates_exactly_one_batch(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    barrier = Barrier(2)

    def run():
        with sqlite3.connect(path, isolation_level=None) as conn:
            current = TaskStore(conn)
            current.initialize()
            barrier.wait(timeout=5)
            return current.run("capture_plan", plan())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert results[0]["data"] == results[1]["data"]
    assert sorted(result["replayed"] for result in results) == [False, True]
    with sqlite3.connect(path) as conn:
        current = TaskStore(conn)
        current.initialize()
        assert counts(current) == [2, 2, 1]


def test_concurrent_different_plans_with_one_key_commit_only_the_winner(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    barrier = Barrier(2)

    def run(project):
        with sqlite3.connect(path, isolation_level=None) as conn:
            current = TaskStore(conn)
            current.initialize()
            barrier.wait(timeout=5)
            try:
                return current.run("capture_plan", plan(project=project))["data"]
            except TaskError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ("Project A", "Project B")))
    assert results.count("idempotency_conflict") == 1
    winner = next(result for result in results if isinstance(result, dict))
    with sqlite3.connect(path) as conn:
        current = TaskStore(conn)
        current.initialize()
        assert counts(current) == [2, 2, 1]
        assert {task["project"] for task in current.run("list", {})["data"]["items"]} == {
            winner["project"]
        }


def test_process_exit_mid_plan_rolls_back_and_committed_receipt_survives_restart(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    code = """
import json, os, sqlite3, sys
from personal_agent.tasks import TaskStore
conn=sqlite3.connect(sys.argv[1], isolation_level=None)
store=TaskStore(conn); store.initialize()
original=store._capture
calls=0
def crash(*args):
    global calls
    calls += 1
    if calls == 2: os._exit(23)
    return original(*args)
if sys.argv[2] == 'crash': store._capture=crash
print(json.dumps(store.run('capture_plan', json.loads(sys.argv[3]))))
"""

    def run(mode):
        return subprocess.run(
            [sys.executable, "-c", code, str(path), mode, json.dumps(plan())],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
        )

    assert run("crash").returncode == 23
    with sqlite3.connect(path) as conn:
        current = TaskStore(conn)
        current.initialize()
        assert counts(current) == [0, 0, 0]
    first, replay = run("commit"), run("commit")
    assert first.returncode == replay.returncode == 0
    initial, repeated = json.loads(first.stdout), json.loads(replay.stdout)
    assert not initial["replayed"] and repeated["replayed"]
    assert initial["data"] == repeated["data"]


def cli(*args):
    parser = argparse.ArgumentParser()
    setup_tasks_cli(parser.add_subparsers(dest="command", required=True))
    return command_request(
        parser.parse_args(["tasks", "plan", "--project", "Demo", "--request-id", "p", *args])
    )


def test_cli_title_list_and_json_model_contract_share_normalization(store):  # noqa: F811
    simple = cli("--task", "First", "--task", "Second")
    structured = cli("--tasks-json", '[{"title":"First"},{"title":"Second","details":""}]')
    model = normalize_task_tool_request(
        "personal_tasks_write",
        {
            "action": "capture_plan",
            "project": "Demo",
            "request_id": "p",
            "tasks": [{"title": "First"}, {"title": "Second"}],
        },
    )
    assert simple == structured == model
    result = store.run(*simple)
    text = render_task_result({"status": "ok", **result}, operation=simple[0], payload=simple[1])
    assert text.startswith("Plan saved: 2 task(s).") and "Request ID: p" in text
    assert all(task["id"] in text for task in result["data"]["items"])


@pytest.mark.parametrize(
    "raw",
    [
        '[{"title":"A","title":"B"}]',
        '[{"title":"A","details":NaN}]',
        "{}",
        "[]",
        '[{"title":"A","due_date":"2030-02-30"}]',
        "[",
        "[" * 1200 + "]" * 1200,
        '[{"title":"A","project":"Other"}]',
        "x" * 32001,
    ],
)
def test_cli_json_rejects_ambiguous_invalid_or_oversized_input(raw):
    with pytest.raises(TaskError, match="invalid_request"):
        cli("--tasks-json", raw)
