"""Pinned native parked-card primitives against isolated real-host SQLite boards."""

import sqlite3
import sys
from contextlib import contextmanager

import pytest

from personal_agent import native_kanban as adapter
from personal_agent.tasks import TaskError


@pytest.fixture(params=["native-default", "delete"])
def board(tmp_path, monkeypatch, request):
    from hermes_cli import kanban_db_connect as kbc

    root = tmp_path / "kanban-root"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(root))
    monkeypatch.setenv("HERMES_HOME", str(root))
    for key in (
        "HERMES_KANBAN_TASK",
        "HERMES_KANBAN_DB",
        "HERMES_KANBAN_BOARD",
        "HERMES_DELEGATED_CHILD",
        "HERMES_MANAGED",
    ):
        monkeypatch.delenv(key, raising=False)
    path = root / "kanban.db"
    # Fixture setup only: actual host initializes a fresh synthetic board.
    conn = kbc.connect(path)
    if request.param == "delete":
        # Isolated fixture only: exercise supported rollback journaling without
        # forcing WAL or disabling the host's SQLite-version safety fallback.
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    conn.close()
    for item in root.iterdir():
        if item.is_file():
            item.chmod(0o600)
    return root, path


@contextmanager
def inspect_db(path):
    from hermes_cli.sqlite_safe_read import connect_tracked

    conn = connect_tracked(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def create(binding, key="personal.test.one"):
    return adapter.create_parked(
        binding,
        key=key,
        title="Synthetic parked task",
        body="Review only; no worker authority.",
        admit=lambda: None,
    )


def observe(binding, key="personal.test.one"):
    return adapter.observe(
        binding,
        key=key,
        payload_digest=adapter.payload_digest(
            "Synthetic parked task", "Review only; no worker authority."
        ),
        admit=lambda: None,
    )


def test_actual_native_creation_stays_sticky_without_dispatch_or_workspace(board):
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as dispatcher

    root, path = board
    before = {p.relative_to(root) for p in root.rglob("*") if p.is_dir()}
    binding = adapter.destination("default")
    result = create(binding)
    assert result["outcome"] == "parked"
    with inspect_db(path) as conn:
        row = kb.get_task(conn, result["card_id"])
        assert row.status == "blocked" and row.assignee is None
        assert row.workspace_kind == "scratch" and row.workspace_path is None
        assert kb.recompute_ready(conn) == 0
        assert kb.get_task(conn, row.id).status == "blocked"
        # Inspect actual dispatcher selectors; never invoke dispatch_tick/spawn.
        assert dispatcher._lane_rows(conn, "ready") == []
        assert dispatcher._lane_rows(conn, "review") == []
        for table in (
            "task_runs",
            "kanban_notify_subs",
            "task_links",
            "task_comments",
            "task_attachments",
        ):
            assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
        assert [r[0] for r in conn.execute("SELECT kind FROM task_events ORDER BY id")] == [
            "created",
            "blocked",
        ]
    assert observe(binding) == result
    assert {p.relative_to(root) for p in root.rglob("*") if p.is_dir()} == before


def test_observer_missing_archived_and_changed_never_recreates(board):
    _, path = board
    binding = adapter.destination("default")
    assert observe(binding)["outcome"] == "missing"
    result = create(binding)
    with inspect_db(path) as conn:
        conn.execute("UPDATE tasks SET status='archived' WHERE id=?", (result["card_id"],))
    assert observe(binding)["outcome"] == "archived"
    with pytest.raises(TaskError):
        create(binding)
    with inspect_db(path) as conn:
        conn.execute(
            "UPDATE tasks SET status='blocked',body='Changed' WHERE id=?", (result["card_id"],)
        )
    assert observe(binding)["outcome"] == "changed"
    with inspect_db(path) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1


def test_observer_detects_duplicate_key_including_archived(board):
    _, path = board
    binding = adapter.destination("default")
    one = create(binding)
    two = create(binding, "personal.test.two")
    with inspect_db(path) as conn:
        conn.execute(
            "UPDATE tasks SET idempotency_key=?,status='archived' WHERE id=?",
            ("personal.test.one", two["card_id"]),
        )
    assert observe(binding)["outcome"] == "duplicate"
    with pytest.raises(TaskError):
        create(binding)
    assert one["card_id"] != two["card_id"]


def test_admission_revocation_inside_transaction_rolls_back(board):
    _, path = board
    binding = adapter.destination("default")
    calls = []

    def admit():
        calls.append(1)
        if len(calls) == 3:
            raise TaskError("revoked")

    with pytest.raises(TaskError, match="revoked"):
        adapter.create_parked(binding, key="revoked", title="Synthetic", body="", admit=admit)
    with inspect_db(path) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM task_events").fetchone()[0] == 0


def test_after_commit_revocation_is_uncertain_but_observable(board):
    binding = adapter.destination("default")
    calls = []

    def admit():
        calls.append(1)
        if len(calls) == 4:
            raise TaskError("revoked")

    with pytest.raises(TaskError, match="revoked"):
        adapter.create_parked(
            binding,
            key="personal.test.one",
            title="Synthetic parked task",
            body="Review only; no worker authority.",
            admit=admit,
        )
    assert observe(binding)["outcome"] == "parked"


@pytest.mark.parametrize("context", ["delegated", "worker", "non_dispatcher"])
def test_native_context_fences_remain_in_force(board, monkeypatch, context):
    from agent.delegation_context import delegated_child_context, non_dispatcher_owned_context

    if context == "worker":
        monkeypatch.setenv("HERMES_KANBAN_TASK", "synthetic-worker")
        with pytest.raises(TaskError):
            adapter.destination("default")
    else:
        scope = delegated_child_context if context == "delegated" else non_dispatcher_owned_context
        with scope(), pytest.raises(TaskError):
            adapter.destination("default")


def test_actual_loaded_host_function_replacement_fails_pin(board, monkeypatch):
    from hermes_cli import kanban_db as kb

    monkeypatch.setattr(kb, "create_task", lambda *args, **kwargs: "forged")
    with pytest.raises(TaskError):
        adapter.destination("default")


def test_unknown_schema_never_migrates_or_creates(board):
    _, path = board
    with inspect_db(path) as conn:
        conn.execute("CREATE TABLE unexpected(value TEXT)")
    with pytest.raises(TaskError):
        adapter.destination("default")
    with inspect_db(path) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='unexpected'").fetchone()


def test_no_normal_connector_initializer_cli_or_dispatcher_called(board):
    forbidden = {
        "connect",
        "connect_closing",
        "init_db",
        "kanban_command",
        "_cmd_create",
        "dispatch_tick",
        "_open_configured",
        "_sqlite_connect",
    }
    seen = []

    def profile(frame, event, arg):
        if event == "call" and frame.f_globals.get("__name__", "").startswith("hermes_cli.kanban"):
            name = frame.f_code.co_name
            if name in forbidden:
                seen.append(name)
                raise AssertionError("Adapter entered forbidden host startup path: " + name)

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        binding = adapter.destination("default")
        create(binding)
        assert observe(binding)["outcome"] == "parked"
    finally:
        sys.setprofile(previous)
    assert seen == []


def test_missing_board_never_initialized(board):
    root, _ = board
    with pytest.raises(TaskError):
        adapter.destination("absent")
    assert not (root / "kanban" / "boards" / "absent").exists()


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE tasks SET title='tampered'",
        "DELETE FROM task_events",
        "CREATE TABLE extra(value TEXT)",
        "ATTACH DATABASE ':memory:' AS other",
        "INSERT INTO task_comments(task_id,author,body,created_at) VALUES ('x','x','x',1)",
    ],
)
def test_writer_authorizer_denies_noncreation_sql(board, sql):
    binding = adapter.destination("default")
    with adapter._connection(binding, write=True) as (_, conn):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql)


def test_observer_connection_cannot_insert_even_allowed_writer_tables(board):
    binding = adapter.destination("default")
    with adapter._connection(binding) as (_, conn):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(
                "INSERT INTO task_events(task_id,kind,created_at) VALUES ('x','created',1)"
            )


@pytest.mark.parametrize("change", ["event", "assignee", "workspace", "session"])
def test_observation_refuses_mutated_owned_invariants(board, change):
    _, path = board
    binding = adapter.destination("default")
    result = create(binding)
    with inspect_db(path) as conn:
        if change == "event":
            conn.execute(
                "INSERT INTO task_events(task_id,kind,payload,created_at) "
                "VALUES (?, 'unblocked', '{}', 1)",
                (result["card_id"],),
            )
        else:
            field, value = {
                "assignee": ("assignee", "other"),
                "workspace": ("workspace_path", "/synthetic/workspace"),
                "session": ("session_id", "foreign"),
            }[change]
            conn.execute(f"UPDATE tasks SET {field}=? WHERE id=?", (value, result["card_id"]))
    assert observe(binding)["outcome"] == "changed"


def test_destination_replacement_and_context_change_refuse_old_binding(board, monkeypatch):
    root, path = board
    binding = adapter.destination("default")
    monkeypatch.setenv("HERMES_KANBAN_TASK", "new-worker-context")
    with pytest.raises(TaskError):
        create(binding)
    monkeypatch.delenv("HERMES_KANBAN_TASK")
    path.rename(root / "old.db")
    path.write_bytes((root / "old.db").read_bytes())
    path.chmod(0o600)
    with pytest.raises(TaskError):
        create(binding)


def test_tracked_connections_always_closed_and_journal_mode_preserved(board):
    from hermes_cli.sqlite_safe_read import has_live_connection

    _, path = board
    with inspect_db(path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    binding = adapter.destination("default")
    assert not has_live_connection(path)
    create(binding)
    assert not has_live_connection(path)
    observe(binding)
    assert not has_live_connection(path)
    with pytest.raises(TaskError):
        create(binding)
    assert not has_live_connection(path)
    with inspect_db(path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == mode


# These use actual native LOCAL authority and execute_command, not direct service calls.
from test_local_conversation_tasks import native as native  # noqa: E402


@pytest.fixture
def handoff_host(native, board, monkeypatch):
    import json

    import test_local_conversation_tasks as local
    from test_local_task_cli import PLUGIN_ID

    home, manager = native
    monkeypatch.setenv("HERMES_HOME", str(home))
    config = json.loads((home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"].update(
        kanban_handoff=True, kanban_handoff_board="default"
    )
    (home / "config.yaml").write_text(json.dumps(config))

    def load(manager):
        manager.discover_and_load()
        plugin = manager._plugins[PLUGIN_ID]
        assert plugin.enabled and plugin.error is None
        assert plugin.tools_registered == ["personal_agent_status"]
        assert "personal-handoff" in manager._plugin_commands

    monkeypatch.setattr(local, "load", load)
    return local.make_host(home, manager)


def handoff(host, text):
    import asyncio
    import json

    from gateway.session_commands import execute_command

    response = asyncio.run(
        execute_command(host.connection, host.ref, {"command": "personal-handoff " + text})
    )
    assert response["type"] == "exec"
    return json.loads(response["output"])


def prepared(host):
    from test_local_conversation_tasks import command

    source = command(
        host,
        'add "Native handoff" --details "Synthetic detail" '
        "--project PrivateProject --request-id source",
    )["data"]
    response = handoff(host, f"prepare {source['id']} --expected-revision 1 --request-id preview")
    assert response["status"] == "ok", response
    return source, response["data"]


def test_native_command_preview_commit_reconcile_after_reload(handoff_host, board):
    host = handoff_host
    _, path = board
    source, preview = prepared(host)
    assert preview["state"] == "prepared"
    assert preview["payload"]["native_title"] == "Native handoff"
    assert "Synthetic detail" in preview["payload"]["native_body"]
    assert "PrivateProject" not in preview["payload"]["native_body"]
    assert source["id"] in preview["payload"]["native_body"]
    with inspect_db(path) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0
    line = f"commit {preview['id']} --expected-digest {preview['intent_digest']}"
    result = handoff(host, line)
    assert result["status"] == "ok", result
    assert result["data"]["state"] == "confirmed"
    assert result["data"]["payload"] is None
    host.manager.discover_and_load(force=True)
    assert handoff(host, "show " + preview["id"])["data"]["state"] == "confirmed"
    assert handoff(host, "reconcile " + preview["id"])["data"]["state"] == "confirmed"
    assert handoff(host, line)["data"]["state"] == "confirmed"
    with inspect_db(path) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
        assert conn.execute("SELECT status,assignee FROM tasks").fetchone()[:] == ("blocked", None)
        assert conn.execute("SELECT count(*) FROM task_runs").fetchone()[0] == 0


@pytest.mark.parametrize("reason", ["source_changed", "wrong_digest", "disabled", "cancelled"])
def test_native_command_commit_refusal_creates_no_card(handoff_host, board, reason):
    import json

    from test_local_conversation_tasks import command
    from test_local_task_cli import PLUGIN_ID

    host = handoff_host
    source, preview = prepared(host)
    digest = preview["intent_digest"]
    if reason == "source_changed":
        command(
            host, f"update {source['id']} --title Changed --expected-revision 1 --request-id change"
        )
    elif reason == "wrong_digest":
        digest = "0" * 64
    elif reason == "disabled":
        config = json.loads((host.home / "config.yaml").read_text())
        config["plugins"]["entries"][PLUGIN_ID]["settings"]["kanban_handoff"] = False
        (host.home / "config.yaml").write_text(json.dumps(config))
    else:
        assert (
            handoff(host, f"cancel {preview['id']} --expected-digest {digest}")["data"]["state"]
            == "cancelled"
        )
    result = handoff(host, f"commit {preview['id']} --expected-digest {digest}")
    if reason == "cancelled":
        assert result["data"]["state"] == "cancelled"
    else:
        assert result["status"] == "error", result
    with inspect_db(board[1]) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


def test_native_handoff_default_off_rejects_prepare(handoff_host, board):
    import json

    from test_local_conversation_tasks import command
    from test_local_task_cli import PLUGIN_ID

    host = handoff_host
    config = json.loads((host.home / "config.yaml").read_text())
    config["plugins"]["entries"][PLUGIN_ID]["settings"].pop("kanban_handoff")
    (host.home / "config.yaml").write_text(json.dumps(config))
    source = command(host, "add Source --request-id source")["data"]
    result = handoff(host, f"prepare {source['id']} --expected-revision 1 --request-id preview")
    assert result["status"] == "error" and result["error"]["code"] == "handoff_disabled"
    with inspect_db(board[1]) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("committed", [False, True])
def test_native_unknown_commit_never_retries_and_reconciles(
    handoff_host, board, monkeypatch, committed
):
    import importlib

    from test_local_task_cli import PLUGIN_ID

    host = handoff_host
    _, preview = prepared(host)
    prefix = host.manager._plugins[PLUGIN_ID].module.__name__ + ".personal_agent."
    native_adapter = importlib.import_module(prefix + "native_kanban")
    original = native_adapter.create_parked
    calls = []

    def uncertain(*args, **kwargs):
        calls.append(1)
        if committed:
            original(*args, **kwargs)
        raise RuntimeError("Synthetic lost response")

    monkeypatch.setattr(native_adapter, "create_parked", uncertain)
    line = f"commit {preview['id']} --expected-digest {preview['intent_digest']}"
    response = handoff(host, line)
    assert response["status"] == "ok" and response["data"]["state"] == "unknown"
    assert response["data"]["payload"] is None
    assert handoff(host, line)["data"]["state"] == "unknown"
    assert len(calls) == 1
    reconciled = handoff(host, "reconcile " + preview["id"])
    assert reconciled["status"] == "ok", reconciled
    assert reconciled["data"]["state"] == ("confirmed" if committed else "unknown")
    handoff(host, line)
    assert len(calls) == 1
    with inspect_db(board[1]) as conn:
        assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == int(committed)
