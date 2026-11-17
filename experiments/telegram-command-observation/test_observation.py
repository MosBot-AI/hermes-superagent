"""Explicit review harness for Telegram's original SDK update and command dispatch."""

import asyncio
import dataclasses
import json
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from telegram import Bot, Update, User
from test_local_task_cli import native as native
from test_owner_telegram_ingress import ACTOR, HOST_LAUNCHER, RECEIVERS, deliver, wire_adapter

PROBE_ID = "synthetic-telegram-probe"
PROBE_CODE = """
import dataclasses
import json

before_read = None
retained = []
results = []

def observe(raw_args, *, telegram_observation=None):
    retained.append(telegram_observation)
    if before_read is not None:
        before_read()
    value = None if telegram_observation is None or raw_args == "defer" else telegram_observation()
    replay = None if value is None else telegram_observation()
    result = {
        "observation": dataclasses.asdict(value) if value is not None else None,
        "replayed": replay is not None,
    }
    results.append(result)
    return json.dumps(result)

def legacy(raw_args, **kwargs):
    result = {"keywords": sorted(kwargs)}
    results.append(result)
    return json.dumps(result)

def register(ctx):
    ctx.register_command("telegram-probe", observe, description="Synthetic observation probe")
    ctx.register_command("telegram-legacy", legacy, description="Synthetic legacy probe")
"""


def make_bot(receiver):
    bot = Bot(f"{receiver}:synthetic-only-no-network")
    # Stand in for SDK initialization. No getMe request or transport connection occurs.
    bot._bot_user = User(receiver, "Synthetic receiver", True, username="probe_bot")
    return bot


def packet(
    bot,
    *,
    command="telegram_probe status",
    origin="message",
    chat_id=ACTOR,
    chat_type="private",
    actor_id=ACTOR,
    actor_is_bot=False,
    update_id=131,
    **fields,
):
    message = {
        "message_id": 71,
        "date": 1767225600,
        "text": "/" + command,
        "chat": {"id": chat_id, "type": chat_type, "first_name": "Synthetic"},
        "from": {"id": actor_id, "first_name": "Synthetic", "is_bot": actor_is_bot},
        **fields,
    }
    return Update.de_json({"update_id": update_id, origin: message}, bot)


@pytest.fixture
def native_probe(native, monkeypatch, request):
    from gateway.config import GatewayConfig
    from gateway.run import GatewayRunner
    from hermes_cli import plugin_host, plugins

    home, manager = native
    probe = home / "plugins" / PROBE_ID
    probe.mkdir()
    (probe / "plugin.yaml").write_text(
        f"name: {PROBE_ID}\nversion: '0.1.0'\ndescription: Synthetic Telegram contract\n",
        encoding="utf-8",
    )
    (probe / "__init__.py").write_text(PROBE_CODE, encoding="utf-8")
    config_path = home / "config.yaml"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["plugins"]["enabled"].append(PROBE_ID)
    if getattr(request, "param", None) == "hosted":
        launcher = home / "test-host-launcher.py"
        launcher.write_text(HOST_LAUNCHER, encoding="utf-8")
        source_root = Path(plugin_host.__file__).resolve().parents[1]
        config["plugins"].update(
            isolation="host",
            host={"launcher": [sys.executable, "-I", "-B", str(launcher), str(source_root)]},
        )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(plugins, "get_plugin_manager", lambda: manager)
    monkeypatch.delenv("HERMES_PLUGIN_HOST_PROCESS", raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", str(ACTOR))
    monkeypatch.setenv("TELEGRAM_ALLOW_BOTS", "all")
    manager.discover_and_load()
    loaded = manager._plugins[PROBE_ID]
    assert loaded.enabled and loaded.error is None
    runner = GatewayRunner(GatewayConfig(sessions_dir=home / "sessions"))
    no_model = AsyncMock(side_effect=AssertionError("probe fell through to inference"))
    monkeypatch.setattr(runner, "_handle_message_with_agent", no_model)
    host = manager._running_plugin_host()
    try:
        if getattr(request, "param", None) == "hosted":
            assert loaded.module is None
            assert host.pid == int((home / "test-host-pid").read_text()) != os.getpid()
        yield runner, loaded.module
    finally:
        no_model.assert_not_called()
        manager.unload()
        if host is not None:
            host.shutdown()
        assert not (home / "plugin-data").exists()
        assert not (home / "test-forbidden-host-effect").exists()


def connected_adapter(runner, receiver=RECEIVERS[0], *, webhook=False):
    adapter, _ = wire_adapter(runner, receiver)
    adapter._bot = make_bot(receiver)
    adapter._webhook_mode = webhook
    if not webhook:
        adapter._begin_polling_generation()
    adapter._mark_connected()
    return adapter


async def dispatch(runner, receiver=RECEIVERS[0], *, bot=None, **fields):
    adapter = connected_adapter(runner, receiver)
    await deliver(adapter, packet(bot or adapter._bot, **fields))
    adapter.send.assert_awaited_once()
    return json.loads(adapter.send.await_args.kwargs["content"])


def test_clean_pin_has_no_original_observation(native_probe):
    runner, _ = native_probe
    assert asyncio.run(dispatch(runner)) == {"observation": None, "replayed": False}


def test_candidate_original_update_identifies_the_actual_receiving_account(native_probe):
    runner, module = native_probe
    for receiver in RECEIVERS:
        result = asyncio.run(dispatch(runner, receiver))
        assert result == {
            "observation": {
                "actor_id": ACTOR,
                "receiver_id": receiver,
                "profile": "default",
                "command": "telegram-probe",
            },
            "replayed": False,
        }
        assert module.retained[-1]() is None
    assert asyncio.run(dispatch(runner, command="telegram_probe defer"))["observation"] is None
    assert module.retained[-1] is not None
    assert module.retained[-1]() is None


@pytest.mark.parametrize(
    "fields",
    [
        {"origin": "edited_message", "edit_date": 1767225601},
        {
            "forward_origin": {
                "type": "hidden_user",
                "date": 1767225600,
                "sender_user_name": "Synthetic original",
            }
        },
        {"chat_id": -100000123, "chat_type": "group"},
        {"actor_is_bot": True},
        pytest.param({"message_thread_id": 41, "is_topic_message": True}, id="private_topic"),
        pytest.param({"business_connection_id": "synthetic-business"}, id="business_context"),
        {"via_bot": {"id": 137246802, "is_bot": True, "first_name": "Synthetic inline bot"}},
    ],
)
def test_candidate_non_direct_updates_keep_command_response_without_evidence(native_probe, fields):
    runner, module = native_probe
    assert asyncio.run(dispatch(runner, **fields))["observation"] is None
    assert module.retained == [None]


def test_candidate_sdk_update_bound_to_different_bot_is_not_observed(native_probe):
    runner, module = native_probe
    # Two connections to the same numeric receiver are still distinct live SDK objects.
    assert asyncio.run(dispatch(runner, bot=make_bot(RECEIVERS[0])))["observation"] is None
    assert module.retained == [None]


def test_candidate_fabricated_command_event_has_no_adapter_observation(native_probe):
    from gateway.platforms.event import MessageType

    runner, module = native_probe

    async def fabricate():
        adapter = connected_adapter(runner)
        data = packet(adapter._bot)
        event = adapter._build_message_event(data.message, MessageType.COMMAND, update_id=131)
        await adapter.handle_message(event)
        await asyncio.wait_for(asyncio.gather(*adapter._session_tasks.values()), timeout=10)

    asyncio.run(fabricate())
    assert module.results == [{"observation": None, "replayed": False}]


@pytest.mark.parametrize(
    "change",
    [
        "expires",
        "disconnect",
        "rehome_adapter",
        "bot_replaced",
        "bot_uninitialized",
        "allowlist_revoked",
        "copied_event",
    ],
)
def test_candidate_requires_live_exact_event_and_transport(native_probe, monkeypatch, change):
    from gateway import run_telegram_command_observation as observation
    from gateway.config import Platform

    runner, module = native_probe
    adapter = connected_adapter(runner)
    if change == "expires":
        clock = observation.monotonic

        def invalidate():
            monkeypatch.setattr(observation, "monotonic", lambda: clock() + 5.0)
    elif change == "disconnect":

        def invalidate():
            runner.adapters = {}
    elif change == "rehome_adapter":

        def invalidate():
            runner._profile_adapters = {"other-profile": {Platform.TELEGRAM: adapter}}
            runner.adapters = {}
    elif change == "bot_replaced":

        def invalidate():
            runner.adapters[Platform.TELEGRAM]._bot = make_bot(RECEIVERS[0])
    elif change == "bot_uninitialized":

        def invalidate():
            adapter._bot._bot_user = None
    elif change == "allowlist_revoked":

        def invalidate():
            monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", str(ACTOR + 1))
            adapter.config.extra["allow_from"] = [str(ACTOR + 1)]
    else:
        original = adapter.handle_message

        async def copy_event(event):
            copied = dataclasses.replace(event)
            copied._telegram_direct_command = event._telegram_direct_command
            await original(copied)

        monkeypatch.setattr(adapter, "handle_message", copy_event)
        invalidate = None
    module.before_read = invalidate
    asyncio.run(deliver(adapter, packet(adapter._bot)))
    assert module.results == [{"observation": None, "replayed": False}]
    assert (module.retained[0] is None) == (change == "copied_event")


def test_candidate_legacy_kwargs_remain_the_documented_context(native_probe):
    runner, _ = native_probe
    assert asyncio.run(dispatch(runner, command="telegram_legacy")) == {
        "keywords": ["platform", "session_id", "session_key", "source"]
    }


@pytest.mark.parametrize("stage", ["before_callback", "before_read"])
@pytest.mark.parametrize("transition", ["poll_fenced", "poll_restarted", "webhook_reconnected"])
def test_candidate_lifecycle_rejects_old_observation_and_accepts_new_input(
    native_probe, monkeypatch, stage, transition
):
    from gateway.config import Platform

    runner, module = native_probe
    adapter = connected_adapter(runner, webhook=transition == "webhook_reconnected")
    bot = adapter._bot

    def transition_transport():
        if transition == "webhook_reconnected":
            adapter._mark_disconnected()
            adapter._mark_connected()
        else:
            adapter._fence_polling()
            if transition == "poll_restarted":
                adapter._begin_polling_generation()
        assert adapter._bot is bot and runner.adapters[Platform.TELEGRAM] is adapter

    with monkeypatch.context() as change:
        if stage == "before_callback":
            original = adapter.handle_message

            async def deliver_after_transition(event):
                transition_transport()
                await original(event)

            change.setattr(adapter, "handle_message", deliver_after_transition)
        else:
            change.setattr(module, "before_read", transition_transport)
        asyncio.run(deliver(adapter, packet(bot)))
    assert module.results == [{"observation": None, "replayed": False}]
    assert (module.retained[0] is None) is (stage == "before_callback")
    if transition == "poll_fenced":
        adapter._begin_polling_generation()
    asyncio.run(deliver(adapter, packet(bot, update_id=132, message_id=72)))
    assert module.results[-1] == {
        "observation": {
            "actor_id": ACTOR,
            "receiver_id": RECEIVERS[0],
            "profile": "default",
            "command": "telegram-probe",
        },
        "replayed": False,
    }
    assert adapter.send.await_count == 2


def test_candidate_lifecycle_rechecks_after_authorization(native_probe, monkeypatch):
    runner, module = native_probe
    adapter = connected_adapter(runner)
    authorize = runner._is_user_authorized_for_source

    def change_during_authorization(source):
        allowed = authorize(source)
        adapter._fence_polling()
        adapter._begin_polling_generation()
        return allowed

    module.before_read = lambda: monkeypatch.setattr(
        runner, "_is_user_authorized_for_source", change_during_authorization
    )
    asyncio.run(deliver(adapter, packet(adapter._bot)))
    assert module.retained[0] is not None
    assert module.results == [{"observation": None, "replayed": False}]


@pytest.mark.parametrize("native_probe", ["hosted"], indirect=True)
def test_candidate_hosted_command_never_receives_live_observation(native_probe):
    runner, module = native_probe
    assert module is None
    assert asyncio.run(dispatch(runner)) == {"observation": None, "replayed": False}
