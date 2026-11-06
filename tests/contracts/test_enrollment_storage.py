"""Real pinned profile/storage helpers; explicit internal calls, never enrollment.

All IDs, homes and prospective policy data are synthetic. No host provenance
issuer, native Bot, socket, grant, real account or protected read is exercised.
"""

import importlib
import json
import os
import sqlite3
import stat

import pytest
from test_local_task_cli import PLUGIN_ID, configure, entry, invoke
from test_local_task_cli import native as native


@pytest.fixture
def api(native):
    _, manager = native
    entry(manager)
    module = manager._plugins[PLUGIN_ID].module
    return importlib.import_module(module.__name__ + ".personal_agent.enrollment_storage")


def location(home):
    return home / "plugin-data" / PLUGIN_ID / "enrollment.sqlite3"


def seed(home):
    path = location(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    return path


def create_payload():
    return {
        "owner_id": "prospective-owner",
        "profile_id": "prospective-profile",
        "enrollment_id": "pending-1",
        "transport_id": "telegram",
        "transport_receiver_id": "synthetic-receiver",
        "principal_id": "synthetic-actor",
        "scope": {
            "operation": "personal.tasks.read",
            "target": "own_inbox",
            "resource_ids": (),
            "data_scope": "tasks.summary",
        },
    }


def lookup():
    return {key: create_payload()[key] for key in ("owner_id", "profile_id", "enrollment_id")}


@pytest.mark.parametrize("mode", ["default", "read_only", "local_tasks"])
def test_plugin_load_and_status_do_not_open_enrollment_store(native, capsys, mode):
    home, manager = native
    configure(home, mode)
    command = entry(manager)
    code, status = invoke(command, capsys, "status")
    assert code is None
    assert status["enrollment_policy"]["production_adapter_enabled"] is False
    assert status["enrollment_policy"]["activation_supported"] is False
    assert not (home / "plugin-data").exists()
    assert set(manager._plugin_commands) == {"personal-access"}


def test_internal_store_persists_in_native_profile_without_task_data(native, api):
    home, _ = native
    with api.open_enrollment_store(home, enabled=True) as store:
        result = store.run("create", create_payload())
    path = location(home)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not path.with_name("tasks.sqlite3").exists()
    with api.open_enrollment_store(home, enabled=True) as restarted:
        assert restarted.run("get", lookup()) == result
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_profile_switch_rejects_stale_bound_home_before_creating_any_database(
    native, tmp_path, monkeypatch, api
):
    home, _ = native
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    with pytest.raises(api.EnrollmentError, match="profile_context_changed"):
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Unreachable")
    assert not (home / "plugin-data").exists()
    assert not (other / "plugin-data").exists()


def test_two_native_profiles_keep_same_prospective_ids_separate(native, tmp_path, monkeypatch, api):
    home, _ = native
    with api.open_enrollment_store(home, enabled=True) as store:
        first = store.run("create", create_payload())
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other))
    with api.open_enrollment_store(other, enabled=True) as store:
        with pytest.raises(api.EnrollmentError, match="not_found"):
            store.run("get", lookup())
        second = store.run("create", create_payload())
    assert first == second  # Equal prospective metadata does not mean shared authority.
    assert location(home).stat().st_ino != location(other).stat().st_ino


@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "world_readable", "fifo", "directory"])
def test_unsafe_main_or_sidecar_is_refused_without_repair(native, tmp_path, suffix, kind, api):
    home, _ = native
    path = seed(home)
    target = path.with_name(path.name + suffix)
    if target.exists():
        target.unlink()
    sentinel = tmp_path / "synthetic-private-sentinel"
    sentinel.write_bytes(b"synthetic-private-data")
    sentinel.chmod(0o600)
    if kind == "symlink":
        target.symlink_to(sentinel)
    elif kind == "hardlink":
        os.link(sentinel, target)
    elif kind == "world_readable":
        target.write_bytes(b"")
        target.chmod(0o644)
    elif kind == "fifo":
        os.mkfifo(target, 0o600)
    else:
        target.mkdir()
    before = target.lstat()
    with pytest.raises(api.EnrollmentError) as error:
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Unsafe storage opened")
    assert str(sentinel) not in str(error.value)
    assert sentinel.read_bytes() == b"synthetic-private-data"
    assert target.lstat().st_mode == before.st_mode
    assert target.lstat().st_ino == before.st_ino


@pytest.mark.parametrize("component", ["home", "parent", "data"])
def test_writable_directory_is_rejected_without_permission_repair(native, component, api):
    home, _ = native
    path = seed(home)
    directory = {"home": home, "parent": path.parent.parent, "data": path.parent}[component]
    directory.chmod(0o777)
    with pytest.raises(api.EnrollmentError, match="unsafe_storage_path"):
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Unsafe directory opened")
    assert stat.S_IMODE(directory.stat().st_mode) == 0o777
    assert path.read_bytes() == b""


@pytest.mark.parametrize("component", ["parent", "data"])
def test_symlinked_directory_is_rejected_before_following_it(native, tmp_path, component, api):
    home, _ = native
    target = tmp_path / "synthetic-target"
    target.mkdir()
    parent = home / "plugin-data"
    if component == "parent":
        parent.symlink_to(target, target_is_directory=True)
    else:
        parent.mkdir()
        (parent / PLUGIN_ID).symlink_to(target, target_is_directory=True)
    with pytest.raises(api.EnrollmentError, match="unsafe_storage_path"):
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Symlink followed")
    assert list(target.iterdir()) == []


def test_existing_wal_store_is_refused_not_converted(native, api):
    home, _ = native
    path = seed(home)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sentinel(value TEXT)")
    with pytest.raises(api.EnrollmentError, match="unsupported_storage_journal"):
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Unsupported journal accepted")
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_foreign_task_database_is_never_adopted(native, api):
    TaskStore = importlib.import_module(api.__package__ + ".tasks").TaskStore

    home, _ = native
    path = seed(home)
    connection = sqlite3.connect(path, isolation_level=None)
    TaskStore(connection).initialize()
    connection.close()
    before = path.read_bytes()
    with pytest.raises(api.EnrollmentError, match="foreign_database"):
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Task database adopted")
    assert path.read_bytes() == before


def test_store_is_closed_after_body_failure(native, api):
    home, _ = native
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with api.open_enrollment_store(home, enabled=True) as store:
            connection = store._connection
            raise RuntimeError("synthetic failure")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


@pytest.mark.parametrize("failure", [KeyboardInterrupt, SystemExit])
def test_store_is_closed_when_initialization_is_interrupted(native, api, monkeypatch, failure):
    home, _ = native
    opened = []

    def interrupted(store):
        opened.append(store._connection)
        raise failure()

    monkeypatch.setattr(api.EnrollmentStore, "initialize", interrupted)
    with pytest.raises(failure):
        with api.open_enrollment_store(home, enabled=True):
            pytest.fail("Unreachable")
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_private_status_never_contains_persisted_prospective_identity(native, capsys, api):
    home, manager = native
    with api.open_enrollment_store(home, enabled=True) as store:
        store.run("create", create_payload())
    command = entry(manager)
    _, result = invoke(command, capsys, "status")
    serialized = json.dumps(result)
    for value in ("prospective-owner", "prospective-profile", "synthetic-actor"):
        assert value not in serialized
    _, diagnostic = invoke(command, capsys, "access")
    assert diagnostic["decision"] == "deny"
    assert diagnostic["protected_reads_enabled"] is False
