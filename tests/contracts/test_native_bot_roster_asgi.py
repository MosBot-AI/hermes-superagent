"""Canonical Bot roster reads over the native local-ticket WebSocket."""

import asyncio
import json
import socket
import sqlite3
import sys
import threading
from contextlib import ExitStack, closing, contextmanager
from types import SimpleNamespace

import pytest
from test_native_voice_audio_asgi import run_native_async

PROTOCOL = "hermes-gateway-v1"
INSTALL_ID = "1234567890abcdef1234567890abcdef"
SUBJECT = "uid:roster-fixture"
SESSION_FIELDS = {"canonical_session", "last_session", "worker_session"}


def roster_request(
    native, *, ticket_profile="default", scope="profile", purpose="interactive", **params
):
    ticket = native.tickets.mint(
        profile_id=str(native.homes[ticket_profile]),
        subject=SUBJECT,
        purpose=purpose,
        scope=scope,
    )
    protocols = [PROTOCOL, f"hermes-gateway-ticket.{ticket}"]
    request = {"jsonrpc": "2.0", "id": "roster", "method": "profiles.list", "params": params}
    asgi_scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "scheme": "ws",
        "path": "/api/ws",
        "raw_path": b"/api/ws",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"127.0.0.1:8765"),
            (b"sec-websocket-protocol", ", ".join(protocols).encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "subprotocols": protocols,
        "state": {},
    }

    async def exchange():
        inbound = asyncio.Queue()
        inbound.put_nowait({"type": "websocket.connect"})
        sent = []
        frames = []

        async def send(message):
            sent.append(message)
            if message["type"] != "websocket.send":
                return
            frame = json.loads(message["text"])
            frames.append(frame)
            if frame.get("params", {}).get("type") == "gateway.ready":
                assert frame["params"]["payload"]["session_authority"] is True
                inbound.put_nowait({"type": "websocket.receive", "text": json.dumps(request)})
            if frame.get("id") == request["id"]:
                inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})

        await native.app(asgi_scope, inbound.get, send)
        assert sent[0] == {"type": "websocket.accept", "subprotocol": PROTOCOL, "headers": []}
        (reply,) = (frame for frame in frames if frame.get("id") == request["id"])
        return reply

    return run_native_async(exchange())


@pytest.fixture
def native_roster(tmp_path, monkeypatch, request):
    unreadable_id = getattr(request, "param", None) == "unreadable_id"
    with serve_roster(tmp_path, monkeypatch, unreadable_id=unreadable_id) as native:
        yield native


@contextmanager
def serve_roster(tmp_path, monkeypatch, *, unreadable_id=False):
    root = tmp_path / "install"
    secondary = root / "profiles" / "secondary"
    secondary.mkdir(parents=True)
    bundled = tmp_path / "empty-bundled"
    bundled.mkdir()
    homes = {"default": root, "secondary": secondary}
    for home in homes.values():
        (home / "config.yaml").write_text('{"model":"synthetic"}', encoding="utf-8")
        (home / "profile.yaml").write_text(
            '{"display_name":"Shared fixture label"}', encoding="utf-8"
        )
    install_path = root / "install_id"
    if unreadable_id:
        install_path.mkdir()
        # Keep the native lock path from adding a fixture file during the read.
        (root / ".install_id.lock").touch()
    else:
        install_path.write_text(f"{INSTALL_ID}\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HERMES_BUNDLED_PLUGINS", str(bundled))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "0")
    monkeypatch.setenv("HERMES_DASHBOARD_SESSION_TOKEN", "synthetic-roster-dashboard")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import pm
    from hermes_cli import env_loader

    forbidden = []

    def refuse(*args, **kwargs):
        forbidden.append("Unexpected roster execution, network or SDK call")
        raise AssertionError(forbidden[-1])

    bind = socket.socket.bind

    def bind_ipv6_probe(sock, address):
        # urllib3 checks local IPv6 availability during an import, without listening.
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
    with monkeypatch.context() as startup:
        startup.setattr(env_loader, "load_hermes_dotenv", lambda *args, **kwargs: [])
        startup.setattr(env_loader, "apply_config_bootstrap_env", lambda *args, **kwargs: None)
        # Importing the standalone sidecar configures stdout and crash hooks.
        startup.setattr(sys, "stdout", sys.stdout)
        startup.setattr(sys, "excepthook", sys.excepthook)
        startup.setattr(threading, "excepthook", threading.excepthook)
        from agent.secret_scope import is_multiplex_active, set_multiplex_active
        from gateway.run_api import GatewayRuntimeAPI
        from gateway.runtime_bootstrap import TicketStore
        from gateway.session_authorities import SessionAuthorities
        from gateway.session_authority import SessionAuthority
        from hermes_cli import web_server
        from hermes_state import SessionDB
        from hermes_state_runtime import begin_runtime_epoch
        from tui_gateway import launch_profile_policy, ws

    monkeypatch.setattr(launch_profile_policy, "_snapshot", None)
    monkeypatch.setattr(web_server, "_DASHBOARD_EMBEDDED_CHAT_ENABLED", True)
    monkeypatch.setattr(ws, "_start_backend_liveness", lambda: None)
    monkeypatch.setattr(ws, "_note_dashboard_client_activity", lambda **kwargs: None)
    monkeypatch.setattr(ws.server, "_ensure_skin_watcher", lambda: None)
    monkeypatch.setattr(ws.server, "_ensure_lease_watcher", lambda: None)
    monkeypatch.setattr(SessionAuthority, "_schedule", refuse)

    instance_id = f"roster-{tmp_path.name}"
    registry = SessionAuthorities(root, multiplexed=True)
    runner = SimpleNamespace(
        config=SimpleNamespace(multiplex_profiles=True),
        session_authorities=registry,
        _draining=False,
        _handle_message=refuse,
    )
    previous_multiplexed = is_multiplex_active()
    try:
        set_multiplex_active(True)
        with ExitStack() as stores:
            authorities = {}
            for name, home in homes.items():
                db = stores.enter_context(closing(SessionDB(db_path=home / "state.db")))
                authority = SessionAuthority(
                    runner,
                    profile_id=str(home),
                    instance_id=instance_id,
                    db=db,
                    epoch=begin_runtime_epoch(db, instance_id=instance_id),
                )
                registry.add(home, authority, name=name)
                authorities[name] = authority
            runner.session_authority = registry.launch
            runner.session_ticket_store = TicketStore(instance_id, registry.profile_ids())
            runner.session_runtime_descriptor = {
                "state": "ready",
                "instance_id": instance_id,
                "served_profiles": registry.served_profiles(),
            }
            state = web_server.app.state
            monkeypatch.setattr(state, "gateway_runner", runner, raising=False)
            monkeypatch.setattr(state, "ui_surface", "gateway", raising=False)
            monkeypatch.setattr(state, "auth_required", False, raising=False)
            monkeypatch.setattr(state, "bound_host", "127.0.0.1", raising=False)
            yield SimpleNamespace(
                app=GatewayRuntimeAPI(web_server.app, runner, web_server.app),
                homes=homes,
                authorities=authorities,
                tickets=runner.session_ticket_store,
            )
            assert all(
                not authority.events and not authority.sessions
                for authority in authorities.values()
            )
    finally:
        set_multiplex_active(previous_multiplexed)
        if unreadable_id:
            assert install_path.is_dir() and not list(install_path.iterdir())
        else:
            assert install_path.read_text(encoding="utf-8") == f"{INSTALL_ID}\n"
            assert not (root / ".install_id.lock").exists()
        assert not forbidden


def seed_chat(db, session_id, title, *, hidden=False, parent=None, source="local", user_id=SUBJECT):
    chat_id = db.get_session(parent)["chat_id"] if parent else session_id
    db.create_session(
        session_id, source=source, user_id=user_id, chat_id=chat_id, parent_session_id=parent
    )
    assert db.set_session_title(session_id, title)
    db.append_message(session_id, "user", f"Synthetic marker for {session_id}")
    if hidden:
        assert db.set_session_hidden(session_id, True)


def durable_state(native):
    snapshot = {}
    for name, home in native.homes.items():
        uri = (home / "state.db").as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            snapshot[name] = (
                conn.execute("SELECT * FROM sessions ORDER BY id").fetchall(),
                conn.execute("SELECT * FROM messages ORDER BY id").fetchall(),
                conn.execute("SELECT * FROM state_meta ORDER BY key").fetchall(),
                conn.execute("SELECT * FROM session_admissions ORDER BY admission_id").fetchall(),
            )
    return snapshot


def profiles(reply, *, install_id=INSTALL_ID):
    result = reply["result"]
    assert result["install_id"] == install_id
    assert result["bot_mode_protocol"] is True
    rows = {row["name"]: row for row in result["profiles"]}
    assert len(rows) == len(result["profiles"]) == 2
    return rows


def test_native_roster_separates_hidden_canonical_lineage_from_recent_and_worker(native_roster):
    native = native_roster
    launch, target = (native.authorities[name].db for name in ("default", "secondary"))
    seed_chat(launch, "local-launch-root", "Bot Chat", hidden=True)
    seed_chat(target, "local-target-root", "Bot Chat", hidden=True)
    target.end_session("local-target-root", "compression")
    seed_chat(target, "target-tip", "Bot Chat continued", hidden=True, parent="local-target-root")
    seed_chat(target, "local-numbered", "Bot Chat #2")
    seed_chat(target, "worker-row", "Worker work", source="kanban")
    before = durable_state(native)

    rows = profiles(roster_request(native, scope="host", profile="secondary"))

    assert list(rows) == ["secondary", "default"]
    assert (
        rows["default"]["display_name"]
        == rows["secondary"]["display_name"]
        == "Shared fixture label"
    )
    assert rows["default"]["canonical_session"]["id"] == "local-launch-root"
    row = rows["secondary"]
    canonical = row["canonical_session"]
    assert canonical["id"] == "local-target-root"
    assert canonical["resolved_id"] == "target-tip"
    assert canonical["root_title"] == "Bot Chat"
    assert canonical["title"] == "Bot Chat continued"
    assert canonical["preview"] == "Synthetic marker for target-tip"
    assert row["last_session"]["id"] == "local-numbered"
    assert row["worker_session"]["id"] == "worker-row"
    assert durable_state(native) == before


def test_native_roster_keeps_profile_scope_and_retiring_siblings_metadata_only(native_roster):
    native = native_roster
    seed_chat(native.authorities["default"].db, "local-default", "Bot Chat", hidden=True)
    # The local interactive ticket is operator within its route scope.
    seed_chat(
        native.authorities["secondary"].db,
        "local-secondary",
        "Bot Chat",
        hidden=True,
        user_id="uid:other-fixture-author",
    )
    before = durable_state(native)

    restricted = profiles(roster_request(native, ticket_profile="secondary"))
    assert restricted["secondary"]["canonical_session"]["id"] == "local-secondary"
    assert not SESSION_FIELDS & restricted["default"].keys()
    refused = roster_request(native, ticket_profile="secondary", profile="default")
    assert refused["error"]["data"]["reason"] == "profile_mismatch"
    assert "result" not in refused

    worker = roster_request(native, purpose="worker-adoption")
    assert worker["error"]["data"]["reason"] == "permission_denied"
    assert "result" not in worker

    fleet = profiles(roster_request(native, scope="host"))
    assert fleet["secondary"]["canonical_session"]["id"] == "local-secondary"
    native.authorities["secondary"].retiring = True
    degraded = profiles(roster_request(native, scope="host"))
    assert degraded["default"]["canonical_session"]["id"] == "local-default"
    assert not SESSION_FIELDS & degraded["secondary"].keys()
    assert durable_state(native) == before


def test_native_roster_leaves_unbound_and_recoverable_chats_unresolved(native_roster):
    native = native_roster
    launch, target = (native.authorities[name].db for name in ("default", "secondary"))
    seed_chat(launch, "legacy-chat", "Bot Chat", source="cli")
    seed_chat(target, "local-archived", "Bot Chat", hidden=True)
    target.end_session("local-archived", "ws_orphan_reap")
    # The auto-archive keeps the title. A deliberate archive clears it.
    assert target._auto_archive_lineage("local-archived")
    archived = target.get_session("local-archived")
    assert archived["title"] == "Bot Chat" and archived["archived"] and archived["auto_archived"]
    seed_chat(target, "local-numbered", "Bot Chat #2")
    before = durable_state(native)

    rows = profiles(roster_request(native, scope="host"))

    assert rows["default"]["canonical_session"] is None
    assert rows["secondary"]["canonical_session"] is None
    assert rows["secondary"]["last_session"]["id"] == "local-numbered"
    assert durable_state(native) == before


@pytest.mark.parametrize("native_roster", ["unreadable_id"], indirect=True)
def test_native_roster_leaves_unreadable_install_identity_empty(native_roster):
    native = native_roster
    seed_chat(native.authorities["default"].db, "local-root", "Bot Chat", hidden=True)
    before = durable_state(native)

    rows = profiles(roster_request(native), install_id="")

    assert rows["default"]["canonical_session"]["id"] == "local-root"
    assert not SESSION_FIELDS & rows["secondary"].keys()
    assert durable_state(native) == before


def test_native_roster_resolves_same_named_profile_on_each_fixture_endpoint(tmp_path, monkeypatch):
    # These separate runtime roots deliberately use the same install marker and profile label.
    for endpoint in ("original", "copy"):
        with (
            monkeypatch.context() as isolated,
            serve_roster(tmp_path / endpoint, isolated) as native,
        ):
            db = native.authorities["secondary"].db
            root_id = f"local-{endpoint}-root"
            tip_id = f"{endpoint}-tip"
            seed_chat(db, root_id, "Bot Chat", hidden=True)
            db.end_session(root_id, "compression")
            seed_chat(db, tip_id, "Bot Chat continued", hidden=True, parent=root_id)
            before = durable_state(native)

            reply = roster_request(native, ticket_profile="secondary", profile="secondary")
            row = profiles(reply)["secondary"]

            assert row["display_name"] == "Shared fixture label"
            assert row["path"] == str(native.homes["secondary"])
            assert row["canonical_session"]["id"] == root_id
            assert row["canonical_session"]["resolved_id"] == tip_id
            assert row["canonical_session"]["preview"] == f"Synthetic marker for {tip_id}"
            assert durable_state(native) == before
