"""Manual acceptance of native Bot replies across Gateway process loss."""

import asyncio
import json
import os
import signal
import time
from contextlib import contextmanager, nullcontext

import pytest
from native_gateway_fixture import (
    crashable_gateway_daemon,
    gateway_daemon,
    restartable_gateway_daemon,
)
from native_profile_cli_fixture import retained_host_client
from test_native_bot_push_reply import (
    INPUT,
    PROMPT,
    RECEIVER_REPLY,
    SENDER_ACK,
    admissions,
    completion_card,
    gateway_dial,
    is_completion_event,
    local_reply_fixture,
    owned_waiter,
    sender_messages,
    start_delivery,
    verify_recipient,
    wait_for_disconnected_reply,
)


@contextmanager
def stopped_waiter(waiter):
    # The waiter was found under the owned Gateway and passed its socket audit.
    # Keep the PID descriptor open across the crash so PID reuse cannot redirect a signal.
    pidfd = os.pidfd_open(waiter.pid)
    try:
        assert waiter.is_running()
        signal.pidfd_send_signal(pidfd, signal.SIGSTOP)
        try:
            yield
        finally:
            try:
                signal.pidfd_send_signal(pidfd, signal.SIGCONT)
            except ProcessLookupError:
                pass
    finally:
        os.close(pidfd)


async def wait_until_stopped(waiter):
    import psutil

    async with asyncio.timeout(4):
        while waiter.status() != psutil.STATUS_STOPPED:
            await asyncio.sleep(0.05)


async def settle_before_loss(client, home, scout, delivery, model, waiter, crash):
    from tools.bot_live_delivery import read_delivery_result

    with stopped_waiter(waiter):
        await wait_until_stopped(waiter)
        model.release.set()
        async with asyncio.timeout(12):
            while True:
                receipt = read_delivery_result(home, delivery.delivery_id)
                if receipt["status"] == "settled":
                    break
                await asyncio.sleep(0.05)
        await verify_recipient(client, home, delivery)
        assert receipt["status"] == "settled" and receipt["reply"] == RECEIVER_REPLY
        assert len(admissions(scout, delivery.sender)) == 1
        assert not any(
            row.get("display_kind") == "process_complete"
            for row in sender_messages(scout, delivery.sender)
        )
        await wait_until_stopped(waiter)
        assert not completed_result_path(scout, delivery).exists()
        crash()
        return receipt


def completed_result_path(scout, delivery):
    return scout / "logs" / "process-results" / f"{delivery.process_id}.json"


async def lose_owner(
    endpoint,
    host,
    home,
    scout,
    model,
    exit_owner,
    *,
    settled_reply,
    recovery,
    restart=False,
    stop_after_drain=False,
):
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
            if recovery:
                output = scout / "logs" / "process-output" / f"{delivery.process_id}.log"
                assert tracked["output_log"] == str(output)
                assert output.stat().st_mode & 0o777 == 0o600
                assert (
                    tracked["notify_on_complete"] is True and tracked["watcher_platform"] == "local"
                )
            else:
                assert not tracked["output_log"]
            assert tracked["pid"] in (waiter.pid, waiter.ppid())
            before = sender_messages(scout, delivery.sender)
            assert before[-1]["content"] == SENDER_ACK
            assert not model.release.is_set() and model.recipient_requests == 1
            if restart and settled_reply:

                def release_during_restart():
                    from gateway.status import read_runtime_status

                    deadline = time.monotonic() + 6
                    while time.monotonic() < deadline:
                        state = read_runtime_status(home / "gateway_state.json") or {}
                        if state.get("gateway_state") == "draining":
                            assert waiter.is_running() and not model.release.is_set()
                            model.release.set()
                            return
                        time.sleep(0.05)
                    pytest.fail("Gateway did not enter the restart wait")

                with stopped_waiter(waiter) if stop_after_drain else nullcontext():
                    if stop_after_drain:
                        await wait_until_stopped(waiter)
                    exit_owner(after_signal=release_during_restart)
            elif restart:
                # Keep the held waiter from racing the native shutdown sweep.
                # Its recipient is still waiting on the synthetic model response.
                with stopped_waiter(waiter):
                    await wait_until_stopped(waiter)
                    exit_owner()
                    assert not model.release.is_set()
            elif settled_reply:
                record = await settle_before_loss(
                    client, home, scout, delivery, model, waiter, exit_owner
                )
            else:
                exit_owner()
            return delivery, record, before, waiter


async def verify_after_owner_loss(
    endpoint,
    home,
    scout,
    model,
    before_loss,
    *,
    settled_reply,
    recovery,
    restart=False,
    stop_after_drain=False,
    mismatched=False,
):
    import psutil
    from agent.turn_failure_copy import AUTOMATION_INTERRUPTED_NOTICE
    from gateway.session_bot_outcome import OWNER_STOPPED_ERROR
    from hermes_cli.gateway_client import GatewayRPCError
    from tools.bot_failure_reasons import UNKNOWN
    from tools.bot_live_delivery import authority_delivery, authority_settle, read_delivery_result

    delivery, before, sender_before, waiter = before_loss
    receiver = delivery.receiver_admission
    receipt_id = receiver["admission_id"]
    target = {"session_id": delivery.target, "admission_id": receipt_id}
    held_restart = restart and not settled_reply
    expected_status, expected_outcome, expected_reply = (
        ("settled", "completed", RECEIVER_REPLY)
        if settled_reply
        else ("failed" if held_restart else "ambiguous", "interrupted", "")
    )
    identity = {
        "id": delivery.delivery_id,
        "profile": "default",
        "message": before["message"],
        "author": before["author"],
        "session_id": delivery.target,
    }
    with gateway_dial(home, endpoint):
        async with asyncio.timeout(42), retained_host_client(home, endpoint) as client:
            expected_history = sender_before
            expected_admissions = [delivery.original]
            if recovery:
                reply_tokens = (
                    expected_reply or "Do not resend; receipt is retained.",
                    delivery.delivery_id,
                    delivery.process_id,
                )
                if held_restart:
                    reply_tokens = (delivery.process_id, delivery.delivery_id, OWNER_STOPPED_ERROR)
                if mismatched:
                    reply_tokens = (delivery.process_id, "exit code -")
                note, stored = await wait_for_disconnected_reply(
                    scout, delivery.sender, delivery.original, reply_tokens, model
                )
                expected_history = sender_before + [stored]
                expected_admissions.append(note["admission_id"])
                persisted = json.loads(completed_result_path(scout, delivery).read_bytes())
                assert persisted["id"] == delivery.process_id
                assert persisted["parent_session_id"] == delivery.sender
                if held_restart or stop_after_drain:
                    assert persisted["exit_code"] in {-9, -15}
                    assert not persisted["output"].strip()
                    assert not completed_result_path(home, delivery).exists()
                    assert "exit code -" in stored["content"]
                    if held_restart:
                        assert RECEIVER_REPLY not in stored["content"]
                    if mismatched:
                        assert delivery.delivery_id not in stored["content"]
                        assert OWNER_STOPPED_ERROR not in stored["content"]
                    elif held_restart:
                        assert "Do not resend blindly." in stored["content"]
                else:
                    assert persisted["exit_code"] == (0 if settled_reply else 1)
                    assert delivery.delivery_id in persisted["output"]
                    assert (expected_reply or "Do not resend; receipt is retained.") in persisted[
                        "output"
                    ]
                assert json.loads(note["request_id"]) == [
                    "completion",
                    delivery.process_id,
                    persisted["started_at"],
                ]
            resumed = await client.rpc(
                "session.resume", profile="default", session_id=delivery.target
            )
            assert resumed["authority_epoch"] > receiver["owner_epoch"]
            receipt = await client.rpc("prompt.receipt", **target, include_result=True)
            assert receipt["ref"] == {"session_id": delivery.target, "profile_id": str(home)}
            assert (receipt["status"], receipt["outcome"]) == ("terminal", expected_outcome)
            assert not resumed["pending"] and not resumed["running"]
            assert sum(
                AUTOMATION_INTERRUPTED_NOTICE in str(row["content"]) for row in resumed["messages"]
            ) == (0 if settled_reply else 1)
            reported = (receipt.get("result") or {}).get("final_response") or ""
            if held_restart:
                assert reported.startswith("Operation interrupted: waiting for model response (")
                expected_reply = reported
                assert all(row.get("content") != RECEIVER_REPLY for row in resumed["messages"])
            else:
                assert reported == expected_reply
            if settled_reply:
                assert (
                    sum(
                        row["role"] == "assistant" and row["content"] == RECEIVER_REPLY
                        for row in resumed["messages"]
                    )
                    == 1
                )
            assert receipt["execution_generation"] == receiver["generation"]
            saved = read_delivery_result(home, delivery.delivery_id)
            assert saved["status"] == expected_status and saved["author"] == before["author"]
            assert saved.get("reply", "") == expected_reply
            assert saved["principal_id"] == before["principal_id"] == f"uid:{os.getuid()}"
            outcome = await asyncio.to_thread(authority_settle, home, identity)
            assert outcome["status"] == expected_status
            assert (
                outcome["admission_id"] == receipt_id
                and outcome["delivery_id"] == delivery.delivery_id
            )
            assert outcome.get("reply", "") == expected_reply
            assert not outcome.get("retry_admission_id")
            if held_restart:
                assert outcome["reason"] == UNKNOWN and outcome["error"] == OWNER_STOPPED_ERROR
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
            if recovery:
                assert (
                    completion_card(reopened["messages"], reply_tokens)["content"]
                    == stored["content"]
                )
            else:
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
            assert (kept["status"], kept["outcome"]) == ("terminal", expected_outcome)
            result_path = completed_result_path(scout, delivery)
            if restart and not recovery:
                launch_path = completed_result_path(home, delivery)
                paths = [path for path in (result_path, launch_path) if path.is_file()]
                assert paths
                process = json.loads(paths[0].read_bytes())
                assert (process["id"], process["parent_session_id"]) == (
                    delivery.process_id,
                    delivery.sender,
                )
                if held_restart:
                    assert process["exit_code"] in {-9, -15}
                    assert not process["output"].strip()
                elif process["exit_code"] == 0:
                    assert RECEIVER_REPLY in process["output"]
                else:
                    assert process["exit_code"] in {-9, -15}
            else:
                assert result_path.exists() == recovery
            assert [
                row["admission_id"] for row in admissions(scout, delivery.sender)
            ] == expected_admissions
            assert sender_messages(scout, delivery.sender) == expected_history
            while not client.events.empty():
                assert not is_completion_event(client.events.get_nowait(), delivery.sender)
            assert model.recipient_requests == 1 and model.unexpected == 0
            assert sorted(model.turns) == ["ack", "recipient", "send"]
            return delivery, expected_history, expected_admissions


def run_owner_loss(
    tmp_path_factory,
    monkeypatch,
    *,
    settled_reply,
    recovery=False,
    restart=False,
    stop_after_drain=False,
    mismatched=False,
):
    with local_reply_fixture(tmp_path_factory, monkeypatch) as (host, home, scout, env, model):
        launch = restartable_gateway_daemon if restart else crashable_gateway_daemon
        if restart:
            env = env | {
                "HERMES_RESTART_AFTER_TURN_TIMEOUT": "10" if settled_reply else "0",
                "HERMES_RESTART_DRAIN_TIMEOUT": "0",
            }
        try:
            with launch(host, home, env, "bot-before-loss") as (first, exit_owner):
                before = asyncio.run(
                    lose_owner(
                        first,
                        host,
                        home,
                        scout,
                        model,
                        exit_owner,
                        settled_reply=settled_reply,
                        recovery=recovery,
                        restart=restart,
                        stop_after_drain=stop_after_drain,
                    )
                )
        finally:
            model.release.set()
        if stop_after_drain:
            path = completed_result_path(scout, before[0])
            result = json.loads(path.read_bytes()) if path.is_file() else {}
            assert result.get("exit_code") in {-9, -15}
            assert result.get("notification", {}).get("state") == "pending"
        if mismatched:
            path = completed_result_path(scout, before[0])
            result = json.loads(path.read_bytes())
            binding = result["notification"]["bot_reply_receipt"]
            assert binding["target_session"] == before[0].target
            binding["target_session"] = before[0].sender
            path.write_text(json.dumps(result), encoding="utf-8")
        with gateway_daemon(host, home, env, "bot-after-loss") as successor:
            assert successor.instance_id != first.instance_id
            observed = asyncio.run(
                verify_after_owner_loss(
                    successor,
                    home,
                    scout,
                    model,
                    before,
                    settled_reply=settled_reply,
                    recovery=recovery,
                    restart=restart,
                    stop_after_drain=stop_after_drain,
                    mismatched=mismatched,
                )
            )
        if recovery:
            with gateway_daemon(host, home, env, "bot-restarted-again") as restarted:
                assert restarted.instance_id not in (first.instance_id, successor.instance_id)
                asyncio.run(verify_no_repeat(restarted, home, scout, model, observed))


async def verify_no_repeat(endpoint, home, scout, model, observed):
    delivery, expected_history, expected_admissions = observed
    with gateway_dial(home, endpoint):
        async with retained_host_client(home, endpoint) as client:
            resumed = await client.rpc(
                "session.resume", profile="scout", session_id=delivery.sender
            )
            assert resumed["session_id"] == delivery.sender and not resumed["pending"]
            await asyncio.sleep(6)
            assert sender_messages(scout, delivery.sender) == expected_history
            assert [
                row["admission_id"] for row in admissions(scout, delivery.sender)
            ] == expected_admissions
            while not client.events.empty():
                assert not is_completion_event(client.events.get_nowait(), delivery.sender)
            assert model.recipient_requests == 1 and model.unexpected == 0
            assert sorted(model.turns) == ["ack", "recipient", "send"]


def test_native_inflight_bot_reply_reconciles_after_owner_loss(tmp_path_factory, monkeypatch):
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=False)


def test_native_settled_bot_reply_reconciles_after_owner_loss(tmp_path_factory, monkeypatch):
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=True)


def test_proposed_inflight_bot_sender_recovers_after_owner_loss(tmp_path_factory, monkeypatch):
    assert os.environ.get("HERMES_BOT_REVIEW_RECOVERY") == "1"
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=False, recovery=True)


def test_proposed_settled_bot_sender_recovers_after_owner_loss(tmp_path_factory, monkeypatch):
    assert os.environ.get("HERMES_BOT_REVIEW_RECOVERY") == "1"
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=True, recovery=True)


def test_native_held_bot_reply_reconciles_after_planned_restart(tmp_path_factory, monkeypatch):
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=False, restart=True)


def test_native_drained_bot_reply_reconciles_after_planned_restart(tmp_path_factory, monkeypatch):
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=True, restart=True)


def test_proposed_held_bot_reply_reconciles_after_planned_restart(tmp_path_factory, monkeypatch):
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=False, recovery=True, restart=True)


def test_proposed_drained_bot_reply_reconciles_after_planned_restart(tmp_path_factory, monkeypatch):
    run_owner_loss(tmp_path_factory, monkeypatch, settled_reply=True, recovery=True, restart=True)


def test_proposed_killed_waiter_restores_settled_receipt(tmp_path_factory, monkeypatch):
    run_owner_loss(
        tmp_path_factory,
        monkeypatch,
        settled_reply=True,
        recovery=True,
        restart=True,
        stop_after_drain=True,
    )


def test_proposed_killed_waiter_refuses_mismatched_receipt(tmp_path_factory, monkeypatch):
    run_owner_loss(
        tmp_path_factory,
        monkeypatch,
        settled_reply=False,
        recovery=True,
        restart=True,
        mismatched=True,
    )
