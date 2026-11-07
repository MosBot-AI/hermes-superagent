"""Production promotion gates, explicit disclosure, and durable synthetic ledger."""

import json
import sys
import time
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from personal_agent import task_plan_worker as worker
from personal_agent import task_worker_ledger as ledger
from personal_agent.task_worker_presentation import quoted
from personal_agent.tasks import TaskError


class Service:
    @property
    def text_worker_contract(self):
        return worker.HOST_TEXT_WORKER_CONTRACT

    def launch_text(self, *args):
        raise AssertionError("unit tests never submit a model request")

    def authorize_text_route(self, *args, **kwargs):
        return "a" * 64

    def result(self, *args):
        raise AssertionError("unit tests never poll a host")


@pytest.fixture
def home(tmp_path, monkeypatch):
    from personal_agent import session_task_tools

    tmp_path.chmod(0o700)
    monkeypatch.setattr(ledger, "current_profile_home", lambda: tmp_path)
    monkeypatch.setattr(session_task_tools, "current_profile_home", lambda: tmp_path)
    storage = ModuleType("plugins.plugin_storage")
    (tmp_path / "plugin-data").mkdir(mode=0o700)
    (tmp_path / "plugin-data" / ledger.PLUGIN_ID).mkdir(mode=0o700)
    storage.plugin_data_dir = lambda _: tmp_path / "plugin-data" / ledger.PLUGIN_ID
    monkeypatch.setitem(sys.modules, "plugins", ModuleType("plugins"))
    monkeypatch.setitem(sys.modules, "plugins.plugin_storage", storage)
    return tmp_path


def consumer(home, **changes):
    settings = dict(
        mode="local_tasks", local_conversation=True, local_model_tools=True, plan_worker=True
    )
    settings.update(changes)
    permission = [True]
    instance = worker.TaskPlanningWorker(
        bound_home=home,
        read_config=lambda k, d: settings.get(k, d),
        service=Service(),
        check_capability=lambda capability: permission[0],
    )
    return instance, settings, permission


def test_context_allowlist_no_evolving_task_metadata():
    task = dict(
        id=str(uuid4()),
        revision=1,
        title="中文",
        state="captured",
        project="P",
        due_date=None,
        work_status="ready",
        details="selected details",
        dependencies=[{"title": "SECRET DEPENDENCY"}],
        native_progress={"secret": "NATIVE"},
        progress_note="UNSELECTED",
        resolution_note="UNSELECTED",
    )
    context = worker.task_context(task)
    payload = json.loads(context.split("\n", 1)[1])
    assert set(payload["task"]) == set(worker.CONTEXT_KEYS)
    assert not any(value in context for value in ("SECRET", "NATIVE", "UNSELECTED"))
    task["details"] = "😀" * 5000
    bounded = worker.task_context(task)
    assert len(bounded) <= worker.MAX_CONTEXT_CHARS
    assert json.loads(bounded.split("\n", 1)[1])["omitted_fields"] == ["details"]


@pytest.mark.parametrize(
    "service",
    [
        SimpleNamespace(launch_text=lambda: None, authorize_text_route=lambda: None),
        SimpleNamespace(
            text_worker_contract="hermes.text-worker.v1",
            launch_text=lambda: None,
            authorize_text_route=lambda: None,
            result=lambda: None,
        ),
    ],
)
def test_callable_presence_or_mutable_marker_is_not_host_support(service):
    with pytest.raises(TaskError, match="plan_worker_host_unsupported"):
        worker.require_host_contract(service)


def test_exact_readonly_marker_required():
    worker.require_host_contract(Service())

    class Wrong(Service):
        @property
        def text_worker_contract(self):
            return "hermes.text-worker.v2"

    with pytest.raises(TaskError):
        worker.require_host_contract(Wrong())


@pytest.mark.parametrize("revoke", ["config", "consent", "host"])
def test_observed_revocation_latches_local_before_ledger_io_failure(home, monkeypatch, revoke):
    instance, settings, permission = consumer(home)
    key = ("session", "route", "key")
    grant = worker.Grant(str(uuid4()), 1, "context", time.monotonic() + 120)
    instance.grants[key] = grant
    if revoke == "config":
        settings["plan_worker"] = False
    elif revoke == "consent":
        permission[0] = False
    else:
        instance.service = object()

    def fail():
        raise TaskError("storage_busy")

    monkeypatch.setattr(instance.ledger, "revoke_owned", fail)
    with pytest.raises(TaskError):
        instance._configured()
    assert grant.state == "revoked"
    settings["plan_worker"] = True
    permission[0] = True
    instance.service = Service()
    instance._configured()
    assert grant.state == "revoked"


def test_default_off_and_capability_rechecked(home):
    instance, settings, permission = consumer(home)
    instance._configured()
    settings.pop("plan_worker")
    with pytest.raises(TaskError, match="plan_worker_disabled"):
        instance._configured()
    settings["plan_worker"] = True
    permission[0] = False
    with pytest.raises(TaskError, match="plan_worker_consent_required"):
        instance._configured()


def test_ledger_durable_claim_no_foreign_owner_adoption(home):
    first = ledger.Ledger(home, str(uuid4()))
    key = ("session", "route", "once")
    task_id = str(uuid4())
    first.authorize(key, task_id, 1, "b" * 64, time.time() + 120)
    second = ledger.Ledger(home, str(uuid4()))
    assert second.claim(key, "b" * 64, "a" * 64)[1] is False
    assert first.claim(key, "b" * 64, "a" * 64)[1] is True
    assert first.claim(key, "b" * 64, "a" * 64)[1] is False
    assert second.get(key)["state"] == "claimed"
    with pytest.raises(TaskError, match="request_id_scope_conflict"):
        second.get(("other", "route", "once"))


def test_ledger_saved_result_survives_new_instance(home):
    first = ledger.Ledger(home, str(uuid4()))
    key, task_id = ("session", "route", "done"), str(uuid4())
    first.authorize(key, task_id, 1, "b" * 64, time.time() + 120)
    first.claim(key, "b" * 64, "a" * 64)
    result = {
        "state": "SUCCEEDED",
        "ready": True,
        "task_id": task_id,
        "snapshot_revision": 1,
        "draft": "中文 draft",
        "result_hash": "c" * 64,
        "notice": "Untrusted planning draft. No task state or external action changed.",
    }
    first.complete(key, result)
    second = ledger.Ledger(home, str(uuid4()))
    assert json.loads(second.get(key)["result"]) == result
    assert second.claim(key, "b" * 64, "a" * 64)[1] is False


def test_quoted_draft_preserves_cjk_and_escapes_controls():
    rendered = quoted("中文😀\x1b[31m\u202e")
    assert "中文😀" in rendered and "\x1b" not in rendered and "\u202e" not in rendered
    assert "\\u202e" in rendered


@pytest.mark.parametrize("crash", [False, True])
def test_consumer_claim_precedes_synthetic_host_and_never_relaunches(home, monkeypatch, crash):
    from contextlib import contextmanager

    instance, _, _ = consumer(home)
    task_id = str(uuid4())
    key = ("session", "route", "once")
    context = "synthetic allowlisted context"
    instance.ledger.authorize(key, task_id, 1, instance._hash(context), time.time() + 120)
    instance.grants[key] = worker.Grant(task_id, 1, context, time.monotonic() + 120)
    monkeypatch.setattr(
        instance, "_task", lambda _: {"id": task_id, "revision": 1, "state": "captured"}
    )

    @contextmanager
    def turn(*args):
        yield "route"

    monkeypatch.setattr(worker.admission, "native_tool_turn", turn)
    calls = []

    class SyntheticService(Service):
        def launch_text(self, request):
            assert instance.ledger.get(key)["state"] == "claimed"
            assert request["provider"] == "opencode-go"
            assert request["model"] == "deepseek-v4.1-flash"
            assert request["expected_route_fingerprint"] == "a" * 64
            calls.append(request)
            if crash:
                raise RuntimeError("synthetic uncertain host outcome")
            return object()

        def result(self, handle):
            return SimpleNamespace(
                terminal_state=SimpleNamespace(value="RUNNING"),
                ready=False,
                summary=None,
                result_hash=None,
            )

    instance.service = SyntheticService()
    first = json.loads(
        instance.run({"action": "launch", "request_id": "once"}, session_id="session")
    )
    instance.run({"action": "launch", "request_id": "once"}, session_id="session")
    assert len(calls) == 1
    assert instance.ledger.get(key)["state"] == "claimed"
    if crash:
        assert first["error"] is not None


def test_register_requires_gate_and_uses_dedicated_toolset(home, monkeypatch):
    monkeypatch.setattr(worker, "current_profile_home", lambda: home)
    commands, tools = [], []
    ctx = SimpleNamespace(
        subagent_lifecycle=Service(),
        has_capability=lambda _: True,
        get_config=lambda k, d: d,
        on_unload=lambda fn: None,
        register_command=lambda *args, **kwargs: commands.append(args),
        register_tool=lambda **kwargs: tools.append(kwargs),
    )
    worker.register(ctx)
    assert commands[0][0] == "personal-plan-worker"
    assert tools[0]["name"] == "personal_task_plan_preview"
    assert tools[0]["toolset"] == "personal_agent_plan_worker"
    ctx.has_capability = lambda _: False
    with pytest.raises(TaskError, match="plan_worker_consent_required"):
        worker.register(ctx)
    assert len(commands) == len(tools) == 1


def test_second_ledger_preflight_preserves_first_process_sqlite_lock(home, monkeypatch):
    """A real child writer detects dropped POSIX locks, unlike same-process SQLite."""
    import os
    import sqlite3
    import subprocess

    first = ledger.Ledger(home, str(uuid4()))
    second = ledger.Ledger(home, str(uuid4()))
    key = ("session", "route", "locked")
    first.authorize(key, str(uuid4()), 1, "b" * 64, time.time() + 120)
    path = home / "plugin-data" / ledger.PLUGIN_ID / "text-worker-ledger.sqlite3"
    real_connect = sqlite3.connect

    def short_connect(*args, **kwargs):
        return real_connect(*args, **{**kwargs, "timeout": 0.05})

    monkeypatch.setattr(ledger.sqlite3, "connect", short_connect)
    code = r"""
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=0.1, isolation_level=None)
try:
    conn.execute("BEGIN IMMEDIATE")
except sqlite3.OperationalError as error:
    if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
        sys.exit(42)
    raise
else:
    conn.execute("ROLLBACK")
finally:
    conn.close()
"""

    def external_writer():
        return subprocess.run(
            [sys.executable, "-I", "-B", "-c", code, str(path)],
            env={"HOME": str(home), "PATH": os.defpath, "LANG": "C.UTF-8"},
            cwd=home,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    with first.connection() as connection:
        # Ensure both existing main DB and rollback-journal preflight are exercised.
        connection.execute("UPDATE grants SET expires_at=expires_at+1 WHERE request_id='locked'")
        with pytest.raises(sqlite3.OperationalError):
            with second.connection():
                raise AssertionError("second same-process writer must not acquire")
        assert connection.in_transaction
        blocked = external_writer()
        assert blocked.returncode == 42, blocked.stderr
    admitted = external_writer()
    assert admitted.returncode == 0, admitted.stderr


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode", "sidecar"])
def test_ledger_refuses_unsafe_existing_files_unchanged(home, kind):
    import os

    instance = ledger.Ledger(home, str(uuid4()))
    key = ("session", "route", "private")
    instance.authorize(key, str(uuid4()), 1, "b" * 64, time.time() + 120)
    path = home / "plugin-data" / ledger.PLUGIN_ID / "text-worker-ledger.sqlite3"
    target = path
    if kind == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    elif kind == "hardlink":
        os.link(path, path.with_suffix(".alias"))
    elif kind == "mode":
        path.chmod(0o644)
    else:
        target = path.with_name(path.name + "-journal")
        target.symlink_to(home / "absent")
    before = target.lstat()
    with pytest.raises(TaskError, match="unsafe_storage_file"):
        instance.get(key)
    after = target.lstat()
    assert (after.st_ino, after.st_mode, after.st_nlink) == (
        before.st_ino,
        before.st_mode,
        before.st_nlink,
    )
