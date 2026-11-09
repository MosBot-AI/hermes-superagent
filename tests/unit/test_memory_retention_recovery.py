"""Abrupt-process expiry batch recovery: canonical rows, FTS, events and receipts."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from personal_agent.local_memory import create_backend

CUTOFF = "2001-01-01T00:00:00Z"
CHILD = r"""
import json, os, sqlite3, sys
from personal_agent.local_memory import create_backend

stage = sys.argv[2]
class Crash(sqlite3.Connection):
    armed = False
    updates = 0
    indexes = 0
    events = 0
    receipts = 0
    def execute(self, sql, *args):
        if self.armed and stage == 'before_commit' and sql == 'COMMIT':
            os._exit(73)
        result = super().execute(sql, *args)
        if self.armed:
            for name, marker in (
                ('updates', 'UPDATE records SET'),
                ('indexes', 'DELETE FROM memory_fts WHERE'),
                ('events', 'INSERT INTO events'),
                ('receipts', 'INSERT INTO receipts'),
            ):
                if sql.startswith(marker):
                    setattr(self, name, getattr(self, name) + 1)
                    if stage == name + str(getattr(self, name)):
                        os._exit(73)
            if stage == 'after_commit' and sql == 'COMMIT':
                os._exit(73)
        return result

conn = sqlite3.connect(sys.argv[1], isolation_level=None, factory=Crash)
backend = create_backend()
backend.open(conn, namespace_id='test', session_ref='test')
conn.armed = True
backend.execute('forget_expired', json.loads(sys.argv[3]))
raise RuntimeError('crash point not reached')
"""


def opened(path):
    conn = sqlite3.connect(path, isolation_level=None)
    backend = create_backend()
    backend.open(conn, namespace_id="test", session_ref="test")
    return backend, conn


@pytest.mark.parametrize(
    "stage",
    [
        "updates1",
        "indexes1",
        "events1",
        "receipts1",
        "updates2",
        "indexes2",
        "events2",
        "receipts2",
        "receipts3",
        "before_commit",
        "after_commit",
    ],
)
def test_batch_abrupt_exit_rolls_back_all_children_or_replays_final_receipt(tmp_path, stage):
    path = tmp_path / "memory.db"
    b, c = opened(path)
    ids = []
    for i in range(3):
        ids.append(
            b.execute(
                "remember",
                {
                    "content": f"canary{i} forgotten plaintext",
                    "request_id": f"seed{i}",
                    "expires_at": "2000-01-01T00:00:00Z",
                },
            )["data"]["record_id"]
        )
    preview = b.execute("expired_preview", {"before": CUTOFF, "limit": 2})
    action = {
        "before": CUTOFF,
        "limit": 2,
        "expected_snapshot": preview["snapshot"],
        "request_id": "crash-batch",
    }
    before = list(c.iterdump())
    b.close()
    c.close()
    result = subprocess.run(
        [sys.executable, "-B", "-c", CHILD, str(path), stage, json.dumps(action)],
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
    assert result.returncode == 73, result.stderr
    assert not result.stdout
    b, c = opened(path)
    try:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.execute("INSERT INTO memory_fts(memory_fts) VALUES ('integrity-check')")
        if stage != "after_commit":
            assert list(c.iterdump()) == before
        outcome = b.execute("forget_expired", action)
        assert outcome["replayed"] is (stage == "after_commit")
        assert outcome["data"]["forgotten_count"] == 2
        assert c.execute("SELECT count(*) FROM records").fetchone()[0] == 3
        assert c.execute("SELECT count(*) FROM events").fetchone()[0] == 5
        assert c.execute("SELECT count(*) FROM receipts").fetchone()[0] == 6
        assert (
            c.execute(
                "SELECT count(*) FROM memory_fts WHERE memory_fts MATCH 'canary0'"
            ).fetchone()[0]
            == 0
        )
        assert b.execute("get", {"record_id": ids[2]})["status"] == "active"
        b.close()
        c.close()
        b, c = opened(path)
        assert b.execute("forget_expired", action) == {**outcome, "replayed": True}
        assert b.execute("get", {"record_id": ids[2]})["status"] == "active"
    finally:
        b.close()
        c.close()
