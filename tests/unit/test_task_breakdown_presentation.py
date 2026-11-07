"""Readable explicit breakdown receipts do not imply execution or ownership."""

from copy import deepcopy

import pytest

from personal_agent.status import build_status
from personal_agent.task_presentation import render_task_result


def receipt():
    def task(id, title, deps, revision=1):
        return dict(
            id=id,
            title=title,
            revision=revision,
            project="发布 ' / --flag",
            state="captured",
            work_status="ready",
            dependencies=[{"task_id": dep, "revision": 1, "state": "captured"} for dep in deps],
            dependencies_satisfied=not deps,
            unsatisfied_dependency_count=len(deps),
        )

    return dict(
        status="ok",
        replayed=False,
        data=dict(
            project="发布 ' / --flag",
            parent=task("parent", "发布", ["existing", "draft", "review"], revision=4),
            inherited_dependency_ids=["existing"],
            items=[
                task("draft", "Draft\nNo execution", ["existing"]),
                task("review", "审阅", ["existing", "draft"]),
            ],
        ),
    )


def test_receipt_explains_original_and_steps_and_inherited_links_without_mutation():
    result = receipt()
    before = deepcopy(result)
    text = render_task_result(result, operation="breakdown", payload={"request_id": "break-1"})
    assert result == before
    for expected in (
        "Task breakdown saved: 2",
        "Saved prerequisite links: 5",
        "Original task (not completed)",
        "revision: 4",
        "Existing prerequisites inherited by every new step: 1",
        "Inherited prerequisite: existing",
        "Needs plan item(s): 1",
        "not exclusive subtask ownership",
        "does not cancel its steps",
        "explicit review and completion are still required",
        "No task started, completed or dispatched",
        "Original: /personal-tasks show parent",
        "Request ID: break-1",
        "审阅",
        "Draft\\nNo execution",
    ):
        assert expected in text
    assert "\nNo execution" not in text


def test_breakdown_replay_uses_historical_receipt_and_no_mutation_suggestions():
    result = receipt()
    result["replayed"] = True
    text = render_task_result(
        result, operation="breakdown", payload={}, prefix="hermes personal-agent tasks"
    )
    assert "Replayed saved plan receipt" in text
    assert "Use show for each task's current state" in text
    assert "Original: hermes personal-agent tasks show parent --format text" in text
    assert " done " not in text


@pytest.mark.parametrize("code", ["dependency_limit", "breakdown_in_progress"])
def test_specific_error_recovery_does_not_suggest_bypassing_gate(code):
    text = render_task_result(
        dict(status="error", error={"code": code}), operation="breakdown", payload={}
    )
    assert code in text
    assert "local_tasks_unavailable" not in text


def test_status_is_explicitly_local_without_hierarchy_or_automatic_completion():
    status = build_status(mode="local_tasks")
    assert status["capabilities"]["atomic_task_breakdown"]
    assert status["local_task_inbox"]["breakdown_inherits_existing_prerequisites"]
    assert not status["local_task_inbox"]["breakdown_parent_auto_completion"]
    assert not status["local_task_inbox"]["breakdown_ownership_hierarchy"]
    assert not build_status()["capabilities"]["atomic_task_breakdown"]
    assert not status["capabilities"]["worker_model_routing"]


def test_help_exposes_real_entrypoint_not_automatic_worker():
    text = render_task_result(dict(status="ok", data={}), operation="help", payload={})
    assert "breakdown TASK_ID --expected-revision N" in text
    assert "It never completes the original task" in text
