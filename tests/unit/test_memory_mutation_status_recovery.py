"""Real SQLite crash, lost-ack and concurrent status-only reconciliation evidence."""

import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK, mutation_request_identity

NAMESPACE = "synthetic-receipt-recovery"
SESSION = "synthetic-recovery-session"


@contextmanager
def opened(path, *, readonly=False, connection_factory=sqlite3.Connection):
    connection = sqlite3.connect(
        f"file:{path}?mode=ro" if readonly else path,
        uri=readonly,
        isolation_level=None,
        check_same_thread=False,
        timeout=10,
        factory=connection_factory,
    )
    backend = create_backend()
    opener = backend.open_readonly if readonly else backend.open
    opener(connection, namespace_id=NAMESPACE, session_ref=SESSION)
    sdk = LocalMemorySDK(backend, LocalBinding(NAMESPACE, SESSION))
    try:
        yield sdk, backend, connection
    finally:
        sdk.close()
        connection.close()


def query(sdk, identity):
    result = sdk.execute("mutation_receipt_status", identity)
    assert result["replayed"] is False
    return result["data"]


CHILD = r"""
import json, os, sqlite3, sys
from personal_agent.local_memory import create_backend
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
class Crash(sqlite3.Connection):
    armed = False
    def execute(self, sql, *args):
        if self.armed and sql == 'COMMIT' and sys.argv[2] == 'before':
            os._exit(73)
        result = super().execute(sql, *args)
        if self.armed and sql == 'COMMIT' and sys.argv[2] == 'after':
            os._exit(73)
        return result
connection = sqlite3.connect(sys.argv[1], isolation_level=None, factory=Crash)
backend = create_backend()
backend.open(connection, namespace_id='synthetic-receipt-recovery',
             session_ref='synthetic-recovery-session')
sdk = LocalMemorySDK(backend, LocalBinding('synthetic-receipt-recovery',
                                         'synthetic-recovery-session'))
connection.armed = True
sdk.execute(sys.argv[3], json.loads(sys.argv[4]))
raise RuntimeError('crash point not reached')
"""


@pytest.mark.parametrize("stage", ["before", "after"])
@pytest.mark.parametrize("operation", ["remember", "correct", "forget"])
def test_process_crash_status_without_replaying_mutation(tmp_path, operation, stage):
    path = tmp_path / "crash.sqlite"
    with opened(path) as (sdk, _, connection):
        seed = sdk.execute("remember", {"request_id": "seed", "content": "private seed"})["data"]
        action = {"request_id": "crashed"}
        if operation == "remember":
            action["content"] = "private new"
        else:
            action.update(record_id=seed["record_id"], expected_revision=1)
            if operation == "correct":
                action["content"] = "private corrected"
        identity = mutation_request_identity(operation, action)
        before = list(connection.iterdump())
    child = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(path), stage, operation, json.dumps(action)],
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
    with opened(path) as (sdk, backend, connection):
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        if stage == "before":
            assert list(connection.iterdump()) == before
        after_recovery = list(connection.iterdump())
        calls = []
        original = backend._mutate

        def forbidden_mutation(*args, **kwargs):
            calls.append(args)
            raise AssertionError("status must never replay a mutation")

        backend._mutate = forbidden_mutation
        outcome = query(sdk, identity)
        backend._mutate = original
        assert not calls
        assert outcome["state"] == ("committed" if stage == "after" else "absent_at_snapshot")
        if stage == "after":
            assert outcome["receipt"]["operation"] == operation
            assert outcome["receipt"]["request_id"] == action["request_id"]
            assert outcome["current"]["revision"] == (1 if operation == "remember" else 2)
        else:
            assert set(outcome) == {"state", "evaluated_at"}
        assert list(connection.iterdump()) == after_recovery
    with opened(path, readonly=True) as (sdk, _, _):
        assert query(sdk, identity)["state"] == outcome["state"]


class LostAck:
    def __init__(self, backend):
        self.backend = backend
        self.mutations = 0

    def describe(self):
        return self.backend.describe()

    def execute(self, operation, request):
        result = self.backend.execute(operation, request)
        if operation in {"remember", "correct", "forget"}:
            self.mutations += 1
            raise RuntimeError("private lost acknowledgment")
        return result

    def close(self):
        pass


def test_lost_ack_recovers_readonly_identity_without_payload_or_replay(tmp_path):
    path = tmp_path / "lost-ack.sqlite"
    action = {"request_id": "lost-ack", "content": "private payload", "topic": "private topic"}
    identity = mutation_request_identity("remember", action)
    with opened(path) as (_, backend, connection):
        wrapper = LostAck(backend)
        sdk = LocalMemorySDK(wrapper, LocalBinding(NAMESPACE, SESSION))
        with pytest.raises(MemoryError, match="outcome_unknown"):
            sdk.execute("remember", action)
        before = list(connection.iterdump())
        outcome = query(sdk, identity)
        assert outcome["state"] == "committed" and wrapper.mutations == 1
        assert list(connection.iterdump()) == before
        encoded = json.dumps(outcome)
        for secret in (action["content"], action["topic"], SESSION, identity["expected_digest"]):
            assert secret not in encoded
    with opened(path, readonly=True) as (sdk, backend, connection):
        before = list(connection.iterdump())
        changes = connection.total_changes
        statements = []
        connection.set_trace_callback(statements.append)
        assert query(sdk, identity)["receipt"] == outcome["receipt"]
        missing = {**identity, "request_id": "never-submitted"}
        assert query(sdk, missing)["state"] == "absent_at_snapshot"
        assert connection.total_changes == changes == 0
        assert list(connection.iterdump()) == before
        assert not any(
            sql.lstrip()
            .upper()
            .startswith(
                (
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "REPLACE",
                    "CREATE",
                    "ALTER",
                    "DROP",
                    "BEGIN IMMEDIATE",
                )
            )
            for sql in statements
        )
        assert connection.execute("SELECT count(*) FROM consumer_cursors").fetchone() == (0,)
        with pytest.raises(MemoryError, match="read_only_backend"):
            backend.execute("remember", action)


@pytest.mark.parametrize("operation", ["correct", "forget"])
def test_status_current_and_receipt_share_snapshot_during_writer_race(tmp_path, operation):
    path = tmp_path / "race.sqlite"
    action = {"content": "private original", "request_id": "remember"}
    identity = mutation_request_identity("remember", action)
    snapshot_acquired, writer_at_commit = Event(), Event()

    class Reader(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            result = super().execute(sql, *args)
            if self.armed and sql == "SELECT id FROM namespace":
                self.armed = False
                snapshot_acquired.set()
                assert writer_at_commit.wait(5)
            return result

    class Writer(sqlite3.Connection):
        armed = False

        def execute(self, sql, *args):
            if self.armed and sql == "COMMIT":
                writer_at_commit.set()
            return super().execute(sql, *args)

    # Open both connections before starting the snapshot. Never raw-open/close
    # the database inode: that can discard SQLite's process-scoped POSIX locks.
    with opened(path, connection_factory=Reader) as (reader, _, read_conn):
        receipt = reader.execute("remember", action)["data"]
        with opened(path, connection_factory=Writer) as (writer, _, write_conn):
            update = {
                "record_id": receipt["record_id"],
                "expected_revision": 1,
                "request_id": operation,
            }
            if operation == "correct":
                update.update(content="private changed", expires_at="2000-01-01T00:00:00Z")
            read_conn.armed = True
            write_conn.armed = True
            with ThreadPoolExecutor(max_workers=2) as pool:
                reading = pool.submit(query, reader, identity)
                assert snapshot_acquired.wait(5)
                writing = pool.submit(writer.execute, operation, update)
                old = reading.result(timeout=10)
                changed = writing.result(timeout=10)["data"]
            assert old["receipt"] == receipt
            assert old["current"] == {
                "record_id": receipt["record_id"],
                "revision": 1,
                "status": "active",
                "expired": False,
            }
            fresh = query(reader, identity)
            assert fresh["receipt"] == receipt
            assert fresh["current"] == {
                "record_id": receipt["record_id"],
                "revision": 2,
                "status": changed["status"],
                "expired": operation == "correct",
            }
            assert query(reader, mutation_request_identity(operation, update))["receipt"] == changed
