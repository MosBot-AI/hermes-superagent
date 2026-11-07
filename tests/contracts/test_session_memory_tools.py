"""Actual pinned native activation, turn lifecycle and model-tool dispatch, offline.

The runtime coordinator and session authority are real; no model, credentials,
network transport, listener or managed worker is started. No identity is inferred
from a model argument. Authorized controllers share the activated session.
"""

import asyncio
import json
from contextlib import contextmanager
from dataclasses import replace

import pytest
import test_local_conversation_tasks as local
import test_local_memory_commands as memory
import test_session_task_tools as task_tools
from test_local_task_cli import PLUGIN_ID

native = local.native


@pytest.fixture
def host(native, monkeypatch):
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"].update(
        local_memory=True, memory_model_tools=True, local_model_tools=True
    )
    (home / "config.yaml").write_text(json.dumps(config))

    def load(manager):
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.enabled and loaded.error is None
        assert set(loaded.tools_registered) == {
            "personal_agent_status",
            "personal_memory_read",
            "personal_memory_write",
            "personal_tasks_read",
            "personal_tasks_write",
        }
        assert "personal-memory-tools" in manager._plugin_commands

    monkeypatch.setattr(local, "load", load)
    return local.make_host(home, manager)


def activate(host, verb="enable-write"):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-memory-tools " + verb})
    )
    return json.loads(result["output"])


@contextmanager
def turn(host, *, sid=None, platform="cli", parent="", key=None, profile=None, coordinator=None):
    from agent import relay_runtime
    from gateway.session_context import scoped_session_key

    # Real coordinator lifecycle with its supported no-instrumentation runtime.
    # No Relay plugin or external telemetry host is initialized by this fixture.
    registry = relay_runtime.RelayHostRegistry()
    registry.for_profile = lambda *args, **kwargs: None
    coordinator = coordinator or relay_runtime.RelaySessionCoordinator(registry)
    session_id = sid or host.ref.session_id
    lease = coordinator.acquire_conversation(
        profile_key=profile or str(host.home),
        session_id=session_id,
        platform=platform,
        parent_session_id=parent,
    )
    with scoped_session_key(host.live.route if key is None else key):
        context = coordinator.begin_turn(lease, turn_id="native-turn", task_id="native-task")
        try:
            yield context
        finally:
            coordinator.end_turn(context, outcome="success")
            coordinator.release_conversation(lease)


def call(host, args=None, *, write=False, sid=None, task_id="native-task"):
    from model_tools import handle_function_call

    return json.loads(
        handle_function_call(
            "personal_memory_write" if write else "personal_memory_read",
            args or {"action": "list"},
            task_id=task_id,
            session_id=sid or host.ref.session_id,
        )
    )


def test_native_slash_activation_to_real_model_dispatch_lifecycle(host):
    from agent.relay_runtime import active_turn

    assert activate(host, "enable-read")["data"]["access"] == "read"
    args = {
        "action": "remember",
        "content": "Prefer jasmine tea",
        "topic": "tastes",
        "request_id": "native-remember",
    }
    with turn(host):
        assert active_turn(host.ref.session_id) is not None
        assert call(host, args, write=True)["error"]["code"] == "session_write_not_activated"
    assert not memory.database(host.home).exists()
    assert activate(host)["data"]["access"] == "write"
    with turn(host):
        added = call(host, args, write=True)
        assert added["status"] == "ok", added
        assert added["schema_version"] == "personal.session-memory-tools.v1"
        assert added["scope"] == "activated_trusted_local_session"
        record = added["data"]
        rid = record["record_id"]
        assert "content" not in record
        replay = call(host, args, write=True)
        assert replay["replayed"] and replay["data"] == record
        assert call(host, {**args, "content": "Different"}, write=True)["error"]["code"] == (
            "idempotency_conflict"
        )
        assert call(host)["data"]["items"][0]["record_id"] == rid
        assert call(host, {"action": "search", "query": "jasmine"})["data"]["items"]
        shown = call(host, {"action": "show", "record_id": rid})["data"]
        assert shown["source"] == "activated_session_model"
        assert shown["content"] == "Prefer jasmine tea"
        update = {
            "action": "correct",
            "record_id": rid,
            "expected_revision": 1,
            "content": "Prefer green tea",
            "request_id": "native-correct",
        }
        assert call(host, update, write=True)["data"]["revision"] == 2
        assert call(host, update, write=True)["replayed"]
        forget = {
            "action": "forget",
            "record_id": rid,
            "expected_revision": 1,
            "request_id": "native-forget",
        }
        assert call(host, forget, write=True)["error"]["code"] == "revision_conflict"
        forget["expected_revision"] = 2
        assert call(host, forget, write=True)["status"] == "ok"
        assert call(host, forget, write=True)["replayed"]
        assert call(host)["data"]["items"] == []
        assert call(host, {"action": "search", "query": "green"})["data"]["items"] == []
        tombstone = call(host, {"action": "show", "record_id": rid})["data"]
        assert tombstone["status"] == "forgotten"
        assert all(tombstone[k] is None for k in ("content", "topic", "source", "session_ref"))
    assert active_turn(host.ref.session_id) is None
    assert call(host)["error"]["code"] == "no_active_local_turn"
    assert activate(host, "disable")["data"]["access"] == "disabled"
    with turn(host):
        assert call(host)["error"]["code"] == "session_tools_not_activated"
    assert not local.database(host.home).exists()


@pytest.mark.parametrize(
    "change,code",
    [
        ({"platform": "telegram"}, "no_active_local_turn"),
        ({"platform": "subagent"}, "no_active_local_turn"),
        ({"parent": "parent-session"}, "no_active_local_turn"),
        ({"key": ""}, "no_active_local_turn"),
        ({"key": "another-route"}, "session_tools_not_activated"),
        ({"sid": "another-session"}, "session_tools_not_activated"),
        ({"profile": "/synthetic/foreign"}, "no_active_local_turn"),
    ],
)
@pytest.mark.parametrize("read_args", [{"action": "list"}, {"action": "recall", "queries": ["茶"]}])
def test_real_turn_wrong_scope_never_opens_storage(host, change, code, read_args):
    activate(host)
    with turn(host, **change):
        result = call(host, read_args, sid=change.get("sid"))
    assert result["error"]["code"] == code, result
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("platform", ["cli", "tui", "desktop"])
def test_supported_native_platforms_share_session_activation(host, platform):
    activate(host, "enable-read")
    with turn(host, platform=platform):
        assert call(host)["status"] == "ok"


def test_native_wrong_task_and_env_only_context_fail_closed(host, monkeypatch):
    activate(host)
    monkeypatch.setenv("HERMES_SESSION_KEY", host.live.route)
    monkeypatch.setenv("HERMES_SESSION_ID", host.ref.session_id)
    assert call(host)["error"]["code"] == "no_active_local_turn"
    with turn(host):
        assert call(host, task_id="wrong-turn")["error"]["code"] == "no_active_local_turn"
    with turn(host, key=""):
        assert call(host)["error"]["code"] == "no_active_local_turn"
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("failure", ["wrong_owner", "no_control", "retiring", "stale_source"])
def test_native_authority_denies_activation_before_storage(host, failure):
    from hermes_state_runtime import RuntimeStoreError

    if failure == "wrong_owner":
        host.connection.actor = replace(host.connection.actor, subject="someone-else")
    elif failure == "no_control":
        host.connection.actor = replace(
            host.connection.actor, capabilities=frozenset({"session:read"})
        )
    elif failure == "retiring":
        host.authority.retiring = True
    else:
        host.live.source = replace(host.source)
    with pytest.raises(RuntimeStoreError):
        activate(host)
    with turn(host):
        assert call(host)["error"]["code"] == "session_tools_not_activated"
    assert not memory.database(host.home).exists()


def test_native_reload_discards_activation_and_unload_closes_retained_callbacks(host):
    from gateway.session_context import scoped_session_key
    from tools.registry import registry

    activate(host)
    retained = registry.get_entry("personal_memory_read").handler
    command = host.manager._plugin_commands["personal-memory-tools"]["handler"]
    host.manager.discover_and_load(force=True)
    with turn(host):
        assert call(host)["error"]["code"] == "session_tools_not_activated"
        assert (
            json.loads(
                retained({"action": "list"}, session_id=host.ref.session_id, task_id="native-task")
            )["error"]["code"]
            == "memory_model_tools_unloaded"
        )
    host.manager.unload()
    with scoped_session_key(host.live.route):
        result = json.loads(
            command(
                "enable-write",
                platform="local",
                source=host.source,
                session_id=host.ref.session_id,
                session_key=host.live.route,
            )
        )
    assert result["error"]["code"] == "memory_model_tools_unloaded"
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("read_args", [{"action": "list"}, {"action": "recall", "queries": ["茶"]}])
def test_native_delegated_and_cron_context_denied(host, read_args):
    from agent.delegation_context import delegated_child_context
    from gateway.session_context import clear_session_vars, set_session_vars

    activate(host)
    with turn(host), delegated_child_context():
        assert call(host, read_args)["error"]["code"] == "no_active_local_turn"
    tokens = set_session_vars(cron_session="1")
    try:
        with turn(host):
            assert call(host, read_args)["error"]["code"] == "no_active_local_turn"
    finally:
        clear_session_vars(tokens)
    assert not memory.database(host.home).exists()


def test_admitted_operator_can_activate_same_session_without_owner_claim(host):
    actor = host.connection.actor
    host.connection.actor = replace(
        actor, subject="another-operator", capabilities=actor.capabilities | {"session:operator"}
    )
    assert activate(host, "enable-read")["status"] == "ok"
    with turn(host):
        assert call(host)["status"] == "ok"


@pytest.mark.parametrize("read_args", [{"action": "list"}, {"action": "recall", "queries": ["茶"]}])
def test_finalized_context_and_uncopied_worker_have_no_admission(host, read_args):
    from concurrent.futures import ThreadPoolExecutor

    from agent import relay_runtime

    activate(host)
    with turn(host) as context:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(call, host, read_args).result(timeout=5)
        assert result["error"]["code"] == "no_active_local_turn"
        relay_runtime.SESSION_COORDINATOR.end_turn(context, outcome="success")
        assert call(host, read_args)["error"]["code"] == "no_active_local_turn"
    assert not memory.database(host.home).exists()


def test_real_turn_facade_dispatches_tools_and_finalizes_on_exception(host, monkeypatch):
    from agent import conversation_loop, relay_runtime
    from agent.turn_facade import TurnFacadeMixin
    from gateway.session_context import scoped_session_key

    class OfflineAgent(TurnFacadeMixin):
        session_id = host.ref.session_id
        platform = "cli"
        model = "offline-no-provider"

        def _conversation_root_id(self):
            return self.session_id

    # Replace only provider/conversation generation and optional telemetry host.
    # Actual turn admission, ContextVar binding, finalization and dispatcher run.
    registry = relay_runtime.RelayHostRegistry()
    monkeypatch.setattr(registry, "for_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        relay_runtime, "SESSION_COORDINATOR", relay_runtime.RelaySessionCoordinator(registry)
    )
    seen = []

    def offline_loop(agent, message, system, history, task_id, *args, **kwargs):
        seen.append(relay_runtime.active_turn(agent.session_id))
        assert seen[-1] is not None
        result = call(host, task_id=task_id)
        assert result["status"] == "ok", result
        if message == "fail":
            raise RuntimeError("synthetic provider failure")
        return {"final_response": "offline complete"}

    monkeypatch.setattr(conversation_loop, "run_conversation", offline_loop)
    activate(host, "enable-read")
    with scoped_session_key(host.live.route):
        agent = OfflineAgent()
        assert agent.run_conversation("read", task_id="native-task")["final_response"]
        assert relay_runtime.active_turn(host.ref.session_id) is None
        assert seen[-1].closed and seen[-1].lease.released
        with pytest.raises(RuntimeError, match="synthetic provider failure"):
            agent.run_conversation("fail", task_id="native-task")
        assert relay_runtime.active_turn(host.ref.session_id) is None
        assert seen[-1].closed and seen[-1].lease.released
        assert call(host)["error"]["code"] == "no_active_local_turn"


@pytest.mark.parametrize("read_args", [{"action": "list"}, {"action": "recall", "queries": ["茶"]}])
def test_actual_finalization_lock_waits_for_admitted_storage_then_fences_copied_context(
    host, monkeypatch, read_args
):
    import importlib
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    from agent import relay_runtime

    module = host.manager._plugins[PLUGIN_ID].module
    memory_backend = importlib.import_module(module.__name__ + ".personal_agent.memory_backend")
    original_run = memory_backend.MemoryService.execute
    admitted = threading.Event()
    release = threading.Event()
    finalizing = threading.Event()
    store_calls = []

    def blocked_run(store, operation, payload):
        store_calls.append(operation)
        admitted.set()
        assert release.wait(5)
        return original_run(store, operation, payload)

    monkeypatch.setattr(memory_backend.MemoryService, "execute", blocked_run)
    registry = relay_runtime.RelayHostRegistry()
    monkeypatch.setattr(registry, "for_profile", lambda *args, **kwargs: None)
    coordinator = relay_runtime.RelaySessionCoordinator(registry)
    activate(host)
    with turn(host, coordinator=coordinator) as context:
        worker_context, stale_context = copy_context(), copy_context()

        def finalize():
            finalizing.set()
            # This is the actual host method, using the same lock as admission.
            coordinator.end_turn(context, outcome="success")

        with ThreadPoolExecutor(max_workers=2) as pool:
            work = pool.submit(worker_context.run, call, host, read_args)
            try:
                assert admitted.wait(5)
                # The store is running in another thread. Prove it owns the real
                # lock, not merely that the finalizer has not been scheduled yet.
                unexpectedly_acquired = context.finalize_lock.acquire(blocking=False)
                if unexpectedly_acquired:
                    context.finalize_lock.release()
                assert not unexpectedly_acquired
                finished = pool.submit(finalize)
                assert finalizing.wait(5)
                assert not finished.done()
                assert not context.closed
            finally:
                release.set()
            assert work.result(timeout=5)["status"] == "ok"
            finished.result(timeout=5)
        assert context.closed
        assert stale_context.run(call, host, read_args)["error"]["code"] == "no_active_local_turn"
        assert call(host, read_args)["error"]["code"] == "no_active_local_turn"
        assert store_calls == [read_args["action"]]


@pytest.mark.parametrize(
    "settings,valid",
    [
        ({}, True),
        ({"memory_model_tools": False}, True),
        ({"local_memory": False}, True),
        ({"memory_model_tools": True, "local_memory": False}, False),
        ({"memory_model_tools": True, "local_conversation": False}, False),
        ({"memory_model_tools": True, "mode": "read_only"}, False),
        ({"memory_model_tools": "true"}, False),
        ({"memory_model_tools": 1}, False),
        ({"memory_model_tools": None}, False),
        ({"memory_model_tools": []}, False),
    ],
)
def test_default_and_invalid_memory_tool_config_never_registers(native, settings, valid):
    home, manager = native
    memory.configure(home, **settings)
    manager.discover_and_load()
    plugin = manager._plugins[PLUGIN_ID]
    assert (plugin.error is None) is valid
    assert "personal-memory-tools" not in manager._plugin_commands
    assert not {"personal_memory_read", "personal_memory_write"}.intersection(
        plugin.tools_registered
    )
    assert not memory.database(home).exists()


def test_task_and_memory_session_activations_are_independent(host):
    task_tools.activate(host)
    with turn(host):
        assert task_tools.call(host)["status"] == "ok"
        assert call(host)["error"]["code"] == "session_tools_not_activated"
    task_tools.activate(host, "disable")
    activate(host)
    with turn(host):
        assert call(host)["status"] == "ok"
        assert task_tools.call(host)["error"]["code"] == "session_tools_not_activated"
    task_tools.activate(host)
    activate(host, "disable")
    with turn(host):
        assert task_tools.call(host)["status"] == "ok"
        assert call(host)["error"]["code"] == "session_tools_not_activated"


def test_memory_model_tools_register_without_task_model_tools(native, monkeypatch):
    home, manager = native
    memory.configure(home, memory_model_tools=True, local_model_tools=False)
    manager.discover_and_load()
    loaded = manager._plugins[PLUGIN_ID]
    assert loaded.error is None
    assert set(loaded.tools_registered) == {
        "personal_agent_status",
        "personal_memory_read",
        "personal_memory_write",
    }
    assert "personal-memory-tools" in manager._plugin_commands
    assert "personal-tools" not in manager._plugin_commands
    assert not memory.database(home).exists()


@pytest.mark.parametrize("read_args", [{"action": "list"}, {"action": "recall", "queries": ["茶"]}])
def test_disable_config_clears_activation_before_storage(host, read_args):
    activate(host)
    memory.configure(host.home, memory_model_tools=False, local_model_tools=True)
    with turn(host):
        assert call(host, read_args)["error"]["code"] == "memory_model_tools_disabled"
    memory.configure(host.home, memory_model_tools=True, local_model_tools=True)
    with turn(host):
        assert call(host, read_args)["error"]["code"] == "session_tools_not_activated"
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize(
    "args,write",
    [
        ({"action": "export"}, False),
        ({"action": "get", "record_id": "synthetic"}, False),
        ({"action": "list", "owner": "synthetic"}, False),
        ({"action": "list", "limit": 51}, False),
        ({"action": "remember", "content": "synthetic"}, True),
        (
            {
                "action": "remember",
                "content": "synthetic",
                "request_id": "id",
                "source": "explicit_local_operator",
            },
            True,
        ),
    ],
)
def test_model_arguments_cannot_export_or_claim_provenance(host, args, write):
    activate(host)
    with turn(host):
        result = call(host, args, write=write)
    assert result["status"] == "error", result
    assert not memory.database(host.home).exists()


@pytest.mark.parametrize("read_args", [{"action": "list"}, {"action": "recall", "queries": ["茶"]}])
def test_activation_ttl_status_and_read_downgrade(host, monkeypatch, read_args):
    import importlib

    module = host.manager._plugins[PLUGIN_ID].module
    session_tools = importlib.import_module(module.__name__ + ".personal_agent.session_task_tools")
    clock = [1000.0]
    monkeypatch.setattr(session_tools.time, "monotonic", lambda: clock[0])
    assert activate(host)["data"]["expires_in_seconds"] == 1800
    clock[0] += 1799
    assert activate(host, "status")["data"]["expires_in_seconds"] == 1
    clock[0] += 1
    assert activate(host, "status")["data"]["access"] == "disabled"
    with turn(host):
        assert call(host, read_args)["error"]["code"] == "session_tools_not_activated"
    activate(host)
    assert activate(host, "enable-read")["data"]["access"] == "read"
    with turn(host):
        result = call(
            host, {"action": "remember", "content": "Blocked", "request_id": "blocked"}, write=True
        )
        assert result["error"]["code"] == "session_write_not_activated"
    assert not memory.database(host.home).exists()


def test_registered_memory_schemas_exclude_export_and_identity(host):
    from tools.registry import registry

    for name, actions in (
        ("personal_memory_read", {"list", "show", "search", "recall"}),
        ("personal_memory_write", {"remember", "correct", "forget"}),
    ):
        schema = registry.get_entry(name).schema
        parameters = schema.get("function", schema)["parameters"]
        assert set(parameters["properties"]["action"]["enum"]) == actions
        assert parameters["additionalProperties"] is False
        assert not {"owner", "source", "session_id", "profile", "approved"}.intersection(
            parameters["properties"]
        )
    assert not memory.database(host.home).exists()


def test_loading_help_and_status_preserve_native_configuration(host):
    before = (host.home / "config.yaml").read_bytes()
    native_memory = host.home / "memories"
    native_memory.mkdir(exist_ok=True)
    source = native_memory / "MEMORY.md"
    source.write_text("Synthetic native provider memory remains separate")
    assert activate(host, "help")["status"] == "ok"
    assert activate(host, "status")["data"]["access"] == "disabled"
    assert (host.home / "config.yaml").read_bytes() == before
    assert source.read_text() == "Synthetic native provider memory remains separate"
    assert not memory.database(host.home).exists()
    loaded = host.manager._plugins[PLUGIN_ID]
    assert not loaded.hooks_registered and not loaded.middleware_registered


def test_unbound_activation_cannot_be_granted_by_copied_source(host):
    callback = host.manager._plugin_commands["personal-memory-tools"]["handler"]
    result = json.loads(
        callback(
            "enable-write",
            platform="local",
            source=host.source,
            session_id=host.ref.session_id,
            session_key=host.live.route,
        )
    )
    assert result["error"]["code"] == "unsupported_origin"
    with turn(host):
        assert call(host)["error"]["code"] == "session_tools_not_activated"
    assert not memory.database(host.home).exists()


def test_native_bounded_recall_obeys_separate_activation_and_current_revisions(host):
    from tools.registry import registry

    args = {"action": "recall", "queries": ["早餐", "燕麦奶"], "limit": 2, "max_chars": 2000}
    # Task activation cannot admit the memory recall action.
    assert task_tools.activate(host, "enable-read")["data"]["access"] == "read"
    with turn(host):
        assert call(host, args)["error"]["code"] == "session_tools_not_activated"
    assert not memory.database(host.home).exists()
    activate(host)
    with turn(host):
        saved = call(
            host,
            {
                "action": "remember",
                "content": "早餐豆浆",
                "topic": "早餐",
                "request_id": "recall-save",
            },
            write=True,
        )
        rid = saved["data"]["record_id"]
        data = call(host, args)["data"]
        assert data["items"][0]["record_id"] == rid
        assert data["items"][0]["source"] == "activated_session_model"
        assert data["items_json_chars"] <= 2000
        assert data["watermark"] == 1
        updated = call(
            host,
            {
                "action": "correct",
                "record_id": rid,
                "expected_revision": 1,
                "content": "早餐燕麦奶",
                "request_id": "recall-correct",
            },
            write=True,
        )
        assert updated["data"]["revision"] == 2
        current = call(host, args)["data"]
        assert current["items"][0]["matched_queries"] == [0, 1]
        assert current["items"][0]["content"] == "早餐燕麦奶"
        assert current["watermark"] == 2
    activate(host, "enable-read")
    with turn(host):
        assert call(host, args)["data"] == current
        assert (
            call(host, {"action": "recall", "queries": ["早餐"], "after": rid})["error"]["code"]
            == "invalid_request"
        )
        assert call(host, args, write=True)["error"]["code"] == "session_write_not_activated"
    retained = registry.get_entry("personal_memory_read").handler
    activate(host, "disable")
    with turn(host):
        assert call(host, args)["error"]["code"] == "session_tools_not_activated"
    host.manager.unload()
    with turn(host):
        denied = json.loads(retained(args, session_id=host.ref.session_id, task_id="native-task"))
        assert denied["error"]["code"] == "memory_model_tools_unloaded"
