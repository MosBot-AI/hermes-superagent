"""Real native project consumers, disposable profiles, no model or worker execution.

These contracts observe private host APIs, not an exported plugin CRUD surface.
Archive/restore flags and path deduplication are not durable operation receipts.
"""

import argparse
import inspect
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import hermes_cli
import pytest
from hermes_cli import projects_cmd, projects_db
from tools import project_tools


def command(*arguments):
    parser = argparse.ArgumentParser()
    projects_cmd.build_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(["project", *arguments])
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = projects_cmd.projects_command(args)
    return status, stdout.getvalue(), stderr.getvalue()


@pytest.fixture
def home(tmp_path, monkeypatch):
    profile = tmp_path / "profile-a"
    profile.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(profile))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    for name in ("HERMES_KANBAN_DB", "HERMES_KANBAN_TASK", "HERMES_DELEGATED_CHILD_CONTEXT"):
        monkeypatch.delenv(name, raising=False)
    return profile


def projects():
    with projects_db.connect_closing() as conn:
        return projects_db.list_projects(conn, include_archived=True)


def test_cli_create_list_show_archive_restore(home, tmp_path):
    folder = tmp_path / "synthetic-repo"
    folder.mkdir()
    assert command("create", "Synthetic 中文", str(folder), "--slug", "synthetic", "--use")[0] == 0
    original = projects()[0]
    assert original.name == "Synthetic 中文"
    assert original.primary_path == str(folder)
    assert command("list")[0] == 0
    assert "Synthetic 中文" in command("list")[1]
    assert original.id in command("show", "synthetic")[1]
    assert command("archive", original.id) == (0, "Archived synthetic\n", "")
    assert "No projects yet" in command("list")[1]
    assert "(archived)" in command("list", "--all")[1]
    assert "(archived)" in command("show", original.id)[1]
    assert command("restore", "synthetic") == (0, "Restored synthetic\n", "")
    assert projects()[0] == original


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_empty_names_rejected_by_real_consumers(home, name):
    status, output, error = command("create", name)
    assert status == 2 and not output and "name must not be empty" in error
    assert json.loads(project_tools.project_create(name)) == {
        "success": False,
        "error": "name is required",
    }
    assert projects() == []


def test_invalid_slug_and_unknown_project_return_errors(home):
    assert command("create", "Synthetic", "--slug", "../escape")[0] == 2
    assert projects() == []
    for action in ("show", "archive", "restore"):
        status, output, error = command(action, "missing")
        assert status == 1 and not output and "no such project" in error


def test_cli_rejects_duplicate_primary_but_tool_reuses_existing(home, tmp_path):
    folder = tmp_path / "repo"
    folder.mkdir()
    assert command("create", "Original", str(folder))[0] == 0
    original = projects()[0]
    status, output, error = command("create", "Duplicate", "--primary", str(folder / "."))
    assert status == 2 and not output and "already belongs" in error
    reused = json.loads(project_tools.project_create("Different name", str(folder)))
    assert reused["success"] is True
    assert reused["id"] == original.id and reused["name"] == "Original"
    assert projects() == [original]


def test_pathless_retry_creates_distinct_ids_without_operation_key(home):
    first = json.loads(project_tools.project_create("Repeated"))
    second = json.loads(project_tools.project_create("Repeated"))
    assert first["success"] and second["success"]
    assert first["id"] != second["id"] and first["slug"] != second["slug"]
    assert len(projects()) == 2
    for consumer in (projects_db.create_project, project_tools.project_create):
        parameters = inspect.signature(consumer).parameters
        assert "idempotency_key" not in parameters
        assert "operation_id" not in parameters
    with projects_db.connect_closing() as conn:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert tables == {"projects", "project_folders", "project_meta", "discovered_repos"}
        assert {row[0] for row in conn.execute("SELECT key FROM project_meta")} == {"active_id"}


def _child_main():
    import socket

    def deny(*_args, **_kwargs):
        raise AssertionError("Project restart contracts must not connect to the network")

    socket.create_connection = deny
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    print(json.dumps([command(*args) for args in json.load(sys.stdin)]))


def restart(home, commands):
    host = Path(hermes_cli.__file__).resolve().parents[1]
    environment = {
        "PATH": os.defpath,
        "HOME": str(home.parent / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(home.parent / "runtime"),
        "HERMES_KANBAN_HOME": str(home),
        "HERMES_BUNDLED_PLUGINS": str(home.parent / "empty-bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(host), str(Path(__file__).parent))),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    # Install the child network guard before importing any native consumer.
    script = (
        "import socket; "
        "deny=lambda *a, **k: (_ for _ in ()).throw(AssertionError('Network forbidden')); "
        "socket.create_connection=deny; socket.socket.connect=deny; socket.socket.connect_ex=deny; "
        "from test_native_project_lifecycle import _child_main; _child_main()"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(commands),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        cwd=home,
        env=environment,
    )
    return json.loads(result.stdout)


def test_restart_persistence_and_profile_isolation(home, tmp_path):
    created = restart(home, [["create", "Restart", "--slug", "restart"]])
    assert created[0][0] == 0
    original = projects()[0]
    observed = restart(home, [["show", original.id], ["archive", original.id]])
    assert original.id in observed[0][1] and observed[1][0] == 0
    archived = restart(home, [["list"], ["list", "--all"], ["restore", original.id]])
    assert "No projects yet" in archived[0][1]
    assert "(archived)" in archived[1][1] and archived[2][0] == 0
    other = tmp_path / "profile-b"
    other.mkdir(mode=0o700)
    isolated = restart(other, [["show", original.id], ["list"], ["create", "Restart"]])
    assert isolated[0][0] == 1 and "No projects yet" in isolated[1][1]
    assert isolated[2][0] == 0
    assert projects() == [original]
    with projects_db.connect_closing(other / "projects.db") as conn:
        assert projects_db.list_projects(conn)[0].id != original.id


def test_archive_does_not_cancel_linked_native_task(home):
    from hermes_cli import kanban_db, kanban_db_connect

    assert command("create", "Bound", "--board", "default")[0] == 0
    project = projects()[0]
    with kanban_db_connect.connect_closing(home / "kanban.db") as conn:
        task_id = kanban_db.create_task(
            conn, title="Synthetic linked task", project_id=project.id, initial_status="blocked"
        )
        before = kanban_db.get_task(conn, task_id)
        assert before.project_id == project.id
        events = conn.execute("SELECT * FROM task_events").fetchall()
        assert command("archive", project.id)[0] == 0
        assert kanban_db.get_task(conn, task_id) == before
        assert conn.execute("SELECT * FROM task_events").fetchall() == events
        assert command("restore", project.id)[0] == 0
        assert kanban_db.get_task(conn, task_id) == before
    # No worker was launched. Unchanged parked state is not proof of live cancellation.


def test_project_crud_is_not_exported_plugin_api(home):
    api = Path(hermes_cli.__file__).parent / "data" / "plugin_api.json"
    manifest = json.loads(api.read_text())
    entries = [entry for group in manifest["groups"] for entry in group["entries"]]
    assert entries
    assert not any(entry.split(":")[0] == "hermes_cli.projects_db" for entry in entries)
