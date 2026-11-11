"""Manual installed-package acceptance, real Gateway and native Kanban storage.

Native results below are manually authored synthetic operator fixtures, NOT
worker execution or provider evidence. No model turns or SQL mutations occur.
"""

# ruff: noqa: F811

import asyncio
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest
from test_packaged_gateway_memory import Gateway
from test_packaged_gateway_tasks import checked, installed  # noqa: F401

BOARD = "synthetic-handoff"
RESULT = "Manually authored synthetic native result 中文. NOT worker execution."
CHANGED_RESULT = RESULT + " Operator amended the editable result."


def configure(home, *, enabled=True, board=BOARD):
    from ruamel.yaml import YAML

    yaml = YAML()
    path = home / "config.yaml"
    config = yaml.load(path)
    settings = config["plugins"]["entries"]["hermes-personal-agent"]["settings"]
    settings.update(kanban_handoff=enabled, kanban_handoff_board=board)
    yaml.dump(config, path)


def native_cli(env, *args):
    """Normal native operator commands, not plugin internals or SQL fixtures."""
    return checked(
        [sys.executable, "-m", "hermes_cli.main", "kanban", *args],
        cwd=Path(os.environ["HERMES_TEST_ROOT"]),
        env=env,
    )


@pytest.fixture
def installed_handoff(installed, tmp_path):
    home, env, live = installed
    root = tmp_path / "native-board-home"
    root.mkdir(mode=0o700)
    env["HERMES_KANBAN_HOME"] = str(root)
    configure(home)
    # Private files from initial creation, including subprocess-created sidecars.
    # Restore the caller's mask even on failure; never repair permissions later.
    previous = os.umask(0o077)
    try:
        native_cli(env, "boards", "create", BOARD)
        yield home, env, live
    finally:
        os.umask(previous)


class HandoffGateway(Gateway):
    def phase(self, sid, callback):
        async def run(desc):
            async with self.live.websocket(self.home, desc) as ws:
                resumed = await self.live.ok(ws, "session.resume", session_id=sid)
                assert resumed["session_id"] == sid

                async def call(text, error=None, *, readable=False):
                    result = await self.live.ok(ws, "slash.exec", session_id=sid, command=text)
                    assert result["type"] == "exec", result
                    if readable:
                        assert not result["output"].lstrip().startswith("{"), result
                        return result["output"]
                    payload = json.loads(result["output"])
                    expected = (
                        "personal.kanban-handoff.v1"
                        if text.startswith("personal-handoff")
                        else "personal.local-conversation-tasks.v1"
                    )
                    assert payload["schema_version"] == expected, payload
                    if error:
                        assert payload["status"] == "error", payload
                        assert payload["error"]["code"] == error, payload
                    else:
                        assert payload["status"] == "ok", payload
                    return payload

                return await callback(call)

        with self.start() as desc:
            return asyncio.run(run(desc))


def assert_operator_runs(runs, *, card_id, result):
    """Native complete synthesizes an ended row; this is NOT worker execution."""
    if result is None:
        assert runs == []  # No execution or completion before operator completion.
        return
    assert len(runs) == 1
    run = runs[0]
    assert run["task_id"] == card_id
    assert run["status"] == run["outcome"] == "completed"
    assert isinstance(run["id"], int) and run["id"] > 0
    assert isinstance(run["started_at"], int)
    assert run["started_at"] == run["ended_at"]
    assert run["summary"] == result
    assert all(
        run[field] is None
        for field in (
            "profile",
            "step_key",
            "claim_lock",
            "claim_expires",
            "worker_pid",
            "worker_started_at",
            "max_runtime_seconds",
            "last_heartbeat_at",
            "metadata",
            "error",
        )
    )


def oracle(gateway, *, card_id=None, status=None, result=None):
    """Read-only identity/count/integrity oracle, including operator-synthetic runs."""
    path = Path(gateway.env["HERMES_KANBAN_HOME"]) / "kanban/boards" / BOARD / "kanban.db"
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        rows = db.execute("SELECT * FROM tasks").fetchall()
        assert len(rows) == (1 if card_id else 0)
        runs = [dict(row) for row in db.execute("SELECT * FROM task_runs")]
        assert_operator_runs(runs, card_id=card_id, result=result)
        if card_id:
            card = dict(rows[0])
            assert card["id"] == card_id and card["status"] == status
            assert card["result"] == result
            assert card["assignee"] is None and card["current_run_id"] is None
            assert card["workspace_kind"] == "scratch"
            assert card["project_id"] is None and card["worker_pid"] is None
            return card


def assert_readable_review(text, review_digest, result):
    """Shared offline/live presentation check; no Gateway or storage access."""
    for value in ("untrusted", "not instructions", "not verified execution", review_digest, result):
        assert value.lower() in text.lower()


def test_installed_handoff_review_accept_and_restart(installed_handoff):
    gateway = HandoffGateway(installed_handoff)
    sid = gateway.create()
    oracle(gateway)

    async def capture_prepare(call):
        task = (
            await call(
                'personal-tasks --json add "Synthetic handoff 中文" --request-id handoff-add'
            )
        )["data"]
        preview = (
            await call(
                f"personal-handoff --json prepare {task['id']} --expected-revision 1 "
                "--request-id handoff-prepare"
            )
        )["data"]
        # Unflagged callers retain the pre-workbench JSON envelope.
        legacy = await call(f"personal-handoff show {preview['id']}")
        explicit = await call(f"personal-handoff --json show {preview['id']}")
        assert legacy == explicit
        assert legacy["data"] == preview
        assert preview["state"] == "prepared"
        assert preview["source"]["task_id"] == task["id"]
        assert preview["destination"]["board"] == BOARD
        assert Path(preview["destination"]["root"]) == Path(gateway.env["HERMES_KANBAN_HOME"])
        readable = await call(f"personal-handoff --text show {preview['id']}", readable=True)
        for value in (task["title"], preview["id"], preview["intent_digest"], BOARD):
            assert value in readable
        await call(
            f"personal-handoff --json commit {preview['id']} --expected-digest " + "0" * 64,
            error="intent_conflict",
        )
        return task, preview

    task, preview = gateway.phase(sid, capture_prepare)
    oracle(gateway)
    hid, tid = preview["id"], task["id"]
    commit = f"personal-handoff --json commit {hid} --expected-digest {preview['intent_digest']}"

    async def commit_phase(call):
        record = (await call(commit))["data"]
        assert record["state"] == "confirmed", record
        assert record["identity_state"] == "available"
        assert record["payload"] is None
        return record

    committed = gateway.phase(sid, commit_phase)
    identity = committed["native_identity"]
    cid = identity["card_id"]
    oracle(gateway, card_id=cid, status="blocked")

    async def reconcile(call):
        record = (await call(f"personal-handoff --json reconcile {hid}"))["data"]
        assert record["state"] == "confirmed" and record["native_identity"] == identity
        assert (await call(commit))["data"]["native_identity"] == identity
        synced = (
            await call(
                f"personal-handoff --json sync {hid} --task {tid} --expected-revision 1 "
                "--request-id sync-blocked"
            )
        )["data"]
        assert synced["state"] == "captured" and synced["revision"] == 2
        assert synced["native_progress"]["status"] == "blocked"
        review = (
            await call(f"personal-handoff --json review {hid} --task {tid} --expected-revision 2")
        )["data"]
        assert review["can_accept"] is False
        assert review["evidence"]["native"]["result_state"] == "not_done"

    gateway.phase(sid, reconcile)
    oracle(gateway, card_id=cid, status="blocked")
    # An explicit native operator marks this fixture done, not a worker or model.
    native_cli(gateway.env, "--board", BOARD, "complete", cid, "--result", RESULT)
    oracle(gateway, card_id=cid, status="done", result=RESULT)

    async def review_done(call):
        current = (await call(f"personal-tasks --json show {tid}"))["data"]
        assert current["state"] == "captured" and current["revision"] == 2
        synced = (
            await call(
                f"personal-handoff --json sync {hid} --task {tid} --expected-revision 2 "
                "--request-id sync-done"
            )
        )["data"]
        assert synced["state"] == "captured" and synced["revision"] == 3
        assert synced["native_progress"]["status"] == "done"
        text = await call(f"personal-tasks show {tid}", readable=True)
        assert "not local completion" in text.lower()
        args = f"review {hid} --task {tid} --expected-revision 3"
        reviewed = (await call("personal-handoff --json " + args))["data"]
        assert reviewed["can_accept"] is True
        assert reviewed["evidence"]["native"]["result"] == RESULT
        assert reviewed["evidence"]["identity"] == identity
        text = await call("personal-handoff --text " + args, readable=True)
        assert_readable_review(text, reviewed["review_digest"], RESULT)
        return reviewed

    reviewed = gateway.phase(sid, review_done)
    accept = (
        f"personal-handoff --json accept-review {hid} --task {tid} --expected-revision 3 "
        f"--expected-digest {reviewed['review_digest']} "
        '--note "Operator reviewed synthetic evidence; no worker execution claimed" '
        "--request-id accept-handoff"
    )
    native_cli(gateway.env, "--board", BOARD, "edit", cid, "--result", CHANGED_RESULT)

    async def stale_result(call):
        await call(accept, error="native_review_changed")
        assert (await call(f"personal-tasks --json show {tid}"))["data"]["revision"] == 3

    gateway.phase(sid, stale_result)
    # Re-review the changed evidence, never restore an old digest to force acceptance.
    configure(gateway.home, board="different-synthetic-board")

    async def wrong_destination(call):
        await call(
            f"personal-handoff --json review {hid} --task {tid} --expected-revision 3",
            error="destination_changed",
        )

    gateway.phase(sid, wrong_destination)
    configure(gateway.home, enabled=False)

    async def disabled_fresh_operations(call):
        await call(
            f"personal-handoff --json review {hid} --task {tid} --expected-revision 3",
            error="handoff_disabled",
        )
        await call(
            f"personal-handoff --json sync {hid} --task {tid} --expected-revision 3 "
            "--request-id disabled-sync",
            error="handoff_disabled",
        )
        await call(accept, error="handoff_disabled")
        current = (await call(f"personal-tasks --json show {tid}"))["data"]
        assert current["state"] == "captured" and current["revision"] == 3

    gateway.phase(sid, disabled_fresh_operations)
    configure(gateway.home)

    async def accept_current(call):
        document = (
            await call(f"personal-handoff --json review {hid} --task {tid} --expected-revision 3")
        )["data"]
        assert document["evidence"]["native"]["result"] == CHANGED_RESULT
        assert document["review_digest"] != reviewed["review_digest"]
        command = accept.replace(reviewed["review_digest"], document["review_digest"])
        await call(
            command.replace("--expected-revision 3", "--expected-revision 2"),
            error="revision_conflict",
        )
        receipt = await call(command)
        assert receipt["replayed"] is False
        assert receipt["data"]["task"]["state"] == "done"
        assert receipt["data"]["task"]["revision"] == 4
        assert receipt["data"]["review"]["card_id"] == cid
        assert RESULT not in json.dumps(receipt) and CHANGED_RESULT not in json.dumps(receipt)
        return command, receipt["data"]

    accepted_command, accepted = gateway.phase(sid, accept_current)
    oracle(gateway, card_id=cid, status="done", result=CHANGED_RESULT)
    configure(gateway.home, enabled=False)

    async def disabled_replay(call):
        replay = await call(accepted_command)
        assert replay["replayed"] is True and replay["data"] == accepted
        await call(
            accepted_command.replace("Operator reviewed", "Different conclusion"),
            error="idempotency_conflict",
        )
        fresh = (
            await call(
                'personal-tasks --json add "Disabled handoff probe" --request-id disabled-task'
            )
        )["data"]
        await call(
            f"personal-handoff --json prepare {fresh['id']} --expected-revision 1 "
            "--request-id disabled-prepare",
            error="handoff_disabled",
        )
        await call(f"personal-handoff --json reconcile {hid}", error="handoff_disabled")
        assert (await call(f"personal-handoff --json show {hid}"))["data"]["state"] == "confirmed"
        assert (await call(f"personal-tasks --json show {tid}"))["data"] == accepted["task"]

    gateway.phase(sid, disabled_replay)
    oracle(gateway, card_id=cid, status="done", result=CHANGED_RESULT)
    task_db = gateway.home / "plugin-data/hermes-personal-agent/tasks.sqlite3"
    with closing(sqlite3.connect(task_db.as_uri() + "?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute(
            "SELECT count(*) FROM receipts WHERE request_id='accept-handoff'"
        ).fetchone() == (1,)
        dump = "\n".join(db.iterdump())
        assert RESULT not in dump and CHANGED_RESULT not in dump
