"""Bounded, fail-closed handoff intent ledger. No host, filesystem or network I/O."""

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from uuid import UUID, uuid4

APPLICATION_ID = 0x5041484F
SCHEMA_VERSION = 2
MAX_RECORDS = 1000
PREPARED_SECONDS = 900
# Source details are repeated in the native preview; astral characters escape
# to 12 ASCII bytes each. Keep full valid task text without unbounding receipts.
MAX_INTENT_CHARS = 160000
_SCHEMA_V1 = {
    "handoffs": """CREATE TABLE handoffs (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        id TEXT NOT NULL UNIQUE, request_id TEXT NOT NULL UNIQUE,
        scope_digest TEXT UNIQUE, intent_digest TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN
            ('prepared','claimed','confirmed','cancelled','expired','unknown')),
        metadata TEXT NOT NULL, payload TEXT, observation TEXT,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)"""
}
_IDENTITY_COLUMNS = (
    "native_identity TEXT",
    "identity_state TEXT NOT NULL DEFAULT 'unbound' "
    "CHECK(identity_state IN ('unbound','available','legacy_unbound'))",
)
_SCHEMA = {"handoffs": _SCHEMA_V1["handoffs"][:-1] + ", " + ", ".join(_IDENTITY_COLUMNS) + ")"}
_CARD_ID = re.compile(r"t_[0-9a-f]{8}\Z")


def _identity(value):
    if type(value) is not dict or set(value) != {"card_id", "created_at", "created_event_id"}:
        _fail()
    _matching(value["card_id"], _CARD_ID)
    _integer(value["created_at"])
    _integer(value["created_event_id"], 1)
    return json.loads(_json(value))


_KEY = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class HandoffError(Exception):
    """Stable redacted failure; no database or source text in messages."""

    def __init__(self, code):
        self.code = code
        self.retryable = code == "storage_busy"
        super().__init__(f"Handoff operation failed ({code}).")


def _json(value):
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _fail(code="invalid_request"):
    raise HandoffError(code)


def _integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**63 - 901:
        _fail()
    return value


def _text(value, maximum, required=True):
    if type(value) is not str or len(value) > maximum or (required and not value.strip()):
        _fail()
    if any(ord(c) < 32 and c not in "\n\t" or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        _fail()
    return value


def _matching(value, pattern):
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail()
    return value


def _id(value):
    try:
        if type(value) is not str or str(UUID(value)) != value or UUID(value).version != 4:
            _fail()
    except ValueError, AttributeError:
        _fail()
    return value


def _intent(value):
    if type(value) is not dict or set(value) != {
        "source",
        "destination",
        "native_title",
        "native_body",
        "key",
        "payload_digest",
        "profile_fingerprint",
    }:
        _fail()
    source = value["source"]
    if type(source) is not dict or set(source) != {"task_id", "revision", "title", "details"}:
        _fail()
    _id(source["task_id"])
    _integer(source["revision"], 1)
    _text(source["title"], 240)
    _text(source["details"], 5000, False)
    _text(value["native_title"], 512)
    _text(value["native_body"], 16000, False)
    _matching(value["key"], _KEY)
    _matching(value["payload_digest"], _HASH)
    _matching(value["profile_fingerprint"], _HASH)
    destination = value["destination"]
    if type(destination) is not dict or set(destination) != {
        "root",
        "board",
        "path",
        "device",
        "inode",
        "schema",
        "source",
    }:
        _fail()
    for key in ("root", "board", "path"):
        _text(destination[key], 4096)
    for key in ("device", "inode"):
        _integer(destination[key])
    for key in ("schema", "source"):
        _matching(destination[key], _HASH)
    try:
        encoded = _json(value)
    except ValueError, TypeError, OverflowError:
        _fail()
    if len(encoded) > MAX_INTENT_CHARS:
        _fail()
    return json.loads(encoded)


def _observation(value):
    if (
        type(value) is not dict
        or "outcome" not in value
        or set(value) - {"outcome", "card_id", "status", "match_count", "observed_at"}
    ):
        _fail()
    if type(value["outcome"]) is not str or value["outcome"] not in (
        "parked",
        "identity_confirmed",
        "missing",
        "duplicate",
        "changed",
        "archived",
        "unavailable",
    ):
        _fail()
    for key in ("card_id", "status"):
        if key in value:
            _text(value[key], 128)
    for key in ("match_count", "observed_at"):
        if key in value:
            _integer(value[key])
    if value["outcome"] == "parked" and (
        not value.get("card_id")
        or value.get("status") != "blocked"
        or value.get("match_count", 1) != 1
    ):
        _fail()
    if value["outcome"] == "identity_confirmed":
        _matching(value.get("card_id"), _CARD_ID)
        if (
            value.get("status")
            not in (
                "triage",
                "todo",
                "scheduled",
                "ready",
                "running",
                "blocked",
                "review",
                "done",
                "archived",
            )
            or value.get("match_count", 1) != 1
        ):
            _fail()
    return json.loads(_json(value))


class HandoffStore:
    """Own transactions on the supplied dedicated connection, never its lifetime."""

    def __init__(self, connection):
        self.connection = connection
        self._initialized = False

    @contextmanager
    def _transaction(self, *, initializing=False):
        began = False
        try:
            if not initializing and not self._initialized:
                _fail("not_initialized")
            if self.connection.in_transaction:
                _fail("connection_in_transaction")
            self.connection.execute("BEGIN IMMEDIATE")
            began = True
            yield
            self.connection.execute("COMMIT")
        except BaseException as error:
            if began and self.connection.in_transaction:
                try:
                    self.connection.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(error, sqlite3.Error):
                code = (getattr(error, "sqlite_errorcode", 0) or 0) & 255
                raise HandoffError("storage_busy" if code in (5, 6) else "storage_error") from None
            raise

    def initialize(self):
        self._initialized = False
        with self._transaction(initializing=True):
            app = self.connection.execute("PRAGMA application_id").fetchone()[0]
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            rows = self.connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall()
            if app == 0 and version == 0 and not rows:
                self.connection.execute(_SCHEMA["handoffs"])
                self.connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
                self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif app != APPLICATION_ID:
                _fail("foreign_database")
            elif version == 1:
                if dict(rows) != _SCHEMA_V1 or len(rows) != len(_SCHEMA_V1):
                    _fail("unsupported_schema")
                for column in _IDENTITY_COLUMNS:
                    self.connection.execute("ALTER TABLE handoffs ADD COLUMN " + column)
                self.connection.execute(
                    "UPDATE handoffs SET identity_state='legacy_unbound' "
                    "WHERE state IN ('claimed','unknown','confirmed')"
                )
                self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            elif version != SCHEMA_VERSION or dict(rows) != _SCHEMA or len(rows) != len(_SCHEMA):
                _fail("unsupported_schema")
            current = self.connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
            ).fetchall()
            if dict(current) != _SCHEMA or len(current) != len(_SCHEMA):
                _fail("unsupported_schema")
        self._initialized = True

    def _expire(self, now):
        self.connection.execute(
            "UPDATE handoffs SET state='expired',payload=NULL,scope_digest=NULL,updated_at=? "
            "WHERE state='prepared' AND expires_at<=?",
            (now, now),
        )

    def _get(self, id):
        row = self.connection.execute(
            "SELECT id,request_id,intent_digest,state,metadata,payload,observation,"
            "created_at,expires_at,updated_at,native_identity,identity_state "
            "FROM handoffs WHERE id=?",
            (id,),
        ).fetchone()
        if row is None:
            _fail("not_found")
        try:
            metadata = json.loads(row[4])
            if type(metadata) is not dict or set(metadata) != {
                "source",
                "destination",
                "key",
                "payload_digest",
                "profile_fingerprint",
            }:
                _fail()
            source = metadata["source"]
            if type(source) is not dict or set(source) != {"task_id", "revision"}:
                _fail()
            _intent(
                {
                    **metadata,
                    "source": {**source, "title": "validation", "details": ""},
                    "native_title": "validation",
                    "native_body": "",
                }
            )
            _matching(row[2], _HASH)
            payload = json.loads(row[5]) if row[5] is not None else None
            observation = json.loads(row[6]) if row[6] is not None else None
            if row[3] == "prepared":
                payload = _intent(payload)
                if (
                    _hash(payload) != row[2]
                    or any(payload[key] != metadata[key] for key in metadata if key != "source")
                    or any(payload["source"][key] != source[key] for key in source)
                ):
                    _fail()
            elif payload is not None:
                _fail()
            if observation is not None:
                _observation(observation)
            identity = json.loads(row[10]) if row[10] is not None else None
            if row[11] == "available":
                identity = _identity(identity)
                if row[3] not in ("claimed", "unknown", "confirmed"):
                    _fail()
            elif row[11] not in ("unbound", "legacy_unbound") or identity is not None:
                _fail()
            if row[11] == "legacy_unbound" and row[3] not in ("claimed", "unknown", "confirmed"):
                _fail()
            return dict(
                id=row[0],
                request_id=row[1],
                intent_digest=row[2],
                state=row[3],
                **metadata,
                payload=payload,
                observation=observation,
                created_at=row[7],
                expires_at=row[8],
                updated_at=row[9],
                native_identity=identity,
                identity_state=row[11],
            )
        except ValueError, TypeError, KeyError, HandoffError:
            _fail("storage_corrupt")

    def prepare(self, request_id, intent, now):
        _matching(request_id, _KEY)
        intent = _intent(intent)
        _integer(now)
        digest = _hash(intent)
        metadata = {
            key: intent[key]
            for key in ("destination", "key", "payload_digest", "profile_fingerprint")
        }
        metadata["source"] = {key: intent["source"][key] for key in ("task_id", "revision")}
        scope = _hash([metadata["source"], intent["destination"], intent["profile_fingerprint"]])
        with self._transaction():
            self._expire(now)
            previous = self.connection.execute(
                "SELECT id,intent_digest FROM handoffs WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous[1] != digest:
                    _fail("idempotency_conflict")
                return self._get(previous[0])
            if self.connection.execute(
                "SELECT 1 FROM handoffs WHERE scope_digest=?", (scope,)
            ).fetchone():
                _fail("source_already_prepared")
            if (
                self.connection.execute("SELECT count(*) FROM handoffs").fetchone()[0]
                >= MAX_RECORDS
            ):
                _fail("handoff_limit")
            id = str(uuid4())
            self.connection.execute(
                "INSERT INTO handoffs(id,request_id,scope_digest,intent_digest,state,metadata,"
                "payload,created_at,expires_at,updated_at) VALUES (?,?,?,?,'prepared',?,?,?,?,?)",
                (
                    id,
                    request_id,
                    scope,
                    digest,
                    _json(metadata),
                    _json(intent),
                    now,
                    now + PREPARED_SECONDS,
                    now,
                ),
            )
            return self._get(id)

    def get(self, id, now):
        _id(id)
        _integer(now)
        with self._transaction():
            self._expire(now)
            return self._get(id)

    def list(self, limit, after, now):
        _integer(limit, 1)
        if limit > 100:
            _fail()
        _integer(now)
        if after is not None:
            _id(after)
        with self._transaction():
            self._expire(now)
            sequence = 0
            if after is not None:
                row = self.connection.execute(
                    "SELECT sequence FROM handoffs WHERE id=?", (after,)
                ).fetchone()
                if row is None:
                    _fail("invalid_cursor")
                sequence = row[0]
            rows = self.connection.execute(
                "SELECT id FROM handoffs WHERE sequence>? ORDER BY sequence LIMIT ?",
                (sequence, limit + 1),
            ).fetchall()
            items = [self._get(row[0]) for row in rows[:limit]]
            for item in items:
                item["payload"] = None  # Listing is metadata-only, not a batch disclosure.
            return dict(
                items=items,
                next_cursor=items[-1]["id"] if len(rows) > limit else None,
                has_more=len(rows) > limit,
            )

    def _check_digest(self, record, expected_digest):
        if record["intent_digest"] != expected_digest:
            _fail("intent_conflict")

    def cancel(self, id, expected_digest, now):
        _id(id)
        _matching(expected_digest, _HASH)
        _integer(now)
        with self._transaction():
            self._expire(now)
            record = self._get(id)
            self._check_digest(record, expected_digest)
            if record["state"] not in ("prepared", "cancelled", "expired"):
                _fail("terminal_state")
            if record["state"] == "prepared":
                self.connection.execute(
                    "UPDATE handoffs SET state='cancelled',payload=NULL,scope_digest=NULL,"
                    "updated_at=? WHERE id=?",
                    (now, id),
                )
            return self._get(id)

    def claim(self, id, expected_digest, now):
        _id(id)
        _matching(expected_digest, _HASH)
        _integer(now)
        with self._transaction():
            self._expire(now)
            record = self._get(id)
            self._check_digest(record, expected_digest)
            if record["state"] != "prepared":
                return record, False
            self.connection.execute(
                "UPDATE handoffs SET state='claimed',payload=NULL,updated_at=? WHERE id=?",
                (now, id),
            )
            result = self._get(id)
            result["payload"] = record["payload"]
            return result, True

    def remember_native_identity(self, id, identity, now):
        """Persist creation anchor before native commit; never infer one from observation."""
        _id(id)
        identity = _identity(identity)
        _integer(now)
        with self._transaction():
            record = self._get(id)
            if record["identity_state"] == "available":
                if record["native_identity"] != identity:
                    _fail("native_identity_conflict")
                return record
            if record["identity_state"] == "legacy_unbound":
                _fail("native_identity_unavailable")
            if record["state"] != "claimed":
                _fail("terminal_state")
            self.connection.execute(
                "UPDATE handoffs SET native_identity=?,identity_state='available',updated_at=? "
                "WHERE id=?",
                (_json(identity), now, id),
            )
            return self._get(id)

    def record_observation(self, id, observation, now):
        _id(id)
        observation = _observation(observation)
        _integer(now)
        with self._transaction():
            self._expire(now)
            record = self._get(id)
            if record["state"] not in ("claimed", "unknown", "confirmed"):
                _fail("terminal_state")
            if observation["outcome"] == "identity_confirmed" and (
                record["identity_state"] != "available" or record["native_identity"] is None
            ):
                _fail("native_identity_unavailable")
            if (
                observation["outcome"] in ("parked", "identity_confirmed")
                and record["native_identity"] is not None
                and observation["card_id"] != record["native_identity"]["card_id"]
            ):
                _fail("native_identity_conflict")
            state = (
                "confirmed"
                if record["state"] == "confirmed"
                or observation["outcome"] in ("parked", "identity_confirmed")
                else "unknown"
            )
            self.connection.execute(
                "UPDATE handoffs SET state=?,observation=?,updated_at=? WHERE id=?",
                (state, _json(observation), now, id),
            )
            return self._get(id)
