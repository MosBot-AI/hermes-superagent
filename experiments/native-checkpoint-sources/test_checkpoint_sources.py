"""Real temporary native SQLite proposal contracts; no production/model activity."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import hermes_state_checkpoint_sources as proposal  # noqa: E402
from consumer import commit_and_inspect, prepare  # noqa: E402
from hermes_state import SessionDB  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    with SessionDB(tmp_path / "state.db") as store:
        store.create_session("session", source="cli")
        store.append_message("session", "user", "original synthetic source")
        yield store


def candidates(db):
    return [
        {
            "role": row["role"],
            "content": row["content"],
            "uids": [row["message_uid"], *json.loads(row["absorbed_message_uids"] or "[]")],
        }
        for row in db.get_messages("session")
    ]


def request(db, **kwargs):
    return proposal.prepare_source_request(
        db,
        "session",
        "attempt",
        candidates(db),
        [{"role": "assistant", "content": "synthetic summary"}],
        **kwargs,
    )


def commit(db, req):
    return proposal.commit_source_request(db, "session", req)


def status(db):
    return proposal.source_receipt_status(db, "session", "attempt")


def rows(db):
    return db.get_messages("session", include_inactive=True, include_compacted=True)


def test_actual_project_resolver_consumer_and_reopen(db):
    normalized = db.get_messages_as_conversation("session")
    req = prepare(db.db_path, "session", "attempt", normalized, "synthetic summary")
    result, availability = commit_and_inspect(db.db_path, "session", req)
    assert availability["available"] and result["source_count"] == 1
    assert commit(db, req) == result
    assert len(rows(db)) == 2
    assert rows(db)[0]["content"] == "original synthetic source"
    assert rows(db)[0]["active"] == 0 and rows(db)[0]["compacted"] == 1
    assert "original synthetic" not in json.dumps(result)
    with sqlite3.connect(db.db_path) as conn:
        dump = list(conn.execute("SELECT * FROM source_receipts")) + list(
            conn.execute("SELECT * FROM source_receipt_rows")
        )
        assert "original synthetic" not in repr(dump)


def test_real_native_user_resume_merge(db):
    db.append_message("session", "user", "second source")
    normalized, _ = db.get_resume_conversations("session")
    req = prepare(db.db_path, "session", "attempt", normalized, "summary")
    assert len(req["sources"][0]) == 2
    assert commit(db, req)["source_count"] == 2
    assert status(db)["available"]


def test_schema_is_explicit_and_status_readonly(db):
    before = rows(db)
    assert status(db) == {"status": "absent", "available": False}
    request(db)
    db.archive_and_compact("session", [{"role": "assistant", "content": "ordinary summary"}])
    assert len(rows(db)) > len(before)
    with sqlite3.connect(db.db_path) as conn:
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'source_receipt%'"
        ).fetchall()


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "mode",
        "session",
        "pending",
        "missing_uid",
        "duplicate",
        "content",
        "row_id",
        "fingerprint",
        "lineage",
        "extra",
        "output_extra",
        "overlong",
        "empty",
        "reversed",
    ],
)
def test_invalid_requests_have_no_effects(db, mutation):
    db.append_message("session", "assistant", "reply")
    req = request(db)
    if mutation == "version":
        req["version"] = 2
    elif mutation == "mode":
        req["mode"] = "worker"
    elif mutation == "session":
        req["session_id"] = "other"
    elif mutation == "pending":
        req["candidates"][0]["content"] += "\n\npending input"
    elif mutation == "missing_uid":
        req["candidates"][0]["uids"] = []
    elif mutation == "duplicate":
        req["candidates"][1]["uids"] = req["candidates"][0]["uids"]
    elif mutation == "content":
        req["candidates"][0]["content"] = "mismatched"
    elif mutation == "row_id":
        req["sources"][0][0]["id"] += 100
    elif mutation == "fingerprint":
        req["sources"][0][0]["fingerprint"] = "0" * 64
    elif mutation == "lineage":
        req["sources"][0][0]["uids"] = ["0" * 32]
    elif mutation == "extra":
        req["watermark"] = 100
    elif mutation == "output_extra":
        req["compacted_messages"][0]["api_content"] = "secret sidecar"
    elif mutation == "overlong":
        req["candidates"][0]["content"] = "x" * 16385
    elif mutation == "empty":
        req["candidates"] = []
    elif mutation == "reversed":
        req["candidates"].reverse()
    before = rows(db)
    with pytest.raises(proposal.SourceReceiptError):
        commit(db, req)
    assert rows(db) == before and status(db)["status"] == "absent"


@pytest.mark.parametrize(
    "field", ["compacted_messages", "candidates", "lock_holder", "revision", "sources"]
)
def test_attempt_binds_all_effect_inputs(db, field):
    req = request(db)
    original = commit(db, req)
    changed = copy.deepcopy(req)
    if field == "compacted_messages":
        changed[field][0]["content"] = "different output"
    elif field == "candidates":
        changed[field][0]["content"] = "different source"
    elif field == "lock_holder":
        changed[field] = "different-owner"
    elif field == "revision":
        changed[field][3] += 1
    elif field == "sources":
        changed[field][0][0]["fingerprint"] = "0" * 64
    with pytest.raises(proposal.SourceReceiptError, match="attempt_conflict"):
        commit(db, changed)
    assert commit(db, req) == original and len(rows(db)) == 2


@pytest.mark.parametrize("change", ["append", "rewrite", "rewind", "uid", "lineage"])
def test_real_sibling_writer_changes_rejected(db, change):
    req = request(db)
    rid = req["sources"][0][0]["id"]
    with SessionDB(db.db_path) as writer:
        if change == "append":
            writer.append_message("session", "assistant", "later")
        elif change == "rewrite":
            writer.set_user_message_content("session", rid, "changed")
        elif change == "rewind":
            writer.rewind_to_message("session", rid)
        elif change == "uid":
            writer._execute_write(
                lambda conn: conn.execute(
                    "UPDATE messages SET message_uid=? WHERE id=?", ("0" * 32, rid)
                )
            )
        elif change == "lineage":
            writer._execute_write(
                lambda conn: conn.execute(
                    "UPDATE messages SET absorbed_message_uids=? WHERE id=?",
                    (json.dumps(["0" * 32]), rid),
                )
            )
    before = rows(db)
    with pytest.raises(proposal.SourceReceiptError):
        commit(db, req)
    assert rows(db) == before and status(db)["status"] == "absent"


def test_cancellation_and_foreign_lost_lease(db):
    req = request(db)
    with pytest.raises(proposal.SourceReceiptError, match="cancelled"):
        proposal.commit_source_request(db, "session", req, cancelled=lambda: True)
    assert status(db)["status"] == "absent"
    assert db.try_acquire_compression_lock("session", "foreign")
    with pytest.raises(proposal.SourceReceiptError, match="lease_conflict"):
        commit(db, req)
    own = request(db, lock_holder="foreign")
    assert commit(db, own)["status"] == "committed"


def test_missing_lease_refuses(db):
    req = request(db, lock_holder="gone")
    with pytest.raises(proposal.SourceReceiptError, match="lease_lost"):
        commit(db, req)
    assert status(db)["status"] == "absent"


def test_exception_after_native_archive_rolls_everything_back(db, monkeypatch):
    req, before = request(db), rows(db)
    archive = db._archive_and_compact_on_conn

    def fail(*args, **kwargs):
        archive(*args, **kwargs)
        raise RuntimeError("private backend detail must not escape")

    monkeypatch.setattr(db, "_archive_and_compact_on_conn", fail)
    with pytest.raises(proposal.SourceReceiptError, match="^commit_failed_reconcile_same_attempt$"):
        commit(db, req)
    assert rows(db) == before and status(db)["status"] == "absent"


def test_subprocess_exit_after_commit_before_reply(db, tmp_path):
    req = request(db)
    payload = tmp_path / "synthetic-request.json"
    payload.write_text(json.dumps(req))
    script = """import os,json,sys
from pathlib import Path
from hermes_state import SessionDB
from hermes_state_checkpoint_sources import commit_source_request
with SessionDB(Path(sys.argv[1])) as db:
 commit_source_request(db,'session',json.loads(Path(sys.argv[2]).read_text()))
 os._exit(23)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(db.db_path), str(payload)],
        env=dict(os.environ),
        timeout=30,
        capture_output=True,
    )
    assert result.returncode == 23, result.stderr.decode()
    original = status(db)
    assert original["available"]
    assert commit(db, req)["receipt_id"] == original["receipt_id"]
    assert len(rows(db)) == 2


def test_two_writers_same_attempt_commit_once(db):
    req, gate = request(db), Barrier(2)

    def run():
        with SessionDB(db.db_path) as writer:
            gate.wait(timeout=10)
            return commit(writer, req)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [f.result(timeout=30) for f in futures]
    assert results[0] == results[1] and len(rows(db)) == 2


@pytest.mark.parametrize(
    "mutation", ["clear", "replace", "delete", "rewrite_back", "partial", "clone"]
)
def test_source_loss_permanently_invalidates_and_replay_is_historical(db, mutation):
    db.append_message("session", "assistant", "second original")
    req = request(db)
    original = commit(db, req)
    ids = [r["id"] for group in req["sources"] for r in group]
    if mutation == "clear":
        db.clear_messages("session")
    elif mutation == "replace":
        db.replace_messages("session", [{"role": "user", "content": "replacement"}])
    elif mutation == "delete":
        db.delete_session("session")
    elif mutation == "rewrite_back":
        db.set_message_reaction("session", ids[0], "X")
        db.set_message_reaction("session", ids[0], None)
    elif mutation == "partial":
        db._execute_write(lambda c: c.execute("DELETE FROM messages WHERE id=?", (ids[0],)))
    elif mutation == "clone":

        def clone_and_delete(c):
            db._clone_message_rows(c, ids)
            c.execute("DELETE FROM messages WHERE id=?", (ids[0],))

        db._execute_write(clone_and_delete)
    assert not status(db)["available"]
    assert status(db)["status"] == "invalidated_or_unknown"
    assert commit(db, req) == original


def test_capacity_refuses_no_eviction_but_replay_survives(db, monkeypatch):
    req = request(db)
    result = commit(db, req)
    monkeypatch.setattr(proposal, "MAX_RECEIPTS", 1)
    db.append_message("session", "user", "next source")
    next_req = proposal.prepare_source_request(
        db,
        "session",
        "next",
        candidates(db)[-1:],
        [{"role": "assistant", "content": "next summary"}],
    )
    before = rows(db)
    with pytest.raises(proposal.SourceReceiptError, match="capacity"):
        commit(db, next_req)
    assert rows(db) == before and commit(db, req) == result


def test_binding_loss_cannot_masquerade_as_complete(db):
    db.append_message("session", "assistant", "second original")
    commit(db, request(db))
    db._execute_write(
        lambda conn: conn.execute(
            "DELETE FROM source_receipt_rows "
            "WHERE row_id=(SELECT MIN(row_id) FROM source_receipt_rows)"
        )
    )
    assert not status(db)["available"]


@pytest.mark.parametrize("mode", ["rotation", "worker", "app_server", "canonical_mutation"])
def test_unsupported_modes_refuse_contract(db, mode):
    req = request(db)
    req["mode"] = mode
    with pytest.raises(proposal.SourceReceiptError, match="unsupported_mode"):
        commit(db, req)
    with pytest.raises(TypeError):
        db.archive_and_compact("session", req["compacted_messages"], source_request=req)
    assert status(db)["status"] == "absent"


def test_native_busy_retry_cannot_mutate_request_digest(db, monkeypatch):
    req = request(db)
    before = copy.deepcopy(req)
    archive = db._archive_and_compact_on_conn
    calls = []

    def busy_once(*args, **kwargs):
        result = archive(*args, **kwargs)
        calls.append(result)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return result

    monkeypatch.setattr(db, "_archive_and_compact_on_conn", busy_once)
    original = commit(db, req)
    assert len(calls) == 2 and req == before
    assert commit(db, req) == original and len(rows(db)) == 2


@pytest.mark.parametrize("existing", [True, False])
def test_generated_and_native_flagged_summaries_are_not_sources(db, existing):
    if existing:
        db.append_message(
            "session", "assistant", "unmarked-looking summary", _compressed_summary=True
        )
        selected = candidates(db)[-1:]
    else:
        commit(db, request(db))
        selected = candidates(db)
    with pytest.raises(proposal.SourceReceiptError, match="source_mismatch"):
        proposal.prepare_source_request(
            db, "session", "next", selected, [{"role": "assistant", "content": "new summary"}]
        )


def test_real_prune_invalidates_without_blocking_deletion(db):
    commit(db, request(db))
    db.end_session("session", "done")
    assert db.prune_sessions(older_than_days=None) == 1
    assert not status(db)["available"]


@pytest.mark.parametrize("kind", ["rows", "content", "aggregate", "lineage", "metadata"])
def test_scan_bounds_fail_without_schema(db, kind):
    if kind == "rows":
        for n in range(256):
            db.append_message("session", "assistant", str(n))
    elif kind == "content":
        db.append_message("session", "assistant", "x" * 16385)
    elif kind == "aggregate":
        for _ in range(5):
            db.append_message("session", "assistant", "x" * 16384)
    elif kind == "lineage":
        db._execute_write(
            lambda c: c.execute("UPDATE messages SET absorbed_message_uids=?", (" " * 40000,))
        )
    elif kind == "metadata":
        db._execute_write(lambda c: c.execute("UPDATE messages SET api_content=?", ("x" * 262145,)))
    with pytest.raises(proposal.SourceReceiptError):
        proposal.prepare_source_request(
            db,
            "session",
            "attempt",
            [{"role": "user", "content": "original synthetic source", "uids": ["0" * 32]}],
            [{"role": "assistant", "content": "summary"}],
        )
    assert status(db)["status"] == "absent"


def test_missing_binding_and_trigger_status_is_unknown(db):
    commit(db, request(db))
    db._execute_write(lambda conn: conn.execute("DROP TRIGGER source_receipt_update"))
    assert status(db)["status"] == "invalidated_or_unknown"


def test_later_unrelated_append_does_not_invalidate_original(db):
    commit(db, request(db))
    db.append_message("session", "user", "later conversation")
    assert status(db)["available"]


def test_selected_subset_preserves_other_rows_and_binds_only_originals(db):
    db.append_message("session", "assistant", "unselected direct source")
    req = proposal.prepare_source_request(
        db, "session", "attempt", candidates(db)[:1], [{"role": "assistant", "content": "summary"}]
    )
    assert commit(db, req)["source_count"] == 1
    assert status(db)["available"]
    assert [r["content"] for r in db.get_messages("session")] == [
        "summary",
        "unselected direct source",
    ]


def test_cancel_callback_cannot_leak_arbitrary_error(db):
    def fail():
        raise proposal.SourceReceiptError("SYNTHETIC_PRIVATE_CALLBACK_DETAIL")

    with pytest.raises(proposal.SourceReceiptError, match="^operation_failed$"):
        proposal.commit_source_request(db, "session", request(db), cancelled=fail)
    assert status(db)["status"] == "absent"


def test_receipt_insert_failure_rolls_back_archive_and_retains_prior_receipts(db):
    req = request(db)
    db._execute_write(proposal._schema)
    db._execute_write(
        lambda c: c.execute(
            "CREATE TRIGGER receipt_fault BEFORE INSERT ON source_receipts "
            "BEGIN SELECT RAISE(ABORT, 'SYNTHETIC_PRIVATE_SQL_DETAIL'); END"
        )
    )
    before = rows(db)
    with pytest.raises(proposal.SourceReceiptError, match="^commit_failed_reconcile_same_attempt$"):
        commit(db, req)
    assert rows(db) == before and status(db)["status"] == "absent"
    db._execute_write(lambda c: c.execute("DROP TRIGGER receipt_fault"))
    assert commit(db, req)["status"] == "committed"


def test_rewritten_original_text_back_is_still_invalidated(db):
    req = request(db)
    rid = req["sources"][0][0]["id"]
    commit(db, req)

    def change(c):
        c.execute("UPDATE messages SET content='changed' WHERE id=?", (rid,))
        c.execute("UPDATE messages SET content='original synthetic source' WHERE id=?", (rid,))

    db._execute_write(change)
    assert not status(db)["available"]


def test_rolled_back_source_mutation_does_not_invalidate(db):
    req = request(db)
    commit(db, req)

    def change(c):
        c.execute("DELETE FROM messages WHERE id=?", (req["sources"][0][0]["id"],))
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        db._execute_write(change)
    assert status(db)["available"]


@pytest.mark.parametrize(
    "kind", ["foreign", "duplicate_uid", "tool_barrier", "assistant_merge", "pending_merge"]
)
def test_exact_source_reconciliation_rejects_unsupported_evidence(db, kind):
    selected = candidates(db)
    if kind == "foreign":
        db.create_session("foreign", source="cli")
        db.append_message("foreign", "user", "original synthetic source")
        selected[0]["uids"] = [db.get_messages("foreign")[0]["message_uid"]]
    elif kind == "duplicate_uid":
        db._execute_write(lambda c: db._clone_message_rows(c, [1]))
    elif kind == "tool_barrier":
        db.append_message("session", "tool", "tool result", tool_call_id="call")
        db.append_message("session", "user", "tail")
        selected += candidates(db)[-1:]
    elif kind == "assistant_merge":
        db.clear_messages("session")
        db.append_message("session", "assistant", "first")
        db.append_message("session", "assistant", "second")
        source = candidates(db)
        selected = [
            {
                "role": "assistant",
                "content": "first\nsecond",
                "uids": [s["uids"][0] for s in source],
            }
        ]
    elif kind == "pending_merge":
        selected[0]["content"] += "\n\nunidentified pending source"
    with pytest.raises(proposal.SourceReceiptError):
        proposal.prepare_source_request(
            db, "session", "attempt", selected, [{"role": "assistant", "content": "summary"}]
        )
    assert status(db)["status"] == "absent"


def test_metadata_binding_capacity_refuses_without_effects(db, monkeypatch):
    monkeypatch.setattr(proposal, "MAX_BINDINGS", 0)
    before = rows(db)
    with pytest.raises(proposal.SourceReceiptError, match="capacity"):
        commit(db, request(db))
    assert rows(db) == before and status(db)["status"] == "absent"


def test_prepare_and_status_read_only_database_bytes(db):
    req = request(db)
    commit(db, req)
    db._execute_write(lambda c: c.execute("SELECT 1"))
    before = db.db_path.read_bytes()
    with SessionDB(db.db_path, read_only=True) as reader:
        assert status(reader)["available"]
        with pytest.raises(proposal.SourceReceiptError, match="read_only"):
            commit(reader, req)
    assert db.db_path.read_bytes() == before


def test_native_rotation_and_worker_do_not_accept_receipt_contract(db):
    from hermes_state_runtime import RuntimeStoreError
    from hermes_state_worker_compression import archive_on_connection, worker_archive

    req = request(db)
    with pytest.raises(TypeError):
        db.publish_compression_child(
            parent_session_id="session",
            child_session_id="child",
            source="cli",
            messages=req["compacted_messages"],
            source_request=req,
        )
    with pytest.raises(TypeError):
        db._execute_write(
            lambda c: archive_on_connection(
                db, c, "session", req["compacted_messages"], source_request=req
            )
        )
    with pytest.raises(RuntimeStoreError):
        db._execute_write(
            lambda c: worker_archive(
                db,
                c,
                "session",
                {
                    "messages": req["compacted_messages"],
                    "model_config_patch": None,
                    "watermark": None,
                    "lock_holder": None,
                    "tail_count": 0,
                    "source_request": req,
                },
            )
        )
    assert status(db)["status"] == "absent" and len(rows(db)) == 1


def test_native_canonical_mutation_rejects_extra_contract(db):
    from hermes_state_mutations import validate_action
    from hermes_state_runtime import RuntimeStoreError

    with pytest.raises(RuntimeStoreError):
        validate_action("compress", {"source_request": request(db)})
    assert status(db)["status"] == "absent"


def test_native_app_server_strict_checkpoint_stays_unavailable():
    from agent.conversation_compression_checkpoint import (
        _refuse_checkpoint_required_on_codex_app_server,
    )

    with pytest.raises(RuntimeError, match="without a truthful pre-compaction"):
        _refuse_checkpoint_required_on_codex_app_server(True, "codex_app_server")
