"""Manual evidence for stopping a named managed worker during native clarification."""

import asyncio
import json
from contextlib import suppress

import pytest
from native_gateway_fixture import gateway_daemon
from test_native_managed_worker import (
    MODEL,
    ScriptedModel,
    admission_rows,
    managed_fixture,
    scout_connection,
    sibling_snapshot,
    worker_rows,
)
from test_native_managed_worker_restart import capture_worker, wait_worker_exit, worker_custody

QUESTION = "Choose a synthetic fixture color"
CHOICES = ["Amber", "Indigo"]
ORIGINAL = "Synthetic fixture question"
FOLLOWER = "Synthetic queued successor"
REPLY = "Synthetic successor completed"
ORIGINAL_INPUT = "fixture-clarify-input"
FOLLOWER_INPUT = "fixture-successor-input"


class ClarifyModel(ScriptedModel):
    def do_POST(self):
        body = self.completion_request()
        if body is None:
            return
        tools = [row.get("function", {}).get("name") for row in body.get("tools", [])]
        users = [
            row.get("content") for row in body.get("messages", []) if row.get("role") == "user"
        ]
        turn = users[-1] if users else None
        if (
            self.path != "/v1/chat/completions"
            or self.headers.get("Authorization") != "Bearer no-key-required"
            or body.get("model") != MODEL
            or tools != ["clarify"]
            or turn not in {ORIGINAL, FOLLOWER}
            or turn in self.server.turns
        ):
            self.server.unexpected += 1
            self.send_error(400)
            return
        self.server.turns.append(turn)
        if turn == ORIGINAL:
            self.send_completion(
                body,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "fixture-clarify",
                            "type": "function",
                            "function": {
                                "name": "clarify",
                                "arguments": json.dumps(
                                    {"questions": [{"question": QUESTION, "choices": CHOICES}]}
                                ),
                            },
                        },
                    ],
                },
            )
            return

        self.server.follower_observed.set()
        if not self.server.follower_release.wait(20):
            self.server.unexpected += 1
            with suppress(BrokenPipeError, ConnectionResetError):
                self.send_error(500)
            return
        self.send_completion(body, {"role": "assistant", "content": REPLY})


async def clarify_event(client, sid, event_type):
    async with asyncio.timeout(12):
        while True:
            frame = await client.events.get()
            assert isinstance(frame, dict), "Native Gateway event stream closed"
            params = frame.get("params", {})
            if (
                frame.get("method") == "event"
                and params.get("session_id") == sid
                and params.get("type") == event_type
            ):
                return params["payload"]


async def assert_stale_stop(client, sid, generation):
    from hermes_cli.gateway_client import GatewayRPCError

    with pytest.raises(GatewayRPCError) as refused:
        await client.rpc(
            "session.interrupt", session_id=sid, execution_generation=generation, _timeout=5
        )
    assert (refused.value.code, refused.value.data.get("reason")) == (4001, "stale_generation")


async def verify_stop(fixture, endpoint, owner, children):
    from gateway.status import get_process_start_time
    from hermes_cli.gateway_client import connect_gateway
    from hermes_cli.gateway_runtime_discovery import query_identify

    birth = get_process_start_time(owner)
    assert birth is not None
    scout, model = fixture.scout, fixture.model
    async with asyncio.timeout(65), connect_gateway(endpoint=endpoint) as client:
        opened = await client.rpc(
            "session.create",
            request_id="fixture-clarify-launch",
            source="cli",
            title="Bot Chat",
            hidden=True,
            cwd=str(scout),
            model=MODEL,
            provider="custom",
            base_url=fixture.url,
            toolsets=["clarify"],
            ignore_rules=True,
            _timeout=8,
        )
        sid = opened["session_id"]
        ref = {"profile_id": str(scout), "session_id": sid}
        first = await client.rpc(
            "prompt.submit", session_id=sid, input_id=ORIGINAL_INPUT, text=ORIGINAL, _timeout=6
        )
        aid = first["admission_id"]
        prompt = await clarify_event(client, sid, "clarify.request")
        assert prompt["kind"] == "clarify" and prompt["question"] == QUESTION
        assert prompt["choices"] == ["Amber (Recommended)", "Indigo"]
        assert prompt["multi_select"] is False
        generation = prompt["execution_generation"]
        original = capture_worker(fixture, owner, children)
        (active,) = admission_rows(scout)
        (worker,) = worker_rows(scout)
        assert (active[0], active[1], active[4], *active[5:]) == (
            aid,
            sid,
            generation,
            "started",
            None,
            ORIGINAL_INPUT,
        )
        original_execution = "admission-worker:" + aid
        assert worker[:6] == (original_execution, sid, "compute", active[3], generation, "running")

        follower = await client.rpc(
            "prompt.submit", session_id=sid, input_id=FOLLOWER_INPUT, text=FOLLOWER, _timeout=6
        )
        fid = follower["admission_id"]
        assert follower["status"] == "queued"
        original_row, queued = admission_rows(scout)
        assert original_row == active and queued[:3] == (fid, sid, active[2])
        assert queued[5:] == ("queued", None, FOLLOWER_INPUT)

        await assert_stale_stop(client, sid, generation + 1)
        held = await client.rpc("session.resume", session_id=sid, _timeout=5)
        assert held["prompts"] == [prompt]
        assert admission_rows(scout) == [active, queued] and worker_rows(scout) == [worker]
        assert (model.turns, model.unexpected) == ([ORIGINAL], 0)

        handle = await client.rpc(
            "session.interrupt", session_id=sid, execution_generation=generation, _timeout=5
        )
        assert handle["ref"] == ref and handle["execution_generation"] == generation
        assert (handle["instance_id"], handle["authority_epoch"]) == (
            endpoint.instance_id,
            active[3],
        )
        interrupted = active[:5] + ("terminal", "interrupted", ORIGINAL_INPUT)
        follower_execution = "admission-worker:" + fid
        try:
            assert await asyncio.to_thread(model.follower_observed.wait, 15), (
                "Native Stop did not release the queued follower"
            )
            successor = capture_worker(fixture, owner, children)
            assert successor.pid != original.pid
            first_terminal, following = admission_rows(scout)
            assert first_terminal == interrupted and following[:4] == queued[:3] + (active[3],)
            assert following[4] > generation and following[5:] == ("started", None, FOLLOWER_INPUT)
            executions = {row[0]: row for row in worker_rows(scout)}
            assert executions.keys() == {original_execution, follower_execution}
            assert executions[original_execution][:6] == worker[:5] + ("terminal",)
            assert executions[follower_execution][:6] == (
                follower_execution,
                sid,
                "compute",
                *following[3:5],
                "running",
            )

            await assert_stale_stop(client, sid, generation)
            assert successor.is_running() and successor.ppid() == owner
            assert admission_rows(scout) == [interrupted, following]
            assert {row[0]: row for row in worker_rows(scout)} == executions

            settled_prompt = await clarify_event(client, sid, "clarify.settled")
            assert settled_prompt == {
                "prompt_id": prompt["prompt_id"],
                "execution_generation": generation,
            }
            assert (await client.rpc("session.resume", session_id=sid, _timeout=5))["prompts"] == []
            receipt = await client.rpc(
                "prompt.receipt", session_id=sid, admission_id=aid, include_result=True, _timeout=5
            )
            assert receipt["ref"] == ref and receipt["admission_id"] == aid
            assert (receipt["status"], receipt["outcome"]) == ("terminal", "interrupted")
            assert (receipt["authority_epoch"], receipt["execution_generation"]) == active[3:5]
            assert receipt["result"]["interrupted"] is True
            assert receipt["result"]["completed"] is False
            assert (model.turns, model.unexpected) == ([ORIGINAL, FOLLOWER], 0)
        finally:
            model.follower_release.set()

        completed = following[:5] + ("terminal", "completed", FOLLOWER_INPUT)
        async with asyncio.timeout(15):
            while admission_rows(scout) != [interrupted, completed]:
                await asyncio.sleep(0.05)
        final_executions = {row[0]: row for row in worker_rows(scout)}
        assert final_executions.keys() == executions.keys()
        assert final_executions[original_execution] == executions[original_execution]
        assert final_executions[follower_execution][:6] == executions[follower_execution][:5] + (
            "terminal",
        )
        final = await client.rpc(
            "prompt.receipt", session_id=sid, admission_id=fid, include_result=True, _timeout=5
        )
        assert final["ref"] == ref and final["admission_id"] == fid
        assert (final["status"], final["outcome"]) == ("terminal", "completed")
        assert (final["authority_epoch"], final["execution_generation"]) == completed[3:5]
        assert final["result"]["final_response"] == REPLY

        retry = await client.rpc(
            "prompt.submit", session_id=sid, input_id=ORIGINAL_INPUT, text=ORIGINAL, _timeout=6
        )
        assert (retry["admission_id"], retry["status"], retry["outcome"]) == (
            aid,
            "terminal",
            "interrupted",
        )
        assert (
            await client.rpc(
                "prompt.receipt", session_id=sid, admission_id=aid, include_result=True, _timeout=5
            )
            == receipt
        )
        assert admission_rows(scout) == [interrupted, completed]
        assert {row[0]: row for row in worker_rows(scout)} == final_executions
        assert (model.turns, model.unexpected) == ([ORIGINAL, FOLLOWER], 0)
        assert all(sibling_snapshot(path) == before for path, before in fixture.controls.items())
        current = query_identify(fixture.home, timeout=2)
        assert (current["pid"], current["instance_id"], get_process_start_time(owner)) == (
            owner,
            endpoint.instance_id,
            birth,
        )
        await wait_worker_exit(original)
        await wait_worker_exit(successor)


def test_native_named_worker_stop_during_clarify_fences_the_follower(tmp_path_factory, monkeypatch):
    with (
        managed_fixture(tmp_path_factory, monkeypatch, handler=ClarifyModel) as fixture,
        gateway_daemon(fixture.host, fixture.home, fixture.child_env, "clarify-stop") as gateway,
        scout_connection(fixture, gateway) as (endpoint, owner),
        worker_custody(owner) as children,
    ):
        asyncio.run(verify_stop(fixture, endpoint, owner, children))
