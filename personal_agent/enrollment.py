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
from typing import Any

from .authorization import ReadRequest, _identifier, _scope

_APPLICATION_ID = 0x5041454E
_SCHEMA_VERSION = 1
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
_SCHEMA = {
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
        """Create only an empty database, or validate the exact owned v1 schema."""
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
