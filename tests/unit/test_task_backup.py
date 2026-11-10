"""Synthetic task snapshots, publication failure and local-only admission."""

import argparse
import json
import os
import sqlite3
from pathlib import Path

import pytest

from personal_agent import PLUGIN_ID
from personal_agent import task_backup as backup
from personal_agent.conversation_tasks import _parse
from personal_agent.plugin import setup_cli
from personal_agent.tasks import TaskError, TaskStore


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "current_profile_home", lambda: tmp_path)
    directory = tmp_path / "plugin-data" / PLUGIN_ID
    directory.mkdir(parents=True, mode=0o700)
    return tmp_path


def source(home, wal=False):
    path = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    connection = sqlite3.connect(path, isolation_level=None)
    path.chmod(0o600)
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    store = TaskStore(connection)
    store.initialize()
    result = store.run(
        "capture_plan",
        {
            "project": "Synthetic",
            "request_id": "synthetic-plan",
            "tasks": [{"title": "First"}, {"title": "Second", "depends_on": [1]}],
        },
    )
    return connection, store, result


def path(home, name="before-upgrade"):
    return home / "plugin-data" / PLUGIN_ID / "task-backups" / (name + ".sqlite3")


@pytest.mark.parametrize("wal", [False, True])
def test_snapshot_preserves_rows_receipts_edges_and_is_standalone(home, wal):
    connection, store, original = source(home, wal)
    original_dump = list(connection.iterdump())
    metadata = backup.task_backup(home, "create", "before-upgrade")
    assert metadata["counts"] == {"tasks": 2, "events": 2, "receipts": 1, "task_dependencies": 1}
    assert metadata["automatic_restore"] is False
    assert len(metadata["sha256"]) == 64
    assert path(home).stat().st_mode & 0o777 == 0o600
    assert path(home).parent.stat().st_mode & 0o777 == 0o700
    assert path(home).stat().st_nlink == 1
    assert backup.task_backup(home, "inspect", "before-upgrade") == metadata
    # A later live mutation does not alter the snapshot.
    store.run("capture", {"title": "Later", "request_id": "later"})
    snapshot = sqlite3.connect(path(home), isolation_level=None)
    assert list(snapshot.iterdump()) == original_dump
    restored_for_test = TaskStore(snapshot)
    restored_for_test.initialize()
    replay = restored_for_test.run(
        "capture_plan",
        {
            "project": "Synthetic",
            "request_id": "synthetic-plan",
            "tasks": [{"title": "First"}, {"title": "Second", "depends_on": [1]}],
        },
    )
    assert replay["replayed"] and replay["data"] == original["data"]
    snapshot.close()
    assert backup.task_backup(home, "inspect", "before-upgrade") == metadata
    connection.close()
    assert set(p.name for p in path(home).parent.iterdir()) == {"before-upgrade.sqlite3"}


def test_existing_backup_is_never_overwritten(home):
    connection, _, _ = source(home)
    metadata = backup.task_backup(home, "create", "before-upgrade")
    with pytest.raises(TaskError, match="backup_exists"):
        backup.task_backup(home, "create", "before-upgrade")
    assert backup.task_backup(home, "inspect", "before-upgrade") == metadata
    connection.close()


@pytest.mark.parametrize(
    "name", ["../escape", "/tmp/escape", ".", "", "a/b", "a.b", "中文", "x" * 65]
)
def test_invalid_names_do_not_create_files(home, name):
    with pytest.raises(TaskError, match="invalid_request"):
        backup.task_backup(home, "create", name)
    assert not path(home).parent.exists()


def test_missing_store_is_not_initialized(home):
    with pytest.raises(TaskError, match="backup_not_found"):
        backup.task_backup(home, "create", "before-upgrade")
    assert not (home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3").exists()


@pytest.mark.parametrize(
    "change,code",
    [
        ("PRAGMA application_id=0", "foreign_database"),
        ("PRAGMA user_version=5", "unsupported_schema"),
        ("CREATE TABLE extra(secret TEXT)", "unsupported_schema"),
    ],
)
def test_unrecognized_database_refused_without_migration(home, change, code):
    connection, _, _ = source(home)
    connection.execute(change)
    before = list(connection.iterdump())
    with pytest.raises(TaskError, match=code):
        backup.task_backup(home, "create", "before-upgrade")
    assert list(connection.iterdump()) == before
    assert not path(home).exists()
    connection.close()


@pytest.mark.parametrize(
    "kind",
    [
        "source_symlink",
        "source_hardlink",
        "public_source",
        "directory_link",
        "public_backups",
        "destination_link",
        "sidecar_link",
    ],
)
def test_unsafe_files_and_paths_fail_closed(home, tmp_path, kind):
    connection, _, _ = source(home)
    connection.close()
    db = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    if kind == "source_symlink":
        db.rename(db.with_suffix(".original"))
        db.symlink_to(db.with_suffix(".original"))
    elif kind == "source_hardlink":
        os.link(db, home / "hardlink")
    elif kind == "public_source":
        db.chmod(0o644)
    elif kind == "directory_link":
        external = home / "external"
        external.mkdir(mode=0o700)
        path(home).parent.symlink_to(external)
    elif kind == "public_backups":
        path(home).parent.mkdir(mode=0o755)
    elif kind == "destination_link":
        path(home).parent.mkdir(mode=0o700)
        path(home).symlink_to(db)
    elif kind == "sidecar_link":
        db.with_name(db.name + "-wal").symlink_to(home / "missing")
    with pytest.raises(TaskError):
        backup.task_backup(home, "create", "before-upgrade")
    assert db.exists()


def test_backup_failure_removes_only_temporary_file(home, monkeypatch):
    connection, _, _ = source(home)

    def fail(*args, **kwargs):
        raise OSError("synthetic private error")

    monkeypatch.setattr(backup.os, "link", fail)
    with pytest.raises(OSError):
        backup.task_backup(home, "create", "before-upgrade")
    assert list(path(home).parent.iterdir()) == []
    assert connection.execute("SELECT count(*) FROM tasks").fetchone() == (2,)
    connection.close()


def test_racing_publication_does_not_replace_destination(home, monkeypatch):
    connection, _, _ = source(home)
    original_link = os.link

    def race(src, dst, **kwargs):
        Path(dst).write_bytes(b"competitor")
        return original_link(src, dst, **kwargs)

    monkeypatch.setattr(backup.os, "link", race)
    with pytest.raises(TaskError, match="backup_exists"):
        backup.task_backup(home, "create", "before-upgrade")
    assert path(home).read_bytes() == b"competitor"
    assert not list(path(home).parent.glob(".pending-*"))
    connection.close()


def test_failed_directory_sync_preserves_published_snapshot(home, monkeypatch):
    connection, _, _ = source(home)
    real = os.fsync
    calls = []

    def sync(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError("directory sync failure")
        return real(fd)

    monkeypatch.setattr(backup.os, "fsync", sync)
    with pytest.raises(OSError):
        backup.task_backup(home, "create", "before-upgrade")
    assert backup.task_backup(home, "inspect", "before-upgrade")["integrity"] == "ok"
    connection.close()


def test_size_limit_and_timeout_never_publish(home, monkeypatch):
    connection, _, _ = source(home)
    monkeypatch.setattr(backup, "MAX_BYTES", 1)
    with pytest.raises(TaskError, match="backup_size_limit"):
        backup.task_backup(home, "create", "before-upgrade")
    monkeypatch.setattr(backup, "MAX_BYTES", 512 * 1024 * 1024)
    monkeypatch.setattr(backup, "TIMEOUT_SECONDS", -1)
    with pytest.raises((TaskError, sqlite3.OperationalError)):
        backup.task_backup(home, "create", "before-upgrade")
    assert not path(home).exists()
    assert not list(path(home).parent.glob(".pending-*"))
    connection.close()


def test_inspect_refuses_sidecars_and_corruption(home):
    connection, _, _ = source(home)
    backup.task_backup(home, "create", "before-upgrade")
    sidecar = path(home).with_name(path(home).name + "-wal")
    sidecar.write_bytes(b"synthetic")
    with pytest.raises(TaskError, match="backup_sidecar_present"):
        backup.task_backup(home, "inspect", "before-upgrade")
    sidecar.unlink()
    path(home).write_bytes(b"not a database")
    with pytest.raises(TaskError, match="backup_not_standalone"):
        backup.task_backup(home, "inspect", "before-upgrade")
    connection.close()


def test_cli_mode_and_profile_gates_before_data(home, monkeypatch, capsys):
    args = argparse.Namespace(backup_operation="create", name="before-upgrade")
    assert backup.run_backup_cli(args, read_mode=lambda: "read_only", bound_home=home) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "local_tasks_disabled"
    monkeypatch.setattr(backup, "current_profile_home", lambda: home / "other")

    def forbidden():
        pytest.fail("config consulted for changed profile")

    assert backup.run_backup_cli(args, read_mode=forbidden, bound_home=home) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "profile_context_changed"
    assert not path(home).parent.exists()


def test_cli_reports_metadata_and_redacts_private_errors(home, monkeypatch, capsys):
    connection, _, _ = source(home)
    parser = argparse.ArgumentParser()
    setup_cli(parser)
    args = parser.parse_args(["task-backup", "create", "--name", "before-upgrade"])
    assert backup.run_backup_cli(args, read_mode=lambda: "local_tasks", bound_home=home) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok" and "First" not in json.dumps(output)

    def fail(*args, **kwargs):
        raise OSError("private path and text")

    monkeypatch.setattr(backup, "task_backup", fail)
    assert backup.run_backup_cli(args, read_mode=lambda: "local_tasks", bound_home=home) == 1
    output = capsys.readouterr().out
    assert "private" not in output and "backup_unavailable" in output
    connection.close()


@pytest.mark.parametrize("command", ["backup --name test", "task-backup create --name test"])
def test_native_conversation_cannot_export(command):
    with pytest.raises(TaskError, match="invalid_request"):
        _parse(command)


def test_wal_snapshot_does_not_mix_a_concurrent_commit(home, monkeypatch):
    connection, store, _ = source(home, wal=True)
    inspect = backup.inspect_task_snapshot
    calls = 0

    def concurrent_commit(snapshot, **kwargs):
        nonlocal calls
        result = inspect(snapshot, **kwargs)
        calls += 1
        if calls == 1:
            store.run("capture", {"title": "Concurrent", "request_id": "concurrent"})
        return result

    monkeypatch.setattr(backup, "inspect_task_snapshot", concurrent_commit)
    result = backup.task_backup(home, "create", "before-upgrade")
    assert result["counts"]["tasks"] == 2
    assert connection.execute("SELECT count(*) FROM tasks").fetchone() == (3,)
    connection.close()


def test_snapshot_excludes_other_stores_and_settings(home):
    connection, _, _ = source(home)
    directory = home / "plugin-data" / PLUGIN_ID
    for filename in ("memory.sqlite3", "policy.sqlite3", ".env"):
        (directory / filename).write_text("synthetic-private-marker")
    backup.task_backup(home, "create", "before-upgrade")
    assert b"synthetic-private-marker" not in path(home).read_bytes()
    assert set(p.name for p in path(home).parent.iterdir()) == {"before-upgrade.sqlite3"}
    connection.close()


def test_abrupt_exit_in_publication_window_fails_closed(home):
    # The brief link/unlink window is intentionally not treated as an immutable
    # published single-link backup. Keep both names for explicit operator review.
    import subprocess
    import sys

    connection, _, _ = source(home)
    connection.close()
    script = """
import os, sys
from pathlib import Path
from personal_agent import task_backup as b
home = Path(sys.argv[1])
b.current_profile_home = lambda: home
link = os.link
def exit_after_link(*args, **kwargs):
    link(*args, **kwargs)
    os._exit(90)
b.os.link = exit_after_link
b.task_backup(home, "create", "before-upgrade")
"""
    result = subprocess.run([sys.executable, "-c", script, str(home)], timeout=10)
    assert result.returncode == 90
    pending = list(path(home).parent.glob(".pending-*"))
    assert len(pending) == 1
    assert pending[0].stat().st_ino == path(home).stat().st_ino
    with pytest.raises(TaskError, match="unsafe_storage_file"):
        backup.task_backup(home, "inspect", "before-upgrade")
    with pytest.raises(TaskError, match="backup_exists"):
        backup.task_backup(home, "create", "before-upgrade")
    # Simulate deliberate offline operator cleanup of the verified alias, not
    # automatic recovery or acceptance of an arbitrary linked file.
    pending[0].unlink()
    assert backup.task_backup(home, "inspect", "before-upgrade")["integrity"] == "ok"


def _competing_writer(database):
    """Separate process: an independent OS-lock oracle, not another SQLite thread."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sqlite3, sys
c = sqlite3.connect(sys.argv[1], timeout=0.05, isolation_level=None)
try:
    c.execute('BEGIN IMMEDIATE')
    c.execute("UPDATE tasks SET title='Concurrent mutation'")
    c.execute('COMMIT')
    print('committed')
except sqlite3.OperationalError as e:
    if 'locked' not in str(e): raise
    print('locked')
finally:
    c.close()
""",
            str(database),
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("with_reader", [False, True])
def test_metadata_retains_os_lock_through_digest_and_reader(home, monkeypatch, with_reader):
    import hashlib
    import time

    connection, _, _ = source(home)
    backup.task_backup(home, "create", "before-upgrade")
    connection.close()
    original = hashlib.sha256(path(home).read_bytes()).hexdigest()
    real_sha = hashlib.sha256
    events = []

    class Digest:
        def __init__(self):
            self.inner = real_sha()

        def update(self, block):
            self.inner.update(block)

        def hexdigest(self):
            # In the old implementation the hash context has closed its fd here.
            events.append("digest")
            assert _competing_writer(path(home)) == "locked"
            return self.inner.hexdigest()

    def reader(conn):
        events.append("reader")
        assert _competing_writer(path(home)) == "locked"
        return conn.execute("SELECT title FROM tasks ORDER BY sequence").fetchall()

    monkeypatch.setattr(backup.hashlib, "sha256", Digest)
    result = backup._metadata(
        path(home),
        time.monotonic() + 10,
        reader=reader if with_reader else None,
        expected_digest=original,
    )
    assert result["sha256"] == original
    assert events == (["digest", "reader"] if with_reader else ["digest"])
    if with_reader:
        assert result["historical_tasks"] == [("First",), ("Second",)]
    assert _competing_writer(path(home)) == "committed"


def test_source_validation_does_not_drop_existing_process_read_lock(home):
    connection, _, _ = source(home)
    database = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    try:
        connection.execute("BEGIN")
        connection.execute("SELECT * FROM tasks").fetchall()
        backup._check_file(database)
        for suffix in ("-journal", "-wal", "-shm"):
            backup._private_database_file(database.with_name(database.name + suffix), create=False)
        assert _competing_writer(database) == "locked"
        connection.rollback()
        assert _competing_writer(database) == "committed"
    finally:
        connection.close()


@pytest.mark.parametrize("failure", ["connection", "schema", "digest", "reader"])
def test_metadata_failure_closes_connection_before_hash_descriptor(home, monkeypatch, failure):
    import time

    connection, _, _ = source(home)
    backup.task_backup(home, "create", "before-upgrade")
    connection.close()
    real_connection, real_close = backup._connection, os.close
    events = []

    class Connection:
        def __init__(self):
            self.conn = real_connection(path(home), time.monotonic() + 10)

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def close(self):
            events.append("connection")
            self.conn.close()

    def connect(*args):
        if failure == "connection":
            raise TaskError("injected")
        return Connection()

    def close(fd):
        events.append("descriptor")
        real_close(fd)

    def fail(*args, **kwargs):
        raise TaskError("injected")

    monkeypatch.setattr(backup, "_connection", connect)
    monkeypatch.setattr(backup.os, "close", close)
    if failure == "schema":
        monkeypatch.setattr(backup, "inspect_task_snapshot", fail)
    with pytest.raises(TaskError):
        backup._metadata(
            path(home),
            time.monotonic() + 10,
            expected_digest="0" * 64 if failure == "digest" else None,
            reader=fail if failure == "reader" else None,
        )
    assert events == (["descriptor"] if failure == "connection" else ["connection", "descriptor"])
    assert _competing_writer(path(home)) == "committed"


def test_metadata_serializes_controlled_readers_and_bounds_wait(home, monkeypatch):
    import concurrent.futures
    import threading
    import time

    connection, _, _ = source(home)
    backup.task_backup(home, "create", "before-upgrade")
    connection.close()
    entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
    real = backup._locked_metadata

    def locked(*args, **kwargs):
        if threading.current_thread().name.startswith("first"):
            entered.set()
            assert release.wait(5)
        else:
            waiting.set()
        return real(*args, **kwargs)

    monkeypatch.setattr(backup, "_locked_metadata", locked)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="first") as pool:
        future = pool.submit(backup._metadata, path(home), time.monotonic() + 10)
        try:
            assert entered.wait(5)
            with pytest.raises(TaskError, match="backup_timeout"):
                backup._metadata(path(home), time.monotonic() + 0.05)
            assert not waiting.is_set()
        finally:
            release.set()
        assert future.result(timeout=5)["counts"]["tasks"] == 2
    assert backup._metadata(path(home), time.monotonic() + 5)["counts"]["tasks"] == 2
    assert waiting.is_set()


@pytest.mark.parametrize("module_name", ["task_backup", "memory_snapshot"])
@pytest.mark.parametrize("stage", [1, 2, 3])
def test_connection_setup_failure_explicitly_closes_before_raw_fd(
    home, monkeypatch, module_name, stage
):
    import importlib
    import time

    module = importlib.import_module("personal_agent." + module_name)
    connection, _, _ = source(home)
    backup.task_backup(home, "create", "before-upgrade")
    connection.close()
    real_connect, real_close = sqlite3.connect, os.close
    events = []

    class Connection:
        def __init__(self, *args, **kwargs):
            self.conn = real_connect(*args, **kwargs)
            self.calls = 0

        def step(self):
            self.calls += 1
            if self.calls == stage:
                raise RuntimeError("synthetic setup failure")

        def execute(self, *args):
            self.step()
            return self.conn.execute(*args)

        def set_progress_handler(self, *args):
            self.step()
            self.conn.set_progress_handler(*args)

        def close(self):
            events.append("connection")
            self.conn.close()

    def close(fd):
        events.append("descriptor")
        real_close(fd)

    monkeypatch.setattr(module.sqlite3, "connect", Connection)
    monkeypatch.setattr(module.os, "close", close)
    with pytest.raises(RuntimeError, match="synthetic setup failure"):
        if module_name == "task_backup":
            module._metadata(path(home), time.monotonic() + 5)
        else:
            module._metadata(path(home), "synthetic", time.monotonic() + 5)
    # Memory's precheck descriptor also closes before setup, but no SQLite lock
    # has been established yet; its outer metadata gate excludes other inspectors.
    assert events[-2:] == ["connection", "descriptor"]
    assert not module._METADATA_LOCK.locked()


@pytest.mark.parametrize("module_name", ["task_backup", "memory_snapshot"])
def test_connection_close_failure_still_closes_descriptor_and_releases_gate(
    home, monkeypatch, module_name
):
    import importlib
    import time

    module = importlib.import_module("personal_agent." + module_name)
    connection, _, _ = source(home)
    backup.task_backup(home, "create", "before-upgrade")
    connection.close()
    helper = "_connection" if module_name == "task_backup" else "_connect"
    real_connect, real_close = getattr(module, helper), os.close
    events = []

    class Connection:
        def __init__(self, *args):
            self.conn = real_connect(*args)

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def close(self):
            self.conn.close()
            events.append("connection")
            raise RuntimeError("synthetic close failure")

    def close(fd):
        events.append("descriptor")
        real_close(fd)

    monkeypatch.setattr(module, helper, Connection)
    monkeypatch.setattr(module.os, "close", close)
    if module_name == "memory_snapshot":
        monkeypatch.setattr(module, "_summary", lambda *args: {})
    with pytest.raises(RuntimeError, match="synthetic close failure"):
        if module_name == "task_backup":
            module._metadata(path(home), time.monotonic() + 5)
        else:
            module._metadata(path(home), "synthetic", time.monotonic() + 5)
    assert events[-2:] == ["connection", "descriptor"]
    assert not module._METADATA_LOCK.locked()
