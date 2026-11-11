"""Review-only metadata journal for explicit source receipt reconciliation.

Two local transactions, never two-database atomicity or canonical memory writes.
Trusted isolated owner harness only; no background runner or production import.
"""

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from hermes_state import SessionDB
from hermes_state_checkpoint_sources import (
    commit_source_request,
    source_receipt_status,
    source_request_identity,
)

MAX_ATTEMPTS = 4096


class RecoveryError(ValueError):
    """Fixed error codes without request, path or database exception payloads."""

    def __init__(self, code):
        safe = {
            "invalid_request",
            "journal_unavailable",
            "binding_mismatch",
            "attempt_conflict",
            "capacity",
            "attempt_missing",
            "host_unavailable",
            "host_commit_unconfirmed",
            "receipt_mismatch",
            "journal_write_unconfirmed",
        }
        super().__init__(code if type(code) is str and code in safe else "operation_failed")


def _require(condition, code="invalid_request"):
    if not condition:
        raise RecoveryError(code)


def _text(value, maximum):
    _require(type(value) is str and 0 < len(value) <= maximum)
    value.encode("utf-8")
    return value


def _snapshot(request, session_id):
    try:
        identity = source_request_identity(session_id, request)
        snapshot = json.loads(json.dumps(request, allow_nan=False))
        _require(source_request_identity(session_id, snapshot) == identity)
        return snapshot, identity
    except Exception:
        raise RecoveryError("invalid_request") from None


class RecoveryJournal:
    """Explicit private journal, fixed to one existing host file and session.

    Construction opens an existing journal by default. Creation is separate and
    exclusive; loss of the journal is not silently treated as an empty queue.
    File identity detects ordinary replacement, not malicious clones or rollback.
    """

    def __init__(self, path, host_path, session_id, *, create=False):
        try:
            self.path = Path(path).absolute()
            self.host = Path(host_path).resolve(strict=True)
            self.session = _text(session_id, 256)
            host_stat = self.host.stat()
            _require(stat.S_ISREG(host_stat.st_mode), "host_unavailable")
            self.binding = (str(self.host), host_stat.st_dev, host_stat.st_ino, self.session)
            parent = self.path.parent.stat()
            _require(
                parent.st_uid == os.getuid() and stat.S_IMODE(parent.st_mode) == 0o700,
                "journal_unavailable",
            )
            if create:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                with self._connection(check_binding=False) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    conn.execute(
                        "CREATE TABLE journal_binding (singleton INTEGER PRIMARY KEY CHECK "
                        "(singleton=1), version INTEGER NOT NULL CHECK (version=1), "
                        "host_path TEXT NOT NULL, host_device INTEGER NOT NULL, "
                        "host_inode INTEGER NOT NULL, session_id TEXT NOT NULL)"
                    )
                    conn.execute("INSERT INTO journal_binding VALUES (1,1,?,?,?,?)", self.binding)
                    conn.execute(
                        "CREATE TABLE attempts (sequence INTEGER PRIMARY KEY, "
                        "attempt_id TEXT NOT NULL UNIQUE, receipt_id TEXT NOT NULL, "
                        "source_count INTEGER NOT NULL, recorded INTEGER NOT NULL DEFAULT 0 "
                        "CHECK(recorded IN (0,1)))"
                    )
                    conn.commit()
            with self._connection():
                pass
        except RecoveryError:
            raise
        except Exception:
            raise RecoveryError("journal_unavailable") from None

    @contextmanager
    def _connection(self, *, check_binding=True):
        conn = None
        try:
            info = self.path.lstat()
            _require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o600,
                "journal_unavailable",
            )
            _require((info.st_dev, info.st_ino) != self.binding[1:3], "binding_mismatch")
            conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", timeout=1, uri=True)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA synchronous=FULL")
            if check_binding:
                row = conn.execute("SELECT * FROM journal_binding WHERE singleton=1").fetchone()
                _require(row is not None and row["version"] == 1, "binding_mismatch")
                _require(tuple(row)[2:] == self.binding, "binding_mismatch")
            yield conn
        except RecoveryError:
            raise
        except Exception:
            raise RecoveryError("journal_write_unconfirmed") from None
        finally:
            if conn is not None:
                conn.close()

    def _host_exists(self):
        try:
            current = self.host.stat()
            _require((current.st_dev, current.st_ino) == self.binding[1:3], "host_unavailable")
        except Exception:
            raise RecoveryError("host_unavailable") from None

    def stage(self, request):
        """Persist bounded exact intent before native admission, without any payload."""
        snapshot, identity = _snapshot(request, self.session)
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (snapshot["attempt_id"],)
            ).fetchone()
            if prior is not None:
                _require(
                    prior["receipt_id"] == identity["receipt_id"]
                    and prior["source_count"] == identity["source_count"],
                    "attempt_conflict",
                )
            else:
                _require(
                    conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] < MAX_ATTEMPTS,
                    "capacity",
                )
                conn.execute(
                    "INSERT INTO attempts (attempt_id, receipt_id, source_count) VALUES (?,?,?)",
                    (snapshot["attempt_id"], identity["receipt_id"], identity["source_count"]),
                )
            conn.commit()
        return identity

    def submit(self, request):
        """Explicit same-request submission only; reconcile never calls this method.

        A commit error leaves durable intent. Reconcile before considering a retry;
        if absent, only an explicitly resupplied identical request may be retried.
        """
        snapshot, _ = _snapshot(request, self.session)
        self.stage(snapshot)
        self._host_exists()
        try:
            with SessionDB(self.host) as writer:
                commit_source_request(writer, self.session, snapshot)
        except Exception:
            raise RecoveryError("host_commit_unconfirmed") from None
        return self.reconcile(snapshot["attempt_id"])

    def pending(self, *, after=0, limit=100):
        """Bounded sequence-key pages; the retained sequence is never renumbered."""
        _require(type(after) is int and 0 <= after < 2**63)
        _require(type(limit) is int and 0 < limit <= 100)
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT sequence, attempt_id FROM attempts "
                "WHERE recorded=0 AND sequence>? ORDER BY sequence LIMIT ?",
                (after, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _record(self, conn, attempt_id):
        conn.execute("UPDATE attempts SET recorded=1 WHERE attempt_id=?", (attempt_id,))

    def reconcile(self, attempt_id):
        """Read host receipt, then idempotently record historical accounting only.

        Availability is a fresh host snapshot observation, never durable recall
        permission. Deletion may follow that read, including before local commit.
        """
        try:
            _text(attempt_id, 128)
        except Exception:
            raise RecoveryError("invalid_request") from None
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            _require(row is not None, "attempt_missing")
        self._host_exists()
        try:
            with SessionDB(self.host, read_only=True) as reader:
                observed = source_receipt_status(reader, self.session, attempt_id)
        except Exception:
            raise RecoveryError("host_unavailable") from None
        historical = bool(row["recorded"])
        if observed["status"] != "absent":
            _require(
                observed["receipt_id"] == row["receipt_id"]
                and observed["source_count"] == row["source_count"],
                "receipt_mismatch",
            )
            with self._connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._record(conn, attempt_id)
                conn.commit()
            historical = True
        return {
            "accounting": "recorded" if historical else "pending",
            "host_observation": observed["status"],
            "source_available_at_observation": observed["available"],
            "durable_memory_checkpoint": False,
        }
