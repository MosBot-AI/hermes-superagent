"""Native commands, CLI and activated model dispatch share one atomic plan receipt."""

import argparse
import json

import pytest
from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host
from test_task_focus import collect
from test_task_workbench import human


def request(**extra):
    return {
        "action": "capture_plan",
        "project": "Native project",
        "request_id": "native-plan",
        "tasks": [
            {"title": "Prepare", "details": "Make a demo"},
            {"title": "Review", "due_date": "2030-01-02"},
        ],
        **extra,
    }


def test_native_plan_capture_replay_review_edit_and_focus(host):
    config = (host.home / "config.yaml").read_bytes()
    text = human(
        host,
        'plan --project "Native project" --task "Prepare" --task "Review" --request-id native-plan',
    )
    assert text.startswith("Plan saved: 2 task(s).")
    replay = command(
        host,
        'plan --project "Native project" --task "Prepare" --task "Review" --request-id native-plan',
    )
    assert replay["replayed"] and len(replay["data"]["items"]) == 2
    selected = replay["data"]["items"][0]
    assert selected["id"] in text and "Request ID: native-plan" in text
    assert command(host, "projects")["data"]["items"][0]["total"] == 2
    assert (
        command(host, 'review --on 2030-01-01 --project "Native project"')["data"]["counts"][
            "total_active"
        ]
        == 2
    )
    activate(host, "enable-write")
    assert activate(host, "focus " + selected["id"])["status"] == "ok"
    with turn(host):
        assert selected["id"] in collect(host)
        updated = call(
            host,
            {
                "action": "progress",
                "task_id": selected["id"],
                "expected_revision": 1,
                "work_status": "in_progress",
                "note": "Draft started",
                "request_id": "progress",
            },
            write=True,
        )
        assert updated["data"]["revision"] == 2
    with turn(host):
        assert '"revision": 2' in collect(host)
    assert (host.home / "config.yaml").read_bytes() == config


def test_activated_model_captures_batch_once_and_cli_reads_same_records(host, capsys):
    activate(host, "enable-read")
    with turn(host):
        assert call(host, request(), write=True)["error"]["code"] == "session_write_not_activated"
    assert not database(host.home).exists()
    activate(host, "enable-write")
    with turn(host):
        first = call(host, request(), write=True)
        assert first["status"] == "ok", first
        assert call(host, request(), write=True)["replayed"]
        assert (
            call(host, request(project="Other"), write=True)["error"]["code"]
            == "idempotency_conflict"
        )
        assert call(host, {"action": "list"})["data"]["items"] == list(
            reversed(first["data"]["items"])
        )
    entry = host.manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    entry["setup_fn"](parser)
    capsys.readouterr()
    code = entry["handler_fn"](
        parser.parse_args(
            [
                "tasks",
                "plan",
                "--project",
                "Native project",
                "--request-id",
                "native-plan",
                "--tasks-json",
                json.dumps(request()["tasks"]),
            ]
        )
    )
    assert code == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["replayed"] and replay["data"] == first["data"]


@pytest.mark.parametrize(
    "change",
    [{"sid": "other"}, {"parent": "parent"}, {"platform": "telegram"}, {"key": "other-route"}],
)
def test_wrong_scope_plan_never_opens_storage(host, change):
    activate(host, "enable-write")
    with turn(host, **change):
        result = call(host, request(), write=True, sid=change.get("sid"))
    assert result["status"] == "error"
    assert not database(host.home).exists()


def test_native_plan_requires_stable_key_and_validates_all_items_before_storage(host):
    assert command(host, "plan --project Demo --task First")["error"]["code"] == "invalid_request"
    assert not database(host.home).exists()
    activate(host, "enable-write")
    with turn(host):
        invalid = request(tasks=[{"title": "Valid"}, {"title": "Invalid", "due_date": "tomorrow"}])
        assert call(host, invalid, write=True)["error"]["code"] == "invalid_request"
    assert not database(host.home).exists()
    raw = 'plan --project Demo --tasks-json \'[{"title":"A","title":"B"}]\' --request-id p'
    assert command(host, raw)["error"]["code"] == "invalid_request"
    assert not database(host.home).exists()


def test_model_replay_survives_plugin_reload_without_duplicating_tasks(host):
    activate(host, "enable-write")
    with turn(host):
        first = call(host, request(), write=True)
    host.manager.discover_and_load(force=True)
    with turn(host):
        assert call(host, request(), write=True)["error"]["code"] == "session_tools_not_activated"
    activate(host, "enable-write")
    with turn(host):
        replay = call(host, request(), write=True)
        assert replay["replayed"] and replay["data"] == first["data"]
        assert len(call(host)["data"]["items"]) == 2
