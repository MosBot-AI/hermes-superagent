"""Explicit breakdown CLI/native/model contracts share strict backend validation."""

import argparse
import json
import shlex
from uuid import uuid4

import pytest

from personal_agent.conversation_tasks import _parse
from personal_agent.task_cli import command_request, setup_tasks_cli
from personal_agent.task_tool_contract import (
    PERSONAL_TASKS_WRITE_SCHEMA,
    normalize_task_tool_request,
)
from personal_agent.tasks import TaskError

TASK = str(uuid4())
STEPS = [{"title": "Second", "depends_on": [2]}, {"title": "First"}]


def cli(raw):
    parser = argparse.ArgumentParser()
    setup_tasks_cli(parser.add_subparsers(dest="command", required=True))
    return command_request(parser.parse_args(["tasks", *shlex.split(raw)]))


@pytest.mark.parametrize("parse", [cli, lambda text: _parse(text)[:2]])
def test_breakdown_explicit_json_and_titles(parse):
    operation, data = parse(
        f"breakdown {TASK} --expected-revision 3 --request-id key "
        "--tasks-json " + shlex.quote(json.dumps(STEPS))
    )
    assert operation == "breakdown" and data["task_id"] == TASK and data["expected_revision"] == 3
    assert data["tasks"][0]["depends_on"] == [2] and "project" not in data
    assert (
        parse(
            f"breakdown {TASK} --expected-revision 3 --request-id key "
            '--task "First" --task "Second"'
        )[1]["tasks"][1]["title"]
        == "Second"
    )


@pytest.mark.parametrize(
    "suffix",
    [
        "--task First",
        "--request-id key",
        "--task First --project X",
        '--request-id key --tasks-json \'[{"title":"A","title":"B"}]\'',
        '--request-id key --task A --tasks-json \'[{"title":"B"}]\'',
    ],
)
def test_native_does_not_invent_key_or_steps_or_accept_project(suffix):
    with pytest.raises(TaskError, match="invalid_request"):
        _parse(f"breakdown {TASK} --expected-revision 1 {suffix}")


def test_model_schema_and_normalization_share_existing_write_scope():
    schema = PERSONAL_TASKS_WRITE_SCHEMA
    assert "breakdown" in schema["parameters"]["properties"]["action"]["enum"]
    request = dict(
        action="breakdown", task_id=TASK, expected_revision=1, tasks=STEPS, request_id="k"
    )
    operation, payload = normalize_task_tool_request("personal_tasks_write", request)
    assert operation == "breakdown" and payload["tasks"][0]["depends_on"] == [2]
    for extra in ({"project": "Other"}, {"origin": "local"}, {"expected_revision": True}):
        with pytest.raises(TaskError):
            normalize_task_tool_request("personal_tasks_write", {**request, **extra})
    with pytest.raises(TaskError):
        normalize_task_tool_request("personal_tasks_read", request)


@pytest.mark.parametrize(
    "steps",
    [
        [{"title": "A", "depends_on": [1]}],
        [{"title": "A", "depends_on": [2]}, {"title": "B", "depends_on": [1]}],
        [{"title": "A", "depends_on": [True]}],
        [],
        [{"title": "A", "project": "Other"}],
    ],
)
def test_model_rejects_invalid_graph_before_storage(steps):
    with pytest.raises(TaskError):
        normalize_task_tool_request(
            "personal_tasks_write",
            dict(
                action="breakdown", task_id=TASK, expected_revision=1, tasks=steps, request_id="key"
            ),
        )
