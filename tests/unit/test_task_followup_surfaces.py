"""Explicit follow-up dates and dated reads, never background reminders."""

import json
import sqlite3
from uuid import uuid4

import pytest

from personal_agent.conversation_tasks import _parse
from personal_agent.task_focus import task_context
from personal_agent.task_presentation import render_task_result
from personal_agent.task_tool_contract import normalize_task_tool_request
from personal_agent.tasks import TaskError, TaskStore


def test_date_set_clear_and_omission_normalize_without_defaults():
    rid = str(uuid4())
    base = f"update {rid} --expected-revision 1 --request-id change"
    assert _parse(base + " --follow-up-on 2026-11-20")[1]["follow_up_on"] == "2026-11-20"
    assert _parse(base + " --clear-follow-up-on")[1]["follow_up_on"] is None
    assert "follow_up_on" not in _parse(base + " --title explicit")[1]
    with pytest.raises(TaskError):
        _parse(base + " --follow-up-on 2026-11-20 --clear-follow-up-on")
    for action in ("update", "progress"):
        data = {
            "action": action,
            "task_id": rid,
            "expected_revision": 1,
            "request_id": "a",
            "follow_up_on": "2026-11-20",
        }
        if action == "progress":
            data.update(work_status="waiting", note="Waiting explicitly")
        assert (
            normalize_task_tool_request("personal_tasks_write", data)[1]["follow_up_on"]
            == "2026-11-20"
        )


def test_followups_requires_date_and_has_no_cursor_or_implicit_state():
    assert _parse("followups --on 2026-11-20")[:2] == (
        "followups",
        {"on": "2026-11-20", "limit": 20},
    )
    for raw in (
        "followups",
        "followups --on today",
        "followups --on 2026-11-20 --after x",
        "followups --on 2026-11-20 --limit 101",
    ):
        with pytest.raises(TaskError):
            _parse(raw)
    assert normalize_task_tool_request(
        "personal_tasks_read",
        {
            "action": "followups",
            "on": "2026-11-20",
            "unassigned": True,
        },
    )[1] == {"on": "2026-11-20", "limit": 20, "unassigned": True}
    with pytest.raises(TaskError):
        normalize_task_tool_request(
            "personal_tasks_write",
            {
                "action": "followups",
                "on": "2026-11-20",
                "request_id": "a",
            },
        )
    for data in (
        {"action": "capture", "title": "Task", "follow_up_on": "2026-11-20"},
        {
            "action": "capture_plan",
            "project": "Demo",
            "tasks": [{"title": "Task", "follow_up_on": "2026-11-20"}],
        },
    ):
        with pytest.raises(TaskError):
            normalize_task_tool_request("personal_tasks_write", {**data, "request_id": "a"})


def test_current_and_historical_followup_presentation():
    with sqlite3.connect(":memory:") as connection:
        store = TaskStore(connection)
        store.initialize()
        task = store.run("capture", {"title": "Waiting", "request_id": "a"})["data"]
        task = store.run(
            "progress",
            {
                "task_id": task["id"],
                "expected_revision": 1,
                "request_id": "b",
                "work_status": "waiting",
                "note": "Explicit",
                "follow_up_on": "2026-11-20",
            },
        )["data"]
        context = json.loads(task_context(task).split("\n", 1)[1])
        assert context["task"]["follow_up_on"] == "2026-11-20"
        payload = {"on": "2026-11-20"}
        text = render_task_result(
            {"status": "ok", "error": None, **store.run("followups", payload)},
            operation="followups",
            payload=payload,
        )
        assert "Follow-up: 2026-11-20" in text
        assert "not reminders or outreach permission" in text
        assert "--after" not in text
        task.pop("follow_up_on")
        historical = render_task_result(
            {"status": "ok", "data": task, "replayed": True}, operation="progress", payload={}
        )
        assert "Follow-up: not recorded in this receipt" in historical
