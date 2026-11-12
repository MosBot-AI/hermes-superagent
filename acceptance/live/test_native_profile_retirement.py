"""Manual acceptance of a native profile transition over one retained Gateway socket."""

import asyncio
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing, suppress
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon

ROOT = Path(__file__).resolve().parents[2]
TITLE = "Bot Chat"
TARGET = "scout"
HEALTHY = ("default", "watch")
CONFIG = {
    "gateway": {"multiplex_profiles": True},
    "webapp": {"enabled": False},
    "model": {
        "provider": "custom",
        "default": "unused-fixture",
        "base_url": "http://127.0.0.1:9/v1",
    },
    "auxiliary": {"title_generation": {"enabled": False}},
    "platform_toolsets": {"gui": []},
    "telemetry": {"shared_metrics": {"enabled": False}},
}


def seed_chats(homes):
    from hermes_state import SessionDB

    for name, home in homes.items():
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        (home / "config.yaml").write_text(json.dumps(CONFIG), encoding="utf-8")
        (home / "models_dev_cache.json").write_text(
            '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
            encoding="utf-8",
        )
        session_id = f"fixture-retained-{name}"
        with SessionDB(home / "state.db") as db:
            db.create_session(session_id, source="cli", model="unused-fixture", cwd=str(home))
            assert db.set_session_title(session_id, TITLE)
            assert db.set_session_hidden(session_id, True)
            db.append_message(session_id, "user", f"synthetic {name}")


def inventory(home):
    uri = (home / "state.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.execute("BEGIN")
        epoch = db.execute("SELECT epoch, instance_id FROM runtime_epoch WHERE singleton=1")
        return (
            epoch.fetchone(),
            db.execute(
                "SELECT id, title, hidden, parent_session_id FROM sessions ORDER BY id"
            ).fetchall(),
            db.execute("SELECT session_id, role, content FROM messages ORDER BY id").fetchall(),
            db.execute(
                "SELECT admission_id, status, outcome FROM session_admissions ORDER BY admission_id"
            ).fetchall(),
        )


def lock_held(home):
    # Probe the same Linux flock as native Gateway ownership without changing its lock record.
    with (home / "gateway.lock").open("rb") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(stream, fcntl.LOCK_UN)
        return False


async def wait_for_profiles(homes, names):
    from hermes_cli.gateway_runtime_discovery import query_identify

    home = homes["default"]
    expected = {str(homes[name]) for name in names}
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        with suppress(FileNotFoundError, KeyError):
            identity = await asyncio.to_thread(query_identify, home, timeout=1)
            advertised = {entry["profile_id"] for entry in identity["served_profiles"]}
            recorded = json.loads((home / "gateway_state.json").read_bytes())
            held = {name for name, profile in homes.items() if lock_held(profile)}
            if advertised == expected and set(recorded["served_profiles"]) == held == set(names):
                return identity["pid"], identity["instance_id"]
        await asyncio.sleep(0.05)
    pytest.fail("Gateway discovery, recorded served set and ownership locks did not settle")


async def verify_retained_socket(endpoint, homes):
    from gateway.control_socket import request_serve_profile_hot, request_unserve_profile
    from hermes_cli.gateway_client import (
        GATEWAY_WS_PROTOCOL,
        GatewayClient,
        GatewayRPCError,
        _session_ticket,
        gateway_ws_target,
    )
    from websockets.asyncio.client import connect

    home = homes["default"]
    parked = homes[TARGET] / "gateway.parked"
    # Use the native same-user Unix grant on the launch home, as for a shared Desktop socket.
    ticket = await asyncio.to_thread(_session_ticket, home, endpoint, scope="host")
    url, protocols = gateway_ws_target(endpoint, ticket)
    async with (
        asyncio.timeout(60),
        connect(url, subprotocols=protocols, open_timeout=5, close_timeout=2, proxy=None) as socket,
        GatewayClient(socket) as client,
    ):
        assert socket.subprotocol == GATEWAY_WS_PROTOCOL

        async def lookup(name):
            result = await client.rpc(
                "session.list", _timeout=5, profile=name, title=TITLE, include_hidden=True
            )
            return [(row["id"], row["resolved_id"]) for row in result["sessions"]]

        async def assert_chats(names):
            for name in names:
                session_id = f"fixture-retained-{name}"
                assert await lookup(name) == [(session_id, session_id)]

        identity = await wait_for_profiles(homes, homes)
        assert identity[1] == endpoint.instance_id
        await assert_chats(homes)
        before = {name: inventory(profile) for name, profile in homes.items()}
        for name, (epoch, sessions, messages, admissions) in before.items():
            assert epoch[1] == endpoint.instance_id
            assert sessions == [(f"fixture-retained-{name}", TITLE, 1, None)]
            assert messages == [(f"fixture-retained-{name}", "user", f"synthetic {name}")]
            assert admissions == []

        async def retire_and_verify_absent():
            retired = await asyncio.to_thread(request_unserve_profile, home, TARGET)
            assert retired and (retired.get("unserved") == TARGET or retired.get("pending") is True)
            parked.touch(mode=0o600)
            # The watcher can re-serve the profile between the first verb and parking. This
            # second verb is serialized behind any in-flight reconcile and settles that race.
            settled = await asyncio.to_thread(request_unserve_profile, home, TARGET)
            assert settled and (
                settled.get("unserved") == TARGET
                or settled.get("pending") is True
                or settled.get("error") == f"profile '{TARGET}' is not served"
            )
            # Identify withdraws a retiring profile before its ownership lock is released.
            assert await wait_for_profiles(homes, HEALTHY) == identity
            with pytest.raises(GatewayRPCError) as refusal:
                await lookup(TARGET)
            assert (refusal.value.code, refusal.value.data["reason"]) == (4001, "profile_mismatch")
            await assert_chats(HEALTHY)
            absent = {name: inventory(profile) for name, profile in homes.items()}
            assert all(absent[name] == before[name] for name in HEALTHY)
            assert absent[TARGET][1:] == before[TARGET][1:]
            epoch, instance = absent[TARGET][0]
            assert epoch >= before[TARGET][0][0] and instance == endpoint.instance_id
            return epoch

        retired_epoch = await retire_and_verify_absent()
        parked.unlink()
        served = await asyncio.to_thread(request_serve_profile_hot, home, TARGET)
        if served and served.get("error") == f"profile '{TARGET}' is already served":
            # Unparking can let the watcher win the serve. Retire that authority and retry
            # the explicit control once, measuring the epoch from the last settled absence.
            retired_epoch = await retire_and_verify_absent()
            parked.unlink()
            served = await asyncio.to_thread(request_serve_profile_hot, home, TARGET)
        assert served and (served.get("served") == TARGET or served.get("pending") is True)
        assert await wait_for_profiles(homes, homes) == identity
        await assert_chats(homes)
        after = {name: inventory(profile) for name, profile in homes.items()}
        assert all(after[name] == before[name] for name in HEALTHY)
        assert after[TARGET][0] == (retired_epoch + 1, endpoint.instance_id)
        assert after[TARGET][1:] == before[TARGET][1:]


def test_retained_host_socket_routes_profile_after_native_unserve_and_hot_serve(
    tmp_path_factory, monkeypatch
):
    assert sys.platform == "linux", "This acceptance lane uses the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((ROOT / "compatibility.json").read_bytes())["hermes_commit"]
    root = tmp_path_factory.mktemp("mux")
    root.chmod(0o700)
    home, user, scratch, runtime, xdg, bundled, guard = (
        root / name for name in ("home", "user", "tmp", "runtime", "xdg", "bundled", "guard")
    )
    for directory in (home, user, scratch, runtime, xdg, bundled, guard):
        directory.mkdir(mode=0o700)
    assert len(os.fsencode(home / "gateway.sock")) <= 100, "The fixture socket path is too long"
    (guard / "sitecustomize.py").write_text(
        "from native_bot_socket_guard import activate_child\nactivate_child()\n", encoding="utf-8"
    )
    env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
    env.update(
        HOME=str(user),
        USERPROFILE=str(user),
        HERMES_HOME=str(home),
        HERMES_RUNTIME_DIR=str(runtime),
        HERMES_BUNDLED_PLUGINS=str(bundled),
        HERMES_ENABLE_PROJECT_PLUGINS="0",
        HERMES_DISABLE_LAZY_INSTALLS="1",
        TMPDIR=str(scratch),
        XDG_RUNTIME_DIR=str(xdg),
        XDG_CONFIG_HOME=str(root / "config"),
        XDG_CACHE_HOME=str(root / "cache"),
        XDG_DATA_HOME=str(root / "data"),
        XDG_STATE_HOME=str(root / "state"),
        PYTHONNOUSERSITE="1",
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUNBUFFERED="1",
    )
    for command, expected in (
        (["rev-parse", "HEAD"], pin),
        (["status", "--porcelain", "--untracked-files=no"], ""),
    ):
        output = subprocess.check_output(
            ["git", *command], cwd=host, env=env, text=True, timeout=10, stdin=subprocess.DEVNULL
        )
        assert output.strip() == expected

    with monkeypatch.context() as isolated:
        for key in tuple(os.environ):
            if key not in env:
                isolated.delenv(key)
        for key, value in env.items():
            isolated.setenv(key, value)
        isolated.syspath_prepend(str(host))
        isolated.setattr(tempfile, "tempdir", str(scratch))
        deactivate = activate(root)
        try:
            from hermes_cli import gateway_client

            assert Path(gateway_client.__file__).resolve().is_relative_to(host)
            homes = {"default": home, TARGET: home / "profiles" / TARGET}
            homes["watch"] = home / "profiles/watch"
            seed_chats(homes)
            child_env = env | {
                "PYTHONPATH": os.pathsep.join(
                    (str(guard), str(host), str(Path(__file__).resolve().parent))
                ),
                "HERMES_BOT_ACCEPTANCE_ROOT": str(root),
            }
            with gateway_daemon(host, home, child_env, "profile-retirement") as endpoint:
                port = urlsplit(endpoint.api_origin).port
                restrict_dials = activate(root, dial_ports=(port,))
                try:
                    asyncio.run(verify_retained_socket(endpoint, homes))
                finally:
                    restrict_dials()
            assert all(not lock_held(profile) for profile in homes.values())
        finally:
            deactivate()
