"""Manual evidence for a live profile rename and its retained canonical chat route."""

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon
from test_native_profile_retirement import (
    CONFIG,
    TITLE,
    inventory,
    lock_held,
    seed_chats,
    wait_for_profiles,
)

REPO = Path(__file__).resolve().parents[2]
OLD = "scout"
NEW = "renamed"
SIBLINGS = ("default", "watch")
LABEL = "profile-rename"


def activate_rename_cli(root, host):
    """Fence service-related side effects in the real CLI child."""
    denied = root / "rename-cli-audit-denied"

    def block():
        denied.touch(mode=0o600)
        raise PermissionError("Rename fixture operation outside private custody")

    def private_path(value, dir_fd):
        return (
            dir_fd == -1
            and isinstance(value, (str, bytes, os.PathLike))
            and Path(os.fsdecode(value)).resolve().is_relative_to(root)
        )

    def inspect_operation(event, args):
        if event == "subprocess.Popen":
            executable, command, cwd, _ = args
            binary = Path(os.fsdecode(executable)).name
            directory = Path(cwd or Path.cwd()).resolve()
            # Native startup provenance and alias collision probes are read-only.
            if not (
                binary == "which"
                and command == ["which", NEW]
                or binary == "git"
                and directory == host
                and command[1:] == ["rev-parse", "HEAD"]
                or binary == "git"
                and command[1:] == ["-C", str(host), "rev-parse", "HEAD"]
            ):
                block()
        elif event == "os.kill":
            if args[1] != 0:
                block()
        elif event in {
            "os.system",
            "os.posix_spawn",
            "os.exec",
            "os.fork",
            "os.forkpty",
            "os.killpg",
        }:
            block()
        elif event in {"os.remove", "os.rmdir"}:
            if not private_path(*args):
                block()
        elif event == "os.rename":
            source, destination, source_fd, destination_fd = args
            if not private_path(source, source_fd) or not private_path(destination, destination_fd):
                block()

    sys.addaudithook(inspect_operation)
    try:
        sys.audit("os.kill", 1, signal.SIGTERM)
    except PermissionError:
        denied.unlink()
        (root / "rename-cli-audit-ready").touch(mode=0o600, exist_ok=False)
    else:
        raise RuntimeError("Rename fixture CLI guard did not activate")


def rename_profile(host, home, env):
    for unit_name in ("hermes-gateway", f"hermes-gateway-{OLD}"):
        unit = Path("/etc/systemd/system") / f"{unit_name}.service"
        assert not (unit.exists() or unit.is_symlink()), "Rename fixture found a real system unit"
    assert Path("/proc/1/comm").read_text().strip() != "s6-svscan", (
        "Rename fixture requires an inactive s6 supervisor"
    )
    result = subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", "profile", "rename", OLD, NEW],
        cwd=host,
        env=env | {"HERMES_RENAME_FIXTURE_CLI": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=38,
        umask=0o077,
    )
    assert (home.parent / "rename-cli-audit-ready").is_file()
    assert not (home.parent / "rename-cli-audit-denied").exists(), (
        "Native CLI attempted an operation outside the private fixture"
    )
    if (
        result.returncode
        or f"Renamed {OLD} → {NEW}" not in result.stdout
        or "live gateway could not migrate session identity" in result.stderr
    ):
        pytest.fail("Native CLI did not confirm the expected live rename", pytrace=False)


def stored_route(home, session):
    uri = (home / "state.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        return db.execute("SELECT session_key FROM sessions WHERE id=?", (session,)).fetchone()[0]


async def verify_rename(host, env, homes, workspace, endpoint):
    from gateway.status import get_process_start_time
    from hermes_cli.gateway_client import (
        GATEWAY_WS_PROTOCOL,
        GatewayClient,
        GatewayRPCError,
        _session_ticket,
        gateway_ws_target,
    )
    from hermes_cli.profiles import read_profile_meta
    from websockets.asyncio.client import connect

    home = homes["default"]
    identity = await wait_for_profiles(homes, homes)
    pid, instance = identity
    assert instance == endpoint.instance_id
    start = get_process_start_time(pid)
    assert start is not None
    ticket = await asyncio.to_thread(_session_ticket, home, endpoint, scope="host")
    url, protocols = gateway_ws_target(endpoint, ticket)
    async with (
        asyncio.timeout(68),
        connect(url, subprotocols=protocols, open_timeout=5, close_timeout=2, proxy=None) as socket,
        GatewayClient(socket) as client,
    ):
        assert socket.subprotocol == GATEWAY_WS_PROTOCOL

        async def lookup(profile):
            result = await client.rpc(
                "session.list", profile=profile, title=TITLE, include_hidden=True, _timeout=5
            )
            return [(row["id"], row["resolved_id"]) for row in result["sessions"]]

        async def roster():
            result = await client.rpc("profiles.list", _timeout=5)
            return {row["name"]: row for row in result["profiles"]}

        async def assert_siblings():
            for profile in SIBLINGS:
                sid = f"fixture-retained-{profile}"
                assert await lookup(profile) == [(sid, sid)]

        await assert_siblings()
        controls = {name: inventory(homes[name]) for name in SIBLINGS}
        created = await client.rpc(
            "session.create",
            profile=OLD,
            request_id="fixture-live-profile-rename",
            source="cli",
            title=TITLE,
            hidden=True,
            cwd=str(workspace),
            toolsets=[],
            ignore_rules=True,
            _timeout=8,
        )
        session = created["session_id"]
        assert await lookup(OLD) == [(session, session)]
        mounted = await client.rpc("session.resume", profile=OLD, session_id=session, _timeout=5)
        assert mounted["session_id"] == session and mounted["messages"] == []
        before_roster = await roster()
        canonical = before_roster[OLD]["canonical_session"]
        assert (canonical["id"], canonical["resolved_id"]) == (session, session)
        before = inventory(homes[OLD])
        assert before[0][1] == instance
        assert before[1:] == ([(session, TITLE, 1, None)], [], [])
        old_route_key = stored_route(homes[OLD], session)
        assert old_route_key.startswith(f"agent:{OLD}:")

        await asyncio.to_thread(rename_profile, host, home, env)
        old_home = homes.pop(OLD)
        renamed = homes[NEW] = old_home.with_name(NEW)
        assert not old_home.exists() and renamed.is_dir()
        assert OLD in read_profile_meta(renamed)["previous_names"]
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == start

        after_roster = await roster()
        assert set(after_roster) == set(homes)
        assert after_roster[NEW]["canonical_session"] == canonical
        with pytest.raises(GatewayRPCError) as old_route:
            await lookup(OLD)
        assert (old_route.value.code, old_route.value.data.get("reason")) == (
            4001,
            "profile_mismatch",
        )
        with pytest.raises(GatewayRPCError) as title_lookup:
            await lookup(NEW)
        assert (title_lookup.value.code, title_lookup.value.data.get("reason")) == (
            4001,
            "storage_unavailable",
        )
        for method in ("session.resume", "session.info"):
            with pytest.raises(GatewayRPCError) as named_read:
                await client.rpc(method, profile=NEW, session_id=session, _timeout=5)
            assert (named_read.value.code, named_read.value.data.get("reason")) == (
                4001,
                "storage_unavailable",
            )
        # Test a fixed synthetic diagnostic predicate without displaying the private log.
        marker = (
            f"Local session {session} receipt refused: "
            "ValueError: route mismatch at _checked_entry:"
        ).encode()
        cause_seen = marker in (home.parent / f"{LABEL}.log").read_bytes()
        assert cause_seen

        await assert_siblings()
        assert {name: inventory(homes[name]) for name in SIBLINGS} == controls
        after = inventory(renamed)
        assert after[0] == (before[0][0] + 1, instance)
        assert after[1:] == before[1:]
        assert stored_route(renamed, session) == f"agent:{NEW}:" + old_route_key.removeprefix(
            f"agent:{OLD}:"
        )
        assert await wait_for_profiles(homes, homes) == identity
        assert get_process_start_time(pid) == start


def test_native_live_rename_retains_roster_but_refuses_canonical_chat_reads(
    tmp_path_factory, monkeypatch
):
    assert sys.platform == "linux", "Live rename requires the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    with (
        tempfile.TemporaryDirectory(prefix="rn-", dir=tmp_path_factory.getbasetemp()) as private,
        monkeypatch.context() as isolated,
    ):
        root = Path(private)
        home, user, runtime, xdg, scratch, bundled, guard, workspace = (
            root / name for name in ("h", "u", "rt", "xdg", "tmp", "bundled", "guard", "workspace")
        )
        for directory in (home, user, runtime, xdg, scratch, bundled, guard, workspace):
            directory.mkdir(mode=0o700)
        assert len(os.fsencode(home / "gateway.sock")) <= 100, "Fixture socket path too long"
        (guard / "sitecustomize.py").write_text(
            "import os\n"
            "from pathlib import Path\n"
            "try:\n"
            "    from native_bot_socket_guard import activate_child\n"
            "    activate_child()\n"
            "    if os.environ.get('HERMES_RENAME_FIXTURE_CLI') == '1':\n"
            "        from test_native_profile_rename import activate_rename_cli\n"
            "        root = Path(os.environ['HERMES_BOT_ACCEPTANCE_ROOT'])\n"
            "        activate_rename_cli(root, Path.cwd())\n"
            "except Exception:\n"
            "    raise SystemExit('Could not load the profile rename fixture audit') from None\n",
            encoding="utf-8",
        )
        env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
        bus = f"unix:path={xdg}/absent"
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
            DBUS_SESSION_BUS_ADDRESS=bus,
            DBUS_SYSTEM_BUS_ADDRESS=bus,
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=os.pathsep.join(
                (str(guard), str(host), str(Path(__file__).resolve().parent))
            ),
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
        isolated.setattr(tempfile, "tempdir", str(scratch))
        deactivate = activate(root)
        try:
            from hermes_cli import gateway_client

            assert Path(gateway_client.__file__).resolve().is_relative_to(host)
            homes = {"default": home, "watch": home / "profiles/watch"}
            seed_chats(homes)
            scout = homes[OLD] = home / f"profiles/{OLD}"
            scout.mkdir(mode=0o700)
            (scout / "config.yaml").write_text(json.dumps(CONFIG), encoding="utf-8")
            (scout / "models_dev_cache.json").write_bytes(
                (home / "models_dev_cache.json").read_bytes()
            )
            with gateway_daemon(host, home, env, LABEL) as endpoint:
                port = urlsplit(endpoint.api_origin).port
                restrict = activate(root, dial_ports=(port,), dial_host="127.0.0.1")
                try:
                    asyncio.run(verify_rename(host, env, homes, workspace, endpoint))
                finally:
                    restrict()
            assert all(not lock_held(profile) for profile in homes.values())
        finally:
            deactivate()
