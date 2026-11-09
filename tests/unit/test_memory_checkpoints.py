"""Durable metadata markers without transcript, payload backup or native success claims."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from test_memory_progress import advance, error, opened, save

from personal_agent import memory_checkpoints
from personal_agent.conversation_memory import parse_command
from personal_agent.local_memory import _APPLICATION_ID, _SCHEMA_V1, _SCHEMA_V2, _SCHEMA_V3
from personal_agent.memory_backend import MemoryError, MemoryService, validate_request
from personal_agent.memory_tool_contract import normalize_memory_tool_request


def capture(backend, watermark=0, key="checkpoint"):
    return MemoryService(backend).execute(
        "checkpoint_create", {"expected_watermark": watermark, "request_id": key}
    )


def inspect(backend, receipt):
    return MemoryService(backend).execute(
        "checkpoint_status", {"checkpoint_id": receipt["checkpoint_id"]}
    )["data"]


def test_empty_marker_is_honest_and_does_not_create_events_or_progress():
    with opened() as (backend, conn):
        first = capture(backend)
        receipt = first["data"]
        assert receipt["through_sequence"] == receipt["record_count"] == receipt["event_count"] == 0
        assert receipt["active_count"] == receipt["forgotten_count"] == 0
        assert receipt["restorable"] is receipt["native_checkpoint"] is False
        assert inspect(backend, receipt)["is_current"] is True
        assert capture(backend) == {"data": receipt, "replayed": True}
        assert conn.execute("SELECT count(*) FROM events").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM consumer_cursors").fetchone() == (0,)
        error("unsupported", backend.checkpoint)
        assert "checkpoint" in backend.describe()["unsupported"]


def test_current_state_correction_forget_and_restart_keep_receipt_historical(tmp_path):
    path = tmp_path / "state.db"
    with opened(path) as (backend, conn):
        rid = save(backend, content="Private original")
        original = capture(backend, 1)["data"]
        assert original["record_count"] == original["active_count"] == original["event_count"] == 1
        advance(backend, 1)
        assert inspect(backend, original)["is_current"]
        backend.execute(
            "correct",
            {
                "record_id": rid,
                "expected_revision": 1,
                "request_id": "c",
                "content": "Private corrected",
            },
        )
        assert not inspect(backend, original)["is_current"]
        assert inspect(backend, original)["current_watermark"] == 2
        corrected = capture(backend, 2, "corrected")["data"]
        backend.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "f"})
        forgotten = capture(backend, 3, "forgotten")["data"]
        assert forgotten["active_count"] == 0 and forgotten["forgotten_count"] == 1
        assert len({r["metadata_sha256"] for r in (original, corrected, forgotten)}) == 3
        assert not inspect(backend, corrected)["is_current"]
        assert inspect(backend, forgotten)["is_current"]
        assert "Private" not in "\n".join(conn.iterdump())
        assert rid not in json.dumps([original, corrected, forgotten])
    with opened(path) as (backend, _):
        assert capture(backend, 1) == {"data": original, "replayed": True}
        assert not inspect(backend, original)["is_current"]
        assert inspect(backend, forgotten)["is_current"]
        assert backend.execute("list", {})["items"] == []
        error("idempotency_conflict", lambda: capture(backend, 3))


def test_watermark_conflict_never_records_stale_or_future_state():
    with opened() as (backend, conn):
        save(backend)
        error("watermark_conflict", lambda: capture(backend, 0))
        error("watermark_conflict", lambda: capture(backend, 2))
        assert conn.execute("SELECT count(*) FROM record_checkpoints").fetchone() == (0,)
        assert capture(backend, 1)["data"]["through_sequence"] == 1


def test_checkpoint_keys_do_not_collide_with_memory_or_consumer_receipts():
    with opened() as (backend, _):
        save(backend, key="checkpoint")
        advance(backend, 1, key="checkpoint")
        assert capture(backend, 1)["replayed"] is False


def test_quota_allows_replay_and_never_blocks_correction_or_forgetting(monkeypatch):
    monkeypatch.setattr(memory_checkpoints, "MAX_CHECKPOINTS", 1)
    with opened() as (backend, _):
        rid = save(backend)
        first = capture(backend, 1)
        error("checkpoint_limit", lambda: capture(backend, 1, "extra"))
        assert capture(backend, 1) == {"data": first["data"], "replayed": True}
        backend.execute(
            "correct",
            {"record_id": rid, "expected_revision": 1, "content": "corrected", "request_id": "c"},
        )
        backend.execute("forget", {"record_id": rid, "expected_revision": 2, "request_id": "f"})
        assert not inspect(backend, first["data"])["is_current"]


def test_model_route_cannot_create_or_replay_marker(tmp_path):
    path = tmp_path / "scope.db"
    with opened(path) as (backend, _):
        receipt = capture(backend)["data"]
    with opened(path, source="activated_session_model") as (backend, conn):
        error("checkpoint_scope_required", lambda: capture(backend))
        error("checkpoint_scope_required", lambda: capture(backend, key="new"))
        assert conn.execute("SELECT count(*) FROM record_checkpoints").fetchone() == (1,)
        assert inspect(backend, receipt)["is_current"]
    for action in ("checkpoint_create", "checkpoint_status", "checkpoint"):
        for tool in ("personal_memory_read", "personal_memory_write"):
            error(
                "invalid_request",
                lambda tool=tool, action=action: normalize_memory_tool_request(
                    tool, {"action": action}
                ),
            )


def test_missing_capability_blocks_before_call():
    with opened() as (backend, _):

        class Incomplete:
            called = False

            def describe(self):
                result = backend.describe()
                result["capabilities"].remove("local_metadata_checkpoint")
                return result

            def execute(self, *_):
                self.called = True
                raise AssertionError("Must not invoke unnegotiated operation")

            def close(self):
                pass

        adapter = Incomplete()
        error("capability_unavailable", lambda: capture(adapter))
        assert not adapter.called


def test_failed_insert_rolls_back_and_retry_can_commit():
    with opened() as (backend, conn):
        conn.set_authorizer(
            lambda action, name, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_INSERT and name == "record_checkpoints"
                else sqlite3.SQLITE_OK
            )
        )
        error("storage_error", lambda: capture(backend))
        conn.set_authorizer(None)
        assert not conn.in_transaction
        assert conn.execute("SELECT count(*) FROM record_checkpoints").fetchone() == (0,)
        assert capture(backend)["replayed"] is False


def test_uncertain_post_commit_failure_reconciles_by_original_request(tmp_path):
    class AfterCommit(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "COMMIT":
                self.armed = False
                raise sqlite3.OperationalError("synthetic lost acknowledgement")
            return result

    path = tmp_path / "uncertain.db"
    with opened(path, factory=AfterCommit) as (backend, conn):
        save(backend)
        conn.armed = True
        error("storage_error", lambda: capture(backend, 1))
    with opened(path) as (backend, conn):
        result = capture(backend, 1)
        assert result["replayed"] and inspect(backend, result["data"])["is_current"]
        assert conn.execute("SELECT count(*) FROM record_checkpoints").fetchone() == (1,)


def test_identical_concurrent_requests_commit_once(tmp_path):
    path = tmp_path / "concurrent.db"
    with opened(path) as (backend, _):
        save(backend)
    barrier = Barrier(2, timeout=5)

    def writer(_):
        with opened(path) as (backend, _):
            barrier.wait()
            return capture(backend, 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, range(2)))
    assert results[0]["data"] == results[1]["data"]
    assert {result["replayed"] for result in results} == {True, False}


def test_snapshot_capture_fences_competing_record_write(tmp_path):
    path = tmp_path / "fence.db"
    with opened(path) as (backend, conn), opened(path) as (writer, other):
        rid = save(backend)
        other.execute("PRAGMA busy_timeout=0")
        observed = []

        def concurrent_write(sql):
            if (
                sql.startswith("SELECT sequence,record_id,revision,operation FROM events")
                and not observed
            ):
                observed.append("attempted")
                try:
                    writer.execute(
                        "forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"}
                    )
                except MemoryError as exc:
                    observed.append(exc.code)

        conn.set_trace_callback(concurrent_write)
        receipt = capture(backend, 1)["data"]
        conn.set_trace_callback(None)
        assert observed == ["attempted", "storage_busy"]
        assert receipt["active_count"] == 1 and inspect(backend, receipt)["is_current"]
        writer.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"})
        assert not inspect(backend, receipt)["is_current"]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM events",
        "UPDATE events SET operation='forget'",
        "UPDATE events SET revision=2",
        "UPDATE events SET sequence=0",
        "UPDATE records SET revision=2",
        "UPDATE events SET record_id='missing'",
    ],
)
def test_inconsistent_event_record_linkage_fails_closed(sql):
    with opened() as (backend, conn):
        save(backend)
        conn.execute(sql)
        error("checkpoint_state_inconsistent", lambda: capture(backend, 1))
        assert conn.execute("SELECT count(*) FROM record_checkpoints").fetchone() == (0,)


@pytest.mark.parametrize("version,schema", [(1, _SCHEMA_V1), (2, _SCHEMA_V2), (3, _SCHEMA_V3)])
def test_upgrade_is_atomic_including_all_earlier_migrations(version, schema):
    from personal_agent.local_memory import create_backend

    conn = sqlite3.connect(":memory:", isolation_level=None)
    for sql in schema.values():
        conn.execute(sql)
    conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version={version}")
    conn.execute("INSERT INTO namespace VALUES ('progress-test')")
    before = list(conn.iterdump())
    conn.set_authorizer(
        lambda action, name, *_: (
            sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_CREATE_TABLE and name == "record_checkpoints"
            else sqlite3.SQLITE_OK
        )
    )
    backend = create_backend()
    error(
        "storage_error", lambda: backend.open(conn, namespace_id="progress-test", session_ref="s")
    )
    conn.set_authorizer(None)
    assert list(conn.iterdump()) == before
    backend.open(conn, namespace_id="progress-test", session_ref="s")
    assert conn.execute("PRAGMA user_version").fetchone() == (9,)
    assert capture(backend)["data"]["record_count"] == 0
    backend.close()
    conn.close()


def test_v3_upgrade_preserves_record_and_consumer_state_and_exact_receipts():
    with opened() as (backend, conn):
        save(backend)
        first = advance(backend, 1)
        names = (
            "namespace",
            "records",
            "events",
            "receipts",
            "consumer_cursors",
            "consumer_receipts",
            "sqlite_sequence",
        )
        before = {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in names}
        backend.close()
        conn.execute("ALTER TABLE records DROP COLUMN expires_at")
        conn.execute("DROP TABLE memory_projection")
        conn.execute("DROP TABLE memory_edits")
        conn.execute("DROP TABLE memory_fts")
        conn.execute("DROP TABLE memory_candidates")
        conn.execute("DROP TABLE record_checkpoints")
        conn.execute("PRAGMA user_version=3")
        backend.open(conn, namespace_id="progress-test", session_ref="s")
        assert {name: conn.execute(f"SELECT * FROM {name}").fetchall() for name in names} == before
        assert advance(backend, 1) == {"data": first["data"], "replayed": True}
        assert capture(backend, 1)["data"]["record_count"] == 1


@pytest.mark.parametrize("value", [None, True, -1, "1", 1.0, 2**63 - 1])
def test_watermark_validation_is_strict(value):
    error(
        "invalid_request",
        lambda: validate_request(
            "checkpoint_create", {"expected_watermark": value, "request_id": "r"}
        ),
    )


def test_command_contract_and_unknown_checkpoint():
    assert parse_command("checkpoint --expected-watermark 2 --request-id c") == (
        "checkpoint_create",
        {"expected_watermark": 2, "request_id": "c"},
    )
    operation, request = parse_command("checkpoint --expected-watermark 0")
    assert operation == "checkpoint_create" and len(request["request_id"]) == 36
    for raw in (
        "checkpoint",
        "checkpoint --expected-watermark -1",
        "checkpoint --expected-watermark 0 --native true",
        "checkpoint-status bogus",
    ):
        error("invalid_request", lambda raw=raw: parse_command(raw))
    with opened() as (backend, _):
        error(
            "checkpoint_not_found",
            lambda: inspect(backend, {"checkpoint_id": "00000000-0000-4000-8000-000000000001"}),
        )


@pytest.mark.parametrize("excess", ["records", "events", "nonterminal_events"])
def test_bounded_state_scan_rejects_over_limit_metadata(excess):
    with opened() as (backend, conn):
        rid = save(backend)
        if excess == "records":
            conn.executemany(
                "INSERT INTO records(record_id,revision,status,content,topic,source,session_ref,"
                "created_at,updated_at) VALUES (?,1,'active','text','','explicit_local_operator',"
                "'s','now','now')",
                [(f"synthetic-{n}",) for n in range(1000)],
            )
        else:
            count = 11001 if excess == "events" else 10001
            conn.executemany(
                "INSERT INTO events(record_id,revision,operation) VALUES (?,?,'correct')",
                [(rid, n) for n in range(2, count + 1)],
            )
            conn.execute("UPDATE records SET revision=?", (count,))
        error("checkpoint_state_limit", lambda: capture(backend, 1))
        assert conn.execute("SELECT count(*) FROM record_checkpoints").fetchone() == (0,)


def test_terminal_event_cannot_be_followed_by_another_event():
    with opened() as (backend, conn):
        rid = save(backend)
        backend.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"})
        conn.execute(
            "INSERT INTO events(record_id,revision,operation) VALUES (?,3,'correct')", (rid,)
        )
        error("checkpoint_state_inconsistent", lambda: capture(backend, 3))


def test_status_read_is_snapshot_consistent_during_competing_forget(tmp_path):
    path = tmp_path / "read-fence.db"
    with opened(path) as (backend, conn), opened(path) as (writer, other):
        rid = save(backend)
        receipt = capture(backend, 1)["data"]
        other.execute("PRAGMA busy_timeout=0")
        observed = []

        def concurrent_write(sql):
            if sql.startswith("SELECT record_id,revision,status FROM records") and not observed:
                observed.append("attempted")
                try:
                    writer.execute(
                        "forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"}
                    )
                except MemoryError as exc:
                    observed.append(exc.code)

        conn.set_trace_callback(concurrent_write)
        status = inspect(backend, receipt)
        conn.set_trace_callback(None)
        assert observed == ["attempted", "storage_busy"]
        assert status["is_current"] and status["current_watermark"] == 1
        writer.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"})
        assert not inspect(backend, receipt)["is_current"]
