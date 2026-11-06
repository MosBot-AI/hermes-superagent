"""Literal search via the real pinned host, including its native CLI entry point."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from test_local_task_cli import PLUGIN_ID, assert_error, configure, entry, install, task
from test_local_task_cli import native as native
from test_task_agenda_cli import ok


def search(command, capsys, query="中文", *argv):
    return ok(command, capsys, "search", "--query", query, *argv)["data"]


def test_search_literal_pages_state_and_reload(native, capsys):
    from hermes_cli.plugins import PluginManager

    home, manager = native
    command = entry(manager)
    records = []
    for index in range(3):
        records.append(
            ok(
                command,
                capsys,
                "capture",
                "--title",
                "中文 Case %_",
                "--details",
                "details needle ' OR 1=1 --",
                "--request-id",
                str(index),
                "--due-date",
                "2028-02-29",
            )["data"]
        )
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = path.read_bytes()
    first = search(command, capsys, "中文", "--limit", "2")
    assert first == {"items": records[:0:-1], "next_cursor": records[1]["id"], "has_more": True}
    assert search(command, capsys, "中文", "--after", first["next_cursor"])["items"] == records[:1]
    for query in ("%_", "Case", "needle", "' OR 1=1 --"):
        assert search(command, capsys, query)["items"] == records[::-1]
    for query in ("case", "c_se", "missing"):
        assert search(command, capsys, query) == {
            "items": [],
            "next_cursor": None,
            "has_more": False,
        }
    assert path.read_bytes() == before
    done = ok(
        command,
        capsys,
        "complete",
        records[1]["id"],
        "--expected-revision",
        "1",
        "--request-id",
        "done",
        "--note",
        "Synthetic resolution",
    )["data"]
    assert done["due_date"] == "2028-02-29"
    assert search(command, capsys)["items"] == [records[2], records[0]]
    assert search(command, capsys, "中文", "--state", "done")["items"] == [done]
    assert search(command, capsys, "中文", "--state", "all")["items"] == [
        records[2],
        done,
        records[0],
    ]
    assert search(command, capsys, "中文", "--after", done["id"])["items"] == records[:1]
    manager.unload()
    restarted = PluginManager()
    try:
        assert search(entry(restarted), capsys)["items"] == [records[2], records[0]]
    finally:
        restarted.unload()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 4


@pytest.mark.parametrize("mode", ["default", "read_only", "invalid"])
def test_mode_gate_before_storage(native, capsys, mode):
    home, manager = native
    command = entry(manager)
    configure(home, mode)
    code = "invalid_configuration" if mode == "invalid" else "local_tasks_disabled"
    assert_error(task(command, capsys, "search", "--query", "private query"), code, "private query")
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "query", ["", " ", "x" * 241, "private\n", "private\t", "private\x00", "private\u202e"]
)
def test_invalid_query_before_storage(native, capsys, query):
    home, manager = native
    assert_error(
        task(entry(manager), capsys, "search", "--query", query), "invalid_request", "private"
    )
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("argv", [["--limit", "0"], ["--limit", "101"], ["--after", "invalid"]])
def test_invalid_bounds_before_storage(native, capsys, argv):
    home, manager = native
    assert_error(task(entry(manager), capsys, "search", "--query", "x", *argv), "invalid_request")
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "argv", [[], ["--query", "x", "--state", "unknown"], ["--query", "x", "--limit", "1.5"]]
)
def test_parser_rejects_missing_query_or_invalid_options(native, capsys, argv):
    home, manager = native
    parser = argparse.ArgumentParser()
    entry(manager)["setup_fn"](parser)
    with pytest.raises(SystemExit) as caught:
        parser.parse_args(["tasks", "search", *argv])
    assert caught.value.code == 2
    capsys.readouterr()
    assert not (home / "plugin-data").exists()


def test_profile_change_isolation_and_foreign_cursor(native, tmp_path, capsys):
    from hermes_cli.plugins import PluginManager
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home, manager = native
    command = entry(manager)
    original = ok(command, capsys, "capture", "--title", "中文", "--request-id", "one")["data"]
    other = tmp_path / "other-search-profile"
    install(other)
    configure(other)
    token = set_hermes_home_override(other)
    second = PluginManager()
    try:
        assert_error(task(command, capsys, "search", "--query", "中文"), "profile_context_changed")
        assert not (other / "plugin-data").exists()
        other_command = entry(second)
        assert search(other_command, capsys)["items"] == []
        for cursor in (original["id"], str(uuid4())):
            assert_error(
                task(other_command, capsys, "search", "--query", "中文", "--after", cursor),
                "invalid_cursor",
            )
    finally:
        second.unload()
        reset_hermes_home_override(token)
    assert search(command, capsys)["items"] == [original]
    before = (home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3").read_bytes()
    configure(home, "read_only")
    assert_error(task(command, capsys, "search", "--query", "中文"), "local_tasks_disabled")
    assert (home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3").read_bytes() == before


def test_top_level_search_without_network(native, tmp_path):
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
    raise AssertionError('Search CLI must not connect to the network')
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
        assert payload["scope"] == "trusted_local_cli_only"
        return payload["data"]

    record = invoke(
        "capture",
        "--title",
        "中文 Case %_",
        "--details",
        "literal needle",
        "--request-id",
        "subprocess",
    )
    for query in ("中文", "Case", "%_", "needle"):
        assert invoke("search", "--query", query)["items"] == [record]
    assert invoke("search", "--query", "case")["items"] == []
    assert invoke("search", "--query", "中文", "--after", record["id"])["items"] == []


def test_missing_profile_refused_before_config_recreates_it(native, capsys):
    home, manager = native
    command = entry(manager)
    home.rename(home.with_name("moved-profile"))
    assert_error(
        task(command, capsys, "search", "--query", "private query"),
        "profile_context_changed",
        home,
        "private query",
    )
    assert not home.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only local storage contract")
def test_search_refuses_broad_database_permissions_without_repair(native, capsys):
    home, manager = native
    command = entry(manager)
    assert search(command, capsys)["items"] == []
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = path.read_bytes()
    path.chmod(0o644)
    assert_error(
        task(command, capsys, "search", "--query", "private query"),
        "unsafe_storage_file",
        home,
        "private query",
    )
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o644
