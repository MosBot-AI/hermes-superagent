"""Native same-install message_agent admission with a named Bot author."""

import asyncio
import hashlib
import json
from contextlib import closing
from types import SimpleNamespace

from native_bot_asgi import native_bot_gateway as native_bot_gateway
from test_native_voice_audio_asgi import run_native_async


def sender_snapshot(db):
    with db._read_ctx() as conn:
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
            for table in ("sessions", "messages", "state_meta", "session_admissions")
        }


def test_named_bot_notify_only_admits_to_default_with_separate_author(
    native_bot_gateway, monkeypatch
):
    from agent.tool_executor import _resolve_sequential_dispatch, _ToolCallRef
    from gateway.session_automation import restore_local_automation
    from hermes_cli import gateway_client
    from hermes_state import SessionDB
    from hermes_state_runtime import list_session_admissions
    from tools import bot_mode_dm

    native = native_bot_gateway
    sender_home = native.home / "profiles" / "scout"
    sender_home.mkdir(parents=True)
    (sender_home / "config.yaml").write_text(
        '{"telemetry":{"shared_metrics":{"enabled":false}}}', encoding="utf-8"
    )
    (sender_home / "profile.yaml").write_text(
        '{"ui_meta":{"hermes-bots":{"title":"Scout Fixture"}}}', encoding="utf-8"
    )

    def unexpected_waiter(*args, **kwargs):
        raise AssertionError("Notify-only delivery started a waiter or a subprocess")

    monkeypatch.setattr(bot_mode_dm, "_spawn_delivery", unexpected_waiter)
    monkeypatch.setattr(bot_mode_dm, "_wait_live_dm", unexpected_waiter)

    observed = {}
    private_control_query = gateway_client.private_control_query

    def observe_intent(home, request):
        # The sender pins both files before asking the target's control door for a ticket.
        (payload_path,) = native.scratch.glob("**/dm-*.txt")
        intent_path = payload_path.with_suffix(".txt.live.json")
        observed.update(
            payload_path=payload_path,
            intent_path=intent_path,
            message=payload_path.read_text(encoding="utf-8"),
            intent=json.loads(intent_path.read_bytes()),
        )
        return private_control_query(home, request)

    monkeypatch.setattr(gateway_client, "private_control_query", observe_intent)

    output = "Synthetic Bot notice"
    message = f"Message from 🤖 Scout Fixture (@scout): [no reply needed] {output}"
    author = {"id": "bot:scout", "name": "scout", "is_bot": True}
    args = {"target": "@hermes", "message": output, "expects_reply": False}

    def execute(agent, call_id):
        call = _ToolCallRef("message_agent", args, "synthetic-bot-task", call_id, [])
        return _resolve_sequential_dispatch(agent, call, []).execute(call.args)

    with closing(SessionDB(sender_home / "state.db")) as sender_db:
        for session_id, title in (("scout-bot", "Bot Chat"), ("scout-scratch", "Scratch")):
            sender_db.create_session(session_id, source="local", user_id="synthetic-scout-owner")
            assert sender_db.set_session_title(session_id, title)
        assert sender_db.set_session_hidden("scout-bot", True)
        before = sender_snapshot(sender_db)

        def agent_context(session_id):
            return SimpleNamespace(
                _session_db=sender_db,
                session_id=session_id,
                _bot_mode_protocol=True,
                tools=[],
                valid_tool_names=set(),
            )

        async def scenario():
            transport = native.connect()
            native.ready = True
            ref = native.seed_bot_chat()
            mailbox = native.home / "runtime" / "bot_live_delivery"

            def admissions():
                return list_session_admissions(
                    native.db, session_id=ref.session_id, pending_only=False
                )

            scratch = agent_context("scout-scratch")
            assert not bot_mode_dm.ensure_message_agent_tool(scratch)
            assert not scratch.tools and not scratch.valid_tool_names
            denied = json.loads(await asyncio.to_thread(execute, scratch, "scratch-call"))
            assert "only available in a Bot Mode 'Bot Chat' session" in denied["error"]
            assert "delivery_id" not in denied
            assert not native.discoveries and not native.control_requests
            assert not transport.requests and not list(mailbox.glob("*.json")) and not admissions()

            scout = agent_context("scout-bot")
            assert bot_mode_dm.ensure_message_agent_tool(scout)
            assert [item["function"]["name"] for item in scout.tools] == ["message_agent"]
            assert scout.valid_tool_names == {"message_agent"}
            ack = json.loads(await asyncio.to_thread(execute, scout, "bot-call"))
            assert ack.get("status") == "queued", ack
            assert ack["to"] == "@hermes" and ack["expects_reply"] is False
            assert not {"error", "notification_error", "process_id", "reply"}.intersection(ack)

            key = hashlib.sha256(str(observed["payload_path"].resolve()).encode()).hexdigest()
            assert observed["message"] == message
            assert observed["intent"]["owner"]["profile_home"] == native.profile_id
            assert observed["intent"]["owner"]["session_id"] == ref.session_id
            assert observed["intent"]["delivery_id"] == ack["delivery_id"] == key
            assert observed["intent"]["author"] == author
            assert observed["intent"]["message"] == message
            assert not observed["payload_path"].exists() and not observed["intent_path"].exists()

            assert native.discoveries == [native.home, native.home]
            (ticket_request,) = native.control_requests
            assert ticket_request["verb"] == "session-ticket"
            assert ticket_request["params"] == {
                "profile_id": native.profile_id,
                "instance_id": native.instance_id,
                "purpose": "interactive",
            }
            (request,) = transport.requests
            assert request["method"] == "bot_relay.deliver"
            assert request["params"] == {
                "id": key,
                "profile": "default",
                "session_id": ref.session_id,
                "message": message,
                "author": author,
            }
            (response,) = transport.responses
            result = response["result"]
            assert result["status"] == "queued" and result["delivery_id"] == key
            assert (
                result["profile_home"] == native.profile_id
                and result["session_id"] == ref.session_id
            )
            assert result["message"] == message and not result["reply"]
            assert len(transport.tickets) == 1 and not transport.dropped

            (receipt_path,) = mailbox.glob("*.json")
            assert receipt_path.name == f"{key}.json"
            receipt = json.loads(receipt_path.read_bytes())
            assert receipt["principal_id"] == native.subject and receipt["author"] == author
            assert receipt["delivery_id"] == key and receipt["status"] == "queued"
            assert receipt["session_id"] == ref.session_id and receipt["message"] == message

            (row,) = admissions()
            route = native.authority.sessions[ref.session_id].route
            assert row["principal_id"] == f"automation:{route}"
            assert row["admission_id"] == receipt["admission_id"] == result["admission_id"]
            assert row["request_id"] == f"bot:{key}" and row["outcome"] is None
            assert row["status"] == "queued" and row["payload"]["text"] == message
            automation = row["payload"]["local_automation_v1"]
            assert automation["route"] == route and automation["turn_author"] == author
            event = restore_local_automation(native.authority, ref, row)
            assert event.internal and event.text == message and event.message_id == f"bot:{key}"
            assert event.metadata["turn_author"] == author
            assert event.metadata["gateway_session_id"] == ref.session_id

            assert native.scheduled == [ref] and sender_snapshot(sender_db) == before
            with native.db._read_ctx() as conn:
                assert [r[0] for r in conn.execute("SELECT id FROM sessions")] == [ref.session_id]
                assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
                assert [
                    r[0] for r in conn.execute("SELECT admission_id FROM session_admissions")
                ] == [row["admission_id"]]
            assert not native.authority.events and not native.tickets.outstanding()

        run_native_async(scenario())
