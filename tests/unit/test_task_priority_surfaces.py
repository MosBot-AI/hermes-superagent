"""Explicit priority and next-work surfaces preserve existing admission contracts."""

import argparse
import json
import sqlite3
from uuid import uuid4

import pytest

from personal_agent.conversation_tasks import _parse
from personal_agent.task_cli import command_request, setup_tasks_cli
from personal_agent.task_focus import task_context
from personal_agent.task_presentation import render_task_result
from personal_agent.task_tool_contract import normalize_task_tool_request
from personal_agent.tasks import TaskError, TaskStore


def cli(*arguments):
    parser = argparse.ArgumentParser()
    setup_tasks_cli(parser.add_subparsers(dest="command", required=True))
    return command_request(parser.parse_args(["tasks", *arguments]))


def test_priority_omission_is_not_injected_in_cli_or_model_requests():
    operation, request = cli("capture", "--title", "Task", "--request-id", "a")
    assert operation == "capture" and "priority" not in request
    operation, request = normalize_task_tool_request(
        "personal_tasks_write", {"action": "capture", "title": "Task", "request_id": "a"}
    )
    assert "priority" not in request


@pytest.mark.parametrize("priority", ["high", "normal", "low"])
def test_priority_cli_conversation_and_model_normalization(priority):
    operation, request = cli(
        "capture", "--title", "Task", "--priority", priority, "--request-id", "a"
    )
    assert request["priority"] == priority
    op, payload, _ = _parse(f'add "Task" --priority {priority} --request-id a')
    assert (op, payload) == (operation, request)
    rid = str(uuid4())
    for action in ("capture", "update"):
        data = {"action": action, "priority": priority, "request_id": "b"}
        if action == "capture":
            data["title"] = "Task"
        else:
            data.update(task_id=rid, expected_revision=1)
        assert normalize_task_tool_request("personal_tasks_write", data)[1]["priority"] == priority


def test_plan_and_breakdown_json_accept_explicit_item_priority():
    tasks = json.dumps([{"title": "Explicit", "priority": "high"}, {"title": "Default"}])
    plan = cli("plan", "--project", "Demo", "--tasks-json", tasks, "--request-id", "plan")[1]
    steps = cli(
        "breakdown",
        str(uuid4()),
        "--expected-revision",
        "1",
        "--tasks-json",
        tasks,
        "--request-id",
        "steps",
    )[1]
    for payload in (plan, steps):
        assert payload["tasks"][0]["priority"] == "high"
        assert "priority" not in payload["tasks"][1]


def test_next_read_limits_and_no_cursor_or_write_escalation():
    assert cli("next") == ("next", {"limit": 5})
    assert _parse("next --limit 20 --project Demo")[:2] == (
        "next",
        {"limit": 20, "project": "Demo"},
    )
    assert normalize_task_tool_request("personal_tasks_read", {"action": "next"}) == (
        "next",
        {"limit": 5},
    )
    for extra in (
        {"after": None},
        {"limit": 21},
        {"priority": "high"},
        {"project": "Demo", "unassigned": True},
    ):
        with pytest.raises(TaskError):
            normalize_task_tool_request("personal_tasks_read", {"action": "next", **extra})
    with pytest.raises(TaskError):
        normalize_task_tool_request("personal_tasks_write", {"action": "next", "request_id": "a"})
    with pytest.raises(TaskError):
        _parse("next --after abc")


def test_priority_readable_next_and_focus_with_historical_receipt():
    with sqlite3.connect(":memory:") as connection:
        store = TaskStore(connection)
        store.initialize()
        task = store.run(
            "capture", {"title": "Explicit high", "request_id": "a", "priority": "high"}
        )["data"]
        assert json.loads(task_context(task).split("\n", 1)[1])["task"]["priority"] == "high"
        result = {"status": "ok", "error": None, **store.run("next", {})}
        text = render_task_result(result, operation="next", payload={})
        assert "Priority: high" in text and "not permission or dispatch" in text
        assert "More:" not in text and "--after" not in text
        historical = dict(task)
        historical.pop("priority")
        text = render_task_result(
            {"status": "ok", "data": historical, "replayed": True, "error": None},
            operation="capture",
            payload={},
        )
        assert "Priority: not recorded in this receipt" in text
