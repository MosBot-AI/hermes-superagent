"""Abrupt-process recovery of synthetic memory writes, without a host or network."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from personal_agent.local_memory import create_backend

CRASH_EXIT = 73
CHILD = r"""
import json, os, sqlite3, sys
from personal_agent.local_memory import create_backend

stage = sys.argv[2]
class Crash(sqlite3.Connection):
    armed = False
    def execute(self, sql, *args):
        if self.armed and stage == 'before_commit' and sql == 'COMMIT':
            os._exit(73)
        result = super().execute(sql, *args)
        markers = {
            'record': ('INSERT INTO records', 'UPDATE records'),
            'event': ('INSERT INTO events',),
            'receipt': ('INSERT INTO receipts',),
            'candidate': ('UPDATE memory_candidates',),
            'after_commit': ('COMMIT',),
        }
        if self.armed and any(sql.startswith(m) for m in markers.get(stage, ())):
            os._exit(73)
        return result

conn = sqlite3.connect(sys.argv[1], factory=Crash)
backend = create_backend()
backend.open(conn, namespace_id='profile:test', session_ref='session:test',
             source_kind='explicit_local_operator')
conn.armed = True
backend.execute(sys.argv[3], json.loads(sys.argv[4]))
raise RuntimeError('requested crash point was not reached')
"""


def opened(path):
    conn = sqlite3.connect(path)
    backend = create_backend()
    backend.open(
        conn,
        namespace_id="profile:test",
        session_ref="session:test",
        source_kind="explicit_local_operator",
    )
    return backend, conn


def proposed(backend):
    backend._source_kind = "activated_session_model"
    result = backend.execute(
        "candidate_propose",
        {
            "request_id": "synthetic-proposal",
            "content": "偏好中文",
            "topic": "",
            "quote": "中文",
            "quote_start": 0,
            "source_digest": "a" * 64,
            "source_turn": "b" * 64,
        },
    )
    backend._source_kind = "explicit_local_operator"
    return {
        "candidate_id": result["data"]["candidate_id"],
        "expected_revision": 1,
        "expires_at": None,
    }


def crash(path, stage, operation, request):
    result = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(path), stage, operation, json.dumps(request)],
        cwd=path.parent,
        env={
            "HOME": str(path.parent),
            "PATH": os.defpath,
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == CRASH_EXIT, result.stderr
    assert not result.stdout


def counts(conn):
    return tuple(
        conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("records", "events", "receipts", "memory_candidates")
    )


def assert_no_resurrection(backend, conn, request, record_id):
    replay = backend.execute("candidate_accept", request)
    assert replay["replayed"] and replay["data"]["record"]["record_id"] == record_id
    assert backend.execute("get", {"record_id": record_id})["status"] == "forgotten"
    assert backend.execute("recall", {"queries": ["中文"]})["items"] == []
    assert counts(conn) == (1, 2, 2, 1)
    assert (
        conn.execute(
            "SELECT content,topic,quote,quote_start,source_digest,session_ref "
            "FROM memory_candidates"
        ).fetchone()
        == (None,) * 6
    )
    assert (
        conn.execute("SELECT content,topic,source,session_ref FROM records").fetchone()
        == (None,) * 4
    )


@pytest.mark.parametrize(
    "stage", ["record", "event", "receipt", "candidate", "before_commit", "after_commit"]
)
def test_candidate_accept_abrupt_exit_is_atomic_and_retryable(tmp_path, stage):
    path = tmp_path / "memory.db"
    backend, conn = opened(path)
    request = proposed(backend)
    before = list(conn.iterdump())
    conn.close()

    crash(path, stage, "candidate_accept", request)
    backend, conn = opened(path)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    if stage != "after_commit":
        assert list(conn.iterdump()) == before
        assert counts(conn) == (0, 0, 0, 1)
    else:
        assert counts(conn) == (1, 1, 1, 1)
        assert (
            backend.execute("candidate_get", {"candidate_id": request["candidate_id"]})["data"][
                "state"
            ]
            == "accepted"
        )
    accepted = backend.execute("candidate_accept", request)
    assert accepted["replayed"] is (stage == "after_commit")
    assert counts(conn) == (1, 1, 1, 1)
    record_id = accepted["data"]["record"]["record_id"]
    conn.close()

    backend, conn = opened(path)
    assert backend.execute("candidate_accept", request) == {**accepted, "replayed": True}
    backend.execute(
        "forget", {"record_id": record_id, "expected_revision": 1, "request_id": "forget"}
    )
    conn.close()
    backend, conn = opened(path)
    assert_no_resurrection(backend, conn, request, record_id)
    conn.close()


@pytest.mark.parametrize("stage", ["record", "event", "receipt", "before_commit", "after_commit"])
def test_forget_abrupt_exit_keeps_tombstone_and_receipt_atomic(tmp_path, stage):
    path = tmp_path / "memory.db"
    backend, conn = opened(path)
    accept_request = proposed(backend)
    record_id = backend.execute("candidate_accept", accept_request)["data"]["record"]["record_id"]
    request = {"record_id": record_id, "expected_revision": 1, "request_id": "forget"}
    before = list(conn.iterdump())
    conn.close()

    crash(path, stage, "forget", request)
    backend, conn = opened(path)
    assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    if stage != "after_commit":
        assert list(conn.iterdump()) == before
        assert counts(conn) == (1, 1, 1, 1)
    else:
        assert_no_resurrection(backend, conn, accept_request, record_id)
    forgotten = backend.execute("forget", request)
    assert forgotten["replayed"] is (stage == "after_commit")
    assert_no_resurrection(backend, conn, accept_request, record_id)
    conn.close()

    backend, conn = opened(path)
    assert backend.execute("forget", request) == {**forgotten, "replayed": True}
    assert_no_resurrection(backend, conn, accept_request, record_id)
    conn.close()
