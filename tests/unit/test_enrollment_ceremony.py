"""Synthetic trusted authority, actual SQLite ceremonies; no production issuer."""

import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from personal_agent.enrollment import EnrollmentStore
from personal_agent.enrollment_ceremony import (
    CeremonyError,
    CeremonyStore,
    ChannelObservation,
    EnrollmentCeremony,
)

KEY = {"owner_id": "owner", "profile_id": "profile", "enrollment_id": "enrollment"}
SCOPE = {
    "operation": "personal.tasks.read",
    "target": "exact_tasks",
    "resource_ids": ("task",),
    "data_scope": "tasks.summary",
}
CAS = {"expected_revision": 1, "expected_enrollment_revision": 1, "expected_epoch": 0}
NOW = datetime(2026, 11, 10, tzinfo=UTC)
OBS = ChannelObservation(
    "telegram",
    "receiver",
    "actor",
    "profile",
    "session",
    "host",
    1,
    1,
    "human",
    "direct",
    "dm",
    False,
)


class Authority:
    def __init__(self):
        self.handles = {}
        self.exit_error = False
        self.now = NOW
        self.calls = []

    def issue(self, purpose, challenge=None, observation=OBS):
        handle = object()
        self.handles[handle] = (purpose, challenge, observation)
        return handle

    @contextmanager
    def hold_observation(self, handle, *, purpose):
        self.calls.append(purpose)
        if type(handle) is not object or handle not in self.handles:
            raise CeremonyError("invalid_observation")
        expected, challenge, observed = self.handles.pop(handle)
        if expected != purpose:
            raise CeremonyError("invalid_observation")
        yield SimpleNamespace(
            observation=observed,
            confirmed_challenge_id=challenge,
            validate_and_now=lambda: self.now,
        )
        if self.exit_error:
            raise RuntimeError("private adapter details")


@pytest.fixture
def ceremony(tmp_path):
    enrollment_db = sqlite3.connect(tmp_path / "enrollment.sqlite3")
    challenge_db = sqlite3.connect(tmp_path / "challenge.sqlite3")
    enrollment = EnrollmentStore(enrollment_db)
    enrollment.initialize()
    enrollment.run(
        "create",
        {
            **KEY,
            "transport_id": "telegram",
            "transport_receiver_id": "receiver",
            "principal_id": "actor",
            "scope": SCOPE,
        },
    )
    challenges = CeremonyStore(challenge_db)
    challenges.initialize()
    authority = Authority()
    coordinator = EnrollmentCeremony(enrollment, challenges, authority=authority, enabled=True)
    yield coordinator, authority, enrollment_db, challenge_db
    challenge_db.close()
    enrollment_db.close()


def issue(c, a):
    return c.run("issue", KEY, **CAS, live_handle=a.issue("issue"))["challenge_id"]


def confirm(c, a, key, observation=OBS, handle=None):
    return c.run(
        "confirm",
        KEY,
        **CAS,
        challenge_id=key,
        live_handle=handle or a.issue("confirm", key, observation),
    )


def test_default_unavailable_before_any_store_or_host_work():
    class Bomb:
        def __getattribute__(self, name):
            pytest.fail("unavailable must not inspect stores or authority")

    for enabled, authority in [(False, Bomb()), (True, None), (1, Bomb())]:
        c = EnrollmentCeremony(Bomb(), Bomb(), authority=authority, enabled=enabled)
        with pytest.raises(CeremonyError, match="unavailable"):
            c.run("issue", {}, **CAS, live_handle={"approved": True})


def test_confirmed_evidence_not_enrollment_activation_or_grant(ceremony):
    c, a, db, ch = ceremony
    key = issue(c, a)
    assert confirm(c, a, key) == {"challenge_id": key, "state": "confirmed", "authority": False}
    assert c.challenges.inspect(key)["authority"] is False
    assert c.enrollment.run("get", KEY)["state"] == "pending"
    assert ch.execute("SELECT outcome FROM ceremony_events ORDER BY sequence").fetchall() == [
        ("issued",),
        ("confirmed",),
    ]
    assert db.execute("SELECT count(*) FROM read_admissions").fetchone()[0] == 0
    with pytest.raises(CeremonyError, match="challenge_unavailable"):
        confirm(c, a, key)


@pytest.mark.parametrize(
    "field,value",
    [
        ("transport_id", "other"),
        ("transport_receiver_id", "other"),
        ("principal_id", "third-party"),
        ("profile_id", "other"),
        ("session_id", "rotated"),
        ("host_incarnation", "restarted"),
        ("route_revision", 2),
        ("device_revision", 2),
        ("actor_kind", "bot"),
        ("provenance", "forwarded"),
        ("provenance", "internal"),
        ("conversation_kind", "group"),
        ("device_revoked", True),
        ("route_revision", True),
    ],
)
def test_wrong_or_untrusted_source_consumes_challenge_attempt(ceremony, field, value):
    c, a, _, _ = ceremony
    key = issue(c, a)
    bad = replace(OBS, **{field: value})
    assert confirm(c, a, key, bad)["state"] == "consumed"
    with pytest.raises(CeremonyError, match="challenge_unavailable"):
        confirm(c, a, key)


def test_confirmation_is_exact_challenge_bound_and_not_json(ceremony):
    c, a, _, _ = ceremony
    key = issue(c, a)
    with pytest.raises(CeremonyError, match="invalid_observation"):
        confirm(c, a, key, handle={"approved": True, "challenge_id": key})
    assert c.challenges.inspect(key)["state"] == "pending"  # never admitted
    wrong = a.issue("confirm", "other")
    with pytest.raises(CeremonyError, match="confirmation_mismatch"):
        confirm(c, a, key, handle=wrong)
    assert c.challenges.inspect(key)["state"] == "pending"
    assert wrong not in a.handles


@pytest.mark.parametrize("delta", [timedelta(minutes=5), timedelta(minutes=6)])
def test_expiry_is_exclusive(ceremony, delta):
    c, a, _, _ = ceremony
    key = issue(c, a)
    a.now += delta
    assert confirm(c, a, key)["state"] == "consumed"


def test_policy_change_or_revoke_before_admission_keeps_challenge_pending(ceremony):
    c, a, _, _ = ceremony
    key = issue(c, a)
    c.enrollment.run("revoke", {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1})
    handle = a.issue("confirm", key)
    with pytest.raises(CeremonyError, match="outcome_uncertain"):
        confirm(c, a, key, handle=handle)
    assert handle not in a.handles
    assert c.challenges.inspect(key)["state"] == "pending"
    # No claim that DB challenge consumed when current-policy admission never happened.


@pytest.mark.parametrize("failure", ["host_exit", "enrollment_commit"])
def test_inner_commit_survives_outer_failure_without_reusable_authority(ceremony, failure):
    c, a, db, _ = ceremony
    key = issue(c, a)
    if failure == "host_exit":
        a.exit_error = True
    else:
        db.set_authorizer(
            lambda op, arg, *rest: (
                sqlite3.SQLITE_DENY
                if op == sqlite3.SQLITE_TRANSACTION and arg == "COMMIT"
                else sqlite3.SQLITE_OK
            )
        )
    handle = a.issue("confirm", key)
    with pytest.raises(CeremonyError, match="outcome_uncertain"):
        confirm(c, a, key, handle=handle)
    db.set_authorizer(None)
    a.exit_error = False
    assert handle not in a.handles
    assert c.challenges.inspect(key) == {
        "challenge_id": key,
        "state": "confirmed",
        "authority": False,
    }
    with pytest.raises(CeremonyError, match="challenge_unavailable"):
        confirm(c, a, key)


@pytest.mark.parametrize("failure", ["audit", "commit"])
def test_challenge_transaction_rollback_does_not_reissue_host_handle(ceremony, failure):
    c, a, _, ch = ceremony
    key = issue(c, a)

    def deny(op, arg, *rest):
        if failure == "audit" and op == sqlite3.SQLITE_INSERT and arg == "ceremony_events":
            return sqlite3.SQLITE_DENY
        if failure == "commit" and op == sqlite3.SQLITE_TRANSACTION and arg == "COMMIT":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    ch.set_authorizer(deny)
    handle = a.issue("confirm", key)
    with pytest.raises(CeremonyError, match="storage_failed"):
        confirm(c, a, key, handle=handle)
    ch.set_authorizer(None)
    assert handle not in a.handles
    assert c.challenges.inspect(key)["state"] == "pending"
    assert confirm(c, a, key)["state"] == "confirmed"  # new independent confirmation only


def test_storage_schema_and_caller_transaction_refused(ceremony):
    c, _, _, ch = ceremony
    ch.execute("BEGIN")
    with pytest.raises(CeremonyError, match="connection_in_transaction"):
        c.challenges.initialize()
    assert ch.in_transaction
    ch.rollback()
    ch.execute("CREATE TEMP TABLE unexpected(value)")
    with pytest.raises(CeremonyError, match="unsupported_schema"):
        c.challenges.initialize()


def test_current_new_policy_cannot_confirm_old_scope_snapshot(ceremony):
    c, a, _, _ = ceremony
    key = issue(c, a)
    c.enrollment.run(
        "set_policy",
        {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1, "scope": SCOPE},
    )
    result = c.run(
        "confirm",
        KEY,
        expected_revision=2,
        expected_enrollment_revision=1,
        expected_epoch=1,
        challenge_id=key,
        live_handle=a.issue("confirm", key),
    )
    assert result["state"] == "consumed"  # even a no-op policy change fences old evidence


def test_independent_connections_confirm_only_once(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    path = tmp_path / "challenges.db"
    with sqlite3.connect(path) as db:
        store = CeremonyStore(db)
        store.initialize()
        key = store.issue(lambda: "exact", lambda: NOW, enrollment_key="synthetic")
    barrier = Barrier(2)

    def attempt(_):
        db = sqlite3.connect(path, timeout=5)
        try:
            store = CeremonyStore(db)
            barrier.wait(timeout=3)
            try:
                return store.confirm(key, lambda: "exact", lambda: NOW, enrollment_key="synthetic")
            except CeremonyError as exc:
                return exc.code
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count(True) == 1 and results.count("challenge_unavailable") == 1


def test_expiry_sample_occurs_after_sqlite_lock_wait(tmp_path):
    from threading import Event, Thread

    path = tmp_path / "challenges.db"
    db = sqlite3.connect(path)
    store = CeremonyStore(db)
    store.initialize()
    key = store.issue(lambda: "exact", lambda: NOW, enrollment_key="synthetic")
    db.execute("BEGIN IMMEDIATE")
    waiting = Event()
    current = [NOW]
    samples, results, errors = [], [], []

    def attempt():
        conn = sqlite3.connect(path, timeout=5)
        conn.set_trace_callback(lambda sql: waiting.set() if sql == "BEGIN IMMEDIATE" else None)

        def now():
            samples.append(current[0])
            return current[0]

        try:
            results.append(
                CeremonyStore(conn).confirm(key, lambda: "exact", now, enrollment_key="synthetic")
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    thread = Thread(target=attempt)
    thread.start()
    try:
        assert waiting.wait(3)
        assert samples == []
        current[0] = NOW + timedelta(minutes=5)
    finally:
        db.rollback()
        thread.join(6)
        db.close()
    assert not thread.is_alive() and errors == []
    assert samples == [NOW + timedelta(minutes=5)] and results == [False]


def test_confirmation_for_other_enrollment_cannot_consume_challenge(ceremony):
    c, a, _, _ = ceremony
    key = issue(c, a)
    other = {**KEY, "owner_id": "other"}
    c.enrollment.run(
        "create",
        {
            **other,
            "transport_id": "telegram",
            "transport_receiver_id": "receiver",
            "principal_id": "actor",
            "scope": SCOPE,
        },
    )
    with pytest.raises(CeremonyError, match="challenge_unavailable"):
        c.run("confirm", other, **CAS, challenge_id=key, live_handle=a.issue("confirm", key))
    assert c.challenges.inspect(key)["state"] == "pending"
    assert confirm(c, a, key)["state"] == "confirmed"


@pytest.mark.parametrize("observed", [None, {}, object.__new__(ChannelObservation)])
def test_malformed_observation_cannot_issue(ceremony, observed):
    c, a, _, ch = ceremony
    with pytest.raises(CeremonyError):
        c.run("issue", KEY, **CAS, live_handle=a.issue("issue", observation=observed))
    assert ch.execute("SELECT count(*) FROM ceremonies").fetchone()[0] == 0


@pytest.mark.parametrize("now", [NOW.replace(tzinfo=None), 123, NOW - timedelta(seconds=1)])
def test_confirmation_rejects_invalid_or_preissue_time(ceremony, now):
    c, a, _, _ = ceremony
    key = issue(c, a)
    a.now = now
    assert confirm(c, a, key)["state"] == "consumed"
