"""Exercise process loss after Bot waiter persistence but before completion admission."""

import asyncio
import json
from pathlib import Path

from native_gateway_fixture import (
    crashable_gateway_daemon,
    gateway_daemon,
    restartable_gateway_daemon,
)
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


async def finish_waiter(first, host, home, scout, model, *, phase, recovery):
    root = home.parent
    with gateway_dial(home, first) as owner_pid:
        async with asyncio.timeout(50), retained_host_client(home, first) as client:
            delivery = await start_delivery(client, home, scout, model)
            await owned_waiter(host, root, owner_pid)
            if phase in {"admitted", "write-failed-admitted"}:
                (root / "admit-finished-waiter").touch()
            if phase.startswith("write-failed"):
                checkpoint = json.loads((scout / "processes.json").read_bytes())
                (tracked,) = [row for row in checkpoint if row["session_id"] == delivery.process_id]
                assert tracked["notify_on_complete"] is True
                (root / "fail-finished-result").write_text(delivery.process_id, encoding="ascii")
                if phase == "write-failed-combined":
                    (root / "checkpoint-before-fault").write_bytes(
                        (scout / "processes.json").read_bytes()
                    )
                    (root / "fail-bot-checkpoint").touch(mode=0o600)
        return await observe_finished(first, home, scout, model, delivery, phase, recovery)


async def observe_finished(first, home, scout, model, delivery, phase, recovery):
    root = home.parent
    async with asyncio.timeout(35), retained_host_client(home, first) as client:
        model.release.set()
        process_id, started_at = json.loads(await read_barrier(root / "finished-waiter"))
        assert process_id == delivery.process_id
        await verify_recipient(client, home, delivery)
        path = completed_result_path(scout, delivery)
        failed_write = phase.startswith("write-failed")
        consumed = phase in {"consumed", "write-failed-consumed"}
        admitted = phase in {"admitted", "write-failed-admitted"}
        if failed_write:
            assert (root / "finished-result-write-failed").is_file()
            assert not path.exists()
            checkpoint = json.loads((scout / "processes.json").read_bytes())
            if phase == "write-failed-combined":
                assert (root / "bot-checkpoint-write-failed").is_file()
                assert (scout / "processes.json").read_bytes() == (
                    root / "checkpoint-before-fault"
                ).read_bytes()
            (handoff,) = [row for row in checkpoint if row["session_id"] == process_id]
            assert handoff["started_at"] == started_at
            assert handoff["parent_session_id"] == delivery.sender
            assert handoff["watcher_platform"] == "local" and handoff["notify_on_complete"] is True
            output = scout / "logs" / "process-output" / f"{process_id}.log"
            assert handoff["output_log"] == str(output)
            content = output.read_text(encoding="utf-8")
            assert RECEIVER_REPLY in content and delivery.delivery_id in content
            assert output.with_suffix(".exit").read_text(encoding="utf-8").strip() == "0"
        else:
            result = json.loads(path.read_bytes())
            assert (result["id"], result["started_at"], result["exit_code"]) == (
                process_id,
                started_at,
                0,
            )
            assert result["parent_session_id"] == delivery.sender
            assert RECEIVER_REPLY in result["output"] and delivery.delivery_id in result["output"]
            assert path.stat().st_mode & 0o777 == 0o600
            if recovery:
                assert result["notification"]["state"] == "pending"
        if consumed:
            (root / "consume-finished-waiter").touch()
            observed = json.loads(await read_barrier(root / "consumed-waiter"))
            assert observed["status"] == "exited"
            assert RECEIVER_REPLY in observed["output"]
            assert delivery.delivery_id in observed["output"]
            if failed_write:
                assert not path.exists()
                checkpoint = json.loads((scout / "processes.json").read_bytes())
                (handoff,) = [row for row in checkpoint if row["session_id"] == process_id]
                assert handoff["completion_consumed"] is True
            else:
                assert json.loads(path.read_bytes())["notification"]["state"] == "consumed"
        original = [delivery.original]
        if admitted:
            note, _ = await wait_for_disconnected_reply(
                scout, delivery.sender, delivery.original, delivery.reply_tokens, model
            )
            assert json.loads(note["request_id"]) == [
                "completion",
                delivery.process_id,
                started_at,
            ]
            original.append(note["admission_id"])
            if not failed_write:
                assert json.loads(path.read_bytes())["notification"]["state"] == "pending"
        history = sender_messages(scout, delivery.sender)
        assert sum(row.get("display_kind") == "process_complete" for row in history) == (
            1 if admitted else 0
        )
        assert [row["admission_id"] for row in admissions(scout, delivery.sender)] == original
        return delivery, history, original, started_at


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


def run_finished_loss(tmp_path_factory, monkeypatch, *, recovery, phase="pending", restart=False):
    entrypoint = Path(__file__).with_name("native_bot_finished_loss_daemon.py").resolve()
    launch = restartable_gateway_daemon if restart else crashable_gateway_daemon
    with local_reply_fixture(tmp_path_factory, monkeypatch) as (host, home, scout, env, model):
        try:
            with launch(host, home, env, "bot-finished-first", entrypoint=entrypoint) as (
                first,
                exit_owner,
            ):
                before = asyncio.run(
                    finish_waiter(first, host, home, scout, model, phase=phase, recovery=recovery)
                )
                exit_owner()
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
                    recover_note=recovery
                    and phase in {"pending", "write-failed", "write-failed-combined"},
                )
            )
            asyncio.run(verify_no_repeat(successor, home, scout, model, observed))
        if recovery:
            with gateway_daemon(host, home, env, "bot-finished-restarted") as restarted:
                assert restarted.instance_id not in (first.instance_id, successor.instance_id)
                asyncio.run(verify_no_repeat(restarted, home, scout, model, observed))
            path = completed_result_path(scout, before[0])
            result = json.loads(path.read_bytes())
            assert (result["id"], result["parent_session_id"], result["started_at"]) == (
                before[0].process_id,
                before[0].sender,
                before[3],
            )
            assert result["notification"]["state"] == (
                "consumed" if phase in {"consumed", "write-failed-consumed"} else "handled"
            )
            if phase.startswith("write-failed"):
                checkpoint = json.loads((scout / "processes.json").read_bytes())
                assert all(row["session_id"] != before[0].process_id for row in checkpoint)


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


def test_native_planned_restart_drops_pending_sender_notification(tmp_path_factory, monkeypatch):
    run_finished_loss(tmp_path_factory, monkeypatch, recovery=False, restart=True)


def test_proposed_planned_restart_recovers_pending_sender_notification(
    tmp_path_factory, monkeypatch
):
    run_finished_loss(tmp_path_factory, monkeypatch, recovery=True, restart=True)


def test_proposed_failed_result_write_recovers_pending_sender_notification(
    tmp_path_factory, monkeypatch
):
    run_finished_loss(
        tmp_path_factory, monkeypatch, recovery=True, phase="write-failed", restart=True
    )


def test_proposed_failed_result_write_preserves_consumption(tmp_path_factory, monkeypatch):
    run_finished_loss(
        tmp_path_factory, monkeypatch, recovery=True, phase="write-failed-consumed", restart=True
    )


def test_proposed_combined_write_failure_recovers_from_previous_checkpoint(
    tmp_path_factory, monkeypatch
):
    run_finished_loss(
        tmp_path_factory, monkeypatch, recovery=True, phase="write-failed-combined", restart=True
    )


def test_proposed_failed_result_write_does_not_repeat_admission(tmp_path_factory, monkeypatch):
    run_finished_loss(
        tmp_path_factory, monkeypatch, recovery=True, phase="write-failed-admitted", restart=True
    )
