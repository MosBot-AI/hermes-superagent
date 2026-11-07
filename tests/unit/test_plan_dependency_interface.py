"""Explicit positional plan dependencies remain data, never execution authority."""

import argparse
import json
from copy import deepcopy

import pytest

from personal_agent.status import build_status
from personal_agent.task_cli import command_request, setup_tasks_cli
from personal_agent.task_presentation import render_task_result
from personal_agent.task_tool_contract import (
    PERSONAL_TASKS_WRITE_SCHEMA,
    normalize_task_tool_request,
)
from personal_agent.tasks import TaskError


def task_request():
    return {
        "project": "Demo",
        "request_id": "dag-plan",
        "tasks": [{"title": "Review", "depends_on": [2]}, {"title": "Draft"}],
    }


def test_cli_json_and_model_normalize_the_same_explicit_graph():
    parser = argparse.ArgumentParser()
    setup_tasks_cli(parser.add_subparsers(dest="command", required=True))
    request = task_request()
    args = parser.parse_args(
        [
            "tasks",
            "plan",
            "--project",
            request["project"],
            "--request-id",
            request["request_id"],
            "--tasks-json",
            json.dumps(request["tasks"]),
        ]
    )
    cli = command_request(args)
    model = normalize_task_tool_request(
        "personal_tasks_write", {"action": "capture_plan", **request}
    )
    assert cli == model
    assert model[1]["tasks"][0]["depends_on"] == [2]
    assert "depends_on" not in model[1]["tasks"][1]


def test_schema_names_one_based_positions_without_external_ids():
    schema = PERSONAL_TASKS_WRITE_SCHEMA["parameters"]["properties"]["tasks"]["items"]
    refs = schema["properties"]["depends_on"]
    assert refs["items"] == {"type": "integer", "minimum": 1, "maximum": 20}
    assert refs["uniqueItems"] and refs["maxItems"] == 19
    assert "ONE-BASED" in refs["description"]
    assert not schema["additionalProperties"]


@pytest.mark.parametrize(
    "extra", [{"approved": True}, {"provider": "other"}, {"task_id": "pretend-existing-id"}]
)
def test_nested_authority_or_external_reference_remains_rejected(extra):
    request = task_request()
    request["tasks"][0].update(extra)
    with pytest.raises(TaskError):
        normalize_task_tool_request("personal_tasks_write", {"action": "capture_plan", **request})


def result():
    items = [
        dict(
            id="task-review",
            title="审阅",
            revision=1,
            state="captured",
            work_status="ready",
            dependencies=[{"task_id": "task-draft", "revision": 1, "state": "captured"}],
            dependencies_satisfied=False,
            unsatisfied_dependency_count=1,
        ),
        dict(
            id="task-draft",
            title="草稿",
            revision=1,
            state="captured",
            work_status="ready",
            dependencies=[],
            dependencies_satisfied=True,
            unsatisfied_dependency_count=0,
        ),
    ]
    return {"status": "ok", "data": {"project": "Demo", "items": items}, "replayed": False}


def test_native_receipt_explains_saved_index_links_and_ready_view_without_mutation():
    data = result()
    original = deepcopy(data)
    text = render_task_result(data, operation="capture_plan", payload={})
    assert data == original
    for fragment in [
        "Plan item 1",
        "Plan item 2",
        "Needs plan item(s): 2",
        "Saved prerequisite links: 1",
        "Input order is not execution order",
        "No task started, completed or dispatched",
        "ready --project=Demo",
        "审阅",
        "草稿",
    ]:
        assert fragment in text


def test_legacy_receipt_absence_is_unknown_not_zero_and_replay_is_historical():
    data = result()
    data["replayed"] = True
    for task in data["data"]["items"]:
        for field in ["dependencies", "dependencies_satisfied", "unsatisfied_dependency_count"]:
            task.pop(field)
    text = render_task_result(data, operation="capture_plan", payload={})
    assert "Replayed saved plan receipt" in text
    assert "metadata unavailable" in text and "Saved prerequisite links: 0" not in text


def test_status_adds_no_dispatch_or_reminder_claim():
    assert not build_status()["capabilities"]["atomic_project_plan_dependencies"]
    current = build_status(mode="local_tasks")
    assert current["capabilities"]["atomic_project_plan_dependencies"]
    assert current["local_task_inbox"]["plan_dependencies_atomic_with_capture"]
    assert not current["capabilities"]["reminders"]
    assert not current["kanban_handoff"]["dispatch_enabled"]
