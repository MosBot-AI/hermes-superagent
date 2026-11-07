"""Synthetic-only local inbox validation, isolation, and transaction tests."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent.tasks import TaskError, TaskStore, validate_request


@pytest.fixture
def store():
    connection = sqlite3.connect(":memory:")
    result = TaskStore(connection)
    result.initialize()
    yield result
    connection.close()


def capture(store, key="first"):
    return store.run("capture", {"title": "Synthetic task", "request_id": key})["data"]


def mutation(task, key="change", **extra):
    return {
        "task_id": task["id"],
        "expected_revision": task["revision"],
        "request_id": key,
        **extra,
    }


def assert_error(code, callable_):
    with pytest.raises(TaskError) as caught:
        callable_()
    assert caught.value.code == code
    assert "Synthetic" not in str(caught.value)
    return caught.value


@pytest.mark.parametrize(
    "operation,payload",
    [
        ("unknown", {}),
        ("capture", {}),
        ("capture", []),
        ("capture", {"title": "x", "request_id": "ok", "unknown": 1}),
        ("get", {"task_id": "not-an-id"}),
        ("get", {"task_id": str(uuid4()).upper()}),
        ("update", {"task_id": str(uuid4()), "request_id": "x", "expected_revision": 1}),
        ("complete", {"task_id": str(uuid4()), "request_id": "x", "expected_revision": 1}),
        (
            "cancel",
            {"task_id": str(uuid4()), "request_id": "x", "expected_revision": 1, "note": ""},
        ),
        ("list", {"state": "running"}),
        ("list", {"state": []}),
        ("list", {"after": "bad"}),
        ("list", {"limit": True}),
        ("list", {"limit": 0}),
        ("list", {"limit": 101}),
        ("list", {"limit": 1.0}),
        ("list", {"extra": 1}),
    ],
)
def test_invalid_requests(operation, payload):
    assert_error("invalid_request", lambda: validate_request(operation, payload))


@pytest.mark.parametrize(
    "title",
    [None, True, "", " ", "x" * 241, "a\nb", "a\tb", "a\x00b", "a\u202eb", "a\u2066b", "a\ud800b"],
)
def test_title_validation(title):
    assert_error(
        "invalid_request",
        lambda: validate_request("capture", {"title": title, "request_id": "test"}),
    )


@pytest.mark.parametrize("key", [None, True, "", "x" * 129, "hello world", "é", "a\nb"])
def test_request_key_validation(key):
    assert_error(
        "invalid_request",
        lambda: validate_request("capture", {"title": "Synthetic", "request_id": key}),
    )


@pytest.mark.parametrize("revision", [True, None, 0, -1, 1.0, "1", 2**63])
def test_revision_validation(revision):
    assert_error(
        "invalid_request",
        lambda: validate_request(
            "update",
            {
                "task_id": str(uuid4()),
                "request_id": "x",
                "expected_revision": revision,
                "details": "",
            },
        ),
    )


@pytest.mark.parametrize(
    "field,operation,maximum",
    [
        ("details", "capture", 5000),
        ("note", "complete", 2000),
        ("note", "cancel", 2000),
    ],
)
def test_multiline_text_limits(field, operation, maximum):
    base = (
        {"title": "Synthetic", "request_id": "key"}
        if operation == "capture"
        else {"task_id": str(uuid4()), "expected_revision": 1, "request_id": "key"}
    )
    for value in [None, False, "x" * (maximum + 1), "x\rb", "x\x1bb", "x\u202eb"]:
        assert_error(
            "invalid_request",
            lambda value=value: validate_request(operation, {**base, field: value}),
        )
    assert validate_request(operation, {**base, field: "x\n\ty"})[field] == "x\n\ty"
    assert len(validate_request(operation, {**base, field: "x" * maximum})[field]) == maximum


def test_normalized_copy_and_bounds():
    request = {"title": "x" * 240, "request_id": "A_1.-"}
    normalized = validate_request("capture", request)
    assert normalized["details"] == ""
    assert "details" not in request
    assert validate_request("list", {}) == {"state": "captured", "limit": 20, "after": None}
    assert validate_request("list", {"limit": 100})["limit"] == 100


def test_lifecycle_replays_and_redacted_events(store):
    task = capture(store)
    assert task["revision"] == 1 and task["source"] == "local_cli"
    assert task["resolved_at"] is None and task["resolution_note"] is None
    request = mutation(task, title="Synthetic revised", details="Synthetic details")
    updated = store.run("update", request)["data"]
    assert updated["revision"] == 2
    completed = store.run("complete", mutation(updated, "done", note="Local operator says done"))
    assert completed["data"]["state"] == "done"
    assert completed["data"]["resolved_at"] is not None
    assert store.run("update", request) == {"data": updated, "replayed": True}
    assert store.run(
        "capture", {"title": "Synthetic task", "details": "", "request_id": "first"}
    ) == {"data": task, "replayed": True}
    assert store.run("get", {"task_id": task["id"]}) == {
        "data": completed["data"],
        "replayed": False,
    }
    assert len(store.run("list", {"state": "done"})["data"]["items"]) == 1
    rows = store._connection.execute("SELECT * FROM events").fetchall()
    assert len(rows) == 3 and all(len(row) == 4 for row in rows)
    assert all("Synthetic" not in str(row) for row in rows)


@pytest.mark.parametrize("operation", ["update", "complete", "cancel"])
def test_terminal_and_cas_rejection(store, operation):
    task = capture(store)
    done = store.run("cancel", mutation(task, "cancel", note="Local operator cancelled"))["data"]
    extra = {"details": "Synthetic"} if operation == "update" else {"note": "Synthetic note"}
    assert_error("revision_conflict", lambda: store.run(operation, mutation(task, **extra)))
    assert_error("terminal_state", lambda: store.run(operation, mutation(done, **extra)))
    assert store.run("list", {"state": "cancelled"})["data"]["items"] == [done]


def test_conflict_and_missing(store):
    capture(store)
    assert_error(
        "idempotency_conflict",
        lambda: store.run("capture", {"title": "Different synthetic", "request_id": "first"}),
    )
    assert_error("not_found", lambda: store.run("get", {"task_id": str(uuid4())}))
    assert_error(
        "not_found",
        lambda: store.run(
            "update",
            {
                "task_id": str(uuid4()),
                "expected_revision": 1,
                "request_id": "missing",
                "title": "x",
            },
        ),
    )
    assert_error("invalid_cursor", lambda: store.run("list", {"after": str(uuid4())}))


def test_pagination_creation_order(store):
    tasks = [capture(store, str(i)) for i in range(5)]
    store.run("update", mutation(tasks[0], title="Synthetic oldest updated"))
    first = store.run("list", {"state": "all", "limit": 2})["data"]
    second = store.run("list", {"state": "all", "limit": 2, "after": first["next_cursor"]})["data"]
    third = store.run("list", {"state": "all", "limit": 2, "after": second["next_cursor"]})["data"]
    assert [t["id"] for p in [first, second, third] for t in p["items"]] == [
        t["id"] for t in reversed(tasks)
    ]
    assert first["has_more"] and second["has_more"]
    assert third["next_cursor"] is None and not third["has_more"]


class FailingConnection(sqlite3.Connection):
    fail_receipt = False

    def execute(self, sql, parameters=()):
        if self.fail_receipt and sql.startswith("INSERT INTO receipts"):
            raise sqlite3.OperationalError("Synthetic private path /do-not-echo")
        return super().execute(sql, parameters)


def test_full_rollback():
    conn = sqlite3.connect(":memory:", factory=FailingConnection)
    store = TaskStore(conn)
    store.initialize()
    conn.fail_receipt = True
    error = assert_error("storage_error", lambda: capture(store))
    assert "do-not-echo" not in str(error)
    assert not conn.in_transaction
    for table in ["tasks", "events", "receipts"]:
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    conn.fail_receipt = False
    task = capture(store)
    conn.fail_receipt = True
    assert_error("storage_error", lambda: store.run("complete", mutation(task, note="Synthetic")))
    assert store.run("get", {"task_id": task["id"]})["data"] == task
    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    conn.close()


def test_schema_refusal_and_reopen(tmp_path):
    path = tmp_path / "owned.sqlite"
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        task = capture(store)
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        assert store.run("get", {"task_id": task["id"]})["data"] == task
        conn.execute("PRAGMA user_version = 5")
        assert_error("unsupported_schema", store.initialize)
        conn.execute("PRAGMA user_version = 2")
        conn.execute("CREATE TABLE foreign_table (x)")
        assert_error("unsupported_schema", store.initialize)
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE foreign_table (x)")
        assert_error("foreign_database", TaskStore(conn).initialize)
        assert conn.execute("PRAGMA application_id").fetchone()[0] == 0
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"Synthetic corruption" * 100)
    with sqlite3.connect(corrupt) as conn:
        assert_error("storage_corrupt", TaskStore(conn).initialize)


def test_invalid_before_any_sql_and_uninitialized():
    with sqlite3.connect(":memory:") as conn:
        store = TaskStore(conn)
        traced = []
        conn.set_trace_callback(traced.append)
        assert_error("invalid_request", lambda: store.run("capture", {}))
        assert traced == []
        assert_error("not_initialized", lambda: store.run("list", {}))
        assert traced == []
        conn.execute("BEGIN")
        assert_error("connection_in_transaction", store.initialize)
        assert conn.in_transaction
        conn.rollback()


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrency(tmp_path, same_key):
    path = tmp_path / "concurrent.sqlite"
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        task = capture(store)
    barrier = Barrier(2)

    def run(index):
        with sqlite3.connect(path, timeout=5) as conn:
            store = TaskStore(conn)
            store.initialize()
            barrier.wait(timeout=10)
            try:
                return store.run(
                    "update",
                    mutation(
                        task, "same" if same_key else f"key{index}", title="Synthetic concurrent"
                    ),
                )
            except TaskError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    if same_key:
        assert sorted(r["replayed"] for r in results) == [False, True]
        assert results[0]["data"] == results[1]["data"]
    else:
        assert sum(r == "revision_conflict" for r in results) == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT revision FROM tasks").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 2


def test_busy_is_retryable(tmp_path):
    path = tmp_path / "busy.sqlite"
    with sqlite3.connect(path) as first, sqlite3.connect(path, timeout=0) as second:
        store = TaskStore(first)
        store.initialize()
        other = TaskStore(second)
        other.initialize()
        first.execute("BEGIN IMMEDIATE")
        error = assert_error("storage_busy", lambda: capture(other))
        assert error.retryable
        assert first.in_transaction and not second.in_transaction
        first.rollback()
        capture(other)


@pytest.mark.parametrize("kind", ["foreign", "newer", "extra_table", "lookalike"])
def test_rejected_schema_leaves_original_bytes_unchanged(tmp_path, kind):
    path = tmp_path / "existing.sqlite"
    with sqlite3.connect(path) as conn:
        if kind in {"newer", "extra_table"}:
            store = TaskStore(conn)
            store.initialize()
            capture(store)
        if kind == "newer":
            conn.execute("PRAGMA user_version = 5")
        elif kind == "extra_table":
            conn.execute("CREATE TABLE extra_table (synthetic TEXT)")
            conn.execute("INSERT INTO extra_table VALUES ('Synthetic private')")
        else:
            table = "sqlitex_hidden" if kind == "lookalike" else "foreign_table"
            conn.execute(f"CREATE TABLE {table} (synthetic TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES ('Synthetic private')")
    before = path.read_bytes()
    with sqlite3.connect(path) as conn:
        code = "unsupported_schema" if kind in {"newer", "extra_table"} else "foreign_database"
        assert_error(code, TaskStore(conn).initialize)
        assert not conn.in_transaction
    assert path.read_bytes() == before


def test_concurrent_capture_and_persisted_receipt(tmp_path):
    path = tmp_path / "capture.sqlite"
    barrier = Barrier(2)
    request = {"title": "Synthetic stable capture", "request_id": "stable"}

    def run(_):
        with sqlite3.connect(path, timeout=5) as conn:
            store = TaskStore(conn)
            store.initialize()
            barrier.wait(timeout=10)
            return store.run("capture", request)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [0, 1]))
    assert sorted(result["replayed"] for result in results) == [False, True]
    assert results[0]["data"] == results[1]["data"]
    with sqlite3.connect(path) as conn:
        store = TaskStore(conn)
        store.initialize()
        assert store.run("capture", request) == {"data": results[0]["data"], "replayed": True}
        assert_error(
            "idempotency_conflict",
            lambda: store.run(
                "complete", mutation(results[0]["data"], "stable", note="Synthetic done")
            ),
        )
        for table in ["tasks", "events", "receipts"]:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
