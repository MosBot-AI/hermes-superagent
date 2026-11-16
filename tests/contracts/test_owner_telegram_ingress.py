"""Offline Telegram command ingress on the pinned native adapter and Gateway."""

import asyncio
import dataclasses
import functools
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from test_local_task_cli import PLUGIN_ID
from test_local_task_cli import native as native
from test_owner_entry_contracts import assert_denied

ACTOR = 137246801
OTHER_ACTOR = 137246802
GROUP = -100137246803
RECEIVERS = (1007001, 1007002)
TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


HOST_LAUNCHER = """\
import os
import runpy
import sys
from pathlib import Path

source_root, executable, option, module = sys.argv[1:]
assert (executable, option, module) == (sys.executable, "-m", "hermes_cli.plugin_host_child")
for name in set(os.environ) - {
    "HOME", "HERMES_HOME", "HERMES_PLUGIN_HOST_PROCESS", "LANG", "LC_ALL", "PATH", "TMPDIR",
}:
    del os.environ[name]
home = Path(os.environ["HERMES_HOME"])
assert home == Path.cwd()
(home / "test-host-pid").write_text(str(os.getpid()), encoding="utf-8")

def guard(event, args):
    network = event in {"socket.bind", "socket.connect", "socket.getaddrinfo", "socket.sendto"}
    private_data = (
        event in {"open", "sqlite3.connect"}
        and isinstance(args[0], (str, bytes))
        and "plugin-data" in Path(os.fsdecode(args[0])).parts
    )
    if network or private_data:
        with (home / "test-forbidden-host-effect").open("a", encoding="utf-8") as evidence:
            print(event, file=evidence)
        raise AssertionError("Hosted Telegram prohibits network and private plugin storage")

sys.addaudithook(guard)
sys.path.insert(0, source_root)
sys.argv[:] = [module]
runpy.run_module(module, run_name="__main__", alter_sys=True)
"""


def update(*, actor=ACTOR, group=False, bot=False, forwarded=False, edited=False, args="status"):
    message = SimpleNamespace(
        message_id=71,
        text=f"/personal_access {args}",
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        reply_to_message=None,
        date=TIMESTAMP,
        edit_date=TIMESTAMP if edited else None,
        forum_topic_created=None,
        forward_origin=SimpleNamespace(type="hidden_user") if forwarded else None,
        chat=SimpleNamespace(
            id=GROUP if group else actor,
            type="group" if group else "private",
            full_name="Synthetic Private Name",
            title="Synthetic group" if group else None,
            is_forum=False,
        ),
        from_user=SimpleNamespace(
            id=actor, full_name="Synthetic Private Name", first_name="Fixture", is_bot=bot
        ),
    )
    return SimpleNamespace(effective_message=message, update_id=131)


@pytest.fixture(params=["in_process", "host"], ids=["in-process", "hosted"])
def command_host(native, monkeypatch, request):
    from hermes_cli import plugin_host, plugins

    home, manager = native
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: manager)
    monkeypatch.delenv("HERMES_PLUGIN_HOST_PROCESS", raising=False)
    if request.param == "in_process":
        manager.discover_and_load()
        yield home, manager, None
        return

    launcher = home / "test-host-launcher.py"
    launcher.write_text(HOST_LAUNCHER, encoding="utf-8")
    source_root = Path(plugin_host.__file__).resolve().parents[1]
    config_path = home / "config.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["plugins"].update(
        isolation="host",
        host={"launcher": [sys.executable, "-I", "-B", str(launcher), str(source_root)]},
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    try:
        manager.discover_and_load()
        loaded = manager._plugins[PLUGIN_ID]
        assert loaded.enabled and loaded.error is None
        assert loaded.module is None
        host = manager._running_plugin_host()
        assert host is not None
        pid = int((home / "test-host-pid").read_text(encoding="utf-8"))
        assert host.pid == host.info["pid"] == pid != os.getpid()
        channel = host.ensure_started()
        rpc = Mock(wraps=channel.call)
        monkeypatch.setattr(channel, "call", rpc)
        yield home, manager, rpc
    finally:
        try:
            manager.unload()
        finally:
            host = manager._running_plugin_host()
            if host is not None:
                host.shutdown()
        assert not (home / "test-forbidden-host-effect").exists()


def assert_hosted_invocations(rpc, command_ref, received):
    from hermes_cli.plugin_host_wire import Record, decode

    calls = [call.args[1] for call in rpc.call_args_list if call.args[0] == "invoke"]
    assert len(calls) == len(received)
    for payload, (raw_args, context) in zip(calls, received, strict=True):
        assert payload["ref"] == command_ref
        assert payload["args"] == [raw_args]
        decoded = decode(payload["kwargs"])
        source = decoded.pop("source")
        assert isinstance(source, Record)
        expected = dataclasses.asdict(context["source"])
        expected["platform"] = context["source"].platform.value
        assert source == expected
        assert not {"_transport_adapter_ref", "forward_origin", "edit_revision"} & source.keys()
        assert decoded == {key: value for key, value in context.items() if key != "source"}


@pytest.fixture
def telegram_ingress(command_host, monkeypatch):
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner

    home, manager, rpc = command_host
    for key in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_ALLOW_BOTS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", str(ACTOR))
    monkeypatch.setenv("TELEGRAM_ALLOW_BOTS", "all")
    entry = manager._plugin_commands["personal-access"]
    callback = entry["handler"]
    received = []

    @functools.wraps(callback)
    def observe(raw_args, **kwargs):
        received.append((raw_args, kwargs))
        return callback(raw_args, **kwargs)

    monkeypatch.setitem(entry, "handler", observe)
    runner = GatewayRunner(GatewayConfig(sessions_dir=home / "sessions"))
    no_model = AsyncMock(side_effect=AssertionError("diagnostic fell through to a model turn"))
    connect = sqlite3.connect
    plugin_storage = Mock(side_effect=AssertionError("diagnostic attempted plugin storage"))

    def refuse_plugin_storage(database, *args, **kwargs):
        if "plugin-data" in Path(database).parts:
            plugin_storage()
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(runner, "_handle_message_with_agent", no_model)
    monkeypatch.setattr(sqlite3, "connect", refuse_plugin_storage)
    try:
        yield home, runner, received
    finally:
        no_model.assert_not_called()
        plugin_storage.assert_not_called()
        assert not (home / "plugin-data").exists()
        if rpc is not None:
            assert_hosted_invocations(rpc, callback.__hermes_plugin_host_ref__, received)


def wire_adapter(runner, receiver):
    from gateway.config import Platform, PlatformConfig
    from gateway.platforms.base import SendResult
    from plugins.platforms.telegram.adapter import TelegramAdapter

    settings = {"allow_from": [str(ACTOR)], "group_allow_from": [str(ACTOR)]}
    adapter = TelegramAdapter(PlatformConfig(enabled=True, extra=settings))
    adapter._bot = SimpleNamespace(id=receiver, username="synthetic_bot")
    adapter.gateway_runner = runner
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._wire_adapter_handlers(adapter)
    intake = AsyncMock(wraps=adapter._message_handler)
    adapter.set_message_handler(intake)
    adapter.send = AsyncMock(return_value=SendResult(success=True, message_id="local-reply"))
    adapter.send_typing = AsyncMock()
    return adapter, intake


async def deliver(adapter, packet):
    await adapter._handle_command(packet, None)
    await asyncio.wait_for(asyncio.gather(*adapter._session_tasks.values()), timeout=10)
    assert not adapter._session_tasks


async def dispatch(runner, packet, receiver):
    adapter, intake = wire_adapter(runner, receiver)
    await deliver(adapter, packet)
    return adapter, intake


def test_live_receiver_and_message_provenance_are_absent_from_the_public_callback(telegram_ingress):
    from gateway.session_identity import identity_of
    from hermes_cli.plugin_host_wire import decode, encode

    _, runner, received = telegram_ingress

    async def drive():
        return [
            await dispatch(runner, update(), RECEIVERS[0]),
            await dispatch(runner, update(), RECEIVERS[1]),
            await dispatch(runner, update(forwarded=True), RECEIVERS[1]),
            await dispatch(runner, update(edited=True), RECEIVERS[1]),
        ]

    deliveries = asyncio.run(drive())
    assert len(received) == 4
    contexts = [context for _, context in received]
    assert all(
        set(invocation) == {"source", "platform", "session_id", "session_key"}
        for invocation in contexts
    )
    assert [adapter._bot.id for adapter, _ in deliveries] == [
        RECEIVERS[0],
        RECEIVERS[1],
        RECEIVERS[1],
        RECEIVERS[1],
    ]
    sources = [invocation["source"] for invocation in contexts]
    assert all(dataclasses.asdict(source) == dataclasses.asdict(sources[0]) for source in sources)
    assert all(invocation["session_id"] == "" for invocation in contexts)
    assert len({invocation["session_key"] for invocation in contexts}) == 1
    for _, intake in deliveries:
        intake.assert_awaited_once()
    events = [intake.await_args.args[0] for _, intake in deliveries]
    assert [event.raw_message.forward_origin is not None for event in events] == [
        False,
        False,
        True,
        False,
    ]
    assert [event.edit_revision for event in events] == [None, None, None, "u131"]
    for (adapter, _), invocation in zip(deliveries, contexts, strict=True):
        source = invocation["source"]
        assert source._transport_adapter_ref() is adapter
        assert identity_of(source).adapter() is adapter
        restored = decode(encode(source))
        assert not hasattr(restored, "_transport_adapter_ref")
        assert identity_of(restored) is None
        assert not hasattr(restored, "forward_origin")
        assert not hasattr(restored, "edit_revision")
        adapter.send.assert_awaited_once()
        result = json.loads(adapter.send.await_args.kwargs["content"])
        assert_denied(result, "receiving_transport_unverified")
        assert result["actor_observation"]["candidate_recognized"] is True


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"group": True}, "private_chat_required"),
        ({"bot": True}, "human_actor_required"),
        ({"args": "owner=true secret-in-args"}, "invalid_arguments"),
        ({"actor": OTHER_ACTOR, "args": "owner=true secret-in-args"}, None),
    ],
)
def test_telegram_ingress_keeps_diagnostic_and_transport_denials_distinct(
    telegram_ingress, changes, reason
):
    _, runner, received = telegram_ingress
    adapter, intake = asyncio.run(dispatch(runner, update(**changes), RECEIVERS[0]))
    if reason is None:
        intake.assert_not_awaited()
        assert not received
        adapter.send.assert_not_awaited()
        return
    assert len(received) == 1
    intake.assert_awaited_once()
    adapter.send.assert_awaited_once()
    result = json.loads(adapter.send.await_args.kwargs["content"])
    assert_denied(result, reason)


def test_current_gateway_allowlist_blocks_a_command_accepted_by_the_adapter(
    telegram_ingress, monkeypatch
):
    _, runner, received = telegram_ingress

    async def drive():
        adapter, intake = wire_adapter(runner, RECEIVERS[0])
        await deliver(adapter, update())
        adapter.send.assert_awaited_once()
        assert_denied(
            json.loads(adapter.send.await_args.kwargs["content"]),
            "receiving_transport_unverified",
        )
        adapter.send.reset_mock()
        intake.reset_mock()

        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", str(OTHER_ACTOR))
        await deliver(adapter, update())
        intake.assert_awaited_once()
        adapter.send.assert_not_awaited()
        assert len(received) == 1

    asyncio.run(drive())
