"""Replay a deferred Cron Bot delivery after its successful receipt goes unread."""

import asyncio
import hashlib
import json
import socket
import subprocess
import sys
import threading
from contextlib import asynccontextmanager, closing
from types import SimpleNamespace

from test_native_voice_audio_asgi import run_native_async


class InMemoryWebSocket:
    def __init__(self, state, subprotocol, send, incoming):
        self.state = state
        self.subprotocol = subprotocol
        self.send = send
        self.incoming = incoming

    async def __aiter__(self):
        while (text := await self.incoming.get()) is not None:
            yield text


class ReceiptTransport:
    def __init__(self, app, protocol, open_state):
        self.app = app
        self.protocol = protocol
        self.open_state = open_state
        self.owner_loop = asyncio.get_running_loop()
        self.tickets = set()
        self.requests = []
        self.responses = []
        self.dropped = []

    @asynccontextmanager
    async def connect(self, url, *, subprotocols, open_timeout, proxy):
        assert url == "ws://127.0.0.1:8765/api/ws" and proxy is None
        assert subprotocols[0] == self.protocol
        self.tickets.add(subprotocols[1])
        caller_loop = asyncio.get_running_loop()
        inbound = asyncio.Queue()
        outbound = asyncio.Queue()
        opened = asyncio.Queue()
        request_id = None
        accepted = False
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "scheme": "ws",
            "path": "/api/ws",
            "query_string": b"",
            "headers": [
                (b"host", b"127.0.0.1:8765"),
                (b"sec-websocket-protocol", ", ".join(subprotocols).encode()),
            ],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8765),
            "subprotocols": subprotocols,
        }

        async def send_to_owner(text):
            nonlocal request_id
            frame = json.loads(text)
            assert frame["method"] == "bot_relay.deliver" and request_id is None
            request_id = frame["id"]
            self.requests.append(frame)
            self.owner_loop.call_soon_threadsafe(
                inbound.put_nowait, {"type": "websocket.receive", "text": text}
            )

        async def send_to_client(message):
            nonlocal accepted
            if message["type"] == "websocket.accept":
                accepted = True
                caller_loop.call_soon_threadsafe(opened.put_nowait, message)
                return
            if message["type"] == "websocket.close":
                loop_queue, value = (outbound, None) if accepted else (opened, message)
                caller_loop.call_soon_threadsafe(loop_queue.put_nowait, value)
                return
            assert message["type"] == "websocket.send"
            text = message["text"]
            frame = json.loads(text)
            if request_id is not None and frame.get("id") == request_id:
                self.responses.append(frame)
                if len(self.responses) == 1 and "result" in frame:
                    self.dropped.append(frame)
                    # The server emitted a result after commit. Only the client's reader sees EOF.
                    caller_loop.call_soon_threadsafe(outbound.put_nowait, None)
                    return
            caller_loop.call_soon_threadsafe(outbound.put_nowait, text)

        async def serve():
            inbound.put_nowait({"type": "websocket.connect"})
            try:
                await self.app(scope, inbound.get, send_to_client)
            finally:
                queue = outbound if accepted else opened
                caller_loop.call_soon_threadsafe(queue.put_nowait, None)

        serving = asyncio.run_coroutine_threadsafe(serve(), self.owner_loop)
        try:
            handshake = await asyncio.wait_for(opened.get(), timeout=min(open_timeout, 3))
            assert handshake and handshake["type"] == "websocket.accept", handshake
            yield InMemoryWebSocket(
                self.open_state, handshake["subprotocol"], send_to_owner, outbound
            )
        finally:
            self.owner_loop.call_soon_threadsafe(
                inbound.put_nowait, {"type": "websocket.disconnect", "code": 1000}
            )
            await asyncio.wait_for(asyncio.wrap_future(serving), timeout=2)


def test_cron_deferred_bot_delivery_replays_after_lost_ack(tmp_path, monkeypatch, caplog):
    home = tmp_path / "hermes"
    home.mkdir()
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (home / "config.yaml").write_text(
        '{"platform_toolsets":{"gui":[]},"model":"synthetic"}', encoding="utf-8"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", "synthetic-receipt-dashboard")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # An explicit temporary directory keeps the bootstrap from starting a detached pruner.
    monkeypatch.setenv("TMPDIR", str(scratch))
    monkeypatch.delenv("HERMES_SCRATCH_DIR", raising=False)

    import pm
    from hermes_cli import env_loader, version_info

    forbidden = []

    def refuse(*args, **kwargs):
        forbidden.append("Unexpected network, process, SDK or turn execution")
        raise AssertionError(forbidden[-1])

    bind = socket.socket.bind

    def bind_ipv6_probe(sock, address):
        # urllib3 checks local IPv6 availability during import without listening.
        if (
            sock.family == socket.AF_INET6
            and sock.type == socket.SOCK_STREAM
            and address == ("::1", 0)
        ):
            return bind(sock, address)
        return refuse()

    monkeypatch.setattr(pm, "ensure_import", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "bind", bind_ipv6_probe)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket.socket, "listen", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)

    with monkeypatch.context() as startup:
        startup.setattr(env_loader, "load_hermes_dotenv", lambda *args, **kwargs: [])
        startup.setattr(env_loader, "apply_config_bootstrap_env", lambda *args, **kwargs: None)
        startup.setattr(sys, "stdout", sys.stdout)
        startup.setattr(sys, "excepthook", sys.excepthook)
        startup.setattr(threading, "excepthook", threading.excepthook)
        # Version metadata is unrelated to receipt behavior and normally shells out to Git.
        startup.setattr(
            version_info,
            "_cached_version_info",
            version_info.VersionInfo("fixture", "fixture", None, None, None, "unknown"),
        )
        from cron.bot_chat_legacy import drain_legacy_pending
        from cron.scheduler_delivery import _deliver_to_bot_chat
        from gateway import session_finite, status
        from gateway.config import GatewayConfig
        from gateway.control_socket import GatewayControlServer
        from gateway.run_api import GatewayRuntimeAPI
        from gateway.runtime_bootstrap import TicketStore
        from gateway.session import SessionStore
        from gateway.session_authority import SessionAuthority
        from gateway.session_contract import SessionActor
        from gateway.session_local import create_local_session
        from gateway.session_local_title import title_new_session
        from hermes_cli import gateway_client, gateway_runtime, web_server
        from hermes_state_runtime import begin_runtime_epoch, list_session_admissions
        from tui_gateway import launch_profile_policy, ws
        from websockets.asyncio import client as websocket_client
        from websockets.protocol import State

    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)
    monkeypatch.setattr(ws, "_start_backend_liveness", lambda: None)
    monkeypatch.setattr(ws, "_note_dashboard_client_activity", lambda **kwargs: None)
    monkeypatch.setattr(ws.server, "_ensure_skin_watcher", lambda: None)
    monkeypatch.setattr(ws.server, "_ensure_lease_watcher", lambda: None)
    monkeypatch.setattr(ws.server, "dispatch", refuse)
    monkeypatch.setattr(session_finite, "execute_finite_admission", refuse)
    # Status publication is unrelated to admission and starts a daemon writer.
    monkeypatch.setattr(status, "publish_runtime_status", lambda **kwargs: 0)

    profile_id = str(home)
    instance_id = "synthetic-receipt-owner"
    subject = "uid:1000"
    config = GatewayConfig()
    store = SessionStore(home / "sessions", config)
    runner = SimpleNamespace(config=config, _draining=False, session_store=store, adapters={})
    runner._adapter_for_source = lambda source: runner.adapters.get(source.platform)
    runner._handle_message = refuse
    tickets = TicketStore(instance_id, frozenset({profile_id}))
    control = GatewayControlServer(home)
    control.ticket_store = tickets
    state = web_server.app.state
    monkeypatch.setattr(state, "gateway_runner", runner, raising=False)
    monkeypatch.setattr(state, "ui_surface", "gateway", raising=False)
    monkeypatch.setattr(state, "auth_required", False, raising=False)
    monkeypatch.setattr(state, "bound_host", "127.0.0.1", raising=False)
    app = GatewayRuntimeAPI(web_server.app, runner, web_server.app)

    with closing(store._db) as db:
        epoch = begin_runtime_epoch(db, instance_id=instance_id)
        authority = SessionAuthority(
            runner, profile_id=profile_id, instance_id=instance_id, db=db, epoch=epoch
        )
        runner.session_authority = authority
        runner.session_ticket_store = tickets
        runner.session_runtime_descriptor = {"state": "ready", "instance_id": instance_id}
        scheduled = []
        # Hold the real FIFO row queued while the receipt and transport reconcile.
        monkeypatch.setattr(authority, "_schedule", scheduled.append)

        endpoint = gateway_runtime.GatewayEndpoint(
            profile_id, instance_id, epoch, 1, "http://127.0.0.1:8765", "none", frozenset()
        )
        ready = False
        control_requests = []

        def discover(home_arg, *, timeout):
            assert home_arg == home and timeout == 5
            if ready:
                return gateway_runtime.GatewayDiscovery("ready", endpoint)
            return gateway_runtime.GatewayDiscovery("stopped")

        def private_control(home_arg, request):
            assert home_arg == home
            control_requests.append(json.loads(request))
            return control.handle_request_line(request, peer_subject=subject)

        monkeypatch.setattr(gateway_runtime, "discover_gateway_endpoint", discover)
        monkeypatch.setattr(gateway_client, "private_control_query", private_control)

        async def scenario():
            nonlocal ready
            transport = ReceiptTransport(app, gateway_client.GATEWAY_WS_PROTOCOL, State.OPEN)
            monkeypatch.setattr(websocket_client, "connect", transport.connect)
            # The synchronous cron caller starts its own loop inside the worker. Give it
            # the same bounded driver as the owner loop to avoid delayed sandbox wakeups.
            monkeypatch.setattr(asyncio, "run", run_native_async)
            # This actor only seeds the local canonical chat. RPC actors come from tickets.
            actor = SessionActor(subject, profile_id, frozenset({"session:create"}), "setup")
            ref = create_local_session(
                authority,
                actor,
                {
                    "request_id": "synthetic-bot-chat",
                    "source": "gui",
                    "cwd": profile_id,
                    "model": "synthetic",
                    "toolsets": [],
                },
            )
            title_new_session(authority, ref, "Bot Chat")
            assert db.set_session_hidden(ref.session_id, True)
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

            ready = True
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
                assert [
                    r[0] for r in conn.execute("SELECT admission_id FROM session_admissions")
                ] == [row["admission_id"]]
            assert not authority.events and not tickets.outstanding()

        run_native_async(scenario())
        assert not forbidden
