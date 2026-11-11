"""Bounded original reads on real synthetic native SQLite snapshots."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import hermes_state_checkpoint_sources as proposal
import pytest
from consumer import prepare, read_original_sources
from hermes_state import SessionDB
from test_checkpoint_sources import commit, request


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with SessionDB(tmp_path / "state.db") as store:
        store.create_session("session", source="cli")
        store.append_message("session", "user", "original synthetic source")
        yield store


def read(store, receipt, **kwargs):
    return proposal.read_receipt_sources(
        store,
        kwargs.get("session", "session"),
        kwargs.get("attempt", "attempt"),
        kwargs.get("expected", receipt["receipt_id"]),
    )


def mutate(store, sql, args=()):
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(sql, args)


def assert_empty(result, status=None):
    assert result == {
        "status": status or result["status"],
        "available": False,
        "durable_memory_checkpoint": False,
    }


def test_exact_originals_restart_optional_consumer(db):
    receipt = commit(db, request(db))
    result = read_original_sources(db.db_path, "session", "attempt", receipt["receipt_id"])
    assert result["status"] == "available_at_snapshot"
    assert result["available"] and not result["durable_memory_checkpoint"]
    assert result["sources"][0]["content"] == "original synthetic source"
    assert "synthetic summary" not in json.dumps(result)
    code = """
import json, sys
from consumer import read_original_sources
print(json.dumps(read_original_sources(sys.argv[1], 'session', 'attempt', sys.argv[2])))
"""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    child = subprocess.check_output(
        [sys.executable, "-c", code, str(db.db_path), receipt["receipt_id"]],
        env=env,
    )
    assert json.loads(child) == result


def test_split_merge_returns_original_rows_not_normalized_join(db):
    db.append_message("session", "user", "second source")
    normalized, _ = db.get_resume_conversations("session")
    req = prepare(db.db_path, "session", "attempt", normalized, "summary")
    assert len(req["sources"]) == 1 and len(req["sources"][0]) == 2
    result = read(db, commit(db, req))
    assert [r["content"] for r in result["sources"]] == [
        "original synthetic source",
        "second source",
    ]
    assert [r["row_id"] for r in result["sources"]] == [r["id"] for r in req["sources"][0]]


def test_persisted_lineage_and_exact_unicode(db):
    uid = "f" * 32
    mutate(
        db,
        "UPDATE messages SET absorbed_message_uids=?, content=? WHERE id=1",
        (json.dumps([uid]), "  原始🙂\n文本  "),
    )
    result = read(db, commit(db, request(db)))
    assert result["sources"][0]["content"] == "  原始🙂\n文本  "
    assert result["sources"][0]["absorbed_message_uids"] == [uid]


def test_absence_does_not_create_schema(db):
    before = sqlite3.connect(db.db_path).execute("SELECT sql FROM sqlite_master").fetchall()
    assert_empty(read(db, {"receipt_id": "0" * 64}), "absent")
    after = sqlite3.connect(db.db_path).execute("SELECT sql FROM sqlite_master").fetchall()
    assert before == after


@pytest.mark.parametrize("binding", ["session", "attempt", "store", "receipt"])
def test_wrong_binding_no_payload(db, tmp_path, binding):
    receipt = commit(db, request(db))
    if binding == "receipt":
        with pytest.raises(proposal.SourceReceiptError, match="^receipt_mismatch$"):
            read(db, receipt, expected="0" * 64)
    elif binding == "store":
        with SessionDB(tmp_path / "other.db") as other:
            assert_empty(read(other, receipt), "absent")
    else:
        assert_empty(read(db, receipt, **{binding: "other"}), "absent")


@pytest.mark.parametrize(
    "mutation",
    ["DELETE FROM messages WHERE id=1", "UPDATE messages SET content='changed' WHERE id=1"],
)
@pytest.mark.parametrize("timing", ["before", "within", "after"])
@pytest.mark.parametrize("journal", ["native", "delete"])
def test_mutation_races_use_one_snapshot(tmp_path, monkeypatch, mutation, timing, journal):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    if journal == "delete":
        (home / "config.yaml").write_text("database:\n  journal_mode: delete\n")
    with SessionDB(tmp_path / "race.db") as store:
        store.create_session("session", source="cli")
        store.append_message("session", "user", "original synthetic source")
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode in ("wal", "delete")
        if journal == "delete":
            assert mode == "delete" and not store._wal_active
        receipt = commit(store, request(store))
        if timing == "before":
            mutate(store, mutation)
            assert_empty(read(store, receipt), "invalidated_or_unknown")
            return
        _assert_snapshot_race(store, receipt, monkeypatch, mutation, timing, mode)


def _assert_snapshot_race(store, receipt, monkeypatch, mutation, timing, mode):
    original = proposal._read_originals if timing == "within" else proposal._read_receipt_snapshot
    observed, release = Event(), Event()
    observation = []

    def writer():
        with sqlite3.connect(store.db_path, timeout=0) as conn:
            conn.execute(mutation)
            try:
                conn.commit()
            except sqlite3.OperationalError as exc:
                assert mode == "delete" and exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                observation.append("blocked_commit")
                observed.set()
                assert release.wait(10), "reader did not release its snapshot"
                conn.commit()
            else:
                observation.append("committed_during_snapshot")
                observed.set()

    def interleave(*args):
        if timing == "after":
            result = original(*args)
        futures.append(pool.submit(writer))
        assert observed.wait(10), "writer did not reach commit observation"
        assert observation == ["committed_during_snapshot" if mode == "wal" else "blocked_commit"]
        return original(*args) if timing == "within" else result

    futures = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with monkeypatch.context() as patch:
                patch.setattr(
                    proposal,
                    "_read_originals" if timing == "within" else "_read_receipt_snapshot",
                    interleave,
                )
                result = read(store, receipt)
            assert result["sources"][0]["content"] == "original synthetic source"
        finally:
            # DELETE writers can commit only after the native read transaction ends.
            release.set()
        assert len(futures) == 1
        futures[0].result(timeout=10)
    assert_empty(read(store, receipt), "invalidated_or_unknown")


@pytest.mark.parametrize(
    "damage",
    [
        "DROP TABLE source_receipt_rows",
        "DELETE FROM source_receipt_rows",
        "INSERT INTO source_receipt_rows SELECT receipt_id,999999 FROM source_receipts",
        "UPDATE source_receipts SET source_count=0",
        "UPDATE source_receipts SET source_count=257",
        "UPDATE source_receipts SET source_count='bad'",
        "UPDATE source_receipt_rows SET row_id='bad'",
    ],
)
def test_malformed_membership_fails_closed(db, damage):
    receipt = commit(db, request(db))
    mutate(db, damage)
    assert_empty(read(db, receipt), "unavailable")


def test_extra_cross_session_binding_cannot_hide_in_join(db):
    receipt = commit(db, request(db))
    db.create_session("other", source="cli")
    rid = db.append_message("other", "user", "other private original")
    mutate(db, "INSERT INTO source_receipt_rows VALUES (?,?)", (receipt["receipt_id"], rid))
    assert_empty(read(db, receipt), "unavailable")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE messages SET role='tool' WHERE id=1",
        "UPDATE messages SET _compressed_summary=1 WHERE id=1",
        "UPDATE messages SET content='[CONTEXT SUMMARY]: hidden' WHERE id=1",
        "UPDATE messages SET content='   ' WHERE id=1",
        "UPDATE messages SET active=1 WHERE id=1",
        "UPDATE messages SET compacted=0 WHERE id=1",
        "UPDATE messages SET session_id='other' WHERE id=1",
        "UPDATE messages SET absorbed_message_uids='bad json' WHERE id=1",
        "UPDATE messages SET message_uid='bad uid' WHERE id=1",
        "UPDATE messages SET tool_calls='bad json' WHERE id=1",
        "UPDATE messages SET tool_call_uid='tool' WHERE id=1",
    ],
)
def test_invalid_stored_originals_defensively_fail_closed(db, sql):
    receipt = commit(db, request(db))
    mutate(db, sql)
    # Synthetic corruption injection tests validation; not a raw-tampering guarantee.
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert_empty(read(db, receipt), "unavailable")


@pytest.mark.parametrize(
    "budget",
    [
        "MAX_ROWS",
        "MAX_IDENTITIES",
        "MAX_ROW_CHARS",
        "MAX_CHARS",
        "MAX_RAW_ROW",
        "MAX_RAW_TOTAL",
        "MAX_SOURCE_OUTPUT",
    ],
)
def test_all_budgets_refuse_without_partial_output(db, monkeypatch, budget):
    receipt = commit(db, request(db))
    monkeypatch.setattr(proposal, budget, 0)
    assert_empty(read(db, receipt), "unavailable")


def test_output_exact_boundary(db, monkeypatch):
    receipt = commit(db, request(db))
    result = read(db, receipt)
    size = len(proposal._json(result).encode("ascii"))
    monkeypatch.setattr(proposal, "MAX_SOURCE_OUTPUT", size)
    assert read(db, receipt) == result
    monkeypatch.setattr(proposal, "MAX_SOURCE_OUTPUT", size - 1)
    assert_empty(read(db, receipt), "unavailable")


def test_missing_triggers_no_payload(db):
    receipt = commit(db, request(db))
    mutate(db, "DROP TRIGGER source_receipt_update")
    assert_empty(read(db, receipt), "invalidated_or_unknown")


def test_closed_reader_and_nested_transaction_are_not_reopened_or_rolled_back(db):
    receipt = commit(db, request(db))
    reader = SessionDB(db.db_path, read_only=True)
    reader.close()
    assert_empty(read(reader, receipt), "unavailable")
    with SessionDB(db.db_path, read_only=True) as reader:
        conn = reader._conn
        conn.execute("BEGIN")
        assert_empty(read(reader, receipt), "unavailable")
        assert conn.in_transaction
        conn.rollback()


def test_read_path_never_writes_or_initializes_schema(db, monkeypatch):
    receipt = commit(db, request(db))

    def forbidden(*args):
        pytest.fail("read path attempted schema or write")

    monkeypatch.setattr(proposal, "_schema", forbidden)
    with SessionDB(db.db_path, read_only=True) as reader:
        conn = reader._conn
        before = conn.total_changes
        assert read(reader, receipt)["available"]
        assert conn.total_changes == before


@pytest.mark.parametrize("expected", [None, "short", "A" * 64, "x" * 64, [], 1])
def test_bad_receipt_input_redacted(db, expected):
    with pytest.raises(proposal.SourceReceiptError, match="^invalid_request$"):
        read(db, {"receipt_id": expected})


def test_same_attempt_other_session_receipt_mismatch(db):
    receipt = commit(db, request(db))
    db.create_session("other", source="cli")
    db.append_message("other", "user", "different private original")
    row = db.get_messages("other")[0]
    req = proposal.prepare_source_request(
        db,
        "other",
        "attempt",
        [
            {
                "role": "user",
                "content": row["content"],
                "uids": [row["message_uid"]],
            }
        ],
        [{"role": "assistant", "content": "summary"}],
    )
    other = proposal.commit_source_request(db, "other", req)
    assert other["receipt_id"] != receipt["receipt_id"]
    with pytest.raises(proposal.SourceReceiptError, match="^receipt_mismatch$"):
        read(db, receipt, session="other")


def test_optional_consumer_missing_store_is_redacted_and_not_created(tmp_path):
    path = tmp_path / "PRIVATE-path.db"
    result = read_original_sources(path, "session", "attempt", "0" * 64)
    assert_empty(result, "unavailable")
    assert "PRIVATE" not in repr(result) and not path.exists()


def test_actual_decoded_per_row_limit_and_one_over(db):
    mutate(db, "UPDATE messages SET content=? WHERE id=1", ("🙂" * 16384,))
    receipt = commit(db, request(db))
    result = read(db, receipt)
    assert result["sources"][0]["content"] == "🙂" * 16384
    assert len(proposal._json(result).encode("ascii")) > 16384 * 10
    mutate(db, "UPDATE messages SET content=? WHERE id=1", ("🙂" * 16385,))
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert_empty(read(db, receipt), "unavailable")


def test_actual_decoded_aggregate_limit_and_one_over(db):
    mutate(db, "UPDATE messages SET content=? WHERE id=1", ("x" * 16383,))
    for _ in range(3):
        db.append_message("session", "assistant", "x" * 16384)
    db.append_message("session", "assistant", "x")
    receipt = commit(db, request(db))
    assert sum(len(row["content"]) for row in read(db, receipt)["sources"]) == 65536
    mutate(db, "UPDATE messages SET content=? WHERE id=1", ("x" * 16384,))
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert_empty(read(db, receipt), "unavailable")


def test_actual_uid_aggregate_limit_and_one_over(db):
    db.append_message("session", "assistant", "reply")
    for rid, start in [(1, 1), (2, 512)]:
        mutate(
            db,
            "UPDATE messages SET absorbed_message_uids=? WHERE id=?",
            (json.dumps([f"{i:032x}" for i in range(start, start + 511)]), rid),
        )
    receipt = commit(db, request(db))
    assert (
        sum(1 + len(row["absorbed_message_uids"]) for row in read(db, receipt)["sources"]) == 1024
    )
    mutate(
        db,
        "UPDATE messages SET absorbed_message_uids=? WHERE id=2",
        (json.dumps([f"{i:032x}" for i in range(512, 1024)]),),
    )
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert_empty(read(db, receipt), "unavailable")


@pytest.mark.parametrize("aggregate", [False, True])
def test_raw_size_boundaries_and_no_partial_result(db, aggregate):
    if aggregate:
        for _ in range(8):
            db.append_message("session", "assistant", "reply")
    receipt = commit(db, request(db))
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM messages WHERE active=0 ORDER BY id").fetchall()
    # Fill supported but unused metadata to exact raw-size limits. This is
    # synthetic corruption injection, not a promise against malicious tampering.
    target = 2097152 if aggregate else 262144
    total = sum(sum(len(v) for v in tuple(row) if isinstance(v, (str, bytes))) for row in rows)
    remaining = target - total
    for row in rows:
        size = sum(len(v) for v in tuple(row) if isinstance(v, (str, bytes)))
        added = min(262144 - size, remaining)
        mutate(db, "UPDATE messages SET reasoning=? WHERE id=?", ("x" * added, row["id"]))
        remaining -= added
    assert remaining == 0
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert read(db, receipt)["available"]
    mutate(db, "UPDATE messages SET reasoning=reasoning || 'x' WHERE id=?", (rows[-1]["id"],))
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert_empty(read(db, receipt), "unavailable")


def test_actual_row_count_limit_and_overflow(db):
    for _ in range(255):
        db.append_message("session", "assistant", "reply")
    receipt = commit(db, request(db))
    assert len(read(db, receipt)["sources"]) == 256
    mutate(db, "INSERT INTO source_receipt_rows VALUES (?,999999)", (receipt["receipt_id"],))
    assert_empty(read(db, receipt), "unavailable")


@pytest.mark.parametrize("mode", ["single", "bulk", "chain"])
def test_supported_native_deletion_prevents_payload(db, mode):
    receipt = commit(db, request(db))
    assert read(db, receipt)["available"]
    if mode == "bulk":
        assert db.delete_sessions(["session"]) == 1
    else:
        assert db.delete_session("session", include_compression_chain=mode == "chain")
    assert_empty(read(db, receipt), "invalidated_or_unknown")


def test_later_row_decode_failure_returns_no_partial_first_row(db):
    db.append_message("session", "assistant", "second original")
    receipt = commit(db, request(db))
    assert len(read(db, receipt)["sources"]) == 2
    mutate(db, "UPDATE messages SET content=? WHERE id=2", (b"\xff",))
    mutate(db, "UPDATE source_receipts SET invalidated=0")
    assert_empty(read(db, receipt), "unavailable")
