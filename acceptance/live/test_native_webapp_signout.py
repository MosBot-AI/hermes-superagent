"""Manual evidence of a serving Webapp's installation-scoped native sign-out."""

import asyncio
import hmac
import json
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
from contextlib import AsyncExitStack, closing, contextmanager
from pathlib import Path

import pytest
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon

REPO = Path(__file__).resolve().parents[2]
PROFILE = "scout"
TITLE = "Bot Chat"
TOKEN_PATH = Path("webapp") / "session-token"


def distinct_ports():
    with socket.socket() as first, socket.socket() as second:
        for sock in (first, second):
            sock.bind(("127.0.0.1", 0))
        return first.getsockname()[1], second.getsockname()[1]


def read_private_credential(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise AssertionError("Expected the fixture's private native Webapp credential")
    return path.read_bytes()


def history_snapshot(installs):
    snapshot = {}
    for label, (home, _, _, _) in installs.items():
        for profile in (home, home / "profiles" / PROFILE):
            uri = (profile / "state.db").as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                db.execute("BEGIN")
                snapshot[label, profile.name] = (
                    db.execute(
                        "SELECT id,title,hidden,parent_session_id FROM sessions ORDER BY id"
                    ).fetchall(),
                    db.execute(
                        "SELECT id,session_id,role,content FROM messages ORDER BY id"
                    ).fetchall(),
                    db.execute(
                        "SELECT admission_id,status,outcome FROM session_admissions "
                        "ORDER BY admission_id"
                    ).fetchall(),
                )
    return snapshot


def prepare_install(box, common_env, port):
    from hermes_state import SessionDB

    home = box / "h"
    named = home / "profiles" / PROFILE
    user, runtime, xdg, scratch, bundled, assets = (
        box / name for name in ("user", "rt", "xdg", "tmp", "bundled", "assets")
    )
    for directory in (home, named, user, runtime, xdg, scratch, bundled, assets):
        directory.mkdir(mode=0o700, parents=True)
    assert len(os.fsencode(home / "gateway.sock")) <= 100, "Fixture socket path too long"
    (assets / "index.html").write_text("<!doctype html><title>Synthetic Webapp</title>")
    absent_bus = f"unix:path={xdg}/absent"
    env = common_env | {
        "HOME": str(user),
        "USERPROFILE": str(user),
        "HERMES_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(runtime),
        "HERMES_BUNDLED_PLUGINS": str(bundled),
        "HERMES_WEBAPP_DIST": str(assets),
        "TMPDIR": str(scratch),
        "XDG_RUNTIME_DIR": str(xdg),
        "XDG_CONFIG_HOME": str(box / "config"),
        "XDG_CACHE_HOME": str(box / "cache"),
        "XDG_DATA_HOME": str(box / "data"),
        "XDG_STATE_HOME": str(box / "state"),
        "DBUS_SESSION_BUS_ADDRESS": absent_bus,
        "DBUS_SYSTEM_BUS_ADDRESS": absent_bus,
        "HERMES_BOT_ACCEPTANCE_ROOT": str(box),
    }

    for name, profile in (("default", home), (PROFILE, named)):
        config = {
            "gateway": {"multiplex_profiles": True},
            "webapp": {"enabled": profile == home, "host": "127.0.0.1", "port": port},
            "model": {
                "provider": "custom",
                "default": "unused-fixture",
                "base_url": "http://127.0.0.1:9/v1",
            },
            "platform_toolsets": {"gui": []},
            "telemetry": {"shared_metrics": {"enabled": False}},
        }
        (profile / "config.yaml").write_text(json.dumps(config), encoding="utf-8")
        (profile / "models_dev_cache.json").write_text(
            '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
            encoding="utf-8",
        )
        session_id = f"fixture-{box.name}-{name}"
        with SessionDB(profile / "state.db") as db:
            db.create_session(session_id, source="cli", model="unused-fixture", cwd=str(profile))
            assert db.set_session_title(session_id, TITLE)
            assert db.set_session_hidden(session_id, True)
            db.append_message(session_id, "user", session_id)

    return home, env


def webapp_cli(host, env, flag, *, expected):
    result = subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", "webapp", flag],
        cwd=host,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=35,
        umask=0o077,
    )
    if result.returncode or expected not in result.stdout:
        pytest.fail(f"Native Webapp {flag} did not confirm the fixture operation", pytrace=False)


@contextmanager
def serving_install(host, home, env, port, monkeypatch):
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_cli.gateway_runtime_discovery import query_identify

    # The shared daemon writes its planned-stop marker in the process Hermes home.
    with monkeypatch.context() as scope:
        for name in ("HERMES_HOME", "HERMES_RUNTIME_DIR"):
            scope.setenv(name, env[name])
        with gateway_daemon(host, home, env, "webapp-signout") as endpoint:
            assert endpoint.api_origin == f"http://127.0.0.1:{port}"
            named = home / "profiles" / PROFILE
            observed = discover_gateway_endpoint(named, timeout=2)
            assert observed.state == "ready" and observed.endpoint is not None
            named_endpoint = observed.endpoint
            assert named_endpoint.profile_id == str(named)
            assert (named_endpoint.instance_id, named_endpoint.api_origin) == (
                endpoint.instance_id,
                endpoint.api_origin,
            )
            webapp_cli(host, env, "--status", expected=f"Serving at {endpoint.api_origin}")
            yield named_endpoint, query_identify(home, timeout=2)


async def browser_connection(stack, endpoint, credential):
    import httpx
    from hermes_cli.gateway_client import GATEWAY_WS_PROTOCOL, GATEWAY_WS_TICKET_PREFIX
    from websockets.asyncio.client import connect

    origin = endpoint.api_origin
    try:
        async with httpx.AsyncClient(base_url=origin, trust_env=False, timeout=4) as http:
            answer = await http.post(
                "/api/webapp/socket-ticket",
                params={"socket": "gateway", "profile": PROFILE},
                headers={"X-Hermes-Session-Token": credential.decode().strip(), "Origin": origin},
            )
            answer.raise_for_status()
            ticket = answer.json()["ticket"]
        browser = await stack.enter_async_context(
            connect(
                origin.replace("http:", "ws:", 1) + "/api/ws?native_dial=browser",
                origin=origin,
                subprotocols=[GATEWAY_WS_PROTOCOL, GATEWAY_WS_TICKET_PREFIX + ticket],
                proxy=None,
                open_timeout=5,
                close_timeout=2,
            )
        )
    except Exception:
        failed = True
    else:
        failed = False
    if failed:
        pytest.fail("Native same-origin browser ticket admission failed", pytrace=False)
    assert browser.subprotocol == GATEWAY_WS_PROTOCOL
    return browser


async def verify_active_signout(host, installs):
    from hermes_cli.gateway_client import GatewayClient, connect_gateway
    from hermes_cli.gateway_runtime_discovery import query_identify

    async def assert_chat(client, label):
        result = await client.rpc("session.list", title=TITLE, include_hidden=True, _timeout=5)
        session_id = f"fixture-{label}-{PROFILE}"
        assert [(row["id"], row["resolved_id"]) for row in result["sessions"]] == [
            (session_id, session_id)
        ]

    async with asyncio.timeout(50), AsyncExitStack() as stack:
        browser_sockets = {}
        browser_clients = {}
        native_clients = {}
        credentials = {}
        for label, (home, _, endpoint, _) in installs.items():
            credentials[label] = read_private_credential(home / TOKEN_PATH)
            browser_sockets[label] = await browser_connection(stack, endpoint, credentials[label])
            browser_clients[label] = await stack.enter_async_context(
                GatewayClient(browser_sockets[label])
            )
            native_clients[label] = await stack.enter_async_context(
                connect_gateway(endpoint=endpoint)
            )
            await assert_chat(browser_clients[label], label)
            await assert_chat(native_clients[label], label)

        def equal_credentials():
            return hmac.compare_digest(credentials["a"], credentials["b"])

        assert not equal_credentials()
        before = history_snapshot(installs)
        assert len(before) == 4
        assert all(
            len(sessions) == len(messages) == 1 and not admissions
            for sessions, messages, admissions in before.values()
        )
        target_env = installs["a"][1]
        await asyncio.to_thread(
            webapp_cli,
            host,
            target_env,
            "--sign-out",
            expected="Signed out of every Webapp tab: closed 1 browser connection.",
        )
        target_socket = browser_sockets["a"]
        async with asyncio.timeout(10):
            await target_socket.wait_closed()
        assert target_socket.close_code == 4401

        # Keep these three original clients. A reconnect would hide a lost connection.
        await assert_chat(native_clients["a"], "a")
        await assert_chat(browser_clients["b"], "b")
        await assert_chat(native_clients["b"], "b")
        assert history_snapshot(installs) == before
        for home, env, endpoint, identity in installs.values():
            current = query_identify(home, timeout=2)
            assert (current["pid"], current["instance_id"]) == (
                identity["pid"],
                identity["instance_id"],
            )
            await asyncio.to_thread(
                webapp_cli, host, env, "--status", expected=f"Serving at {endpoint.api_origin}"
            )

        def credential_unchanged(label):
            home = installs[label][0]
            return hmac.compare_digest(
                read_private_credential(home / TOKEN_PATH), credentials[label]
            )

        assert not credential_unchanged("a")
        assert credential_unchanged("b")


def test_native_webapp_signout_closes_only_selected_install_browser(tmp_path_factory, monkeypatch):
    assert sys.platform == "linux", "This acceptance uses the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    with (
        tempfile.TemporaryDirectory(prefix="ws-", dir=tmp_path_factory.getbasetemp()) as private,
        monkeypatch.context() as isolated,
    ):
        root = Path(private)
        guard = root / "guard"
        guard.mkdir(mode=0o700)
        (guard / "sitecustomize.py").write_text(
            "from native_bot_socket_guard import activate_child\nactivate_child()\n",
            encoding="utf-8",
        )
        env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
        env.update(
            HOME=str(root),
            HERMES_ENABLE_PROJECT_PLUGINS="0",
            HERMES_DISABLE_LAZY_INSTALLS="1",
            PYTHONPATH=os.pathsep.join(
                (str(guard), str(host), str(Path(__file__).resolve().parent))
            ),
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            HERMES_BOT_ACCEPTANCE_ROOT=str(root),
        )
        for command, expected in (
            (["rev-parse", "HEAD"], pin),
            (["status", "--porcelain", "--untracked-files=no"], ""),
        ):
            actual = subprocess.check_output(
                ["git", *command],
                cwd=host,
                env=env,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            assert actual.strip() == expected

        for key in tuple(os.environ):
            if key not in env:
                isolated.delenv(key)
        for key, value in env.items():
            isolated.setenv(key, value)
        isolated.syspath_prepend(str(host))
        isolated.setattr(tempfile, "tempdir", str(root))
        deactivate = activate(root)
        try:
            ports = distinct_ports()
            restrict = activate(root, dial_ports=ports, dial_host="127.0.0.1")
            try:
                home_a, env_a = prepare_install(root / "a", env, ports[0])
                home_b, env_b = prepare_install(root / "b", env, ports[1])
                with (
                    serving_install(host, home_a, env_a, ports[0], isolated) as first,
                    serving_install(host, home_b, env_b, ports[1], isolated) as second,
                ):
                    assert first[0].instance_id != second[0].instance_id
                    assert first[1]["pid"] != second[1]["pid"]
                    asyncio.run(
                        verify_active_signout(
                            host, {"a": (home_a, env_a, *first), "b": (home_b, env_b, *second)}
                        )
                    )
            finally:
                restrict()
        finally:
            deactivate()
