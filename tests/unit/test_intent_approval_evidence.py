"""Receipt bindings, refusal, atomic recovery and scope on the internal draft ledger."""

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest
from test_action_intents import KEY, NOW, SPEC, fail

from personal_agent.action_intents import ActionIntentStore, IntentError, VerifiedIntentApproval

REFERENCE = "synthetic-private-receipt"


@pytest.fixture
def ledger():
    receipts = {}
    with closing(sqlite3.connect(":memory:", isolation_level=None)) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW, approval_verifier=receipts.get)
        store.initialize()
        draft = store.prepare(SPEC)
        receipts[REFERENCE] = proof(draft)
        yield conn, store, draft, receipts


def proof(draft, reference=REFERENCE):
    return VerifiedIntentApproval(
        reference, draft["binding_digest"], 1, NOW, NOW + timedelta(minutes=2)
    )


def record(store, draft, reference=REFERENCE, **kwargs):
    key = {field: draft[field] for field in KEY}
    return store.record_approval(
        key,
        **{
            "expected_binding_digest": draft["binding_digest"],
            "expected_revision": 1,
            "receipt_ref": reference,
            **kwargs,
        },
    )


def test_exact_evidence_is_durable_redacted_and_historical(ledger):
    conn, store, draft, receipts = ledger
    assert store.inspect_approval(KEY) is None
    evidence = record(store, draft)
    assert evidence["binding_digest"] == draft["binding_digest"]
    assert evidence["intent_revision"] == 1
    assert store.inspect(KEY) == draft
    assert store.review_pending({k: KEY[k] for k in ("owner_id", "profile_id")})["items"] == [draft]
    receipts.clear()
    recovered = ActionIntentStore(conn, clock=lambda: NOW + timedelta(minutes=8))
    recovered.initialize()
    expired = recovered.inspect(KEY)
    assert expired["state"] == "expired"
    assert recovered.inspect_approval(KEY) == record(recovered, draft) == evidence
    assert conn.execute("SELECT count(*) FROM approval_evidence").fetchone() == (1,)
    assert conn.execute("SELECT count(*) FROM events").fetchone() == (2,)
    dump = "\n".join(conn.iterdump())
    for raw in (REFERENCE, SPEC["target"].decode(), SPEC["payload"].decode()):
        assert raw not in dump and raw not in str(evidence)


def test_unknown_unconfigured_or_failed_verifier_cannot_record(ledger):
    conn, store, draft, receipts = ledger
    receipts.clear()
    fail("approval_unavailable", lambda: record(store, draft))
    missing = ActionIntentStore(conn, clock=lambda: NOW)
    missing.initialize()
    fail("approval_unavailable", lambda: record(missing, draft))

    def broken(reference):
        raise RuntimeError(reference)

    invalid = ActionIntentStore(conn, clock=lambda: NOW, approval_verifier=broken)
    invalid.initialize()
    error = fail("approval_unavailable", lambda: record(invalid, draft))
    assert REFERENCE not in str(error) and error.__suppress_context__
    assert store.inspect_approval(KEY) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("receipt_ref", "other-receipt"),
        ("binding_digest", "0" * 64),
        ("intent_revision", True),
        ("intent_revision", 2),
        ("approved_at", NOW - timedelta(seconds=1)),
        ("approved_at", NOW + timedelta(seconds=1)),
        ("approved_at", NOW.replace(tzinfo=None)),
        ("expires_at", NOW),
        ("expires_at", SPEC["expires_at"] + timedelta(seconds=1)),
    ],
)
def test_mismatched_verifier_evidence_is_refused(ledger, field, value):
    _, store, draft, receipts = ledger
    receipts[REFERENCE] = replace(receipts[REFERENCE], **{field: value})
    fail("approval_mismatch", lambda: record(store, draft))
    assert store.inspect_approval(KEY) is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("owner_id", "other-owner"),
        ("profile_id", "other-profile"),
        ("request_id", "other-draft"),
        ("target", b"other-target"),
        ("payload", b"other-payload"),
        ("policy_revision", 8),
        ("epoch", 3),
        ("resource_revision", 4),
        ("expires_at", SPEC["expires_at"] + timedelta(seconds=1)),
    ],
)
def test_receipt_cannot_follow_altered_identity_or_binding(ledger, key, value):
    _, store, draft, _ = ledger
    new_spec = {**SPEC, key: value}
    if key not in KEY:
        new_spec["request_id"] = "replacement"
    other = store.prepare(new_spec)
    fail("approval_mismatch", lambda: record(store, other))
    fail(
        "request_conflict",
        lambda: record(store, other, expected_binding_digest=draft["binding_digest"]),
    )
    assert store.inspect_approval({k: other[k] for k in KEY}) is None


def test_single_receipt_per_draft_and_scope(ledger):
    _, store, draft, receipts = ledger
    first = record(store, draft)
    other = store.prepare({**SPEC, "owner_id": "separate-owner"})
    receipts[REFERENCE] = proof(other)
    fail("approval_conflict", lambda: record(store, other))
    receipts["second"] = proof(draft, "second")
    fail("approval_conflict", lambda: record(store, draft, "second"))
    assert store.inspect_approval(KEY) == first


def test_expired_or_cancelled_draft_cannot_gain_evidence(ledger):
    _, store, draft, _ = ledger
    store._clock = lambda: SPEC["expires_at"]
    fail("not_pending", lambda: record(store, draft))
    store._clock = lambda: NOW
    store.cancel(KEY, expected_revision=1)
    fail("not_pending", lambda: record(store, draft))
    assert store.inspect_approval(KEY) is None


def test_verification_delay_cannot_extend_receipt_freshness(ledger):
    conn, _, draft, receipts = ledger
    current = NOW

    def verifier(reference):
        nonlocal current
        current = receipts[reference].expires_at
        return receipts[reference]

    store = ActionIntentStore(conn, clock=lambda: current, approval_verifier=verifier)
    store.initialize()
    fail("approval_mismatch", lambda: record(store, draft))
    assert store.inspect_approval(KEY) is None


def test_migration_from_v2_preserves_cancelled_draft_and_replacement(ledger):
    conn, store, draft, _ = ledger
    new = {**SPEC, "request_id": "new-draft"}
    selection = {field: draft[field] for field in (*KEY, "binding_digest")}
    result = store.replace(selection, new)
    conn.execute("DROP TABLE approval_evidence")
    conn.execute("PRAGMA user_version=2")
    store.initialize()
    assert conn.execute("PRAGMA user_version").fetchone() == (3,)
    assert store.replace(selection, new) == result
    assert store.inspect_approval(KEY) is None


@pytest.mark.parametrize("version", [1, 2])
def test_migration_refuses_extra_schema_object_with_owned_name(ledger, version):
    conn, store, _, _ = ledger
    events_sql = conn.execute(
        "SELECT sql FROM main.sqlite_master WHERE type='table' AND name='events'"
    ).fetchone()[0]
    events = conn.execute("SELECT * FROM main.events").fetchall()
    conn.execute("DROP TABLE main.approval_evidence")
    if version == 1:
        conn.execute("DROP TABLE main.replacements")
    conn.execute("DROP TABLE main.events")
    conn.execute("CREATE TRIGGER events AFTER INSERT ON intents BEGIN SELECT 1; END")
    conn.execute(events_sql)
    conn.executemany("INSERT INTO main.events VALUES (?,?,?,?,?,?)", events)
    conn.execute(f"PRAGMA user_version={version}")
    before = list(conn.iterdump())

    fail("unsupported_schema", store.initialize)

    assert conn.execute("PRAGMA user_version").fetchone() == (version,)
    assert list(conn.iterdump()) == before


def test_corrupt_stored_receipt_refuses_retry(ledger):
    conn, store, draft, _ = ledger
    record(store, draft)
    conn.execute("UPDATE approval_evidence SET binding_digest=?", ("0" * 64,))
    fail("invalid_record", lambda: store.inspect_approval(KEY))
    fail("invalid_record", lambda: record(store, draft))


def test_record_approval_and_cancel_serialize(tmp_path):
    path = tmp_path / "approval-race.db"
    with closing(sqlite3.connect(path)) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        draft = store.prepare(SPEC)
    barrier = Barrier(2, timeout=5)

    def run(cancel):
        with closing(sqlite3.connect(path)) as conn:
            store = ActionIntentStore(
                conn, clock=lambda: NOW, approval_verifier=lambda _: proof(draft)
            )
            store.initialize()
            barrier.wait()
            if cancel:
                return store.cancel(KEY, expected_revision=1)
            try:
                return record(store, draft)
            except IntentError as error:
                assert error.code == "not_pending"
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        cancelled, evidence = pool.map(run, (True, False))
    assert cancelled["state"] == "cancelled"
    with closing(sqlite3.connect(path)) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        assert store.inspect_approval(KEY) == evidence
        if evidence is not None:
            assert record(store, draft) == evidence


@pytest.mark.parametrize("cut", ["before_commit", "after_commit"])
def test_process_death_recovers_the_exact_receipt(tmp_path, cut):
    path = tmp_path / "kill.db"
    with closing(sqlite3.connect(path)) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW)
        store.initialize()
        draft = store.prepare(SPEC)
    program = """
import os, sqlite3, sys
from datetime import datetime, timedelta
from personal_agent.action_intents import ActionIntentStore, VerifiedIntentApproval

class Crashing(sqlite3.Connection):
    armed = False
    def execute(self, sql, *args):
        if self.armed and sql == "COMMIT" and sys.argv[2] == "before_commit":
            os._exit(73)
        result = super().execute(sql, *args)
        if self.armed and sql == "COMMIT":
            os._exit(73)
        return result

conn = sqlite3.connect(sys.argv[1], factory=Crashing)
now = datetime.fromisoformat(sys.argv[3])
digest = sys.argv[4]
verify = lambda ref: VerifiedIntentApproval(ref, digest, 1, now, now + timedelta(minutes=2))
store = ActionIntentStore(conn, clock=lambda: now, approval_verifier=verify)
store.initialize()
conn.armed = True
store.record_approval(
    {"owner_id": "owner", "profile_id": "profile", "request_id": "request"},
    expected_binding_digest=digest, expected_revision=1, receipt_ref=sys.argv[5],
)
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            str(path),
            cut,
            NOW.isoformat(),
            draft["binding_digest"],
            REFERENCE,
        ],
        timeout=15,
    )
    assert result.returncode == 73
    with closing(sqlite3.connect(path)) as conn:
        store = ActionIntentStore(conn, clock=lambda: NOW, approval_verifier=lambda _: proof(draft))
        store.initialize()
        recovered = store.inspect_approval(KEY)
        assert (recovered is not None) == (cut == "after_commit")
        evidence = record(store, draft)
        if recovered is not None:
            assert evidence == recovered
        assert conn.execute("SELECT count(*) FROM approval_evidence").fetchone() == (1,)
