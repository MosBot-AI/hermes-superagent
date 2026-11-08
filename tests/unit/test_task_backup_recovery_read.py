"""Only explicitly requested historical rows, never restoration or effect replay."""

import json
import sqlite3
from uuid import uuid4

import pytest
from test_task_backup import path, source

from personal_agent import task_backup as backup
from personal_agent.tasks import TaskError


@pytest.fixture
def home(tmp_path, monkeypatch):
    from personal_agent import PLUGIN_ID

    monkeypatch.setattr(backup, "current_profile_home", lambda: tmp_path)
    (tmp_path / "plugin-data" / PLUGIN_ID).mkdir(parents=True, mode=0o700)
    return tmp_path


def snapshot(home):
    connection, store, original = source(home)
    metadata = backup.task_backup(home, "create", "before-upgrade")
    connection.close()
    return metadata["sha256"]


def test_pages_read_historical_rows_and_show_original_after_live_changes(home):
    connection, store, original = source(home)
    digest = backup.task_backup(home, "create", "before-upgrade")["sha256"]
    before = path(home).read_bytes()
    first = backup.task_backup(home, "tasks", "before-upgrade", sha256=digest, limit=1)
    page = first["historical_tasks"]
    assert page["has_more"] and len(page["items"]) == 1
    assert "details" not in page["items"][0]
    task_id = page["items"][0]["id"]
    store.run(
        "update",
        {"task_id": task_id, "expected_revision": 1, "request_id": "later", "title": "Changed"},
    )
    output = backup.task_backup(home, "show", "before-upgrade", sha256=digest, task_id=task_id)
    old = output["historical_tasks"]["task"]
    assert old["title"] == "Second" and old["revision"] == 1
    assert "native_progress" not in old and "depends_on" not in old
    assert output["automatic_restore"] is False and "Historical untrusted" in output["notice"]
    second = backup.task_backup(
        home, "tasks", "before-upgrade", sha256=digest, after=page["next_cursor"], limit=1
    )["historical_tasks"]
    assert not second["has_more"] and second["next_cursor"] is None
    assert second["items"][0]["id"] != task_id
    assert second["items"][0]["title"] == "First"
    assert store.run("get", {"task_id": task_id})["data"]["title"] == "Changed"
    assert path(home).read_bytes() == before
    connection.close()


def test_recovery_reads_do_not_require_or_recreate_live_database(home):
    digest = snapshot(home)
    live = path(home).parent.parent / "tasks.sqlite3"
    live.unlink()
    page = backup.task_backup(home, "tasks", "before-upgrade", sha256=digest)
    assert len(page["historical_tasks"]["items"]) == 2
    assert not live.exists()


@pytest.mark.parametrize("operation", ["tasks", "show"])
def test_digest_change_refused_before_disclosing_content(home, operation):
    snapshot(home)
    args = {"task_id": str(uuid4())} if operation == "show" else {}
    with pytest.raises(TaskError, match="backup_changed"):
        backup.task_backup(home, operation, "before-upgrade", sha256="0" * 64, **args)


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"sha256": "bad"},
        {"sha256": "A" * 64},
        {"sha256": 1},
        {"sha256": "0" * 64, "limit": 0},
        {"sha256": "0" * 64, "limit": 21},
        {"sha256": "0" * 64, "limit": True},
        {"sha256": "0" * 64, "after": "not-id"},
        {"sha256": "0" * 64, "task_id": str(uuid4())},
    ],
)
def test_invalid_options_fail_without_creating_backup_directory(home, options):
    with pytest.raises(TaskError, match="invalid_request"):
        backup.task_backup(home, "tasks", "before-upgrade", **options)
    assert not path(home).parent.exists()


def test_missing_cursor_and_task_are_redacted(home):
    digest = snapshot(home)
    with pytest.raises(TaskError, match="invalid_cursor"):
        backup.task_backup(home, "tasks", "before-upgrade", sha256=digest, after=str(uuid4()))
    with pytest.raises(TaskError, match="not_found"):
        backup.task_backup(home, "show", "before-upgrade", sha256=digest, task_id=str(uuid4()))


def test_empty_snapshot(home):
    connection, store, _ = source(home)
    connection.execute("DELETE FROM task_dependencies")
    connection.execute("DELETE FROM tasks")
    digest = backup.task_backup(home, "create", "before-upgrade")["sha256"]
    page = backup.task_backup(home, "tasks", "before-upgrade", sha256=digest)["historical_tasks"]
    assert page == {"items": [], "next_cursor": None, "has_more": False}
    connection.close()


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("CREATE TABLE other(secret TEXT)", "unsupported_schema"),
        ("PRAGMA user_version=5", "unsupported_schema"),
        ("UPDATE tasks SET title=zeroblob(40000)", "backup_record_too_large"),
    ],
)
def test_malformed_rows_or_schema_fail_closed(home, mutation, code):
    snapshot(home)
    with sqlite3.connect(path(home)) as connection:
        connection.execute(mutation)
    import hashlib

    digest = hashlib.sha256(path(home).read_bytes()).hexdigest()
    before = path(home).read_bytes()
    with pytest.raises(TaskError, match=code):
        backup.task_backup(home, "tasks", "before-upgrade", sha256=digest)
    assert path(home).read_bytes() == before


def test_output_budget_fails_without_partial_content(home, monkeypatch):
    digest = snapshot(home)
    monkeypatch.setattr(backup, "MAX_RESULT_CHARS", 10)
    with pytest.raises(TaskError, match="backup_result_too_large"):
        backup.task_backup(home, "tasks", "before-upgrade", sha256=digest)


def test_cli_reads_are_explicit_and_live_revocable(home, capsys):
    import argparse

    from personal_agent.plugin import setup_cli

    parser = argparse.ArgumentParser()
    setup_cli(parser)
    digest = snapshot(home)
    args = parser.parse_args(
        ["task-backup", "tasks", "--name", "before-upgrade", "--sha256", digest]
    )
    assert backup.run_backup_cli(args, read_mode=lambda: "local_tasks", bound_home=home) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["data"]["historical_tasks"]["items"]
    assert backup.run_backup_cli(args, read_mode=lambda: "read_only", bound_home=home) == 1
    assert "First" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        parser.parse_args(["task-backup", "tasks", "--name", "before-upgrade"])


def test_sql_and_path_errors_never_leak_payload(home, monkeypatch, capsys):
    import argparse

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("private task text /secret/path")

    monkeypatch.setattr(backup, "_connection", fail)
    snapshot_dir = path(home).parent
    snapshot_dir.mkdir(mode=0o700)
    path(home).write_bytes(b"SQLite format 3\x00" + b"\x10\x00\x01\x01")
    path(home).chmod(0o600)
    args = argparse.Namespace(backup_operation="tasks", name="before-upgrade", sha256="0" * 64)
    assert backup.run_backup_cli(args, read_mode=lambda: "local_tasks", bound_home=home) == 1
    output = capsys.readouterr().out
    assert json.loads(output)["error"]["code"] == "backup_unavailable"
    assert "private task text" not in output and "/secret/path" not in output


def test_digest_and_rows_share_lock_against_sqlite_writer(home):
    digest = snapshot(home)
    original = backup._read_tasks
    import time

    def reader(connection):
        other = sqlite3.connect(path(home), isolation_level=None, timeout=0)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("UPDATE tasks SET title='Concurrent replacement'")
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                other.execute("COMMIT")
            rows = original(connection, "tasks", after=None, limit=10, task_id=None)
            assert {item["title"] for item in rows["items"]} == {"First", "Second"}
            return rows
        finally:
            other.rollback()
            other.close()

    result = backup._metadata(
        path(home), time.monotonic() + 30, reader=reader, expected_digest=digest
    )
    assert result["sha256"] == digest
    assert backup.task_backup(home, "inspect", "before-upgrade")["sha256"] == digest


@pytest.mark.parametrize("operation", ["inspect", "tasks", "show"])
def test_closed_wal_snapshot_is_refused_without_creating_sidecars(home, operation):
    import hashlib

    snapshot(home)
    connection = sqlite3.connect(path(home))
    connection.execute("PRAGMA journal_mode=WAL")
    task_id = connection.execute("SELECT id FROM tasks LIMIT 1").fetchone()[0]
    connection.close()
    assert not path(home).with_name(path(home).name + "-wal").exists()
    before = path(home).read_bytes()
    digest = hashlib.sha256(before).hexdigest()
    options = {"sha256": digest} if operation != "inspect" else {}
    if operation == "show":
        options["task_id"] = task_id
    with pytest.raises(TaskError, match="backup_not_standalone"):
        backup.task_backup(home, operation, "before-upgrade", **options)
    assert path(home).read_bytes() == before
    assert {item.name for item in path(home).parent.iterdir()} == {"before-upgrade.sqlite3"}
