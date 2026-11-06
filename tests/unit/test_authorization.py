"""Synthetic internal inputs only; these tests do not establish a live issuer."""

from dataclasses import FrozenInstanceError, asdict, fields, replace
from datetime import UTC, datetime, timedelta, timezone, tzinfo

import pytest

from personal_agent.authorization import (
    ReadDecision,
    ReadGrant,
    ReadRequest,
    VerifiedReadContext,
    evaluate_read,
)

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
IDENTITY = dict(
    owner_id="owner-1",
    profile_id="profile-1",
    transport_id="telegram",
    transport_receiver_id="bot-1",
    principal_id="principal-1",
    session_id="session-1",
    policy_revision=3,
    epoch=7,
)
CONTEXT = VerifiedReadContext(**IDENTITY, owned_task_ids=("task-1", "task-2"))
REQUEST = ReadRequest("personal.tasks.read", "exact_tasks", ("task-1",), "tasks.summary")
GRANT = ReadGrant(
    **IDENTITY,
    grant_id="grant-1",
    **asdict(REQUEST),
    not_before=NOW - timedelta(hours=1),
    expires_at=NOW + timedelta(hours=1),
    revoked=False,
)


def evaluate(context=CONTEXT, grant=GRANT, request=REQUEST, **kwargs):
    return evaluate_read(
        context,
        grant,
        request,
        **{
            "current_policy_revision": 3,
            "current_epoch": 7,
            "now": NOW,
            **kwargs,
        },
    )


def deny(result, reason=None):
    assert type(result) is ReadDecision
    assert result.allowed is False
    assert result.reason != "allow"
    if reason:
        assert result.reason == reason
    assert set(asdict(result)) == {"allowed", "reason"}
    assert all(
        secret not in repr(result)
        for secret in (*IDENTITY.values(), "task-1")
        if type(secret) is str
    )


def test_valid_exact_read_and_subset():
    assert evaluate() == ReadDecision(True, "allow")
    assert evaluate(grant=replace(GRANT, resource_ids=("task-1", "task-2"))).allowed
    assert evaluate(grant=replace(GRANT, resource_ids=("task-2", "task-1"))).allowed


@pytest.mark.parametrize(
    "operation,target,scope",
    [
        ("personal.tasks.read", "own_inbox", "tasks.summary"),
        ("personal.primary_binding.inspect", "primary_binding", "primary_binding.metadata"),
    ],
)
def test_valid_collection_or_binding(operation, target, scope):
    request = ReadRequest(operation, target, (), scope)
    grant = replace(GRANT, **asdict(request))
    assert evaluate(request=request, grant=grant).allowed
    assert evaluate(
        context=replace(CONTEXT, owned_task_ids=()), request=request, grant=grant
    ).allowed
    deny(evaluate(request=replace(request, resource_ids=("foreign",)), grant=grant))
    deny(evaluate(request=request, grant=replace(grant, resource_ids=("foreign",))))


@pytest.mark.parametrize("field", list(IDENTITY)[:6])
def test_all_identity_dimensions_must_match(field):
    deny(evaluate(context=replace(CONTEXT, **{field: "another"})), "identity_mismatch")
    deny(evaluate(grant=replace(GRANT, **{field: "another"})), "identity_mismatch")


@pytest.mark.parametrize("field", ["policy_revision", "epoch"])
@pytest.mark.parametrize("value", [0, 1, 99])
def test_stale_context_grant_and_current_policy(field, value):
    deny(evaluate(context=replace(CONTEXT, **{field: value})), "stale_policy")
    deny(evaluate(grant=replace(GRANT, **{field: value})), "stale_policy")
    deny(evaluate(**{"current_" + field: value}), "stale_policy")


@pytest.mark.parametrize(
    "value", [None, True, False, -1, 1.0, float("nan"), float("inf"), "3", [], {}, 2**63]
)
@pytest.mark.parametrize("field", ["policy_revision", "epoch"])
def test_invalid_policy_types(field, value):
    deny(evaluate(context=replace(CONTEXT, **{field: value})), "invalid_context")
    deny(evaluate(grant=replace(GRANT, **{field: value})), "invalid_grant")
    deny(evaluate(**{"current_" + field: value}), "invalid_policy")


def test_revocation_and_time_boundaries():
    deny(evaluate(grant=replace(GRANT, revoked=True)), "revoked")
    assert evaluate(now=GRANT.not_before).allowed
    deny(evaluate(now=GRANT.not_before - timedelta(microseconds=1)), "inactive_grant")
    assert evaluate(now=GRANT.expires_at - timedelta(microseconds=1)).allowed
    deny(evaluate(now=GRANT.expires_at), "inactive_grant")
    deny(evaluate(now=GRANT.expires_at + timedelta(microseconds=1)), "inactive_grant")
    for before in (GRANT.expires_at, GRANT.expires_at + timedelta(days=1)):
        deny(evaluate(grant=replace(GRANT, not_before=before)), "invalid_time")


class HostileTimezone(tzinfo):
    def utcoffset(self, dt):
        raise AssertionError("Untrusted timezone must not execute")


class DateSubclass(datetime):
    pass


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        False,
        0,
        1.0,
        float("inf"),
        float("nan"),
        "2026-11-06",
        [],
        {},
        NOW.replace(tzinfo=None),
        NOW.replace(tzinfo=timezone(timedelta(hours=1))),
        NOW.replace(tzinfo=HostileTimezone()),
        NOW.replace(fold=1),
        DateSubclass(2026, 11, 6, tzinfo=UTC),
    ],
)
def test_invalid_times(value):
    deny(evaluate(now=value), "invalid_time")
    deny(evaluate(grant=replace(GRANT, not_before=value)), "invalid_time")
    deny(evaluate(grant=replace(GRANT, expires_at=value)), "invalid_time")


@pytest.mark.parametrize(
    "field,value",
    [
        ("operation", "personal.tasks.write"),
        ("operation", "personal.tasks.delete"),
        ("operation", "personal.tasks.read.extra"),
        ("operation", "*"),
        ("operation", "personal.primary_binding.update"),
        ("operation", None),
        ("target", "*"),
        ("target", "all_inboxes"),
        ("target", "../foreign"),
        ("target", None),
        ("data_scope", "*"),
        ("data_scope", "tasks.full"),
        ("data_scope", ("tasks.summary",)),
        ("data_scope", None),
        ("resource_ids", ()),
        ("resource_ids", ("*",)),
        ("resource_ids", ("task-1", "task-1")),
        ("resource_ids", ["task-1"]),
        ("resource_ids", ({"task-1": True},)),
        ("resource_ids", (("task-1",),)),
        ("resource_ids", None),
        ("resource_ids", (True,)),
    ],
)
def test_unknown_or_malformed_scopes(field, value):
    deny(evaluate(request=replace(REQUEST, **{field: value})), "invalid_request")
    deny(evaluate(grant=replace(GRANT, **{field: value})), "invalid_grant")


def test_no_scope_conversion_or_foreign_overlap():
    deny(evaluate(request=replace(REQUEST, resource_ids=("task-2",))), "scope_mismatch")
    deny(evaluate(grant=replace(GRANT, resource_ids=("task-1", "foreign"))), "resource_not_owned")
    deny(evaluate(context=replace(CONTEXT, owned_task_ids=("task-2",))), "resource_not_owned")
    inbox = replace(REQUEST, target="own_inbox", resource_ids=())
    binding = ReadRequest(
        "personal.primary_binding.inspect", "primary_binding", (), "primary_binding.metadata"
    )
    for scope in (inbox, binding):
        deny(evaluate(request=scope), "scope_mismatch")
        deny(evaluate(grant=replace(GRANT, **asdict(scope))), "scope_mismatch")


@pytest.mark.parametrize(
    "value",
    ["", "*", "name space", "../id", "x/y", "é", "a" * 129, "x\n", True, 1, None, [], {}, ("id",)],
)
def test_all_identifiers_validated(value):
    for field in list(IDENTITY)[:6]:
        deny(evaluate(context=replace(CONTEXT, **{field: value})), "invalid_context")
        deny(evaluate(grant=replace(GRANT, **{field: value})), "invalid_grant")
    deny(evaluate(grant=replace(GRANT, grant_id=value)), "invalid_grant")
    deny(evaluate(context=replace(CONTEXT, owned_task_ids=(value,))), "invalid_context")


@pytest.mark.parametrize("value", [0, 1, "false", None, [], {}])
def test_revocation_requires_bool(value):
    deny(evaluate(grant=replace(GRANT, revoked=value)), "invalid_grant")


@pytest.mark.parametrize("value", [None, {}, {"authenticated": True}, True, object()])
def test_no_json_boolean_or_object_authentication(value):
    deny(evaluate(context=value), "invalid_context")
    deny(evaluate(grant=value), "invalid_grant")
    deny(evaluate(request=value), "invalid_request")


@pytest.mark.parametrize(
    "cls,arg", [(VerifiedReadContext, "context"), (ReadGrant, "grant"), (ReadRequest, "request")]
)
def test_uninitialized_or_subclass_objects_never_authorize(cls, arg):
    deny(evaluate(**{arg: object.__new__(cls)}))
    subclass = type("Forged", (cls,), {})
    original = {"context": CONTEXT, "grant": GRANT, "request": REQUEST}[arg]
    deny(evaluate(**{arg: subclass(**asdict(original))}))


def test_frozen_immutable_semantics_and_revalidation():
    for value in (CONTEXT, GRANT, REQUEST, evaluate()):
        with pytest.raises((FrozenInstanceError, TypeError)):
            value.extra = "anything"
        for field in fields(value):
            with pytest.raises(FrozenInstanceError):
                setattr(value, field.name, None)
    assert type(GRANT.resource_ids) is tuple
    assert type(CONTEXT.owned_task_ids) is tuple
    # Frozen is not a Python sandbox: even bypassed assignment must be revalidated.
    for original, arg, field in [
        (CONTEXT, "context", "owned_task_ids"),
        (GRANT, "grant", "resource_ids"),
        (REQUEST, "request", "resource_ids"),
    ]:
        mutated = replace(original)
        mutable = ["task-1"]
        object.__setattr__(mutated, field, mutable)
        deny(evaluate(**{arg: mutated}))
        mutable.append("foreign")
        deny(evaluate(**{arg: mutated}))


def test_bounded_ids_and_deterministic_redacted_decisions():
    deny(evaluate(context=replace(CONTEXT, owned_task_ids=("task-1", "task-1"))))
    ids = tuple(f"task-{i}" for i in range(1025))
    deny(evaluate(context=replace(CONTEXT, owned_task_ids=ids)))
    deny(evaluate(grant=replace(GRANT, resource_ids=ids)))
    deny(evaluate(request=replace(REQUEST, resource_ids=ids)))
    revoked = replace(GRANT, revoked=True)
    assert evaluate(grant=revoked) == evaluate(grant=revoked) == ReadDecision(False, "revoked")
