"""Manual acceptance of a native Bot reply waking its viewed local sender."""

import asyncio
import json
import os
import sys
from contextlib import closing
from urllib.parse import urlsplit

from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon
from native_profile_cli_fixture import retained_host_client
from test_native_bot_poll_reply import MESSAGE, NOTICE, isolated_reply_fixture
from test_native_bot_receipt import AUTHOR
from test_native_managed_worker import MODEL, ScriptedModel, scripted_model

PROMPT = "Synthetic Bot push request"
INPUT = "fixture-bot-push-input"
RECEIVER_REPLY = "Synthetic recipient's push reply"
SENDER_ACK = "Synthetic sender acknowledged the queued request"
SENDER_REPLY = "Synthetic sender received the completion"
TOOL_CALL = "fixture-bot-push-call"


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
                self.server.observed.set()
                if not self.server.release.wait(25):
                    self.server.unexpected += 1
                    self.send_error(500)
                    return
                reply["content"] = RECEIVER_REPLY
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


def create_profiles(home, scout, url):
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
        (profile / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
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


async def exercise_push(endpoint, host, home, scout, model):
    from hermes_cli.gateway_runtime_discovery import query_identify
    from hermes_state import SessionDB

    port = urlsplit(endpoint.api_origin).port
    assert port is not None
    with (home.parent / "gateway-port").open("x", encoding="ascii") as file:
        file.write(str(port))
    owner = query_identify(home, timeout=2)
    assert owner["instance_id"] == endpoint.instance_id
    restrict = activate(home.parent, dial_ports=(port,), dial_host="127.0.0.1")
    try:
        async with asyncio.timeout(66), retained_host_client(home, endpoint) as client:
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
            await client.rpc("session.resume", profile="scout", session_id=sender, _timeout=8)
            submitted = await client.rpc(
                "prompt.submit",
                profile="scout",
                session_id=sender,
                input_id=INPUT,
                text=PROMPT,
                _timeout=8,
            )
            try:
                await settled(client, "scout", scout, sender, submitted["admission_id"], SENDER_ACK)
                assert await asyncio.to_thread(model.observed.wait, 5)
                waiter = await owned_waiter(host, home.parent, owner["pid"])
                ack = model.ack
                assert ack["status"] in {"queued", "claimed"} and ack["to"] == "@hermes"
                assert ack["reply_delivery"] == "notification"
                assert not {"error", "notification_error", "reply"}.intersection(ack)
                delivery, process = ack["delivery_id"], ack["process_id"]
                assert len(admissions(scout, sender)) == 1
                (queued,) = admissions(home, target)
                assert queued["request_id"] == f"bot:{delivery}"
                assert queued["status"] != "terminal"
            finally:
                model.release.set()

            event = await completion_event(client, sender)
            assert all(value in event["text"] for value in (RECEIVER_REPLY, delivery, process))
            (origin, wake) = admissions(scout, sender)
            assert origin["admission_id"] == submitted["admission_id"]
            assert wake["principal_id"].startswith("automation:")
            assert json.loads(wake["request_id"])[0] == "completion"
            await settled(client, "scout", scout, sender, wake["admission_id"], SENDER_REPLY)
            await settled(client, "default", home, target, queued["admission_id"], RECEIVER_REPLY)
            assert [row["admission_id"] for row in admissions(scout, sender)] == [
                origin["admission_id"],
                wake["admission_id"],
            ]
            while not client.events.empty():
                assert not is_completion_event(client.events.get_nowait(), sender)
            (received,) = admissions(home, target)
            assert received["admission_id"] == queued["admission_id"]
            assert received["payload"]["text"] == MESSAGE
            assert not waiter.is_running()

            with closing(SessionDB(scout / "state.db", read_only=True)) as db:
                messages = db.get_messages(sender)
            (card,) = [row for row in messages if row["display_kind"] == "process_complete"]
            assert (messages[-1]["role"], messages[-1]["content"]) == ("assistant", SENDER_REPLY)
            assert all(value in card["content"] for value in (RECEIVER_REPLY, delivery, process))
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
            assert model.turns[0] == "send" and model.turns[-1] == "wake"
            assert sorted(model.turns) == ["ack", "recipient", "send", "wake"]
            assert model.unexpected == 0
            assert all(value in model.wake_text for value in (RECEIVER_REPLY, delivery, process))
    finally:
        restrict()


def test_native_viewed_bot_reply_wakes_sender_once(tmp_path_factory, monkeypatch):
    with isolated_reply_fixture(
        tmp_path_factory, monkeypatch, activate_hook="native_bot_push_guard:activate_push_child"
    ) as (_, fixture, scout, env, installed):
        assert not installed
        host, home, _, _ = fixture
        with scripted_model(handler=BotPushModel) as model:
            url = f"http://127.0.0.1:{model.server_port}/v1"
            create_profiles(home, scout, url)
            child_env = env | {
                "HERMES_BOT_ACCEPTANCE_ROOT": str(home.parent),
                "HERMES_BOT_ACCEPTANCE_MODEL_PORT": str(model.server_port),
            }
            with gateway_daemon(host, home, child_env, "bot-push") as endpoint:
                asyncio.run(exercise_push(endpoint, host, home, scout, model))
