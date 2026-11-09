"""Frozen native worker configuration plus current transactional synthetic reads.

No owner adoption, WorkerChannel, real model, credential or external write is
exercised. The native model-facing dispatcher is called directly. The handler
uses the existing coordinator with explicitly synthetic independent adapters.
"""

import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from personal_agent.enrollment import EnrollmentStore

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "worker_policy_probe"
ROOT = FIXTURE.parents[2]
read_frame = runpy.run_path(str(FIXTURE / "protocol.py"))["read_frame"]
KEY = {"owner_id": "owner", "profile_id": "profile", "enrollment_id": "enrollment"}
SCOPE = {
    "operation": "personal.tasks.read",
    "target": "exact_tasks",
    "resource_ids": ("task",),
    "data_scope": "tasks.summary",
}


class Worker:
    def __init__(self, process):
        self.process = process

    def send(self, **command):
        self.process.stdin.write(json.dumps(command) + "\n")
        self.process.stdin.flush()

    def read(self):
        return read_frame(self.process.stdout.fileno())

    def issue(self, revision=1, epoch=0, enrollment_revision=1):
        self.send(
            op="issue", revision=revision, epoch=epoch, enrollment_revision=enrollment_revision
        )
        assert self.read() == {"issued": True}

    def call(self, path="model", **options):
        self.send(op="call", path=path, **options)
        return self.read()


@contextmanager
def connection(path):
    db = sqlite3.connect(path, timeout=10)
    try:
        store = EnrollmentStore(db)
        store.initialize()
        yield db, store
    finally:
        db.close()


@pytest.fixture
def worker(tmp_path, request):
    import hermes_cli.plugins

    host = Path(hermes_cli.plugins.__file__).resolve().parents[1]
    home = tmp_path / "home"
    shutil.copytree(
        FIXTURE,
        home / "plugins" / "worker-policy-probe",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    # Live config disagrees from launch and changes again while the child lives.
    (home / "config.yaml").write_text(
        json.dumps({"plugins": {"enabled": []}, "agent": {"max_turns": 99}})
    )
    path = home / "policy.sqlite3"
    with connection(path) as (_, store):
        store.run(
            "create",
            {
                **KEY,
                "transport_id": "synthetic",
                "transport_receiver_id": "bot",
                "principal_id": "actor",
                "scope": SCOPE,
            },
        )
    env = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR")
        if key in os.environ
    }
    env.update(
        HOME=str(tmp_path / "os-home"),
        HERMES_HOME=str(home),
        HERMES_BUNDLED_PLUGINS=str(bundled),
        HERMES_ENABLE_PROJECT_PLUGINS="0",
    )
    mode = getattr(request, "param", "ordinary")
    with (tmp_path / "stderr.log").open("w+") as errors:
        process = subprocess.Popen(
            [sys.executable, str(FIXTURE / "worker.py"), str(host), str(ROOT), mode],
            cwd=tmp_path,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            bufsize=1,
        )
        client = Worker(process)
        try:
            ready = client.read()
            yield client, path, ready
        finally:
            if process.poll() is None:
                try:
                    client.send(op="stop")
                    process.wait(timeout=3)
                except OSError, subprocess.TimeoutExpired:
                    process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
            errors.seek(0)
            assert process.returncode == 0, errors.read()


def mutate(path, operation):
    with connection(path) as (_, store):
        payload = {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1}
        if operation == "set_policy":
            payload["scope"] = SCOPE
        return store.run(operation, payload)


def history(path):
    with connection(path) as (_, store):
        return store.read_admission_history(KEY)["items"]


def allowed(result):
    assert result["result"] == {"titles": ["Synthetic bounded summary"]}
    assert result["config"] == 7 and result["transaction"] is False


def denied(result, code="policy_denied"):
    assert result["result"] == {"denied": code}
    assert result["config"] == 7 and result["transaction"] is False
    assert "Synthetic bounded summary" not in json.dumps(result)
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("change", ["revoke", "set_policy"])
def test_live_worker_rechecks_persistent_policy_on_both_dispatch_paths(worker, change):
    """E04-WP-01: same allowed handler/process refuses after separate-connection change."""
    client, path, ready = worker
    assert ready["ready"]
    for route in ("model", "registry"):
        client.issue()
        allowed(client.call(route))
    client.issue()  # Independently issued before mutation, never from the pending row.
    changed = mutate(path, change)
    assert changed["epoch"] == 1
    (path.parent / "config.yaml").write_text("[broken YAML")
    first = client.call()
    denied(first)
    client.issue()
    second = client.call("registry")
    denied(second)
    assert first["pid"] == second["pid"] == ready["pid"]
    assert first["reads"] == second["reads"] == 2
    assert second["calls"] == 4  # Denial really happens inside the handler.
    rows = history(path)
    assert len(rows) == 2
    assert all(row["epoch"] == 0 and row["policy_revision"] == 1 for row in rows)
    assert all(row["outcome"] == "snapshot_prepared" for row in rows)
    assert all(row["resource_count"] == 1 for row in rows)
    assert not any(
        secret in json.dumps(rows)
        for secret in ("Synthetic bounded summary", '"task"', "actor", "bot", "session", "grant")
    )
    if change == "set_policy":
        # Trusted harness explicitly issues a NEW independent synthetic confirmation.
        client.issue(revision=2, epoch=1)
        allowed(client.call())
        assert history(path)[-1]["epoch"] == 1
        with connection(path) as (_, store):
            assert store.run("get", KEY)["state"] == "pending"
    else:
        assert changed["state"] == "revoked"
        # Hostile synthetic revival attempt: matching administrative counters
        # are test inputs, never an authority issuer or activation mechanism.
        for route in ("model", "registry"):
            client.issue(
                revision=changed["policy_revision"],
                epoch=changed["epoch"],
                enrollment_revision=changed["enrollment_revision"],
            )
            current_but_revoked = client.call(route)
            denied(current_but_revoked)
            assert current_but_revoked["pid"] == ready["pid"]
            assert current_but_revoked["reads"] == 2
        assert history(path) == rows


@pytest.mark.parametrize("missing", ["host", "resource"])
def test_pending_record_and_model_claims_do_not_replace_adapters(worker, missing):
    """E04-WP-02: stored pending labels plus approved/draft arguments are not authority."""
    client, path, _ = worker
    client.issue()
    result = client.call("registry", missing=missing)
    denied(result, "unavailable")
    assert result["reads"] == 0 and history(path) == []


@pytest.mark.parametrize("failure", ["storage", "audit", "commit"])
def test_handler_storage_failures_return_no_data_or_committed_audit(worker, failure):
    """E04-WP-03: actual SQLite authorizer fault, including failure after materialization."""
    client, path, _ = worker
    client.issue()
    result = client.call(failure=failure)
    denied(result)
    assert result["reads"] == (failure != "storage")
    assert history(path) == []
    client.issue()
    allowed(client.call("registry"))
    assert len(history(path)) == 1


@pytest.mark.parametrize("worker", ["safe"], indirect=True)
def test_safe_worker_suppresses_fixture_plugin_and_registry(worker):
    """E04-WP-04: native safe policy suppresses this plugin, not a host-wide sandbox."""
    _, path, ready = worker
    assert ready["loaded"] is False and ready["registered"] is False
    assert "Unknown tool" in ready["registry"]["error"]
    assert "error" in ready["model"]
    assert history(path) == []


def test_admission_holds_sqlite_lock_before_competing_revoke(worker):
    """E04-WP-05: real busy evidence, then admitted audit precedes waiting revoke."""
    client, path, _ = worker
    client.issue()
    initialized, start_revoke = threading.Event(), threading.Event()
    attempted, finished = threading.Event(), threading.Event()
    results, failures = [], []

    def revoke():
        db = sqlite3.connect(path, timeout=10)
        try:
            store = EnrollmentStore(db)
            store.initialize()
            initialized.set()
            assert start_revoke.wait(10)
            db.set_trace_callback(lambda sql: attempted.set() if sql == "BEGIN IMMEDIATE" else None)
            results.append(
                store.run(
                    "revoke", {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1}
                )
            )
        except BaseException as error:
            failures.append(error)
        finally:
            db.close()
            finished.set()

    thread = threading.Thread(target=revoke)
    thread.start()
    try:
        assert initialized.wait(5)
        client.send(op="call", path="model", hold=True)
        assert client.read() == {"reading": True}
        # This actual failed BEGIN proves the worker already holds the SQLite lock.
        with sqlite3.connect(path, timeout=0) as contender:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("BEGIN IMMEDIATE")
        start_revoke.set()
        assert attempted.wait(5) and not finished.is_set()
        client.send(op="release")
        allowed(client.read())
    finally:
        thread.join(timeout=12)
        assert not thread.is_alive()
    assert failures == [] and results[0]["state"] == "revoked"
    assert history(path)[0]["epoch"] == 0
    client.issue()
    denied(client.call("registry"))


def test_revoke_commit_wins_while_worker_waits_for_sqlite(worker):
    """E04-WP-06: held revoke COMMIT, worker BEGIN attempted, then no resource read."""
    client, path, _ = worker
    client.issue()
    holding, release = threading.Event(), threading.Event()
    failures = []

    def revoke():
        with connection(path) as (db, store):

            def trace(sql):
                if sql == "COMMIT":
                    holding.set()
                    assert release.wait(10)

            db.set_trace_callback(trace)
            try:
                store.run(
                    "revoke", {**KEY, "expected_revision": 1, "expected_enrollment_revision": 1}
                )
            except BaseException as error:
                failures.append(error)

    thread = threading.Thread(target=revoke)
    thread.start()
    try:
        assert holding.wait(5)
        with sqlite3.connect(path, timeout=0) as contender:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("BEGIN IMMEDIATE")
        client.send(op="call", path="model", trace=True)
        assert client.read() == {"begin": True}
    finally:
        release.set()
        thread.join(timeout=12)
        assert not thread.is_alive()
    assert failures == []
    result = client.read()
    denied(result)
    assert result["reads"] == 0 and history(path) == []
    client.issue()
    denied(client.call("registry"))


def test_confirmation_is_consumed_across_dispatch_paths(worker):
    """E04-WP-07: pending metadata and replayed model claims cannot renew a handle."""
    client, path, _ = worker
    client.issue()
    allowed(client.call())
    result = client.call("registry")
    denied(result, "admission_failed")
    assert result["reads"] == 1 and len(history(path)) == 1


@pytest.mark.parametrize("partial", [b"", b"{", b'{"x":'])
def test_worker_protocol_partial_frames_obey_deadline(partial):
    """E04-WP-08: no newline may not extend the absolute read deadline."""
    reader, writer = os.pipe()
    try:
        os.write(writer, partial)
        started = time.monotonic()
        with pytest.raises(TimeoutError, match="deadline"):
            read_frame(reader, timeout=0.05)
        assert time.monotonic() - started < 2
    finally:
        os.close(reader)
        os.close(writer)


@pytest.mark.parametrize("partial", [b"", b"{"])
def test_worker_protocol_eof_refuses_incomplete_frame(partial):
    reader, writer = os.pipe()
    try:
        os.write(writer, partial)
    finally:
        os.close(writer)
    try:
        with pytest.raises(EOFError, match="complete frame"):
            read_frame(reader, timeout=0.1)
    finally:
        os.close(reader)


def test_worker_protocol_size_limit_and_consecutive_frames():
    reader, writer = os.pipe()
    try:
        os.write(writer, b'{"a":1}\n{"b":2}\n')
        assert read_frame(reader, timeout=0.1) == {"a": 1}
        assert read_frame(reader, timeout=0.1) == {"b": 2}
        os.write(writer, b"123456789")
        with pytest.raises(ValueError, match="byte limit"):
            read_frame(reader, timeout=0.1, max_bytes=8)
    finally:
        os.close(reader)
        os.close(writer)
