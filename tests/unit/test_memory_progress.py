"""Metadata change replay and durable local consumer cursors, not native checkpoints."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier

import pytest

from personal_agent import memory_progress
from personal_agent.conversation_memory import parse_command
from personal_agent.local_memory import _APPLICATION_ID, _SCHEMA_V2, create_backend
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request
from personal_agent.memory_tool_contract import normalize_memory_tool_request


@contextmanager
def opened(path=":memory:", source="explicit_local_operator", factory=sqlite3.Connection):
    conn = sqlite3.connect(path, isolation_level=None, timeout=3, factory=factory)
    backend = create_backend()
    backend.open(conn, namespace_id="progress-test", session_ref="session", source_kind=source)
    try:
        yield backend, conn
    finally:
        backend.close()
        conn.close()


def save(backend, key="save", content="private original"):
    return backend.execute("remember", {"content": content, "request_id": key})["data"]["record_id"]


def advance(backend, through, revision=0, key="advance", consumer="projection"):
    return MemoryService(backend).execute(
        "consumer_advance",
        {
            "consumer_id": consumer,
            "expected_revision": revision,
            "through_sequence": through,
            "request_id": key,
        },
    )


def current(backend, consumer="projection"):
    return MemoryService(backend).execute("consumer_get", {"consumer_id": consumer})["data"]


def error(code, callback):
    with pytest.raises(MemoryError) as caught:
        callback()
    assert caught.value.code == code


def test_changes_include_terminal_event_but_never_historical_payload_or_receipt_key():
    with opened() as (backend, _):
        rid = save(backend)
        backend.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "content": "private corrected",
                "request_id": "private-key",
            },
        )
        backend.execute(
            "forget", {"record_id": rid, "expected_revision": 2, "request_id": "forget"}
        )
        page = MemoryService(backend).execute("changes", {})["data"]
        assert page["items"] == [
            {"sequence": 1, "record_id": rid, "revision": 1, "operation": "remember"},
            {"sequence": 2, "record_id": rid, "revision": 2, "operation": "correct"},
            {"sequence": 3, "record_id": rid, "revision": 3, "operation": "forget"},
        ]
        assert page["through_sequence"] == page["current_watermark"] == page["next_sequence"] == 3
        assert not page["has_more"] and page["retention_floor"] == 0
        assert "private" not in json.dumps(page)
        assert backend.execute("get", {"record_id": rid})["content"] is None


def test_fixed_upper_bound_paginates_without_chasing_new_writes():
    with opened() as (backend, _):
        for n in range(4):
            save(backend, str(n))
        first = backend.changes(limit=2)
        save(backend, "new")
        second = backend.changes(
            limit=2,
            after_sequence=first["next_sequence"],
            through_sequence=first["through_sequence"],
        )
        assert [event["sequence"] for event in second["items"]] == [3, 4]
        assert second["through_sequence"] == 4 and second["current_watermark"] == 5
        assert not second["has_more"]
        assert backend.changes(after_sequence=4)["items"][0]["sequence"] == 5
        empty = backend.changes(after_sequence=4, through_sequence=4)
        assert empty["items"] == [] and empty["next_sequence"] == 4
        error("future_watermark", lambda: backend.changes(through_sequence=6))
        error("invalid_sequence", lambda: backend.changes(after_sequence=5, through_sequence=4))


def test_consumer_commit_reopen_replay_and_historical_receipt_does_not_regress(tmp_path):
    path = tmp_path / "memory.db"
    with opened(path) as (backend, conn):
        assert current(backend) == {
            "consumer_id": "projection",
            "revision": 0,
            "through_sequence": 0,
            "registered": False,
            "scope": "caller_reported_local_record_progress_not_native_checkpoint",
        }
        assert conn.execute("SELECT count(*) FROM consumer_cursors").fetchone() == (0,)
        save(backend)
        first = advance(backend, 1)
        save(backend, "second")
        second = advance(backend, 2, 1, "next")
        assert second["data"]["revision"] == 2
        assert conn.execute("SELECT count(*) FROM events").fetchone() == (2,)
    with opened(path) as (backend, _):
        assert advance(backend, 1) == {"data": first["data"], "replayed": True}
        assert current(backend)["through_sequence"] == 2
        error("idempotency_conflict", lambda: advance(backend, 2))
        error("revision_conflict", lambda: advance(backend, 2, 1, "stale"))
        error("cursor_not_advanced", lambda: advance(backend, 1, 2, "regress"))
        error("cursor_not_advanced", lambda: advance(backend, 2, 2, "noop"))
        error("future_watermark", lambda: advance(backend, 3, 2, "future"))
        assert current(backend)["through_sequence"] == 2


def test_consumers_are_independent_and_record_receipts_have_separate_keys():
    with opened() as (backend, _):
        save(backend, "shared")
        first = advance(backend, 1, key="shared", consumer="one")
        second = advance(backend, 0, key="two", consumer="two")
        assert first["data"]["through_sequence"] == 1 and second["data"]["through_sequence"] == 0
        error("idempotency_conflict", lambda: advance(backend, 1, key="shared", consumer="two"))
        assert current(backend, "one")["revision"] == current(backend, "two")["revision"] == 1
        assert current(backend, "missing")["registered"] is False


def test_cursor_limits_never_block_canonical_forgetting(monkeypatch):
    monkeypatch.setattr(memory_progress, "MAX_CONSUMERS", 1)
    monkeypatch.setattr(memory_progress, "MAX_CURSOR_MUTATIONS", 1)
    with opened() as (backend, _):
        rid = save(backend)
        first = advance(backend, 0)
        error("consumer_limit", lambda: advance(backend, 1, consumer="two", key="two"))
        error("consumer_mutation_limit", lambda: advance(backend, 1, 1, "later"))
        assert advance(backend, 0) == {"data": first["data"], "replayed": True}
        backend.execute(
            "forget", {"record_id": rid, "expected_revision": 1, "request_id": "forget"}
        )
        assert backend.changes()["items"][-1]["operation"] == "forget"


def test_activated_model_route_cannot_write_consumer_progress():
    with opened(source="activated_session_model") as (backend, conn):
        save(backend)
        assert backend.changes()["items"]
        error("consumer_scope_required", lambda: advance(backend, 1))
        assert conn.execute("SELECT count(*) FROM consumer_receipts").fetchone() == (0,)
    for action in ("changes", "consumer_get", "consumer_advance"):
        for tool in ("personal_memory_read", "personal_memory_write"):
            error(
                "invalid_request",
                lambda tool=tool, action=action: normalize_memory_tool_request(
                    tool, {"action": action}
                ),
            )
    error("invalid_request", lambda: parse_command("consumer_advance"))


def test_receipt_failure_rolls_back_cursor_and_retry_is_first_commit():
    with opened() as (backend, conn):
        save(backend)
        conn.set_authorizer(
            lambda action, name, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and name == "consumer_receipts"
                else sqlite3.SQLITE_OK
            )
        )
        error("storage_error", lambda: advance(backend, 1))
        conn.set_authorizer(None)
        assert current(backend)["registered"] is False
        assert not conn.in_transaction
        assert advance(backend, 1)["replayed"] is False


def test_uncertain_post_commit_failure_reconciles_by_same_key(tmp_path):
    class AfterCommit(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "COMMIT":
                self.armed = False
                raise sqlite3.OperationalError("synthetic post-commit failure")
            return result

    path = tmp_path / "uncertain.db"
    with opened(path, factory=AfterCommit) as (backend, conn):
        save(backend)
        conn.armed = True
        error("storage_error", lambda: advance(backend, 1))
    with opened(path) as (backend, _):
        assert advance(backend, 1)["replayed"] is True
        assert current(backend)["revision"] == 1


def test_two_cursor_writers_use_compare_and_swap(tmp_path):
    path = tmp_path / "memory.db"
    with opened(path) as (backend, _):
        save(backend)
    barrier = Barrier(2, timeout=5)

    def worker(key):
        with opened(path) as (backend, _):
            barrier.wait()
            try:
                return advance(backend, 1, key=key)["data"]["revision"]
            except MemoryError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(worker, ["a", "b"]))
    assert set(result) == {1, "revision_conflict"}
    with opened(path) as (backend, conn):
        assert current(backend)["revision"] == 1
        assert conn.execute("SELECT count(*) FROM consumer_receipts").fetchone() == (1,)


def build_v2(conn):
    for sql in _SCHEMA_V2.values():
        conn.execute(sql)
    conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
    conn.execute("PRAGMA user_version=2")
    conn.execute("INSERT INTO namespace VALUES ('progress-test')")


def test_exact_v2_migration_preserves_records_receipts_events_and_model_source():
    with opened(source="activated_session_model") as (backend, conn):
        rid = save(backend)
        before = {
            name: conn.execute(f"SELECT * FROM {name}").fetchall()
            for name in ("namespace", "records", "events", "receipts", "sqlite_sequence")
        }
        backend.close()
        conn.execute("ALTER TABLE records DROP COLUMN expires_at")
        conn.execute("DROP TABLE memory_projection")
        conn.execute("DROP TABLE memory_fts")
        conn.execute("DROP TABLE memory_candidates")
        conn.execute("DROP TABLE record_checkpoints")
        conn.execute("DROP TABLE consumer_cursors")
        conn.execute("DROP TABLE consumer_receipts")
        conn.execute("PRAGMA user_version=2")
        backend.open(conn, namespace_id="progress-test", session_ref="new")
        assert conn.execute("PRAGMA user_version").fetchone() == (8,)
        assert {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in before} == before
        assert save(backend) == rid
        assert backend.execute("get", {"record_id": rid})["source"] == "activated_session_model"
        assert advance(backend, 1)["data"]["revision"] == 1


def test_v2_progress_migration_failure_rolls_back_all_new_tables():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    build_v2(conn)
    before = list(conn.iterdump())
    conn.set_authorizer(
        lambda action, name, *_: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_TABLE and name == "consumer_receipts"
            else sqlite3.SQLITE_OK
        )
    )
    error(
        "storage_error",
        lambda: create_backend().open(conn, namespace_id="progress-test", session_ref="s"),
    )
    conn.set_authorizer(None)
    assert list(conn.iterdump()) == before
    assert conn.execute("PRAGMA user_version").fetchone() == (2,)
    conn.close()


@pytest.mark.parametrize(
    "operation,payload",
    [("changes", {"limit": value}) for value in [True, 0, 51, 1.0, "2"]]
    + [
        ("changes", {key: value})
        for key in ("after_sequence", "through_sequence")
        for value in [True, -1, 1.0, "1", 2**63 - 1]
    ]
    + [
        ("consumer_get", {"consumer_id": value})
        for value in [None, True, "", "A", "x/y", "a" * 65, "a\n"]
    ]
    + [
        (
            "consumer_advance",
            {
                "consumer_id": "x",
                "expected_revision": rev,
                "through_sequence": sequence,
                "request_id": "r",
            },
        )
        for rev, sequence in [(-1, 0), (True, 0), (0, None), (0, -1), (0, 2**63 - 1)]
    ]
    + [("changes", {"query": "forged"}), ("consumer_get", {"consumer_id": "x", "scope": "forged"})],
)
def test_strict_bounds(operation, payload):
    error("invalid_request", lambda: validate_request(operation, payload))


def test_changes_command_validates_the_same_bounded_page():
    assert parse_command("changes --after-sequence 2 --through-sequence 5 --limit 1") == (
        "changes",
        {"after_sequence": 2, "through_sequence": 5, "limit": 1},
    )
    assert parse_command("changes") == (
        "changes",
        {"after_sequence": 0, "through_sequence": None, "limit": 20},
    )


def test_model_bound_replay_of_operator_receipt_still_denied(tmp_path):
    path = tmp_path / "memory.db"
    with opened(path) as (backend, _):
        save(backend)
        advance(backend, 1)
    with opened(path, source="activated_session_model") as (backend, _):
        error("consumer_scope_required", lambda: advance(backend, 1))
        assert current(backend)["revision"] == 1


def test_identical_concurrent_cursor_requests_commit_once(tmp_path):
    path = tmp_path / "memory.db"
    with opened(path) as (backend, _):
        save(backend)
    barrier = Barrier(2, timeout=5)

    def worker(_):
        with opened(path) as (backend, _):
            barrier.wait()
            return advance(backend, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, range(2)))
    assert results[0]["data"] == results[1]["data"]
    assert {result["replayed"] for result in results} == {False, True}
    with opened(path) as (backend, conn):
        assert current(backend)["revision"] == 1
        assert conn.execute("SELECT count(*) FROM consumer_receipts").fetchone() == (1,)


def test_v1_new_table_failure_rolls_back_prior_records_rebuild():
    from test_local_memory import legacy_database

    conn = sqlite3.connect(":memory:", isolation_level=None)
    legacy_database(conn)
    before = list(conn.iterdump())
    conn.set_authorizer(
        lambda action, name, *_: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_TABLE and name == "consumer_receipts"
            else sqlite3.SQLITE_OK
        )
    )
    error(
        "storage_error", lambda: create_backend().open(conn, namespace_id="legacy", session_ref="s")
    )
    conn.set_authorizer(None)
    assert list(conn.iterdump()) == before
    assert conn.execute("PRAGMA user_version").fetchone() == (1,)
    conn.close()


def test_changes_snapshot_blocks_new_event_before_page_rows(tmp_path):
    path = tmp_path / "memory.db"
    with opened(path) as (reader, conn), opened(path) as (writer, other):
        save(writer)
        other.execute("PRAGMA busy_timeout=0")
        observed = []

        def concurrent_write(sql):
            if (
                sql.startswith("SELECT sequence,record_id,revision,operation FROM events")
                and not observed
            ):
                observed.append("attempted")
                try:
                    save(writer, "second")
                except MemoryError as exc:
                    observed.append(exc.code)

        conn.set_trace_callback(concurrent_write)
        page = reader.changes()
        conn.set_trace_callback(None)
        assert observed == ["attempted", "storage_busy"]
        assert page["through_sequence"] == page["current_watermark"] == 1
        assert [item["sequence"] for item in page["items"]] == [1]
        save(writer, "second")
        assert reader.changes()["current_watermark"] == 2
