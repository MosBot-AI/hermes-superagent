"""Real pinned host, public profile/storage APIs and in-process native CLI entries.

Private manager fields are observations, not plugin dependencies. Synthetic local
operator input only; these tests do not establish OS containment or owner identity.
"""

import argparse
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ID = "hermes-personal-agent"


def install(home):
    plugin = home / "plugins" / PLUGIN_ID
    plugin.mkdir(parents=True)
    for name in ("plugin.yaml", "__init__.py", "pyproject.toml", "compatibility.json", "LICENSE"):
        shutil.copy2(PLUGIN_ROOT / name, plugin / name)
    shutil.copytree(
        PLUGIN_ROOT / "personal_agent",
        plugin / "personal_agent",
        ignore=shutil.ignore_patterns("__pycache__"),
    )


def configure(home, mode="local_tasks"):
    settings = {} if mode == "default" else {"settings": {"mode": mode}}
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "plugins": {"enabled": [PLUGIN_ID], "entries": {PLUGIN_ID: settings}},
                "delegation": {"backend": "default"},
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def native(tmp_path, monkeypatch):
    from hermes_cli.plugins import PluginManager

    home = tmp_path / "profile-one"
    install(home)
    configure(home)
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    manager = PluginManager()
    try:
        yield home, manager
    finally:
        manager.unload()


def entry(manager):
    manager.discover_and_load()
    loaded = manager._plugins[PLUGIN_ID]
    assert loaded.enabled and loaded.error is None
    assert loaded.tools_registered == ["personal_agent_status"]
    assert not loaded.hooks_registered
    assert not loaded.middleware_registered
    assert set(manager._plugin_commands) == {"personal-access"}
    assert not manager._platform_handler_factories
    return manager._cli_commands["personal-agent"]


def invoke(command, capsys, *argv):
    parser = argparse.ArgumentParser()
    command["setup_fn"](parser)
    # Isolate host loader logs from the CLI's single JSON output.
    capsys.readouterr()
    code = command["handler_fn"](parser.parse_args(list(argv)))
    output = capsys.readouterr()
    assert output.err == ""
    return code, json.loads(output.out)


def task(command, capsys, *argv):
    return invoke(command, capsys, "tasks", *argv)


def capture(command, capsys, request="capture-1", title="Synthetic task"):
    code, result = task(
        command,
        capsys,
        "capture",
        "--title",
        title,
        "--details",
        "Synthetic body",
        "--request-id",
        request,
    )
    assert code == 0, result
    assert result["status"] == "ok"
    assert result["scope"] == "trusted_local_cli_only"
    return result


def assert_error(result, code, *secrets):
    assert result[0] == 1
    payload = result[1]
    assert payload["status"] == "error"
    assert payload["data"] is None
    assert payload["replayed"] is False
    if code is not None:
        assert payload["error"]["code"] == code
    for secret in secrets:
        assert str(secret) not in json.dumps(payload)


@pytest.mark.parametrize("mode", ["default", "read_only"])
@pytest.mark.parametrize(
    "argv",
    [
        ["capture", "--title", "Synthetic private title", "--request-id", "r1"],
        ["list"],
        ["show", "00000000-0000-4000-8000-000000000001"],
        [
            "update",
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "r2",
            "--title",
            "Synthetic change",
        ],
        [
            "complete",
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "r3",
            "--note",
            "Synthetic note",
        ],
        [
            "cancel",
            "00000000-0000-4000-8000-000000000001",
            "--expected-revision",
            "1",
            "--request-id",
            "r4",
            "--note",
            "Synthetic note",
        ],
    ],
)
def test_read_only_refuses_every_task_operation_without_storage(native, capsys, mode, argv):
    home, manager = native
    configure(home, mode)
    assert_error(task(entry(manager), capsys, *argv), "local_tasks_disabled")
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("mode", ["read_only", "local_tasks"])
def test_diagnostics_and_model_tool_never_create_storage(native, capsys, mode):
    from tools.registry import registry

    home, manager = native
    configure(home, mode)
    command = entry(manager)
    for name in ("status", "coverage"):
        code, result = invoke(command, capsys, name)
        assert code is None
        assert isinstance(result, dict)
    raw = registry.dispatch("personal_agent_status", {}, scope=manager.scope_key)
    assert json.loads(raw)["mode"] == mode
    assert not (home / "plugin-data").exists()


def test_task_lifecycle_survives_new_manager_and_replays_old_receipt(native, capsys):
    from hermes_cli.plugins import PluginManager
    from plugins.plugin_storage import plugin_data_dir

    home, manager = native
    first = capture(entry(manager), capsys)
    original = first["data"]
    assert original["state"] == "captured" and original["revision"] == 1
    task_id = original["id"]
    path = plugin_data_dir(PLUGIN_ID) / "tasks.sqlite3"
    assert path == home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    manager.unload()
    restarted = PluginManager()
    try:
        command = entry(restarted)
        assert task(command, capsys, "show", task_id)[1]["data"] == original
        assert task(command, capsys, "list")[1]["data"]["items"] == [original]
        update = [
            "update",
            task_id,
            "--expected-revision",
            "1",
            "--request-id",
            "update-1",
            "--title",
            "Synthetic edited task",
            "--details",
            "",
        ]
        code, updated = task(command, capsys, *update)
        assert code == 0 and updated["data"]["revision"] == 2
        assert updated["data"]["details"] == ""
        assert task(command, capsys, *update)[1]["replayed"] is True
        stale = update.copy()
        stale[5] = "stale-update"
        assert_error(task(command, capsys, *stale), "revision_conflict")
        changed = update.copy()
        changed[7] = "Synthetic changed replay"
        assert_error(task(command, capsys, *changed), "idempotency_conflict")
        code, completed = task(
            command,
            capsys,
            "complete",
            task_id,
            "--expected-revision",
            "2",
            "--request-id",
            "complete-1",
            "--note",
            "Synthetic done",
        )
        assert code == 0
        assert completed["data"]["state"] == "done"
        assert completed["data"]["revision"] == 3
        replay = capture(command, capsys)
        assert replay["replayed"] is True and replay["data"] == original
        assert task(command, capsys, "show", task_id)[1]["data"] == completed["data"]
        second = capture(command, capsys, request="capture-2")["data"]
        code, cancelled = task(
            command,
            capsys,
            "cancel",
            second["id"],
            "--expected-revision",
            "1",
            "--request-id",
            "cancel-2",
            "--note",
            "Synthetic cancellation",
        )
        assert code == 0 and cancelled["data"]["state"] == "cancelled"
        assert cancelled["data"]["revision"] == 2
        assert task(command, capsys, "list")[1]["data"]["items"] == []
        assert len(task(command, capsys, "list", "--state", "all")[1]["data"]["items"]) == 2
    finally:
        restarted.unload()


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("read_only", "local_tasks_disabled"),
        ("live", "invalid_configuration"),
        (None, "invalid_configuration"),
        ({}, "invalid_configuration"),
    ],
)
def test_loaded_handler_rechecks_live_configuration(native, capsys, mode, expected):
    home, manager = native
    command = entry(manager)
    configure(home, mode)
    assert_error(task(command, capsys, "list"), expected)
    assert not (home / "plugin-data").exists()


def test_native_profile_override_isolation_and_stale_handler(native, tmp_path, capsys):
    from hermes_cli.plugins import PluginManager
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    home, manager = native
    first_command = entry(manager)
    first = capture(first_command, capsys)["data"]
    other = tmp_path / "profile-two"
    install(other)
    configure(other)
    token = set_hermes_home_override(other)
    second_manager = PluginManager()
    try:
        assert_error(task(first_command, capsys, "show", first["id"]), "profile_context_changed")
        assert not (other / "plugin-data").exists()
        second_command = entry(second_manager)
        assert task(second_command, capsys, "list")[1]["data"]["items"] == []
        # Same idempotency key is scoped to each independent profile.
        second = capture(second_command, capsys)["data"]
        assert first["id"] != second["id"]
        assert_error(task(second_command, capsys, "show", first["id"]), "not_found")
    finally:
        second_manager.unload()
        reset_hermes_home_override(token)
    assert task(first_command, capsys, "list")[1]["data"]["items"] == [first]
    assert_error(task(second_command, capsys, "list"), "profile_context_changed")
    assert home.is_dir()


def test_missing_profile_is_not_recreated(native, capsys):
    home, manager = native
    command = entry(manager)
    shutil.rmtree(home)
    assert_error(task(command, capsys, "list"), None, home)
    assert not home.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["capture", "--title", "", "--request-id", "invalid-empty-title"],
        ["capture", "--title", "Synthetic private title", "--request-id", "invalid/id"],
        ["list", "--limit", "101"],
        ["show", "not-a-task"],
    ],
)
def test_invalid_payload_rejected_before_storage_creation(native, capsys, argv):
    home, manager = native
    assert_error(
        task(entry(manager), capsys, *argv), "invalid_request", home, "Synthetic private title"
    )
    assert not (home / "plugin-data").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only local storage contract")
@pytest.mark.parametrize(
    "kind", ["broad", "db-symlink", "hardlink", "parent-symlink", "dir-symlink"]
)
def test_unsafe_storage_is_refused_without_mutating_target(native, tmp_path, capsys, kind):
    home, manager = native
    command = entry(manager)
    directory = home / "plugin-data" / PLUGIN_ID
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "sentinel"
    target.write_bytes(b"Synthetic private file contents")
    target.chmod(0o600)
    if kind == "parent-symlink":
        (home / "plugin-data").symlink_to(outside, target_is_directory=True)
    elif kind == "dir-symlink":
        directory.parent.mkdir()
        directory.symlink_to(outside, target_is_directory=True)
    else:
        directory.mkdir(parents=True)
        db = directory / "tasks.sqlite3"
        if kind == "db-symlink":
            db.symlink_to(target)
        elif kind == "hardlink":
            os.link(target, db)
        else:
            db.write_bytes(b"Synthetic private database contents")
            db.chmod(0o644)
            target = db
    before, mode = target.read_bytes(), target.stat().st_mode
    assert_error(
        task(
            command,
            capsys,
            "capture",
            "--title",
            "Synthetic private title",
            "--details",
            "Synthetic private body",
            "--request-id",
            "unsafe-1",
        ),
        None,
        target,
        home,
        "Synthetic private title",
        "Synthetic private body",
    )
    assert target.read_bytes() == before and target.stat().st_mode == mode
    assert sorted(p.name for p in outside.iterdir()) == ["sentinel"]


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("unknown", "foreign_database"),
        ("newer", "unsupported_schema"),
        ("corrupt", "local_tasks_unavailable"),
    ],
)
def test_unrecognized_database_is_never_reset(native, capsys, kind, expected):
    home, manager = native
    command = entry(manager)
    directory = home / "plugin-data" / PLUGIN_ID
    directory.mkdir(parents=True)
    path = directory / "tasks.sqlite3"
    if kind == "corrupt":
        path.write_bytes(b"Synthetic corrupt non-database contents")
    else:
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE sentinel (value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES ('synthetic-private')")
            if kind == "newer":
                connection.execute("PRAGMA application_id = 1346458699")
                connection.execute("PRAGMA user_version = 999")
    path.chmod(0o600)
    before = path.read_bytes()
    assert_error(task(command, capsys, "list"), expected, home, "synthetic-private")
    assert path.read_bytes() == before


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only local storage contract")
@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["empty-hardlink", "padded-hardlink", "broad", "symlink"])
def test_unsafe_existing_sqlite_sidecar_is_refused_without_mutation(
    native, tmp_path, capsys, suffix, kind
):
    home, manager = native
    command = entry(manager)
    capture(command, capsys)
    db = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before_db = db.read_bytes()
    outside = tmp_path / "synthetic-outside-sidecar"
    outside.write_bytes(b"" if kind == "empty-hardlink" else bytes(512))
    outside.chmod(0o600)
    sidecar = db.with_name(db.name + suffix)
    if kind.endswith("hardlink"):
        os.link(outside, sidecar)
    elif kind == "symlink":
        sidecar.symlink_to(outside)
    else:
        sidecar.write_bytes(bytes(512))
        sidecar.chmod(0o644)
    before_sidecar, before_outside = sidecar.read_bytes(), outside.read_bytes()
    mode_sidecar, mode_outside = sidecar.stat().st_mode, outside.stat().st_mode
    assert_error(
        task(
            command,
            capsys,
            "capture",
            "--title",
            "Synthetic private sidecar title",
            "--request-id",
            "sidecar-2",
        ),
        None,
        home,
        outside,
        "Synthetic private sidecar title",
    )
    assert db.read_bytes() == before_db
    assert sidecar.read_bytes() == before_sidecar and sidecar.stat().st_mode == mode_sidecar
    assert outside.read_bytes() == before_outside and outside.stat().st_mode == mode_outside


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only local storage contract")
@pytest.mark.parametrize("directory_name", ["plugin-data", PLUGIN_ID])
@pytest.mark.parametrize("permissions", [0o775, 0o777])
def test_writable_storage_directory_is_refused_without_permission_repair(
    native, capsys, directory_name, permissions
):
    home, manager = native
    command = entry(manager)
    directory = home / "plugin-data" / PLUGIN_ID
    directory.mkdir(parents=True)
    unsafe = directory.parent if directory_name == "plugin-data" else directory
    unsafe.chmod(permissions)
    assert_error(task(command, capsys, "list"), None, home)
    assert stat.S_IMODE(unsafe.stat().st_mode) == permissions
    assert not (directory / "tasks.sqlite3").exists()


def test_actual_top_level_cli_persists_across_clean_processes(native, tmp_path):
    """Exercise the real CLI main, not only its registered handler function."""
    from hermes_cli import main

    home, _manager = native
    upstream = Path(main.__file__).resolve().parents[1]
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_PYTHON": sys.executable,
        "HERMES_BUNDLED_PLUGINS": os.environ["HERMES_BUNDLED_PLUGINS"],
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONHASHSEED": "0",
    }
    bootstrap = """
import socket, sys
def refuse(*args, **kwargs):
    raise AssertionError('Top-level CLI contract must not connect to the network')
socket.create_connection = refuse
socket.socket.connect = refuse
socket.socket.connect_ex = refuse
sys.argv = ['hermes', *sys.argv[1:]]
from hermes_cli.main import main
main()
"""

    def command(*args, expected=0):
        result = subprocess.run(
            [sys.executable, "-c", bootstrap, "personal-agent", *args],
            cwd=upstream,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == expected, result.stderr
        return json.loads(result.stdout)

    created = command("tasks", "capture", "--title", "Synthetic CLI task", "--request-id", "c1")
    task_id = created["data"]["id"]
    assert command("tasks", "list")["data"]["items"][0]["id"] == task_id
    command(
        "tasks",
        "complete",
        task_id,
        "--expected-revision",
        "1",
        "--note",
        "Synthetic explicit completion",
        "--request-id",
        "c2",
    )
    assert command("tasks", "show", task_id)["data"]["state"] == "done"
    assert command("status")["local_task_inbox"]["enabled"] is True
    database = home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"
    before = database.read_bytes()
    configure(home, "read_only")
    assert command("tasks", "list", expected=1)["error"]["code"] == "local_tasks_disabled"
    assert database.read_bytes() == before


def test_stale_status_handler_does_not_recreate_a_deleted_profile(native, capsys):
    home, manager = native
    command = entry(manager)
    shutil.rmtree(home)
    code, result = invoke(command, capsys, "status")
    assert code == 1
    assert result["error"]["code"] == "profile_context_changed"
    assert not home.exists()
