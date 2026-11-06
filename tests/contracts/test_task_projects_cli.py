"""Project labels through the real pinned host CLI, with synthetic local profiles."""

import argparse

import pytest
from test_local_task_cli import assert_error, configure, entry, task
from test_local_task_cli import native as native
from test_task_agenda_cli import ok


def capture(command, capsys, key, label=None):
    args = [
        "capture",
        "--title",
        "Synthetic project task",
        "--request-id",
        key,
        "--due-date",
        "2028-02-29",
    ]
    if label is not None:
        args += ["--project", label]
    return ok(command, capsys, *args)["data"]


def test_projects_lifecycle_filters_replay_and_reload(native, capsys):
    from hermes_cli.plugins import PluginManager

    _home, manager = native
    command = entry(manager)
    first = capture(command, capsys, "a", "Alpha")
    other = capture(command, capsys, "b", "alpha")
    unassigned = capture(command, capsys, "c")
    assert capture(command, capsys, "a", "Alpha") == first
    for operation, extra in [
        ("list", []),
        ("search", ["--query", "Synthetic"]),
        ("agenda", ["--on", "2028-02-29"]),
    ]:
        assert ok(command, capsys, operation, *extra, "--project", "Alpha")["data"]["items"] == [
            first
        ]
        assert ok(command, capsys, operation, *extra, "--unassigned")["data"]["items"] == [
            unassigned
        ]
    page = ok(command, capsys, "projects", "--limit", "1")["data"]
    assert page["items"] == [dict(project="Alpha", captured=1, done=0, cancelled=0, total=1)]
    assert page["next_cursor"] == "Alpha" and page["has_more"]
    clear = [
        "update",
        first["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "clear",
        "--clear-project",
    ]
    cleared = ok(command, capsys, *clear)["data"]
    assert cleared["project"] is None and cleared["revision"] == 2
    assert ok(command, capsys, *clear)["replayed"]
    assert (
        ok(command, capsys, "projects", "--after", "Alpha")["data"]["items"][0]["project"]
        == "alpha"
    )
    ok(
        command,
        capsys,
        "complete",
        other["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "done",
        "--note",
        "Synthetic completion",
    )
    manager.unload()
    restarted = PluginManager()
    try:
        command = entry(restarted)
        result = ok(command, capsys, "projects")["data"]
        assert result["items"] == [dict(project="alpha", captured=0, done=1, cancelled=0, total=1)]
        assert result["unassigned_counts"] == dict(captured=2, done=0, cancelled=0, total=2)
        assert ok(command, capsys, "show", first["id"])["data"] == cleared
        assert_error(
            task(
                command,
                capsys,
                "update",
                other["id"],
                "--expected-revision",
                "2",
                "--request-id",
                "terminal",
                "--project",
                "New",
            ),
            "terminal_state",
        )
    finally:
        restarted.unload()


@pytest.mark.parametrize("mode", ["default", "read_only"])
def test_projects_disabled_without_storage(native, capsys, mode):
    home, manager = native
    configure(home, mode)
    assert_error(task(entry(manager), capsys, "projects"), "local_tasks_disabled")
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("label", ["", " bad", "bad ", "bad\nlabel", "x" * 81])
@pytest.mark.parametrize("operation", ["capture", "update", "list", "search", "agenda", "projects"])
def test_invalid_project_before_storage(native, capsys, label, operation):
    home, manager = native
    args = {
        "capture": ["--title", "Synthetic", "--request-id", "bad"],
        "update": [
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "bad",
        ],
        "list": [],
        "search": ["--query", "Synthetic"],
        "agenda": ["--on", "2028-02-29"],
        "projects": [],
    }[operation]
    flag = "--after" if operation == "projects" else "--project"
    assert_error(
        task(entry(manager), capsys, operation, *args, flag, label), "invalid_request", home
    )
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["list", "--project", "A", "--unassigned"],
        ["search", "--query", "Synthetic", "--project", "A", "--unassigned"],
        ["agenda", "--on", "2028-02-29", "--project", "A", "--unassigned"],
        [
            "update",
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "bad",
            "--project",
            "A",
            "--clear-project",
        ],
    ],
)
def test_project_flags_mutually_exclusive(native, capsys, args):
    home, manager = native
    parser = argparse.ArgumentParser()
    entry(manager)["setup_fn"](parser)
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["tasks", *args])
    assert caught.value.code == 2
    capsys.readouterr()
    assert not (home / "plugin-data").exists()


def test_projects_live_profile_gate(native, capsys):
    home, manager = native
    command = entry(manager)
    capture(command, capsys, "a", "Synthetic")
    path = home / "plugin-data" / "hermes-personal-agent" / "tasks.sqlite3"
    before = path.read_bytes()
    configure(home, "read_only")
    assert_error(task(command, capsys, "projects"), "local_tasks_disabled")
    assert path.read_bytes() == before
