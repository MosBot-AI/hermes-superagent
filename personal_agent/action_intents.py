"""Internal durable intent drafts, never approvals or executable authority.

Caller owns the private connection, truthful scope and trusted clock. Labels and
hashes do not authenticate a person. No plugin entry point, storage opener,
network, executor or approval issuer uses this module. Raw target/payload bytes
are hashed in memory and never stored. Hashes are not encryption or secrecy.
"""

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from .authorization import _identifier, _time

MAX_INTENTS = 1000
MAX_PAYLOAD_BYTES = 65536
MAX_TARGET_BYTES = 4096
MAX_LIFETIME = timedelta(hours=24)
_APPLICATION_ID = 0x5041494E
_VERSION = 1
_MAX_REVISION = 2**63 - 1
_KEYS = ("owner_id", "profile_id", "request_id")
_FIELDS = _KEYS + (
    "operation",
    "policy_revision",
    "epoch",
    "resource_revision",
    "expires_at",
    "target_digest",
    "payload_digest",
    "binding_digest",
    "created_at",
    "state",
    "revision",
)
_SCHEMA = {
    "intents": """CREATE TABLE intents (
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL, request_id TEXT NOT NULL,
        operation TEXT NOT NULL, policy_revision INTEGER NOT NULL, epoch INTEGER NOT NULL,
        resource_revision INTEGER NOT NULL, expires_at TEXT NOT NULL,
        target_digest TEXT NOT NULL, payload_digest TEXT NOT NULL, binding_digest TEXT NOT NULL,
        created_at TEXT NOT NULL, state TEXT NOT NULL
        CHECK(state IN ('draft','cancelled','expired')),
        revision INTEGER NOT NULL CHECK(revision IN (1,2)),
        PRIMARY KEY(owner_id, profile_id, request_id))""",
    "events": """CREATE TABLE events (
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL, request_id TEXT NOT NULL,
        revision INTEGER NOT NULL, outcome TEXT NOT NULL
        CHECK(outcome IN ('prepared','cancelled','expired')), recorded_at TEXT NOT NULL,
        PRIMARY KEY(owner_id, profile_id, request_id, revision))""",
}
_SPEC_FIELDS = set(_KEYS) | {
    "operation",
    "policy_revision",
    "epoch",
    "resource_revision",
    "expires_at",
    "target",
    "payload",
}


class IntentError(Exception):
    """Fixed redacted errors; never includes bytes, IDs, hashes or database text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Action intent operation failed ({code}).")


def _revision(value: object, *, zero: bool = False) -> bool:
    return type(value) is int and (0 if zero else 1) <= value <= _MAX_REVISION


def _key(value: object) -> dict:
    if type(value) is not dict or value.keys() != set(_KEYS):
        raise IntentError("invalid_request")
    value = cast(dict[str, Any], value)
    if not all(_identifier(value[key]) for key in _KEYS):
        raise IntentError("invalid_request")
    return dict(value)


def _stamp(value: datetime) -> str:
    if not _time(value):
        raise IntentError("invalid_time")
    return value.isoformat(timespec="microseconds")


def _parse_stamp(value: object) -> datetime:
    if type(value) is not str:
        raise IntentError("invalid_record")
    try:
        result = datetime.fromisoformat(value)
        if _stamp(result) != value:
            raise ValueError
        return result
    except ValueError, IntentError:
        raise IntentError("invalid_record") from None


def _digest(domain: bytes, value: bytes) -> str:
    return hashlib.sha256(domain + b"\x00" + value).hexdigest()


def _binding(record: dict) -> str:
    # Fixed primitive fields, exact bytes digests, explicit domain/version. No
    # normalization of target/payload: adapters must specify their serialization.
    binding_fields = _KEYS + (
        "operation",
        "policy_revision",
        "epoch",
        "resource_revision",
        "expires_at",
        "target_digest",
        "payload_digest",
    )
    data = {key: record[key] for key in binding_fields}
    return _digest(
        b"personal.action-intent.v1",
        json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )


def _spec(value: object) -> dict:
    if type(value) is not dict or value.keys() != _SPEC_FIELDS:
        raise IntentError("invalid_request")
    value = cast(dict[str, Any], value)
    result = _key({key: value[key] for key in _KEYS})
    if not _identifier(value["operation"]):
        raise IntentError("invalid_request")
    for field in ("policy_revision", "resource_revision", "epoch"):
        if not _revision(value[field], zero=field == "epoch"):
            raise IntentError("invalid_request")
        result[field] = value[field]
    result["operation"] = value["operation"]
    result["expires_at"] = _stamp(value["expires_at"])
    for field, maximum in (("target", MAX_TARGET_BYTES), ("payload", MAX_PAYLOAD_BYTES)):
        raw = value[field]
        if type(raw) is not bytes or not 1 <= len(raw) <= maximum:
            raise IntentError("invalid_request")
        result[field + "_digest"] = _digest(f"personal.action-{field}.v1".encode(), raw)
    result["binding_digest"] = _binding(result)
    return result


class ActionIntentStore:
    """Bounded metadata-only draft ledger on a dedicated, caller-secured connection.

    Every operation takes BEGIN IMMEDIATE and checks exact schema. Scope labels
    are selectors, not authentication. Prepared drafts cannot be approved or run.
    Clock is trusted local code and sampled after lock acquisition. The caller
    must supply an independently current clock, not an untrusted request field.
    No pruning, adoption, policy mutation, restore or clone-freshness guarantee.
    """

    def __init__(
        self, connection: sqlite3.Connection, *, clock: Callable[[], datetime] | None = None
    ):
        self._connection = connection
        self._clock = clock if clock is not None else lambda: datetime.now(UTC)
        self._initialized = False

    def _schema(self, *, create: bool = False) -> None:
        conn = self._connection
        if conn.execute("SELECT 1 FROM sqlite_temp_master LIMIT 1").fetchone():
            raise IntentError("unsupported_schema")
        app = conn.execute("PRAGMA application_id").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute(
            "SELECT name,sql FROM main.sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        ).fetchall()
        if create and app == 0 and version == 0 and not rows:
            for sql in _SCHEMA.values():
                conn.execute(sql)
            conn.execute(f"PRAGMA application_id={_APPLICATION_ID}")
            conn.execute(f"PRAGMA user_version={_VERSION}")
        elif app != _APPLICATION_ID:
            raise IntentError("foreign_database")
        elif version != _VERSION or len(rows) != len(_SCHEMA) or dict(rows) != _SCHEMA:
            raise IntentError("unsupported_schema")

    def _transaction(self, callback: Callable[[], Any], *, initialize: bool = False) -> Any:
        conn = self._connection
        began = False
        try:
            if not initialize and not self._initialized:
                raise IntentError("not_initialized")
            if conn.in_transaction:
                raise IntentError("connection_in_transaction")
            conn.execute("BEGIN IMMEDIATE")
            began = True
            self._schema(create=initialize)
            result = callback()
            conn.execute("COMMIT")
            return result
        except BaseException as error:
            if began and conn.in_transaction:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(error, IntentError):
                raise
            if isinstance(error, Exception):
                raise IntentError("storage_error") from None
            raise

    def initialize(self) -> None:
        self._initialized = False
        self._transaction(lambda: None, initialize=True)
        self._initialized = True

    def _now(self) -> datetime:
        try:
            now = self._clock()
            _stamp(now)
            return now
        except Exception:
            raise IntentError("invalid_time") from None

    def _record(self, key: dict) -> dict | None:
        row = self._connection.execute(
            f"SELECT {','.join(_FIELDS)} FROM main.intents "
            "WHERE owner_id=? AND profile_id=? AND request_id=?",
            tuple(key[name] for name in _KEYS),
        ).fetchone()
        if row is None:
            return None
        record = dict(zip(_FIELDS, row, strict=True))
        if (
            not all(_identifier(record[name]) for name in (*_KEYS, "operation"))
            or not all(_revision(record[name]) for name in ("policy_revision", "resource_revision"))
            or not _revision(record["epoch"], zero=True)
            or any(
                type(record[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", record[name]) is None
                for name in ("target_digest", "payload_digest", "binding_digest")
            )
            or record["binding_digest"] != _binding(record)
            or (record["state"], record["revision"])
            not in (("draft", 1), ("cancelled", 2), ("expired", 2))
        ):
            raise IntentError("invalid_record")
        created, expires = _parse_stamp(record["created_at"]), _parse_stamp(record["expires_at"])
        if not timedelta(0) < expires - created <= MAX_LIFETIME:
            raise IntentError("invalid_record")
        events = self._connection.execute(
            "SELECT revision,outcome,recorded_at FROM main.events "
            "WHERE owner_id=? AND profile_id=? AND request_id=? ORDER BY revision",
            tuple(key[name] for name in _KEYS),
        ).fetchall()
        expected = [(1, "prepared", record["created_at"])]
        if len(events) == 2 and record["revision"] == 2:
            terminal_time = _parse_stamp(events[1][2])
            if terminal_time < created or (
                record["state"] == "expired" and terminal_time < expires
            ):
                raise IntentError("invalid_record")
            expected.append((2, record["state"], events[1][2]))
        if [tuple(event) for event in events] != expected or len(events) != record["revision"]:
            raise IntentError("invalid_record")
        return record

    def _event(self, record: dict, outcome: str, now: datetime) -> None:
        self._connection.execute(
            "INSERT INTO main.events VALUES (?,?,?,?,?,?)",
            tuple(record[name] for name in _KEYS) + (record["revision"], outcome, _stamp(now)),
        )

    def _terminal(self, record: dict, state: str, now: datetime) -> dict:
        record = {**record, "state": state, "revision": 2}
        self._connection.execute(
            "UPDATE main.intents SET state=?,revision=2 WHERE owner_id=? AND profile_id=? "
            "AND request_id=? AND state='draft' AND revision=1",
            (state,) + tuple(record[name] for name in _KEYS),
        )
        self._event(record, state, now)
        return record

    def _expire(self, record: dict, now: datetime) -> dict:
        if now < _parse_stamp(record["created_at"]):
            raise IntentError("clock_regressed")
        if record["state"] == "draft" and now >= _parse_stamp(record["expires_at"]):
            return self._terminal(record, "expired", now)
        return record

    def prepare(self, specification: dict) -> dict:
        """Create metadata or inspect the exact retry; never renew or resurrect it.

        Request ID is unique within owner/profile. Changed bytes or any bound
        field conflict even after expiry/cancellation. A new ID is not a permit
        to retry an externally uncertain operation; this ledger sends nothing.
        """
        request = _spec(specification)
        key = {name: request[name] for name in _KEYS}

        def apply():
            now = self._now()
            existing = self._record(key)
            if existing is not None:
                if existing["binding_digest"] != request["binding_digest"]:
                    raise IntentError("request_conflict")
                return self._expire(existing, now)
            expires = _parse_stamp(request["expires_at"])
            if not timedelta(0) < expires - now <= MAX_LIFETIME:
                raise IntentError("invalid_expiry")
            if (
                self._connection.execute("SELECT count(*) FROM main.intents").fetchone()[0]
                >= MAX_INTENTS
            ):
                raise IntentError("capacity_exhausted")
            record = {**request, "created_at": _stamp(now), "state": "draft", "revision": 1}
            self._connection.execute(
                f"INSERT INTO main.intents VALUES ({','.join('?' for _ in _FIELDS)})",
                tuple(record[name] for name in _FIELDS),
            )
            self._event(record, "prepared", now)
            return record

        return self._transaction(apply)

    def inspect(self, key: dict) -> dict:
        """Return metadata; observation may atomically mark expiry, never execute."""
        key = _key(key)

        def apply():
            now = self._now()
            record = self._record(key)
            if record is None:
                raise IntentError("not_found")
            return self._expire(record, now)

        return self._transaction(apply)

    def review_pending(self, scope: dict, *, limit: int = 100) -> dict:
        """Return a bounded, coherent internal draft snapshot, never approval.

        Scope selectors are not authentication. Reconcile all scoped expiry
        before limiting output; this observation may commit terminal events.
        Results are metadata only and must not substitute for reviewing the
        actual action or rechecking authority immediately before execution.
        """
        if (
            type(scope) is not dict
            or scope.keys() != {"owner_id", "profile_id"}
            or not all(_identifier(value) for value in scope.values())
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise IntentError("invalid_request")
        scope = dict(scope)

        def apply():
            now = self._now()
            rows = self._connection.execute(
                "SELECT request_id FROM main.intents WHERE owner_id=? AND profile_id=? "
                "ORDER BY request_id LIMIT ?",
                (scope["owner_id"], scope["profile_id"], MAX_INTENTS + 1),
            ).fetchall()
            if len(rows) > MAX_INTENTS:
                raise IntentError("capacity_exhausted")
            records = []
            for (request_id,) in rows:
                record = self._record({**scope, "request_id": request_id})
                if record is None:
                    raise IntentError("invalid_record")
                records.append(record)
            pending = []
            for record in records:
                record = self._expire(record, now)
                if record["state"] == "draft":
                    pending.append(record)
            # Parsed instants, not variable-precision ISO text, determine order.
            pending.sort(key=lambda item: (_parse_stamp(item["expires_at"]), item["request_id"]))
            return {
                "observed_at": _stamp(now),
                "pending_count": len(pending),
                "truncated": len(pending) > limit,
                "items": pending[:limit],
            }

        return self._transaction(apply)

    def cancel(self, key: dict, *, expected_revision: int) -> dict:
        """Cancel a draft only, not a host job or external effect. Retry is stable."""
        key = _key(key)
        if type(expected_revision) is not int or expected_revision != 1:
            raise IntentError("revision_conflict")

        def apply():
            now = self._now()
            record = self._record(key)
            if record is None:
                raise IntentError("not_found")
            record = self._expire(record, now)
            if record["state"] == "draft":
                return self._terminal(record, "cancelled", now)
            # Expiry may have won. Truthfully return that terminal state rather
            # than saying a non-draft was cancelled. Neither state is revivable.
            return record

        return self._transaction(apply)

    def cancel_many(self, requests: list[dict]) -> list[dict]:
        """Atomically cancel an explicit same-scope set of exact draft bindings.

        This is internal bookkeeping, not revocation of running actions. No
        discovery/wildcard is accepted; callers supply previously inspected
        immutable bindings. Exact terminal retries return their actual states.
        """
        if type(requests) is not list or not 1 <= len(requests) <= 100:
            raise IntentError("invalid_request")
        selected = []
        seen = set()
        scope = None
        for item in requests:
            if type(item) is not dict or item.keys() != {*_KEYS, "binding_digest"}:
                raise IntentError("invalid_request")
            key = _key({name: item[name] for name in _KEYS})
            digest = item["binding_digest"]
            if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise IntentError("invalid_request")
            item_scope = (key["owner_id"], key["profile_id"])
            if scope is not None and item_scope != scope:
                raise IntentError("scope_mismatch")
            scope = item_scope
            if key["request_id"] in seen:
                raise IntentError("invalid_request")
            seen.add(key["request_id"])
            selected.append((key, digest))

        def apply():
            now = self._now()
            records = []
            # Validate the entire selection before mutating any row. The write
            # lock prevents preparation/cancellation racing between these steps.
            for key, digest in selected:
                record = self._record(key)
                if record is None:
                    raise IntentError("not_found")
                if record["binding_digest"] != digest:
                    raise IntentError("request_conflict")
                records.append(record)
            result = []
            for record in records:
                record = self._expire(record, now)
                if record["state"] == "draft":
                    record = self._terminal(record, "cancelled", now)
                result.append(record)
            return result

        return self._transaction(apply)
