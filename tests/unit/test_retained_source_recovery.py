"""Synthetic retained-source crash, serialization and migration acceptance evidence."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, source_request_identity

NAMESPACE = "synthetic-source-recovery"
SESSION = "synthetic-source-session"


@contextmanager
def opened(path, *, readonly=False, factory=sqlite3.Connection, model=False):
    conn = sqlite3.connect(
        f"file:{path}?mode=ro" if readonly else path,
        uri=readonly,
        isolation_level=None,
        check_same_thread=False,
        timeout=10,
        factory=factory,
    )
    backend = create_backend()
    kind = "activated_session_model" if model else "explicit_local_operator"
    try:
        if readonly:
            backend.open_readonly(conn, namespace_id=NAMESPACE, session_ref=SESSION)
        else:
            backend.open(conn, namespace_id=NAMESPACE, session_ref=SESSION, source_kind=kind)
        yield LocalMemorySDK(backend, LocalBinding(NAMESPACE, SESSION, kind)), backend, conn
    finally:
        backend.close()
        conn.close()


def request(key="a", *, consumer="importer", sequence=0, content="synthetic private source"):
    return {
        "request_id": key,
        "consumer_id": consumer,
        "expected_sequence": sequence,
        "content": content,
        "topic": "synthetic private topic",
        "expires_at": None,
        "retention": "independent_snapshot",
        "source": {
            "identity": hashlib.sha256(key.encode()).hexdigest(),
            "fingerprint": hashlib.sha256(content.encode()).hexdigest(),
            "role": "user",
            "receipt_id": hashlib.sha256(("receipt:" + key).encode()).hexdigest(),
        },
    }


def status(sdk, action):
    return sdk.execute("source_status", source_request_identity(action))["data"]


def cursor(sdk, consumer="importer"):
    return sdk.execute("source_cursor", {"consumer_id": consumer})["data"]


def counts(conn):
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("records", "events", "receipts", "retained_source_decisions")
    )


CHILD = r"""
import json, os, sqlite3, sys
from personal_agent.local_memory import create_backend
class Crash(sqlite3.Connection):
    armed = False
    def execute(self, sql, *args):
        if self.armed and sql == 'COMMIT' and sys.argv[2] == 'before':
            os._exit(73)
        result = super().execute(sql, *args)
        if self.armed and sql == 'COMMIT' and sys.argv[2] == 'after':
            os._exit(73)
        return result
conn = sqlite3.connect(sys.argv[1], isolation_level=None, factory=Crash)
b = create_backend()
b.open(conn, namespace_id='synthetic-source-recovery', session_ref='synthetic-source-session')
conn.armed = True
b.execute(sys.argv[3], json.loads(sys.argv[4]))
raise RuntimeError('crash point not reached')
"""


@pytest.mark.parametrize("operation", ["source_stage", "source_accept", "source_discard"])
@pytest.mark.parametrize("stage", ["before", "after"])
def test_process_death_at_commit_recovers_metadata_and_atomic_cursor(tmp_path, operation, stage):
    path, action = tmp_path / "crash.db", request()
    with opened(path) as (sdk, _, conn):
        if operation != "source_stage":
            sdk.execute("source_stage", action)
        before = list(conn.iterdump())
    payload = source_request_identity(action) if operation == "source_discard" else action
    child = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(path), stage, operation, json.dumps(payload)],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert child.returncode == 73, child.stderr
    assert not child.stdout
    # A writable connection performs SQLite hot-journal recovery, not mutation replay.
    with opened(path) as (_, _, conn):
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        if stage == "before":
            assert list(conn.iterdump()) == before
        committed_accept = stage == "after" and operation == "source_accept"
        present = operation != "source_stage" or stage == "after"
        assert counts(conn) == ((1, 1, 1) if committed_accept else (0, 0, 0)) + (int(present),)
    with opened(path, readonly=True) as (sdk, backend, conn):
        before = list(conn.iterdump())
        backend._mutate = lambda *args: pytest.fail("status must not replay writes")
        outcome = status(sdk, action)
        position = cursor(sdk)
        if not present:
            assert outcome["state"] == "absent_at_snapshot"
            assert position == {"consumer_id": "importer", "through_sequence": 0, "pending": None}
        else:
            expected = (
                {
                    "source_stage": "pending",
                    "source_accept": "accepted",
                    "source_discard": "discarded",
                }[operation]
                if stage == "after"
                else "pending"
            )
            assert outcome["decision"]["state"] == expected
            assert position["through_sequence"] == int(expected != "pending")
            assert (position["pending"] is not None) == (expected == "pending")
            if committed_accept:
                assert outcome["current"]["record_id"] == outcome["decision"]["record"]["record_id"]
                assert outcome["current"]["revision"] == 1
        for secret in (
            action["content"],
            action["topic"],
            SESSION,
            source_request_identity(action)["expected_digest"],
        ):
            assert secret not in json.dumps([outcome, position])
        assert conn.total_changes == 0
        assert list(conn.iterdump()) == before
    with opened(path) as (sdk, _, conn):
        replay = sdk.execute(operation, payload)
        assert replay["replayed"] is (stage == "after")
        assert counts(conn) == ((1, 1, 1, 1) if operation == "source_accept" else (0, 0, 0, 1))


def test_pending_survives_restart_and_serializes_simultaneous_admissions(tmp_path):
    path = tmp_path / "admit.db"
    actions = [request("a"), request("b")]
    barrier = Barrier(2)
    with opened(path) as (left, _, _), opened(path) as (right, _, _):

        def admit(sdk, action):
            barrier.wait(timeout=5)
            try:
                return sdk.execute("source_stage", action)["data"]["request_id"]
            except MemoryError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(admit, sdk, action)
                for sdk, action in zip((left, right), actions, strict=True)
            ]
            outcomes = [future.result(timeout=15) for future in futures]
        assert outcomes.count("source_pending") == 1
        winner = next(action for action in actions if action["request_id"] in outcomes)
    with opened(path) as (sdk, _, conn):
        assert cursor(sdk)["pending"]["request_id"] == winner["request_id"]
        with pytest.raises(MemoryError, match="source_pending"):
            sdk.execute("source_stage", request("c"))
        assert counts(conn) == (0, 0, 0, 1)
        sdk.execute("source_discard", source_request_identity(winner))
        sdk.execute("source_stage", request("c", sequence=1, content="another payload"))
        assert cursor(sdk)["through_sequence"] == 1
        assert cursor(sdk)["pending"]["source_sequence"] == 2


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_suppression_serializes_against_already_staged_fresh_accept(tmp_path, operation):
    path, original = tmp_path / "suppressed.db", request()
    duplicate = request("duplicate", consumer="another")
    with opened(path) as (sdk, _, _):
        sdk.execute("source_stage", original)
        record = sdk.execute("source_accept", original)["data"]["record"]
        sdk.execute("source_stage", duplicate)
        mutation = {
            "request_id": operation,
            "record_id": record["record_id"],
            "expected_revision": 1,
        }
        if operation == "correct":
            mutation["content"] = "synthetic corrected source"
        sdk.execute(operation, mutation)
    with opened(path) as (sdk, _, conn):
        before = list(conn.iterdump())
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_accept", duplicate)
        with pytest.raises(MemoryError, match="source_suppressed"):
            sdk.execute("source_stage", request("fresh", consumer="third"))
        assert list(conn.iterdump()) == before
        assert status(sdk, original)["suppressed"]
        assert status(sdk, original)["current"]["revision"] == 2
        assert status(sdk, duplicate)["suppressed"]
        assert cursor(sdk, "another")["pending"]["request_id"] == "duplicate"
        sdk.execute("source_discard", source_request_identity(duplicate))
        assert cursor(sdk, "another")["through_sequence"] == 1
        assert sdk.execute("source_accept", original)["replayed"]
        assert counts(conn) == (1, 2, 2, 2)


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_status_receipt_current_and_suppression_share_one_snapshot(tmp_path, operation):
    path, action = tmp_path / "snapshot.db", request()
    acquired, committing = Event(), Event()

    class Reader(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "SELECT id FROM namespace":
                self.armed = False
                acquired.set()
                assert committing.wait(5)
            return result

    class Writer(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and sql == "COMMIT":
                committing.set()
            return super().execute(sql, *args)

    with opened(path, factory=Reader) as (reader, _, rc):
        reader.execute("source_stage", action)
        receipt = reader.execute("source_accept", action)["data"]["record"]
        with opened(path, factory=Writer) as (writer, _, wc):
            mutation = {
                "request_id": operation,
                "record_id": receipt["record_id"],
                "expected_revision": 1,
            }
            if operation == "correct":
                mutation.update(content="corrected synthetic", expires_at="2000-01-01T00:00:00Z")
            rc.armed = wc.armed = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                reading = pool.submit(status, reader, action)
                assert acquired.wait(5)
                writing = pool.submit(writer.execute, operation, mutation)
                old = reading.result(timeout=15)
                writing.result(timeout=15)
            fresh = status(reader, action)
            assert old["decision"]["record"] == fresh["decision"]["record"] == receipt
            assert old["current"]["revision"] == 1 and old["suppressed"] is False
            assert fresh["current"]["revision"] == 2 and fresh["suppressed"] is True
            assert fresh["current"]["expired"] is (operation == "correct")
            assert fresh["current"]["status"] == (
                "active" if operation == "correct" else "forgotten"
            )


@pytest.mark.parametrize(
    "readonly,model,reason",
    [
        (True, False, "read_only_backend"),
        (False, True, "source_scope_required"),
    ],
)
@pytest.mark.parametrize("operation", ["source_stage", "source_accept", "source_discard"])
def test_write_authority_refusal_does_not_change_store(
    tmp_path, readonly, model, reason, operation
):
    path, action = tmp_path / "authority.db", request()
    with opened(path) as (sdk, _, _):
        sdk.execute("source_stage", action)
    with opened(path, readonly=readonly, model=model) as (_, backend, conn):
        before = list(conn.iterdump())
        payload = source_request_identity(action) if operation == "source_discard" else action
        with pytest.raises(MemoryError, match=reason):
            backend.execute(operation, payload)
        assert list(conn.iterdump()) == before


def test_schema11_migration_preserves_payload_and_rolls_back_on_failure(tmp_path):
    path = tmp_path / "migration.db"
    with opened(path) as (sdk, _, conn):
        sdk.execute("remember", {"request_id": "seed", "content": "synthetic legacy payload"})
        conn.execute("DROP TABLE retained_source_decisions")
        conn.execute("PRAGMA user_version=11")
        before = list(conn.iterdump())
        payload = conn.execute("SELECT * FROM records").fetchall()

    class FailMigration(sqlite3.Connection):
        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if sql == "PRAGMA user_version=12":
                raise sqlite3.OperationalError("synthetic migration interruption")
            return result

    with pytest.raises(MemoryError):
        with opened(path, factory=FailMigration):
            pytest.fail("migration failure was swallowed")
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone() == (11,)
        assert list(conn.iterdump()) == before
    finally:
        conn.close()
    with opened(path) as (sdk, _, conn):
        assert conn.execute("PRAGMA user_version").fetchone() == (12,)
        assert conn.execute("SELECT * FROM records").fetchall() == payload
        assert counts(conn) == (1, 1, 1, 0)
        assert cursor(sdk)["through_sequence"] == 0
        migrated = [line for line in conn.iterdump() if "retained_source_decisions" not in line]
        assert migrated == before


@pytest.mark.parametrize("quota", ["source_limit", "source_consumer_limit"])
def test_full_source_quotas_do_not_block_forgetting_or_suppression(tmp_path, quota):
    path, action = tmp_path / "quota.db", request()
    with opened(path) as (sdk, _, conn):
        sdk.execute("source_stage", action)
        receipt = sdk.execute("source_accept", action)["data"]["record"]
        # Populate valid terminal metadata directly to exercise the exact quota boundary,
        # without turning this recovery test into a thousand admission round trips.
        count = 999 if quota == "source_limit" else 63
        conn.execute("BEGIN IMMEDIATE")
        for index in range(count):
            seed = request(
                f"quota-{index}",
                consumer="importer" if quota == "source_limit" else f"consumer{index}",
                sequence=index + 1 if quota == "source_limit" else 0,
                content=f"synthetic discarded {index}",
            )
            conn.execute(
                "INSERT INTO retained_source_decisions VALUES "
                "(?,?,?,?,?,?,?,?,'discarded',NULL,NULL,1)",
                (
                    seed["request_id"],
                    seed["consumer_id"],
                    seed["expected_sequence"] + 1,
                    source_request_identity(seed)["expected_digest"],
                    seed["source"]["identity"],
                    seed["source"]["fingerprint"],
                    "user",
                    seed["source"]["receipt_id"],
                ),
            )
        conn.execute("COMMIT")
    with opened(path) as (sdk, _, conn):
        with pytest.raises(MemoryError, match=quota):
            sdk.execute("source_stage", request("overflow", consumer="new", content="new data"))
        forgotten = sdk.execute(
            "forget",
            {
                "request_id": "forget",
                "record_id": receipt["record_id"],
                "expected_revision": 1,
            },
        )["data"]
        assert forgotten["status"] == "forgotten"
        assert status(sdk, action)["suppressed"]
        assert (
            conn.execute("SELECT content,topic,source,session_ref FROM records").fetchone()
            == (None,) * 4
        )
        assert counts(conn) == (1, 2, 2, count + 1)
    with opened(path, readonly=True) as (sdk, _, _):
        outcome = status(sdk, action)
        assert outcome["current"]["status"] == "forgotten" and outcome["suppressed"]


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_mutation_writer_lock_prevents_racing_accept_from_bypassing_suppression(
    tmp_path, operation
):
    path, action = tmp_path / "write-race.db", request()
    duplicate = request("racing", consumer="other")
    mutation_locked, accept_attempting = Event(), Event()

    class Mutation(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "BEGIN IMMEDIATE":
                self.armed = False
                mutation_locked.set()
                assert accept_attempting.wait(5)
            return result

    class Acceptance(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and sql == "BEGIN IMMEDIATE":
                self.armed = False
                accept_attempting.set()
            return super().execute(sql, *args)

    with opened(path, factory=Mutation) as (mutator, _, mc):
        mutator.execute("source_stage", action)
        receipt = mutator.execute("source_accept", action)["data"]["record"]
        mutator.execute("source_stage", duplicate)
        with opened(path, factory=Acceptance) as (acceptor, _, ac):
            mutation = {
                "request_id": operation,
                "record_id": receipt["record_id"],
                "expected_revision": 1,
            }
            if operation == "correct":
                mutation["content"] = "synthetic corrected race"
            mc.armed = ac.armed = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                changing = pool.submit(mutator.execute, operation, mutation)
                assert mutation_locked.wait(5)
                accepting = pool.submit(acceptor.execute, "source_accept", duplicate)
                changing.result(timeout=15)
                with pytest.raises(MemoryError, match="source_suppressed"):
                    accepting.result(timeout=15)
            assert counts(mc) == (1, 2, 2, 2)
            assert status(acceptor, duplicate)["decision"]["state"] == "pending"
            assert status(acceptor, duplicate)["suppressed"]
