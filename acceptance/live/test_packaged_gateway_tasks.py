"""Explicit live acceptance: installed production package, real native transport.

Never collected by the normal unit suite. Run only in an isolated supported host
with HERMES_TEST_ROOT, HERMES_RUNTIME_PACKAGE and HERMES_SOURCE_COMMIT supplied.
No model turn, provider credential, fabricated runner or direct database write.
"""

import asyncio
import importlib.util
import json
import os
import shlex
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
        # Pinned host requires a non-empty model label in a restorable session
        # policy even for command-only sessions. This is metadata, not a call.
        "model": {"default": "deepseek-v4.1-flash"},
        "auxiliary": {"title_generation": {"enabled": False}},
        "platform_toolsets": {"cli": []},
        "plugins": {
            "isolation": "in_process",
            "entries": {
                "hermes-personal-agent": {
                    "settings": {
                        "mode": "local_tasks",
                        "local_conversation": True,
                        "local_model_tools": True,
                    }
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


def project_plan_command():
    """Synthetic explicit plan, including forward references; not model output."""
    tasks = [
        {"title": "审核中文草稿", "depends_on": [2]},
        {"title": "整理中文草稿", "details": "合成验收数据，不发送外部消息"},
        {"title": "确认项目记录", "depends_on": [1, 2]},
    ]
    return (
        'personal-tasks --json plan --project "中文项目验收" --request-id live-project-plan '
        "--tasks-json " + shlex.quote(json.dumps(tasks, ensure_ascii=False))
    )


def test_packaged_project_plan_dependencies_focus_and_restart(installed):
    home, env, live = installed
    project = "中文项目验收"
    plan = project_plan_command()
    initial_receipt = None
    completed_receipts = {}

    async def slash(ws, sid, raw, *, tools=False):
        result = await live.ok(ws, "slash.exec", session_id=sid, command=raw)
        assert result["type"] == "exec", result
        payload = json.loads(result["output"])
        expected = (
            "personal.session-task-tools.v1" if tools else "personal.local-conversation-tasks.v1"
        )
        assert payload["schema_version"] == expected
        return payload

    async def ready(ws, sid):
        result = await slash(ws, sid, f'personal-tasks --json ready --project "{project}"')
        assert result["status"] == "ok", result
        return [item["id"] for item in result["data"]["items"]]

    async def create(desc):
        nonlocal initial_receipt
        async with live.websocket(home, desc) as ws:
            created = await live.ok(
                ws,
                "session.create",
                request_id="live-plan-session",
                source="cli",
                cwd=str(home),
                toolsets=[],
            )
            sid = created["session_id"]
            await live.ok(ws, "session.resume", session_id=sid)
            captured = await slash(ws, sid, plan)
            assert captured["status"] == "ok", captured
            initial_receipt = captured["data"]
            review, draft, publish = initial_receipt["items"]
            assert [item["title"] for item in (review, draft, publish)] == [
                "审核中文草稿",
                "整理中文草稿",
                "确认项目记录",
            ]
            assert all(
                item["revision"] == 1 and item["project"] == project
                for item in (review, draft, publish)
            )
            assert review["dependencies"] == [
                {"task_id": draft["id"], "revision": 1, "state": "captured"}
            ]
            assert {item["task_id"] for item in publish["dependencies"]} == {
                review["id"],
                draft["id"],
            }
            assert draft["dependencies"] == []
            assert await ready(ws, sid) == [draft["id"]]
            projects = await slash(ws, sid, "personal-tasks --json projects")
            assert projects["data"]["items"] == [
                {"project": project, "captured": 3, "done": 0, "cancelled": 0, "total": 3}
            ]
            listed = await slash(ws, sid, f'personal-tasks --json list --project "{project}"')
            assert {item["id"] for item in listed["data"]["items"]} == {
                item["id"] for item in initial_receipt["items"]
            }
            replay = await slash(ws, sid, plan)
            assert replay["replayed"] is True and replay["data"] == initial_receipt
            conflicting = await slash(ws, sid, plan.replace("审核中文草稿", "改变后的草稿"))
            assert conflicting["error"]["code"] == "idempotency_conflict"

            enabled = await slash(ws, sid, "personal-tools enable-read", tools=True)
            assert enabled["status"] == "ok" and enabled["data"]["access"] == "read"
            selected = await slash(ws, sid, f"personal-tools focus {review['id']}", tools=True)
            assert selected["data"]["focus_task_id"] == review["id"]
            assert selected["data"]["revision_at_selection"] == 1
            # Selection is checked; no model turn/context injection is claimed.
            updated = await slash(
                ws,
                sid,
                f"personal-tasks --json update {draft['id']} "
                '--expected-revision 1 --details "补充中文验收细节" '
                "--request-id live-plan-edit",
            )
            assert updated["status"] == "ok" and updated["data"]["revision"] == 2
            assert updated["data"]["details"] == "补充中文验收细节"
            stale = await slash(
                ws,
                sid,
                f"personal-tasks --json update {draft['id']} "
                '--expected-revision 1 --details "不得覆盖更新" --request-id live-plan-stale',
            )
            assert stale["status"] == "error" and stale["error"]["code"] == "revision_conflict"
            unchanged = await slash(ws, sid, f"personal-tasks --json show {draft['id']}")
            assert unchanged["data"] == updated["data"]
            for task in (review, publish):
                refused = await slash(
                    ws,
                    sid,
                    f"personal-tasks --json done {task['id']} "
                    '--expected-revision 1 --note "不得提前完成" '
                    f"--request-id blocked-{task['id']}",
                )
                assert refused["status"] == "error"
                assert refused["error"]["code"] == "dependencies_unsatisfied"
                current = await slash(ws, sid, f"personal-tasks --json show {task['id']}")
                assert current["data"]["state"] == "captured" and current["data"]["revision"] == 1

            for task, revision, expected_ready in (
                (draft, 2, [review["id"]]),
                (review, 1, [publish["id"]]),
                (publish, 1, []),
            ):
                raw = (
                    f"personal-tasks --json done {task['id']} --expected-revision {revision} "
                    f"--note 已核对合成记录 --request-id done-{task['id']}"
                )
                completed = await slash(ws, sid, raw)
                assert completed["status"] == "ok", completed
                assert completed["data"]["state"] == "done"
                assert completed["data"]["revision"] == revision + 1
                completed_receipts[task["id"]] = (raw, completed["data"])
                assert await ready(ws, sid) == expected_ready
            disabled = await slash(ws, sid, "personal-tools disable", tools=True)
            assert disabled["status"] == "ok" and disabled["data"]["access"] == "disabled"
            status = await slash(ws, sid, "personal-tools status", tools=True)
            assert status["data"]["access"] == "disabled"
            assert status["data"]["focus_task_id"] is None
            # This verifies operator metadata only, not model-tool refusal.
            enabled = await slash(ws, sid, "personal-tools enable-read", tools=True)
            assert enabled["data"]["access"] == "read"
            focused = await slash(ws, sid, f"personal-tools focus {publish['id']}", tools=True)
            assert focused["data"]["focus_task_id"] == publish["id"]
            assert focused["data"]["revision_at_selection"] == 2
            status = await slash(ws, sid, "personal-tools status", tools=True)
            assert status["data"]["access"] == "read"
            assert status["data"]["focus_task_id"] == publish["id"]
            return sid

    with live.daemon(home, env, "project-first.log") as (proc, first, _):
        sid = asyncio.run(create(first))
        assert live.planned_stop(home, proc, first) == 0
    assert live.control_absent(home)
    assert not live.port_open(live.api_port(first))

    async def resume(desc):
        async with live.websocket(home, desc) as ws:
            snapshot = await live.ok(ws, "session.resume", session_id=sid)
            assert snapshot["session_id"] == sid
            state = await slash(ws, sid, "personal-tools status", tools=True)
            assert state["data"]["access"] == "disabled"
            assert state["data"]["focus_task_id"] is None
            # Restart clears activation/focus. This does not prove a model-tool
            # invocation was refused: this test intentionally submits no prompt.
            assert await ready(ws, sid) == []
            projects = await slash(ws, sid, "personal-tasks --json projects")
            assert projects["data"]["items"] == [
                {"project": project, "captured": 0, "done": 3, "cancelled": 0, "total": 3}
            ]
            for task_id, (raw, receipt) in completed_receipts.items():
                current = await slash(ws, sid, f"personal-tasks --json show {task_id}")
                assert current["data"]["state"] == "done"
                assert current["data"]["revision"] == receipt["revision"]
                assert current["data"]["dependencies_satisfied"] is True
                replay = await slash(ws, sid, raw)
                assert replay["replayed"] is True and replay["data"] == receipt
            plan_replay = await slash(ws, sid, plan)
            assert plan_replay["replayed"] is True and plan_replay["data"] == initial_receipt
            assert all(
                item["state"] == "captured" and item["revision"] == 1
                for item in plan_replay["data"]["items"]
            )
            listed = await slash(
                ws, sid, f'personal-tasks --json list --state all --project "{project}"'
            )
            assert {item["id"] for item in listed["data"]["items"]} == set(completed_receipts)

    with live.daemon(home, env, "project-second.log") as (proc, second, _):
        assert second["instance_id"] != first["instance_id"]
        asyncio.run(resume(second))
        assert live.planned_stop(home, proc, second) == 0
    assert live.control_absent(home)
    assert not live.port_open(live.api_port(second))
    task_db = home / "plugin-data/hermes-personal-agent/tasks.sqlite3"
    for database in (home / "state.db", task_db):
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    with closing(sqlite3.connect(task_db.as_uri() + "?mode=ro", uri=True)) as db:
        assert set(db.execute("SELECT id,revision,state FROM tasks").fetchall()) == {
            (task_id, receipt["revision"], "done")
            for task_id, (_, receipt) in completed_receipts.items()
        }
        review, draft, publish = initial_receipt["items"]
        assert set(
            db.execute("SELECT task_id,dependency_id FROM task_dependencies").fetchall()
        ) == {
            (review["id"], draft["id"]),
            (publish["id"], review["id"]),
            (publish["id"], draft["id"]),
        }
        assert {row[0] for row in db.execute("SELECT request_id FROM receipts")} == {
            "live-project-plan",
            "live-plan-edit",
            *[f"done-{task_id}" for task_id in completed_receipts],
        }
        assert db.execute("SELECT count(*) FROM events").fetchone() == (7,)
        assert db.execute("SELECT count(*) FROM receipts").fetchone() == (5,)
        assert db.execute(
            "SELECT count(*) FROM events WHERE operation='capture_plan'"
        ).fetchone() == (3,)


def test_packaged_explicit_priorities_and_next_work_survive_restart(installed):
    home, env, live = installed
    tasks = [
        {"title": "优先但待前置完成", "priority": "high", "depends_on": [2]},
        {"title": "先完成前置", "priority": "low"},
        {"title": "普通独立任务", "priority": "normal", "due_date": "2030-01-02"},
    ]
    plan = (
        'personal-tasks --json plan --project "优先级验收" --request-id priority-plan '
        "--tasks-json " + shlex.quote(json.dumps(tasks, ensure_ascii=False))
    )
    initial = None

    async def command(ws, sid, raw):
        result = await live.ok(ws, "slash.exec", session_id=sid, command=raw)
        assert result["type"] == "exec", result
        value = json.loads(result["output"])
        assert value["schema_version"] == "personal.local-conversation-tasks.v1"
        return value

    async def next_ids(ws, sid):
        result = await command(ws, sid, 'personal-tasks --json next --project "优先级验收"')
        assert result["status"] == "ok", result
        assert result["data"]["authority"] == "planning_data_not_permission_or_dispatch"
        assert result["data"]["total"] == 2 and result["data"]["omitted"] == 0
        return [item["id"] for item in result["data"]["items"]]

    async def create(desc):
        nonlocal initial
        async with live.websocket(home, desc) as ws:
            created = await live.ok(
                ws,
                "session.create",
                request_id="priority-session",
                source="cli",
                cwd=str(home),
                toolsets=[],
            )
            sid = created["session_id"]
            await live.ok(ws, "session.resume", session_id=sid)
            result = await command(ws, sid, plan)
            assert result["status"] == "ok", result
            initial = result["data"]
            blocked, prerequisite, normal = initial["items"]
            assert [item["priority"] for item in initial["items"]] == ["high", "low", "normal"]
            assert await next_ids(ws, sid) == [normal["id"], prerequisite["id"]]
            old_ready = await command(ws, sid, 'personal-tasks --json ready --project "优先级验收"')
            assert [item["id"] for item in old_ready["data"]["items"]] == [
                prerequisite["id"],
                normal["id"],
            ]
            edit = await command(
                ws,
                sid,
                f"personal-tasks --json update {prerequisite['id']} --priority high "
                "--expected-revision 1 --request-id priority-edit",
            )
            assert edit["status"] == "ok" and edit["data"]["revision"] == 2
            assert edit["data"]["priority"] == "high"
            assert await next_ids(ws, sid) == [prerequisite["id"], normal["id"]]
            stale = await command(
                ws,
                sid,
                f"personal-tasks --json update {prerequisite['id']} --priority low "
                "--expected-revision 1 --request-id priority-stale",
            )
            assert stale["error"]["code"] == "revision_conflict"
            current = await command(ws, sid, f"personal-tasks --json show {prerequisite['id']}")
            assert current["data"] == edit["data"]
            finished = await command(
                ws,
                sid,
                f"personal-tasks --json done {prerequisite['id']} "
                '--expected-revision 2 --note "前置记录已核对" --request-id priority-done',
            )
            assert finished["status"] == "ok" and finished["data"]["revision"] == 3
            assert await next_ids(ws, sid) == [blocked["id"], normal["id"]]
            return sid

    with live.daemon(home, env, "priority-first.log") as (proc, first, _):
        sid = asyncio.run(create(first))
        assert live.planned_stop(home, proc, first) == 0
    assert live.control_absent(home) and not live.port_open(live.api_port(first))

    async def resume(desc):
        async with live.websocket(home, desc) as ws:
            snapshot = await live.ok(ws, "session.resume", session_id=sid)
            assert snapshot["session_id"] == sid
            blocked, prerequisite, normal = initial["items"]
            assert await next_ids(ws, sid) == [blocked["id"], normal["id"]]
            current = await command(ws, sid, f"personal-tasks --json show {prerequisite['id']}")
            assert current["data"]["priority"] == "high"
            assert current["data"]["state"] == "done" and current["data"]["revision"] == 3
            replay = await command(ws, sid, plan)
            assert replay["replayed"] is True and replay["data"] == initial
            assert replay["data"]["items"][1]["priority"] == "low"

    with live.daemon(home, env, "priority-second.log") as (proc, second, _):
        assert second["instance_id"] != first["instance_id"]
        asyncio.run(resume(second))
        assert live.planned_stop(home, proc, second) == 0
    assert live.control_absent(home) and not live.port_open(live.api_port(second))
    task_db = home / "plugin-data/hermes-personal-agent/tasks.sqlite3"
    with closing(sqlite3.connect(task_db.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        blocked, prerequisite, normal = initial["items"]
        assert set(db.execute("SELECT id,priority,state,revision FROM tasks")) == {
            (blocked["id"], "high", "captured", 1),
            (prerequisite["id"], "high", "done", 3),
            (normal["id"], "normal", "captured", 1),
        }
        assert db.execute("SELECT count(*) FROM events").fetchone() == (5,)
        assert {row[0] for row in db.execute("SELECT request_id FROM receipts")} == {
            "priority-plan",
            "priority-edit",
            "priority-done",
        }
