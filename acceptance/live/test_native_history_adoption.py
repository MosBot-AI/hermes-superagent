"""Manual acceptance of local operator adoption of a compressed legacy Bot Chat."""

import asyncio
import json
import os
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

REPO = Path(__file__).resolve().parents[2]
PROFILE = "scout"
ROOT_ID = "fixture-canonical-root"
TIP_ID = "fixture-canonical-tip"
ROOT_MARKER = "Synthetic original root message"
TIP_MARKER = "Synthetic continuation message"
DECOY_MARKER = "Synthetic default profile message"
HISTORICAL_USER = "basic:synthetic-historical-login"
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


def seed_history(home, scout):
    from hermes_state import SessionDB

    for profile in (home, scout):
        (profile / "config.yaml").write_text(json.dumps(CONFIG), encoding="utf-8")
        (profile / "models_dev_cache.json").write_text(
            '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
            encoding="utf-8",
        )
        with SessionDB(profile / "state.db") as db:
            session_id = TIP_ID if profile == home else ROOT_ID
            db.create_session(
                session_id,
                source="desktop",
                user_id=HISTORICAL_USER,
                model="unused-fixture",
                cwd=str(profile),
            )
            assert db.set_session_title(session_id, "Bot Chat")
            assert db.set_session_hidden(session_id, True)
            if profile == home:
                db.append_message(session_id, "user", DECOY_MARKER)
                continue

            db.append_message(ROOT_ID, "user", ROOT_MARKER)
            holder = "synthetic-compression"
            assert db.try_acquire_compression_lock(ROOT_ID, holder)
            try:
                # Native atomic storage publication of a synthetic handoff, without a model.
                db.publish_compression_child(
                    parent_session_id=ROOT_ID,
                    child_session_id=TIP_ID,
                    source="desktop",
                    messages=[{"role": "user", "content": TIP_MARKER}],
                    model="unused-fixture",
                    cwd=str(profile),
                    compression_lock_holder=holder,
                )
            finally:
                db.release_compression_lock(ROOT_ID, holder)
            assert db.set_session_hidden(TIP_ID, True)
            db.end_session(TIP_ID, "session_switch")
            assert db.get_compression_tip(ROOT_ID) == TIP_ID
            for sid, source, principal in (
                ("foreign", "desktop", "telegram:41"),
                ("scheduled", "cron", None),
            ):
                db.create_session(
                    sid, source=source, user_id=principal, model="unused-fixture", cwd=str(profile)
                )
                db.append_message(sid, "user", "Synthetic excluded record")


def inventory(home):
    from hermes_state_local import POLICY_PREFIX
    from hermes_state_local_migration import LEGACY_PREFIX

    with closing(sqlite3.connect((home / "state.db").as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        meta = db.execute(
            "SELECT key, value FROM state_meta WHERE key LIKE ? OR key LIKE ?",
            (POLICY_PREFIX + "%", LEGACY_PREFIX + "%"),
        )
        sessions = db.execute(
            "SELECT id,title,hidden,parent_session_id,source,session_key,chat_id,user_id,"
            "end_reason "
            "FROM sessions ORDER BY id"
        )
        return {
            "bindings": {row["key"]: json.loads(row["value"]) for row in meta},
            "sessions": {row["id"]: dict(row) for row in sessions},
            "messages": [
                tuple(row)
                for row in db.execute("SELECT session_id,role,content FROM messages ORDER BY id")
            ],
            "admissions": db.execute("SELECT count(*) FROM session_admissions").fetchone()[0],
        }


def adopt(host, env, *flags, expected):
    result = subprocess.run(
        [sys.executable, "-m", "hermes_cli.main", "-p", PROFILE, "sessions", "adopt", *flags],
        cwd=host,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=35,
        umask=0o077,
    )
    if result.returncode or not all(marker in result.stdout for marker in expected):
        pytest.fail(
            "Native scoped sessions adopt did not confirm the expected outcome", pytrace=False
        )


def verify_adoption(before, after, scout):
    from gateway.owner_identity import host_owner_subject
    from hermes_state_local import POLICY_PREFIX
    from hermes_state_local_migration import LEGACY_PREFIX

    principal = host_owner_subject()
    legacy_key, policy_key = LEGACY_PREFIX + TIP_ID, POLICY_PREFIX + TIP_ID
    assert before["bindings"] == {}
    assert set(after["bindings"]) == {legacy_key, policy_key}
    assert after["bindings"][legacy_key] == {
        "session_id": TIP_ID,
        "legacy_session_id": TIP_ID,
        "profile_id": str(scout),
        "principal_id": principal,
    }
    policy = after["bindings"][policy_key]
    assert policy["session_id"] == policy["legacy_session_id"] == TIP_ID
    assert policy["profile_id"] == str(scout)
    assert policy["principal_id"] == principal
    assert before["messages"] == after["messages"]
    assert before["admissions"] == after["admissions"] == 0
    assert set(after["sessions"]) == set(before["sessions"])

    old_tip = before["sessions"][TIP_ID]
    new_tip = after["sessions"][TIP_ID]
    assert old_tip["user_id"] == HISTORICAL_USER
    assert old_tip["parent_session_id"] == ROOT_ID
    assert old_tip["session_key"] is None and old_tip["chat_id"] is None
    assert new_tip["session_key"] == policy["route"]
    assert new_tip == old_tip | {
        "session_key": policy["route"],
        "chat_id": TIP_ID,
        "user_id": principal,
    }
    for sid in (ROOT_ID, "foreign", "scheduled"):
        assert after["sessions"][sid] == before["sessions"][sid]


async def verify_named_reads(endpoint):
    from hermes_cli.gateway_client import GatewayRPCError, connect_gateway

    async with asyncio.timeout(18), connect_gateway(endpoint=endpoint) as client:
        listed = await client.rpc("session.list", title="Bot Chat", include_hidden=True, _timeout=4)
        assert [(row["id"], row["resolved_id"]) for row in listed["sessions"]] == [
            (ROOT_ID, TIP_ID)
        ]
        for sid in (ROOT_ID, TIP_ID):
            resumed = await client.rpc("session.resume", session_id=sid, _timeout=4)
            assert resumed["session_id"] == resumed["stored_session_id"] == TIP_ID
            assert [(message["role"], message["content"]) for message in resumed["messages"]] == [
                ("user", ROOT_MARKER),
                ("user", TIP_MARKER),
            ]
            await client.rpc(
                "session.detach",
                session_id=TIP_ID,
                subscription_id=resumed["subscription_id"],
                _timeout=4,
            )

        for operands, reason in (
            ({"session_id": TIP_ID, "profile": "default"}, "profile_mismatch"),
            ({"session_id": "foreign"}, "not_found"),
        ):
            with pytest.raises(GatewayRPCError) as refusal:
                await client.rpc("session.resume", _timeout=4, **operands)
            assert (refusal.value.code, refusal.value.data["reason"]) == (4001, reason)


def verify_owned_gateway(host, root, home, scout, env):
    from hermes_cli import gateway_client
    from hermes_cli.gateway_runtime import discover_gateway_endpoint
    from hermes_cli.gateway_runtime_discovery import query_identify

    assert Path(gateway_client.__file__).resolve().is_relative_to(host)
    seed_history(home, scout)
    with gateway_daemon(host, home, env, "history-adoption") as gateway:
        identity = query_identify(home, timeout=2)
        observed = discover_gateway_endpoint(scout, timeout=2)
        assert observed.state == "ready" and observed.endpoint is not None
        endpoint = observed.endpoint
        assert endpoint.profile_id == str(scout)
        assert (endpoint.instance_id, endpoint.api_origin) == (
            gateway.instance_id,
            gateway.api_origin,
        )
        port = urlsplit(gateway.api_origin).port
        assert port is not None
        cli_env = env | {"HERMES_NATIVE_ACCEPTANCE_DIAL_PORT": str(port)}

        initial, default = inventory(scout), inventory(home)
        assert not default["bindings"] and default["admissions"] == 0
        assert default["messages"] == [(TIP_ID, "user", DECOY_MARKER)]
        assert set(default["sessions"]) == {TIP_ID}
        assert default["sessions"][TIP_ID]["title"] == "Bot Chat"
        assert initial["sessions"][ROOT_ID]["title"] == "Bot Chat"
        assert initial["sessions"][ROOT_ID]["end_reason"] == "compression"
        assert initial["sessions"][ROOT_ID]["hidden"] == initial["sessions"][TIP_ID]["hidden"] == 1

        eligible = "1 pre-gateway chat(s) to adopt (1 desktop)"
        adopt(host, cli_env, "--dry-run", expected=(eligible, "Dry run: nothing was adopted."))
        assert inventory(scout) == initial
        assert inventory(home) == default
        adopt(host, cli_env, expected=(eligible, "Adopted 1 chat(s)."))
        adopted = inventory(scout)
        verify_adoption(initial, adopted, scout)
        assert inventory(home) == default
        adopt(host, cli_env, expected=("Nothing to adopt:",))
        assert inventory(scout) == adopted
        assert inventory(home) == default

        deactivate = activate(root, dial_ports=(port,), dial_host="127.0.0.1")
        try:
            asyncio.run(verify_named_reads(endpoint))
        finally:
            deactivate()
        assert inventory(scout) == adopted
        assert inventory(home) == default
        current = query_identify(home, timeout=2)
        assert (current["pid"], current["instance_id"]) == (
            identity["pid"],
            identity["instance_id"],
        )


def test_native_named_cli_adopts_the_original_compressed_history(tmp_path_factory, monkeypatch):
    assert sys.platform == "linux", "This acceptance uses the Linux private control socket"
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    pin = json.loads((REPO / "compatibility.json").read_bytes())["hermes_commit"]
    with (
        tempfile.TemporaryDirectory(prefix="ha-", dir=tmp_path_factory.getbasetemp()) as private,
        monkeypatch.context() as isolated,
    ):
        root = Path(private)
        home, user, scratch, runtime, xdg, bundled, guard = (
            root / name for name in ("h", "user", "tmp", "rt", "xdg", "bundled", "guard")
        )
        scout = home / "profiles" / PROFILE
        for directory in (home, scout, user, scratch, runtime, xdg, bundled, guard):
            directory.mkdir(mode=0o700, parents=True)
        assert len(os.fsencode(home / "gateway.sock")) <= 100, "Fixture socket path too long"
        (guard / "sitecustomize.py").write_text(
            "from native_bot_socket_guard import activate_child\nactivate_child()\n",
            encoding="utf-8",
        )
        env = {name: os.environ[name] for name in ("PATH", "LANG", "TZ") if name in os.environ}
        absent_bus = f"unix:path={xdg}/absent"
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
            DBUS_SESSION_BUS_ADDRESS=absent_bus,
            DBUS_SYSTEM_BUS_ADDRESS=absent_bus,
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
            output = subprocess.check_output(
                ["git", *command],
                cwd=host,
                env=env,
                text=True,
                timeout=10,
                stdin=subprocess.DEVNULL,
            )
            assert output.strip() == expected

        for key in tuple(os.environ):
            if key not in env:
                isolated.delenv(key)
        for key, value in env.items():
            isolated.setenv(key, value)
        isolated.syspath_prepend(str(host))
        isolated.setattr(tempfile, "tempdir", str(scratch))
        deactivate = activate(root)
        try:
            verify_owned_gateway(host, root, home, scout, env)
        finally:
            deactivate()
