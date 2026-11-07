"""Actual LOCAL sync commands; advisory metadata only, no native dispatch or model."""

import importlib
import json

import pytest
from test_kanban_handoff import board as board
from test_kanban_handoff import handoff, inspect_db, prepared
from test_kanban_handoff import handoff_host as handoff_host
from test_kanban_handoff import native as native
from test_local_conversation_tasks import command
from test_local_task_cli import PLUGIN_ID


def confirmed(host):
    source, preview = prepared(host)
    result = handoff(host, f"commit {preview['id']} --expected-digest {preview['intent_digest']}")
    assert result["status"] == "ok" and result["data"]["state"] == "confirmed", result
    return source, result["data"]


def sync(host, source, receipt, revision=1, key="sync-one"):
    return handoff(
        host,
        f"sync {receipt['id']} --task {source['id']} "
        f"--expected-revision {revision} --request-id {key}",
    )


def module(host, name):
    prefix = host.manager._plugins[PLUGIN_ID].module.__name__ + ".personal_agent."
    return importlib.import_module(prefix + name)


def snapshot(path):
    with inspect_db(path) as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        return {
            table: [tuple(row) for row in conn.execute("SELECT * FROM " + table)]
            for table in tables
        }


def set_status(path, status):
    with inspect_db(path) as conn:
        conn.execute("UPDATE tasks SET status=?", (status,))


@pytest.mark.parametrize(
    "status",
    ["triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"],
)
def test_sync_all_native_statuses_never_changes_local_work_state(handoff_host, board, status):
    host = handoff_host
    source, receipt = confirmed(host)
    set_status(board[1], status)
    before = snapshot(board[1])
    result = sync(host, source, receipt)
    assert result["status"] == "ok" and result["replayed"] is False, result
    task = result["data"]
    assert task["revision"] == 2 and task["state"] == "captured" and task["work_status"] == "ready"
    observation = task["native_progress"]
    assert observation["outcome"] == "current" and observation["status"] == status
    assert set(observation) == {
        "handoff_id",
        "card_id",
        "outcome",
        "status",
        "observed_at",
        "exported_revision",
    }
    assert snapshot(board[1]) == before
    assert command(host, "show " + source["id"])["data"] == task
    # This operator-only action does not silently extend model tools or focus.
    contract = module(host, "task_tool_contract")
    assert "sync" not in contract._READ_ACTIONS + contract._WRITE_ACTIONS
    assert "native_sync" not in contract._READ_ACTIONS + contract._WRITE_ACTIONS
    context = module(host, "task_focus").task_context(task)
    assert "native_progress" not in context
    assert observation["card_id"] not in context


def test_reload_exact_retry_is_historical_and_new_request_refreshes(handoff_host, board):
    host = handoff_host
    source, receipt = confirmed(host)
    first = sync(host, source, receipt)
    set_status(board[1], "review")
    host.manager.discover_and_load(force=True)
    retry = sync(host, source, receipt)
    assert retry["replayed"] and retry["data"] == first["data"]
    fresh = sync(host, source, receipt, revision=2, key="sync-fresh")
    assert fresh["data"]["native_progress"]["status"] == "review"
    assert fresh["data"]["revision"] == 3
    assert sync(host, source, receipt)["data"] == first["data"]


@pytest.mark.parametrize("condition", ["source", "revision", "terminal"])
def test_source_cas_and_terminal_refusals(handoff_host, board, condition):
    host = handoff_host
    source, receipt = confirmed(host)
    revision = 1
    if condition == "source":
        source = command(host, "add Other --request-id other")["data"]
    elif condition == "revision":
        revision = 2
    else:
        command(
            host, f"complete {source['id']} --expected-revision 1 --request-id done --note explicit"
        )
        revision = 2
    before = snapshot(board[1])
    result = sync(host, source, receipt, revision=revision)
    assert result["status"] == "error"
    assert snapshot(board[1]) == before
    assert command(host, "show " + source["id"])["data"]["native_progress"] is None


def test_exact_retry_survives_disabled_config_removed_ledger_and_native_board(
    handoff_host, board, monkeypatch
):
    host = handoff_host
    source, receipt = confirmed(host)
    first = sync(host, source, receipt)
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"]["kanban_handoff"] = False
    (host.home / "config.yaml").write_text(json.dumps(config))
    ledger = host.home / "plugin-data" / PLUGIN_ID / "kanban-handoff" / "receipts.sqlite3"
    ledger.rename(ledger.with_suffix(".unavailable"))
    board[1].rename(board[1].with_suffix(".unavailable"))

    def denied(*args, **kwargs):
        raise AssertionError("Historical retry must not access native board or handoff ledger")

    monkeypatch.setattr(module(host, "kanban_handoff"), "open_handoff_store", denied)
    monkeypatch.setattr(module(host, "native_kanban"), "observe_progress", denied)
    retry = sync(host, source, receipt)
    assert retry["replayed"] and retry["data"] == first["data"]
    assert not ledger.exists() and not board[1].exists()


@pytest.mark.parametrize("advanced", ["blocked", "running", "review", "done", "archived"])
def test_unknown_after_real_commit_reconcile_then_sync(handoff_host, board, monkeypatch, advanced):
    host = handoff_host
    source, preview = prepared(host)
    native_adapter = module(host, "native_kanban")
    original = native_adapter.create_parked

    def lost_response(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Synthetic lost successful response")

    monkeypatch.setattr(native_adapter, "create_parked", lost_response)
    result = handoff(host, f"commit {preview['id']} --expected-digest {preview['intent_digest']}")
    assert result["data"]["state"] == "unknown"
    assert result["data"]["native_identity"] is not None
    assert sync(host, source, preview)["status"] == "error"
    set_status(board[1], advanced)  # Another authorized actor; never launch work.
    reconciled = handoff(host, "reconcile " + preview["id"])
    assert reconciled["data"]["state"] == "confirmed"
    if advanced != "blocked":
        assert reconciled["data"]["observation"]["outcome"] == "identity_confirmed"
    projected = sync(host, source, preview)["data"]
    assert projected["native_progress"]["status"] == advanced
    assert projected["state"] == "captured" and projected["work_status"] == "ready"
    with inspect_db(board[1]) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


@pytest.mark.parametrize(
    "change,outcome",
    [
        ("gc", "identity_unavailable"),
        ("key", "key_changed"),
        ("duplicate", "duplicate"),
        ("missing", "missing"),
    ],
)
def test_identity_failures_record_no_native_status_and_never_rebind(
    handoff_host, board, change, outcome
):
    host = handoff_host
    source, receipt = confirmed(host)
    identity = receipt["native_identity"]
    with inspect_db(board[1]) as conn:
        if change == "gc":
            conn.execute("DELETE FROM task_events WHERE id=?", (identity["created_event_id"],))
        elif change == "key":
            conn.execute("UPDATE tasks SET idempotency_key='different'")
        elif change == "missing":
            conn.execute("DELETE FROM tasks")
        else:
            # Synthetic external actor's duplicate; no native worker is started.
            columns = [r[1] for r in conn.execute("PRAGMA table_info(tasks)")]
            row = list(conn.execute("SELECT * FROM tasks").fetchone())
            row[columns.index("id")] = (
                "t_ffffffff" if identity["card_id"] != "t_ffffffff" else "t_eeeeeeee"
            )
            row[columns.index("status")] = "archived"
            conn.execute("INSERT INTO tasks VALUES (" + ",".join("?" for _ in row) + ")", row)
    before = snapshot(board[1])
    result = sync(host, source, receipt)
    assert result["status"] == "ok", result
    observed = result["data"]["native_progress"]
    assert observed["outcome"] == outcome and observed["status"] is None
    assert observed["card_id"] == identity["card_id"]
    assert snapshot(board[1]) == before


def test_native_unavailable_does_not_overwrite_prior_snapshot(handoff_host, board, monkeypatch):
    host = handoff_host
    source, receipt = confirmed(host)
    first = sync(host, source, receipt)

    def unavailable(*args, **kwargs):
        raise RuntimeError("Synthetic unavailable")

    monkeypatch.setattr(module(host, "native_kanban"), "observe_progress", unavailable)
    result = sync(host, source, receipt, revision=2, key="new")
    assert result["status"] == "error"
    assert command(host, "show " + source["id"])["data"] == first["data"]


def test_local_receipt_failure_rolls_back_observation_and_allows_explicit_retry(
    handoff_host, board, monkeypatch
):
    host = handoff_host
    source, receipt = confirmed(host)
    tasks = module(host, "tasks")
    original = tasks.TaskStore._record_event

    def crash(*args, **kwargs):
        raise RuntimeError("Synthetic local transaction failure")

    monkeypatch.setattr(tasks.TaskStore, "_record_event", crash)
    before = snapshot(board[1])
    assert sync(host, source, receipt)["status"] == "error"
    local = command(host, "show " + source["id"])["data"]
    assert local["revision"] == 1 and local["native_progress"] is None
    monkeypatch.setattr(tasks.TaskStore, "_record_event", original)
    result = sync(host, source, receipt)
    assert result["status"] == "ok" and not result["replayed"]
    assert snapshot(board[1]) == before


def test_real_fresh_process_replays_exact_native_command_receipt(handoff_host, board):
    import os
    import subprocess
    import sys
    from pathlib import Path

    import hermes_cli

    host = handoff_host
    source, receipt = confirmed(host)
    first = sync(host, source, receipt)
    line = f"sync {receipt['id']} --task {source['id']} --expected-revision 1 --request-id sync-one"
    env = {
        "PATH": os.defpath,
        "HOME": str(host.home.parent / "os-home"),
        "HERMES_HOME": str(host.home),
        "HERMES_KANBAN_HOME": str(board[0]),
        "HERMES_BUNDLED_PLUGINS": str(host.home.parent / "bundled"),
        "HERMES_ENABLE_PROJECT_PLUGINS": "0",
        "LANG": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONPATH": os.pathsep.join(
            (str(Path(hermes_cli.__file__).resolve().parents[1]), str(Path(__file__).parent))
        ),
    }
    bootstrap = """
import socket, json, sys, os, io
from pathlib import Path
from contextlib import redirect_stdout
def deny(*a, **kw): raise AssertionError('No network or listeners in restart test')
socket.create_connection = deny
for name in ('connect','connect_ex','bind','listen','sendto','sendmsg'):
    if hasattr(socket.socket,name): setattr(socket.socket,name,deny)
with redirect_stdout(io.StringIO()):
    import test_local_conversation_tasks as local
    from test_kanban_handoff import handoff
    from hermes_cli.plugins import get_plugin_manager
    manager = get_plugin_manager()
    try:
        host = local.make_host(Path(os.environ['HERMES_HOME']), manager)
        result = handoff(host, json.load(sys.stdin))
    finally:
        manager.unload()
print(json.dumps(result))
"""
    result = subprocess.run(
        [sys.executable, "-c", bootstrap],
        input=json.dumps(line),
        env=env,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=40,
    )
    assert result.returncode == 0, result.stderr
    retry = json.loads(result.stdout)
    assert retry["replayed"] and retry["data"] == first["data"]
