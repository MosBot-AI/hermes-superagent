"""Pinned native CLI history, reload, pagination and fail-closed reads."""

from uuid import uuid4

import pytest
from test_local_task_cli import PLUGIN_ID, assert_error, configure, entry, task
from test_local_task_cli import native as native
from test_task_agenda_cli import ok


def test_history_reuses_durable_metadata_after_reload(native, capsys):
    from hermes_cli.plugins import PluginManager

    home, manager = native
    command = entry(manager)
    record = ok(command, capsys, "capture", "--title", "Private", "--request-id", "one")["data"]
    ok(command, capsys, "capture", "--title", "Private", "--request-id", "one")
    ok(
        command,
        capsys,
        "update",
        record["id"],
        "--title",
        "Private changed",
        "--expected-revision",
        "1",
        "--request-id",
        "two",
    )
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = path.read_bytes()
    page = ok(command, capsys, "history", record["id"], "--limit", "1")["data"]
    assert page["current_revision"] == 2 and page["current_state"] == "captured"
    assert page["next_cursor"] == 1 and page["has_more"]
    assert page["items"] == [
        {"revision": 1, "operation": "capture", "timestamp": record["created_at"]}
    ]
    manager.unload()
    restarted = PluginManager()
    try:
        second = ok(entry(restarted), capsys, "history", record["id"], "--after-revision", "1")[
            "data"
        ]
        assert second["items"][0]["operation"] == "update"
        assert second["next_cursor"] is None and not second["has_more"]
        assert "Private" not in str(second)
    finally:
        restarted.unload()
    assert path.read_bytes() == before


@pytest.mark.parametrize("mode", ["default", "read_only", "invalid"])
def test_history_mode_gate_never_opens_storage(native, capsys, mode):
    home, manager = native
    command = entry(manager)
    configure(home, mode)
    code = "invalid_configuration" if mode == "invalid" else "local_tasks_disabled"
    assert_error(task(command, capsys, "history", str(uuid4())), code)
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["--limit", "0"],
        ["--limit", "101"],
        ["--after-revision", "-1"],
        ["--after-revision", str(2**63)],
    ],
)
def test_history_invalid_bounds_before_storage(native, capsys, argv):
    home, manager = native
    assert_error(task(entry(manager), capsys, "history", str(uuid4()), *argv), "invalid_request")
    assert not (home / "plugin-data").exists()


def test_history_missing_task_and_cursor_errors_are_redacted(native, capsys):
    _, manager = native
    command = entry(manager)
    assert_error(task(command, capsys, "history", str(uuid4())), "not_found")
    record = ok(command, capsys, "capture", "--title", "Private", "--request-id", "a")["data"]
    assert_error(
        task(command, capsys, "history", record["id"], "--after-revision", "2"),
        "invalid_cursor",
        "Private",
    )
