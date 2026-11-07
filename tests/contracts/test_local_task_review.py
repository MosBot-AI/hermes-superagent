"""Native command and activated model-read dispatch for the same daily overview."""

import json

from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host


def test_review_native_command_and_read_tool_agree(host):
    record = command(
        host,
        'add "Synthetic overdue" --due-date 2026-11-06 '
        '--project "Demo" --details "Private detail" --request-id one',
    )["data"]
    args = {"action": "review", "on": "2026-11-07", "project": "Demo", "max_chars": 2048}
    before = database(host.home).read_bytes()
    slash = command(host, "review --on 2026-11-07 --project Demo --max-chars 2048")
    assert slash["status"] == "ok" and slash["request_id"] is None
    assert slash["data"]["counts"]["overdue"] == 1
    assert slash["data"]["buckets"]["overdue"]["items"][0]["id"] == record["id"]
    assert "Private detail" not in json.dumps(slash)
    assert len(json.dumps(slash["data"], ensure_ascii=True, sort_keys=True)) <= 2048
    with turn(host):
        assert call(host, args)["error"]["code"] == "session_tools_not_activated"
    activate(host, "enable-read")
    with turn(host):
        result = call(host, args)
        assert result["status"] == "ok" and result["data"] == slash["data"]
        assert call(host, {**args, "max_chars": True})["error"]["code"] == "invalid_request"
        assert call(host, {**args, "state": "all"})["error"]["code"] == "invalid_request"
        assert call(host, args, write=True)["error"]["code"] == "session_write_not_activated"
    assert call(host, args)["error"]["code"] == "no_active_local_turn"
    with turn(host, sid="another-session"):
        assert (
            call(host, args, sid="another-session")["error"]["code"]
            == "session_tools_not_activated"
        )
    activate(host, "disable")
    with turn(host):
        assert call(host, args)["error"]["code"] == "session_tools_not_activated"
    assert database(host.home).read_bytes() == before


def test_review_wrong_origin_and_invalid_arguments_never_open_storage(host):
    activate(host, "enable-read")
    for platform in ("telegram", "subagent"):
        with turn(host, platform=platform):
            assert call(host, {"action": "review", "on": "2026-11-07"})["error"]["code"] == (
                "no_active_local_turn"
            )
    for raw in (
        "review",
        "review --on tomorrow",
        "review --on 2026-11-07 --limit 5",
        "review --on 2026-11-07 --project Demo --unassigned",
    ):
        assert command(host, raw)["error"]["code"] == "invalid_request"
    assert not database(host.home).exists()
