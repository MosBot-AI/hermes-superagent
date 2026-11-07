"""Advisory board observations never imply changes to local task completion."""

import copy

import pytest

from personal_agent.status import build_status
from personal_agent.task_presentation import _task_lines, render_task_result


def task():
    return {
        "id": "task-1",
        "title": "演示任务 ✅",
        "revision": 3,
        "state": "captured",
        "work_status": "blocked",
        "details": "Private details",
    }


def observation(outcome="current", status="done"):
    return {
        "handoff_id": "handoff-1",
        "card_id": "card-1",
        "outcome": outcome,
        "status": status,
        "observed_at": 1794000000,
        "exported_revision": 1,
    }


@pytest.mark.parametrize(
    "status",
    ["triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"],
)
def test_all_native_states_are_advisory_and_do_not_mutate_local_task(status):
    value = task() | {"native_progress": observation(status=status)}
    original = copy.deepcopy(value)
    rendered = render_task_result({"status": "ok", "data": value}, operation="get", payload={})
    assert "Native board observed " + status + " (not local completion)" in rendered
    assert "[blocked]" in rendered and "演示任务 ✅" in rendered
    assert "exported revision: 1" in rendered and "1794000000" in rendered
    assert value == original


@pytest.mark.parametrize(
    "outcome", ["missing", "duplicate", "identity_changed", "key_changed", "identity_unavailable"]
)
def test_unknown_outcomes_never_show_an_old_status(outcome):
    value = task() | {"native_progress": observation(outcome, None)}
    text = "\n".join(_task_lines(value))
    assert outcome + "; status unavailable (not local completion)" in text
    assert "observed done" not in text and "card-1" not in text
    assert "Private details" not in text


def test_old_receipt_unknown_differs_from_current_no_observation():
    assert "unknown (not recorded in this receipt)" in "\n".join(_task_lines(task()))
    assert "no observations recorded" in "\n".join(_task_lines(task() | {"native_progress": None}))


def test_page_is_bounded_and_does_not_expand_native_identity_details():
    rows = [task() | {"id": str(i), "native_progress": observation()} for i in range(25)]
    text = render_task_result(
        {"status": "ok", "data": {"items": rows, "has_more": True}}, operation="list", payload={}
    )
    assert text.count("Native board observed") == 20
    assert "handoff-1" not in text and "Private details" not in text
    assert "More:" in text


def test_status_reports_configuration_not_runtime_or_completion_verification():
    disabled = build_status()["kanban_handoff"]
    assert disabled["native_progress_sync_implemented"]
    assert not disabled["native_progress_sync_enabled"]
    enabled = build_status(
        mode="local_tasks",
        local_conversation=True,
        kanban_handoff=True,
        kanban_handoff_board="default",
    )["kanban_handoff"]
    assert enabled["native_progress_sync_enabled"]
    for key in (
        "native_progress_sync_live_verified",
        "native_progress_sync_automatic",
        "native_progress_sync_changes_completion",
        "native_runtime_verified",
        "native_schema_verified",
        "dispatch_enabled",
    ):
        assert enabled[key] is False
