"""Pinned native task progress, reload, exact retries and configuration refusal."""

from uuid import uuid4

import pytest
from test_local_task_cli import PLUGIN_ID, assert_error, configure, entry, task
from test_local_task_cli import native as native
from test_task_agenda_cli import ok


def test_cli_progress_persists_replays_and_filters_after_reload(native, capsys):
    from hermes_cli.plugins import PluginManager

    home, manager = native
    command = entry(manager)
    record = ok(
        command,
        capsys,
        "capture",
        "--title",
        "Synthetic progress",
        "--project",
        "Demo",
        "--due-date",
        "2026-11-07",
        "--request-id",
        "capture",
    )["data"]
    args = (
        "progress",
        record["id"],
        "--expected-revision",
        "1",
        "--work-status",
        "blocked",
        "--note",
        "Waiting for a synthetic review",
        "--request-id",
        "progress",
    )
    first = ok(command, capsys, *args)
    assert first["data"]["work_status"] == "blocked" and first["data"]["revision"] == 2
    assert first["data"]["state"] == "captured" and first["data"]["resolution_note"] is None
    assert ok(command, capsys, *args)["replayed"]
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = path.read_bytes()
    manager.unload()
    restarted = PluginManager()
    try:
        command = entry(restarted)
        replay = ok(command, capsys, *args)
        assert replay["replayed"] and replay["data"] == first["data"]
        assert ok(command, capsys, "list", "--work-status", "blocked", "--project", "Demo")["data"][
            "items"
        ] == [first["data"]]
        overview = ok(command, capsys, "review", "--on", "2026-11-07", "--work-status", "blocked")[
            "data"
        ]
        assert overview["progress_counts"]["blocked"] == 1
        assert "Waiting for" not in str(overview)
        assert (
            ok(command, capsys, "history", record["id"])["data"]["items"][-1]["operation"]
            == "progress"
        )
    finally:
        restarted.unload()
    assert path.read_bytes() == before


@pytest.mark.parametrize("mode", ["default", "read_only", "invalid"])
def test_progress_disabled_never_opens_storage(native, capsys, mode):
    home, manager = native
    command = entry(manager)
    configure(home, mode)
    code = "invalid_configuration" if mode == "invalid" else "local_tasks_disabled"
    assert_error(
        task(
            command,
            capsys,
            "progress",
            str(uuid4()),
            "--expected-revision",
            "1",
            "--work-status",
            "waiting",
            "--note",
            "Synthetic",
            "--request-id",
            "one",
        ),
        code,
    )
    assert not (home / "plugin-data").exists()


def test_progress_invalid_revision_note_and_conflicts_remain_redacted(native, capsys):
    home, manager = native
    command = entry(manager)
    base = ("progress", str(uuid4()), "--work-status", "blocked", "--request-id", "invalid")
    for extra in (
        ("--expected-revision", "0", "--note", "Synthetic"),
        ("--expected-revision", "1", "--note", " "),
    ):
        assert_error(task(command, capsys, *base, *extra), "invalid_request")
    assert not (home / "plugin-data").exists()
    record = ok(command, capsys, "capture", "--title", "Private", "--request-id", "capture")["data"]
    args = (
        "progress",
        record["id"],
        "--work-status",
        "waiting",
        "--note",
        "Private blocker",
        "--expected-revision",
        "2",
        "--request-id",
        "bad",
    )
    assert_error(task(command, capsys, *args), "revision_conflict", "Private")
