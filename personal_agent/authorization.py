"""Pure, fail-closed preparation for a future trusted read adapter, NOT live access.

VerifiedReadContext means an INTERNAL already-verified input, never user JSON or
an ``authenticated=True`` flag. No production adapter can issue it yet. A future
trusted adapter must establish identity, ownership, session, policy and revocation
evidence independently of the caller, and enforce the decision before reading.
Python objects/types are neither authentication proof nor a sandbox: arbitrary
in-process code can construct or alter them. Validation rejects malformed values,
not a malicious interpreter. This module performs no I/O, enrollment or effects.

Identifiers are opaque ASCII stable IDs (1..128 characters, letters/digits and
``._:-``); they are not patterns, paths or display names. Scope names are exact.
``own_inbox`` is the whole task collection owned by this exact owner/profile,
never a global inbox; resource_ids must be empty. ``exact_tasks`` uses nonempty
explicit IDs checked against independently verified owned_task_ids. Binding
inspection exposes only metadata of this exact profile and has no resource IDs.
No target conversion, wildcard, implicit session, writes or delegated authority.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

Reason = Literal[
    "allow",
    "invalid_context",
    "invalid_grant",
    "invalid_request",
    "invalid_policy",
    "invalid_time",
    "identity_mismatch",
    "stale_policy",
    "revoked",
    "inactive_grant",
    "scope_mismatch",
    "resource_not_owned",
]


@dataclass(frozen=True, slots=True)
class VerifiedReadContext:
    owner_id: str
    profile_id: str
    transport_id: str
    transport_receiver_id: str
    principal_id: str
    session_id: str
    policy_revision: int
    epoch: int
    owned_task_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReadGrant:
    grant_id: str
    owner_id: str
    profile_id: str
    transport_id: str
    transport_receiver_id: str
    principal_id: str
    session_id: str
    policy_revision: int
    epoch: int
    operation: str
    target: str
    resource_ids: tuple[str, ...]
    data_scope: str
    not_before: datetime
    expires_at: datetime
    revoked: bool


@dataclass(frozen=True, slots=True)
class ReadRequest:
    operation: str
    target: str
    resource_ids: tuple[str, ...]
    data_scope: str


@dataclass(frozen=True, slots=True)
class ReadDecision:
    allowed: bool
    reason: Reason


_IDENTITY = (
    "owner_id",
    "profile_id",
    "transport_id",
    "transport_receiver_id",
    "principal_id",
    "session_id",
)


def _identifier(value: object) -> bool:
    return (
        type(value) is str
        and 1 <= len(value) <= 128
        and all(c.isascii() and (c.isalnum() or c in "._:-") for c in value)
    )


def _ids(value: object) -> bool:
    return (
        type(value) is tuple
        and len(value) <= 1024
        and all(_identifier(item) for item in value)
        and len(set(value)) == len(value)
    )


def _revision(value: object) -> bool:
    return type(value) is int and 0 <= value <= 2**63 - 1


def _time(value: object) -> bool:
    # Require the exact builtin UTC singleton: no naive, numeric, custom tzinfo,
    # datetime subclass, local zone or executable timezone behavior.
    return type(value) is datetime and value.tzinfo is UTC and value.fold == 0


def _identity(value: VerifiedReadContext | ReadGrant) -> bool:
    return (
        all(_identifier(getattr(value, field)) for field in _IDENTITY)
        and _revision(value.policy_revision)
        and _revision(value.epoch)
    )


def _scope(value: ReadGrant | ReadRequest) -> bool:
    if not all(type(x) is str for x in (value.operation, value.target, value.data_scope)):
        return False
    if not _ids(value.resource_ids):
        return False
    if value.operation == "personal.tasks.read" and value.data_scope == "tasks.summary":
        return (value.target == "exact_tasks" and bool(value.resource_ids)) or (
            value.target == "own_inbox" and not value.resource_ids
        )
    return (
        value.operation == "personal.primary_binding.inspect"
        and value.target == "primary_binding"
        and value.data_scope == "primary_binding.metadata"
        and not value.resource_ids
    )


def _deny(reason: Reason) -> ReadDecision:
    return ReadDecision(False, reason)


def evaluate_read(
    context: VerifiedReadContext,
    grant: ReadGrant,
    request: ReadRequest,
    *,
    current_policy_revision: int,
    current_epoch: int,
    now: datetime,
) -> ReadDecision:
    """Evaluate trusted snapshots, with no clock reads or persistent state.

    current_policy_revision/current_epoch/now must come from trusted policy/clock
    sources, not request arguments. Epoch invalidates previously issued grants;
    revoked is a current trusted revocation snapshot, not a caller assertion.
    The interval is [not_before, expires_at). No implicit defaults or wildcards.
    Exact-task requests may select a subset of an exact-task grant. Every granted
    resource ID must be independently owned; foreign overlaps deny entirely.
    A decision alone cannot prevent races: a future adapter must make the policy
    snapshot and resource read consistent. Decisions contain no input data.
    """
    # Exact types and guarded access also reject fake/partially initialized
    # dataclasses. Frozen slots hold only immutable primitives/tuples/datetimes.
    try:
        if type(context) is not VerifiedReadContext or not _identity(context):
            return _deny("invalid_context")
        if not _ids(context.owned_task_ids):
            return _deny("invalid_context")
        if type(grant) is not ReadGrant or not _identity(grant):
            return _deny("invalid_grant")
        if not _identifier(grant.grant_id) or type(grant.revoked) is not bool:
            return _deny("invalid_grant")
        if not _scope(grant):
            return _deny("invalid_grant")
        if type(request) is not ReadRequest or not _scope(request):
            return _deny("invalid_request")
        if not _revision(current_policy_revision) or not _revision(current_epoch):
            return _deny("invalid_policy")
        if not all(_time(t) for t in (now, grant.not_before, grant.expires_at)):
            return _deny("invalid_time")
        if grant.not_before >= grant.expires_at:
            return _deny("invalid_time")
        if any(getattr(context, f) != getattr(grant, f) for f in _IDENTITY):
            return _deny("identity_mismatch")
        if (
            context.policy_revision != current_policy_revision
            or grant.policy_revision != current_policy_revision
            or context.epoch != current_epoch
            or grant.epoch != current_epoch
        ):
            return _deny("stale_policy")
        if grant.revoked:
            return _deny("revoked")
        if not grant.not_before <= now < grant.expires_at:
            return _deny("inactive_grant")
        if (request.operation, request.target, request.data_scope) != (
            grant.operation,
            grant.target,
            grant.data_scope,
        ) or not set(request.resource_ids).issubset(grant.resource_ids):
            return _deny("scope_mismatch")
        if not set(grant.resource_ids).issubset(context.owned_task_ids):
            return _deny("resource_not_owned")
        return ReadDecision(True, "allow")
    except AttributeError, TypeError, ValueError:
        # Uninitialized slots and malformed nested values never authorize.
        return _deny("invalid_context")
