"""Pinned native Kanban consumer contracts, not adapter or live-worker acceptance.

Only disposable blocked, unassigned, pathless scratch cards are archived. Native
archive can terminate workers, promote dependencies and remove workspaces; those
branches are deliberately excluded. No receipts are manufactured with SQL.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def _child_main():
    import argparse
    import io
    import shutil
    import socket
    from contextlib import redirect_stderr, redirect_stdout
    from dataclasses import asdict

    forbidden = []

    def deny(*_args, **_kwargs):
        forbidden.append("network, process launch, signal or workspace deletion")
        raise AssertionError(forbidden[-1])

    # A pytest monkeypatch cannot protect a restarted interpreter. These are
    # fail-closed safety guards, never successful replacements for native APIs.
    socket.create_connection = deny
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    subprocess.Popen = deny
    os.kill = deny
    shutil.rmtree = deny

    from hermes_cli import kanban as cli
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_connect as kbc

    parser = argparse.ArgumentParser()
    cli.build_parser(parser.add_subparsers(dest="command"))
    results = []
    for step in json.load(sys.stdin):
        if "argv" in step:
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.kanban_command(parser.parse_args(["kanban", *step["argv"]]))
            results.append({"code": code, "stdout": stdout.getvalue(), "stderr": stderr.getvalue()})
        elif "board" in step:
            # Public native metadata API: an explicit scratch must NOT inherit
            # a project default (no actual repository or workspace is supplied).
            kb.create_board(step["board"], name="Synthetic board", project_id="unresolved-project")
            results.append(True)
        else:
            board = step.get("inspect", "default")
            with kb.scoped_current_board(board), kbc.connect_closing(board=board) as conn:
                cards = kb.list_tasks(conn, include_archived=True)
                if "archive" in step:
                    task = kb.get_task(conn, step["archive"])
                    if task is not None:
                        assert task.status in {"blocked", "archived"}
                        assert task.assignee is None and task.worker_pid is None
                        assert task.workspace_kind == "scratch" and task.workspace_path is None
                        assert not kb.parent_ids(conn, task.id) and not kb.child_ids(conn, task.id)
                        assert kb.list_runs(conn, task.id) == []
                    results.append(kb.archive_task(conn, step["archive"]))
                else:
                    results.append(
                        [
                            {
                                "task": asdict(kb.get_task(conn, card.id)),
                                "events": [
                                    asdict(event) for event in kb.list_events(conn, card.id)
                                ],
                                "runs": [asdict(run) for run in kb.list_runs(conn, card.id)],
                            }
                            for card in cards
                        ]
                    )
        assert not forbidden, forbidden  # Also catch swallowed best-effort failures.
    assert not list(Path(os.environ["HERMES_HOME"]).rglob("workspaces"))
    print(json.dumps(results))


def restart(home, steps):
    import hermes_cli

    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    env = {
        "PATH": os.defpath,
        "HOME": str(home.parent / "os-home"),
        "HERMES_HOME": str(home),
        "HERMES_KANBAN_HOME": str(home),
        "HERMES_RUNTIME_DIR": str(home.parent / "runtime"),
        "HERMES_BUNDLED_PLUGINS": str(home.parent / "bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONPATH": os.pathsep.join(
            (str(Path(hermes_cli.__file__).resolve().parents[1]), str(Path(__file__).parent))
        ),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from test_native_kanban_lifecycle import _child_main; _child_main()",
        ],
        input=json.dumps(steps),
        cwd=home,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return json.loads(result.stdout)


def create(title="Synthetic card", body="Synthetic body", board="default", key="same-key"):
    return {
        "argv": [
            "--board",
            board,
            "create",
            title,
            "--body",
            body,
            "--workspace",
            "scratch",
            "--initial-status",
            "blocked",
            "--idempotency-key",
            key,
            "--json",
        ]
    }


def output(result):
    assert result["code"] == 0, result
    assert result["stderr"] == ""
    return json.loads(result["stdout"])


def assert_parked(receipt):
    task = receipt["task"]
    assert task["status"] == "blocked"
    assert task["assignee"] is None and task["worker_pid"] is None
    assert task["workspace_kind"] == "scratch" and task["workspace_path"] is None
    assert task["project_id"] is None and task["current_run_id"] is None
    assert receipt["runs"] == []
    assert [event["kind"] for event in receipt["events"]] == ["created", "blocked"]
    assert all(event["run_id"] is None for event in receipt["events"])
    assert receipt["events"][0]["payload"]["status"] == "blocked"


def test_native_consumer_create_show_list_and_real_receipts(tmp_path):
    home = tmp_path / "private"
    created, inspected = restart(home, [create(), {"inspect": "default"}])
    card = output(created)
    assert len(inspected) == 1
    assert_parked(inspected[0])
    assert card["id"] == inspected[0]["task"]["id"]
    shown, listed = restart(
        home,
        [
            {"argv": ["show", card["id"], "--json"]},
            {"argv": ["list", "--json"]},
        ],
    )
    assert output(shown)["task"]["id"] == card["id"]
    assert output(shown)["runs"] == []
    assert [event["kind"] for event in output(shown)["events"]] == ["created", "blocked"]
    assert [task["id"] for task in output(listed)] == [card["id"]]


def test_native_same_key_changed_payload_returns_original_after_restart(tmp_path):
    home = tmp_path / "private"
    created, before = restart(home, [create(), {"inspect": "default"}])
    replay, after = restart(home, [create(title="Changed", body="Changed"), {"inspect": "default"}])
    assert output(replay) == output(created)
    assert after == before  # No new card, mutated payload, event or run.
    assert_parked(after[0])


def test_native_archive_replay_missing_and_archived_key_reuse(tmp_path):
    home = tmp_path / "private"
    created = output(restart(home, [create()])[0])
    card_id = created["id"]
    archived, before = restart(home, [{"archive": card_id}, {"inspect": "default"}])
    assert archived is True
    assert before[0]["task"]["status"] == "archived"
    assert [event["kind"] for event in before[0]["events"]] == ["created", "blocked", "archived"]
    assert before[0]["runs"] == []
    replay, missing, after = restart(
        home,
        [
            {"archive": card_id},
            {"archive": "t_00000000"},
            {"inspect": "default"},
        ],
    )
    assert replay is False and missing is False
    assert after == before
    replacement, cards = restart(home, [create(title="Replacement"), {"inspect": "default"}])
    new_id = output(replacement)["id"]
    assert new_id != card_id
    by_id = {item["task"]["id"]: item for item in cards}
    assert set(by_id) == {card_id, new_id}
    assert by_id[card_id] == before[0]
    assert_parked(by_id[new_id])
    listed = output(restart(home, [{"argv": ["list", "--json"]}])[0])
    assert [item["id"] for item in listed] == [new_id]


def test_native_board_separation_and_explicit_scratch_override(tmp_path):
    home = tmp_path / "private"
    _, default, named, first, second = restart(
        home,
        [
            {"board": "separate"},
            create(),
            create(board="separate"),
            {"inspect": "default"},
            {"inspect": "separate"},
        ],
    )
    default_id, named_id = output(default)["id"], output(named)["id"]
    assert default_id != named_id
    assert len(first) == len(second) == 1
    assert_parked(first[0])
    assert_parked(second[0])
    archived, default_after, named_after = restart(
        home,
        [
            {"inspect": "separate", "archive": named_id},
            {"inspect": "default"},
            {"inspect": "separate"},
        ],
    )
    assert archived is True
    assert default_after == first
    assert named_after[0]["task"]["status"] == "archived"
    assert named_after[0]["runs"] == []


def test_native_consumer_archive_keeps_queryable_history(tmp_path):
    home = tmp_path / "private"
    card_id = output(restart(home, [create()])[0])["id"]
    archived, shown, listed = restart(
        home,
        [
            {"argv": ["archive", card_id]},
            {"argv": ["show", card_id, "--json"]},
            {"argv": ["list", "--json"]},
        ],
    )
    assert archived["code"] == 0
    assert f"Archived {card_id}" in archived["stdout"]
    shown = output(shown)
    assert shown["task"]["status"] == "archived" and shown["runs"] == []
    assert [event["kind"] for event in shown["events"]] == ["created", "blocked", "archived"]
    assert output(listed) == []
