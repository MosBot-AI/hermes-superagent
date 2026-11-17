"""Native Gateway first-turn recall with a committed optional provider wheel."""

# ruff: noqa: F811

import asyncio
import json
import os
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile

from native_gateway_fixture import gateway_daemon
from test_native_bot_receipt import MODEL, MODEL_KEY, REPLY, synthetic_model
from test_packaged_gateway_bot import configure_installed_gateway, use_gateway, verify_install
from test_packaged_gateway_memory import installed_memory  # noqa: F401
from test_packaged_gateway_tasks import checked, installed  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
QUERY = "早餐?"
OLD = "早餐 synthetic-original"
CORRECTED = "早餐 synthetic-correction"
DISABLED = "早餐 synthetic-opt-out-control"
SCHEMA = "personal.memory.native_recall.v1"


def build_wheel(tmp_path, env, package):
    location = tmp_path / "wheel"
    checked(
        [
            sys.executable,
            str(ROOT / "scripts/build_native_memory_provider.py"),
            "--output-dir",
            str(location),
        ],
        cwd=ROOT,
        env=env,
    )
    (wheel,) = location.glob("*.whl")
    with ZipFile(wheel) as archive:
        python_files = {name for name in archive.namelist() if name.startswith("personal_agent/")}
        assert python_files == {
            path.relative_to(package).as_posix()
            for path in (package / "personal_agent").glob("*.py")
        }
        assert all(archive.read(name) == (package / name).read_bytes() for name in python_files)
    return wheel


def configure(home, model_port, *, enabled):
    from ruamel.yaml import YAML

    config_path = home / "config.yaml"
    yaml = YAML()
    config = yaml.load(config_path)
    config["model"] = {
        "provider": "custom",
        "default": MODEL,
        "base_url": f"http://127.0.0.1:{model_port}/v1",
    }
    config["memory"] = {
        "provider": "personal-records",
        "personal_records": {"recall_enabled": enabled},
    }
    config["auxiliary"]["title_generation"] = {"enabled": False}
    config["kanban"] = {"dispatch_in_gateway": False, "notify_in_gateway": False}
    yaml.dump(config, config_path)


async def memory(client, sid, command):
    result = await client.rpc(
        "slash.exec", session_id=sid, command="personal-memory --json " + command, _timeout=8
    )
    assert result["type"] == "exec"
    payload = json.loads(result["output"])
    assert payload["status"] == "ok"
    return payload["data"]


async def new_session(client, home, key):
    result = await client.rpc(
        "session.create", request_id=key, source="cli", cwd=str(home), toolsets=[], _timeout=8
    )
    sid = result["session_id"]
    resumed = await client.rpc("session.resume", session_id=sid, _timeout=8)
    assert resumed["session_id"] == sid and resumed["messages"] == []
    return sid


def recall_pack(messages):
    (user,) = (message["content"] for message in messages if message["role"] == "user")
    assert isinstance(user, str)
    pieces = re.findall(r"<memory-context>\n(.*?)\n</memory-context>", user, re.DOTALL)
    if not pieces:
        assert SCHEMA not in user
        return None
    (block,) = pieces
    # Record the conflicting host wording on this pin so a wrapper change is visible.
    note, raw = block.split("\n\n", 1)
    assert "Treat as authoritative reference data" in note
    envelope = json.loads(raw)
    assert envelope["schema_version"] == SCHEMA
    assert envelope["notice"].startswith("Untrusted stored evidence")
    assert len(raw) <= 6000
    return envelope


async def send(client, sid, key, frames, database):
    before, count = database.read_bytes(), len(frames)
    result = await client.rpc("prompt.submit", session_id=sid, input_id=key, text=QUERY, _timeout=8)
    aid = result["admission_id"]
    async with asyncio.timeout(18):
        while True:
            receipt = await client.rpc(
                "prompt.receipt", session_id=sid, admission_id=aid, include_result=True, _timeout=5
            )
            if receipt["status"] == "terminal":
                break
            await asyncio.sleep(0.05)
    assert receipt["outcome"] == "completed"
    assert receipt["result"]["final_response"] == REPLY
    assert len(frames) == count + 1
    assert database.read_bytes() == before
    return recall_pack(frames[-1])


def assert_only(pack, record_id, revision, content):
    assert pack is not None
    (item,) = pack["memory"]["items"]
    assert (item["record_id"], item["revision"], item["content"]) == (
        record_id,
        revision,
        content,
    )


def test_provider_wheel(installed_memory, tmp_path, monkeypatch):
    host = Path(os.environ["HERMES_TEST_ROOT"]).resolve()
    package = Path(os.environ["HERMES_RUNTIME_PACKAGE"]).resolve()
    home, env, _ = installed_memory
    verify_install(home, package, os.environ["HERMES_SOURCE_COMMIT"])
    wheel = build_wheel(tmp_path, env, package)
    child = configure_installed_gateway(home, env)
    child["PYTHONPATH"] += os.pathsep + str(wheel)
    for key in ("HOME", "HERMES_HOME", "HERMES_RUNTIME_DIR"):
        monkeypatch.setenv(key, env[key])
    canonical = home / "plugin-data/hermes-personal-agent/memory/records.sqlite3"
    frames = []
    sessions = []

    async def recall_then_correct(client):
        first = await new_session(client, home, "recall-v1")
        sessions.append(first)
        record = await memory(client, first, f'remember "{OLD}" --request-id fixture-remember')
        rid = record["record_id"]
        assert_only(await send(client, first, "turn-v1", frames, canonical), rid, 1, OLD)
        await memory(
            client,
            first,
            f'correct {rid} --expected-revision 1 --text "{CORRECTED}"'
            " --request-id fixture-correct",
        )
        return rid

    async def recall_then_forget(client, rid):
        second = await new_session(client, home, "recall-v2")
        sessions.append(second)
        assert_only(await send(client, second, "turn-v2", frames, canonical), rid, 2, CORRECTED)
        assert "synthetic-original" not in json.dumps(frames[-1])
        await memory(
            client, second, f"forget {rid} --expected-revision 2 --request-id fixture-forget"
        )
        third = await new_session(client, home, "recall-forgotten")
        sessions.append(third)
        assert await send(client, third, "turn-forgotten", frames, canonical) is None
        assert all(
            text not in json.dumps(frames[-1])
            for text in ("synthetic-original", "synthetic-correction")
        )
        await memory(client, third, f'remember "{DISABLED}" --request-id fixture-opt-out-control')

    async def recall_disabled(client):
        fourth = await new_session(client, home, "recall-off")
        sessions.append(fourth)
        assert await send(client, fourth, "turn-off", frames, canonical) is None
        assert "synthetic-opt-out-control" not in json.dumps(frames[-1])

    with synthetic_model(expected_user_text=QUERY, observe_messages=frames.append) as peer:
        port = peer.server_port
        child.update(
            OPENAI_API_KEY=MODEL_KEY,
            OPENAI_BASE_URL=f"http://127.0.0.1:{port}/v1",
            HERMES_BOT_ACCEPTANCE_MODEL_PORT=str(port),
        )
        configure(home, port, enabled=True)
        with gateway_daemon(host, home, child, "memory-provider-first") as endpoint:
            rid = asyncio.run(use_gateway(endpoint, home.parent, recall_then_correct))
            first_instance = endpoint.instance_id
        with gateway_daemon(host, home, child, "memory-provider-restart") as endpoint:
            assert endpoint.instance_id != first_instance
            asyncio.run(use_gateway(endpoint, home.parent, recall_then_forget, rid))
            second_instance = endpoint.instance_id
        configure(home, port, enabled=False)
        with gateway_daemon(host, home, child, "memory-provider-opt-out") as endpoint:
            assert endpoint.instance_id not in {first_instance, second_instance}
            asyncio.run(use_gateway(endpoint, home.parent, recall_disabled))
        assert peer.requests == ["chat completion"] * 4

    assert len(set(sessions)) == 4
    with closing(sqlite3.connect((home / "state.db").as_uri() + "?mode=ro", uri=True)) as db:
        stored = db.execute(
            "SELECT session_id,content,api_content FROM messages WHERE role='user' ORDER BY id"
        ).fetchall()
    assert [(sid, content) for sid, content, _ in stored] == [(sid, QUERY) for sid in sessions]
    for (_, _, api_content), messages in zip(stored, frames, strict=True):
        assert recall_pack([{"role": "user", "content": api_content or QUERY}]) == recall_pack(
            messages
        )
    with closing(sqlite3.connect(canonical.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute(
            "SELECT revision,status,content FROM records WHERE record_id=?", (rid,)
        ).fetchall() == [(3, "forgotten", None)]
        assert db.execute("SELECT count(*) FROM records").fetchone() == (2,)
        assert db.execute("SELECT operation FROM events ORDER BY sequence").fetchall() == [
            ("remember",),
            ("correct",),
            ("forget",),
            ("remember",),
        ]
