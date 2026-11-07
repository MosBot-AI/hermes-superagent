"""Actual pinned-host explicit breakdown commands, activated tools and durable replay."""

import argparse
import json
import shlex

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native  # noqa: F401
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host  # noqa: F401

STEPS = [{"title": "Review", "depends_on": [2]}, {"title": "Draft"}]


def parent(host):
    prerequisite = command(host, 'add "Approval" --project Demo --request-id prerequisite')["data"]
    task = command(
        host, 'add "Deliver" --details "PRIVATE PARENT DETAILS" --project Demo --request-id parent'
    )["data"]
    linked = command(
        host,
        f"dependencies {task['id']} --expected-revision 1 "
        f"--needs {prerequisite['id']} --request-id link",
    )["data"]
    return linked, prerequisite


def raw(task):
    return (
        f"breakdown {task['id']} --expected-revision 2 --request-id breakdown --tasks-json "
        + shlex.quote(json.dumps(STEPS))
    )


def test_native_breakdown_inherits_every_prerequisite_and_never_completes_parent(host):
    task, prerequisite = parent(host)
    result = command(host, raw(task))
    assert result["status"] == "ok", result
    data = result["data"]
    review, draft = data["items"]
    assert data["parent"]["revision"] == 3 and data["parent"]["state"] == "captured"
    assert data["parent"]["work_status"] == task["work_status"]
    assert data["inherited_dependency_ids"] == [prerequisite["id"]]
    assert {d["task_id"] for d in review["dependencies"]} == {prerequisite["id"], draft["id"]}
    assert {d["task_id"] for d in draft["dependencies"]} == {prerequisite["id"]}
    assert {d["task_id"] for d in data["parent"]["dependencies"]} == {
        prerequisite["id"],
        review["id"],
        draft["id"],
    }
    assert all(step["revision"] == 1 and step["details"] == "" for step in data["items"])
    assert command(host, "ready")["data"]["items"][0]["id"] == prerequisite["id"]
    assert (
        command(
            host, f"done {task['id']} --expected-revision 3 --request-id too-soon --note Explicit"
        )["error"]["code"]
        == "dependencies_unsatisfied"
    )
    command(
        host,
        f"done {prerequisite['id']} --expected-revision 1 --request-id approval --note Explicit",
    )
    command(host, f"done {draft['id']} --expected-revision 1 --request-id draft --note Explicit")
    command(host, f"done {review['id']} --expected-revision 1 --request-id review --note Explicit")
    fresh = command(host, f"show {task['id']}")["data"]
    assert (
        fresh["state"] == "captured" and fresh["revision"] == 3 and fresh["dependencies_satisfied"]
    )
    replay = command(host, raw(task))
    assert replay["replayed"] and replay["data"] == data


def test_cli_creation_model_replay_and_reload_require_write_activation(host, capsys):
    task, _ = parent(host)
    entry = host.manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    entry["setup_fn"](parser)
    capsys.readouterr()
    assert entry["handler_fn"](parser.parse_args(["tasks", *shlex.split(raw(task))])) == 0
    first = json.loads(capsys.readouterr().out)
    request = dict(
        action="breakdown",
        task_id=task["id"],
        expected_revision=2,
        request_id="breakdown",
        tasks=STEPS,
    )
    activate(host, "enable-read")
    with turn(host):
        assert call(host, request, write=True)["error"]["code"] == "session_write_not_activated"
    activate(host, "enable-write")
    with turn(host):
        replay = call(host, request, write=True)
    assert replay["replayed"] and replay["data"] == first["data"]
    host.manager.discover_and_load(force=True)
    with turn(host):
        assert call(host, request, write=True)["error"]["code"] == "session_tools_not_activated"
    activate(host, "enable-write")
    with turn(host):
        assert call(host, request, write=True)["data"] == first["data"]
    assert len(command(host, "list")["data"]["items"]) == 4


@pytest.mark.parametrize("change", [{"sid": "other"}, {"key": "other"}, {"parent": "parent"}])
def test_breakdown_cannot_expand_session_authority(host, change):
    task, _ = parent(host)
    before = database(host.home).read_bytes()
    activate(host, "enable-write")
    with turn(host, **change):
        result = call(
            host,
            dict(
                action="breakdown",
                task_id=task["id"],
                expected_revision=2,
                request_id="breakdown",
                tasks=STEPS,
            ),
            write=True,
            sid=change.get("sid"),
        )
    assert result["status"] == "error" and database(host.home).read_bytes() == before


def test_activated_model_creates_explicit_steps_without_copying_parent_text(host):
    task, _ = parent(host)
    activate(host, "enable-write")
    with turn(host):
        result = call(
            host,
            dict(
                action="breakdown",
                task_id=task["id"],
                expected_revision=2,
                request_id="model-breakdown",
                tasks=STEPS,
            ),
            write=True,
        )
    assert result["status"] == "ok", result
    assert [item["title"] for item in result["data"]["items"]] == ["Review", "Draft"]
    assert all(item["details"] == "" for item in result["data"]["items"])
    assert result["data"]["parent"]["state"] == "captured"


@pytest.mark.parametrize(
    "extra",
    [
        {"project": "Other"},
        {"expected_revision": 1},
        {"tasks": [{"title": "Cycle", "depends_on": [1]}]},
    ],
)
def test_invalid_or_stale_breakdown_preserves_existing_database(host, extra):
    task, _ = parent(host)
    before = database(host.home).read_bytes()
    activate(host, "enable-write")
    with turn(host):
        result = call(
            host,
            dict(
                action="breakdown",
                task_id=task["id"],
                expected_revision=2,
                request_id="invalid-breakdown",
                tasks=STEPS,
            )
            | extra,
            write=True,
        )
    assert result["status"] == "error"
    assert database(host.home).read_bytes() == before
