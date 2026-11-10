"""Synthetic date-only agenda and atomic legacy-schema migration coverage."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent.tasks import TaskError, TaskStore, validate_request

# Independent copy of the shipped v1 DDL: migration tests must not follow v2 edits.
V1_SCHEMA = {
    "tasks": """CREATE TABLE tasks (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE, title TEXT NOT NULL, details TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('captured','done','cancelled')),
        revision INTEGER NOT NULL CHECK(revision >= 1),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL, resolved_at TEXT,
        resolution_note TEXT, source TEXT NOT NULL CHECK(source = 'local_cli'))""",
    "receipts": """CREATE TABLE receipts (
        request_id TEXT PRIMARY KEY NOT NULL, digest TEXT NOT NULL, receipt TEXT NOT NULL)""",
    "events": """CREATE TABLE events (
        task_id TEXT NOT NULL, revision INTEGER NOT NULL,
        operation TEXT NOT NULL, timestamp TEXT NOT NULL,
        PRIMARY KEY(task_id, revision))""",
}
APPLICATION_ID = 0x5041544B


def expect_error(code, callback):
    with pytest.raises(TaskError) as caught:
        callback()
    assert caught.value.code == code
    return caught.value


@pytest.fixture
def store():
    conn = sqlite3.connect(":memory:")
    result = TaskStore(conn)
    result.initialize()
    yield result
    conn.close()


def capture(store, due_date="2024-02-29", key=None):
    payload = {"title": "Synthetic agenda", "request_id": key or str(uuid4())}
    if due_date is not None:
        payload["due_date"] = due_date
    return store.run("capture", payload)["data"]


def change(store, task, operation="update", key=None, **fields):
    return store.run(
        operation,
        {
            "task_id": task["id"],
            "expected_revision": task["revision"],
            "request_id": key or str(uuid4()),
            **fields,
        },
    )


def seed_v1(conn):
    """Seed legacy receipts, including replay of an old revision after completion."""
    for statement in V1_SCHEMA.values():
        conn.execute(statement)
    conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    conn.execute("PRAGMA user_version = 1")
    history = []
    for index in range(2):
        task_id = str(uuid4())
        task = {
            "id": task_id,
            "title": f"Synthetic legacy {index}",
            "details": "",
            "state": "captured",
            "revision": 1,
            "created_at": "2026-01-01T12:00:00.000000+00:00",
            "updated_at": "2026-01-01T12:00:00.000000+00:00",
            "resolved_at": None,
            "resolution_note": None,
            "source": "local_cli",
        }
        conn.execute(
            "INSERT INTO tasks (id,title,details,state,revision,created_at,updated_at,"
            "resolved_at,resolution_note,source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            tuple(task.values()),
        )
        operations = [
            ("capture", {"title": task["title"], "details": "", "request_id": f"legacy-{index}"})
        ]
        if index == 1:
            operations.extend(
                [
                    (
                        "update",
                        {
                            "task_id": task_id,
                            "expected_revision": 1,
                            "request_id": "legacy-edit",
                            "details": "Synthetic edited",
                        },
                    ),
                    (
                        "complete",
                        {
                            "task_id": task_id,
                            "expected_revision": 2,
                            "request_id": "legacy-done",
                            "note": "Synthetic complete",
                        },
                    ),
                ]
            )
        for operation, request in operations:
            if operation == "update":
                task = {**task, "details": request["details"], "revision": 2}
            elif operation == "complete":
                task = {
                    **task,
                    "state": "done",
                    "revision": 3,
                    "resolved_at": task["updated_at"],
                    "resolution_note": request["note"],
                }
            digest = hashlib.sha256(
                json.dumps(
                    [operation, {k: v for k, v in request.items() if k != "request_id"}],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ).hexdigest()
            conn.execute(
                "INSERT INTO receipts VALUES (?,?,?)",
                (request["request_id"], digest, json.dumps(task, ensure_ascii=True)),
            )
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?)",
                (task_id, task["revision"], operation, task["updated_at"]),
            )
            history.append((operation, request, dict(task)))
        conn.execute(
            "UPDATE tasks SET details=?,state=?,revision=?,resolved_at=?,resolution_note=? "
            "WHERE id=?",
            (
                task["details"],
                task["state"],
                task["revision"],
                task["resolved_at"],
                task["resolution_note"],
                task_id,
            ),
        )
    conn.commit()
    return history


def schema(conn):
    return conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' ORDER BY name"
    ).fetchall()


def snapshot(conn):
    return {
        "schema": schema(conn),
        "version": conn.execute("PRAGMA user_version").fetchone()[0],
        "app": conn.execute("PRAGMA application_id").fetchone()[0],
        **{
            table: conn.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("tasks", "events", "receipts", "sqlite_sequence")
        },
    }


@pytest.mark.parametrize("value", ["0001-01-01", "9999-12-31", "2000-02-29", "2024-02-29"])
def test_valid_dates(store, value):
    task = capture(store, value)
    assert task["due_date"] == value
    assert store.run("agenda", {"on": value})["data"]["items"] == [task]
    assert validate_request("agenda", {"on": value}) == {
        "on": value,
        "limit": 20,
        "after": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        20240229,
        1.0,
        [],
        {},
        "",
        "0000-01-01",
        "10000-01-01",
        "1900-02-29",
        "2023-02-29",
        "2024-04-31",
        "2024-00-01",
        "2024-13-01",
        "2024-01-00",
        "2024-01-32",
        "2024-2-29",
        "20240229",
        "2024-W09-4",
        "tomorrow",
        "2024-02-29T00:00:00Z",
        "2024-02-29+00:00",
        " 2024-02-29",
        "2024-02-29 ",
        "2024-02-29\n",
        "2024-02-29\x00",
        "\u202e2024-02-29",
        "２０２４-02-29",
        "٢٠٢٤-02-29",
    ],
)
def test_invalid_dates_before_sql(store, value):
    traced = []
    store._connection.set_trace_callback(traced.append)
    expect_error(
        "invalid_request",
        lambda: store.run("capture", {"title": "x", "request_id": "bad", "due_date": value}),
    )
    expect_error("invalid_request", lambda: store.run("agenda", {"on": value}))
    if value is not None:
        expect_error(
            "invalid_request",
            lambda: store.run(
                "update",
                {
                    "task_id": str(uuid4()),
                    "expected_revision": 1,
                    "request_id": "bad-edit",
                    "due_date": value,
                },
            ),
        )
    assert traced == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"on": "2024-02-29", "state": "all"},
        {"on": "2024-02-29", "limit": False},
        {"on": "2024-02-29", "limit": 0},
        {"on": "2024-02-29", "limit": 101},
        {"on": "2024-02-29", "limit": 1.0},
        {"on": "2024-02-29", "after": ""},
        {"on": "2024-02-29", "after": str(uuid4()).upper()},
        {"on": "2024-02-29", "after": "00000000-0000-1000-8000-000000000001"},
    ],
)
def test_agenda_request_validation(payload):
    expect_error("invalid_request", lambda: validate_request("agenda", payload))


def test_due_date_cas_clear_and_replay(store):
    task = capture(store)
    updated = change(store, task, due_date="2024-03-01", key="move")["data"]
    assert updated["revision"] == 2
    expect_error("revision_conflict", lambda: change(store, task, due_date=None))
    cleared = change(store, updated, due_date=None, key="clear")["data"]
    assert cleared["due_date"] is None and cleared["revision"] == 3
    assert change(store, updated, due_date=None, key="clear") == {"data": cleared, "replayed": True}
    assert change(store, task, due_date="2024-03-01", key="move")["data"] == updated
    expect_error(
        "idempotency_conflict", lambda: change(store, updated, due_date="2024-03-01", key="clear")
    )
    assert store.run("agenda", {"on": "9999-12-31"})["data"]["items"] == []
    assert store.run("get", {"task_id": task["id"]})["data"] == cleared
    assert store.run("list", {})["data"]["items"] == [cleared]
    restored = change(store, cleared, due_date="0001-01-01")["data"]
    titled = change(store, restored, title="Still dated")["data"]
    assert titled["due_date"] == "0001-01-01"


@pytest.mark.parametrize("operation", ["complete", "cancel"])
def test_terminal_tasks_excluded_but_can_anchor(store, operation):
    first, second = capture(store), capture(store)
    page = store.run("agenda", {"on": "2024-02-29", "limit": 1})["data"]
    assert page["next_cursor"] == first["id"]
    done = change(store, first, operation, note="Synthetic resolved")["data"]
    assert done["due_date"] == first["due_date"]
    expect_error("terminal_state", lambda: change(store, done, due_date=None))
    assert store.run("agenda", {"on": "2024-02-29", "after": page["next_cursor"]})["data"][
        "items"
    ] == [second]


def test_agenda_order_bounded_pages_and_restart(tmp_path):
    path = tmp_path / "agenda.sqlite"
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        later = capture(store, "2025-01-01")
        same = [capture(store) for _ in range(4)]
        earlier = capture(store, "2023-12-31")
        capture(store, None)
        capture(store, "2026-01-01")
        traced = []
        conn.set_trace_callback(traced.append)
        first = store.run("agenda", {"on": "2025-01-01", "limit": 2})["data"]
        assert first["items"] == [earlier, same[0]]
        assert any("ORDER BY due_date ASC, sequence ASC LIMIT 3" in sql for sql in traced)
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        second = store.run(
            "agenda", {"on": "2025-01-01", "limit": 2, "after": first["next_cursor"]}
        )["data"]
        third = store.run(
            "agenda", {"on": "2025-01-01", "limit": 2, "after": second["next_cursor"]}
        )["data"]
        assert second["items"] == same[1:3]
        assert third["items"] == [same[3], later]
        assert first["has_more"] and second["has_more"]
        assert not third["has_more"] and third["next_cursor"] is None
        assert len(store.run("agenda", {"on": "9999-12-31", "limit": 100})["data"]["items"]) == 7


def test_invalid_cursors_and_live_edits(store):
    undated = capture(store, None)
    future = capture(store, "2025-01-01")
    for task_id in (str(uuid4()), undated["id"], future["id"]):
        expect_error(
            "invalid_cursor",
            lambda task_id=task_id: store.run("agenda", {"on": "2024-02-29", "after": task_id}),
        )
    first = capture(store)
    second = capture(store)
    change(store, first, due_date="2024-02-28")
    assert store.run("agenda", {"on": "2024-02-29", "after": first["id"]})["data"]["items"] == [
        second
    ]
    changed = store.run("get", {"task_id": first["id"]})["data"]
    change(store, changed, due_date=None)
    expect_error(
        "invalid_cursor",
        lambda: store.run("agenda", {"on": "2024-02-29", "after": first["id"]}),
    )


def test_migration_preserves_records_receipts_and_legacy_retries(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        history = seed_v1(conn)
        before = snapshot(conn)
        store = TaskStore(conn)
        store.initialize()
        after = snapshot(conn)
        assert after["version"] == 8 and after["app"] == APPLICATION_ID
        for table in ("events", "receipts", "sqlite_sequence"):
            assert after[table] == before[table]
        assert after["tasks"] == [
            (*row, None, None, "ready", "", None, "normal", None) for row in before["tasks"]
        ]
        assert "due_date" not in validate_request(
            "capture", {"title": "Synthetic", "request_id": "omitted"}
        )
        for operation, request, receipt in history:
            assert store.run(operation, request) == {"data": receipt, "replayed": True}
        # An omitted legacy details argument still normalizes to the same old digest.
        operation, request, receipt = history[0]
        assert store.run(operation, {k: v for k, v in request.items() if k != "details"}) == {
            "data": receipt,
            "replayed": True,
        }
        task = store.run("get", {"task_id": receipt["id"]})["data"]
        assert task == {
            **receipt,
            "due_date": None,
            "project": None,
            "work_status": "ready",
            "progress_note": "",
            "progress_updated_at": None,
            "dependencies": [],
            "dependencies_satisfied": True,
            "unsatisfied_dependency_count": 0,
            "native_progress": None,
            "priority": "normal",
            "follow_up_on": None,
        }
        change(store, task, due_date="2024-02-29")
        with sqlite3.connect(":memory:") as fresh:
            TaskStore(fresh).initialize()
            assert schema(conn) == schema(fresh)
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        assert store.run("capture", history[0][1])["data"] == history[0][2]
        assert len(store.run("agenda", {"on": "2024-02-29"})["data"]["items"]) == 1


class MigrationFailure(sqlite3.Connection):
    fail_at = None

    def execute(self, sql, parameters=()):
        if self.fail_at is not None and sql.startswith(self.fail_at):
            raise sqlite3.OperationalError("Synthetic private migration failure")
        return super().execute(sql, parameters)


@pytest.mark.parametrize("fail_at", ["ALTER TABLE", "PRAGMA user_version = 8", "COMMIT"])
def test_migration_failure_atomic_retry(tmp_path, fail_at):
    path = tmp_path / "failure.sqlite"
    with sqlite3.connect(path, factory=MigrationFailure) as conn:
        history = seed_v1(conn)
        before = snapshot(conn)
        original_bytes = path.read_bytes()
        conn.fail_at = fail_at
        store = TaskStore(conn)
        error = expect_error("storage_error", store.initialize)
        assert "private" not in str(error)
        assert not conn.in_transaction
        assert snapshot(conn) == before
        assert path.read_bytes() == original_bytes
        expect_error("not_initialized", lambda: store.run("agenda", {"on": "2024-02-29"}))
        conn.fail_at = None
        store.initialize()
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
        assert store.run("capture", history[0][1])["replayed"]


@pytest.mark.parametrize("kind", ["foreign", "newer", "modified", "extra_index", "extra_trigger"])
def test_migration_refuses_unrecognized_schema_unchanged(tmp_path, kind):
    path = tmp_path / "reject.sqlite"
    with sqlite3.connect(path) as conn:
        seed_v1(conn)
        if kind == "foreign":
            conn.execute("PRAGMA application_id = 123")
        elif kind == "newer":
            conn.execute("PRAGMA user_version = 3")
        elif kind == "modified":
            conn.execute("ALTER TABLE tasks ADD COLUMN unexpected TEXT")
        elif kind == "extra_index":
            conn.execute("CREATE INDEX extra ON tasks(title)")
        else:
            conn.execute("CREATE TRIGGER extra AFTER INSERT ON tasks BEGIN SELECT 1; END")
    before = path.read_bytes()
    with sqlite3.connect(path) as conn:
        expect_error(
            "foreign_database" if kind == "foreign" else "unsupported_schema",
            TaskStore(conn).initialize,
        )
        assert not conn.in_transaction
    assert path.read_bytes() == before


def test_concurrent_migration_runs_once(tmp_path):
    path = tmp_path / "concurrent.sqlite"
    with sqlite3.connect(path) as conn:
        history = seed_v1(conn)
    barrier = Barrier(2)

    def initialize(_):
        with sqlite3.connect(path, timeout=5) as conn:
            traced = []
            conn.set_trace_callback(traced.append)
            store = TaskStore(conn)
            barrier.wait(timeout=10)
            store.initialize()
            assert store.run("capture", history[0][1])["replayed"]
            return sum(sql.startswith("ALTER TABLE") for sql in traced)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(initialize, range(2))) == 7
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 8
        assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == len(history)


def test_dated_capture_replay_and_bounded_default(store):
    request = {
        "title": "Synthetic dated replay",
        "request_id": "dated-replay",
        "due_date": "2024-02-29",
    }
    original = store.run("capture", request)["data"]
    assert store.run("capture", request) == {"data": original, "replayed": True}
    expect_error(
        "idempotency_conflict",
        lambda: store.run("capture", {**request, "due_date": "2024-03-01"}),
    )
    for _ in range(100):
        capture(store)
    traced = []
    store._connection.set_trace_callback(traced.append)
    default = store.run("agenda", {"on": "2024-02-29"})["data"]
    maximum = store.run("agenda", {"on": "2024-02-29", "limit": 100})["data"]
    assert len(default["items"]) == 20 and default["has_more"]
    assert len(maximum["items"]) == 100 and maximum["has_more"]
    assert any(sql.endswith("LIMIT 21") for sql in traced)
    assert any(sql.endswith("LIMIT 101") for sql in traced)
    assert all(sql.startswith("SELECT") or sql in ("BEGIN", "COMMIT") for sql in traced)


def test_due_date_write_failure_rolls_back():
    with sqlite3.connect(":memory:", factory=MigrationFailure) as conn:
        store = TaskStore(conn)
        store.initialize()
        task = capture(store)
        before = snapshot(conn)
        conn.fail_at = "INSERT INTO receipts"
        expect_error("storage_error", lambda: change(store, task, due_date=None, key="clear"))
        assert snapshot(conn) == before
        conn.fail_at = None
        assert change(store, task, due_date=None, key="clear")["data"]["due_date"] is None
