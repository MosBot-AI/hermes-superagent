"""Dependency command and model boundaries, and truthful local-only presentation."""

import argparse
import copy
import sqlite3
from uuid import uuid4

import pytest

from personal_agent.conversation_tasks import _parse
from personal_agent.task_cli import command_request, setup_tasks_cli
from personal_agent.task_presentation import render_task_result
from personal_agent.task_tool_contract import (
    PERSONAL_TASKS_READ_SCHEMA,
    PERSONAL_TASKS_WRITE_SCHEMA,
    normalize_task_tool_request,
)
from personal_agent.tasks import TaskError, TaskStore

ID = str(uuid4())
NEEDS = str(uuid4())


def cli(raw):
    import shlex

    parser = argparse.ArgumentParser()
    setup_tasks_cli(parser.add_subparsers(dest="command", required=True))
    return command_request(parser.parse_args(["tasks", *shlex.split(raw)]))


@pytest.mark.parametrize("parse", [cli, lambda raw: _parse(raw)[:2]])
def test_dependencies_explicit_replace_and_clear(parse):
    suffix = " --expected-revision 1 --request-id stable"
    operation, payload = parse(f"dependencies {ID} --needs {NEEDS}{suffix}")
    assert operation == "set_dependencies"
    assert payload == dict(
        task_id=ID, dependency_ids=[NEEDS], expected_revision=1, request_id="stable"
    )
    assert parse(f"dependencies {ID} --clear{suffix}")[1]["dependency_ids"] == []
    assert parse("ready --unassigned --limit 3")[0] == "ready"
    assert parse('ready --project "Exact Project"')[1]["project"] == "Exact Project"


@pytest.mark.parametrize(
    "suffix",
    [
        "--needs " + NEEDS,
        "--clear",
        "--request-id key",
        "--needs " + NEEDS + " --clear --request-id key",
        "--needs " + NEEDS + " --needs " + NEEDS + " --request-id key",
    ],
)
def test_native_dependencies_never_invents_key_or_set(suffix):
    with pytest.raises(TaskError, match="invalid_request"):
        _parse(f"dependencies {ID} --expected-revision 1 {suffix}")


@pytest.mark.parametrize(
    "arguments",
    [
        {"dependency_ids": [NEEDS] * 2},
        {"dependency_ids": [str(uuid4()) for _ in range(21)]},
        {"dependency_ids": [NEEDS.upper()]},
        {"dependency_ids": None},
        {"dependency_ids": [], "expected_revision": True},
        {"dependency_ids": [], "origin": "local"},
    ],
)
def test_model_dependency_validation(arguments):
    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request(
            "personal_tasks_write",
            {
                "action": "set_dependencies",
                "task_id": ID,
                "expected_revision": 1,
                "request_id": "stable",
                **arguments,
            },
        )


def test_model_actions_stay_separated_and_strict():
    assert "ready" in PERSONAL_TASKS_READ_SCHEMA["parameters"]["properties"]["action"]["enum"]
    field = PERSONAL_TASKS_WRITE_SCHEMA["parameters"]["properties"]["dependency_ids"]
    assert field["uniqueItems"] and field["maxItems"] == 20
    assert (
        normalize_task_tool_request(
            "personal_tasks_write",
            {
                "action": "set_dependencies",
                "task_id": ID,
                "expected_revision": 1,
                "request_id": "clear",
                "dependency_ids": [],
            },
        )[0]
        == "set_dependencies"
    )
    for tool, args in [
        ("personal_tasks_read", {"action": "set_dependencies"}),
        ("personal_tasks_write", {"action": "ready"}),
        ("personal_tasks_read", {"action": "ready", "work_status": "in_progress"}),
        ("personal_tasks_read", {"action": "ready", "project": "A", "unassigned": True}),
    ]:
        with pytest.raises(TaskError):
            normalize_task_tool_request(tool, args)


def test_real_receipts_blockers_ready_and_old_unknown():
    with sqlite3.connect(":memory:") as connection:
        store = TaskStore(connection)
        store.initialize()
        first = store.run(
            "capture",
            {"title": "Prerequisite secret title", "project": "Demo", "request_id": "first"},
        )["data"]
        target = store.run(
            "capture", {"title": "Target", "project": "Demo", "request_id": "target"}
        )["data"]
        operation, payload, _ = _parse(
            f"dependencies {target['id']} --needs {first['id']} "
            "--expected-revision 1 --request-id deps"
        )
        receipt = {"status": "ok", **store.run(operation, payload)}
        text = render_task_result(receipt, operation=operation, payload=payload)
        assert "unsatisfied: 1 | blocked" in text and first["id"] in text
        assert "Prerequisite secret title" not in text
        assert "no work, reminder or external action was executed" in text
        legacy = copy.deepcopy(receipt)
        for key in ("dependencies", "dependencies_satisfied", "unsatisfied_dependency_count"):
            del legacy["data"][key]
        assert "unknown (not recorded" in render_task_result(legacy, operation="get", payload={})
        ready = {"status": "ok", **store.run("ready", {})}
        text = render_task_result(ready, operation="ready", payload={})
        assert "Total eligible: 1" in text and '"Target"' not in text
        assert "oldest first, not priority" in text and "No dispatch" in text
        review = {"status": "ok", **store.run("review", {"on": "2026-11-07"})}
        text = render_task_result(review, operation="review", payload={})
        assert "Prerequisites: satisfied 1, blocked 1" in text
        assert "unsatisfied: 1 | blocked" in text


@pytest.mark.parametrize(
    "code",
    [
        "dependency_cycle",
        "dependency_project_required",
        "dependency_project_mismatch",
        "dependencies_unsatisfied",
        "dependency_project_locked",
    ],
)
def test_dependency_errors_have_fixed_readable_explanations(code):
    text = render_task_result(
        {"status": "error", "error": {"code": code}}, operation="set_dependencies", payload={}
    )
    assert text.startswith("Task request failed: " + code)
    assert "local_tasks_unavailable" not in text


def test_ready_display_cursor_roundtrip_preserves_filters_and_oldest_order():
    with sqlite3.connect(":memory:") as connection:
        store = TaskStore(connection)
        store.initialize()
        ids = []
        for number in range(22):
            ids.append(
                store.run(
                    "capture",
                    {
                        "title": f"Synthetic {number}",
                        "project": "Exact project",
                        "request_id": f"capture-{number}",
                    },
                )["data"]["id"]
            )
        payload = {"project": "Exact project", "limit": 100}
        result = {"status": "ok", **store.run("ready", payload)}
        assert [item["id"] for item in result["data"]["items"]] == ids
        text = render_task_result(result, operation="ready", payload=payload)
        command = next(
            line.removeprefix("More: /personal-tasks ")
            for line in text.splitlines()
            if line.startswith("More: ")
        )
        operation, followup, _ = _parse(command)
        assert operation == "ready" and followup["project"] == "Exact project"
        assert followup["after"] == ids[19]
        page = store.run(operation, followup)["data"]
        assert [item["id"] for item in page["items"]] == ids[20:]
        assert page["total_eligible"] == 22
