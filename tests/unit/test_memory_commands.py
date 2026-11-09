"""Offline command and private-file boundaries; native admission is tested separately."""

import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from types import ModuleType

import pytest

from personal_agent import conversation_memory as commands
from personal_agent import memory_storage
from personal_agent.local_memory import create_backend
from personal_agent.memory_backend import MemoryError


@pytest.fixture
def local(tmp_path, monkeypatch):
    config = {"mode": "local_tasks", "local_conversation": True, "local_memory": True}
    opened = []
    binding = {"key": "route"}
    monkeypatch.setattr(commands, "current_profile_home", lambda: tmp_path)
    monkeypatch.setattr(commands, "_bound_key", lambda: binding["key"])
    monkeypatch.setattr(commands, "_supported_origin", lambda *args: True)

    @contextmanager
    def backend(home, session):
        opened.append((home, session))
        connection = sqlite3.connect(tmp_path / "memory.sqlite3", isolation_level=None)
        adapter = create_backend()
        try:
            adapter.open(connection, namespace_id="test-namespace", session_ref=session)
            yield adapter
        finally:
            adapter.close()
            connection.close()

    monkeypatch.setattr(commands, "open_memory_backend", backend)
    instance = commands.LocalMemoryCommands(bound_home=tmp_path, read_config=config.get)

    def call(text, **kwargs):
        args = {"platform": "local", "session_id": "session", "session_key": "route", **kwargs}
        return json.loads(instance.command(text, **args))

    return instance, call, config, binding, opened


def test_native_command_style_lifecycle_and_no_payload_replay(local):
    _, call, _, _, _ = local
    saved = call('remember "中文偏好: 简洁" --topic preference --request-id remember-1')
    assert saved["status"] == "ok"
    record = saved["data"]["record_id"]
    assert "简洁" not in json.dumps(saved, ensure_ascii=False)
    assert call(f"show {record}")["data"]["content"] == "中文偏好: 简洁"
    assert call('search "简洁"')["data"]["items"][0]["record_id"] == record
    corrected = call(f'correct {record} --text "繁體中文" --expected-revision 1 --request-id c1')
    assert corrected["data"]["revision"] == 2
    assert call(f"forget {record} --expected-revision 2 --request-id f1")["status"] == "ok"
    assert call("list")["data"]["items"] == []
    assert call(f"show {record}")["data"]["content"] is None
    replay = call('remember "中文偏好: 简洁" --topic preference --request-id remember-1')
    assert replay["replayed"] and replay["data"] == saved["data"]
    assert "简洁" not in json.dumps(replay, ensure_ascii=False)
    exported = call("export --limit 1")["data"]
    assert exported["items"][0]["status"] == "forgotten"
    assert exported["restorable"] is False


def test_help_and_default_generated_keys(local):
    _, call, _, _, opened = local
    assert "No automatic model recall" in call("help")["data"]["help"]
    assert not opened
    result = call('remember "Operator note"')
    assert result["request_id"] == result["data"]["request_id"]
    assert len(result["request_id"]) == 36


@pytest.mark.parametrize(
    "raw",
    [
        'remember "unterminated',
        'remember "secret" --owner owner',
        'remember "secret" --request-id=bad/key',
        'search ""',
        "list --limit 51",
        "list --limit true",
        "forget bogus --expected-revision 1",
        "correct 00000000-0000-4000-8000-000000000001 --expected-revision 1",
        'remember ""',
        'remember "' + "x" * 2049 + '"',
        "help trailing",
        "list --lim 2",
        'remember "nul\x00"',
        'remember "escape\x1b"',
        " ".join(["list"] * 41),
        "x" * 8193,
        None,
        {},
    ],
)
def test_invalid_commands_redacted_before_storage(local, raw):
    _, call, _, _, opened = local
    response = call(raw)
    assert response["status"] == "error"
    assert response["error"]["code"] == "invalid_request"
    assert response["data"] is None
    assert not opened


@pytest.mark.parametrize(
    "key,value",
    [
        ("local_memory", False),
        ("local_memory", "true"),
        ("local_memory", 1),
        ("local_conversation", False),
        ("local_conversation", 1),
        ("mode", "read_only"),
        ("mode", "bogus"),
    ],
)
def test_config_changes_rejected_before_storage(local, key, value):
    _, call, config, _, opened = local
    config[key] = value
    assert call("list")["status"] == "error"
    assert not opened


def test_unbound_origin_profile_and_unload(local, monkeypatch, tmp_path):
    instance, call, _, binding, opened = local
    assert call("list", platform="cli")["error"]["code"] == "unsupported_origin"
    binding["key"] = ""
    assert call("list")["error"]["code"] == "unsupported_origin"
    binding["key"] = "route"
    monkeypatch.setattr(commands, "current_profile_home", lambda: tmp_path / "other")
    assert call("list")["error"]["code"] == "profile_context_changed"
    instance.close()
    assert call("list")["error"]["code"] == "local_memory_unloaded"
    assert not opened


@pytest.fixture
def private_store(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    home.mkdir(mode=0o700)
    root = home / "plugin-data" / "hermes-personal-agent"
    monkeypatch.setattr(memory_storage, "current_profile_home", lambda: home)
    parent = ModuleType("plugins")
    module = ModuleType("plugins.plugin_storage")

    def data_dir(plugin_id):
        assert plugin_id == "hermes-personal-agent"
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        return root

    module.plugin_data_dir = data_dir
    monkeypatch.setitem(sys.modules, "plugins", parent)
    monkeypatch.setitem(sys.modules, "plugins.plugin_storage", module)
    return home, root / "memory" / "records.sqlite3"


def test_private_storage_and_profile_partition(private_store):
    home, path = private_store
    with memory_storage.open_memory_backend(home, "session") as backend:
        assert backend.describe()["adapter_id"] == "local_sqlite"
        assert backend.execute("list", {})["items"] == []
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
    assert not (path.parent.parent / "tasks.sqlite3").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "world_read", "sidecar", "directory"])
def test_unsafe_storage_rejected_without_repair(private_store, tmp_path, kind):
    home, path = private_store
    path.parent.mkdir(parents=True, mode=0o700)
    target = tmp_path / "sentinel"
    target.write_text("DO NOT MODIFY")
    target.chmod(0o600)
    if kind == "symlink":
        path.symlink_to(target)
    elif kind == "hardlink":
        os.link(target, path)
    elif kind == "world_read":
        path.write_text("DO NOT MODIFY")
        path.chmod(0o644)
    elif kind == "sidecar":
        path.with_name(path.name + "-journal").symlink_to(target)
    else:
        path.parent.chmod(0o777)
    with pytest.raises(MemoryError, match="unsafe_storage"):
        with memory_storage.open_memory_backend(home, "session"):
            pass
    assert target.read_text() == "DO NOT MODIFY"


def test_search_terms_command_current_content_pagination_and_expiry(local):
    _, call, _, _, _ = local
    ids = []
    for n, text in enumerate(("北京 Hermes alpha", "北京 Hermes beta", "上海 Hermes gamma")):
        ids.append(call(f'remember "{text}" --request-id terms-{n}')["data"]["record_id"])
    command = 'search-terms "北京" "Hermes" --limit 1'
    page = call(command)["data"]
    assert [item["record_id"] for item in page["items"]] == [ids[1]]
    assert page["has_more"] and page["next_cursor"] == ids[1]
    second = call(command + f" --after {page['next_cursor']}")["data"]
    assert [item["record_id"] for item in second["items"]] == [ids[0]]
    assert not second["has_more"]
    assert call('search-terms "北京" "hermes"')["data"]["items"] == []
    call(f'correct {ids[1]} --text "上海 Hermes beta" --expected-revision 1 --request-id terms-c')
    assert call(command)["data"]["items"][0]["record_id"] == ids[0]
    call(f"forget {ids[0]} --expected-revision 1 --request-id terms-f")
    assert call(command)["data"]["items"] == []
    expired = call(
        'remember "北京 Hermes expired" --expires-at 2000-01-01T00:00:00Z --request-id terms-e'
    )["data"]["record_id"]
    assert call(command)["data"]["items"] == []
    inspected = call(command + " --include-expired")["data"]["items"]
    assert len(inspected) == 1 and inspected[0]["record_id"] == expired and inspected[0]["expired"]


@pytest.mark.parametrize(
    "raw",
    [
        "search-terms",
        'search-terms ""',
        'search-terms "北京" "北京"',
        "search-terms " + " ".join(f"term{i}" for i in range(9)),
        'search-terms "' + "x" * 129 + '"',
        "search-terms 北京 --limit 51",
        "search-terms 北京 --after fake",
        "search-terms 北京 --profile other",
        "search-terms 北京 --query 北京",
    ],
)
def test_search_terms_command_invalid_before_storage(local, raw):
    _, call, _, _, opened = local
    result = call(raw)
    assert result["error"]["code"] == "invalid_request"
    assert not opened
