"""Bounded review-only worker receipts. No task writes, handles or credentials stored.

An owner is a consumer-instance epoch, not a PID or a claim of process liveness.
Foreign owners are never adopted or declared dead. A crash may lose a result but
cannot make a consumed request eligible again. Retention is indefinite, at most
64 entries; capacity refuses new grants rather than evicting tombstones.
"""

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager

from personal_agent import PLUGIN_ID
from personal_agent.task_cli import (
    _private_database_file,
    _private_storage_directory,
    current_profile_home,
)
from personal_agent.tasks import TaskError

MAX_GRANTS = 64
MAX_RESULT_CHARS = 32000
APPLICATION_ID = 0x57504C31
SCHEMA = """CREATE TABLE grants (
request_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, route TEXT NOT NULL,
task_id TEXT NOT NULL, revision INTEGER NOT NULL, context_hash TEXT NOT NULL,
owner TEXT NOT NULL, expires_at REAL NOT NULL,
state TEXT NOT NULL CHECK(state IN
('authorized','claimed','revoked','expired','stale','completed')),
result TEXT, route_fingerprint TEXT)"""


class Ledger:
    def __init__(self, home, owner):
        self.home, self.owner = home, owner

    @contextmanager
    def connection(self):
        if not self.home.is_dir() or current_profile_home() != self.home:
            raise TaskError("profile_context_changed")
        expected = self.home / "plugin-data" / PLUGIN_ID
        for directory in (self.home, expected.parent, expected):
            _private_storage_directory(directory)
        from plugins.plugin_storage import plugin_data_dir

        directory = plugin_data_dir(PLUGIN_ID)
        if directory.resolve() != expected:
            raise TaskError("unsafe_storage_path")
        for parent in (expected.parent, expected):
            _private_storage_directory(parent)
        path = directory / "text-worker-ledger.sqlite3"
        for suffix in ("-journal", "-wal", "-shm"):
            _private_database_file(path.with_name(path.name + suffix), create=False)
        _private_database_file(path)
        conn = sqlite3.connect(path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            app = conn.execute("PRAGMA application_id").fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            objects = conn.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if not app and not version and not objects:
                conn.execute(SCHEMA)
                conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
                conn.execute("PRAGMA user_version=1")
            elif (
                app != APPLICATION_ID
                or version != 1
                or [tuple(row) for row in objects] != [("grants", SCHEMA)]
            ):
                raise TaskError("worker_ledger_schema_mismatch")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _find(conn, key):
        session, route, request_id = key
        row = conn.execute("SELECT * FROM grants WHERE request_id=?", (request_id,)).fetchone()
        if row is not None and (row["session_id"], row["route"]) != (session, route):
            raise TaskError("request_id_scope_conflict")
        if row is None:
            return None
        row = dict(row)
        fingerprint = row["route_fingerprint"]
        if row["state"] in ("claimed", "completed"):
            if type(fingerprint) is not str or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
                raise TaskError("worker_ledger_corrupt")
        elif fingerprint is not None:
            raise TaskError("worker_ledger_corrupt")
        if row["state"] == "completed":
            try:
                if type(row["result"]) is not str or len(row["result"]) > MAX_RESULT_CHARS + 256:
                    raise ValueError("invalid receipt size")
                envelope = json.loads(row["result"])
                data = envelope["data"]
                encoded = json.dumps(data, ensure_ascii=True, sort_keys=True)
                if (
                    set(envelope) != {"data", "sha256", "route_fingerprint"}
                    or envelope["route_fingerprint"] != fingerprint
                    or hashlib.sha256((fingerprint + encoded).encode("ascii")).hexdigest()
                    != envelope["sha256"]
                    or set(data)
                    != {
                        "state",
                        "ready",
                        "task_id",
                        "snapshot_revision",
                        "draft",
                        "result_hash",
                        "notice",
                    }
                    or data["task_id"] != row["task_id"]
                    or type(data["snapshot_revision"]) is not int
                    or data["snapshot_revision"] != row["revision"]
                    or data["ready"] is not True
                    or data["state"] not in ("SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED")
                    or data["notice"]
                    != "Untrusted planning draft. No task state or external action changed."
                    or (
                        data["state"] == "SUCCEEDED"
                        and (type(data["draft"]) is not str or not data["draft"].strip())
                    )
                    or (data["state"] != "SUCCEEDED" and data["draft"] is not None)
                    or data["draft"] is not None
                    and type(data["draft"]) is not str
                    or type(data["result_hash"]) is not str
                    or re.fullmatch(r"[0-9a-f]{64}", data["result_hash"]) is None
                ):
                    raise ValueError("invalid receipt")
                row["result"] = encoded
            except ValueError, TypeError, KeyError:
                raise TaskError("worker_ledger_corrupt") from None
        elif row["result"] is not None:
            raise TaskError("worker_ledger_corrupt")
        return row

    def get(self, key):
        with self.connection() as conn:
            return self._find(conn, key)

    def authorize(self, key, task_id, revision, context_hash, expires_at):
        with self.connection() as conn:
            prior = self._find(conn, key)
            if prior:
                if (prior["task_id"], prior["revision"]) != (task_id, revision):
                    raise TaskError("request_id_conflict")
                return prior, True
            if conn.execute("SELECT count(*) FROM grants").fetchone()[0] >= MAX_GRANTS:
                raise TaskError("grant_capacity_reached")
            session, route, request_id = key
            conn.execute(
                "INSERT INTO grants VALUES (?,?,?,?,?,?,?,?, 'authorized',NULL,NULL)",
                (
                    request_id,
                    session,
                    route,
                    task_id,
                    revision,
                    context_hash,
                    self.owner,
                    expires_at,
                ),
            )
            return self._find(conn, key), False

    def claim(self, key, context_hash, route_fingerprint):
        if (
            type(route_fingerprint) is not str
            or re.fullmatch(r"[0-9a-f]{64}", route_fingerprint) is None
        ):
            raise TaskError("worker_route_unavailable")
        with self.connection() as conn:
            row = self._find(conn, key)
            if row is None:
                raise TaskError("no_task_worker_grant")
            if row["owner"] != self.owner or row["state"] != "authorized":
                return row, False
            state = "expired" if time.time() >= row["expires_at"] else "claimed"
            if row["context_hash"] != context_hash:
                state = "stale"
            fingerprint = route_fingerprint if state == "claimed" else None
            conn.execute(
                "UPDATE grants SET state=?,route_fingerprint=? WHERE request_id=?",
                (state, fingerprint, key[2]),
            )
            row["state"] = state
            row["route_fingerprint"] = fingerprint
            return row, state == "claimed"

    def revoke(self, key, state="revoked"):
        if state not in ("revoked", "stale", "expired"):
            raise ValueError("invalid terminal state")
        with self.connection() as conn:
            row = self._find(conn, key)
            if row is None:
                raise TaskError("unknown_grant")
            # Explicit native revocation can revoke an unclaimed grant across owners.
            conn.execute(
                "UPDATE grants SET state=? WHERE request_id=? AND state='authorized'",
                (state, key[2]),
            )
            return self._find(conn, key)

    def revoke_owned(self):
        with self.connection() as conn:
            conn.execute(
                "UPDATE grants SET state='revoked' WHERE owner=? AND state='authorized'",
                (self.owner,),
            )

    def complete(self, key, result):
        encoded = json.dumps(result, ensure_ascii=True, sort_keys=True)
        if len(encoded) > MAX_RESULT_CHARS:
            raise TaskError("worker_result_too_large")
        with self.connection() as conn:
            row = self._find(conn, key)
            if row is None or row["owner"] != self.owner or row["state"] != "claimed":
                raise TaskError("worker_ledger_claim_lost")
            fingerprint = row["route_fingerprint"]
            envelope = json.dumps(
                {
                    "data": result,
                    "route_fingerprint": fingerprint,
                    "sha256": hashlib.sha256((fingerprint + encoded).encode("ascii")).hexdigest(),
                },
                ensure_ascii=True,
                sort_keys=True,
            )
            conn.execute(
                "UPDATE grants SET state='completed',result=? WHERE request_id=?",
                (envelope, key[2]),
            )
            self._find(conn, key)  # Validate before commit and before any draft exposure.
