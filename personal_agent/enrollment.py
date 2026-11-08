"""Disabled administrative pending-enrollment storage, never authentication.

All supplied identities and scopes are prospective operator records, not verified
facts. This module cannot activate a record, issue a context/grant, adopt tasks,
or authorize reads. Use a dedicated connection from a separately secured opener.
A database restored from backup is not an external freshness authority.

CAS-only retries: create uses a caller-selected stable enrollment_id. After an
uncertain outcome, get that exact owner/profile/id before retrying. Duplicate
create conflicts; updates using an old revision conflict, including no-op edits.
There are no replay receipts or cached authorization responses.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .authorization import ReadRequest, _identifier, _scope

_APPLICATION_ID = 0x5041454E
_SCHEMA_VERSION = 2
MAX_READ_AUDITS = 10000
_MAX = 2**63 - 1
_COLUMNS = (
    "owner_id",
    "profile_id",
    "enrollment_id",
    "transport_id",
    "transport_receiver_id",
    "principal_id",
    "state",
    "enrollment_revision",
    "policy_revision",
    "epoch",
    "operation",
    "target",
    "resource_ids",
    "data_scope",
)
_SCHEMA_V1 = {
    "enrollments": """CREATE TABLE enrollments (
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL,
        enrollment_id TEXT NOT NULL, transport_id TEXT NOT NULL,
        transport_receiver_id TEXT NOT NULL, principal_id TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('pending','revoked')),
        enrollment_revision INTEGER NOT NULL CHECK(enrollment_revision >= 1),
        policy_revision INTEGER NOT NULL CHECK(policy_revision >= 1),
        epoch INTEGER NOT NULL CHECK(epoch >= 0),
        operation TEXT NOT NULL, target TEXT NOT NULL,
        resource_ids TEXT NOT NULL, data_scope TEXT NOT NULL,
        PRIMARY KEY(owner_id, profile_id, enrollment_id))""",
    "events": """CREATE TABLE events (
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL, enrollment_id TEXT NOT NULL,
        epoch INTEGER NOT NULL, operation TEXT NOT NULL
        CHECK(operation IN ('create','set_policy','revoke')),
        enrollment_revision INTEGER NOT NULL, policy_revision INTEGER NOT NULL,
        PRIMARY KEY(owner_id, profile_id, enrollment_id, epoch))""",
}
_READ_AUDIT_SQL = """CREATE TABLE read_admissions (
        sequence INTEGER PRIMARY KEY,
        owner_id TEXT NOT NULL, profile_id TEXT NOT NULL, enrollment_id TEXT NOT NULL,
        enrollment_revision INTEGER NOT NULL, policy_revision INTEGER NOT NULL,
        epoch INTEGER NOT NULL, prepared_at TEXT NOT NULL,
        resource_count INTEGER NOT NULL CHECK(resource_count BETWEEN 1 AND 32),
        outcome TEXT NOT NULL CHECK(outcome = 'snapshot_prepared'))"""
_SCHEMA = {**_SCHEMA_V1, "read_admissions": _READ_AUDIT_SQL}
_READ_AUDIT_COLUMNS = (
    "sequence",
    "owner_id",
    "profile_id",
    "enrollment_id",
    "enrollment_revision",
    "policy_revision",
    "epoch",
    "prepared_at",
    "resource_count",
    "outcome",
)


@dataclass(frozen=True, slots=True)
class PreparedRead[T]:
    """Trusted coordinator result, not a data-driven approval or delivery receipt."""

    value: T
    prepared_at: datetime
    resource_count: int


_KEYS = {"owner_id", "profile_id", "enrollment_id"}
_IDENTITY = {"transport_id", "transport_receiver_id", "principal_id"}
_SCOPE = {"operation", "target", "resource_ids", "data_scope"}
_CAS = {"expected_revision", "expected_enrollment_revision"}


class EnrollmentError(Exception):
    """Redacted stable failure; never contains identity, scope or SQLite text."""

    def __init__(self, code: str, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(f"Pending enrollment operation failed ({code}).")


def _revision(value: object, *, minimum: int = 1) -> bool:
    return type(value) is int and minimum <= value <= _MAX


def _request(operation: str, payload: dict) -> dict:
    fields = {
        "create": _KEYS | _IDENTITY | {"scope"},
        "get": _KEYS,
        "set_policy": _KEYS | _CAS | {"scope"},
        "revoke": _KEYS | _CAS,
    }
    if (
        type(operation) is not str
        or operation not in fields
        or type(payload) is not dict
        or payload.keys() != fields[operation]
    ):
        raise EnrollmentError("invalid_request")
    result = dict(payload)
    for name in _KEYS | (_IDENTITY if operation == "create" else set()):
        if not _identifier(result[name]):
            raise EnrollmentError("invalid_request")
    for name in _CAS & result.keys():
        if not _revision(result[name]):
            raise EnrollmentError("invalid_request")
    if "scope" in result:
        scope = result["scope"]
        if type(scope) is not dict or scope.keys() != _SCOPE:
            raise EnrollmentError("invalid_request")
        if not _scope(ReadRequest(**scope)):
            raise EnrollmentError("invalid_request")
        result["scope"] = dict(scope)
    return result


class EnrollmentStore:
    """Dedicated synchronous store. Caller owns connection and access control.

    Not safe for simultaneous use of one connection. Independent connections
    serialize mutations with BEGIN IMMEDIATE. Every operation revalidates schema;
    arbitrary SQL or same-process code is outside this administrative boundary.
    Audit rows retain routing IDs and revisions but no principal, receiver,
    resource IDs, free text, policy content, secrets, or raw failure diagnostics.
    """

    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._initialized = False

    def _schema(self, *, create: bool = False) -> None:
        conn = self._connection
        app = conn.execute("PRAGMA application_id").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        rows = conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"
        ).fetchall()
        # Temporary tables/triggers could shadow main objects or intercept writes.
        if conn.execute("SELECT 1 FROM sqlite_temp_master LIMIT 1").fetchone():
            raise EnrollmentError("unsupported_schema")
        if create and app == 0 and version == 0 and not rows:
            for statement in _SCHEMA.values():
                conn.execute(statement)
            conn.execute(f"PRAGMA application_id = {_APPLICATION_ID}")
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        elif app != _APPLICATION_ID:
            raise EnrollmentError("foreign_database")
        elif create and version == 1 and len(rows) == len(_SCHEMA_V1) and dict(rows) == _SCHEMA_V1:
            # Upgrade only the exact owned predecessor, atomically with initialize.
            # Administrative rows remain byte-for-byte unchanged; no historical
            # read events are fabricated and no pending identity is activated.
            conn.execute(_READ_AUDIT_SQL)
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        elif version != _SCHEMA_VERSION or len(rows) != len(_SCHEMA) or dict(rows) != _SCHEMA:
            raise EnrollmentError("unsupported_schema")

    def _transaction(self, action: Any) -> Any:
        conn = self._connection
        began = False
        try:
            if conn.in_transaction:
                raise EnrollmentError("connection_in_transaction")
            conn.execute("BEGIN IMMEDIATE")
            began = True
            result = action()
            conn.execute("COMMIT")
            return result
        except BaseException as error:
            if began:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(error, sqlite3.Error):
                code = getattr(error, "sqlite_errorcode", 0) or 0
                if code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise EnrollmentError("storage_busy", retryable=True) from None
                raise EnrollmentError("storage_error") from None
            raise

    def initialize(self) -> None:
        """Create/validate v2 or atomically upgrade the exact owned v1 schema."""
        self._initialized = False
        self._transaction(lambda: self._schema(create=True))
        self._initialized = True

    def _get(self, request: dict) -> dict:
        row = self._connection.execute(
            f"SELECT {','.join(_COLUMNS)} FROM main.enrollments "
            "WHERE owner_id = ? AND profile_id = ? AND enrollment_id = ?",
            tuple(request[key] for key in ("owner_id", "profile_id", "enrollment_id")),
        ).fetchone()
        if row is None:
            raise EnrollmentError("not_found")
        result = dict(zip(_COLUMNS, row, strict=True))
        try:
            ids = json.loads(result.pop("resource_ids"))
            if type(ids) is not list:
                raise ValueError
            scope = {key: result.pop(key) for key in ("operation", "target", "data_scope")}
            scope["resource_ids"] = tuple(ids)
            if not _scope(ReadRequest(**scope)):
                raise ValueError
            if not all(_identifier(result[key]) for key in _KEYS | _IDENTITY):
                raise ValueError
            if result["state"] not in ("pending", "revoked"):
                raise ValueError
            if not all(
                _revision(result[key]) for key in ("enrollment_revision", "policy_revision")
            ):
                raise ValueError
            if not _revision(result["epoch"], minimum=0):
                raise ValueError
        except ValueError, TypeError, KeyError:
            raise EnrollmentError("invalid_record") from None
        result["scope"] = scope
        return result

    def _audit(self, record: dict, operation: str) -> None:
        self._connection.execute(
            "INSERT INTO main.events VALUES (?,?,?,?,?,?,?)",
            tuple(record[key] for key in ("owner_id", "profile_id", "enrollment_id", "epoch"))
            + (operation, record["enrollment_revision"], record["policy_revision"]),
        )

    def with_current_record[T](
        self,
        key: dict,
        *,
        expected_revision: int,
        expected_enrollment_revision: int,
        expected_epoch: int,
        operation: Callable[[dict], T],
    ) -> T:
        """Run trusted synchronous code while current policy excludes revocation.

        Internal coordination primitive, NOT an authorization decision. A pending
        record supplies proposed constraints only. The operation must hold an
        independent trusted authority fence and a stable owned resource snapshot;
        it must not send, prompt, perform network I/O or expose a lazy result.
        No callback is accepted through run(), JSON or a registered entry point.
        The detached result escapes only after commit. This does not issue a
        reusable permit, persist read admissions or authenticate host provenance.
        """
        request = _request("get", key)
        if (
            not _revision(expected_revision)
            or not _revision(expected_enrollment_revision)
            or not _revision(expected_epoch, minimum=0)
            or not callable(operation)
        ):
            raise EnrollmentError("invalid_request")
        if not self._initialized:
            raise EnrollmentError("not_initialized")

        def apply() -> T:
            self._schema()
            record = self._get(request)
            if (
                record["policy_revision"] != expected_revision
                or record["enrollment_revision"] != expected_enrollment_revision
                or record["epoch"] != expected_epoch
            ):
                raise EnrollmentError("revision_conflict")
            if record["state"] == "revoked":
                raise EnrollmentError("revoked")
            return operation(record)

        return self._transaction(apply)

    def with_audited_read[T](
        self,
        key: dict,
        *,
        expected_revision: int,
        expected_enrollment_revision: int,
        expected_epoch: int,
        operation: Callable[[dict], PreparedRead[T]],
    ) -> T:
        """Persist minimal prepared-snapshot metadata before returning any result.

        Internal trusted-code API only. The coordinator supplies a trusted final
        UTC sample, not request time. This event does not prove a return, transport
        send, receipt by a user, or independently authenticated owner identity.
        Fail closed at capacity before calling the resource operation; no eviction.
        """
        if not callable(operation):
            raise EnrollmentError("invalid_request")

        def apply(record: dict) -> T:
            count = self._connection.execute(
                "SELECT count(*) FROM (SELECT 1 FROM main.read_admissions LIMIT ?)",
                (MAX_READ_AUDITS,),
            ).fetchone()[0]
            if count >= MAX_READ_AUDITS:
                raise EnrollmentError("read_audit_full")
            last_sequence = self._connection.execute(
                "SELECT coalesce(max(sequence),0) FROM main.read_admissions"
            ).fetchone()[0]
            if not _revision(last_sequence, minimum=0) or last_sequence >= _MAX:
                raise EnrollmentError("read_audit_exhausted")
            prepared = operation(record)
            if (
                type(prepared) is not PreparedRead
                or type(prepared.prepared_at) is not datetime
                or prepared.prepared_at.tzinfo is not UTC
                or prepared.prepared_at.fold != 0
                or type(prepared.resource_count) is not int
                or not 1 <= prepared.resource_count <= 32
            ):
                raise EnrollmentError("invalid_read_audit")
            self._connection.execute(
                "INSERT INTO main.read_admissions (sequence,owner_id,profile_id,enrollment_id,"
                "enrollment_revision,policy_revision,epoch,prepared_at,resource_count,outcome) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (last_sequence + 1,)
                + tuple(
                    record[name]
                    for name in (
                        "owner_id",
                        "profile_id",
                        "enrollment_id",
                        "enrollment_revision",
                        "policy_revision",
                        "epoch",
                    )
                )
                + (prepared.prepared_at.isoformat(), prepared.resource_count, "snapshot_prepared"),
            )
            return prepared.value

        return self.with_current_record(
            key,
            expected_revision=expected_revision,
            expected_enrollment_revision=expected_enrollment_revision,
            expected_epoch=expected_epoch,
            operation=apply,
        )

    def policy_history(self, key: dict, *, after_epoch: int = -1, limit: int = 50) -> dict:
        """Inspect bounded administrative events, not authenticated authority.

        Return one coherent page and current-record watermark. Separate calls are
        not a frozen snapshot. Validate the selected range and current tail, not
        the entire historical database. No policy content or intended identities
        leave this internal, unwired API; scope selectors remain caller-owned.
        """
        request = _request("get", key)
        if (
            type(after_epoch) is not int
            or not -1 <= after_epoch <= _MAX
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise EnrollmentError("invalid_request")
        if not self._initialized:
            raise EnrollmentError("not_initialized")

        def read() -> dict:
            self._schema()
            record = self._get(request)
            epoch = record["epoch"]
            if after_epoch > epoch:
                raise EnrollmentError("invalid_cursor")
            revoked = record["state"] == "revoked"
            if (
                record["enrollment_revision"] != (2 if revoked else 1)
                or record["policy_revision"] != epoch + (0 if revoked else 1)
                or (revoked and epoch == 0)
            ):
                raise EnrollmentError("invalid_policy_audit")
            scope = tuple(request[name] for name in ("owner_id", "profile_id", "enrollment_id"))
            columns = "epoch,operation,enrollment_revision,policy_revision"
            where = "owner_id=? AND profile_id=? AND enrollment_id=?"

            def validate(row: tuple, expected_epoch: int) -> None:
                expected_operation = (
                    "create"
                    if expected_epoch == 0
                    else "revoke"
                    if revoked and expected_epoch == epoch
                    else "set_policy"
                )
                terminal = expected_operation == "revoke"
                if any(type(row[index]) is not int for index in (0, 2, 3)) or row != (
                    expected_epoch,
                    expected_operation,
                    2 if terminal else 1,
                    expected_epoch if terminal else expected_epoch + 1,
                ):
                    raise EnrollmentError("invalid_policy_audit")

            tail = self._connection.execute(
                f"SELECT {columns} FROM main.events WHERE {where} AND epoch=?", scope + (epoch,)
            ).fetchone()
            if tail is None:
                raise EnrollmentError("invalid_policy_audit")
            validate(tail, epoch)
            rows = self._connection.execute(
                f"SELECT {columns} FROM main.events WHERE {where} AND epoch>? "
                "ORDER BY epoch LIMIT ?",
                scope + (after_epoch, limit + 1),
            ).fetchall()
            if len(rows) != min(epoch - after_epoch, limit + 1):
                raise EnrollmentError("invalid_policy_audit")
            for offset, row in enumerate(rows, start=1):
                validate(row, after_epoch + offset)
            items = [dict(zip(columns.split(","), row, strict=True)) for row in rows[:limit]]
            return {
                "items": items,
                "has_more": len(rows) > limit,
                "next_after_epoch": items[-1]["epoch"] if items else after_epoch,
                "current_epoch": epoch,
                "current_state": record["state"],
                "current_enrollment_revision": record["enrollment_revision"],
                "current_policy_revision": record["policy_revision"],
            }

        return self._transaction(read)

    def read_admission_history(
        self, key: dict, *, after_sequence: int = 0, limit: int = 50
    ) -> dict:
        """Bounded internal administrative read; selectors are not identity proof.

        No transport/API exposes this method. Revoked records retain their history.
        Entries are observations, never reusable authorization or replay receipts.
        """
        request = _request("get", key)
        if (
            not _revision(after_sequence, minimum=0)
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise EnrollmentError("invalid_request")
        if not self._initialized:
            raise EnrollmentError("not_initialized")

        def read() -> dict:
            self._schema()
            self._get(request)
            rows = self._connection.execute(
                f"SELECT {','.join(_READ_AUDIT_COLUMNS)} FROM main.read_admissions "
                "WHERE owner_id=? AND profile_id=? AND enrollment_id=? AND sequence>? "
                "ORDER BY sequence LIMIT ?",
                tuple(request[name] for name in ("owner_id", "profile_id", "enrollment_id"))
                + (after_sequence, limit + 1),
            ).fetchall()
            items = [dict(zip(_READ_AUDIT_COLUMNS, row, strict=True)) for row in rows[:limit]]
            for item in items:
                try:
                    sample = datetime.fromisoformat(item["prepared_at"])
                    valid_time = sample.tzinfo is UTC and sample.isoformat() == item["prepared_at"]
                except TypeError, ValueError:
                    valid_time = False
                if (
                    not valid_time
                    or item["outcome"] != "snapshot_prepared"
                    or not all(
                        _revision(item[name])
                        for name in (
                            "sequence",
                            "enrollment_revision",
                            "policy_revision",
                        )
                    )
                    or not _revision(item["epoch"], minimum=0)
                    or type(item["resource_count"]) is not int
                    or not 1 <= item["resource_count"] <= 32
                ):
                    raise EnrollmentError("invalid_read_audit")
            return {
                "items": items,
                "has_more": len(rows) > limit,
                "next_after_sequence": rows[min(len(rows), limit) - 1][0]
                if rows
                else after_sequence,
            }

        return self._transaction(read)

    def run(self, operation: str, payload: dict) -> dict:
        """Return current administrative snapshot, never a permission decision."""
        request = _request(operation, payload)
        if not self._initialized:
            raise EnrollmentError("not_initialized")

        def apply() -> dict:
            self._schema()
            key = tuple(request[k] for k in ("owner_id", "profile_id", "enrollment_id"))
            if operation == "create":
                if self._connection.execute(
                    "SELECT 1 FROM main.enrollments WHERE owner_id=? AND profile_id=? "
                    "AND enrollment_id=?",
                    key,
                ).fetchone():
                    raise EnrollmentError("already_exists")
                scope = request["scope"]
                self._connection.execute(
                    "INSERT INTO main.enrollments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    key
                    + tuple(
                        request[k]
                        for k in ("transport_id", "transport_receiver_id", "principal_id")
                    )
                    + (
                        "pending",
                        1,
                        1,
                        0,
                        scope["operation"],
                        scope["target"],
                        json.dumps(scope["resource_ids"]),
                        scope["data_scope"],
                    ),
                )
            else:
                record = self._get(request)
                if operation == "get":
                    return record
                if (
                    request["expected_revision"] != record["policy_revision"]
                    or request["expected_enrollment_revision"] != record["enrollment_revision"]
                ):
                    raise EnrollmentError("revision_conflict")
                if record["state"] == "revoked":
                    raise EnrollmentError("revoked")
                revision = "policy_revision" if operation == "set_policy" else "enrollment_revision"
                if record[revision] == _MAX or record["epoch"] == _MAX:
                    raise EnrollmentError("revision_exhausted")
                if operation == "set_policy":
                    scope = request["scope"]
                    self._connection.execute(
                        "UPDATE main.enrollments SET operation=?,target=?,resource_ids=?,"
                        "data_scope=?,policy_revision=policy_revision+1,epoch=epoch+1 "
                        "WHERE owner_id=? AND profile_id=? AND enrollment_id=?",
                        (
                            scope["operation"],
                            scope["target"],
                            json.dumps(scope["resource_ids"]),
                            scope["data_scope"],
                        )
                        + key,
                    )
                else:
                    self._connection.execute(
                        "UPDATE main.enrollments SET state='revoked',"
                        "enrollment_revision=enrollment_revision+1,epoch=epoch+1 "
                        "WHERE owner_id=? AND profile_id=? AND enrollment_id=?",
                        key,
                    )
            record = self._get(request)
            self._audit(record, operation)
            return record

        return self._transaction(apply)
