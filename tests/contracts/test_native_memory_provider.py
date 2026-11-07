"""Actual Hermes loader/manager lifecycle with synthetic profiles; no agent or listener."""

import json
import tomllib
from contextlib import contextmanager
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
import test_native_plugin

from personal_agent.memory_storage import open_memory_backend
from personal_agent.native_memory_provider import PersonalRecordsProvider

home = test_native_plugin.home
manager = test_native_plugin.manager


def configuration():
    return {
        "memory": {"provider": "personal-records", "personal_records": {"recall_enabled": True}},
        "plugins": {
            "enabled": ["hermes-personal-agent"],
            "entries": {
                "hermes-personal-agent": {
                    "settings": {
                        "mode": "local_tasks",
                        "local_conversation": True,
                        "local_memory": True,
                    }
                }
            },
        },
    }


@contextmanager
def scoped(home):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override

    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)


@pytest.fixture
def native_recall(home, manager, monkeypatch):  # noqa: F811
    from agent.memory_manager import MemoryManager
    from plugins import memory

    config = configuration()
    (home / "config.yaml").write_text(json.dumps(config))
    project = tomllib.loads(
        (Path(__file__).parents[2] / "packaging/native-memory-provider.toml").read_text()
    )
    value = project["project"]["entry-points"]["hermes_agent.memory_providers"]["personal-records"]
    entry = EntryPoint(name="personal-records", value=value, group="hermes_agent.memory_providers")
    monkeypatch.setattr(memory, "_iter_entry_points", lambda: [entry])
    with scoped(home):
        first = memory.load_memory_provider("personal-records", register_skills=False)
        second = memory.load_memory_provider("personal-records", register_skills=False)
        assert isinstance(first, PersonalRecordsProvider) and first is not second
        assert first.is_available()
        native_manager = MemoryManager()
        native_manager.add_provider(first)
        native_manager.initialize_all(
            session_id="session-one", hermes_home=str(home), platform="cli", agent_context="primary"
        )
        try:
            yield home, first, native_manager, config
        finally:
            native_manager.shutdown_all()
            second.shutdown()


def save(home, content="早餐豆浆"):
    with open_memory_backend(home, "operator") as backend:
        return backend.execute("remember", {"content": content, "request_id": "r"})["data"][
            "record_id"
        ]


def test_loader_and_lifecycle_read_fresh_records_without_writing(native_recall):
    home, provider, native_manager, _ = native_recall
    before_config = (home / "config.yaml").read_bytes()
    assert not (home / "plugin-data").exists()
    assert native_manager.prefetch_all("早餐", session_id="session-one") == ""
    assert not (home / "plugin-data").exists()
    rid = save(home)
    db = home / "plugin-data/hermes-personal-agent/memory/records.sqlite3"
    before_db = db.read_bytes()
    pack = json.loads(native_manager.prefetch_all("早餐?", session_id="session-one"))
    assert pack["memory"]["items"][0]["record_id"] == rid
    assert "recalled 1 memory" in native_manager.describe_recall()
    native_manager.sync_all(
        "new private user text",
        "new private assistant text",
        session_id="session-one",
        messages=[{"role": "user", "content": "private"}],
    )
    native_manager.on_session_end([{"role": "user", "content": "private"}])
    native_manager.on_memory_write("add", "memory", "private host memory")
    native_manager.queue_prefetch_all("早餐", session_id="session-one")
    native_manager.shutdown_all()
    assert db.read_bytes() == before_db
    assert native_manager.prefetch_all("早餐", session_id="session-one") == ""
    assert provider.recall_status() is None
    assert (home / "config.yaml").read_bytes() == before_config


def test_actual_manager_preserves_required_checkpoint_failure(native_recall):
    home, _, native_manager, _ = native_recall
    save(home)
    assert not native_manager.supports_pre_compress_checkpoint()
    assert native_manager.on_pre_compress([{"role": "user", "content": "private"}]) == ""
    with pytest.raises(RuntimeError, match="No active memory provider completed"):
        native_manager.on_pre_compress(
            [], evidence_messages=[{"role": "user", "content": "private"}], require_checkpoint=True
        )


def test_native_session_switch_revoke_and_forget_do_not_return_stale_pack(native_recall):
    home, provider, native_manager, config = native_recall
    rid = save(home)
    assert native_manager.prefetch_all("早餐", session_id="session-one")
    native_manager.on_session_switch("session-two", reset=True)
    assert native_manager.prefetch_all("早餐", session_id="session-one") == ""
    assert provider.recall_status() is None
    assert native_manager.prefetch_all("早餐", session_id="session-two")
    with open_memory_backend(home, "operator") as backend:
        backend.execute("forget", {"record_id": rid, "expected_revision": 1, "request_id": "f"})
    assert native_manager.prefetch_all("早餐", session_id="session-two") == ""
    config["memory"]["personal_records"]["recall_enabled"] = False
    (home / "config.yaml").write_text(json.dumps(config))
    assert not provider.is_available()
    assert native_manager.prefetch_all("早餐", session_id="session-two") == ""
    assert provider.recall_status() is None


def test_native_manager_refuses_second_external_provider(native_recall):
    _, provider, native_manager, _ = native_recall
    second = PersonalRecordsProvider()
    native_manager.add_provider(second)
    assert native_manager.providers == [provider]


@pytest.mark.parametrize(
    "context,platform",
    [("cron", "cli"), ("subagent", "cli"), ("primary", "telegram"), (None, "cli")],
)
def test_native_manager_nonprimary_and_remote_contexts_never_open_store(home, context, platform):  # noqa: F811
    from agent.memory_manager import MemoryManager

    (home / "config.yaml").write_text(json.dumps(configuration()))
    with scoped(home):
        provider = PersonalRecordsProvider()
        native_manager = MemoryManager()
        native_manager.add_provider(provider)
        native_manager.initialize_all(
            session_id="session", hermes_home=str(home), platform=platform, agent_context=context
        )
        assert native_manager.prefetch_all("private", session_id="session") == ""
        native_manager.shutdown_all()
    assert not (home / "plugin-data").exists()


def test_native_profile_switch_cannot_read_other_home(native_recall, tmp_path):
    home, provider, native_manager, _ = native_recall
    save(home)
    second = tmp_path / "other"
    second.mkdir(mode=0o700)
    (second / "config.yaml").write_text(json.dumps(configuration()))
    with scoped(second):
        assert native_manager.prefetch_all("早餐", session_id="session-one") == ""
        assert provider.prefetch("早餐", session_id="session-one") == ""
        assert provider.recall_status() is None
    assert not (second / "plugin-data").exists()


def test_native_trivial_prompt_clears_indicator(native_recall):
    home, provider, native_manager, _ = native_recall
    save(home)
    assert native_manager.prefetch_all("早餐", session_id="session-one")
    assert native_manager.prefetch_all("thanks", session_id="session-one") == ""
    assert provider.recall_status() is None


def test_live_native_plugin_disable_stops_new_recall(native_recall):
    home, provider, native_manager, config = native_recall
    save(home)
    assert native_manager.prefetch_all("早餐", session_id="session-one")
    config["plugins"]["disabled"] = ["personal-records"]
    (home / "config.yaml").write_text(json.dumps(config))
    assert native_manager.prefetch_all("早餐", session_id="session-one") == ""
    assert provider.recall_status() is None
