"""Manual evidence for a named managed worker interrupted by its owner's loss."""

import asyncio
from contextlib import contextmanager, suppress

import pytest
from native_gateway_fixture import crashable_gateway_daemon, gateway_daemon
from test_native_managed_worker import (
    INPUT,
    MODEL,
    REPLY,
    TEXT,
    admission_rows,
    managed_children,
    managed_fixture,
    query,
    scout_connection,
    sibling_snapshot,
    worker_rows,
)

FOLLOWER_INPUT = "fixture-follower-input"
FOLLOWER_TEXT = "Synthetic managed follower turn"
SUCCESSOR_LABEL = "worker-after-loss"


def worker_running(worker):
    import psutil

    with suppress(psutil.NoSuchProcess):
        # An orphan may be a zombie until the private PID namespace's init reaps it.
        return worker.is_running() and worker.status() != psutil.STATUS_ZOMBIE
    return False


async def wait_worker_exit(worker):
    async with asyncio.timeout(15):
        while worker_running(worker):
            await asyncio.sleep(0.05)


@contextmanager
def worker_custody(owner):
    import psutil

    owner_process = psutil.Process(owner)
    children = []
    try:
        yield children
    finally:
        with suppress(psutil.NoSuchProcess):
            if owner_process.is_running():
                children.extend(
                    worker for worker in managed_children(owner) if worker not in children
                )
        for worker in children:
            with suppress(psutil.NoSuchProcess):
                if worker_running(worker):
                    worker.kill()  # The psutil handle checks process birth before signaling.
                    asyncio.run(wait_worker_exit(worker))


def capture_worker(fixture, owner, children):
    (child,) = managed_children(owner)
    children.append(child)
    assert child.ppid() == owner and worker_running(child)
    assert (fixture.root / f"socket-guard-{child.pid}").is_file()
    return child


async def crash_during_turn(fixture, endpoint, owner, crash, children):
    from gateway.owner_identity import host_owner_subject
    from hermes_cli.gateway_client import connect_gateway

    scout, model = fixture.scout, fixture.model
    async with asyncio.timeout(37), connect_gateway(endpoint=endpoint) as client:
        created = await client.rpc(
            "session.create",
            request_id="fixture-managed-launch",
            source="cli",
            title="Bot Chat",
            hidden=True,
            cwd=str(scout),
            model=MODEL,
            provider="custom",
            base_url=fixture.url,
            toolsets=[],
            ignore_rules=True,
            _timeout=10,
        )
        sid = created["session_id"]
        admitted = await client.rpc(
            "prompt.submit", session_id=sid, input_id=INPUT, text=TEXT, _timeout=8
        )
        assert await asyncio.to_thread(model.observed.wait, 15), "No held original model request"
        child = capture_worker(fixture, owner, children)
        (first,) = admission_rows(scout)
        (physical,) = worker_rows(scout)
        assert first[:3] == (admitted["admission_id"], sid, host_owner_subject())
        assert first[5:] == ("started", None, INPUT)
        assert physical[:6] == (
            "admission-worker:" + first[0],
            sid,
            "compute",
            *first[3:5],
            "running",
        )
        assert query(scout, "SELECT epoch FROM runtime_epoch") == [(first[3],)]
        submitted = await client.rpc(
            "prompt.submit", session_id=sid, input_id=FOLLOWER_INPUT, text=FOLLOWER_TEXT, _timeout=6
        )
        assert submitted["status"] == "queued"
        first_after_queue, follower = admission_rows(scout)
        assert first_after_queue == first
        assert follower[:3] == (submitted["admission_id"], sid, host_owner_subject())
        assert follower[5:] == ("queued", None, FOLLOWER_INPUT)
        assert model.turns == [TEXT] and model.unexpected == 0 and not model.release.is_set()
        assert child.ppid() == owner and worker_running(child)
        crash()  # Keep the normal native viewer attached until the verified owner has died.

    await wait_worker_exit(child)
    assert model.unexpected == 0 and not model.release.is_set()
    model.release.set()
    return first, follower, physical


async def verify_recovery(fixture, endpoint, owner, before_crash, children):
    from hermes_cli.gateway_client import GatewayRPCError, connect_gateway

    scout, model = fixture.scout, fixture.model
    first, follower, physical = before_crash
    aid, sid, _, old_epoch, generation = first[:5]
    follower_id = follower[0]
    params = {"session_id": sid, "admission_id": aid}
    named_ref = {"session_id": sid, "profile_id": str(scout)}
    unknown = first[:5] + ("unknown", None, INPUT)
    async with asyncio.timeout(55), connect_gateway(endpoint=endpoint) as client:
        assert admission_rows(scout) == [unknown, follower]
        (worker_unknown,) = worker_rows(scout)
        assert worker_unknown[:6] == physical[:5] + ("unknown",)
        [(epoch,)] = query(scout, "SELECT epoch FROM runtime_epoch")
        assert epoch > old_epoch

        resumed = await client.rpc("session.resume", session_id=sid, _timeout=8)
        assert resumed["session_id"] == sid
        assert [(row["admission_id"], row["status"]) for row in resumed["pending"]] == [
            (aid, "unknown"),
            (follower_id, "queued"),
        ]
        receipt = await client.rpc("prompt.receipt", **params, include_result=True, _timeout=6)
        assert receipt["admission_id"] == aid and receipt["ref"] == named_ref
        assert (receipt["status"], receipt["outcome"]) == ("unknown", None)
        assert receipt.get("result") is None
        assert (receipt["authority_epoch"], receipt["execution_generation"]) == (
            old_epoch,
            generation,
        )
        log = fixture.root / f"{SUCCESSOR_LABEL}.log"
        pause = f"Session {sid} paused: unknown_execution".encode()
        prior_pauses = log.read_bytes().count(pause)
        replay = await client.rpc(
            "prompt.submit", session_id=sid, input_id=INPUT, text=TEXT, _timeout=6
        )
        assert (replay["admission_id"], replay["status"]) == (aid, "unknown")
        # An idempotent submit still schedules a drain. Wait for its fixed private
        # pause marker before acknowledgment so that this tests serialized recovery.
        async with asyncio.timeout(8):
            while log.read_bytes().count(pause) <= prior_pauses:
                await asyncio.sleep(0.05)

        with pytest.raises(GatewayRPCError) as refused:
            await client.rpc(
                "prompt.resolve_unknown", **params, execution_generation=generation + 1, _timeout=6
            )
        assert (refused.value.code, refused.value.data.get("reason")) == (4001, "stale_generation")
        assert admission_rows(scout) == [unknown, follower] and worker_rows(scout) == [
            worker_unknown
        ]
        assert model.turns == [TEXT] and model.unexpected == 0

        resolved = await client.rpc(
            "prompt.resolve_unknown", **params, execution_generation=generation, _timeout=6
        )
        assert resolved["admission_id"] == aid and resolved["ref"] == named_ref
        assert (resolved["status"], resolved["outcome"]) == ("terminal", "interrupted")
        interrupted = first[:5] + ("terminal", "interrupted", INPUT)

        try:
            assert await asyncio.to_thread(model.follower_observed.wait, 15), (
                "Acknowledgment did not release the FIFO to the scripted model"
            )
            child = capture_worker(fixture, owner, children)
            current_first, started = admission_rows(scout)
            assert current_first == interrupted
            assert started[:4] == follower[:3] + (epoch,)
            assert started[5:] == ("started", None, FOLLOWER_INPUT)
            workers = {row[0]: row for row in worker_rows(scout)}
            assert workers[physical[0]][:6] == physical[:5] + ("terminal",)
            follower_worker_id = "admission-worker:" + follower_id
            assert workers.keys() == {physical[0], follower_worker_id}
            assert workers[follower_worker_id][:6] == (
                follower_worker_id,
                sid,
                "compute",
                epoch,
                started[4],
                "running",
            )
        finally:
            model.follower_release.set()

        settled = [interrupted, started[:5] + ("terminal", "completed", FOLLOWER_INPUT)]
        async with asyncio.timeout(15):
            while admission_rows(scout) != settled:
                await asyncio.sleep(0.05)
        final_workers = {row[0]: row for row in worker_rows(scout)}
        assert final_workers.keys() == workers.keys()
        assert final_workers[physical[0]] == workers[physical[0]]
        assert final_workers[follower_worker_id][:6] == workers[follower_worker_id][:5] + (
            "terminal",
        )
        follower_receipt = await client.rpc(
            "prompt.receipt",
            session_id=sid,
            admission_id=follower_id,
            include_result=True,
            _timeout=6,
        )
        assert (
            follower_receipt["ref"] == named_ref and follower_receipt["admission_id"] == follower_id
        )
        assert (follower_receipt["status"], follower_receipt["outcome"]) == (
            "terminal",
            "completed",
        )
        assert (
            follower_receipt["authority_epoch"],
            follower_receipt["execution_generation"],
        ) == started[3:5]
        assert follower_receipt["result"]["final_response"] == REPLY
        repeated = await client.rpc(
            "prompt.resolve_unknown", **params, execution_generation=generation, _timeout=6
        )
        assert repeated == resolved and admission_rows(scout) == settled
        assert model.turns == [TEXT, FOLLOWER_TEXT] and model.unexpected == 0
        await wait_worker_exit(child)


def test_native_named_managed_worker_restart_requires_exact_unknown_resolution(
    tmp_path_factory, monkeypatch
):
    with managed_fixture(tmp_path_factory, monkeypatch, follower=FOLLOWER_TEXT) as fixture:
        with (
            crashable_gateway_daemon(
                fixture.host, fixture.home, fixture.child_env, "worker-before-loss"
            ) as (first, crash),
            scout_connection(fixture, first) as (endpoint, owner),
            worker_custody(owner) as children,
        ):
            before = asyncio.run(crash_during_turn(fixture, endpoint, owner, crash, children))

        with (
            gateway_daemon(
                fixture.host, fixture.home, fixture.child_env, SUCCESSOR_LABEL
            ) as second,
            scout_connection(fixture, second) as (endpoint, successor),
            worker_custody(successor) as children,
        ):
            assert second.instance_id != first.instance_id and successor != owner
            asyncio.run(verify_recovery(fixture, endpoint, successor, before, children))

        assert all(
            sibling_snapshot(path) == snapshot for path, snapshot in fixture.controls.items()
        )
