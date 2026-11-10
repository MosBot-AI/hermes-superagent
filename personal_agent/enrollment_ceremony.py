"""Unwired one-shot enrollment evidence; never a live owner/grant issuer.

Lock order: independent host invalidation guard -> current enrollment transaction
-> dedicated challenge transaction. There is no cross-database atomic commit.
Challenge commits may survive a later enrollment/host failure; no success escapes
that failure, and persisted evidence never substitutes for current authority.
"""

import json
import sqlite3
import uuid
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .authorization import _identifier, _revision
from .enrollment import EnrollmentStore


class CeremonyError(Exception):
    def __init__(self, code: str):
        codes = {
            "invalid_observation",
            "source_denied",
            "identity_mismatch",
            "unsupported_schema",
            "connection_in_transaction",
            "storage_failed",
            "capacity",
            "challenge_unavailable",
            "unavailable",
            "invalid_request",
            "confirmation_mismatch",
            "confirmation_denied",
            "outcome_uncertain",
        }
        code = code if type(code) is str and code in codes else "outcome_uncertain"
        self.code = code
        super().__init__(f"Enrollment ceremony failed ({code}).")


@dataclass(frozen=True, slots=True)
class ChannelObservation:
    """Trusted adapter output, not authentication by Python type or construction.

    No deserializer or production adapter exists. Route/device revisions and
    incarnation must be checked under the adapter's actual invalidation fence.
    """

    transport_id: str
    transport_receiver_id: str
    principal_id: str
    profile_id: str
    session_id: str
    host_incarnation: str
    route_revision: int
    device_revision: int
    actor_kind: str
    provenance: str
    conversation_kind: str
    device_revoked: bool


class ObservationGuard(Protocol):
    observation: ChannelObservation
    confirmed_challenge_id: str | None

    def validate_and_now(self) -> datetime:
        """Check current identity/route/device/session and return trusted UTC now."""
        ...


class EnrollmentAuthority(Protocol):
    def hold_observation(
        self, live_handle: object, *, purpose: str
    ) -> AbstractContextManager[ObservationGuard]:
        """Consume independent one-shot proof before yielding a fenced observation.

        purpose=issue observes a candidate. purpose=confirm additionally proves
        explicit confirmation of the exact
        challenge ID; the guard must expose it as confirmed_challenge_id. Failed
        attempts burn the handle. No caller JSON, flags or pending labels suffice.
        """
        ...


_SCHEMA = {
    "ceremonies": "CREATE TABLE ceremonies (id TEXT PRIMARY KEY, enrollment_key TEXT NOT NULL, "
    "binding TEXT NOT NULL, "
    "expires TEXT NOT NULL, state TEXT NOT NULL "
    "CHECK(state IN ('pending','consumed','confirmed')))",
    "ceremony_events": "CREATE TABLE ceremony_events (sequence INTEGER PRIMARY KEY, "
    "challenge_id TEXT NOT NULL, outcome TEXT NOT NULL "
    "CHECK(outcome IN ('issued','denied','confirmed')))",
}
_APP = 1212502862


def _now(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is not UTC:
        raise CeremonyError("invalid_observation")
    return value


def _observation(value: object) -> ChannelObservation:
    if type(value) is not ChannelObservation:
        raise CeremonyError("invalid_observation")
    try:
        ids = (
            value.transport_id,
            value.transport_receiver_id,
            value.principal_id,
            value.profile_id,
            value.session_id,
            value.host_incarnation,
        )
        valid = all(_identifier(v) for v in ids)
        valid = valid and _revision(value.route_revision) and _revision(value.device_revision)
        valid = valid and type(value.actor_kind) is str and type(value.provenance) is str
        valid = valid and type(value.conversation_kind) is str
        valid = valid and value.actor_kind == "human" and value.provenance == "direct"
        valid = valid and value.conversation_kind == "dm" and value.device_revoked is False
    except AttributeError, TypeError:
        valid = False
    if not valid:
        raise CeremonyError("source_denied")
    return value


def _binding(record: dict, observed: ChannelObservation) -> str:
    for key in ("transport_id", "transport_receiver_id", "principal_id", "profile_id"):
        if record[key] != getattr(observed, key):
            raise CeremonyError("identity_mismatch")
    # Persist only exact prospective scope and fenced identity; never a grant.
    return json.dumps(
        {"observation": asdict(observed), "enrollment": record},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


class CeremonyStore:
    """Caller-owned separate SQLite connection, private storage required by caller.

    No production opener, path discovery or plugin surface invokes this class.
    Exact schema validation rejects foreign/temp objects. Same-process malicious
    Python or database tampering are outside this administrative trust boundary.
    """

    def __init__(self, connection: sqlite3.Connection):
        if type(connection) is not sqlite3.Connection:
            raise CeremonyError("invalid_request")
        self.connection = connection

    def _schema(self, create=False):
        db = self.connection
        rows = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*'"))
        if db.execute("SELECT 1 FROM sqlite_temp_master LIMIT 1").fetchone():
            raise CeremonyError("unsupported_schema")
        app = db.execute("PRAGMA application_id").fetchone()[0]
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if create and not rows and app == version == 0:
            for sql in _SCHEMA.values():
                db.execute(sql)
            db.execute(f"PRAGMA application_id={_APP}")
            db.execute("PRAGMA user_version=1")
        elif rows != _SCHEMA or app != _APP or version != 1:
            raise CeremonyError("unsupported_schema")

    def _transaction(self, action):
        db = self.connection
        if db.in_transaction:
            raise CeremonyError("connection_in_transaction")
        began = False
        try:
            db.execute("BEGIN IMMEDIATE")
            began = True
            result = action()
            db.execute("COMMIT")
            return result
        except BaseException as exc:
            if began:
                try:
                    db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
            if isinstance(exc, sqlite3.Error):
                raise CeremonyError("storage_failed") from None
            raise

    def initialize(self):
        self._transaction(lambda: self._schema(create=True))

    def issue(self, binding, now, *, enrollment_key: str) -> str:
        def action():
            self._schema()
            if self.connection.execute("SELECT count(*) FROM ceremonies").fetchone()[0] >= 10000:
                raise CeremonyError("capacity")
            key = uuid.uuid4().hex
            current = binding()
            expires = now() + timedelta(minutes=5)
            self.connection.execute(
                "INSERT INTO ceremonies VALUES (?,?,?,?,'pending')",
                (key, enrollment_key, current, expires.isoformat()),
            )
            self.connection.execute(
                "INSERT INTO ceremony_events(challenge_id,outcome) VALUES (?,'issued')", (key,)
            )
            return key

        return self._transaction(action)

    def inspect(self, key: str) -> dict:
        """Historical state only; never revalidate or import an authorization grant."""
        if not _identifier(key):
            raise CeremonyError("invalid_request")

        def action():
            self._schema()
            row = self.connection.execute(
                "SELECT state FROM ceremonies WHERE id=?", (key,)
            ).fetchone()
            if row is None:
                raise CeremonyError("challenge_unavailable")
            return {"challenge_id": key, "state": row[0], "authority": False}

        return self._transaction(action)

    def confirm(self, key: str, binding, now, *, enrollment_key: str) -> bool:
        def action():
            self._schema()
            row = self.connection.execute(
                "SELECT binding,expires,state,enrollment_key FROM ceremonies WHERE id=?", (key,)
            ).fetchone()
            if row is None or row[2] != "pending" or row[3] != enrollment_key:
                raise CeremonyError("challenge_unavailable")
            # Re-sample AFTER the SQLite wait, inside all invalidation fences.
            allowed = False
            try:
                current = binding()
                expires = datetime.fromisoformat(row[1])
                sampled = now()
                allowed = current == row[0] and expires - timedelta(minutes=5) <= sampled < expires
            except CeremonyError:
                pass
            self.connection.execute(
                "UPDATE ceremonies SET state=? WHERE id=?",
                ("confirmed" if allowed else "consumed", key),
            )
            self.connection.execute(
                "INSERT INTO ceremony_events(challenge_id,outcome) VALUES (?,?)",
                (key, "confirmed" if allowed else "denied"),
            )
            return allowed

        return self._transaction(action)


class EnrollmentCeremony:
    """Internal coordinator. enabled alone is never authority; missing adapter denies."""

    def __init__(
        self,
        enrollment: EnrollmentStore,
        challenges: CeremonyStore,
        *,
        authority: EnrollmentAuthority | None = None,
        enabled: bool = False,
    ):
        self.enrollment = enrollment
        self.challenges = challenges
        self.authority = authority
        self.enabled = enabled

    def run(
        self,
        operation: str,
        key: dict,
        *,
        expected_revision: int,
        expected_enrollment_revision: int,
        expected_epoch: int,
        live_handle: object,
        challenge_id: str | None = None,
    ) -> dict:
        if self.enabled is not True or self.authority is None:
            raise CeremonyError("unavailable")
        if (
            type(operation) is not str
            or operation not in ("issue", "confirm")
            or (operation == "issue" and challenge_id is not None)
            or (operation == "confirm" and not _identifier(challenge_id))
        ):
            raise CeremonyError("invalid_request")
        challenge_committed = False
        try:
            with self.authority.hold_observation(live_handle, purpose=operation) as guard:
                if operation == "confirm" and (
                    type(guard.confirmed_challenge_id) is not str
                    or guard.confirmed_challenge_id != challenge_id
                ):
                    raise CeremonyError("confirmation_mismatch")

                def act(record):
                    nonlocal challenge_committed

                    def binding():
                        _now(guard.validate_and_now())
                        observed = _observation(guard.observation)
                        return _binding(record, observed)

                    enrollment_key = json.dumps(
                        [record[name] for name in ("owner_id", "profile_id", "enrollment_id")]
                    )
                    if operation == "issue":
                        result = self.challenges.issue(
                            binding,
                            lambda: _now(guard.validate_and_now()),
                            enrollment_key=enrollment_key,
                        )
                        challenge_committed = True
                        return {"challenge_id": result, "state": "pending", "authority": False}
                    assert type(challenge_id) is str
                    allowed = self.challenges.confirm(
                        challenge_id,
                        binding,
                        lambda: _now(guard.validate_and_now()),
                        enrollment_key=enrollment_key,
                    )
                    challenge_committed = True
                    return {
                        "challenge_id": challenge_id,
                        "state": "confirmed" if allowed else "consumed",
                        "authority": False,
                    }

                result = self.enrollment.with_current_record(
                    key,
                    expected_revision=expected_revision,
                    expected_enrollment_revision=expected_enrollment_revision,
                    expected_epoch=expected_epoch,
                    operation=act,
                )
            return result
        except CeremonyError:
            if challenge_committed:
                raise CeremonyError("outcome_uncertain") from None
            raise
        except Exception:
            # A challenge transaction may already have committed. No cross-store
            # rollback, reusable permit or successful confirmation is claimed.
            raise CeremonyError("outcome_uncertain") from None
