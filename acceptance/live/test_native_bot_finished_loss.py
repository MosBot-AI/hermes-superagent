"""Exercise process loss after Bot waiter persistence but before completion admission."""

import asyncio
import json
from pathlib import Path

from native_gateway_fixture import crashable_gateway_daemon, gateway_daemon
from native_profile_cli_fixture import retained_host_client
from test_native_bot_owner_loss import completed_result_path, verify_no_repeat
from test_native_bot_push_reply import (
    INPUT,
    PROMPT,
    RECEIVER_REPLY,
    admissions,
    gateway_dial,
    local_reply_fixture,
    owned_waiter,
    sender_messages,
    start_delivery,
    verify_recipient,
    wait_for_disconnected_reply,
)


async def read_barrier(path):
    async with asyncio.timeout(18):
        while not path.is_file() or not (value := path.read_text(encoding="utf-8")):
            await asyncio.sleep(0.05)
    return value


async def crash_after_waiter(first, host, home, scout, model, crash, *, phase, recovery):
    root = home.parent
    with gateway_dial(home, first) as owner_pid:
        async with asyncio.timeout(50), retained_host_client(home, first) as client:
            delivery = await start_delivery(client, home, scout, model)
            await owned_waiter(host, root, owner_pid)
            if phase == "admitted":
                (root / "admit-finished-waiter").touch()
        return await commit_crash(first, home, scout, model, crash, delivery, phase, recovery)


async def commit_crash(first, home, scout, model, crash, delivery, phase, recovery):
    root = home.parent
    async with asyncio.timeout(35), retained_host_client(home, first) as client:
        model.release.set()
        assert await read_barrier(root / "finished-waiter") == delivery.process_id
        await verify_recipient(client, home, delivery)
        path = completed_result_path(scout, delivery)
        result = json.loads(path.read_bytes())
        assert result["id"] == delivery.process_id and result["exit_code"] == 0
        assert result["parent_session_id"] == delivery.sender
        assert RECEIVER_REPLY in result["output"] and delivery.delivery_id in result["output"]
        assert path.stat().st_mode & 0o777 == 0o600
        if recovery:
            assert result["notification"]["state"] == "pending"
        if phase == "consumed":
            (root / "consume-finished-waiter").touch()
            observed = json.loads(await read_barrier(root / "consumed-waiter"))
            assert observed["status"] == "exited"
            assert RECEIVER_REPLY in observed["output"]
            assert delivery.delivery_id in observed["output"]
            assert json.loads(path.read_bytes())["notification"]["state"] == "consumed"
        original = [delivery.original]
        if phase == "admitted":
            note, _ = await wait_for_disconnected_reply(
                scout, delivery.sender, delivery.original, delivery.reply_tokens, model
            )
            assert json.loads(note["request_id"]) == [
                "completion",
                delivery.process_id,
                result["started_at"],
            ]
            original.append(note["admission_id"])
            assert json.loads(path.read_bytes())["notification"]["state"] == "pending"
        history = sender_messages(scout, delivery.sender)
        assert sum(row.get("display_kind") == "process_complete" for row in history) == (
            1 if phase == "admitted" else 0
        )
        assert [row["admission_id"] for row in admissions(scout, delivery.sender)] == original
        crash()
        return delivery, history, original, result["started_at"]


async def verify_successor(endpoint, home, scout, model, before, *, recover_note):
    delivery, history, original, started_at = before
    if recover_note:
        note, stored = await wait_for_disconnected_reply(
            scout, delivery.sender, delivery.original, delivery.reply_tokens, model
        )
        assert json.loads(note["request_id"]) == ["completion", delivery.process_id, started_at]
        history = [*history, stored]
        original.append(note["admission_id"])
    with gateway_dial(home, endpoint):
        async with asyncio.timeout(25), retained_host_client(home, endpoint) as client:
            sender = {"profile": "scout", "session_id": delivery.sender}
            reopened = await client.rpc("session.resume", **sender)
            assert reopened["session_id"] == delivery.sender
            replay = await client.rpc("prompt.submit", **sender, input_id=INPUT, text=PROMPT)
            assert (replay["admission_id"], replay["status"], replay["outcome"]) == (
                delivery.original,
                "terminal",
                "completed",
            )
            await verify_recipient(client, home, delivery)
            assert model.recipient_requests == 1 and model.unexpected == 0
    return delivery, history, original


def run_finished_loss(tmp_path_factory, monkeypatch, *, recovery, phase="pending"):
    entrypoint = Path(__file__).with_name("native_bot_finished_loss_daemon.py").resolve()
    with local_reply_fixture(tmp_path_factory, monkeypatch) as (host, home, scout, env, model):
        try:
            with crashable_gateway_daemon(
                host, home, env, "bot-finished-before-loss", entrypoint=entrypoint
            ) as (first, crash):
                before = asyncio.run(
                    crash_after_waiter(
                        first, host, home, scout, model, crash, phase=phase, recovery=recovery
                    )
                )
        finally:
            model.release.set()
        with gateway_daemon(host, home, env, "bot-finished-successor") as successor:
            assert successor.instance_id != first.instance_id
            observed = asyncio.run(
                verify_successor(
                    successor,
                    home,
                    scout,
                    model,
                    before,
                    recover_note=recovery and phase == "pending",
                )
            )
            asyncio.run(verify_no_repeat(successor, home, scout, model, observed))
        if recovery:
            with gateway_daemon(host, home, env, "bot-finished-restarted") as restarted:
                assert restarted.instance_id not in (first.instance_id, successor.instance_id)
                asyncio.run(verify_no_repeat(restarted, home, scout, model, observed))
            result = json.loads(completed_result_path(scout, before[0]).read_bytes())
            assert result["notification"]["state"] == (
                "consumed" if phase == "consumed" else "handled"
            )


def test_native_finished_bot_reply_needs_sender_recovery(tmp_path_factory, monkeypatch):
    run_finished_loss(tmp_path_factory, monkeypatch, recovery=False)


def test_proposed_finished_bot_sender_recovers_after_owner_loss(tmp_path_factory, monkeypatch):
    run_finished_loss(tmp_path_factory, monkeypatch, recovery=True)


def test_proposed_consumed_bot_result_stays_consumed_after_owner_loss(
    tmp_path_factory, monkeypatch
):
    run_finished_loss(tmp_path_factory, monkeypatch, recovery=True, phase="consumed")


def test_proposed_admitted_bot_completion_is_not_duplicated(tmp_path_factory, monkeypatch):
    run_finished_loss(tmp_path_factory, monkeypatch, recovery=True, phase="admitted")
