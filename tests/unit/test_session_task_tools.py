"""Activation state machine; host authenticity is covered by native contracts."""

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from personal_agent import session_task_tools as tools
from personal_agent.tasks import TaskStore


@pytest.fixture
def gate(tmp_path, monkeypatch):
    config = {"mode": "local_tasks", "local_conversation": True, "local_model_tools": True}
    binding = {"key": "route", "now": 100.0}
    opened = []
    monkeypatch.setattr(tools, "current_profile_home", lambda: tmp_path)
    monkeypatch.setattr(tools, "_bound_key", lambda: binding["key"])
    monkeypatch.setattr(tools, "_supported_origin", lambda *args: True)
    monkeypatch.setattr(tools.time, "monotonic", lambda: binding["now"])

    @contextmanager
    def turn(*args):
        yield binding["key"]

    @contextmanager
    def store(home):
        opened.append(home)
        connection = sqlite3.connect(tmp_path / "tasks.sqlite3", isolation_level=None)
        try:
            task_store = TaskStore(connection)
            task_store.initialize()
            yield task_store
        finally:
            connection.close()

    monkeypatch.setattr(tools, "native_tool_turn", turn)
    monkeypatch.setattr(tools, "open_task_store", store)
    instance = tools.SessionTaskTools(bound_home=tmp_path, read_config=config.get)

    def command(verb, sid="session", key="route", **kwargs):
        return json.loads(
            instance.command(verb, platform="local", session_id=sid, session_key=key, **kwargs)
        )

    def call(args=None, name="personal_tasks_read", sid="session"):
        return json.loads(
            instance.run(name, args or {"action": "list"}, session_id=sid, task_id="turn")
        )

    return instance, command, call, config, binding, opened


def test_activation_read_write_replay_revoke_and_unload(gate):
    instance, command, call, _, _, opened = gate
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert not opened
    assert command("enable-read")["data"]["access"] == "read"
    args = {"action": "capture", "title": "Local task", "request_id": "capture-1"}
    assert call(args, "personal_tasks_write")["error"]["code"] == "session_write_not_activated"
    assert not opened
    assert call()["data"]["items"] == []
    command("enable-write")
    captured = call(args, "personal_tasks_write")
    assert captured["status"] == "ok"
    assert call(args, "personal_tasks_write")["replayed"]
    assert len(call()["data"]["items"]) == 1
    command("disable")
    assert call()["error"]["code"] == "session_tools_not_activated"
    command("enable-write")
    instance.close()
    assert command("enable-write")["error"]["code"] == "local_model_tools_unloaded"
    assert call()["error"]["code"] == "local_model_tools_unloaded"


def test_exact_session_route_expiry_and_capacity(gate, monkeypatch):
    _, command, call, _, binding, opened = gate
    monkeypatch.setattr(tools, "MAX_ACTIVE_SESSIONS", 2)
    assert command("enable-read")["data"]["expires_in_seconds"] == 1800
    assert call(sid="other")["error"]["code"] == "session_tools_not_activated"
    binding["key"] = "other-route"
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert command("enable-write")["error"]["code"] == "unsupported_origin"
    binding["key"] = "route"
    command("enable-read", sid="second")
    assert command("enable-read", sid="third")["error"]["code"] == "activation_capacity_reached"
    assert command("enable-write")["status"] == "ok"  # Refresh existing slot.
    binding["now"] += 1800
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert command("status")["data"]["access"] == "disabled"
    assert command("enable-read", sid="third")["status"] == "ok"
    assert not opened


@pytest.mark.parametrize(
    "key,value,code",
    [
        ("mode", "read_only", "local_model_tools_disabled"),
        ("mode", "bogus", "invalid_configuration"),
        ("local_conversation", False, "local_model_tools_disabled"),
        ("local_model_tools", False, "local_model_tools_disabled"),
        ("local_model_tools", 1, "invalid_configuration"),
        ("local_conversation", "true", "invalid_configuration"),
    ],
)
def test_configuration_rechecked_before_storage(gate, key, value, code):
    _, command, call, config, _, opened = gate
    command("enable-write")
    config[key] = value
    assert call()["error"]["code"] == code
    assert command("status")["error"]["code"] == code
    assert not opened


def test_argument_and_exception_redaction_before_storage(gate, monkeypatch, capsys):
    _, command, call, _, _, opened = gate
    command("enable-write")
    result = call({"action": "list", "owner": "SECRET-ARGUMENT"})
    assert result["error"]["code"] == "invalid_request"
    assert "SECRET" not in json.dumps(result)
    assert not opened

    def unavailable(*args):
        raise RuntimeError("SECRET-STORAGE-PATH")

    monkeypatch.setattr(tools, "open_task_store", unavailable)
    result = call(
        {"action": "capture", "title": "SECRET-TITLE", "request_id": "stable"},
        "personal_tasks_write",
    )
    assert result["error"]["code"] == "local_model_tools_unavailable"
    assert result["request_id"] == "stable"
    assert "SECRET" not in json.dumps(result)
    assert capsys.readouterr() == ("", "")


def test_revoke_linearizes_after_already_admitted_work(gate, monkeypatch):
    _, command, call, _, _, _ = gate
    command("enable-read")
    admitted, release, revoke_started = threading.Event(), threading.Event(), threading.Event()
    original = tools.open_task_store

    @contextmanager
    def blocked(home):
        admitted.set()
        assert release.wait(5)
        with original(home) as store:
            yield store

    def revoke():
        revoke_started.set()
        return command("disable")

    monkeypatch.setattr(tools, "open_task_store", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(call)
        assert admitted.wait(5)
        revocation = pool.submit(revoke)
        assert revoke_started.wait(5)
        try:
            assert not revocation.done()
        finally:
            release.set()
        assert work.result(timeout=5)["status"] == "ok"
        assert revocation.result(timeout=5)["data"]["access"] == "disabled"
    assert call()["error"]["code"] == "session_tools_not_activated"
