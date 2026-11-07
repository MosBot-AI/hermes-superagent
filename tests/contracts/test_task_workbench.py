"""Pinned native human output and explicitly retained structured task contracts."""

import argparse
import asyncio
import json
import re

from test_local_conversation_tasks import command, database
from test_local_conversation_tasks import native as native
from test_session_task_tools import activate, call, turn
from test_session_task_tools import host as host


def human(host, text):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-tasks " + text})
    )
    assert result["type"] == "exec"
    return result["output"]


def test_native_text_default_and_json_read_same_persisted_task(host):
    text = human(host, 'add "Native readable task" --project Demo --due-date 2026-11-07')
    assert text.startswith("Task saved.") and '"Native readable task" [ready]' in text
    task_id = re.search(r"  ID: ([a-f0-9-]{36})", text).group(1)
    key = re.search(r"Request ID: ([a-f0-9-]{36})", text).group(1)
    before = database(host.home).read_bytes()
    structured = command(host, f"show {task_id}")
    assert structured["schema_version"] == "personal.local-conversation-tasks.v1"
    assert structured["data"]["title"] == "Native readable task"
    replay = human(
        host, f'add "Native readable task" --project Demo --due-date 2026-11-07 --request-id {key}'
    )
    assert replay.startswith("Replayed saved receipt.")
    assert database(host.home).read_bytes() == before
    overview = human(host, "review --on 2026-11-07")
    assert "Due today: 1" in overview and "Active: 1" in overview
    assert task_id in overview and "not a priority or execution decision" in overview
    assert human(host, "help").startswith("Local task workbench")
    assert command(host, "help")["data"]["help"]


def test_text_mutations_preserve_progress_cas_and_read_tool_json(host):
    task = command(host, 'add "Synthetic" --request-id seed')["data"]
    progress = human(
        host,
        f"progress {task['id']} --expected-revision 1 --work-status blocked "
        '--note "Awaiting fixture" --request-id progress',
    )
    assert "Local progress recorded." in progress and "[blocked]" in progress
    assert 'Progress note: "Awaiting fixture"' in progress
    conflict = human(
        host, f'done {task["id"]} --expected-revision 1 --note "Done" --request-id stale'
    )
    assert "revision_conflict" in conflict and "reconcile" in conflict
    activate(host, "enable-read")
    with turn(host):
        current = call(host, {"action": "show", "task_id": task["id"]})
        assert current["schema_version"] == "personal.session-task-tools.v1"
        assert current["data"]["work_status"] == "blocked"
        assert current["data"]["revision"] == 2
    before = database(host.home).read_bytes()
    assert "invalid_request" in human(host, 'add "Private malformed')
    assert database(host.home).read_bytes() == before
    done = human(host, f'done {task["id"]} --expected-revision 2 --note "Done" --request-id done')
    assert "Task marked done in the local inbox." in done and "[done]" in done
    assert "Last recorded progress note" in done


def test_cli_stays_json_by_default_and_text_is_explicit(host, capsys):
    command_entry = host.manager._cli_commands["personal-agent"]
    parser = argparse.ArgumentParser()
    command_entry["setup_fn"](parser)
    capsys.readouterr()
    code = command_entry["handler_fn"](
        parser.parse_args(["tasks", "capture", "--title", "CLI task", "--request-id", "cli"])
    )
    structured = json.loads(capsys.readouterr().out)
    assert code == 0 and structured["schema_version"] == "personal.local-tasks.v1"
    code = command_entry["handler_fn"](
        parser.parse_args(["tasks", "show", structured["data"]["id"], "--format", "text"])
    )
    output = capsys.readouterr().out
    assert code == 0 and output.startswith("Task details") and '"CLI task"' in output
    code = command_entry["handler_fn"](
        parser.parse_args(["tasks", "list", "--limit", "0", "--format", "text"])
    )
    output = capsys.readouterr().out
    assert code == 1 and "invalid_request" in output


def test_retained_callback_admission_errors_are_readable_or_explicit_json(host):
    callback = host.manager._plugin_commands["personal-tasks"]["handler"]
    args = dict(
        platform="telegram",
        source=host.source,
        session_id=host.ref.session_id,
        session_key=host.live.route,
    )
    text = callback('add "Never read this"', **args)
    assert text.startswith("Task request failed: unsupported_origin") and "Never read" not in text
    payload = json.loads(callback('--json add "Never read this"', **args))
    assert payload["error"]["code"] == "unsupported_origin"
    assert not database(host.home).exists()
