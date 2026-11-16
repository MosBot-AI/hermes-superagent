"""Replay a deferred Cron Bot delivery after its successful receipt goes unread."""

import asyncio
import hashlib
import json

from native_bot_asgi import native_bot_gateway as native_bot_gateway
from test_native_voice_audio_asgi import run_native_async


def test_cron_deferred_bot_delivery_replays_after_lost_ack(native_bot_gateway, caplog):
    from cron.bot_chat_legacy import drain_legacy_pending
    from cron.scheduler_delivery import _deliver_to_bot_chat
    from hermes_cli import gateway_client
    from hermes_state_runtime import list_session_admissions

    native = native_bot_gateway
    home, db, authority = native.home, native.db, native.authority
    profile_id, instance_id, subject = native.profile_id, native.instance_id, native.subject
    control_requests, scheduled, tickets = native.control_requests, native.scheduled, native.tickets

    async def scenario():
        transport = native.connect(drop_first_result=True)
        ref = native.seed_bot_chat()
        job = {"id": "fixture-job", "name": "Fixture job", "execution_id": "fixture-run"}
        output = "Synthetic cron output"
        key = hashlib.sha256(
            json.dumps(
                [profile_id, job["id"], job["execution_id"], profile_id], separators=(",", ":")
            ).encode()
        ).hexdigest()
        pending = home / "cron" / "bot_chat_pending" / f"{key}.json"
        mailbox = home / "runtime" / "bot_live_delivery"
        receipt_path = mailbox / f"{key}.json"

        def admissions():
            return list_session_admissions(db, session_id=ref.session_id, pending_only=False)

        status = await asyncio.to_thread(_deliver_to_bot_chat, job, output, "")
        assert f"queued (receipt {key})" in status
        assert job["_bot_chat_delivery_receipts"] == {
            "bot-chat:(own)": {"status": "queued", "delivery_id": key}
        }
        spool = pending.read_bytes()
        parked = json.loads(spool)
        assert parked["id"] == key and parked["status"] == "queued"
        assert parked["home"] == profile_id and parked["content"] == output
        assert not admissions() and not list(mailbox.glob("*.json"))
        assert not control_requests and not transport.requests

        native.ready = True
        await asyncio.to_thread(drain_legacy_pending)
        (lost_ack,) = transport.dropped
        assert transport.responses == [lost_ack] and len(transport.requests) == 1
        assert any(
            entry.exc_info
            and isinstance(entry.exc_info[1], gateway_client.GatewayClientError)
            and str(entry.exc_info[1]) == gateway_client.DISCONNECTED
            for entry in caplog.records
        )
        assert pending.read_bytes() == spool
        assert list(mailbox.glob("*.json")) == [receipt_path]
        first_receipt = json.loads(receipt_path.read_bytes())
        (row,) = admissions()
        ack = lost_ack["result"]
        assert ack["delivery_id"] == key and ack["status"] == "queued"
        assert ack["profile_home"] == profile_id and ack["session_id"] == ref.session_id
        assert first_receipt["status"] == "queued" and first_receipt["principal_id"] == subject
        assert row["status"] == "queued" and row["request_id"] == f"bot:{key}"
        assert row["outcome"] is None
        assert row["admission_id"] == first_receipt["admission_id"] == ack["admission_id"]
        assert row["payload"]["text"] == first_receipt["message"] == ack["message"]
        assert output in ack["message"]

        await asyncio.to_thread(drain_legacy_pending)
        assert len(control_requests) == len(transport.tickets) == len(transport.requests) == 2
        assert all(frame["verb"] == "session-ticket" for frame in control_requests)
        assert all(
            frame["params"]
            == {"profile_id": profile_id, "instance_id": instance_id, "purpose": "interactive"}
            for frame in control_requests
        )
        first, replay = transport.requests
        assert first["method"] == replay["method"] == "bot_relay.deliver"
        assert (
            first["params"]
            == replay["params"]
            == {
                "id": key,
                "profile": "default",
                "session_id": ref.session_id,
                "message": ack["message"],
            }
        )
        assert len(transport.responses) == 2
        replay_result = transport.responses[1]["result"]
        assert {k: v for k, v in replay_result.items() if k != "target_state"} == {
            k: v for k, v in ack.items() if k != "target_state"
        }
        transferred = pending.read_bytes()
        assert json.loads(transferred) == {
            **parked,
            "status": "transferred",
            "error": None,
            "receipt_status": "queued",
        }

        await asyncio.to_thread(drain_legacy_pending)
        assert len(control_requests) == len(transport.requests) == len(transport.responses) == 2
        assert pending.read_bytes() == transferred
        assert list(mailbox.glob("*.json")) == [receipt_path]
        assert json.loads(receipt_path.read_bytes()) == first_receipt
        assert admissions() == [row] and scheduled == [ref]
        with db._read_ctx() as conn:
            assert [r[0] for r in conn.execute("SELECT id FROM sessions")] == [ref.session_id]
            assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
            assert [r[0] for r in conn.execute("SELECT admission_id FROM session_admissions")] == [
                row["admission_id"]
            ]
        assert not authority.events and not tickets.outstanding()

    run_native_async(scenario())
