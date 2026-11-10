"""Atomic advisory snapshots: no inferred completion or native I/O."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent import tasks
from personal_agent.tasks import TaskError, TaskStore


def store(path=":memory:", factory=sqlite3.Connection):
    result = TaskStore(sqlite3.connect(path, factory=factory))
    result.initialize()
    return result


def capture(s):
    return s.run("capture", {"title": "Synthetic", "request_id": str(uuid4()), "project": "p"})[
        "data"
    ]


def request(task, **changes):
    return {
        "task_id": task["id"],
        "handoff_id": str(uuid4()),
        "expected_revision": task["revision"],
        "request_id": str(uuid4()),
        **changes,
    }


def observation(req, **changes):
    return {
        "handoff_id": req["handoff_id"],
        "card_id": "t_1234abcd",
        "outcome": "current",
        "status": "done",
        "observed_at": 1800000000,
        "exported_revision": 1,
        **changes,
    }


def failure(code, call):
    with pytest.raises(TaskError) as exc:
        call()
    assert exc.value.code == code


def test_atomic_advisory_never_infers_completion_and_all_read_paths():
    s = store()
    task = capture(s)
    req = request(task)
    data = s.sync_native(req, lambda current: observation(req))["data"]
    assert data["revision"] == 2
    assert data["native_progress"] == observation(req)
    for field in ("state", "work_status", "progress_note", "dependencies", "title", "details"):
        assert data[field] == task[field]
    assert data["state"] == "captured"
    assert s.run("get", {"task_id": task["id"]})["data"] == data
    for op, payload in (("list", {}), ("search", {"query": "Synthetic"}), ("ready", {})):
        assert s.run(op, payload)["data"]["items"][0]["native_progress"] == observation(req)
    assert (
        s.run("history", {"task_id": task["id"]})["data"]["items"][-1]["operation"] == "native_sync"
    )
    failure("invalid_request", lambda: s.run("native_sync", req))


def test_receipt_first_even_after_terminal_and_changed_native():
    s = store()
    task = capture(s)
    req = request(task)
    original = s.sync_native(req, lambda _: observation(req))
    s.run(
        "complete",
        {"task_id": task["id"], "expected_revision": 2, "request_id": "done", "note": "explicit"},
    )

    def never(_):
        raise AssertionError("Replay must not observe native or ledger")

    assert s.sync_native(req, never) == {**original, "replayed": True}
    failure(
        "idempotency_conflict", lambda: s.sync_native({**req, "handoff_id": str(uuid4())}, never)
    )
    failure(
        "terminal_state",
        lambda: s.sync_native({**req, "expected_revision": 3, "request_id": "new"}, never),
    )


def test_cas_and_request_namespace_collision_precede_callback():
    s = store()
    task = capture(s)
    req = request(task)

    def never(_):
        raise AssertionError("callback must not run")

    failure("revision_conflict", lambda: s.sync_native({**req, "expected_revision": 2}, never))
    s.run("capture", {"title": "Other", "request_id": req["request_id"]})
    failure("idempotency_conflict", lambda: s.sync_native(req, never))


@pytest.mark.parametrize("stage", ["callback", "event", "commit"])
def test_atomic_rollback_preserves_previous_snapshot(stage):
    class Conn(sqlite3.Connection):
        fail_commit = False

        def execute(self, sql, *args):
            if sql == "COMMIT" and self.fail_commit:
                raise sqlite3.OperationalError("synthetic failure")
            return super().execute(sql, *args)

    s = store(factory=Conn)
    task = capture(s)
    req = request(task)
    first = s.sync_native(req, lambda _: observation(req))["data"]
    newer = request(first)

    def callback(_):
        if stage == "callback":
            raise RuntimeError("native unavailable")
        return observation(newer, status="running")

    if stage == "event":
        s._record_event = lambda *args: (_ for _ in ()).throw(RuntimeError("crash"))
    if stage == "commit":
        s._connection.fail_commit = True
    with pytest.raises((RuntimeError, TaskError)):
        s.sync_native(newer, callback)
    s._connection.fail_commit = False
    assert s.run("get", {"task_id": task["id"]})["data"] == first
    assert (
        s._connection.execute(
            "SELECT count(*) FROM receipts WHERE request_id=?", (newer["request_id"],)
        ).fetchone()[0]
        == 0
    )


def test_failure_snapshot_and_replacement_are_advisory():
    s = store()
    task = capture(s)
    first = request(task)
    data = s.sync_native(first, lambda _: observation(first))["data"]
    newer = request(data)
    data = s.sync_native(newer, lambda _: observation(newer, outcome="missing", status=None))[
        "data"
    ]
    assert data["native_progress"]["handoff_id"] == newer["handoff_id"]
    assert data["state"] == "captured"
    assert s._connection.execute("SELECT count(*) FROM task_native_progress").fetchone()[0] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"card_id": None},
        {"card_id": "bad"},
        {"status": "unknown"},
        {"status": None},
        {"outcome": "missing"},
        {"outcome": "unavailable", "status": None},
        {"observed_at": True},
        {"exported_revision": 0},
        {"body": "private"},
    ],
)
def test_projection_rejects_unknown_or_private_fields(changes):
    s = store()
    task = capture(s)
    req = request(task)
    failure("invalid_request", lambda: s.sync_native(req, lambda _: observation(req, **changes)))
    assert s.run("get", {"task_id": task["id"]})["data"] == task


def test_two_concurrent_same_request_observes_only_once(tmp_path):
    path = tmp_path / "tasks.db"
    s = store(path)
    req = request(capture(s))
    barrier = Barrier(2)
    calls = []

    def work(_):
        other = store(path)
        barrier.wait()

        def observe(task):
            calls.append(task["revision"])
            return observation(req)

        try:
            return other.sync_native(req, observe)
        finally:
            other._connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, (0, 1)))
    assert calls == [1]
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert results[0]["data"] == results[1]["data"]


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_exact_schema_migration_preserves_history(version):
    conn = sqlite3.connect(":memory:")
    for sql in getattr(tasks, f"_SCHEMA_V{version}").values():
        conn.execute(sql)
    conn.execute(f"PRAGMA application_id={tasks._APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version={version}")
    task_id = str(uuid4())
    conn.execute(
        "INSERT INTO tasks(id,title,details,state,revision,created_at,updated_at,source) "
        "VALUES (?,'old','','captured',1,'then','then','local_cli')",
        (task_id,),
    )
    conn.execute("INSERT INTO events VALUES (?,1,'capture','then')", (task_id,))
    conn.execute("INSERT INTO receipts VALUES ('old','digest','{\"historical\":true}')")
    conn.commit()
    before = {
        table: conn.execute(f"SELECT * FROM {table}").fetchall()
        for table in ("tasks", "events", "receipts")
    }
    s = TaskStore(conn)
    s.initialize()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    assert s.run("get", {"task_id": task_id})["data"]["native_progress"] is None
    for table in ("events", "receipts"):
        assert conn.execute(f"SELECT * FROM {table}").fetchall() == before[table]
    assert (
        conn.execute("SELECT * FROM tasks").fetchone()[: len(before["tasks"][0])]
        == before["tasks"][0]
    )


@pytest.mark.parametrize(
    "status",
    ["triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"],
)
def test_all_native_statuses_never_transition_local_task(status):
    s = store()
    task = capture(s)
    req = request(task)
    data = s.sync_native(req, lambda _: observation(req, status=status))["data"]
    assert data["state"] == "captured" and data["work_status"] == "ready"
    assert data["native_progress"]["status"] == status


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_migration_failure_rolls_back_every_table(version):
    class Failing(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("CREATE TABLE task_native_progress"):
                raise sqlite3.OperationalError("synthetic migration failure")
            return super().execute(sql, *args)

    conn = sqlite3.connect(":memory:", factory=Failing)
    for sql in getattr(tasks, f"_SCHEMA_V{version}").values():
        conn.execute(sql)
    conn.execute(f"PRAGMA application_id={tasks._APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version={version}")
    conn.commit()
    before = conn.execute("SELECT * FROM sqlite_master").fetchall()
    failure("storage_error", lambda: TaskStore(conn).initialize())
    assert conn.execute("SELECT * FROM sqlite_master").fetchall() == before
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_corrupt_advisory_refuses_read_and_new_mutation():
    s = store()
    task = capture(s)
    req = request(task)
    s.sync_native(req, lambda _: observation(req))
    s._connection.execute("UPDATE task_native_progress SET observation='{}'")
    s._connection.commit()
    failure("storage_corrupt", lambda: s.run("get", {"task_id": task["id"]}))
    failure(
        "storage_corrupt",
        lambda: s.sync_native(
            {**req, "expected_revision": 2, "request_id": "new"}, lambda _: observation(req)
        ),
    )
    # Historical replay does not consult overwritten current advisory state.
    assert s.sync_native(req, lambda _: None)["replayed"]


def test_changed_handoff_or_future_export_revision_rejected():
    s = store()
    task = capture(s)
    req = request(task)
    for changes in ({"handoff_id": str(uuid4())}, {"exported_revision": 2}):
        failure(
            "invalid_native_observation",
            lambda changes=changes: s.sync_native(req, lambda _: observation(req, **changes)),
        )
    assert s.run("get", {"task_id": task["id"]})["data"] == task


def test_failure_outcomes_null_status_and_keep_identity():
    from personal_agent.task_native_sync import FAILURES

    s = store()
    task = capture(s)
    for outcome in sorted(FAILURES):
        req = request(task)
        task = s.sync_native(
            req, lambda _, outcome=outcome, req=req: observation(req, outcome=outcome, status=None)
        )["data"]
        assert task["native_progress"]["card_id"] == "t_1234abcd"
        assert task["native_progress"]["status"] is None
        assert task["state"] == "captured"


def test_durable_replay_after_restart_without_observer(tmp_path):
    path = tmp_path / "tasks.db"
    s = store(path)
    task = capture(s)
    req = request(task)
    original = s.sync_native(req, lambda _: observation(req))
    s._connection.close()  # Simulated caller loses its result after durable commit.
    reopened = store(path)
    assert reopened.sync_native(req, None) == {**original, "replayed": True}


def test_agenda_snapshot_includes_native_progress():
    s = store()
    task = s.run("capture", {"title": "Dated", "due_date": "2026-11-07", "request_id": "dated"})[
        "data"
    ]
    req = request(task)
    s.sync_native(req, lambda _: observation(req))
    assert s.run("agenda", {"on": "2026-11-07"})["data"]["items"][0][
        "native_progress"
    ] == observation(req)


@pytest.mark.parametrize("boundary", ["before", "after"])
def test_abrupt_process_exit_at_sync_commit(tmp_path, boundary):
    """Real process death, rather than an exception that runs Python rollback."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    path = tmp_path / "crash.sqlite3"
    s = store(path)
    task = capture(s)
    req = request(task)
    proposed = observation(req)
    s._connection.close()
    script = r"""
import json, os, sqlite3, sys
from personal_agent.tasks import TaskStore
path, boundary, request_json, observation_json = sys.argv[1:]
class CrashConnection(sqlite3.Connection):
    armed = False
    def execute(self, sql, *args):
        if self.armed and sql == "COMMIT":
            if boundary == "before":
                os._exit(71)
            result = super().execute(sql, *args)
            os._exit(72)
        return super().execute(sql, *args)
conn = sqlite3.connect(path, factory=CrashConnection)
store = TaskStore(conn)
store.initialize()
conn.armed = True
store.sync_native(json.loads(request_json), lambda _: json.loads(observation_json))
raise AssertionError("commit crash hook did not fire")
"""
    home = tmp_path / "child-home"
    home.mkdir(mode=0o700)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            script,
            str(path),
            boundary,
            json.dumps(req),
            json.dumps(proposed),
        ],
        env={
            "HOME": str(home),
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        cwd=home,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == (71 if boundary == "before" else 72), result.stderr
    recovered = store(path)
    conn = recovered._connection
    current = recovered.run("get", {"task_id": task["id"]})["data"]
    events = conn.execute(
        "SELECT revision,operation FROM events WHERE task_id=? ORDER BY revision", (task["id"],)
    ).fetchall()
    receipts = conn.execute(
        "SELECT receipt FROM receipts WHERE request_id=?", (req["request_id"],)
    ).fetchall()
    calls = []

    def callback(current_task):
        calls.append(current_task["revision"])
        if boundary == "after":
            raise AssertionError("committed retry must not read native state")
        return proposed

    if boundary == "before":
        assert current == task
        assert events == [(1, "capture")]
        assert receipts == []
        assert conn.execute("SELECT count(*) FROM task_native_progress").fetchone()[0] == 0
    else:
        assert current["revision"] == 2
        assert current["native_progress"] == proposed
        assert events == [(1, "capture"), (2, "native_sync")]
        assert len(receipts) == 1
        assert json.loads(receipts[0][0]) == current
    replay = recovered.sync_native(req, callback)
    assert replay["replayed"] is (boundary == "after")
    assert calls == ([1] if boundary == "before" else [])
    if boundary == "after":
        assert replay["data"] == json.loads(receipts[0][0])
    assert replay["data"]["revision"] == 2
    assert conn.execute("SELECT count(*) FROM task_native_progress").fetchone()[0] == 1
    assert (
        conn.execute("SELECT count(*) FROM events WHERE task_id=?", (task["id"],)).fetchone()[0]
        == 2
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM receipts WHERE request_id=?", (req["request_id"],)
        ).fetchone()[0]
        == 1
    )
    recovered._connection.close()
