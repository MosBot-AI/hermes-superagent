"""Explicit memory commands through pinned native LOCAL authorization.

Synthetic temporary profiles only: no listener, credentials, model or provider.
Host internals are observations, not dependencies of the plugin implementation.
"""

import asyncio
import json
import sqlite3
from dataclasses import replace

import pytest
import test_local_conversation_tasks as task_commands
from test_local_conversation_tasks import make_host
from test_local_task_cli import PLUGIN_ID, install

native = task_commands.native


def configure(home, **settings):
    value = {
        "mode": "local_tasks",
        "local_conversation": True,
        "local_memory": True,
        **settings,
    }
    config = {
        "plugins": {"enabled": [PLUGIN_ID], "entries": {PLUGIN_ID: {"settings": value}}},
        "delegation": {"backend": "default"},
        "memory": {"provider": "synthetic-existing-provider"},
    }
    (home / "config.yaml").write_text(json.dumps(config), encoding="utf-8")


@pytest.fixture
def host(native):
    home, manager = native
    configure(home)
    return make_host(home, manager)


def command(host, text):
    from gateway.session_commands import execute_command

    result = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-memory " + text})
    )
    assert result["type"] == "exec"
    return json.loads(result["output"])


def handler(host):
    return host.manager._plugin_commands["personal-memory"]["handler"]


def assert_error(result, code):
    assert result["status"] == "error", result
    assert result["data"] is None
    assert result["replayed"] is False
    assert result["error"]["code"] == code


def test_load_help_preserve_native_memory_and_do_not_create_store(host):
    before = (host.home / "config.yaml").read_bytes()
    native_memory = host.home / "memories"
    native_memory.mkdir(exist_ok=True)
    source = native_memory / "MEMORY.md"
    source.write_text("Synthetic native memory must not be imported", encoding="utf-8")
    assert command(host, "help")["status"] == "ok"
    assert not (host.home / "plugin-data").exists()
    assert (host.home / "config.yaml").read_bytes() == before
    assert source.read_text() == "Synthetic native memory must not be imported"
    loaded = host.manager._plugins[PLUGIN_ID]
    assert loaded.tools_registered == ["personal_agent_status"]
    assert not loaded.hooks_registered and not loaded.middleware_registered
    assert command(host, 'search "Synthetic native memory"')["data"]["items"] == []
    assert (host.home / "config.yaml").read_bytes() == before
    assert source.read_text() == "Synthetic native memory must not be imported"


def test_absent_and_disabled_memory_do_not_register(native):
    home, manager = native
    # The shared fixture enables task conversations, but not personal memory.
    manager.discover_and_load()
    assert "personal-tasks" in manager._plugin_commands
    assert "personal-memory" not in manager._plugin_commands
    configure(home, local_memory=False)
    manager.discover_and_load(force=True)
    assert "personal-memory" not in manager._plugin_commands
    assert not (home / "plugin-data").exists()


@pytest.mark.parametrize(
    "settings",
    [
        {"local_memory": "true"},
        {"local_memory": 1},
        {"local_memory": None},
        {"local_memory": []},
        {"local_conversation": False},
        {"mode": "read_only", "local_conversation": False},
    ],
)
def test_invalid_memory_configuration_never_registers(native, settings):
    home, manager = native
    configure(home, **settings)
    manager.discover_and_load()
    assert manager._plugins[PLUGIN_ID].error
    assert "personal-memory" not in manager._plugin_commands
    assert not (home / "plugin-data").exists()


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
def test_native_admission_denies_before_memory_storage(host, failure, reason):
    from hermes_state_runtime import RuntimeStoreError

    actor = host.connection.actor
    if failure == "wrong_owner":
        host.connection.actor = replace(actor, subject="someone-else")
    elif failure == "no_control":
        host.connection.actor = replace(actor, capabilities=frozenset({"session:read"}))
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
        command(host, 'remember "Must not persist" --request-id refused')
    assert caught.value.reason == reason
    assert not (host.home / "plugin-data").exists()


@pytest.mark.parametrize("platform", ["telegram", "discord", "api_server"])
def test_native_inbound_rejects_nonlocal_memory_before_storage(host, platform):
    from gateway.config import Platform
    from gateway.platforms.base import MessageEvent

    source = replace(host.source, platform=Platform(platform))
    event = MessageEvent(text="/personal-memory list", source=source)
    entry = host.runner.session_store.lookup_by_session_key(host.live.route)
    result = asyncio.run(host.runner._hm_run_plugin_handler(handler(host), event, source, entry))
    assert_error(json.loads(result), "unsupported_origin")
    assert not (host.home / "plugin-data").exists()


@pytest.mark.parametrize(
    "context",
    [
        {},
        {"platform": "local", "source": None},
        {"platform": "cli", "source": None, "session_id": "", "session_key": ""},
    ],
)
def test_unbound_direct_callbacks_cannot_open_store(host, context):
    assert_error(json.loads(handler(host)("list", **context)), "unsupported_origin")
    assert not (host.home / "plugin-data").exists()


def test_host_producer_cannot_parse_memory_slash_command(host):
    from gateway.platforms.base import MessageEvent

    event = MessageEvent(
        text='/personal-memory remember "Must not persist"',
        source=host.source,
        allow_gateway_control=False,
    )
    assert not event.is_command()
    assert event.get_command() is None
    assert not (host.home / "plugin-data").exists()


def database(home):
    return home / "plugin-data" / PLUGIN_ID / "memory" / "records.sqlite3"


def retained_command(host, callback, text):
    from gateway.platforms.base import MessageEvent

    event = MessageEvent(text="/personal-memory " + text, source=host.source)
    entry = host.runner.session_store.lookup_by_session_key(host.live.route)
    return json.loads(
        asyncio.run(host.runner._hm_run_plugin_handler(callback, event, host.source, entry))
    )


def test_retained_callback_rechecks_config_and_unload(host):
    callback = handler(host)
    configure(host.home, local_memory=False)
    assert_error(retained_command(host, callback, "list"), "local_memory_disabled")
    configure(host.home, local_memory="true")
    assert_error(retained_command(host, callback, "list"), "invalid_configuration")
    configure(host.home, local_memory=False)
    host.manager.discover_and_load(force=True)
    assert "personal-memory" not in host.manager._plugin_commands
    assert_error(retained_command(host, callback, "list"), "local_memory_unloaded")
    configure(host.home)
    host.manager.discover_and_load(force=True)
    callback = handler(host)
    host.manager.unload()
    assert "personal-memory" not in host.manager._plugin_commands
    assert_error(retained_command(host, callback, "list"), "local_memory_unloaded")
    assert not (host.home / "plugin-data").exists()


def test_even_real_source_without_host_context_is_unbound(host):
    result = handler(host)(
        "list",
        platform="local",
        source=host.source,
        session_id=host.ref.session_id,
        session_key=host.live.route,
    )
    assert_error(json.loads(result), "unsupported_origin")
    assert not (host.home / "plugin-data").exists()


def test_native_memory_lifecycle_and_durable_receipts(host):
    added = command(host, 'remember "Prefer jasmine tea" --topic tastes --request-id remember')
    assert added["schema_version"] == "personal.local-memory.v1"
    assert added["status"] == "ok", added
    record = added["data"]
    record_id = record["record_id"]
    assert record["revision"] == 1
    assert "content" not in record
    assert database(host.home).is_file()
    assert not (host.home / "plugin-data" / PLUGIN_ID / "tasks.sqlite3").exists()
    replay = command(host, 'remember "Prefer jasmine tea" --topic tastes --request-id remember')
    assert replay["replayed"] and replay["data"] == record
    assert_error(
        command(host, 'remember "Different content" --topic tastes --request-id remember'),
        "idempotency_conflict",
    )
    assert len(command(host, "list")["data"]["items"]) == 1
    assert len(command(host, 'search "jasmine"')["data"]["items"]) == 1
    shown = command(host, f"show {record_id}")
    assert shown["data"]["content"] == "Prefer jasmine tea"
    host.manager.discover_and_load(force=True)
    assert command(host, f"show {record_id}")["data"] == shown["data"]
    corrected = command(
        host,
        f'correct {record_id} --text "Prefer green tea" --expected-revision 1 --request-id edit',
    )
    assert corrected["status"] == "ok", corrected
    assert corrected["data"]["revision"] == 2
    assert_error(
        command(host, f"forget {record_id} --expected-revision 1 --request-id stale"),
        "revision_conflict",
    )
    assert command(host, 'search "jasmine"')["data"]["items"] == []
    assert command(host, f"show {record_id}")["data"]["content"] == "Prefer green tea"
    exported = command(host, "export --limit 1")["data"]
    assert len(exported["items"]) == 1
    forgotten = command(host, f"forget {record_id} --expected-revision 2 --request-id forget")
    assert forgotten["status"] == "ok", forgotten
    assert command(host, "list")["data"]["items"] == []
    assert command(host, 'search "green"')["data"]["items"] == []
    assert "Prefer green tea" not in json.dumps(command(host, f"show {record_id}"))
    assert "Prefer jasmine tea" not in json.dumps(command(host, "export"))
    with sqlite3.connect(database(host.home)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_two_profile_native_dispatch_and_retained_callback_scope(native, tmp_path):
    from gateway.run import _profile_runtime_scope
    from hermes_cli.plugins import get_plugin_manager

    home_a, manager_a = native
    configure(home_a)
    host_a = make_host(home_a, manager_a)
    callback_a = handler(host_a)
    home_b = tmp_path / "second-profile"
    install(home_b)
    configure(home_b)
    with _profile_runtime_scope(home_b):
        host_b = make_host(home_b, get_plugin_manager())
    assert host_a.manager is not host_b.manager
    with _profile_runtime_scope(home_b):
        added_a = command(host_a, 'remember "Only profile A" --request-id same-key')
    with _profile_runtime_scope(home_a):
        added_b = command(host_b, 'remember "Only profile B" --request-id same-key')
    assert added_a["status"] == added_b["status"] == "ok", (added_a, added_b)
    assert not added_a["replayed"] and not added_b["replayed"]
    assert [row["content"] for row in command(host_a, "list")["data"]["items"]] == [
        "Only profile A"
    ]
    assert [row["content"] for row in command(host_b, "list")["data"]["items"]] == [
        "Only profile B"
    ]
    before_a, before_b = database(home_a).read_bytes(), database(home_b).read_bytes()
    with _profile_runtime_scope(home_b):
        refused = retained_command(host_b, callback_a, 'remember "Wrong scope" --request-id bad')
    assert_error(refused, "profile_context_changed")
    assert database(home_a).read_bytes() == before_a
    assert database(home_b).read_bytes() == before_b


@pytest.mark.parametrize("controller", ["same_owner_other_transport", "operator"])
def test_host_authorized_controllers_share_memory_access(host, controller):
    added = command(host, 'remember "Shared host access" --request-id shared')
    assert added["status"] == "ok", added
    actor = host.connection.actor
    if controller == "operator":
        host.connection.actor = replace(
            actor,
            subject="other-operator",
            capabilities=actor.capabilities | {"session:operator"},
            transport_id="other-transport",
        )
    else:
        host.connection.actor = replace(actor, transport_id="other-transport")
    assert command(host, f"show {added['data']['record_id']}")["data"]["content"] == (
        "Shared host access"
    )


@pytest.mark.parametrize("operation", ["list", "export"])
def test_native_read_pages_are_bounded(host, operation):
    ids = set()
    for index in range(3):
        result = command(host, f'remember "Synthetic page {index}" --request-id page-{index}')
        assert result["status"] == "ok", result
        ids.add(result["data"]["record_id"])
    seen = set()
    cursor = None
    for _ in range(3):
        args = f"{operation} --limit 1" + (f" --after {cursor}" if cursor else "")
        page = command(host, args)["data"]
        assert len(page["items"]) == 1
        record_id = page["items"][0]["record_id"]
        assert record_id not in seen
        seen.add(record_id)
        if not page["has_more"]:
            assert page["next_cursor"] is None
            break
        cursor = page["next_cursor"]
        assert cursor
    assert seen == ids


@pytest.mark.parametrize(
    "text",
    [
        'remember "unterminated',
        "list --limit 0",
        "list --limit 1000000",
        "export --limit 1000000",
        "remember --unknown SECRET_MUST_NOT_BE_REFLECTED",
        "import SECRET_MUST_NOT_BE_REFLECTED",
    ],
)
def test_invalid_commands_redact_arguments_and_do_not_open_store(host, text):
    result = command(host, text)
    assert result["status"] == "error"
    assert result["data"] is None
    assert "SECRET_MUST_NOT_BE_REFLECTED" not in json.dumps(result)
    assert not (host.home / "plugin-data").exists()
