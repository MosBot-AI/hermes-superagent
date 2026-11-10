"""Synthetic local dependency graphs, migrations and transaction boundaries."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent import tasks
from personal_agent.tasks import TaskError, TaskStore


def store(path=":memory:"):
    result = TaskStore(sqlite3.connect(path))
    result.initialize()
    return result


def capture(s, project="p"):
    return s.run("capture", {"title": "Synthetic", "project": project, "request_id": str(uuid4())})[
        "data"
    ]


def change(s, op, t, **kw):
    return s.run(
        op,
        {"task_id": t["id"], "expected_revision": t["revision"], "request_id": str(uuid4()), **kw},
    )["data"]


def deps(s, t, *parents):
    return change(s, "set_dependencies", t, dependency_ids=[p["id"] for p in parents])


def error(code, fn):
    with pytest.raises(TaskError) as caught:
        fn()
    assert caught.value.code == code


def test_live_readiness_and_cancelled_blocks():
    s = store()
    a, b, c = [capture(s) for _ in range(3)]
    b = deps(s, b, a)
    assert not b["dependencies_satisfied"]
    assert [t["id"] for t in s.run("ready", {"limit": 1})["data"]["items"]] == [a["id"]]
    assert s.run("ready", {})["data"]["total_eligible"] == 2
    for op, kw in [
        ("complete", {"note": "done"}),
        ("progress", {"note": "start", "work_status": "in_progress"}),
    ]:
        error("dependencies_unsatisfied", lambda op=op, kw=kw: change(s, op, b, **kw))
    a = change(s, "complete", a, note="done")
    fresh = s.run("get", {"task_id": b["id"]})["data"]
    assert fresh["revision"] == b["revision"] and fresh["dependencies_satisfied"]
    assert fresh["dependencies"] == [{"task_id": a["id"], "revision": 2, "state": "done"}]
    b = deps(s, b, c)
    change(s, "cancel", c, note="cancelled")
    assert not s.run("get", {"task_id": b["id"]})["data"]["dependencies_satisfied"]
    change(s, "cancel", b, note="allowed")


def test_graph_and_project_guards():
    s = store()
    a, b, c = [capture(s) for _ in range(3)]
    a = deps(s, a, b)
    b = deps(s, b, c)
    error("dependency_cycle", lambda: deps(s, c, a))
    error("dependency_cycle", lambda: deps(s, c, c))
    error("invalid_request", lambda: deps(s, c, b, b))
    error("dependency_project_mismatch", lambda: deps(s, c, capture(s, "other")))
    error("dependency_project_required", lambda: deps(s, capture(s, None)))
    for t in (a, b, c):
        error("dependency_project_locked", lambda t=t: change(s, "update", t, project="new"))
    c = change(s, "cancel", c, note="cancel")
    error("dependency_project_locked", lambda: change(s, "update", b, project="new"))
    assert s.run("review", {"on": "2026-11-07"})["data"]["dependency_counts"] == {
        "satisfied": 2,
        "blocked": 2,
    }


def test_replay_sorted_and_historical():
    s = store()
    a, b, c = [capture(s) for _ in range(3)]
    payload = {
        "task_id": a["id"],
        "expected_revision": 1,
        "request_id": "same",
        "dependency_ids": [b["id"], c["id"]],
    }
    first = s.run("set_dependencies", payload)
    deps(s, first["data"])
    replay = s.run(
        "set_dependencies", {**payload, "dependency_ids": list(reversed(payload["dependency_ids"]))}
    )
    assert replay == {**first, "replayed": True}
    assert s.run("get", {"task_id": a["id"]})["data"]["dependencies"] == []
    error(
        "idempotency_conflict", lambda: s.run("set_dependencies", {**payload, "dependency_ids": []})
    )


@pytest.mark.parametrize("race", ["opposite", "start"])
def test_concurrent_graph_writers(tmp_path, race):
    path = tmp_path / "tasks.db"
    s = store(path)
    a, b = capture(s), capture(s)
    barrier = Barrier(2)

    def run(index):
        other = store(path)
        barrier.wait()
        try:
            if index == 0:
                deps(other, a, b)
            elif race == "opposite":
                deps(other, b, a)
            else:
                change(other, "progress", a, work_status="in_progress", note="start")
            return "ok"
        except TaskError as exc:
            return exc.code
        finally:
            other._connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (0, 1)))
    assert results.count("ok") == 1
    assert set(results) <= {"ok", "dependency_cycle", "revision_conflict"}


def test_rollback_graph_revision_receipt():
    s = store()
    a, b = capture(s), capture(s)
    original = s._record_event

    def fail(*args):
        raise RuntimeError("synthetic crash")

    s._record_event = fail
    with pytest.raises(RuntimeError):
        deps(s, a, b)
    s._record_event = original
    assert s.run("get", {"task_id": a["id"]})["data"] == a
    assert s._connection.execute("SELECT count(*) FROM receipts").fetchone()[0] == 2


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_exact_legacy_migration(version):
    conn = sqlite3.connect(":memory:")
    schema = getattr(tasks, f"_SCHEMA_V{version}")
    for sql in schema.values():
        conn.execute(sql)
    conn.execute(f"PRAGMA application_id={tasks._APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version={version}")
    task_id = str(uuid4())
    conn.execute(
        "INSERT INTO tasks(id,title,details,state,revision,created_at,updated_at,source) "
        "VALUES (?, 'legacy','detail','captured',1,'then','then','local_cli')",
        (task_id,),
    )
    conn.execute("INSERT INTO events VALUES (?,1,'capture','then')", (task_id,))
    conn.execute("INSERT INTO receipts VALUES ('old','digest','{\"legacy\":true}')")
    conn.commit()
    before = {
        table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in ("events", "receipts")
    }
    s = TaskStore(conn)
    s.initialize()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
    assert s.run("get", {"task_id": task_id})["data"]["dependencies"] == []
    for table, rows in before.items():
        assert conn.execute(f"SELECT * FROM {table}").fetchall() == rows


@pytest.mark.parametrize(
    "op,payload",
    [
        ("get", {}),
        ("list", {}),
        ("search", {"query": "Synthetic"}),
        ("agenda", {"on": "2026-11-07"}),
        ("ready", {}),
    ],
)
def test_reads_use_snapshot(op, payload):
    s = store()
    a = capture(s)
    if op == "get":
        payload = {"task_id": a["id"]}
    trace = []
    s._connection.set_trace_callback(trace.append)
    s.run(op, payload)
    assert trace[0] == "BEGIN" and trace[-1] == "COMMIT"


def test_corrupt_reference_fails_closed():
    s = store()
    a, b = capture(s), capture(s)
    deps(s, a, b)
    s._connection.execute("DELETE FROM tasks WHERE id=?", (b["id"],))
    s._connection.commit()
    for op, request in [
        ("get", {"task_id": a["id"]}),
        ("ready", {}),
        ("review", {"on": "2026-11-07"}),
    ]:
        error("storage_corrupt", lambda op=op, request=request: s.run(op, request))


def test_in_progress_cannot_add_unsatisfied():
    s = store()
    a, b = capture(s), capture(s)
    a = change(s, "progress", a, work_status="in_progress", note="start")
    error("dependencies_unsatisfied", lambda: deps(s, a, b))
    b = change(s, "complete", b, note="done")
    assert deps(s, a, b)["dependencies_satisfied"]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_migration_rollback(version):
    class Failing(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql.startswith("CREATE TABLE task_dependencies"):
                raise sqlite3.OperationalError("synthetic migration crash")
            return super().execute(sql, *args)

    conn = sqlite3.connect(":memory:", factory=Failing)
    for sql in getattr(tasks, f"_SCHEMA_V{version}").values():
        conn.execute(sql)
    conn.execute(f"PRAGMA application_id={tasks._APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version={version}")
    conn.commit()
    before = conn.execute("SELECT * FROM sqlite_master").fetchall()
    error("storage_error", lambda: TaskStore(conn).initialize())
    assert conn.execute("SELECT * FROM sqlite_master").fetchall() == before
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_read_snapshot_resists_concurrent_completion(tmp_path):
    path = tmp_path / "snapshot.db"
    s = store(path)
    s._connection.execute("PRAGMA journal_mode=WAL")
    a, b = capture(s), capture(s)
    a = deps(s, a, b)
    other = store(path)
    fired = False

    def trace(sql):
        nonlocal fired
        # The task SELECT has established the snapshot before dependency reads.
        if "LEFT JOIN tasks t ON t.id=d.task_id" in sql and not fired:
            fired = True
            change(other, "complete", b, note="done")

    s._connection.set_trace_callback(trace)
    old = s.run("get", {"task_id": a["id"]})["data"]
    assert fired and not old["dependencies_satisfied"]
    s._connection.set_trace_callback(None)
    assert s.run("get", {"task_id": a["id"]})["data"]["dependencies_satisfied"]


def test_ready_filters_pagination_and_progress():
    s = store()
    a, b, c = [capture(s) for _ in range(3)]
    capture(s, "other")
    free = capture(s, None)
    first = s.run("ready", {"project": "p", "limit": 1})["data"]
    assert first["items"] == [a] and first["total_eligible"] == 3
    second = s.run("ready", {"project": "p", "after": first["next_cursor"]})["data"]
    assert second["items"] == [b, c] and not second["has_more"]
    change(s, "progress", b, work_status="waiting", note="waiting")
    assert s.run("ready", {"project": "p"})["data"]["total_eligible"] == 2
    assert s.run("ready", {"unassigned": True})["data"]["items"] == [free]
    error("invalid_cursor", lambda: s.run("ready", {"after": str(uuid4())}))


@pytest.mark.parametrize(
    "ids", [None, "bad", ["bad"], [str(uuid4())] * 2, [str(uuid4()) for _ in range(21)]]
)
def test_dependency_payload_bounds(ids):
    s = store()
    a = capture(s)
    error("invalid_request", lambda: change(s, "set_dependencies", a, dependency_ids=ids))
