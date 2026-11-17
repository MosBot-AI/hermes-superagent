"""Manual canonical browser recovery across the loss of a started admission."""

import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager, closing
from pathlib import Path
from sqlite3 import connect

import pytest
from native_gateway_fixture import crashable_gateway_daemon
from test_native_webapp_signout import (
    PROFILE,
    TOKEN_PATH,
    browser_connection,
    distinct_ports,
    isolated_webapp_host,
    named_webapp_endpoint,
    prepare_install,
    read_private_credential,
    serving_install,
)

HEAD_INPUT = "fixture-lost-head"
TAIL_INPUT = "fixture-paused-tail"


@asynccontextmanager
async def browser_client(home, endpoint):
    from hermes_cli.gateway_client import GatewayClient

    async with asyncio.timeout(40), AsyncExitStack() as stack:
        credential = read_private_credential(home / TOKEN_PATH)
        browser = await browser_connection(stack, endpoint, credential)
        yield await stack.enter_async_context(GatewayClient(browser))


async def canonical_call(client, method, model, **params):
    return model.model_validate(await client.rpc(method, _timeout=6, **params), strict=True)


async def refused(client, method, reason, **params):
    from hermes_cli.gateway_client import GatewayRPCError

    with pytest.raises(GatewayRPCError) as error:
        await client.rpc(method, _timeout=6, **params)
    assert error.value.data.get("reason") == reason
    return error.value.data


async def wait_for_claim(home):
    marker = home.parent / "claimed.json"
    async with asyncio.timeout(10):
        while not marker.is_file():
            await asyncio.sleep(0.05)
    return json.loads(marker.read_bytes())


def create_params(endpoint):
    return {
        "request_id": "fixture-browser-create",
        "source": "cli",
        "cwd": endpoint.profile_id,
        "toolsets": [],
    }


async def describe(client, endpoint):
    from tui_gateway.contracts.canonical import RuntimeDescribeResult

    result = await canonical_call(client, "runtime.describe", RuntimeDescribeResult)
    assert result.instance_id == endpoint.instance_id
    assert result.profile_id == endpoint.profile_id
    assert {"durable-admission-v1", "event-replay-v1", "local-cli-create-v1"}.issubset(
        result.capabilities
    )
    assert "cli" in result.session_create.sources
    assert {"request_id", "source", "cwd", "toolsets"}.issubset(result.session_create.parameters)
    return result


async def receipt(client, sid, aid):
    from tui_gateway.contracts.canonical import PromptReceiptResult

    return await canonical_call(
        client,
        "prompt.receipt",
        PromptReceiptResult,
        session_id=sid,
        admission_id=aid,
        include_result=True,
    )


async def first_owner(home, endpoint):
    from tui_gateway.contracts.canonical_sessions import CanonicalSnapshot, CanonicalSubmitResult

    async with browser_client(home, endpoint) as client:
        identity = await describe(client, endpoint)
        params = create_params(endpoint)
        created = await canonical_call(client, "session.create", CanonicalSnapshot, **params)
        sid = created.session_id
        original = await canonical_call(client, "session.resume", CanonicalSnapshot, session_id=sid)
        assert original.session_id == original.stored_session_id == sid
        assert original.authority_epoch == identity.authority_epoch
        assert original.info.desktop_protocol == "hermes-gateway-v1"
        assert not original.messages and not original.pending and not original.prompts

        replay = await canonical_call(client, "session.create", CanonicalSnapshot, **params)
        assert replay.session_id == replay.stored_session_id == sid
        assert replay.replay_epoch == original.replay_epoch
        error = await refused(
            client, "session.create", "invalid_params", **(params | {"cwd": str(home)})
        )
        assert error.get("field") == "request_id"

        head = (
            await canonical_call(
                client,
                "prompt.submit",
                CanonicalSubmitResult,
                session_id=sid,
                submission_id=HEAD_INPUT,
                text="Synthetic lost turn",
            )
        ).root
        assert head.status == "queued" and head.outcome is None
        assert (head.ref.profile_id, head.ref.session_id) == (endpoint.profile_id, sid)

        claim = await wait_for_claim(home)
        started = await receipt(client, sid, head.admission_id)
        assert started.status == "started" and started.result is None
        assert started.admission_id == claim["admission_id"] == head.admission_id
        assert started.execution_generation == claim["generation"]
        assert started.authority_epoch == identity.authority_epoch

        tail_params = {"session_id": sid, "input_id": TAIL_INPUT, "text": "Synthetic queued turn"}
        tail = (
            await canonical_call(client, "prompt.submit", CanonicalSubmitResult, **tail_params)
        ).root
        assert tail.status == "queued" and tail.sequence == started.sequence + 1
        assert tail.ref == started.ref and tail.admission_id != started.admission_id
        assert (
            await canonical_call(client, "prompt.submit", CanonicalSubmitResult, **tail_params)
        ).root == tail
        await refused(
            client,
            "prompt.submit",
            "admission_conflict",
            **(tail_params | {"text": "Changed turn"}),
        )
        return original, started, tail


async def recover_owner(home, endpoint, original, started, tail):
    from tui_gateway.contracts.canonical import AdmissionStatus
    from tui_gateway.contracts.canonical_sessions import CanonicalEventsResult, CanonicalSnapshot

    sid = original.session_id
    async with browser_client(home, endpoint) as client:
        described = await describe(client, endpoint)
        assert described.authority_epoch > original.authority_epoch

        current = await canonical_call(client, "session.resume", CanonicalSnapshot, session_id=sid)
        assert current.session_id == current.stored_session_id == sid
        assert current.authority_epoch == described.authority_epoch
        assert current.replay_epoch != original.replay_epoch
        assert [(row.admission_id, row.status) for row in current.pending] == [
            (started.admission_id, "unknown"),
            (tail.admission_id, "queued"),
        ]
        assert not current.prompts and not current.messages
        assert (await receipt(client, sid, started.admission_id)).status == "unknown"
        old_stream = await canonical_call(
            client,
            "session.events.since",
            CanonicalEventsResult,
            session_id=sid,
            replay_epoch=original.replay_epoch,
            last_sequence=original.last_sequence,
        )
        assert old_stream.snapshot_required and not old_stream.events
        assert old_stream.replay_epoch == current.replay_epoch
        same_creation = await canonical_call(
            client, "session.create", CanonicalSnapshot, **create_params(endpoint)
        )
        assert same_creation.session_id == sid

        cancel = {"session_id": sid, "admission_id": tail.admission_id}
        cancelled = await canonical_call(client, "prompt.cancel", AdmissionStatus, **cancel)
        assert (cancelled.status, cancelled.outcome) == ("terminal", "cancelled")
        assert cancelled.sequence == tail.sequence and cancelled.ref == tail.ref
        assert await canonical_call(client, "prompt.cancel", AdmissionStatus, **cancel) == cancelled

        generation = started.execution_generation
        assert generation is not None
        resolve = {"session_id": sid, "admission_id": started.admission_id}
        await refused(
            client,
            "prompt.resolve_unknown",
            "stale_generation",
            **resolve,
            execution_generation=generation + 1,
        )
        assert (await receipt(client, sid, started.admission_id)).status == "unknown"
        resolved = await canonical_call(
            client,
            "prompt.resolve_unknown",
            AdmissionStatus,
            **resolve,
            execution_generation=generation,
        )
        assert (resolved.status, resolved.outcome) == ("terminal", "interrupted")
        assert resolved.sequence == started.sequence and resolved.ref == started.ref
        assert (
            await canonical_call(
                client,
                "prompt.resolve_unknown",
                AdmissionStatus,
                **resolve,
                execution_generation=generation,
            )
            == resolved
        )

    async with browser_client(home, endpoint) as client:
        caught_up = await canonical_call(
            client,
            "session.events.since",
            CanonicalEventsResult,
            session_id=sid,
            replay_epoch=current.replay_epoch,
            last_sequence=current.last_sequence,
        )
        assert not caught_up.snapshot_required and not caught_up.truncated and caught_up.count > 0
        assert caught_up.count == len(caught_up.events)
        assert [event.seq for event in caught_up.events] == list(
            range(current.last_sequence + 1, caught_up.latest_seq + 1)
        )
        assert all(
            event.session_id == sid and event.replay_epoch == current.replay_epoch
            for event in caught_up.events
        )
        assert any(
            event.type == "session.info" and event.payload.get("pending") == []
            for event in caught_up.events
        )
        after = await canonical_call(client, "session.resume", CanonicalSnapshot, session_id=sid)
        assert not after.pending and not after.prompts and not after.messages
        return resolved, cancelled, after


async def confirm_durable_receipts(home, endpoint, resolved, cancelled, last):
    from tui_gateway.contracts.canonical_sessions import CanonicalSnapshot, CanonicalSubmitResult

    sid = resolved.ref.session_id
    async with browser_client(home, endpoint) as client:
        current = await canonical_call(client, "session.resume", CanonicalSnapshot, session_id=sid)
        assert current.session_id == current.stored_session_id == sid
        assert current.authority_epoch > last.authority_epoch
        assert not current.pending and not current.prompts and not current.messages
        for previous in (resolved, cancelled):
            saved = await receipt(client, sid, previous.admission_id)
            assert saved.model_dump(exclude={"result", "usage"}) == previous.model_dump()
            assert saved.result is None and saved.usage is None
        exact_retry = await canonical_call(
            client,
            "prompt.submit",
            CanonicalSubmitResult,
            session_id=sid,
            submission_id=TAIL_INPUT,
            text="Synthetic queued turn",
        )
        assert exact_retry.root == cancelled

    default = (home / "state.db").as_uri() + "?mode=ro"
    selected = (home / "profiles" / PROFILE / "state.db").as_uri() + "?mode=ro"
    with closing(connect(default, uri=True)) as db:
        assert db.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchall() == []
        assert db.execute("SELECT count(*) FROM session_admissions").fetchone() == (0,)
    with closing(connect(selected, uri=True)) as db:
        assert db.execute("SELECT id FROM sessions WHERE id=?", (sid,)).fetchall() == [(sid,)]
        assert db.execute(
            "SELECT count(*) FROM messages WHERE session_id=?", (sid,)
        ).fetchone() == (0,)
        admissions = db.execute(
            "SELECT request_id,status,outcome FROM session_admissions "
            "WHERE target_session_id=? ORDER BY seq",
            (sid,),
        ).fetchall()
        assert admissions == [
            (HEAD_INPUT, "terminal", "interrupted"),
            (TAIL_INPUT, "terminal", "cancelled"),
        ]


def test_native_canonical_session_recovers_lost_claim_and_cancels_queued_input(
    tmp_path_factory, monkeypatch
):
    with isolated_webapp_host(tmp_path_factory, monkeypatch) as (host, root, common, scope):
        port, _ = distinct_ports()
        home, env = prepare_install(root / "canonical", common, port)
        for name in ("HERMES_HOME", "HERMES_RUNTIME_DIR"):
            scope.setenv(name, env[name])
        entrypoint = Path(__file__).with_name("native_canonical_claim_daemon.py")
        with crashable_gateway_daemon(
            host, home, env, "lost-owner", entrypoint=entrypoint
        ) as owner:
            launch, terminate = owner
            original, started, tail = asyncio.run(
                first_owner(home, named_webapp_endpoint(home, launch, port))
            )
            terminate()

        with serving_install(host, home, env, port, scope) as (endpoint, _):
            assert endpoint.instance_id != launch.instance_id
            resolved, cancelled, last = asyncio.run(
                recover_owner(home, endpoint, original, started, tail)
            )
        with serving_install(host, home, env, port, scope) as (replacement, _):
            assert replacement.instance_id not in {launch.instance_id, endpoint.instance_id}
            asyncio.run(confirm_durable_receipts(home, replacement, resolved, cancelled, last))
