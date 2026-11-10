"""Explicit live acceptance: installed production package, real native transport.

Never collected by the normal unit suite. Run only in an isolated supported host
with HERMES_TEST_ROOT, HERMES_RUNTIME_PACKAGE and HERMES_SOURCE_COMMIT supplied.
No model turn, provider credential, fabricated runner or direct database write.
"""

import asyncio
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def checked(command, *, cwd, env):
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
        check=True,
    )


@pytest.fixture
def installed(tmp_path):
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve()
    package = Path(os.environ["HERMES_RUNTIME_PACKAGE"]).resolve()
    source = os.environ["HERMES_SOURCE_COMMIT"]
    pin = json.loads((ROOT / "compatibility.json").read_text())["hermes_commit"]
    assert (
        subprocess.check_output(["git", "-C", str(host), "rev-parse", "HEAD"], text=True).strip()
        == pin
    )
    assert json.loads((package / "PROVENANCE.json").read_text())["source_commit"] == source
    # Only transport/process helpers are reused, never the upstream fake model
    # peer, harness, fake fixture runner or prompt tests.
    sys.path.insert(0, str(host))
    spec = importlib.util.spec_from_file_location(
        "pinned_native_helpers", host / "tests/gateway/test_unified_gateway_native_live.py"
    )
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    home, user = tmp_path / "profile", tmp_path / "user"
    home.mkdir(mode=0o700)
    user.mkdir(mode=0o700)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "TZ") if key in os.environ}
    env.update(
        HOME=str(user),
        HERMES_HOME=str(home),
        PYTHONUNBUFFERED="1",
        HERMES_RUNTIME_DIR=str(tmp_path / "runtime"),
    )
    config = {
        "gateway": {"multiplex_profiles": False},
        "auxiliary": {"title_generation": {"enabled": False}},
        "platform_toolsets": {"cli": []},
        "plugins": {
            "isolation": "in_process",
            "entries": {
                "hermes-personal-agent": {
                    "settings": {"mode": "local_tasks", "local_conversation": True}
                }
            },
        },
    }
    (home / "config.yaml").write_text(json.dumps(config))
    # Official installer performs its normal scan and enable flow. A scan denial
    # fails the test: there are deliberately no bypass/force/allow-removed flags.
    # Installation may use the runner's existing proxy/CA routing, but no model
    # credentials. The Gateway receives the smaller env above, not this copy.
    install_env = dict(env)
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    ):
        if key in os.environ:
            install_env[key] = os.environ[key]
    checked(
        [
            sys.executable,
            "-m",
            "hermes_cli.main",
            "plugins",
            "install",
            package.as_uri(),
            "--yes-deps",
            "--enable",
        ],
        cwd=host,
        env=install_env,
    )
    yield home, env, helpers
    sys.path.remove(str(host))


def test_packaged_task_commands_survive_real_gateway_restart(installed):
    home, env, live = installed
    add = 'personal-tasks --json add "Synthetic live acceptance" --request-id live-add'

    async def command(ws, sid, raw):
        result = await live.ok(ws, "slash.exec", session_id=sid, command=raw)
        assert result["type"] == "exec", result
        payload = json.loads(result["output"])
        assert payload["schema_version"] == "personal.local-conversation-tasks.v1"
        return payload

    async def create(desc):
        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus

        with pytest.raises(InvalidStatus):
            async with connect(desc["api_origin"].replace("http:", "ws:") + "/api/ws"):
                pass
        async with live.websocket(home, desc) as ws:
            created = await live.ok(
                ws,
                "session.create",
                request_id="live-session",
                source="cli",
                cwd=str(home),
                toolsets=[],
            )
            sid = created["session_id"]
            await live.ok(ws, "session.resume", session_id=sid)
            captured = await command(ws, sid, add)
            assert captured["status"] == "ok", captured
            task = captured["data"]
            assert task["revision"] == 1
            replay = await command(ws, sid, add)
            assert replay["replayed"] is True and replay["data"] == task
            changed = await command(
                ws,
                sid,
                f"personal-tasks --json update {task['id']} --expected-revision 1 "
                '--title "Updated synthetic task" --request-id live-update',
            )
            assert changed["status"] == "ok" and changed["data"]["revision"] == 2
            stale = await command(
                ws,
                sid,
                f"personal-tasks --json update {task['id']} --expected-revision 1 "
                '--title "Must not overwrite" --request-id live-stale',
            )
            assert stale["status"] == "error"
            assert stale["error"]["code"] == "revision_conflict"
            invalid = await command(ws, sid, "personal-tasks --json add")
            assert invalid["status"] == "error"
            return sid, task["id"]

    with live.daemon(home, env, "first.log") as (proc, first, _):
        sid, task_id = asyncio.run(create(first))
        assert live.planned_stop(home, proc, first) == 0
    assert live.control_absent(home)
    assert not live.port_open(live.api_port(first))

    async def resume(desc):
        async with live.websocket(home, desc) as ws:
            snapshot = await live.ok(ws, "session.resume", session_id=sid)
            assert snapshot["session_id"] == sid
            shown = await command(ws, sid, f"personal-tasks --json show {task_id}")
            assert shown["status"] == "ok"
            assert shown["data"]["revision"] == 2
            assert shown["data"]["title"] == "Updated synthetic task"
            replay = await command(ws, sid, add)
            assert replay["replayed"] is True and replay["data"]["id"] == task_id
            listed = await command(ws, sid, "personal-tasks --json list --state all")
            assert [item["id"] for item in listed["data"]["items"]] == [task_id]

    with live.daemon(home, env, "second.log") as (proc, second, _):
        assert second["instance_id"] != first["instance_id"]
        asyncio.run(resume(second))
        assert live.planned_stop(home, proc, second) == 0
    assert live.control_absent(home)
    assert not live.port_open(live.api_port(second))
    # Independent read-only integrity oracle; test never writes canonical state.
    task_db = home / "plugin-data/hermes-personal-agent/tasks.sqlite3"
    assert task_db.is_file()
    for database in (home / "state.db", task_db):
        assert database.is_file()
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with closing(sqlite3.connect(task_db.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("SELECT id, revision, title FROM tasks").fetchall() == [
            (task_id, 2, "Updated synthetic task")
        ]
