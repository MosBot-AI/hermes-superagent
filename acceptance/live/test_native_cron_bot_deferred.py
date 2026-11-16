"""Manual acceptance of native cron deferral to a named Bot Chat."""

import asyncio
import hashlib
import json
import os
import time

import pytest
from native_gateway_fixture import gateway_daemon
from test_native_managed_worker import (
    MODEL,
    REPLY,
    ScriptedModel,
    admission_rows,
    managed_fixture,
    query,
    scout_connection,
    sibling_snapshot,
)

JOB = {"id": "fixture-digest", "name": "Synthetic digest", "execution_id": "fixture-run"}
OUTPUT = "Synthetic scheduled digest 中文"
TARGET = "bot-chat:scout"


class CronModel(ScriptedModel):
    def do_POST(self):
        body = self.completion_request()
        if body is None:
            return
        turn = next(
            (row["content"] for row in reversed(body["messages"]) if row.get("role") == "user"),
            None,
        )
        if (
            self.path != "/v1/chat/completions"
            or self.headers.get("Authorization") != "Bearer no-key-required"
            or body.get("model") != MODEL
            or OUTPUT not in json.dumps(turn, ensure_ascii=False)
            or body.get("tools")
        ):
            self.server.unexpected += 1
            self.send_error(400)
            return
        self.server.turns.append(turn)
        self.server.observed.set()
        if not self.server.release.wait(20):
            self.server.unexpected += 1
            self.send_error(500)
            return
        self.send_completion(body, {"role": "assistant", "content": REPLY})


async def create_canonical(fixture, endpoint):
    from hermes_cli.gateway_client import connect_gateway

    async with asyncio.timeout(15), connect_gateway(endpoint=endpoint) as client:
        result = await client.rpc(
            "session.create",
            request_id="fixture-cron-canonical",
            title="Bot Chat",
            source="cli",
            hidden=True,
            cwd=str(fixture.scout),
            model=MODEL,
            provider="custom",
            base_url=fixture.url,
            # Restoring the route must work without an in-memory session API key.
            toolsets=[],
            ignore_rules=True,
        )
        return result["session_id"]


def configure(path, **gateway):
    config_path = path / "config.yaml"
    config = json.loads(config_path.read_bytes())
    config["gateway"].update(gateway)
    config_path.write_text(json.dumps(config), encoding="utf-8")


def run_source_tick():
    from cron.scheduler import tick

    assert tick(verbose=False) == 0  # No due jobs; the native tick drains the pending result.


def verify_transfer(fixture, watch, session_id, key, pending, parked):
    from cron.scheduler_delivery import _deliver_to_bot_chat, bot_chat_message
    from tools.bot_live_delivery import read_delivery_result

    model, scout = fixture.model, fixture.scout
    message = bot_chat_message(JOB, OUTPUT)
    try:
        run_source_tick()
        transferred = pending.read_bytes()
        transfer = json.loads(transferred)
        assert transfer["receipt_status"] in {"queued", "claimed"}
        assert transfer == {
            **json.loads(parked),
            "status": "transferred",
            "error": None,
            "receipt_status": transfer["receipt_status"],
        }
        if not model.observed.wait(12):
            diagnostic = read_delivery_result(scout, key)
            pytest.fail(
                f"No held cron completion (status={diagnostic['status']}, "
                f"error={diagnostic.get('error')}, unexpected={model.unexpected})",
                pytrace=False,
            )
        receipt = read_delivery_result(scout, key)
        assert receipt["status"] in {"queued", "claimed"}
        assert receipt["session_id"] == session_id and receipt["delivery_id"] == key
        assert (
            receipt["profile_home"] == str(scout)
            and receipt["principal_id"] == f"uid:{os.getuid()}"
        )
        assert receipt["message"] == message and "author" not in receipt
        (row,) = admission_rows(scout)
        assert row[:3] == (
            receipt["admission_id"],
            session_id,
            f"automation:agent:scout:local:dm:{session_id}",
        )
        assert row[5:] == ("started", None, f"bot:{key}")
        run_source_tick()
        assert pending.read_bytes() == transferred
        assert admission_rows(scout) == [row]
    finally:
        model.release.set()

    deadline = time.monotonic() + 18
    while time.monotonic() < deadline:
        settled = read_delivery_result(scout, key)
        if settled["status"] == "settled":
            break
        assert settled["status"] in {"queued", "claimed"}
        time.sleep(0.05)
    else:
        pytest.fail("The transferred Bot Chat result did not settle", pytrace=False)
    assert settled["admission_id"] == row[0] and settled["reply"] == REPLY
    assert admission_rows(scout) == [(*row[:5], "terminal", "completed", f"bot:{key}")]
    same_run = JOB.copy()
    assert _deliver_to_bot_chat(same_run, OUTPUT, "scout") is None
    assert same_run["_bot_chat_delivery_receipts"] == {
        TARGET: {"status": "settled", "delivery_id": key}
    }
    changed = _deliver_to_bot_chat(JOB.copy(), "Changed synthetic digest", "scout")
    assert changed.endswith("delivery id already belongs to a different payload")
    run_source_tick()
    assert read_delivery_result(scout, key) == settled
    assert pending.read_bytes() == transferred
    assert list(pending.parent.glob("*.json")) == [pending]
    assert [p.name for p in (scout / "runtime/bot_live_delivery").glob("*.json")] == [f"{key}.json"]
    assert query(scout, "SELECT id FROM sessions WHERE title = 'Bot Chat'") == [(session_id,)]
    assert query(
        scout,
        "SELECT content FROM messages WHERE session_id = ? AND role = 'assistant'",
        session_id,
    ) == [(REPLY,)]
    assert len(model.turns) == 1 and model.unexpected == 0
    for path in (watch, fixture.home):
        assert sibling_snapshot(path) == fixture.controls[path]


def test_native_cron_transfers_one_deferred_result_to_existing_named_bot(
    tmp_path_factory, monkeypatch
):
    with managed_fixture(tmp_path_factory, monkeypatch, handler=CronModel) as fixture:
        from cron.scheduler_delivery import _deliver_to_bot_chat
        from cron.scheduler_provider import _profile_cron_scope
        from hermes_cli.gateway_runtime import discover_gateway_endpoint
        from tools.bot_live_delivery import read_delivery_result

        watch = fixture.home / "profiles/watch"
        # The source has no Gateway. Only its explicit native ticks drain its cron store.
        configure(watch, standalone=True)
        configure(fixture.scout, managed_workers=False)
        with (
            gateway_daemon(fixture.host, fixture.home, fixture.child_env, "cron-seed") as first,
            scout_connection(fixture, first) as (endpoint, _),
        ):
            session_id = asyncio.run(create_canonical(fixture, endpoint))

        with _profile_cron_scope(watch):
            assert discover_gateway_endpoint(fixture.scout, timeout=2).state == "absent"
            job = JOB.copy()
            seed = [str(watch), job["id"], job["execution_id"], str(fixture.scout)]
            key = hashlib.sha256(json.dumps(seed, separators=(",", ":")).encode()).hexdigest()
            parked_message = _deliver_to_bot_chat(job, OUTPUT, "scout")
            assert parked_message.startswith(f"{TARGET} queued (receipt {key})")
            assert job["_bot_chat_delivery_receipts"] == {
                TARGET: {"status": "queued", "delivery_id": key}
            }
            pending = watch / "cron/bot_chat_pending" / f"{key}.json"
            parked = pending.read_bytes()
            record = json.loads(parked)
            assert record["status"] == "queued" and record["id"] == key
            assert record["home"] == str(fixture.scout) and record["content"] == OUTPUT
            run_source_tick()
            assert pending.read_bytes() == parked
            assert read_delivery_result(fixture.scout, key) is None
            assert admission_rows(fixture.scout) == [] and fixture.model.turns == []
            assert query(fixture.scout, "SELECT id FROM sessions") == [(session_id,)]

        with (
            gateway_daemon(fixture.host, fixture.home, fixture.child_env, "cron-restart") as second,
            scout_connection(fixture, second) as (_, _),
            _profile_cron_scope(watch),
        ):
            assert second.instance_id != first.instance_id
            assert pending.read_bytes() == parked
            assert read_delivery_result(fixture.scout, key) is None
            verify_transfer(fixture, watch, session_id, key, pending, parked)
