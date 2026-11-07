"""Real pinned native APIs, synthetic private boards only. No CLI/model/network."""

import os
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc

from personal_agent import native_kanban as adapter
from personal_agent.tasks import TaskError


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("No network permitted in native adapter contract")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(params=["native-default", "delete"])
def board(tmp_path, monkeypatch, request):
    home = tmp_path / "private"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.delenv("HERMES_KANBAN_DB", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
    previous = os.umask(0o077)
    try:
        conn = kbc.connect(home / "kanban.db")
        if request.param == "delete":
            assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        conn.close()
        yield adapter.destination("default")
    finally:
        os.umask(previous)


def create(binding, key="key", admit=lambda: None):
    return adapter.create_parked(
        binding, key=key, title="中文 synthetic", body="untrusted text", admit=admit
    )


def observe(binding, key="key"):
    return adapter.observe(
        binding,
        key=key,
        payload_digest=adapter.payload_digest("中文 synthetic", "untrusted text"),
        admit=lambda: None,
    )


def fail(fn, code=None):
    with pytest.raises(TaskError) as caught:
        fn()
    if code:
        assert caught.value.code == code


def fixture_sql(binding, sql, args=()):
    # Test-only mutation, never adapter storage operations.
    from hermes_cli.sqlite_safe_read import connect_tracked

    conn = connect_tracked(binding["path"])
    try:
        result = conn.execute(sql, args).fetchall()
        conn.commit()
        return result
    finally:
        conn.close()


def test_actual_create_observe_and_no_retry(board):
    assert observe(board) == {"outcome": "missing"}
    result = create(board)
    assert result["outcome"] == "parked" and result["status"] == "blocked"
    assert observe(board) == result
    fail(lambda: create(board), "native_key_conflict")
    assert fixture_sql(board, "SELECT count(*) FROM tasks") == [(1,)]
    assert fixture_sql(board, "SELECT count(*) FROM task_events") == [(2,)]
    for table in (
        "task_runs",
        "task_links",
        "task_comments",
        "kanban_notify_subs",
        "task_attachments",
    ):
        assert fixture_sql(board, f"SELECT count(*) FROM {table}") == [(0,)]
    assert not (
        os.path.join(board["root"], "workspaces")
        and os.path.exists(os.path.join(board["root"], "workspaces"))
    )


@pytest.mark.parametrize(
    "sql,outcome",
    [
        ("UPDATE tasks SET status='archived'", "archived"),
        ("UPDATE tasks SET body='changed'", "changed"),
        ("UPDATE tasks SET assignee='somebody'", "changed"),
        ("UPDATE tasks SET status='ready'", "changed"),
        ("UPDATE tasks SET completion_contract='other/repo'", "changed"),
    ],
)
def test_changed_or_archived_never_recreated(board, sql, outcome):
    create(board)
    fixture_sql(board, sql)
    assert observe(board)["outcome"] == outcome
    fail(lambda: create(board), "native_key_conflict")


def test_duplicate_key_is_not_adopted(board):
    create(board)
    create(board, "second")
    fixture_sql(board, "UPDATE tasks SET idempotency_key='key'")
    assert observe(board) == {"outcome": "duplicate"}
    fail(lambda: create(board), "native_key_conflict")


def test_revoke_before_commit_rolls_back(board):
    calls = 0

    def admit():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise TaskError("disabled")

    fail(lambda: create(board, admit=admit), "disabled")
    assert observe(board) == {"outcome": "missing"}


def test_postcommit_admission_failure_may_have_committed(board):
    calls = 0

    def admit():
        nonlocal calls
        calls += 1
        if calls == 4:
            raise TaskError("disabled")

    fail(lambda: create(board, admit=admit), "disabled")
    assert observe(board)["outcome"] == "parked"


def test_concurrent_same_key_native_outer_transaction(board):
    barrier = Barrier(2)

    def work(_):
        barrier.wait()
        try:
            return create(board)["outcome"]
        except TaskError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, (0, 1)))
    assert results.count("parked") == 1
    assert set(results) <= {
        "parked",
        "native_key_conflict",
        "native_unsafe_storage",
        "native_unavailable",
    }
    assert fixture_sql(board, "SELECT count(*) FROM tasks") == [(1,)]
    assert fixture_sql(board, "SELECT count(*) FROM task_events") == [(2,)]


@pytest.mark.parametrize("mutation", ["trigger", "extra", "missing"])
def test_foreign_schema_refused(board, mutation):
    statement = {
        "trigger": "CREATE TRIGGER surprise AFTER INSERT ON tasks BEGIN DELETE FROM tasks; END",
        "extra": "CREATE TABLE extra(x)",
        "missing": "DROP INDEX idx_tasks_status",
    }[mutation]
    fixture_sql(board, statement)
    fail(lambda: create(board), "native_schema_mismatch")


@pytest.mark.parametrize("context", ["delegated", "cron_context", "worker_env"])
def test_native_context_fences(board, context, monkeypatch):
    from agent import delegation_context as dc

    if context == "worker_env":
        monkeypatch.setenv("HERMES_KANBAN_TASK", "t_00000000")
        fail(lambda: create(board), "native_context_denied")
    else:
        scope = (
            dc.delegated_child_context
            if context == "delegated"
            else dc.non_dispatcher_owned_context
        )
        with scope():
            fail(lambda: create(board), "native_context_denied")


def test_replaced_actual_function_refused(board, monkeypatch):
    monkeypatch.setattr(kb, "create_task", lambda *a, **kw: "t_00000000")
    fail(lambda: create(board), "native_unavailable")


def test_inode_change_and_unsafe_permissions_refused(board):
    from pathlib import Path

    path = Path(board["path"])
    path.chmod(0o644)
    fail(lambda: observe(board), "native_unsafe_path")
    path.chmod(0o600)
    path.rename(path.with_suffix(".old"))
    path.touch(mode=0o600)
    fail(lambda: observe(board), "native_destination_changed")


def test_sql_authorizer_denies_writes_except_native_inserts(board):
    with adapter._connection(board, write=True) as (_, conn):
        for sql in (
            "DELETE FROM tasks",
            "UPDATE tasks SET title='x'",
            "CREATE TABLE x(y)",
            "ATTACH DATABASE ':memory:' AS other",
            "PRAGMA journal_mode=OFF",
            "INSERT INTO kanban_notify_subs(task_id,platform,chat_id) VALUES('x','x','x')",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                conn.execute(sql)


def test_named_board_explicit_scratch_does_not_inherit_project(board):
    from pathlib import Path

    kb.create_board("named", name="Synthetic", project_id="must-not-resolve")
    root = Path(board["root"])
    for path in (root / "kanban", root / "kanban" / "boards", root / "kanban" / "boards" / "named"):
        path.chmod(0o700)
    conn = kbc.connect(board="named")
    if fixture_sql(board, "PRAGMA journal_mode") == [("delete",)]:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    conn.close()
    named = adapter.destination("named")
    result = create(named)
    assert result["outcome"] == "parked"
    assert fixture_sql(named, "SELECT project_id,workspace_path FROM tasks") == [(None, None)]
    assert fixture_sql(board, "SELECT count(*) FROM tasks") == [(0,)]


def test_missing_board_is_not_initialized(board):
    from pathlib import Path

    fail(lambda: adapter.destination("absent"))
    assert not (Path(board["root"]) / "kanban" / "boards" / "absent").exists()


def test_sidecar_symlink_refused(board, tmp_path):
    from pathlib import Path

    sidecar = Path(board["path"] + "-journal")
    sidecar.symlink_to(tmp_path / "missing")
    fail(lambda: observe(board), "native_unsafe_path")


def test_tracked_connection_unregisters_and_preserves_journal(board):
    from hermes_cli.sqlite_safe_read import has_live_connection

    before = fixture_sql(board, "PRAGMA journal_mode")
    with adapter._connection(board) as (_, conn):
        assert has_live_connection(board["path"])
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == before[0][0]
    assert not has_live_connection(board["path"])
    create(board)
    assert fixture_sql(board, "PRAGMA journal_mode") == before


def test_class_method_replacement_refused(board, monkeypatch):
    from hermes_cli import sqlite_safe_read

    monkeypatch.setattr(sqlite_safe_read._TrackingMixin, "close", lambda self: None)
    fail(lambda: observe(board), "native_unavailable")


def test_existing_rollback_journal_is_refused_without_open(board):
    from pathlib import Path

    journal = Path(board["path"] + "-journal")
    journal.write_bytes(b"synthetic journal, never repaired")
    journal.chmod(0o600)
    before = journal.read_bytes()
    fail(lambda: observe(board), "native_unsafe_storage")
    fail(lambda: create(board), "native_unsafe_storage")
    assert journal.read_bytes() == before


@pytest.mark.parametrize("revoke", [False, True])
def test_own_journal_exists_only_during_transaction(board, revoke):
    from pathlib import Path

    journal = Path(board["path"] + "-journal")
    mode = fixture_sql(board, "PRAGMA journal_mode")[0][0]
    calls = 0
    seen = []

    def admit():
        nonlocal calls
        calls += 1
        if calls == 3:
            seen.append(journal.exists())
            if revoke:
                raise TaskError("disabled")

    if revoke:
        fail(lambda: create(board, admit=admit), "disabled")
        assert observe(board) == {"outcome": "missing"}
    else:
        assert create(board, admit=admit)["outcome"] == "parked"
        assert observe(board)["outcome"] == "parked"
    assert seen == [mode == "delete"]
    assert not journal.exists()
    assert fixture_sql(board, "PRAGMA journal_mode") == [(mode,)]


def test_owned_journal_check_rejects_real_attached_database(board):
    from hermes_cli.sqlite_safe_read import connect_tracked

    conn = connect_tracked(board["path"], isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        conn.execute("ATTACH DATABASE ':memory:' AS unexpected")
        conn.execute("BEGIN IMMEDIATE")
        fail(
            lambda: adapter._check(board, kb, owned_write_connection=conn),
            "native_unsafe_storage",
        )
        conn.execute("ROLLBACK")
    finally:
        conn.close()


def anchored(board):
    identities = []
    result = adapter.create_parked(
        board,
        key="key",
        title="中文 synthetic",
        body="untrusted text",
        admit=lambda: None,
        remember_identity=identities.append,
    )
    assert len(identities) == 1 and identities[0]["card_id"] == result["card_id"]
    return identities[0]


def progress(board, identity):
    return adapter.observe_progress(board, key="key", identity=identity, admit=lambda: None)


@pytest.mark.parametrize(
    "status",
    ["triage", "todo", "scheduled", "ready", "running", "blocked", "review", "done", "archived"],
)
def test_progress_all_native_statuses_are_advisory_metadata_only(board, status):
    identity = anchored(board)
    fixture_sql(
        board,
        "UPDATE tasks SET status=?,title=?,body=?,result=?,assignee=? WHERE id=?",
        (
            status,
            "PRIVATE TITLE",
            "PRIVATE BODY",
            "PRIVATE RESULT",
            "PRIVATE PROFILE",
            identity["card_id"],
        ),
    )
    before = fixture_sql(board, "SELECT * FROM tasks")
    result = progress(board, identity)
    assert result == {
        "outcome": "current",
        "card_id": identity["card_id"],
        "status": status,
        "observed_at": result["observed_at"],
    }
    assert type(result["observed_at"]) is int
    assert fixture_sql(board, "SELECT * FROM tasks") == before
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize(
    "change,outcome",
    [
        ("missing", "missing"),
        ("key", "key_changed"),
        ("created_at", "identity_changed"),
        ("creator", "identity_changed"),
        ("pruned", "identity_unavailable"),
        ("event_kind", "identity_changed"),
        ("event_task", "identity_changed"),
        ("replacement", "identity_changed"),
        ("duplicate_archived", "duplicate"),
    ],
)
def test_progress_never_follows_identity_drift(board, change, outcome):
    identity = anchored(board)
    if change == "missing":
        fixture_sql(board, "DELETE FROM tasks WHERE id=?", (identity["card_id"],))
    elif change == "key":
        fixture_sql(
            board, "UPDATE tasks SET idempotency_key='other' WHERE id=?", (identity["card_id"],)
        )
    elif change == "created_at":
        fixture_sql(
            board, "UPDATE tasks SET created_at=created_at+1 WHERE id=?", (identity["card_id"],)
        )
    elif change == "creator":
        fixture_sql(board, "UPDATE tasks SET created_by='other' WHERE id=?", (identity["card_id"],))
    elif change == "pruned":
        fixture_sql(board, "DELETE FROM task_events WHERE id=?", (identity["created_event_id"],))
    elif change == "event_kind":
        fixture_sql(
            board,
            "UPDATE task_events SET kind='updated' WHERE id=?",
            (identity["created_event_id"],),
        )
    elif change == "event_task":
        fixture_sql(
            board,
            "UPDATE task_events SET task_id='t_00000000' WHERE id=?",
            (identity["created_event_id"],),
        )
    elif change == "replacement":
        fixture_sql(board, "DELETE FROM tasks WHERE id=?", (identity["card_id"],))
        create(board)
    else:
        other = create(board, "other")
        fixture_sql(
            board,
            "UPDATE tasks SET idempotency_key='key',status='archived' WHERE id=?",
            (other["card_id"],),
        )
    result = progress(board, identity)
    assert result["outcome"] == outcome and result["card_id"] == identity["card_id"]
    assert "status" not in result
    observed = adapter.observe(
        board,
        key="key",
        identity=identity,
        payload_digest=adapter.payload_digest("中文 synthetic", "untrusted text"),
        admit=lambda: None,
    )
    assert observed["outcome"] == outcome and "status" not in observed


def test_identity_callback_precedes_commit_and_failure_rolls_back(board):
    seen = []

    def remember(identity):
        seen.append(identity)
        assert fixture_sql(board, "SELECT count(*) FROM tasks") == [(0,)]
        raise RuntimeError("Synthetic ledger failure")

    fail(
        lambda: adapter.create_parked(
            board,
            key="key",
            title="Synthetic",
            body="",
            admit=lambda: None,
            remember_identity=remember,
        )
    )
    assert len(seen) == 1
    assert fixture_sql(board, "SELECT count(*) FROM tasks") == [(0,)]
    assert progress(board, seen[0])["outcome"] == "missing"


@pytest.mark.parametrize(
    "field,value",
    [
        ("card_id", "bad"),
        ("created_at", True),
        ("created_at", -1),
        ("created_event_id", 0),
        ("created_event_id", True),
    ],
)
def test_invalid_identity_never_readmitted(board, field, value):
    identity = anchored(board)
    identity[field] = value
    fail(lambda: progress(board, identity), "invalid_request")


def test_progress_refuses_unknown_native_status(board):
    identity = anchored(board)
    fixture_sql(board, "UPDATE tasks SET status='unrecognized' WHERE id=?", (identity["card_id"],))
    fail(lambda: progress(board, identity), "native_unsafe_storage")


def test_reused_card_id_and_timestamp_do_not_replace_original_event_anchor(board):
    identity = anchored(board)
    fixture_sql(board, "DELETE FROM task_events WHERE task_id=?", (identity["card_id"],))
    fixture_sql(board, "DELETE FROM tasks WHERE id=?", (identity["card_id"],))
    replacement = create(board)
    fixture_sql(
        board,
        "UPDATE tasks SET id=?,created_at=? WHERE id=?",
        (identity["card_id"], identity["created_at"], replacement["card_id"]),
    )
    fixture_sql(
        board,
        "UPDATE task_events SET task_id=? WHERE task_id=?",
        (identity["card_id"], replacement["card_id"]),
    )
    assert progress(board, identity)["outcome"] == "identity_unavailable"


def test_progress_sql_reads_no_payload_or_identity_sensitive_columns(board, monkeypatch):
    from contextlib import contextmanager

    identity = anchored(board)
    original = adapter._connection
    reads = []

    @contextmanager
    def guarded(*args, **kwargs):
        with original(*args, **kwargs) as (host, conn):
            authorizer = adapter._authorizer(False)

            def authorize(action, arg1, arg2, database, source):
                if action == sqlite3.SQLITE_READ and arg1 in {"tasks", "task_events"}:
                    reads.append((arg1, arg2))
                    if arg2 in {"title", "body", "result", "assignee", "payload"}:
                        return sqlite3.SQLITE_DENY
                return authorizer(action, arg1, arg2, database, source)

            conn.set_authorizer(authorize)
            yield host, conn

    monkeypatch.setattr(adapter, "_connection", guarded)
    assert progress(board, identity)["outcome"] == "current"
    assert reads and not any(
        column in {"title", "body", "result", "assignee", "payload"} for _, column in reads
    )


@pytest.mark.parametrize("status", ["running", "review", "done", "archived"])
def test_anchored_reconcile_confirms_identity_not_still_parked(board, status):
    identity = anchored(board)
    fixture_sql(board, "UPDATE tasks SET status=?", (status,))
    result = adapter.observe(
        board,
        key="key",
        identity=identity,
        payload_digest=adapter.payload_digest("中文 synthetic", "untrusted text"),
        admit=lambda: None,
    )
    assert result == {
        "outcome": "identity_confirmed",
        "card_id": identity["card_id"],
        "status": status,
    }
    # Legacy unanchored receipts never gain creation identity from a changed card.
    assert observe(board)["outcome"] != "identity_confirmed"
