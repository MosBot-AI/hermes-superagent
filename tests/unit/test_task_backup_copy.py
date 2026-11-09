"""Explicit historical text recovery never rolls back state or authority."""

import sqlite3
from contextlib import contextmanager

import pytest
from test_task_backup import path, source

from personal_agent import task_backup as backup
from personal_agent.tasks import TaskError, TaskStore


@pytest.fixture
def home(tmp_path, monkeypatch):
    from personal_agent import PLUGIN_ID

    monkeypatch.setattr(backup, "current_profile_home", lambda: tmp_path)
    (tmp_path / "plugin-data" / PLUGIN_ID).mkdir(parents=True, mode=0o700)
    return tmp_path


@pytest.fixture(autouse=True)
def local_store(monkeypatch):
    @contextmanager
    def open_store(home):
        connection = sqlite3.connect(
            path(home).parent.parent / "tasks.sqlite3", isolation_level=None
        )
        store = TaskStore(connection)
        store.initialize()
        try:
            yield store
        finally:
            connection.close()

    monkeypatch.setattr(backup, "open_task_store", open_store)


def prepare(home):
    connection, store, plan = source(home)
    task = plan["data"]["items"][0]
    store.run(
        "complete",
        {
            "task_id": task["id"],
            "expected_revision": 1,
            "note": "Finished before backup",
            "request_id": "complete",
        },
    )
    digest = backup.task_backup(home, "create", "before-upgrade")["sha256"]
    return connection, store, task["id"], digest


def test_preview_is_pure_even_without_live_store(home, monkeypatch):
    connection, _, task_id, digest = prepare(home)
    connection.close()
    live = path(home).parent.parent / "tasks.sqlite3"
    live.unlink()
    before = path(home).read_bytes()
    monkeypatch.setattr(
        backup, "open_task_store", lambda *args: pytest.fail("preview opened store")
    )
    preview = backup.task_backup(
        home, "recover-preview", "before-upgrade", sha256=digest, task_id=task_id
    )
    assert preview["copy_fields"] == {"title": "First", "details": "", "project": "Synthetic"}
    assert "recovery" not in preview and not live.exists()
    assert path(home).read_bytes() == before


def test_copy_is_new_record_and_replay_preserves_later_edits(home):
    connection, store, old_id, digest = prepare(home)
    old = store.run("get", {"task_id": old_id})["data"]
    args = dict(sha256=digest, task_id=old_id, request_id="recover-1")
    result = backup.task_backup(home, "recover-copy", "before-upgrade", **args)["recovery"]
    new = result["data"]
    assert new["id"] != old_id and new["state"] == "captured" and new["revision"] == 1
    assert new["resolved_at"] is None and new["resolution_note"] is None
    assert new["progress_note"] == "" and new["dependencies"] == []
    assert store.run("get", {"task_id": old_id})["data"] == old
    store.run(
        "complete",
        {
            "task_id": new["id"],
            "expected_revision": 1,
            "note": "New completion",
            "request_id": "new-done",
        },
    )
    replay = backup.task_backup(home, "recover-copy", "before-upgrade", **args)["recovery"]
    assert replay["replayed"] and replay["data"] == new
    assert store.run("get", {"task_id": new["id"]})["data"]["state"] == "done"
    assert connection.execute("SELECT count(*) FROM tasks").fetchone()[0] == 3
    assert (
        connection.execute(
            "SELECT operation FROM events WHERE task_id=? AND revision=1", (new["id"],)
        ).fetchone()[0]
        == "recover_copy"
    )
    connection.close()


@pytest.mark.parametrize("change", ["digest", "task", "request", "invalid_text"])
def test_invalid_or_changed_selection_does_not_mutate(home, change):
    connection, store, task_id, digest = prepare(home)
    args = dict(sha256=digest, task_id=task_id, request_id="recover-1")
    if change == "digest":
        args["sha256"] = "0" * 64
    elif change == "task":
        args["task_id"] = "00000000-0000-4000-8000-000000000000"
    elif change == "request":
        args["request_id"] = "bad key"
    else:
        snap = sqlite3.connect(path(home))
        snap.execute("UPDATE tasks SET title='' WHERE id=?", (task_id,))
        snap.commit()
        snap.close()
        args["sha256"] = backup.task_backup(home, "inspect", "before-upgrade")["sha256"]
    before = list(connection.iterdump())
    with pytest.raises(TaskError):
        backup.task_backup(home, "recover-copy", "before-upgrade", **args)
    assert list(connection.iterdump()) == before
    connection.close()


def test_changed_source_conflicts_with_same_request_key(home):
    connection, store, task_id, digest = prepare(home)
    backup.task_backup(
        home,
        "recover-copy",
        "before-upgrade",
        sha256=digest,
        task_id=task_id,
        request_id="recover-1",
    )
    other = backup.task_backup(home, "create", "later")["sha256"]
    before = list(connection.iterdump())
    with pytest.raises(TaskError, match="idempotency_conflict"):
        backup.task_backup(
            home, "recover-copy", "later", sha256=other, task_id=task_id, request_id="recover-1"
        )
    assert list(connection.iterdump()) == before
    connection.close()


def test_event_failure_rolls_back_new_task_and_receipt(home, monkeypatch):
    connection, _, task_id, digest = prepare(home)
    before = list(connection.iterdump())

    def fail(*args):
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(TaskStore, "_record_event", fail)
    with pytest.raises(RuntimeError):
        backup.task_backup(
            home,
            "recover-copy",
            "before-upgrade",
            sha256=digest,
            task_id=task_id,
            request_id="recover-1",
        )
    assert list(connection.iterdump()) == before
    connection.close()


def test_recovery_operation_is_not_a_model_action():
    from personal_agent.task_tool_contract import normalize_task_tool_request

    with pytest.raises(TaskError, match="invalid_request"):
        normalize_task_tool_request("personal_tasks_write", {"action": "recover_copy"})


def test_same_key_different_original_task_is_rejected(home):
    connection, store, task_id, digest = prepare(home)
    backup.task_backup(
        home,
        "recover-copy",
        "before-upgrade",
        sha256=digest,
        task_id=task_id,
        request_id="recover-1",
    )
    other_id = connection.execute("SELECT id FROM tasks WHERE title='Second'").fetchone()[0]
    before = list(connection.iterdump())
    with pytest.raises(TaskError, match="idempotency_conflict"):
        backup.task_backup(
            home,
            "recover-copy",
            "before-upgrade",
            sha256=digest,
            task_id=other_id,
            request_id="recover-1",
        )
    assert list(connection.iterdump()) == before
    connection.close()
