"""Manual acceptance of an officially installed plugin in a canonical Bot Chat."""

import asyncio
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from native_bot_socket_guard import activate
from native_gateway_fixture import gateway_daemon
from test_native_bot_receipt import refuse_old_instance
from test_packaged_gateway_tasks import installed as installed

TITLE = "Bot Chat"
TASK = "合成 Bot Chat 验收任务"
ADD = f'personal-tasks --json add "{TASK}" --request-id packaged-bot-add'


def verify_install(home, package, source):
    plugin = home / "plugins/hermes-personal-agent"
    assert plugin.resolve().is_relative_to(home)
    manifest = (plugin / "PROVENANCE.json").read_bytes()
    assert manifest == (package / "PROVENANCE.json").read_bytes()
    provenance = json.loads(manifest)
    assert provenance["source_commit"] == source
    for entry in provenance["files"]:
        installed_file = plugin / entry["path"]
        assert installed_file.resolve().is_relative_to(plugin.resolve())
        assert hashlib.sha256(installed_file.read_bytes()).hexdigest() == entry["sha256"]


def configure_command_only(home, env):
    from ruamel.yaml import YAML

    root = home.parent
    guard, bundled = root / "guard", root / "bundled"
    guard.mkdir(mode=0o700)
    bundled.mkdir(mode=0o700)
    (guard / "sitecustomize.py").write_text(
        "try:\n"
        "    from native_bot_socket_guard import activate_child\n"
        "    activate_child()\n"
        "except Exception:\n"
        "    raise SystemExit('Could not load the packaged Bot socket audit') from None\n",
        encoding="utf-8",
    )
    path = home / "config.yaml"
    yaml = YAML()
    config = yaml.load(path)
    config["webapp"] = {"enabled": False}
    config["telemetry"] = {"shared_metrics": {"enabled": False}}
    yaml.dump(config, path)
    (home / "models_dev_cache.json").write_text(
        '{"hermes-test-offline":{"id":"hermes-test-offline","env":[],"models":{}}}',
        encoding="utf-8",
    )
    return env | {
        "HERMES_BOT_ACCEPTANCE_ROOT": str(root),
        "HERMES_BUNDLED_PLUGINS": str(bundled),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "HERMES_DISABLE_LAZY_INSTALLS": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(guard), str(Path(__file__).resolve().parent))),
    }


async def lookup(client):
    result = await client.rpc("profiles.list", _timeout=6)
    (profile,) = result["profiles"]
    assert profile["name"] == "default"
    listed = await client.rpc("session.list", title=TITLE, include_hidden=True, _timeout=6)
    canonical = profile["canonical_session"]
    pairs = [(row["id"], row["resolved_id"]) for row in listed["sessions"]]
    assert pairs == ([(canonical["id"], canonical["resolved_id"])] if canonical else [])
    return pairs


async def command(client, sid, raw):
    result = await client.rpc("slash.exec", session_id=sid, command=raw, _timeout=8)
    assert result["type"] == "exec"
    payload = json.loads(result["output"])
    assert payload["schema_version"] == "personal.local-conversation-tasks.v1"
    assert payload["status"] == "ok"
    return payload


async def open_chat(client, sid):
    assert await lookup(client) == [(sid, sid)]
    resumed = await client.rpc("session.resume", session_id=sid, _timeout=8)
    assert resumed["session_id"] == resumed["stored_session_id"] == sid
    assert resumed["messages"] == []


async def create_and_capture(client, home):
    assert await lookup(client) == []
    result = await client.rpc(
        "session.create",
        request_id="packaged-bot-canonical",
        title=TITLE,
        source="cli",
        hidden=True,
        cwd=str(home),
        toolsets=[],
        _timeout=8,
    )
    sid = result["session_id"]
    await open_chat(client, sid)
    task = (await command(client, sid, ADD))["data"]
    assert task["title"] == TASK and task["revision"] == 1
    return sid, task


async def confirm_after_restart(client, sid, task):
    await open_chat(client, sid)
    shown = await command(client, sid, f"personal-tasks --json show {task['id']}")
    assert shown["data"] == task
    replay = await command(client, sid, ADD)
    assert replay["replayed"] is True and replay["data"] == task


async def use_gateway(endpoint, root, action, *args):
    from hermes_cli.gateway_client import connect_gateway
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    port = urlsplit(endpoint.api_origin).port
    assert port is not None
    deactivate = activate(root, dial_ports=(port,), dial_host="127.0.0.1")
    try:
        async with asyncio.timeout(35):
            url = endpoint.api_origin.replace("http:", "ws:", 1) + "/api/ws"
            with pytest.raises(InvalidStatus):
                async with connect(url, open_timeout=5, proxy=None):
                    pass
            async with connect_gateway(endpoint=endpoint) as client:
                return await action(client, *args)
    finally:
        deactivate()


def verify_saved_state(home, sid, task_id):
    with closing(sqlite3.connect((home / "state.db").as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT id,title,hidden,parent_session_id FROM sessions").fetchall() == [
            (sid, TITLE, 1, None)
        ]
        assert db.execute("SELECT count(*) FROM session_admissions").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM messages").fetchone() == (0,)
    task_db = home / "plugin-data/hermes-personal-agent/tasks.sqlite3"
    with closing(sqlite3.connect(task_db.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT id,revision,title FROM tasks").fetchall() == [(task_id, 1, TASK)]


def test_installed_task_commands_reopen_original_canonical_bot_chat(installed, monkeypatch):
    home, env, _ = installed
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve(strict=True)
    package = Path(os.environ["HERMES_RUNTIME_PACKAGE"]).resolve(strict=True)
    verify_install(home, package, os.environ["HERMES_SOURCE_COMMIT"])
    child_env = configure_command_only(home, env)
    for key in ("HOME", "HERMES_HOME", "HERMES_RUNTIME_DIR"):
        monkeypatch.setenv(key, env[key])

    with gateway_daemon(host, home, child_env, "packaged-bot-first") as first:
        sid, task = asyncio.run(use_gateway(first, home.parent, create_and_capture, home))

    with gateway_daemon(host, home, child_env, "packaged-bot-second") as second:
        assert second.instance_id != first.instance_id
        assert second.authority_epoch > first.authority_epoch
        refuse_old_instance(home, first.instance_id)
        asyncio.run(use_gateway(second, home.parent, confirm_after_restart, sid, task))

    verify_saved_state(home, sid, task["id"])
