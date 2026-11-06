"""Independent memory activation and store behavior; real host contracts are separate."""

import json
import sqlite3
from contextlib import contextmanager

import pytest

from personal_agent import session_memory_tools as memory
from personal_agent import session_task_tools as gates
from personal_agent.local_memory import create_backend


@pytest.fixture
def access(tmp_path, monkeypatch):
    config = {
        "mode": "local_tasks",
        "local_conversation": True,
        "local_memory": True,
        "memory_model_tools": True,
        "local_model_tools": False,
    }
    binding = {"key": "route", "now": 100.0}
    opened = []
    monkeypatch.setattr(memory, "current_profile_home", lambda: tmp_path)
    monkeypatch.setattr(gates, "current_profile_home", lambda: tmp_path)
    monkeypatch.setattr(gates, "_bound_key", lambda: binding["key"])
    monkeypatch.setattr(gates, "_supported_origin", lambda *args: True)
    monkeypatch.setattr(gates.time, "monotonic", lambda: binding["now"])

    @contextmanager
    def turn(*args):
        yield binding["key"]

    @contextmanager
    def backend(home, session, *, source_kind):
        opened.append((home, session, source_kind))
        connection = sqlite3.connect(tmp_path / "memory.sqlite3", isolation_level=None)
        adapter = create_backend()
        try:
            adapter.open(
                connection,
                namespace_id="test-namespace",
                session_ref=session,
                source_kind=source_kind,
            )
            yield adapter
        finally:
            adapter.close()
            connection.close()

    monkeypatch.setattr(gates, "native_tool_turn", turn)
    monkeypatch.setattr(memory, "open_memory_backend", backend)
    instance = memory.SessionMemoryTools(bound_home=tmp_path, read_config=config.get)

    def command(verb, sid="session", key="route"):
        return json.loads(instance.command(verb, platform="local", session_id=sid, session_key=key))

    def call(arguments=None, *, write=False, sid="session", name=None):
        return json.loads(
            instance.run(
                name or ("personal_memory_write" if write else "personal_memory_read"),
                arguments or {"action": "list"},
                session_id=sid,
                task_id="turn",
            )
        )

    return instance, command, call, config, binding, opened


def test_activation_and_model_edit_provenance_and_forgotten_receipt(access):
    _, command, call, _, _, opened = access
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert command("enable-read")["data"]["access"] == "read"
    payload = {"action": "remember", "content": "中文偏好", "request_id": "remember-1"}
    assert call(payload, write=True)["error"]["code"] == "session_write_not_activated"
    assert not opened
    command("enable-write")
    saved = call(payload, write=True)
    record_id = saved["data"]["record_id"]
    row = call({"action": "show", "record_id": record_id})["data"]
    assert row["source"] == "activated_session_model"
    assert "explicit_local_operator" not in json.dumps(row)
    forgotten = call(
        {"action": "forget", "record_id": record_id, "expected_revision": 1, "request_id": "f1"},
        write=True,
    )
    assert forgotten["status"] == "ok"
    replay = call(payload, write=True)
    assert replay["replayed"] and replay["data"] == saved["data"]
    assert "中文偏好" not in json.dumps(replay, ensure_ascii=False)
    assert call()["data"]["items"] == []
    command("disable")
    assert call()["error"]["code"] == "session_tools_not_activated"


def test_read_downgrade_expiry_session_route_capacity_and_unload(access, monkeypatch):
    instance, command, call, _, binding, opened = access
    monkeypatch.setattr(gates, "MAX_ACTIVE_SESSIONS", 2)
    assert "Memory and task activations are independent" in command("help")["data"]["help"]
    assert not opened
    command("enable-write")
    command("enable-read")
    assert command("status")["data"]["access"] == "read"
    assert call(sid="other")["error"]["code"] == "session_tools_not_activated"
    binding["key"] = "other-route"
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert command("enable-read")["error"]["code"] == "unsupported_origin"
    binding["key"] = "route"
    command("enable-read", sid="other")
    assert command("enable-read", sid="third")["error"]["code"] == "activation_capacity_reached"
    binding["now"] += 1800
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert command("status")["data"]["access"] == "disabled"
    command("enable-read")
    instance.close()
    assert call()["error"]["code"] == "memory_model_tools_unloaded"
    assert command("enable-write")["error"]["code"] == "memory_model_tools_unloaded"
    assert not opened


@pytest.mark.parametrize(
    "key,value",
    [
        ("mode", "read_only"),
        ("mode", "bogus"),
        ("local_memory", False),
        ("local_memory", 1),
        ("local_conversation", False),
        ("memory_model_tools", False),
        ("memory_model_tools", "true"),
    ],
)
def test_configuration_rejection_clears_activation(access, key, value):
    _, command, call, config, _, opened = access
    original = config[key]
    command("enable-write")
    config[key] = value
    assert call()["status"] == "error"
    config[key] = original
    assert call()["error"]["code"] == "session_tools_not_activated"
    assert not opened


def test_unknown_fields_export_and_cross_feature_tool_names_rejected(access):
    _, command, call, _, _, opened = access
    command("enable-write")
    for payload in (
        {"action": "export"},
        {"action": "list", "owner": "forged"},
        {"action": "remember", "content": "secret"},
        {"action": "remember", "content": "secret", "request_id": "x", "source": "owner"},
    ):
        assert (
            call(payload, write=payload["action"] == "remember")["error"]["code"]
            == "invalid_request"
        )
    assert call({"action": "capture"}, name="personal_tasks_write")["status"] == "error"
    assert not opened


def test_task_configuration_and_memory_state_are_independent(access, tmp_path):
    _, command, call, config, _, _ = access
    tasks = gates.SessionTaskTools(bound_home=tmp_path, read_config=config.get)
    command("enable-read")
    assert call()["status"] == "ok"
    assert (
        json.loads(
            tasks.command(
                "enable-read", platform="local", session_id="session", session_key="route"
            )
        )["error"]["code"]
        == "local_model_tools_disabled"
    )
    config["local_model_tools"] = True
    task_status = json.loads(
        tasks.command("status", platform="local", session_id="session", session_key="route")
    )
    assert task_status["data"]["access"] == "disabled"


def test_storage_error_retains_validated_request_id(access):
    _, command, call, _, _, _ = access
    command("enable-write")
    call({"action": "remember", "content": "one", "request_id": "key"}, write=True)
    failed = call({"action": "remember", "content": "two", "request_id": "key"}, write=True)
    assert failed["error"]["code"] == "idempotency_conflict"
    assert failed["request_id"] == "key"
