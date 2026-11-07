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
from test_local_conversation_tasks import native  # noqa: F401
from test_local_task_cli import PLUGIN_ID


@pytest.fixture
def host(native, monkeypatch):  # noqa: F811
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["local_model_tools"] = True
    (home / "config.yaml").write_text(json.dumps(config))

    def load(manager):
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.enabled and loaded.error is None
        assert set(loaded.tools_registered) == {
            "personal_agent_status",
            "personal_tasks_read",
            "personal_tasks_write",
        }
        assert "personal-tools" in manager._plugin_commands

    monkeypatch.setattr(local, "load", load)
    return local.make_host(home, manager)


def activate(host, verb="enable-write"):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-tools " + verb})
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
            "personal_tasks_write" if write else "personal_tasks_read",
            args or {"action": "list"},
            task_id=task_id,
            session_id=sid or host.ref.session_id,
        )
    )


def test_native_slash_activation_to_real_model_dispatch_lifecycle(host):
    from agent.relay_runtime import active_turn

    assert activate(host, "enable-read")["data"]["access"] == "read"
    args = {
        "action": "capture",
        "title": "Native model task",
        "project": "Demo",
        "due_date": "2030-01-01",
        "request_id": "native-capture",
    }
    with turn(host):
        assert active_turn(host.ref.session_id) is not None
        assert call(host, args, write=True)["error"]["code"] == "session_write_not_activated"
    assert not local.database(host.home).exists()
    assert activate(host)["data"]["access"] == "write"
    with turn(host):
        captured = call(host, args, write=True)
        assert captured["status"] == "ok", captured
        task = captured["data"]
        assert call(host, args, write=True)["replayed"]
        assert call(host)["data"]["items"][0]["id"] == task["id"]
        assert call(host, {"action": "search", "query": "Native"})["data"]["items"]
        assert call(host, {"action": "projects"})["data"]["items"]
        assert call(host, {"action": "agenda", "on": "2030-01-02"})["data"]["items"]
        update = {
            "action": "update",
            "task_id": task["id"],
            "expected_revision": 1,
            "title": "Updated",
            "request_id": "native-update",
        }
        assert call(host, update, write=True)["data"]["revision"] == 2
        done = {
            "action": "complete",
            "task_id": task["id"],
            "expected_revision": 1,
            "note": "Finished",
            "request_id": "native-done",
        }
        assert call(host, done, write=True)["error"]["code"] == "revision_conflict"
        done["expected_revision"] = 2
        assert call(host, done, write=True)["data"]["state"] == "done"
        history_args = {"action": "history", "task_id": task["id"], "limit": 2}
        history = call(host, history_args)["data"]
        assert history["current_revision"] == 3 and history["current_state"] == "done"
        assert [item["operation"] for item in history["items"]] == ["capture", "update"]
        final = call(host, {**history_args, "after_revision": history["next_cursor"]})["data"]
        assert [item["operation"] for item in final["items"]] == ["complete"]
    assert active_turn(host.ref.session_id) is None
    assert call(host)["error"]["code"] == "no_active_local_turn"
    assert call(host, history_args)["error"]["code"] == "no_active_local_turn"
    assert activate(host, "disable")["data"]["access"] == "disabled"
    with turn(host):
        assert call(host)["error"]["code"] == "session_tools_not_activated"
        assert call(host, history_args)["error"]["code"] == "session_tools_not_activated"


def test_native_history_read_activation_and_validation(host):
    activate(host)
    with turn(host):
        task = call(
            host,
            {"action": "capture", "title": "Private task", "request_id": "history-task"},
            write=True,
        )["data"]
    activate(host, "enable-read")
    args = {"action": "history", "task_id": task["id"]}
    with turn(host):
        result = call(host, args)
        assert result["status"] == "ok"
        assert result["data"]["items"][0]["operation"] == "capture"
        assert "Private task" not in json.dumps(result)
        assert call(host, {**args, "after_revision": 2})["error"]["code"] == "invalid_cursor"
        assert call(host, {**args, "after_revision": True})["error"]["code"] == "invalid_request"
        assert call(host, {**args, "after": task["id"]})["error"]["code"] == "invalid_request"
    with turn(host, sid="different-session"):
        denied = call(host, args, sid="different-session")
        assert denied["error"]["code"] == "session_tools_not_activated"


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
def test_real_turn_wrong_scope_never_opens_storage(host, change, code):
    activate(host)
    with turn(host, **change):
        result = call(host, sid=change.get("sid"))
    assert result["error"]["code"] == code, result
    assert not local.database(host.home).exists()


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
    assert not local.database(host.home).exists()


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
    assert not local.database(host.home).exists()


def test_native_reload_discards_activation_and_unload_closes_retained_callbacks(host):
    from gateway.session_context import scoped_session_key
    from tools.registry import registry

    activate(host)
    retained = registry.get_entry("personal_tasks_read").handler
    command = host.manager._plugin_commands["personal-tools"]["handler"]
    host.manager.discover_and_load(force=True)
    with turn(host):
        assert call(host)["error"]["code"] == "session_tools_not_activated"
        assert (
            json.loads(
                retained({"action": "list"}, session_id=host.ref.session_id, task_id="native-task")
            )["error"]["code"]
            == "local_model_tools_unloaded"
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
    assert result["error"]["code"] == "local_model_tools_unloaded"
    assert not local.database(host.home).exists()


def test_native_delegated_and_cron_context_denied(host):
    from agent.delegation_context import delegated_child_context
    from gateway.session_context import clear_session_vars, set_session_vars

    activate(host)
    with turn(host), delegated_child_context():
        assert call(host)["error"]["code"] == "no_active_local_turn"
    tokens = set_session_vars(cron_session="1")
    try:
        with turn(host):
            assert call(host)["error"]["code"] == "no_active_local_turn"
    finally:
        clear_session_vars(tokens)
    assert not local.database(host.home).exists()


def test_admitted_operator_can_activate_same_session_without_owner_claim(host):
    actor = host.connection.actor
    host.connection.actor = replace(
        actor, subject="another-operator", capabilities=actor.capabilities | {"session:operator"}
    )
    assert activate(host, "enable-read")["status"] == "ok"
    with turn(host):
        assert call(host)["status"] == "ok"


def test_finalized_context_and_uncopied_worker_have_no_admission(host):
    from concurrent.futures import ThreadPoolExecutor

    from agent import relay_runtime

    activate(host)
    with turn(host) as context:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(call, host).result(timeout=5)
        assert result["error"]["code"] == "no_active_local_turn"
        relay_runtime.SESSION_COORDINATOR.end_turn(context, outcome="success")
        assert call(host)["error"]["code"] == "no_active_local_turn"
    assert not local.database(host.home).exists()


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


def test_actual_finalization_lock_waits_for_admitted_storage_then_fences_copied_context(
    host, monkeypatch
):
    import importlib
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context

    from agent import relay_runtime

    module = host.manager._plugins[PLUGIN_ID].module
    tasks = importlib.import_module(module.__name__ + ".personal_agent.tasks")
    original_run = tasks.TaskStore.run
    admitted = threading.Event()
    release = threading.Event()
    finalizing = threading.Event()
    store_calls = []

    def blocked_run(store, operation, payload):
        store_calls.append(operation)
        admitted.set()
        assert release.wait(5)
        return original_run(store, operation, payload)

    monkeypatch.setattr(tasks.TaskStore, "run", blocked_run)
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
            work = pool.submit(worker_context.run, call, host)
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
        assert stale_context.run(call, host)["error"]["code"] == "no_active_local_turn"
        assert call(host)["error"]["code"] == "no_active_local_turn"
        assert store_calls == ["list"]


@pytest.mark.parametrize(
    "settings,valid",
    [
        ({}, True),
        ({"mode": "local_tasks", "local_conversation": True}, True),
        ({"mode": "local_tasks", "local_conversation": True, "local_model_tools": False}, True),
        ({"local_model_tools": True}, False),
        ({"mode": "read_only", "local_conversation": True, "local_model_tools": True}, False),
        ({"mode": "local_tasks", "local_model_tools": True}, False),
        ({"mode": "local_tasks", "local_conversation": True, "local_model_tools": "true"}, False),
        ({"mode": "local_tasks", "local_conversation": True, "local_model_tools": 1}, False),
    ],
)
def test_default_and_invalid_model_tool_config_never_registers_tools(native, settings, valid):  # noqa: F811
    home, manager = native
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"] = settings
    (home / "config.yaml").write_text(json.dumps(config))
    manager.discover_and_load()
    plugin = manager._plugins[PLUGIN_ID]
    assert (plugin.error is None) is valid
    assert "personal-tools" not in manager._plugin_commands
    assert not {"personal_tasks_read", "personal_tasks_write"}.intersection(plugin.tools_registered)
    assert not local.database(home).exists()
