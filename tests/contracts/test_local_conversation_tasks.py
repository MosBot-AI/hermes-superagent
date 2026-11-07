"""Pinned host command admission through real LOCAL authorization and plugin SQLite.

No listener, network transport, model or provider is started. The connection is
an already-authenticated in-memory transport fixture, not a login/auth proof.
Host internals below are test observations only, never plugin dependencies.
"""

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_local_task_cli import PLUGIN_ID, install


def configure(home, *, enabled=True, mode="local_tasks"):
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "plugins": {
                    "enabled": [PLUGIN_ID],
                    "entries": {
                        PLUGIN_ID: {"settings": {"mode": mode, "local_conversation": enabled}}
                    },
                },
                "delegation": {"backend": "default"},
            }
        )
    )


@pytest.fixture
def native(tmp_path, monkeypatch):
    from pathlib import Path

    from hermes_cli.plugins import _reset_plugin_managers_for_tests, get_plugin_manager

    home = tmp_path / "profile"
    install(home)
    configure(home)
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "os-home"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "os-home")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    _reset_plugin_managers_for_tests()
    manager = get_plugin_manager()
    try:
        yield home, manager
    finally:
        _reset_plugin_managers_for_tests()


def load(manager):
    manager.discover_and_load()
    loaded = manager._plugins[PLUGIN_ID]
    assert loaded.enabled and loaded.error is None
    assert loaded.module is not None
    assert not loaded.hooks_registered and not loaded.middleware_registered
    assert loaded.tools_registered == ["personal_agent_status"]
    return manager._plugin_commands["personal-tasks"]["handler"]


@pytest.fixture
def host(native):
    return make_host(*native)


def make_host(home, manager):
    from gateway.config import GatewayConfig, Platform
    from gateway.run import GatewayRunner
    from gateway.run_inbound_hooks import GatewayInboundHooksMixin
    from gateway.session import SessionEntry
    from gateway.session_authority import LiveSession, SessionAuthority
    from gateway.session_contract import SessionActor, SessionRef
    from gateway.session_local import LocalSessionAdapter
    from gateway.session_local_recovery import local_source

    load(manager)
    now = datetime.now(UTC)
    sid = "synthetic-native-session"
    route = "agent:main:local:" + sid
    entry = SessionEntry(route, sid, now, now)

    class Runner(GatewayInboundHooksMixin):
        # Real host binding; only executor and unstarted transport plumbing differ.
        _set_session_env = GatewayRunner._set_session_env
        _clear_session_env = GatewayRunner._clear_session_env
        _session_env_scope = GatewayRunner._session_env_scope

        def _adapters_for_profile(self, profile):
            return self.adapters if profile in (None, "default") else {}

        def _adapter_for_source(self, source):
            return self._adapters_for_profile(source.profile).get(source.platform)

        def _session_key_for_source(self, source):
            return route

        async def _run_in_executor_with_context(self, call):
            return await asyncio.to_thread(call)

    runner = Runner()
    runner.config = GatewayConfig()
    runner._draining = False
    runner.session_store = SimpleNamespace(
        lookup_by_session_key=lambda key: entry if key == route else None
    )
    authority = SessionAuthority(
        runner, profile_id=str(home), instance_id="synthetic-runtime", db=None, epoch=1
    )
    runner.session_authority = authority
    adapter = LocalSessionAdapter(authority)
    runner.adapters = {Platform.LOCAL: adapter}
    source = local_source(authority, sid, "synthetic-owner")
    live = LiveSession(source=source, route=route)
    authority.sessions[sid] = live
    adapter.register_source(source)
    adapter.policies[sid] = SimpleNamespace(cwd=str(home), terminal_json="{}")
    actor = SessionActor(
        "synthetic-owner",
        str(home),
        frozenset({"session:read", "session:control"}),
        "synthetic-transport",
    )
    connection = SimpleNamespace(authority=authority, actor=actor, subscriptions={})
    return SimpleNamespace(
        home=home,
        manager=manager,
        runner=runner,
        authority=authority,
        adapter=adapter,
        source=source,
        live=live,
        connection=connection,
        ref=SessionRef(str(home), sid),
    )


def command(host, text, **extra):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(
            host.connection, host.ref, {"command": "personal-tasks --json " + text, **extra}
        )
    )
    assert result["type"] == "exec"
    return json.loads(result["output"])


def database(home):
    return home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3"


def test_real_native_owner_command_sqlite_lifecycle(host):
    added = command(
        host,
        'add "Native task" --project "Demo project" --due-date 2030-01-01 --request-id native-add',
    )
    assert added["status"] == "ok", added
    task = added["data"]
    assert task["revision"] == 1
    assert database(host.home).is_file()
    replay = command(
        host,
        'add "Native task" --project "Demo project" --due-date 2030-01-01 --request-id native-add',
    )
    assert replay["replayed"] and replay["data"] == task
    assert command(host, "list")["data"]["items"][0]["id"] == task["id"]
    assert command(host, 'search "Native"')["data"]["items"][0]["id"] == task["id"]
    assert command(host, "projects")["data"]["items"][0]["project"] == "Demo project"
    assert command(host, "agenda --on 2030-01-02")["data"]["items"][0]["id"] == task["id"]
    history = command(host, f"history {task['id']}")
    assert history["status"] == "ok" and history["request_id"] is None
    assert history["data"]["current_revision"] == 1
    assert history["data"]["items"][0]["operation"] == "capture"
    updated = command(
        host,
        f"update {task['id']} --expected-revision 1 --title Changed --request-id native-update",
    )
    assert updated["data"]["revision"] == 2
    stale = command(
        host, f"done {task['id']} --expected-revision 1 --note Finished --request-id stale"
    )
    assert stale["error"]["code"] == "revision_conflict"
    done = command(
        host, f"done {task['id']} --expected-revision 2 --note Finished --request-id done"
    )
    assert done["data"]["state"] == "done"
    assert command(host, "list")["data"]["items"] == []
    assert command(host, f"show {task['id']}")["data"]["revision"] == 3
    with sqlite3.connect(database(host.home)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("wrong_owner", "permission_denied"),
        ("no_control", "permission_denied"),
        ("no_read", "permission_denied"),
        ("wrong_profile", "profile_mismatch"),
        ("stale_source", "permission_denied"),
        ("mutated_source", "permission_denied"),
        ("foreign_source_profile", "permission_denied"),
        ("draining", "runtime_draining"),
        ("retiring", "runtime_draining"),
        ("retired", "runtime_retired"),
    ],
)
def test_native_admission_refuses_before_plugin_storage(host, failure, reason):
    from hermes_state_runtime import RuntimeStoreError

    actor = host.connection.actor
    if failure == "wrong_owner":
        host.connection.actor = replace(actor, subject="someone-else")
    elif failure == "no_control":
        host.connection.actor = replace(
            actor, capabilities=frozenset({"session:read", "session:respond"})
        )
    elif failure == "no_read":
        host.connection.actor = replace(actor, capabilities=frozenset({"session:control"}))
    elif failure == "wrong_profile":
        host.connection.actor = replace(actor, profile_id=str(host.home / "foreign"))
    elif failure == "stale_source":
        host.live.source = replace(host.source)
    elif failure == "mutated_source":
        host.source.chat_id = "changed"
    elif failure == "foreign_source_profile":
        host.source.profile = "foreign"
    elif failure == "draining":
        host.runner._draining = True
    else:
        setattr(host.authority, failure, True)
    with pytest.raises(RuntimeStoreError) as caught:
        command(host, 'add "Must never persist" --request-id refused')
    assert caught.value.reason == reason
    assert not (host.home / "plugin-data").exists()


def test_disabled_by_default_and_read_only_has_no_command(native):
    home, manager = native
    configure(home, enabled=False, mode="read_only")
    manager.discover_and_load()
    assert "personal-tasks" not in manager._plugin_commands
    assert not (home / "plugin-data").exists()


def test_reload_unload_and_retained_callback_rechecks_config(native):
    home, manager = native
    callback = load(manager)
    configure(home, enabled=False)
    result = json.loads(
        callback(
            "--json list",
            platform="cli",
            source=None,
            session_id="synthetic",
            session_key="synthetic",
        )
    )
    assert result["error"]["code"] == "local_conversation_disabled"
    manager.discover_and_load(force=True)
    assert "personal-tasks" not in manager._plugin_commands
    configure(home)
    manager.discover_and_load(force=True)
    assert "personal-tasks" in manager._plugin_commands
    manager.unload()
    assert "personal-tasks" not in manager._plugin_commands
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize("platform", ["telegram", "discord", "api_server"])
def test_real_inbound_dispatch_rejects_nonlocal_before_storage(host, platform):
    from gateway.config import Platform
    from gateway.platforms.base import MessageEvent

    source = replace(host.source, platform=Platform(platform))
    event = MessageEvent(text="/personal-tasks --json list", source=source)
    entry = host.runner.session_store.lookup_by_session_key(host.live.route)
    callback = host.manager._plugin_commands["personal-tasks"]["handler"]
    result = asyncio.run(host.runner._hm_run_plugin_handler(callback, event, source, entry))
    assert json.loads(result)["error"]["code"] == "unsupported_origin"
    assert not (host.home / "plugin-data").exists()


def test_host_producer_event_cannot_parse_slash_command(host):
    from gateway.platforms.base import MessageEvent

    event = MessageEvent(
        text='/personal-tasks add "Do not execute"', source=host.source, allow_gateway_control=False
    )
    assert not event.is_command()
    assert event.get_command() is None
    assert not (host.home / "plugin-data").exists()


def test_absent_opt_in_has_no_registration(native):
    home, manager = native
    (home / "config.yaml").write_text(
        json.dumps(
            {
                "plugins": {
                    "enabled": [PLUGIN_ID],
                    "entries": {PLUGIN_ID: {"settings": {"mode": "local_tasks"}}},
                },
            }
        )
    )
    manager.discover_and_load()
    assert manager._plugins[PLUGIN_ID].enabled
    assert "personal-tasks" not in manager._plugin_commands
    assert not (home / "plugin-data").exists()


def test_session_entry_id_can_differ_from_local_chat_id(host):
    # Session resets keep routing chat identity while the conversation ID moves.
    entry = host.runner.session_store.lookup_by_session_key(host.live.route)
    entry.session_id = "synthetic-reset-session"
    assert entry.session_id != host.source.chat_id
    added = command(host, 'add "After reset" --request-id after-reset')
    assert added["status"] == "ok", added


def test_native_database_survives_plugin_reload_and_cancel(host):
    added = command(host, 'add "Persistent task" --request-id persistent')
    task = added["data"]
    host.manager.discover_and_load(force=True)
    assert command(host, f"show {task['id']}")["data"] == task
    cancelled = command(
        host, f"cancel {task['id']} --expected-revision 1 --note Withdrawn --request-id cancel"
    )
    assert cancelled["data"]["state"] == "cancelled"
    assert command(host, "list")["data"]["items"] == []
    assert len(command(host, "list --state all")["data"]["items"]) == 1


def test_source_host_wire_record_requires_no_isolation_downgrade(host):
    # Exercise the actual public callback with the host's record codec. This
    # verifies serialization compatibility, not a running isolated worker.
    from hermes_cli.plugin_host_wire import decode, encode

    source = decode(encode(host.source))
    callback = host.manager._plugin_commands["personal-tasks"]["handler"]
    result = json.loads(
        callback(
            '--json add "Wire source" --request-id wire',
            platform="local",
            source=source,
            session_id=host.ref.session_id,
            session_key=host.live.route,
        )
    )
    assert result["status"] == "ok", result


@pytest.mark.parametrize("controller", ["same_owner_other_transport", "operator"])
def test_admitted_owner_and_operator_share_native_task_access(host, controller):
    added = command(host, 'add "Shared owner task" --request-id owner-add')
    assert added["status"] == "ok", added
    task = added["data"]
    actor = host.connection.actor
    if controller == "operator":
        host.connection.actor = replace(
            actor,
            subject="synthetic-other-operator",
            capabilities=actor.capabilities | {"session:operator"},
            transport_id="synthetic-operator-transport",
        )
    else:
        host.connection.actor = replace(actor, transport_id="synthetic-second-owner-transport")
    # Admission remains the real host's owner/operator check. This does not
    # claim a transport is physically local or issue credentials for it.
    assert command(host, f"show {task['id']}")["data"] == task
    changed = command(
        host,
        f"update {task['id']} --expected-revision 1 --title Shared --request-id shared-update",
    )
    assert changed["status"] == "ok", changed
    host.connection.actor = actor
    assert command(host, f"show {task['id']}")["data"]["title"] == "Shared"


def test_two_profile_native_dispatch_and_retained_callback_scope(native, tmp_path):
    from gateway.run import _profile_runtime_scope
    from hermes_cli.plugins import get_plugin_manager

    home_a, manager_a = native
    host_a = make_host(home_a, manager_a)
    callback_a = manager_a._plugin_commands["personal-tasks"]["handler"]
    home_b = tmp_path / "second-profile"
    install(home_b)
    configure(home_b)
    with _profile_runtime_scope(home_b):
        manager_b = get_plugin_manager()
        host_b = make_host(home_b, manager_b)
    assert manager_a is not manager_b
    assert manager_a._plugins[PLUGIN_ID].module is not manager_b._plugins[PLUGIN_ID].module

    # Both commands use the same idempotency key, independently scoped to the
    # authoritative profile. Ambient scope deliberately points to the other
    # profile; real execute_command must select its own profile before dispatch.
    with _profile_runtime_scope(home_b):
        added_a = command(host_a, 'add "Only profile A" --request-id same-key')
    with _profile_runtime_scope(home_a):
        added_b = command(host_b, 'add "Only profile B" --request-id same-key')
    assert added_a["status"] == added_b["status"] == "ok", (added_a, added_b)
    assert not added_a["replayed"] and not added_b["replayed"]
    assert added_a["data"]["id"] != added_b["data"]["id"]
    assert [row["title"] for row in command(host_a, "list")["data"]["items"]] == ["Only profile A"]
    assert [row["title"] for row in command(host_b, "list")["data"]["items"]] == ["Only profile B"]

    before_a, before_b = database(home_a).read_bytes(), database(home_b).read_bytes()
    with _profile_runtime_scope(home_b):
        refused = json.loads(
            callback_a(
                '--json add "Wrong retained scope" --request-id forbidden',
                platform="local",
                source=host_b.source,
                session_id=host_b.ref.session_id,
                session_key=host_b.live.route,
            )
        )
    assert refused["error"]["code"] == "profile_context_changed"
    assert database(home_a).read_bytes() == before_a
    assert database(home_b).read_bytes() == before_b
