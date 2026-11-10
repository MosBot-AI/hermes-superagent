"""Real native command/tool follow-up lifecycle without model or scheduler calls."""

from test_local_conversation_tasks import command
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host
from test_task_focus import collect


def test_native_followup_due_postpone_replay_restart_and_clear(host):
    task = command(host, "add Waiting --due-date 2026-12-01 --request-id capture")["data"]
    rid = task["id"]
    waiting = command(
        host,
        f"progress {rid} --expected-revision 1 --work-status waiting "
        "--note explicit --follow-up-on 2026-11-20 --request-id wait",
    )
    assert waiting["status"] == "ok", waiting
    assert command(host, "followups --on 2026-11-19")["data"]["items"] == []
    assert command(host, "followups --on 2026-11-20")["data"]["items"][0]["id"] == rid
    change = f"update {rid} --expected-revision 2 --follow-up-on 2026-11-22 --request-id later"
    updated = command(host, change)
    assert updated["status"] == "ok", updated
    assert updated["data"]["due_date"] == "2026-12-01"
    stale = command(
        host, f"update {rid} --expected-revision 2 --clear-follow-up-on --request-id stale"
    )
    assert stale["status"] == "error"
    host.manager.discover_and_load(force=True)
    assert command(host, change)["replayed"] is True
    assert command(host, "followups --on 2026-11-20")["data"]["items"] == []
    assert command(host, "show " + rid)["data"]["follow_up_on"] == "2026-11-22"
    done = command(host, f"done {rid} --expected-revision 3 --note explicit --request-id done")
    assert done["status"] == "ok" and done["data"]["follow_up_on"] is None
    assert command(host, "followups --on 2026-12-01")["data"]["items"] == []


def test_native_followup_read_write_activation_focus_and_disable(host):
    task = command(host, "add Task --request-id capture")["data"]
    read = {"action": "followups", "on": "2026-11-20"}
    change = {
        "action": "progress",
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "waiting",
        "work_status": "blocked",
        "note": "Explicit",
        "follow_up_on": "2026-11-20",
    }
    with turn(host):
        assert call(host, read)["status"] == "error"
    activate(host, "enable-read")
    with turn(host):
        assert call(host, read)["data"]["items"] == []
        assert call(host, change, write=True)["status"] == "error"
    activate(host, "enable-write")
    with turn(host):
        assert call(host, change, write=True)["data"]["follow_up_on"] == "2026-11-20"
    activate(host, "focus " + task["id"])
    with turn(host):
        assert '"follow_up_on": "2026-11-20"' in collect(host)
        assert call(host, read)["data"]["total"] == 1
    activate(host, "disable")
    with turn(host):
        assert call(host, read)["status"] == "error"
    cleared = command(
        host,
        f"progress {task['id']} --expected-revision 2 --work-status ready "
        "--note explicit --request-id ready",
    )
    assert cleared["status"] == "ok" and cleared["data"]["follow_up_on"] is None
