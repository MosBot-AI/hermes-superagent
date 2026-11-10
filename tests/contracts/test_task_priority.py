"""Priority through actual native command and activated tool consumers; no models."""

import json
import shlex

from test_local_conversation_tasks import command
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host
from test_task_focus import collect


def test_native_priority_next_dependency_and_restart(host):
    tasks = [
        {"title": "First low", "priority": "low"},
        {"title": "Blocked high", "priority": "high", "depends_on": [1]},
        {"title": "Normal", "priority": "normal"},
    ]
    result = command(
        host, "plan --project Demo --request-id plan --tasks-json " + shlex.quote(json.dumps(tasks))
    )
    assert result["status"] == "ok", result
    first, second, third = result["data"]["items"]
    assert [x["id"] for x in command(host, "next")["data"]["items"]] == [third["id"], first["id"]]
    done = command(
        host, f"done {first['id']} --expected-revision 1 --request-id done --note explicit"
    )
    assert done["status"] == "ok", done
    assert command(host, "next")["data"]["items"][0]["id"] == second["id"]
    change = f"update {third['id']} --priority low --expected-revision 1 --request-id reprioritize"
    updated = command(host, change)
    assert updated["status"] == "ok", updated
    host.manager.discover_and_load(force=True)
    assert command(host, change)["replayed"] is True
    assert command(host, "show " + third["id"])["data"]["priority"] == "low"
    assert command(host, "next --after ignored")["status"] == "error"


def test_native_priority_tool_admission_focus_and_disable(host):
    task = command(host, "add Task --priority high --request-id capture")["data"]
    with turn(host):
        assert call(host, {"action": "next"})["status"] == "error"
    activate(host, "enable-read")
    activate(host, "focus " + task["id"])
    update = {
        "action": "update",
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "reprioritize",
        "priority": "low",
    }
    with turn(host):
        assert call(host, {"action": "next"})["data"]["items"][0]["priority"] == "high"
        assert '"priority": "high"' in collect(host)
        assert call(host, update, write=True)["status"] == "error"
    activate(host, "enable-write")
    with turn(host):
        assert call(host, update, write=True)["data"]["priority"] == "low"
    activate(host, "disable")
    with turn(host):
        assert call(host, {"action": "next"})["status"] == "error"
        assert (
            call(host, {**update, "expected_revision": 2, "request_id": "denied"}, write=True)[
                "status"
            ]
            == "error"
        )
    assert command(host, "show " + task["id"])["data"]["revision"] == 2
