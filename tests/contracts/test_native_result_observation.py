"""Explicit native result reads on synthetic pinned-host boards; never dispatch."""

import json
from contextlib import contextmanager

import pytest
from test_native_kanban import adapter, fixture_sql
from test_native_kanban import board as board  # noqa: F401
from test_native_kanban import no_network as no_network  # noqa: F401

from personal_agent.tasks import TaskError


def created(board):
    anchors = []
    adapter.create_parked(
        board,
        key="key",
        title="PRIVATE TITLE",
        body="PRIVATE BODY",
        admit=lambda: None,
        remember_identity=anchors.append,
    )
    return anchors[0]


def observe(board, identity, admit=lambda: None):
    return adapter.observe_result(board, key="key", identity=identity, admit=admit)


def done(board, content, completed=123):
    fixture_sql(
        board, "UPDATE tasks SET status='done',result=?,completed_at=?", (content, completed)
    )


def test_result_exact_projection_read_only_and_editable(board):
    identity = created(board)
    done(board, "Complete synthetic result")
    before = fixture_sql(board, "SELECT * FROM tasks")
    events = fixture_sql(board, "SELECT * FROM task_events")
    result = observe(board, identity)
    assert set(result) == {
        "card_id",
        "outcome",
        "status",
        "observed_at",
        "result_state",
        "result",
        "completed_at",
        "current_run_id",
    }
    assert result["result_state"] == "available" and result["result"] == "Complete synthetic result"
    assert result["completed_at"] == 123 and result["current_run_id"] is None
    assert "PRIVATE" not in json.dumps(result)
    assert fixture_sql(board, "SELECT * FROM tasks") == before
    assert fixture_sql(board, "SELECT * FROM task_events") == events
    done(board, "Changed after done")
    assert observe(board, identity)["result"] == "Changed after done"


@pytest.mark.parametrize(
    "text,state",
    [
        (None, "empty"),
        (" \n\t", "empty"),
        ("x" * 8000, "available"),
        ("x" * 8001, "too_large"),
        ("中" * 6000, "too_large"),
        ("😀" * 3000, "too_large"),
        ("x" * 100000, "too_large"),
        ("zero\x00" + "x" * 40000, "too_large"),
        ("bidi\u202euntrusted\ntext", "available"),
    ],
    ids=[
        "null",
        "blank",
        "max-ascii",
        "over-chars",
        "escaped-chinese",
        "escaped-emoji",
        "sqlite-limit",
        "embedded-nul",
        "bidi",
    ],
)
def test_complete_results_are_bounded_without_truncation(board, text, state):
    identity = created(board)
    done(board, text)
    result = observe(board, identity)
    assert result["result_state"] == state
    assert result["result"] == (text if state == "available" else None)
    assert len(json.dumps(result, ensure_ascii=True, sort_keys=True)) <= 32000


@pytest.mark.parametrize("value", [b"binary", b"\xff"])
def test_nontext_result_refused(board, value):
    identity = created(board)
    done(board, value)
    with pytest.raises(TaskError, match="native_unsafe_storage"):
        observe(board, identity)


@pytest.mark.parametrize("completed", [None, -1, "bad", 253402300800])
def test_done_requires_valid_completion_epoch(board, completed):
    identity = created(board)
    done(board, "result", completed)
    with pytest.raises(TaskError, match="native_unsafe_storage"):
        observe(board, identity)


def test_nonterminal_and_active_run_withhold_result_without_reading_it(board, monkeypatch):
    identity = created(board)
    original = adapter._connection
    reads = []

    @contextmanager
    def tracked(*args, **kwargs):
        with original(*args, **kwargs) as (kb, conn):
            authorization = adapter._authorizer(False)

            def allow(action, arg1, arg2, database, source):
                import sqlite3

                if action == sqlite3.SQLITE_READ:
                    reads.append((arg1, arg2))
                    assert (arg1, arg2) != ("tasks", "result")
                return authorization(action, arg1, arg2, database, source)

            conn.set_authorizer(allow)
            yield kb, conn

    monkeypatch.setattr(adapter, "_connection", tracked)
    assert observe(board, identity)["result_state"] == "not_done"
    done(board, "SECRET RESULT")
    fixture_sql(board, "UPDATE tasks SET current_run_id=12")
    result = observe(board, identity)
    assert result["result_state"] == "active_run" and result["result"] is None
    assert result["current_run_id"] == 12


@pytest.mark.parametrize(
    "sql,outcome",
    [
        ("UPDATE tasks SET idempotency_key='changed'", "key_changed"),
        ("UPDATE tasks SET created_at=created_at+1", "identity_changed"),
        ("DELETE FROM task_events WHERE kind='created'", "identity_unavailable"),
        ("DELETE FROM tasks", "missing"),
    ],
)
def test_identity_failures_never_read_result_fields(board, monkeypatch, sql, outcome):
    identity = created(board)
    done(board, "SECRET")
    fixture_sql(board, sql)

    def forbidden(*args):
        pytest.fail("Identity failure must not inspect result metadata")

    monkeypatch.setattr(adapter, "_result_fields", forbidden)
    result = observe(board, identity)
    assert result["outcome"] == outcome and result["status"] is None
    assert result["result_state"] == "unavailable"
    assert all(result[key] is None for key in ("result", "completed_at", "current_run_id"))


def test_revocation_and_destination_change_rechecked_before_return(board):
    identity = created(board)
    done(board, "SECRET")
    calls = []

    def revoke():
        calls.append(1)
        if len(calls) > 1:
            raise TaskError("revoked")

    with pytest.raises(TaskError, match="revoked"):
        observe(board, identity, revoke)
    changed = {**board, "inode": board["inode"] + 1}
    with pytest.raises(TaskError):
        observe(changed, identity)


def test_progress_path_still_never_reads_result(board, monkeypatch):
    identity = created(board)
    done(board, "SECRET")

    def forbidden(*args):
        pytest.fail("Ordinary progress must not inspect result")

    monkeypatch.setattr(adapter, "_result_fields", forbidden)
    result = adapter.observe_progress(board, key="key", identity=identity, admit=lambda: None)
    assert "result" not in result and result["status"] == "done"


def test_duplicate_key_never_discloses_either_result(board):
    identity = created(board)
    adapter.create_parked(board, key="other", title="Other", body="Other", admit=lambda: None)
    done(board, "SECRET")
    fixture_sql(board, "UPDATE tasks SET idempotency_key='key'")
    result = observe(board, identity)
    assert result["outcome"] == "duplicate" and result["result_state"] == "unavailable"
    assert result["result"] is None and result["status"] is None


def test_profile_change_during_result_read_discards_content(board, monkeypatch):
    identity = created(board)
    done(board, "SECRET")
    original = adapter._result_fields

    def changed(*args):
        original(*args)
        monkeypatch.setenv("HERMES_KANBAN_HOME", board["root"] + "-changed")

    monkeypatch.setattr(adapter, "_result_fields", changed)
    with pytest.raises(TaskError):
        observe(board, identity)


@pytest.mark.parametrize("run", [0, -1, "wrong"])
def test_invalid_active_run_metadata_is_not_result_authority(board, run):
    identity = created(board)
    done(board, "SECRET")
    fixture_sql(board, "UPDATE tasks SET current_run_id=?", (run,))
    with pytest.raises(TaskError, match="native_unsafe_storage"):
        observe(board, identity)
