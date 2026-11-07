"""Pinned native CLI review across reloads and fail-closed configurations."""

import pytest
from test_local_task_cli import PLUGIN_ID, assert_error, configure, entry, task
from test_local_task_cli import native as native
from test_task_agenda_cli import ok


def test_review_cli_is_bounded_and_unchanged_after_reload(native, capsys):
    from hermes_cli.plugins import PluginManager

    home, manager = native
    command = entry(manager)
    for index in range(3):
        ok(
            command,
            capsys,
            "capture",
            "--title",
            f"Review task {index}",
            "--due-date",
            "2026-11-07",
            "--project",
            "Demo",
            "--details",
            "Not in review",
            "--request-id",
            f"task-{index}",
        )
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = path.read_bytes()
    args = ("review", "--on", "2026-11-07", "--per-bucket-limit", "1", "--project", "Demo")
    result = ok(command, capsys, *args)["data"]
    assert result["counts"]["due_today"] == 3
    assert result["buckets"]["due_today"]["omitted"] == 2
    assert len(result["buckets"]["due_today"]["items"]) == 1
    assert "Not in review" not in str(result)
    manager.unload()
    restarted = PluginManager()
    try:
        assert ok(entry(restarted), capsys, *args)["data"] == result
    finally:
        restarted.unload()
    assert path.read_bytes() == before


@pytest.mark.parametrize("mode", ["default", "read_only", "invalid"])
def test_review_mode_gate_never_opens_storage(native, capsys, mode):
    home, manager = native
    command = entry(manager)
    configure(home, mode)
    code = "invalid_configuration" if mode == "invalid" else "local_tasks_disabled"
    assert_error(task(command, capsys, "review", "--on", "2026-11-07"), code)
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["--lookahead-days", "-1"],
        ["--lookahead-days", "91"],
        ["--per-bucket-limit", "0"],
        ["--per-bucket-limit", "21"],
        ["--max-chars", "2047"],
        ["--max-chars", "64001"],
    ],
)
def test_invalid_review_bounds_before_storage(native, capsys, argv):
    home, manager = native
    assert_error(
        task(entry(manager), capsys, "review", "--on", "2026-11-07", *argv), "invalid_request"
    )
    assert not (home / "plugin-data").exists()
