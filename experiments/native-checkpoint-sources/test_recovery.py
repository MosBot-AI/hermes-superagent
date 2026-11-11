"""Real two-store crash/restart evidence for the isolated journal proposal."""

import copy
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import recovery  # noqa: E402
from consumer import prepare  # noqa: E402
from hermes_state import SessionDB  # noqa: E402
from hermes_state_checkpoint_sources import (  # noqa: E402
    SourceReceiptError,
    commit_source_request,
    source_receipt_status,
    source_request_identity,
)
from recovery import RecoveryError, RecoveryJournal  # noqa: E402


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    host, path = tmp_path / "native.db", tmp_path / "journal.db"
    with SessionDB(host) as db:
        db.create_session("session", source="cli")
        db.append_message("session", "user", "SYNTHETIC_ORIGINAL_PRIVATE_TEXT")
        request = prepare(
            host,
            "session",
            "attempt",
            db.get_messages_as_conversation("session"),
            "SYNTHETIC_SUMMARY_PRIVATE_TEXT",
        )
    journal = RecoveryJournal(path, host, "session", create=True)
    return host, path, request, journal


def reopen(setup):
    return RecoveryJournal(setup[1], setup[0], "session")


def host_rows(host):
    with SessionDB(host, read_only=True) as db:
        return db.get_messages("session", include_inactive=True, include_compacted=True)


def counts(path):
    with sqlite3.connect(path) as db:
        return db.execute("SELECT COUNT(*), SUM(recorded) FROM attempts").fetchone()


def test_exact_identity_is_public_and_has_no_side_effects(setup):
    host, _, request, _ = setup
    original = copy.deepcopy(request)
    identity = source_request_identity("session", request)
    assert request == original and identity["source_count"] == 1
    assert "PRIVATE" not in json.dumps(identity)
    with SessionDB(host, read_only=True) as db:
        assert source_receipt_status(db, "session", "attempt")["status"] == "absent"
    with SessionDB(host) as db:
        receipt = commit_source_request(db, "session", request)
    assert identity["receipt_id"] == receipt["receipt_id"]


@pytest.mark.parametrize("change", ["session", "summary", "source", "revision", "lease", "attempt"])
def test_identity_binds_canonical_request(setup, change):
    request = copy.deepcopy(setup[2])
    before = source_request_identity("session", request)
    if change == "session":
        with pytest.raises(SourceReceiptError):
            source_request_identity("other", request)
        return
    if change == "summary":
        request["compacted_messages"][0]["content"] += "changed"
    elif change == "source":
        request["sources"][0][0]["fingerprint"] = "0" * 64
    elif change == "revision":
        request["revision"][-1] += 1
    elif change == "lease":
        request["lock_holder"] = "lease"
    else:
        request["attempt_id"] = "other"
    assert source_request_identity("session", request) != before


def test_submit_reopen_replay_and_metadata_only(setup):
    host, path, req, journal = setup
    result = journal.submit(req)
    assert result == {
        "accounting": "recorded",
        "host_observation": "committed_available",
        "source_available_at_observation": True,
        "durable_memory_checkpoint": False,
    }
    assert reopen(setup).submit(req) == result
    assert reopen(setup).pending() == [] and counts(path) == (1, 1)
    assert len(host_rows(host)) == 2
    with sqlite3.connect(path) as db:
        dump = "\n".join(db.iterdump())
    assert "PRIVATE_TEXT" not in dump
    assert b"PRIVATE_TEXT" not in path.read_bytes()


def test_prepared_absent_is_pending_and_no_automatic_retry(setup, monkeypatch):
    host, path, req, journal = setup
    journal.stage(req)
    before = host_rows(host)
    monkeypatch.setattr(
        recovery, "commit_source_request", lambda *_: pytest.fail("unexpected replay")
    )
    result = reopen(setup).reconcile("attempt")
    assert result["accounting"] == "pending" and result["host_observation"] == "absent"
    assert reopen(setup).pending() == [{"sequence": 1, "attempt_id": "attempt"}]
    assert host_rows(host) == before and counts(path) == (1, 0)


def test_post_host_commit_recovery_needs_no_payload(setup, monkeypatch):
    host, path, req, journal = setup
    journal.stage(req)
    with SessionDB(host) as db:
        commit_source_request(db, "session", req)
    monkeypatch.setattr(
        recovery, "commit_source_request", lambda *_: pytest.fail("unexpected replay")
    )
    assert reopen(setup).reconcile("attempt")["accounting"] == "recorded"
    assert counts(path) == (1, 1) and len(host_rows(host)) == 2


@pytest.mark.parametrize(
    "point", ["before_host", "inside_host", "after_host", "inside_journal", "after_journal"]
)
def test_abrupt_process_exit_and_fresh_process_reconciliation(setup, point):
    host, path, req, journal = setup
    # Request is passed only through process stdin, never retained in the journal.
    code = r"""
import json, os, sys
from recovery import RecoveryJournal
from hermes_state import SessionDB
host, path, point = sys.argv[1:]
request = json.load(sys.stdin)
journal = RecoveryJournal(path, host, "session")
if point == "before_host":
    journal.stage(request)
    os._exit(71)
if point == "inside_host":
    original = SessionDB._archive_and_compact_on_conn
    def interrupt(*args, **kwargs):
        original(*args, **kwargs)
        os._exit(71)
    SessionDB._archive_and_compact_on_conn = interrupt
if point == "after_host":
    journal.reconcile = lambda *_: os._exit(71)
if point == "inside_journal":
    original = journal._record
    def interrupt(*args):
        original(*args)
        os._exit(71)
    journal._record = interrupt
journal.submit(request)
os._exit(71)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).parent), str(ROOT), os.environ["CHECKPOINT_PROPOSAL_HOST"]]
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(host), str(path), point],
        input=json.dumps(req),
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 71, result.stderr
    expected_commit = point in ("after_host", "inside_journal", "after_journal")
    assert counts(path) == (1, int(point == "after_journal"))
    code = """
import json,sys
from recovery import RecoveryJournal
j=RecoveryJournal(sys.argv[2],sys.argv[1],"session")
print(json.dumps({"pending":j.pending(),"result":j.reconcile("attempt")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(host), str(path)],
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["result"]["accounting"] == ("recorded" if expected_commit else "pending")
    assert len(host_rows(host)) == (2 if expected_commit else 1)
    if not expected_commit:
        # Only explicit resupply of the identical request retries the absent attempt.
        journal.submit(req)
    assert counts(path) == (1, 1) and len(host_rows(host)) == 2
    for target in (host, path):
        with sqlite3.connect(target) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_local_record_failure_preserves_host_result_and_pending(setup, monkeypatch):
    host, path, req, journal = setup
    original = journal._record

    def fail(conn, attempt):
        original(conn, attempt)
        raise RuntimeError("SYNTHETIC_PRIVATE_FAILURE")

    monkeypatch.setattr(journal, "_record", fail)
    with pytest.raises(RecoveryError, match="^journal_write_unconfirmed$"):
        journal.submit(req)
    assert len(host_rows(host)) == 2 and counts(path) == (1, 0)
    assert reopen(setup).reconcile("attempt")["accounting"] == "recorded"


def test_intent_failure_prevents_host_admission(setup, monkeypatch):
    host, path, req, journal = setup
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TRIGGER fail BEFORE INSERT ON attempts "
            "BEGIN SELECT RAISE(ABORT, 'PRIVATE'); END"
        )
    monkeypatch.setattr(recovery, "commit_source_request", lambda *_: pytest.fail("host admitted"))
    with pytest.raises(RecoveryError, match="^journal_write_unconfirmed$"):
        journal.submit(req)
    assert len(host_rows(host)) == 1 and counts(path) == (0, None)


def test_unknown_host_return_can_be_reconciled(setup, monkeypatch):
    host, path, req, journal = setup
    original = recovery.commit_source_request

    def uncertain(*args):
        original(*args)
        raise RuntimeError("PRIVATE")

    monkeypatch.setattr(recovery, "commit_source_request", uncertain)
    with pytest.raises(RecoveryError, match="^host_commit_unconfirmed$"):
        journal.submit(req)
    assert counts(path) == (1, 0) and len(host_rows(host)) == 2
    assert reopen(setup).reconcile("attempt")["accounting"] == "recorded"


@pytest.mark.parametrize(
    "when", ["before_record", "after_record", "between_observation_and_record"]
)
def test_deletion_is_not_masked_by_historical_accounting(setup, monkeypatch, when):
    host, path, req, journal = setup
    journal.stage(req)
    with SessionDB(host) as db:
        commit_source_request(db, "session", req)

    def delete():
        with SessionDB(host) as db:
            db._execute_write(
                lambda c: c.execute(
                    "DELETE FROM messages WHERE id=?", (req["sources"][0][0]["id"],)
                )
            )

    if when == "before_record":
        delete()
    elif when == "after_record":
        journal.reconcile("attempt")
        delete()
    else:
        original = journal._record

        def delete_then_record(*args):
            delete()
            original(*args)

        monkeypatch.setattr(journal, "_record", delete_then_record)
        # Historical local accounting is safe even if this prior read became stale.
        assert journal.reconcile("attempt")["source_available_at_observation"]
    result = reopen(setup).reconcile("attempt")
    assert result["accounting"] == "recorded" and not result["source_available_at_observation"]
    assert result["host_observation"] == "invalidated_or_unknown" and counts(path) == (1, 1)
    assert len(host_rows(host)) == 1


def test_attempt_conflict_prevents_host_mutation(setup):
    host, _, req, journal = setup
    journal.stage(req)
    changed = copy.deepcopy(req)
    changed["compacted_messages"][0]["content"] = "different"
    with pytest.raises(RecoveryError, match="^attempt_conflict$"):
        journal.submit(changed)
    assert len(host_rows(host)) == 1


def test_foreign_same_attempt_receipt_is_not_accepted(setup):
    host, path, req, journal = setup
    journal.stage(req)
    changed = copy.deepcopy(req)
    changed["compacted_messages"][0]["content"] = "different"
    with SessionDB(host) as db:
        commit_source_request(db, "session", changed)
    with pytest.raises(RecoveryError, match="^receipt_mismatch$"):
        journal.reconcile("attempt")
    assert counts(path) == (1, 0)


def test_concurrent_identical_submission_is_single_accounting(setup):
    host, path, req, _ = setup

    def submit(_):
        return reopen(setup).submit(req)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(8)))
    assert all(r["accounting"] == "recorded" for r in results)
    assert counts(path) == (1, 1) and len(host_rows(host)) == 2


def test_capacity_and_sequence_pagination_do_not_drop_pending(setup, monkeypatch):
    host, path, req, journal = setup
    monkeypatch.setattr(recovery, "MAX_ATTEMPTS", 3)
    for n in range(3):
        changed = copy.deepcopy(req)
        changed["attempt_id"] = f"attempt-{n}"
        journal.stage(changed)
    assert journal.pending(limit=2) == [
        {"sequence": 1, "attempt_id": "attempt-0"},
        {"sequence": 2, "attempt_id": "attempt-1"},
    ]
    assert journal.pending(after=2) == [{"sequence": 3, "attempt_id": "attempt-2"}]
    journal.stage(changed)
    with pytest.raises(RecoveryError, match="^capacity$"):
        journal.submit(req)
    assert counts(path) == (3, 0) and len(host_rows(host)) == 1


@pytest.mark.parametrize(
    "change",
    [
        "missing_host",
        "replaced_host",
        "wrong_host",
        "wrong_session",
        "missing_journal",
        "bad_permissions",
        "symlink",
        "hardlink",
    ],
)
def test_binding_and_missing_storage_fail_closed(setup, tmp_path, change):
    host, path, req, journal = setup
    journal.stage(req)
    if change == "missing_host":
        host.rename(tmp_path / "saved.db")
        with pytest.raises(RecoveryError, match="^host_unavailable$"):
            journal.reconcile("attempt")
        assert not host.exists()
        return
    if change == "replaced_host":
        host.rename(tmp_path / "saved.db")
        host.write_bytes((tmp_path / "saved.db").read_bytes())
        with pytest.raises(RecoveryError, match="^host_unavailable$"):
            journal.reconcile("attempt")
    elif change == "wrong_host":
        other = tmp_path / "other.db"
        other.write_bytes(host.read_bytes())
        with pytest.raises(RecoveryError, match="^binding_mismatch$"):
            RecoveryJournal(path, other, "session")
    elif change == "wrong_session":
        with pytest.raises(RecoveryError, match="^binding_mismatch$"):
            RecoveryJournal(path, host, "other")
    elif change == "missing_journal":
        path.rename(tmp_path / "saved.db")
        with pytest.raises(RecoveryError):
            reopen(setup)
        assert not path.exists()
    elif change == "bad_permissions":
        path.chmod(0o644)
        with pytest.raises(RecoveryError, match="^journal_unavailable$"):
            reopen(setup)
    elif change == "symlink":
        path.rename(tmp_path / "saved.db")
        path.symlink_to(tmp_path / "saved.db")
        with pytest.raises(RecoveryError, match="^journal_unavailable$"):
            reopen(setup)
    else:
        os.link(path, tmp_path / "alias.db")
        with pytest.raises(RecoveryError, match="^journal_unavailable$"):
            reopen(setup)


def test_missing_attempt_and_invalid_input_never_create_receipt(setup):
    host, _, req, journal = setup
    with pytest.raises(RecoveryError, match="^attempt_missing$"):
        journal.reconcile("missing")
    for invalid in (None, {}, {**req, "version": 2}):
        with pytest.raises(RecoveryError, match="^invalid_request$"):
            journal.submit(invalid)
    for after, limit in ((True, 1), (0, True), (0, 101), (-1, 1)):
        with pytest.raises(RecoveryError):
            journal.pending(after=after, limit=limit)
    assert len(host_rows(host)) == 1


def test_recorded_history_does_not_hide_missing_host_receipt(setup):
    host, _, req, journal = setup
    journal.submit(req)
    # Manual deletion/rollback is unsupported, but status must not invent availability.
    with sqlite3.connect(host) as db:
        db.execute("DELETE FROM source_receipts")
    result = journal.reconcile("attempt")
    assert result["accounting"] == "recorded" and result["host_observation"] == "absent"
    assert not result["source_available_at_observation"]


def test_stale_source_before_admission(setup):
    host, path, req, journal = setup
    journal.stage(req)
    with SessionDB(host) as db:
        db._execute_write(
            lambda c: c.execute(
                "UPDATE messages SET content=? WHERE id=?",
                ("changed synthetic", req["sources"][0][0]["id"]),
            )
        )
    with pytest.raises(RecoveryError, match="host_commit_unconfirmed"):
        journal.submit(req)
    assert journal.reconcile("attempt")["accounting"] == "pending"
    assert counts(path) == (1, 0)
    assert len(host_rows(host)) == 1


def test_conflicting_concurrent_submission(setup):
    host, path, req, journal = setup
    other = copy.deepcopy(req)
    other["compacted_messages"][0]["content"] = "different synthetic"

    def submit(r):
        try:
            return reopen(setup).submit(r)["accounting"]
        except RecoveryError as e:
            return str(e)

    with ThreadPoolExecutor(max_workers=2) as p:
        result = list(p.map(submit, [req, other]))
    assert sorted(result) == ["attempt_conflict", "recorded"]
    assert counts(path) == (1, 1)
    assert len(host_rows(host)) == 2


def test_source_update_after_commit(setup):
    host, path, req, journal = setup
    journal.submit(req)
    with SessionDB(host) as db:
        db._execute_write(
            lambda c: c.execute(
                "UPDATE messages SET content=? WHERE id=?",
                ("changed synthetic", req["sources"][0][0]["id"]),
            )
        )
    result = reopen(setup).reconcile("attempt")
    assert result["accounting"] == "recorded"
    assert result["host_observation"] == "invalidated_or_unknown"
    assert result["source_available_at_observation"] is False
