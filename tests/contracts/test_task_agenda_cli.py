"""Date-only agenda through the real pinned host's registered local CLI.

Synthetic profiles only. No model, scheduler, remote transport or reminder is
involved; the existing local-operator and POSIX storage boundaries still apply.
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from test_local_task_cli import (
    PLUGIN_ID,
    assert_error,
    configure,
    entry,
    install,
    task,
)
from test_local_task_cli import (
    native as native,
)


def ok(command, capsys, *argv):
    code, result = task(command, capsys, *argv)
    assert code == 0, result
    assert result["schema_version"] == "personal.local-tasks.v1"
    assert result["status"] == "ok"
    assert result["scope"] == "trusted_local_cli_only"
    assert result["error"] is None
    return result


def capture_due(command, capsys, key, due=None):
    argv = ["capture", "--title", "Synthetic agenda task", "--request-id", key]
    if due is not None:
        argv += ["--due-date", due]
    return ok(command, capsys, *argv)


def agenda(command, capsys, *argv):
    return ok(command, capsys, "agenda", "--on", "2028-02-29", *argv)["data"]


def test_date_only_lifecycle_order_pagination_and_reload(native, capsys):
    from hermes_cli.plugins import PluginManager

    home, manager = native
    command = entry(manager)
    late = capture_due(command, capsys, "late", "2028-02-29")["data"]
    early = capture_due(command, capsys, "early", "2028-02-28")["data"]
    tied = capture_due(command, capsys, "tied", "2028-02-28")["data"]
    undated = capture_due(command, capsys, "undated")["data"]
    future = capture_due(command, capsys, "future", "2028-03-01")["data"]
    assert undated["due_date"] is None
    first = agenda(command, capsys, "--limit", "2")
    assert first == {
        "on": "2028-02-29",
        "items": [early, tied],
        "next_cursor": tied["id"],
        "has_more": True,
    }
    assert agenda(command, capsys, "--limit", "2", "--after", tied["id"]) == {
        "on": "2028-02-29",
        "items": [late],
        "next_cursor": None,
        "has_more": False,
    }
    edited = ok(
        command,
        capsys,
        "update",
        future["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "reschedule",
        "--due-date",
        "2028-02-27",
    )["data"]
    assert edited["due_date"] == "2028-02-27" and edited["revision"] == 2
    assert edited["title"] == future["title"] and edited["details"] == future["details"]
    cleared = ok(
        command,
        capsys,
        "update",
        early["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "clear",
        "--clear-due",
    )["data"]
    assert cleared["due_date"] is None and cleared["revision"] == 2
    for action, record in [("complete", late), ("cancel", tied)]:
        terminal = ok(
            command,
            capsys,
            action,
            record["id"],
            "--expected-revision",
            "1",
            "--request-id",
            action,
            "--note",
            "Synthetic explicit resolution",
        )["data"]
        assert terminal["due_date"] == record["due_date"]
    assert agenda(command, capsys)["items"] == [edited]
    manager.unload()
    restarted = PluginManager()
    try:
        command = entry(restarted)
        assert agenda(command, capsys)["items"] == [edited]
        assert ok(command, capsys, "show", early["id"])["data"] == cleared
        all_tasks = ok(command, capsys, "list", "--state", "all")["data"]["items"]
        assert len(all_tasks) == 5 and all("due_date" in row for row in all_tasks)
        with sqlite3.connect(home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3") as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        restarted.unload()


@pytest.mark.parametrize("mode", ["default", "read_only"])
def test_agenda_disabled_without_storage(native, capsys, mode):
    home, manager = native
    configure(home, mode)
    assert_error(
        task(entry(manager), capsys, "agenda", "--on", "2028-02-29"), "local_tasks_disabled"
    )
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "date",
    [
        "2027-02-29",
        "1900-02-29",
        "2028-04-31",
        "0000-01-01",
        "2028-00-01",
        "2028-01-00",
        "2028-13-01",
        "2028-2-29",
        "20280229",
        "2028-W09-2",
        "tomorrow",
        "2028-02-29T00:00:00Z",
        "2028-02-29 UTC",
        " 2028-02-29",
        "",
    ],
)
@pytest.mark.parametrize("operation", ["capture", "update", "agenda"])
def test_exact_gregorian_dates_rejected_before_storage(native, capsys, date, operation):
    home, manager = native
    if operation == "capture":
        argv = [
            operation,
            "--title",
            "Synthetic private title",
            "--request-id",
            "bad",
            "--due-date",
            date,
        ]
    elif operation == "update":
        argv = [
            operation,
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "bad",
            "--due-date",
            date,
        ]
    else:
        argv = [operation, "--on", date]
    assert_error(task(entry(manager), capsys, *argv), "invalid_request", home)
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("extra", [["--limit", "0"], ["--limit", "101"], ["--after", "not-a-uuid"]])
def test_invalid_agenda_bounds_and_cursor_before_storage(native, capsys, extra):
    home, manager = native
    assert_error(
        task(entry(manager), capsys, "agenda", "--on", "2028-02-29", *extra), "invalid_request"
    )
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["agenda"],
        [
            "update",
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "conflict",
            "--due-date",
            "2028-02-29",
            "--clear-due",
        ],
    ],
)
def test_required_date_and_mutually_exclusive_flags(native, capsys, argv):
    home, manager = native
    command = entry(manager)
    parser = argparse.ArgumentParser()
    command["setup_fn"](parser)
    with pytest.raises(SystemExit) as error:
        parser.parse_args(["tasks", *argv])
    assert error.value.code == 2
    capsys.readouterr()
    assert not (home / "plugin-data").exists()


def test_due_date_retries_do_not_duplicate_mutations(native, capsys):
    _home, manager = native
    command = entry(manager)
    first = capture_due(command, capsys, "same", "2000-02-29")
    replay = capture_due(command, capsys, "same", "2000-02-29")
    assert replay["replayed"] is True and replay["data"] == first["data"]
    assert_error(
        task(
            command,
            capsys,
            "capture",
            "--title",
            "Synthetic agenda task",
            "--request-id",
            "same",
            "--due-date",
            "2000-03-01",
        ),
        "idempotency_conflict",
    )
    update = [
        "update",
        first["data"]["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "same-update",
        "--due-date",
        "2028-02-29",
    ]
    edited = ok(command, capsys, *update)
    replay = ok(command, capsys, *update)
    assert replay["replayed"] is True and replay["data"] == edited["data"]
    clear = [
        "update",
        first["data"]["id"],
        "--expected-revision",
        "2",
        "--request-id",
        "same-clear",
        "--clear-due",
    ]
    cleared = ok(command, capsys, *clear)
    assert ok(command, capsys, *clear)["data"] == cleared["data"]
    assert ok(command, capsys, *clear)["replayed"] is True
    assert agenda(command, capsys)["items"] == []
    assert len(ok(command, capsys, "list")["data"]["items"]) == 1


def test_agenda_profile_isolation_and_live_mode_gate(native, tmp_path, capsys):
    from hermes_cli.plugins import PluginManager
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home, manager = native
    command = entry(manager)
    original = capture_due(command, capsys, "shared-key", "2028-02-29")["data"]
    other = tmp_path / "agenda-other-profile"
    install(other)
    configure(other)
    token = set_hermes_home_override(other)
    second = PluginManager()
    try:
        assert_error(
            task(command, capsys, "agenda", "--on", "2028-02-29"), "profile_context_changed"
        )
        assert not (other / "plugin-data").exists()
        other_command = entry(second)
        assert agenda(other_command, capsys)["items"] == []
        record = capture_due(other_command, capsys, "shared-key", "2028-02-29")["data"]
        assert record["id"] != original["id"]
        assert agenda(other_command, capsys)["items"] == [record]
        assert_error(
            task(other_command, capsys, "agenda", "--on", "2028-02-29", "--after", original["id"]),
            "invalid_cursor",
        )
    finally:
        second.unload()
        reset_hermes_home_override(token)
    assert agenda(command, capsys)["items"] == [original]
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = path.read_bytes()
    configure(home, "read_only")
    assert_error(task(command, capsys, "agenda", "--on", "2028-02-29"), "local_tasks_disabled")
    assert path.read_bytes() == before


def test_top_level_agenda_round_trip_without_network(native, tmp_path):
    from hermes_cli import main

    home, _manager = native
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_PYTHON": sys.executable,
        "HERMES_BUNDLED_PLUGINS": os.environ["HERMES_BUNDLED_PLUGINS"],
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
    }
    bootstrap = """
import socket, sys
def refuse(*args, **kwargs):
    raise AssertionError('Agenda CLI must not connect to the network')
socket.create_connection = refuse
socket.socket.connect = refuse
socket.socket.connect_ex = refuse
sys.argv = ['hermes', *sys.argv[1:]]
from hermes_cli.main import main
main()
"""

    def invoke(*argv):
        result = subprocess.run(
            [sys.executable, "-c", bootstrap, "personal-agent", "tasks", *argv],
            cwd=Path(main.__file__).resolve().parents[1],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok" and payload["error"] is None
        return payload["data"]

    record = invoke(
        "capture",
        "--title",
        "Synthetic subprocess task",
        "--request-id",
        "a",
        "--due-date",
        "2028-02-29",
    )
    assert invoke("agenda", "--on", "2028-02-29")["items"] == [record]
    edited = invoke(
        "update",
        record["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "b",
        "--due-date",
        "2028-03-01",
    )
    assert edited["revision"] == 2
    assert invoke("agenda", "--on", "2028-02-29")["items"] == []
    assert invoke("agenda", "--on", "2028-03-01")["items"] == [edited]
    cleared = invoke(
        "update", record["id"], "--expected-revision", "2", "--request-id", "c", "--clear-due"
    )
    assert cleared["due_date"] is None
    assert invoke("show", record["id"]) == cleared
    assert invoke("agenda", "--on", "2028-03-01")["items"] == []
