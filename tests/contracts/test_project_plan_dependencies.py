"""Atomic indexed plans through actual native commands, CLI and activated tools.

Synthetic local data only. No provider, listener, worker or installation occurs.
"""

import argparse
import json
import shlex
import sqlite3

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native  # noqa: F401
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host  # noqa: F401


def tasks():
    return [
        {"title": "Review", "depends_on": [2]},
        {"title": "Draft"},
        {"title": "Publish", "depends_on": [1, 2]},
    ]


def request(items=None, key="indexed-plan"):
    return {
        "action": "capture_plan",
        "project": "Synthetic plan",
        "request_id": key,
        "tasks": tasks() if items is None else items,
    }


def native_plan(host, items=None, key="indexed-plan"):
    return command(
        host,
        'plan --project "Synthetic plan" --request-id '
        + key
        + " --tasks-json "
        + shlex.quote(json.dumps(tasks() if items is None else items)),
    )


def assert_graph(result):
    assert result["status"] == "ok", result
    review, draft, publish = result["data"]["items"]
    assert [item["title"] for item in (review, draft, publish)] == ["Review", "Draft", "Publish"]
    assert all(item["revision"] == 1 for item in (review, draft, publish))
    assert review["dependencies"] == [{"task_id": draft["id"], "revision": 1, "state": "captured"}]
    assert {dep["task_id"] for dep in publish["dependencies"]} == {review["id"], draft["id"]}
    assert draft["dependencies"] == [] and draft["dependencies_satisfied"]
    assert review["unsatisfied_dependency_count"] == 1
    assert publish["unsatisfied_dependency_count"] == 2
    return review, draft, publish


def test_native_forward_reference_plan_ready_and_immediate_transition_gates(host):
    config = (host.home / "config.yaml").read_bytes()
    result = native_plan(host)
    review, draft, publish = assert_graph(result)
    ready = command(host, 'ready --project "Synthetic plan"')["data"]
    assert [item["id"] for item in ready["items"]] == [draft["id"]]
    for verb in ("done", "progress"):
        suffix = " --work-status in_progress" if verb == "progress" else ""
        refused = command(
            host,
            f"{verb} {review['id']} --expected-revision 1 "
            f"--request-id premature-{verb} --note Explicit{suffix}",
        )
        assert refused["error"]["code"] == "dependencies_unsatisfied"
    completed = command(
        host, f"done {draft['id']} --expected-revision 1 --request-id draft-done --note Explicit"
    )
    assert completed["status"] == "ok"
    assert command(host, f"show {review['id']}")["data"]["revision"] == 1
    assert [item["id"] for item in command(host, "ready")["data"]["items"]] == [review["id"]]
    assert native_plan(host)["data"] == result["data"]  # Historical graph receipt, not fresh state.
    assert command(host, f"show {publish['id']}")["data"]["unsatisfied_dependency_count"] == 1
    with sqlite3.connect(database(host.home)) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM events WHERE operation='capture_plan'"
            ).fetchone()[0]
            == 3
        )
        assert connection.execute("SELECT count(*) FROM task_dependencies").fetchone()[0] == 3
    assert (host.home / "config.yaml").read_bytes() == config


def test_model_cli_reload_share_exact_ordered_receipt_and_activation_boundary(host, capsys):
    activate(host, "enable-read")
    with turn(host):
        assert call(host, request(), write=True)["error"]["code"] == "session_write_not_activated"
    assert not database(host.home).exists()
    activate(host, "enable-write")
    with turn(host):
        first = call(host, request(), write=True)
    assert_graph(first)
    entry = host.manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    entry["setup_fn"](parser)
    capsys.readouterr()
    assert (
        entry["handler_fn"](
            parser.parse_args(
                [
                    "tasks",
                    "plan",
                    "--project",
                    "Synthetic plan",
                    "--request-id",
                    "indexed-plan",
                    "--tasks-json",
                    json.dumps(tasks()),
                ]
            )
        )
        == 0
    )
    replay = json.loads(capsys.readouterr().out)
    assert replay["replayed"] and replay["data"] == first["data"]
    host.manager.discover_and_load(force=True)
    with turn(host):
        assert call(host, request(), write=True)["error"]["code"] == "session_tools_not_activated"
    activate(host, "enable-write")
    with turn(host):
        replay = call(host, request(), write=True)
    assert replay["replayed"] and replay["data"] == first["data"]
    assert len(command(host, "list")["data"]["items"]) == 3


@pytest.mark.parametrize(
    "bad",
    [
        [{"title": "Self", "depends_on": [1]}],
        [{"title": "A", "depends_on": [2]}, {"title": "B", "depends_on": [1]}],
        [{"title": "A", "depends_on": [2, 2]}, {"title": "B"}],
        [{"title": "A", "depends_on": [0]}],
        [{"title": "A", "depends_on": [2]}],
        [{"title": "A", "depends_on": [True]}],
        [{"title": "A", "depends_on": [1.0]}],
        [{"title": "A", "depends_on": None}],
    ],
)
def test_invalid_graph_native_and_model_leave_existing_database_unchanged(host, bad):
    command(host, 'add "Existing" --request-id existing')
    before = database(host.home).read_bytes()
    assert native_plan(host, bad)["status"] == "error"
    assert database(host.home).read_bytes() == before
    activate(host, "enable-write")
    with turn(host):
        assert call(host, request(bad), write=True)["status"] == "error"
    assert database(host.home).read_bytes() == before


@pytest.mark.parametrize(
    "change",
    [{"sid": "other"}, {"key": "other-route"}, {"parent": "parent"}, {"platform": "telegram"}],
)
def test_dependent_plan_does_not_expand_turn_authority(host, change):
    activate(host, "enable-write")
    with turn(host, **change):
        result = call(host, request(), write=True, sid=change.get("sid"))
    assert result["status"] == "error"
    assert not database(host.home).exists()


def test_missing_and_empty_dependency_lists_preserve_legacy_request_identity(host):
    first = native_plan(host, [{"title": "A"}, {"title": "B"}])
    assert first["status"] == "ok", first
    replay = native_plan(host, [{"title": "A", "depends_on": []}, {"title": "B", "depends_on": []}])
    assert replay["replayed"] and replay["data"] == first["data"]


def test_cli_fresh_dependent_plan_is_visible_to_native_and_read_activated_model(host, capsys):
    entry = host.manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    entry["setup_fn"](parser)
    capsys.readouterr()
    assert (
        entry["handler_fn"](
            parser.parse_args(
                [
                    "tasks",
                    "plan",
                    "--project",
                    "Synthetic plan",
                    "--request-id",
                    "cli-new",
                    "--tasks-json",
                    json.dumps(tasks()),
                ]
            )
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    _, draft, _ = assert_graph(created)
    assert not created["replayed"]
    assert native_plan(host, key="cli-new")["data"] == created["data"]
    activate(host, "enable-read")
    with turn(host):
        ready = call(host, {"action": "ready", "project": "Synthetic plan"})
        assert [item["id"] for item in ready["data"]["items"]] == [draft["id"]]
        refused = call(host, request(key="different"), write=True)
        assert refused["error"]["code"] == "session_write_not_activated"
