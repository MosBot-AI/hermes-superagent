"""Real native session admission and model dispatch for explicit local progress."""

from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host


def test_native_slash_and_model_progress_share_receipts_and_working_state(host):
    task = command(
        host, 'add "Synthetic task" --project Demo --due-date 2026-11-07 --request-id seed'
    )["data"]
    args = {
        "action": "progress",
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "working",
        "work_status": "in_progress",
        "note": "Started local review",
    }
    activate(host, "enable-read")
    with turn(host):
        assert call(host, args, write=True)["error"]["code"] == "session_write_not_activated"
    activate(host)
    with turn(host):
        started = call(host, args, write=True)
        assert started["status"] == "ok" and started["data"]["work_status"] == "in_progress"
        assert started["data"]["state"] == "captured" and started["data"]["revision"] == 2
        assert call(host, args, write=True)["replayed"]
        assert (
            call(host, {**args, "note": "Different"}, write=True)["error"]["code"]
            == "idempotency_conflict"
        )
    blocked = command(
        host,
        f"progress {task['id']} --expected-revision 2 --work-status blocked "
        '--note "Waiting for synthetic data" --request-id blocker',
    )
    assert blocked["status"] == "ok" and blocked["data"]["revision"] == 3
    before = database(host.home).read_bytes()
    activate(host, "enable-read")
    with turn(host):
        current = call(host, {"action": "show", "task_id": task["id"]})["data"]
        assert current["progress_note"] == "Waiting for synthetic data"
        overview = call(host, {"action": "review", "on": "2026-11-07", "work_status": "blocked"})[
            "data"
        ]
        assert overview["progress_counts"]["blocked"] == 1
        assert overview["buckets"]["due_today"]["items"][0]["work_status"] == "blocked"
        assert "Waiting for" not in str(overview)
        history = call(host, {"action": "history", "task_id": task["id"]})["data"]
        assert [item["operation"] for item in history["items"]] == [
            "capture",
            "progress",
            "progress",
        ]
    assert database(host.home).read_bytes() == before
    assert call(host, args, write=True)["error"]["code"] == "no_active_local_turn"
    activate(host, "disable")
    with turn(host):
        assert call(host, args, write=True)["error"]["code"] == "session_tools_not_activated"
    assert database(host.home).read_bytes() == before


def test_native_progress_validation_no_scope_expansion_or_terminal_revival(host):
    task = command(host, 'add "Synthetic" --request-id one')["data"]
    activate(host)
    args = {
        "action": "progress",
        "task_id": task["id"],
        "expected_revision": 1,
        "request_id": "progress",
        "work_status": "waiting",
        "note": "Synthetic",
    }
    before = database(host.home).read_bytes()
    with turn(host):
        for extra in (
            {"work_status": "done"},
            {"note": ""},
            {"title": "No edit"},
            {"approved": True},
        ):
            assert call(host, {**args, **extra}, write=True)["error"]["code"] == "invalid_request"
    with turn(host, sid="other-session"):
        assert (
            call(host, args, write=True, sid="other-session")["error"]["code"]
            == "session_tools_not_activated"
        )
    assert database(host.home).read_bytes() == before
    terminal = command(
        host, f'done {task["id"]} --expected-revision 1 --note "Done" --request-id done'
    )["data"]
    with turn(host):
        denied = call(host, {**args, "expected_revision": terminal["revision"]}, write=True)
        assert denied["error"]["code"] == "terminal_state"
    assert command(host, "list --work-status waiting")["data"]["items"] == []
