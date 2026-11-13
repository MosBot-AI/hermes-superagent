"""Manual acceptance of an in-flight native Bot reply across Gateway process loss."""

import asyncio
import json
import os

import pytest
from native_gateway_fixture import crashable_gateway_daemon, gateway_daemon
from native_profile_cli_fixture import retained_host_client
from test_native_bot_push_reply import (
    INPUT,
    PROMPT,
    SENDER_ACK,
    admissions,
    gateway_dial,
    is_completion_event,
    local_reply_fixture,
    owned_waiter,
    sender_messages,
    start_delivery,
)


async def lose_owner(endpoint, host, home, scout, model, crash):
    from tools.bot_live_delivery import read_delivery_result

    with gateway_dial(home, endpoint) as owner_pid:
        async with asyncio.timeout(40), retained_host_client(home, endpoint) as client:
            delivery = await start_delivery(client, home, scout, model)
            waiter = await owned_waiter(host, home.parent, owner_pid)
            record = read_delivery_result(home, delivery.delivery_id)
            assert record["admission_id"] == delivery.receiver_admission["admission_id"]
            assert record["status"] in {"queued", "claimed"} and not record.get("reply")
            checkpoint = json.loads((scout / "processes.json").read_bytes())
            (tracked,) = [item for item in checkpoint if item["session_id"] == delivery.process_id]
            assert not tracked["output_log"]
            assert tracked["pid"] in (waiter.pid, waiter.ppid())
            before = sender_messages(scout, delivery.sender)
            assert before[-1]["content"] == SENDER_ACK
            assert not model.release.is_set() and model.recipient_requests == 1
            crash()
            return delivery, record, before, waiter


async def verify_after_owner_loss(endpoint, home, scout, model, before_loss):
    import psutil
    from agent.turn_failure_copy import AUTOMATION_INTERRUPTED_NOTICE
    from hermes_cli.gateway_client import GatewayRPCError
    from tools.bot_live_delivery import authority_delivery, authority_settle, read_delivery_result

    delivery, before, sender_before, waiter = before_loss
    receiver = delivery.receiver_admission
    receipt_id = receiver["admission_id"]
    target = {"session_id": delivery.target, "admission_id": receipt_id}
    generation = receiver["generation"]
    identity = {
        "id": delivery.delivery_id,
        "profile": "default",
        "message": before["message"],
        "author": before["author"],
        "session_id": delivery.target,
    }
    with gateway_dial(home, endpoint):
        async with asyncio.timeout(38), retained_host_client(home, endpoint) as client:
            resumed = await client.rpc(
                "session.resume", profile="default", session_id=delivery.target
            )
            assert resumed["authority_epoch"] > receiver["owner_epoch"]
            receipt = await client.rpc("prompt.receipt", **target, include_result=True)
            assert receipt["ref"] == {"session_id": delivery.target, "profile_id": str(home)}
            assert (receipt["status"], receipt["outcome"]) == ("terminal", "interrupted"), receipt
            assert not resumed["pending"] and not resumed["running"]
            assert (
                sum(
                    AUTOMATION_INTERRUPTED_NOTICE in str(row["content"])
                    for row in resumed["messages"]
                )
                == 1
            )
            assert not (receipt.get("result") or {}).get("final_response")
            assert receipt["execution_generation"] == generation
            saved = read_delivery_result(home, delivery.delivery_id)
            assert saved["status"] == "ambiguous" and saved["author"] == before["author"]
            assert saved["principal_id"] == before["principal_id"] == f"uid:{os.getuid()}"
            outcome = await asyncio.to_thread(authority_settle, home, identity)
            assert outcome["status"] == "ambiguous"
            assert (
                outcome["admission_id"] == receipt_id
                and outcome["delivery_id"] == delivery.delivery_id
            )
            assert not outcome.get("reply") and not outcome.get("retry_admission_id")
            assert outcome["session_id"] == delivery.target
            delivery_replay = await asyncio.to_thread(authority_delivery, home, identity)
            assert delivery_replay.pop("target_state") == "idle"
            assert delivery_replay == outcome
            with pytest.raises(GatewayRPCError) as refused:
                await asyncio.to_thread(
                    authority_delivery, home, identity | {"message": "Synthetic changed delivery"}
                )
            assert refused.value.data["reason"] == "admission_conflict"

            sender = {"profile": "scout", "session_id": delivery.sender}
            reopened = await client.rpc("session.resume", **sender)
            assert reopened["session_id"] == reopened["stored_session_id"] == delivery.sender
            assert not reopened["pending"] and not reopened["running"]
            (tool_result,) = [row for row in reopened["messages"] if row["role"] == "tool"]
            ack = json.loads(tool_result["content"])
            assert (ack["delivery_id"], ack["process_id"]) == (
                delivery.delivery_id,
                delivery.process_id,
            )
            assert not any(
                row.get("display_kind") == "process_complete" for row in reopened["messages"]
            )
            replay = await client.rpc("prompt.submit", **sender, input_id=INPUT, text=PROMPT)
            assert (replay["admission_id"], replay["status"], replay["outcome"]) == (
                delivery.original,
                "terminal",
                "completed",
            )

            assert (await asyncio.to_thread(authority_settle, home, identity)) == outcome

            # Allow a successor watcher tick after the original waiter has exited.
            async with asyncio.timeout(10):
                while waiter.is_running():
                    try:
                        if waiter.status() == psutil.STATUS_ZOMBIE:
                            break
                    except psutil.NoSuchProcess:
                        break
                    await asyncio.sleep(0.05)
            await asyncio.sleep(6)
            (kept,) = admissions(home, delivery.target)
            assert (
                kept["admission_id"] == receipt_id
                and kept["request_id"] == f"bot:{delivery.delivery_id}"
            )
            assert (kept["status"], kept["outcome"]) == ("terminal", "interrupted")
            assert [row["admission_id"] for row in admissions(scout, delivery.sender)] == [
                delivery.original
            ]
            assert sender_messages(scout, delivery.sender) == sender_before
            while not client.events.empty():
                assert not is_completion_event(client.events.get_nowait(), delivery.sender)
            assert model.recipient_requests == 1 and model.unexpected == 0
            assert sorted(model.turns) == ["ack", "recipient", "send"]


def test_native_inflight_bot_reply_reconciles_after_owner_loss(tmp_path_factory, monkeypatch):
    with local_reply_fixture(tmp_path_factory, monkeypatch) as (host, home, scout, env, model):
        try:
            with crashable_gateway_daemon(host, home, env, "bot-before-loss") as (first, crash):
                before = asyncio.run(lose_owner(first, host, home, scout, model, crash))
        finally:
            model.release.set()
        with gateway_daemon(host, home, env, "bot-after-loss") as successor:
            assert successor.instance_id != first.instance_id
            asyncio.run(verify_after_owner_loss(successor, home, scout, model, before))
