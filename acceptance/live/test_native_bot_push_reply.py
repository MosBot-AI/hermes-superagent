"""Manual acceptance of native local Bot replies with and without a viewer."""

import asyncio
import json
import os
import sys
from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass
from urllib.parse import urlsplit

from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon
from native_profile_cli_fixture import retained_host_client
from test_native_bot_poll_reply import MESSAGE, NOTICE, isolated_reply_fixture
from test_native_bot_receipt import AUTHOR
from test_native_managed_worker import MODEL, ScriptedModel, scripted_model
from test_packaged_gateway_bot import (
    ADD,
    TASK,
    command,
    confirm_task,
    lookup,
    verify_saved_state,
)

PROMPT = "Synthetic Bot push request"
INPUT = "fixture-bot-push-input"
RECEIVER_REPLY = "Synthetic recipient's push reply"
SENDER_ACK = "Synthetic sender acknowledged the queued request"
SENDER_REPLY = "Synthetic sender received the completion"
TOOL_CALL = "fixture-bot-push-call"
FOLLOW_UP = "Synthetic explicit follow-up after reconnect"
FOLLOW_UP_ID = "fixture-bot-reconnect-follow-up"
RECOVERED_REPLY = "Synthetic sender used the recovered completion"


class BotPushModel(ScriptedModel):
    def do_POST(self):
        body = self.completion_request()
        if body is None:
            return
        messages = body.get("messages", [])
        user = next((m.get("content") for m in reversed(messages) if m["role"] == "user"), None)
        tools = [tool["function"]["name"] for tool in body.get("tools", [])]
        text = json.dumps(user, ensure_ascii=False)
        reply = {"role": "assistant"}
        phase = None
        if (
            self.path == "/v1/chat/completions"
            and self.headers.get("Authorization") == "Bearer no-key-required"
            and body.get("model") == MODEL
        ):
            if MESSAGE in text:
                phase = "recipient"
                self.server.recipient_requests += 1
                self.server.observed.set()
                if not self.server.release.wait(25):
                    self.server.unexpected += 1
                    self.send_error(500)
                    return
                reply["content"] = RECEIVER_REPLY
            elif FOLLOW_UP in text:
                phase = "follow-up"
                self.server.follow_up_history = [
                    m["content"] for m in messages if m["role"] == "user"
                ]
                reply["content"] = RECOVERED_REPLY
            elif RECEIVER_REPLY in text and "[IMPORTANT:" in text:
                phase = "wake"
                self.server.wake_text = text
                reply["content"] = SENDER_REPLY
            elif PROMPT in text and messages[-1]["role"] == "tool":
                phase = "ack"
                if messages[-1].get("tool_call_id") != TOOL_CALL:
                    self.server.unexpected += 1
                    self.send_error(400)
                    return
                self.server.ack = json.loads(messages[-1]["content"])
                reply["content"] = SENDER_ACK
            elif PROMPT in text and tools == ["message_agent"]:
                phase = "send"
                reply.update(
                    content=None,
                    tool_calls=[
                        {
                            "id": TOOL_CALL,
                            "type": "function",
                            "function": {
                                "name": "message_agent",
                                "arguments": json.dumps(
                                    {"target": "@hermes", "message": NOTICE, "expects_reply": True}
                                ),
                            },
                        }
                    ],
                )
        if phase is None:
            self.server.unexpected += 1
            self.send_error(400)
            return
        self.server.turns.append(phase)
        self.send_completion(body, reply)


def create_profiles(home, scout, url, *, installed):
    config = {
        "gateway": {"multiplex_profiles": True, "managed_workers": False},
        "webapp": {"enabled": False},
        "model": {"provider": "custom", "default": MODEL, "base_url": url},
        "auxiliary": {"title_generation": {"enabled": False}},
        "terminal": {
            "backend": "local",
            "cwd": str(home.parent),
            "auto_source_bashrc": False,
        },
        "platform_toolsets": {"gui": []},
        "telemetry": {"shared_metrics": {"enabled": False}},
    }
    for profile in (home, scout):
        config_path = profile / "config.yaml"
        if profile == home and installed:
            from ruamel.yaml import YAML

            yaml = YAML()
            recipient_config = yaml.load(config_path)
            recipient_config.update(config)
            yaml.dump(recipient_config, config_path)
        else:
            config_path.write_text(json.dumps(config), encoding="utf-8")
        (profile / "models_dev_cache.json").write_text(
            '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
            encoding="utf-8",
        )


def admissions(home, session):
    from hermes_state import SessionDB
    from hermes_state_runtime import list_session_admissions

    with closing(SessionDB(home / "state.db", read_only=True)) as db:
        return list_session_admissions(db, session_id=session, pending_only=False)


async def settled(client, profile, home, session, admission, response):
    async with asyncio.timeout(24):
        while True:
            receipt = await client.rpc(
                "prompt.receipt",
                profile=profile,
                session_id=session,
                admission_id=admission,
                include_result=True,
                _timeout=5,
            )
            if receipt["status"] == "terminal":
                break
            await asyncio.sleep(0.1)
    assert receipt["ref"] == {"profile_id": str(home), "session_id": session}
    assert receipt["outcome"] == "completed"
    assert receipt["result"]["final_response"] == response


def is_completion_event(frame, sender):
    assert isinstance(frame, dict), "Native Gateway event stream closed"
    params = frame.get("params", {})
    return (
        frame.get("method") == "event"
        and params.get("session_id") == sender
        and params.get("type") == "message.start"
        and params["payload"].get("display_kind") == "process_complete"
    )


async def completion_event(client, sender):
    async with asyncio.timeout(30):
        while True:
            frame = await client.events.get()
            if is_completion_event(frame, sender):
                return frame["params"]["payload"]


async def owned_waiter(host, root, owner_pid):
    import psutil

    owner = psutil.Process(owner_pid)
    expected = [sys.executable, str(host / "tools/bot_mode_dm.py"), "--run-delivery"]
    async with asyncio.timeout(8):
        while True:
            matches = []
            for process in owner.children(recursive=True):
                try:
                    if (
                        process.cmdline()[:3] == expected
                        and (root / f"socket-guard-{process.pid}").is_file()
                    ):
                        matches.append(process)
                except psutil.NoSuchProcess, psutil.ZombieProcess:
                    continue
            if matches:
                (waiter,) = matches
                return waiter
            await asyncio.sleep(0.05)


def completion_card(messages, reply_tokens):
    (card,) = [row for row in messages if row.get("display_kind") == "process_complete"]
    assert card["role"] == "user"
    assert all(value in card["content"] for value in reply_tokens)
    return card


def sender_messages(scout, sender):
    from hermes_state import SessionDB

    with closing(SessionDB(scout / "state.db", read_only=True)) as db:
        return db.get_messages(sender)


def completion_admission(scout, sender, original):
    (origin, completion) = admissions(scout, sender)
    assert origin["admission_id"] == original
    assert completion["principal_id"].startswith("automation:")
    assert json.loads(completion["request_id"])[0] == "completion"
    assert origin["seq"] < completion["seq"]
    return completion


async def verify_viewed(client, scout, sender, original, reply_tokens, model):
    event = await completion_event(client, sender)
    assert all(value in event["text"] for value in reply_tokens)
    wake = completion_admission(scout, sender, original)
    await settled(client, "scout", scout, sender, wake["admission_id"], SENDER_REPLY)
    assert completion_admission(scout, sender, original)["admission_id"] == wake["admission_id"]
    while not client.events.empty():
        assert not is_completion_event(client.events.get_nowait(), sender)
    messages = sender_messages(scout, sender)
    completion_card(messages, reply_tokens)
    assert (messages[-1]["role"], messages[-1]["content"]) == ("assistant", SENDER_REPLY)
    assert model.turns[0] == "send" and model.turns[-1] == "wake"
    assert sorted(model.turns) == ["ack", "recipient", "send", "wake"]
    assert all(value in model.wake_text for value in reply_tokens)


async def wait_for_disconnected_reply(scout, sender, original, reply_tokens, model):
    async with asyncio.timeout(24):
        while True:
            rows = admissions(scout, sender)
            if len(rows) >= 2 and all(row["status"] == "terminal" for row in rows):
                break
            await asyncio.sleep(0.05)
    note = completion_admission(scout, sender, original)
    assert note["outcome"] == "completed"
    messages = sender_messages(scout, sender)
    stored = completion_card(messages, reply_tokens)
    assert messages[-1] == stored
    assert stored["display_metadata"]["completion_admission"] == note["admission_id"]
    assert stored["display_metadata"]["completion_note"] == [note["request_id"]]
    assert sorted(model.turns) == ["ack", "recipient", "send"]
    return note, stored


async def verify_reopened(client, scout, sender, original, reply_tokens, note, stored, model):
    resumed = await client.rpc(
        "session.resume", profile="scout", session_id=sender, display_projection=True, _timeout=8
    )
    assert resumed["session_id"] == resumed["stored_session_id"] == sender
    assert not resumed["running"] and not resumed["pending"]
    recovered = completion_card(resumed["messages"], reply_tokens)
    assert recovered["content"] == stored["content"]
    assert recovered["display_metadata"] == stored["display_metadata"]
    (projected,) = [
        row for row in resumed["display_messages"] if row.get("display_kind") == "process_complete"
    ]
    assert projected["text"] == stored["content"]
    assert projected["display_metadata"] == stored["display_metadata"]
    await settled(client, "scout", scout, sender, note["admission_id"], "")

    repeated = await client.rpc(
        "prompt.submit",
        profile="scout",
        session_id=sender,
        input_id=INPUT,
        text=PROMPT,
        _timeout=8,
    )
    assert repeated["admission_id"] == original
    assert (repeated["status"], repeated["outcome"]) == ("terminal", "completed")
    assert completion_admission(scout, sender, original)["admission_id"] == note["admission_id"]
    assert sorted(model.turns) == ["ack", "recipient", "send"]

    follow_up = await client.rpc(
        "prompt.submit",
        profile="scout",
        session_id=sender,
        input_id=FOLLOW_UP_ID,
        text=FOLLOW_UP,
        _timeout=8,
    )
    await settled(client, "scout", scout, sender, follow_up["admission_id"], RECOVERED_REPLY)
    assert [row["admission_id"] for row in admissions(scout, sender)] == [
        original,
        note["admission_id"],
        follow_up["admission_id"],
    ]
    context = json.dumps(model.follow_up_history, ensure_ascii=False)
    assert context.count(reply_tokens[0]) == 1
    assert all(value in context for value in reply_tokens)
    assert context.index(reply_tokens[0]) < context.index(FOLLOW_UP)
    messages = sender_messages(scout, sender)
    assert completion_card(messages, reply_tokens)["display_metadata"] == stored["display_metadata"]
    assert (messages[-1]["role"], messages[-1]["content"]) == ("assistant", RECOVERED_REPLY)
    assert model.turns[0] == "send" and model.turns[-1] == "follow-up"
    assert sorted(model.turns) == ["ack", "follow-up", "recipient", "send"]


async def verify_recipient(client, home, send):
    target, queued, delivery = send.target, send.receiver_admission, send.delivery_id
    await settled(client, "default", home, target, queued["admission_id"], RECEIVER_REPLY)
    (received,) = admissions(home, target)
    assert received["admission_id"] == queued["admission_id"]
    assert received["payload"]["text"] == MESSAGE
    (receipt_path,) = (home / "runtime/bot_live_delivery").glob("*.json")
    receipt = json.loads(receipt_path.read_bytes())
    assert (receipt["session_id"], receipt["delivery_id"], receipt["admission_id"]) == (
        target,
        delivery,
        queued["admission_id"],
    )
    assert receipt["status"] == "settled" and receipt["reply"] == RECEIVER_REPLY
    assert receipt["principal_id"] == f"uid:{os.getuid()}"
    assert {key: receipt["author"].get(key) for key in AUTHOR} == AUTHOR


@contextmanager
def gateway_dial(home, endpoint):
    from hermes_cli.gateway_runtime_discovery import query_identify

    port = urlsplit(endpoint.api_origin).port
    assert port is not None
    port_file = home.parent / "gateway-port"
    with port_file.open("x", encoding="ascii") as file:
        file.write(str(port))
    restrict = activate(home.parent, dial_ports=(port,), dial_host="127.0.0.1")
    try:
        owner = query_identify(home, timeout=2)
        assert owner["instance_id"] == endpoint.instance_id
        yield owner["pid"]
    finally:
        restrict()
        port_file.unlink()


@dataclass(frozen=True)
class BotDelivery:
    sender: str
    target: str
    original: str
    receiver_admission: dict
    delivery_id: str
    process_id: str
    recipient_task: dict | None = None

    @property
    def reply_tokens(self):
        return RECEIVER_REPLY, self.delivery_id, self.process_id


async def check_recipient_plugin(recipient, target):
    inventory = await recipient.rpc("plugins.list", _timeout=8)
    (plugin,) = [row for row in inventory["plugins"] if row["key"] == "hermes-personal-agent"]
    assert plugin["enabled"] and plugin["commands"] > 0 and not plugin["error"]
    assert await lookup(recipient) == [(target, target)]
    resumed = await recipient.rpc("session.resume", session_id=target, _timeout=8)
    assert resumed["session_id"] == resumed["stored_session_id"] == target
    return resumed


async def start_delivery(client, home, scout, model, *, recipient=None):
    ids = {}
    for profile in ("default", "scout"):
        created = await client.rpc(
            "session.create",
            profile=profile,
            request_id=f"fixture-bot-push-{profile}",
            title="Bot Chat",
            source="gui",
            cwd=str(home.parent),
            hidden=True,
            toolsets=[],
            _timeout=8,
        )
        ids[profile] = created["session_id"]
    target, sender = ids["default"], ids["scout"]
    task = None
    if recipient is not None:
        await check_recipient_plugin(recipient, target)
        task = (await command(recipient, target, ADD))["data"]
        assert task["title"] == TASK and task["revision"] == 1
    await client.rpc("session.resume", profile="scout", session_id=sender, _timeout=8)
    submitted = await client.rpc(
        "prompt.submit",
        profile="scout",
        session_id=sender,
        input_id=INPUT,
        text=PROMPT,
        _timeout=8,
    )
    original = submitted["admission_id"]
    await settled(client, "scout", scout, sender, original, SENDER_ACK)
    assert await asyncio.to_thread(model.observed.wait, 5)
    ack = model.ack
    assert ack["status"] in {"queued", "claimed"} and ack["to"] == "@hermes"
    assert ack["reply_delivery"] == "notification"
    assert not {"error", "notification_error", "reply"}.intersection(ack)
    delivery_id, process_id = ack["delivery_id"], ack["process_id"]
    assert len(admissions(scout, sender)) == 1
    (receiver_admission,) = admissions(home, target)
    assert receiver_admission["request_id"] == f"bot:{delivery_id}"
    assert receiver_admission["status"] == "started"
    return BotDelivery(sender, target, original, receiver_admission, delivery_id, process_id, task)


async def exercise_local_reply(endpoint, host, home, scout, model, *, reconnect, installed):
    from hermes_cli.gateway_client import connect_gateway
    from websockets.protocol import State

    with gateway_dial(home, endpoint) as owner_pid:
        try:
            recipient_connection = (
                connect_gateway(endpoint=endpoint) if installed else nullcontext()
            )
            async with (
                asyncio.timeout(82),
                retained_host_client(home, endpoint) as client,
                recipient_connection as recipient,
            ):
                delivery = await start_delivery(client, home, scout, model, recipient=recipient)
                waiter = await owned_waiter(host, home.parent, owner_pid)
                if not reconnect:
                    model.release.set()
                    await verify_viewed(
                        client,
                        scout,
                        delivery.sender,
                        delivery.original,
                        delivery.reply_tokens,
                        model,
                    )
                    await verify_recipient(client, home, delivery)
                    if recipient is not None:
                        assert await lookup(recipient) == [(delivery.target, delivery.target)]
                        await confirm_task(recipient, delivery.target, delivery.recipient_task)
                        repeated = await client.rpc(
                            "prompt.submit",
                            profile="scout",
                            session_id=delivery.sender,
                            input_id=INPUT,
                            text=PROMPT,
                            _timeout=8,
                        )
                        assert repeated["admission_id"] == delivery.original
                        assert (repeated["status"], repeated["outcome"]) == (
                            "terminal",
                            "completed",
                        )
                        completion_admission(scout, delivery.sender, delivery.original)
                        while not client.events.empty():
                            assert not is_completion_event(
                                client.events.get_nowait(), delivery.sender
                            )

            if reconnect:
                # Keep the recipient held until the viewer's actual WebSocket has closed.
                assert client.websocket.state is State.CLOSED
                assert not model.release.is_set()
                model.release.set()
                note, stored = await wait_for_disconnected_reply(
                    scout, delivery.sender, delivery.original, delivery.reply_tokens, model
                )
                async with retained_host_client(home, endpoint) as reopened:
                    await verify_reopened(
                        reopened,
                        scout,
                        delivery.sender,
                        delivery.original,
                        delivery.reply_tokens,
                        note,
                        stored,
                        model,
                    )
                    await verify_recipient(reopened, home, delivery)
            assert not waiter.is_running()
            assert model.recipient_requests == 1 and model.unexpected == 0
            if delivery.recipient_task is not None:
                return delivery.target, delivery.recipient_task["id"]
        finally:
            model.release.set()


@contextmanager
def local_reply_fixture(tmp_path_factory, monkeypatch, *, installed=False):
    with isolated_reply_fixture(
        tmp_path_factory, monkeypatch, activate_hook="native_bot_push_guard:activate_push_child"
    ) as (_, fixture, scout, env, prepared):
        assert prepared == installed
        host, home, _, _ = fixture
        with scripted_model(handler=BotPushModel) as model:
            model.recipient_requests = 0
            create_profiles(
                home, scout, f"http://127.0.0.1:{model.server_port}/v1", installed=installed
            )
            child_env = env | {
                "HERMES_BOT_ACCEPTANCE_ROOT": str(home.parent),
                "HERMES_BOT_ACCEPTANCE_MODEL_PORT": str(model.server_port),
            }
            yield host, home, scout, child_env, model


def run_local_reply(tmp_path_factory, monkeypatch, *, reconnect, installed=False):
    with local_reply_fixture(tmp_path_factory, monkeypatch, installed=installed) as (
        host,
        home,
        scout,
        env,
        model,
    ):
        with gateway_daemon(host, home, env, "bot-push") as endpoint:
            saved = asyncio.run(
                exercise_local_reply(
                    endpoint, host, home, scout, model, reconnect=reconnect, installed=installed
                )
            )
        if installed:
            target, task_id = saved
            verify_saved_state(
                home,
                target,
                task_id,
                messages=(("user", MESSAGE), ("assistant", RECEIVER_REPLY)),
                admission_count=1,
            )


def test_installed_recipient_reply_wakes_viewed_sender_once(tmp_path_factory, monkeypatch):
    run_local_reply(tmp_path_factory, monkeypatch, reconnect=False, installed=True)


def test_native_viewed_bot_reply_wakes_sender_once(tmp_path_factory, monkeypatch):
    run_local_reply(tmp_path_factory, monkeypatch, reconnect=False)


def test_native_disconnected_bot_reply_recovers_once(tmp_path_factory, monkeypatch):
    run_local_reply(tmp_path_factory, monkeypatch, reconnect=True)
