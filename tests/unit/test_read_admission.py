"""Synthetic adapters test coordination, never real ingress or identity proof."""

import sqlite3
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest

from personal_agent.authorization import ReadGrant, ReadRequest, VerifiedReadContext
from personal_agent.enrollment import EnrollmentStore
from personal_agent.read_admission import (
    ReadAdmissionError,
    ReadAdmissionService,
    ReadConfirmation,
    TaskSummary,
)

KEY = {"owner_id": "owner", "profile_id": "profile", "enrollment_id": "enrollment"}
REQUEST = ReadRequest("personal.tasks.read", "exact_tasks", ("task",), "tasks.summary")
NOW = datetime(2026, 1, 1, tzinfo=UTC)
CONTEXT = VerifiedReadContext(
    "owner", "profile", "telegram", "bot", "actor", "session", 1, 0, ("task",)
)
GRANT = ReadGrant(
    "grant",
    "owner",
    "profile",
    "telegram",
    "bot",
    "actor",
    "session",
    1,
    0,
    REQUEST.operation,
    REQUEST.target,
    REQUEST.resource_ids,
    REQUEST.data_scope,
    NOW - timedelta(seconds=1),
    NOW + timedelta(seconds=60),
    False,
)
CONFIRMATION = ReadConfirmation("enrollment", 1, "host-one", CONTEXT, GRANT, REQUEST)
SUMMARY = TaskSummary("task", "Small task", "captured", "2026-12-31")


def scope(request=REQUEST):
    return {
        name: getattr(request, name)
        for name in ("operation", "target", "resource_ids", "data_scope")
    }


class SyntheticHost:
    """Test-only capability model; not a production identity implementation."""

    def __init__(self, events):
        self.confirmation = CONFIRMATION
        self.host_incarnation = "host-one"
        self.handle = object()
        self.used = False
        self.live = True
        self.now = NOW
        self.events = events
        self.fail_exit = False

    @contextmanager
    def hold_admission(self, handle):
        if handle is not self.handle or self.used:
            raise ValueError("untrusted, stale or consumed handle")
        self.used = True
        self.events.append("host_enter")
        try:
            yield self
        finally:
            self.events.append("host_exit")
            if self.fail_exit:
                raise ValueError("private adapter error")

    def validate_and_now(self):
        self.events.append("clock")
        if not self.live:
            raise ValueError("session invalidated")
        return self.now


class SyntheticSource:
    def __init__(self, events):
        self.events = events
        self.rows = (SUMMARY,)
        self.on_enter = lambda: None
        self.on_read = lambda: None
        self.fail_exit = False

    @contextmanager
    def open_snapshot(self, owner_id, profile_id, request):
        assert (owner_id, profile_id) == ("owner", "profile")
        self.events.append("ownership")
        self.on_enter()
        try:
            yield self
        finally:
            self.events.append("snapshot_exit")
            if self.fail_exit:
                raise ValueError("private snapshot error")

    def read_summaries(self):
        self.events.append("read")
        self.on_read()
        return self.rows


@pytest.fixture
def setup():
    connection = sqlite3.connect(":memory:")
    store = EnrollmentStore(connection)
    store.initialize()
    store.run(
        "create",
        {
            **KEY,
            "transport_id": "telegram",
            "transport_receiver_id": "bot",
            "principal_id": "actor",
            "scope": scope(),
        },
    )
    events = []
    host, source = SyntheticHost(events), SyntheticSource(events)
    service = ReadAdmissionService(store, host_authority=host, resource_source=source, enabled=True)
    yield store, host, source, service, events
    connection.close()


def read(setup, key=None, request=REQUEST, handle=None):
    _, host, _, service, _ = setup
    return service.read(
        KEY if key is None else key, request, live_handle=host.handle if handle is None else handle
    )


def denied(setup, **kwargs):
    with pytest.raises(ReadAdmissionError) as error:
        read(setup, **kwargs)
    assert "private" not in str(error.value)
    return error.value.code


@pytest.mark.parametrize("enabled", [False, None, 1, "yes"])
def test_disabled_no_access(enabled):
    class Bomb:
        def __getattr__(self, name):
            raise AssertionError("must not access adapters/storage")

    service = ReadAdmissionService(
        Bomb(), host_authority=Bomb(), resource_source=Bomb(), enabled=enabled
    )
    with pytest.raises(ReadAdmissionError, match="unavailable"):
        service.read({}, REQUEST, live_handle=object())


@pytest.mark.parametrize("missing", ["host", "resource", "both"])
def test_missing_adapter(setup, missing):
    store, host, source, _, events = setup
    service = ReadAdmissionService(
        store,
        enabled=True,
        host_authority=None if missing in ("host", "both") else host,
        resource_source=None if missing in ("resource", "both") else source,
    )
    with pytest.raises(ReadAdmissionError, match="unavailable"):
        service.read(KEY, REQUEST, live_handle=host.handle)
    assert events == []


def test_success_fences_and_no_replay(setup):
    store, host, source, _, events = setup
    store._connection.set_trace_callback(
        lambda sql: events.append(sql) if sql in ("BEGIN IMMEDIATE", "COMMIT") else None
    )
    assert read(setup) == (SUMMARY,)
    assert events == [
        "host_enter",
        "clock",
        "BEGIN IMMEDIATE",
        "clock",
        "ownership",
        "clock",
        "read",
        "clock",
        "snapshot_exit",
        "clock",
        "COMMIT",
        "host_exit",
    ]
    assert denied(setup) == "admission_failed"
    assert events.count("read") == 1
    with pytest.raises(FrozenInstanceError):
        SUMMARY.title = "changed"


@pytest.mark.parametrize(
    "key", [{}, {**KEY, "extra": "x"}, {**KEY, "owner_id": "../x"}, [], {**KEY, "owner_id": True}]
)
def test_invalid_selectors(setup, key):
    assert denied(setup, key=key) == "invalid_request"
    assert setup[-1] == []


@pytest.mark.parametrize(
    "candidate_request",
    [
        {},
        replace(REQUEST, target="own_inbox", resource_ids=()),
        replace(REQUEST, resource_ids=tuple(f"t{x}" for x in range(33))),
        replace(REQUEST, resource_ids=("task", "task")),
        replace(REQUEST, resource_ids=["task"]),
        replace(REQUEST, data_scope="tasks.details"),
        replace(
            REQUEST,
            operation="personal.primary_binding.inspect",
            target="primary_binding",
            resource_ids=(),
            data_scope="primary_binding.metadata",
        ),
    ],
)
def test_invalid_request_before_host(setup, candidate_request):
    assert denied(setup, request=candidate_request) == "invalid_request"
    assert setup[-1] == []


@pytest.mark.parametrize(
    "change",
    [
        {"enrollment_id": "other"},
        {"enrollment_revision": True},
        {"host_incarnation": "old"},
        {"context": replace(CONTEXT, owner_id="other")},
        {"context": replace(CONTEXT, session_id="other")},
        {"context": replace(CONTEXT, owned_task_ids=())},
        {"grant": replace(GRANT, resource_ids=("task", "extra"))},
        {"grant": replace(GRANT, revoked=True)},
        {"grant": replace(GRANT, expires_at=NOW)},
        {"request": replace(REQUEST, resource_ids=("other",))},
    ],
)
def test_bad_confirmation_before_resources(setup, change):
    setup[1].confirmation = replace(CONFIRMATION, **change)
    denied(setup)
    assert "ownership" not in setup[-1]


@pytest.mark.parametrize("handle", [{"approved": True}, "handle", CONFIRMATION])
def test_opaque_handle_not_claims(setup, handle):
    denied(setup, handle=handle)
    assert setup[-1] == []


@pytest.mark.parametrize("action", ["set_policy", "revoke"])
def test_stale_or_revoked_persisted_policy(setup, action):
    payload = {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1}
    if action == "set_policy":
        payload["scope"] = scope()
    setup[0].run(action, payload)
    assert denied(setup) == "policy_denied"
    assert "ownership" not in setup[-1]


def test_independent_confirmed_identity_must_match_candidate(setup):
    setup[1].confirmation = replace(
        CONFIRMATION,
        context=replace(CONTEXT, principal_id="new"),
        grant=replace(GRANT, principal_id="new"),
    )
    assert denied(setup) == "identity_mismatch"
    assert "ownership" not in setup[-1]


@pytest.mark.parametrize(
    "rows",
    [
        [],
        (),
        (SUMMARY, SUMMARY),
        (replace(SUMMARY, task_id="foreign"),),
        ({"task_id": "task", "title": "secret"},),
        (replace(SUMMARY, title="x" * 241),),
        (replace(SUMMARY, title=""),),
        (replace(SUMMARY, title="line\nnext"),),
        (replace(SUMMARY, state="unknown"),),
        (replace(SUMMARY, due_date="2026-02-30"),),
        (replace(SUMMARY, due_date="20261231"),),
        (replace(SUMMARY, due_date=NOW),),
    ],
)
def test_bounded_minimal_snapshot(setup, rows):
    setup[2].rows = rows
    assert denied(setup) == "invalid_snapshot"
    assert not setup[0]._connection.in_transaction


@pytest.mark.parametrize("stage", ["enter", "read"])
@pytest.mark.parametrize("change", ["expiry", "invalidated", "bad_clock"])
def test_recheck_after_wait_and_after_read(setup, stage, change):
    _, host, source, _, events = setup

    def invalidate():
        if change == "expiry":
            host.now = GRANT.expires_at
        elif change == "bad_clock":
            host.now = NOW.replace(tzinfo=None)
        else:
            host.live = False

    setattr(source, "on_" + stage, invalidate)
    denied(setup)
    if stage == "enter":
        assert "read" not in events
    assert "snapshot_exit" in events


@pytest.mark.parametrize("failure", ["snapshot", "guard", "commit", "read"])
def test_failures_never_return_data(setup, failure):
    store, host, source, _, events = setup
    if failure == "snapshot":
        source.fail_exit = True
    elif failure == "guard":
        host.fail_exit = True
    elif failure == "read":

        def fail():
            raise RuntimeError("private read error")

        source.on_read = fail
    else:
        store._connection.set_authorizer(
            lambda action, arg, *_: (
                sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_TRANSACTION and arg == "COMMIT"
                else sqlite3.SQLITE_OK
            )
        )
    denied(setup)
    assert events[-1] == "host_exit"
    assert not store._connection.in_transaction


def test_snapshot_cannot_suppress_failed_post_read_check(setup):
    _, host, source, service, events = setup

    class SuppressingSnapshot:
        @contextmanager
        def open_snapshot(self, owner_id, profile_id, request):
            try:
                yield source
            except ReadAdmissionError:
                pass  # Deliberately broken trusted adapter must not leak a result.

    source.on_read = lambda: setattr(host, "now", GRANT.expires_at)
    service._resource_source = SuppressingSnapshot()
    assert denied(setup) == "snapshot_incomplete"
    assert "read" in events


@pytest.mark.parametrize("title", ["   ", "x\u200by", "x\u2028y", "x\ud800y", "x\u2029y"])
def test_summary_unicode_controls(setup, title):
    setup[2].rows = (replace(SUMMARY, title=title),)
    assert denied(setup) == "invalid_snapshot"


def test_maximum_bound_request_order_and_candidate_superset(setup):
    store, host, source, _, _ = setup
    ids = tuple(f"task-{i}" for i in range(32))
    request = replace(REQUEST, resource_ids=ids)
    store.run(
        "set_policy",
        {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1, "scope": scope(request)},
    )
    host.confirmation = replace(
        CONFIRMATION,
        request=request,
        context=replace(CONTEXT, owned_task_ids=ids, policy_revision=2, epoch=1),
        grant=replace(GRANT, resource_ids=ids, policy_revision=2, epoch=1),
    )
    source.rows = tuple(replace(SUMMARY, task_id=i, due_date=None) for i in reversed(ids))
    assert tuple(row.task_id for row in read(setup, request=request)) == ids


def test_candidate_allows_exact_subset_but_not_grant_reuse(setup):
    store, host, source, _, _ = setup
    candidate = replace(REQUEST, resource_ids=("task", "other"))
    store.run(
        "set_policy",
        {
            **KEY,
            "expected_revision": 1,
            "expected_enrollment_revision": 1,
            "scope": scope(candidate),
        },
    )
    host.confirmation = replace(
        CONFIRMATION,
        context=replace(CONTEXT, policy_revision=2, epoch=1),
        grant=replace(GRANT, policy_revision=2, epoch=1),
    )
    assert read(setup) == (SUMMARY,)


@pytest.mark.parametrize(
    "candidate",
    [
        replace(REQUEST, resource_ids=("other",)),
        replace(REQUEST, target="own_inbox", resource_ids=()),
        replace(REQUEST, resource_ids=tuple(f"task-{i}" for i in range(33))),
    ],
)
def test_candidate_cannot_expand_scope(setup, candidate):
    store, host, _, _, events = setup
    store.run(
        "set_policy",
        {
            **KEY,
            "expected_revision": 1,
            "expected_enrollment_revision": 1,
            "scope": scope(candidate),
        },
    )
    host.confirmation = replace(
        CONFIRMATION,
        context=replace(CONTEXT, policy_revision=2, epoch=1),
        grant=replace(GRANT, policy_revision=2, epoch=1),
    )
    assert denied(setup) == "scope_mismatch"
    assert "ownership" not in events


@pytest.mark.parametrize("kind", ["unknown_code", "subclass", "modified_args", "modified_code"])
def test_adapter_admission_errors_are_sanitized(setup, kind):
    class PrivateError(ReadAdmissionError):
        def __str__(self):
            return "private-data"

    error = (
        PrivateError("invalid_snapshot")
        if kind == "subclass"
        else ReadAdmissionError("private-data" if kind == "unknown_code" else "invalid_snapshot")
    )
    if kind == "modified_args":
        error.args = ("private-data",)
    elif kind == "modified_code":
        error.code = "private-data"

    def fail():
        raise error

    setup[2].on_read = fail
    with pytest.raises(ReadAdmissionError) as caught:
        read(setup)
    assert type(caught.value) is ReadAdmissionError
    assert "private-data" not in str(caught.value)
    assert caught.value.code == (
        "invalid_snapshot" if kind == "modified_args" else "admission_failed"
    )
    assert caught.value is not error


@pytest.mark.parametrize("code", ["private-data", [], None, True])
def test_admission_error_constructor_only_accepts_fixed_codes(code):
    error = ReadAdmissionError(code)
    assert error.code == "admission_failed"
    assert str(error) == "Read admission failed (admission_failed)."
