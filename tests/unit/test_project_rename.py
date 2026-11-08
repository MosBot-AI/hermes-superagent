"""Whole-project rename uses synthetic local data, never a native project."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest

from personal_agent import task_project_rename
from personal_agent.conversation_tasks import _parse
from personal_agent.task_presentation import render_task_result
from personal_agent.tasks import TaskError, TaskStore, validate_request


def store(path=":memory:"):
    s = TaskStore(sqlite3.connect(path))
    s.initialize()
    return s


def capture(s, project="旧项目"):
    return s.run("capture", {"title": "Synthetic", "project": project, "request_id": str(uuid4())})[
        "data"
    ]


def mutate(s, t, op, **kw):
    return s.run(
        op,
        {"task_id": t["id"], "expected_revision": t["revision"], "request_id": str(uuid4()), **kw},
    )["data"]


def intent(s, old="旧项目", new="New Project", key="rename-1"):
    p = {"project": old, "new_project": new}
    return {
        **p,
        "expected_snapshot": s.run("project_rename_preview", p)["data"]["snapshot"],
        "request_id": key,
    }


def error(code, call):
    with pytest.raises(TaskError) as e:
        call()
    assert e.value.code == code


def snapshot(s):
    return {
        table: s._connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in ("tasks", "task_dependencies", "events", "receipts")
    }


def test_atomic_rename_preserves_graph_and_terminal_data():
    s = store()
    a, b, c = [capture(s) for _ in range(3)]
    a = mutate(s, a, "complete", note="accepted")
    b = mutate(s, b, "set_dependencies", dependency_ids=[a["id"]])
    b = mutate(s, b, "progress", work_status="in_progress", note="working")
    c = mutate(s, c, "cancel", note="not needed")
    other = capture(s, "other")
    before = {t["id"]: t for t in (a, b, c, other)}
    payload = intent(s)
    result = s.run("rename_project", payload)
    assert result["data"]["state_counts"] == {"captured": 1, "done": 1, "cancelled": 1}
    for t in (a, b, c):
        current = s.run("get", {"task_id": t["id"]})["data"]
        assert current["project"] == "New Project"
        assert current["revision"] == t["revision"] + 1
        for field in (
            "state",
            "resolved_at",
            "resolution_note",
            "title",
            "details",
            "work_status",
            "progress_note",
            "progress_updated_at",
        ):
            assert current[field] == before[t["id"]][field]
        assert (
            s.run("history", {"task_id": t["id"]})["data"]["items"][-1]["operation"]
            == "rename_project"
        )
    current_b = s.run("get", {"task_id": b["id"]})["data"]
    assert current_b["dependencies_satisfied"]
    assert current_b["dependencies"] == [{"task_id": a["id"], "revision": 3, "state": "done"}]
    assert s.run("get", {"task_id": other["id"]})["data"] == other
    error("project_not_found", lambda: intent(s))
    assert s._connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


@pytest.mark.parametrize("change", ["capture", "update", "complete", "cancel", "progress", "move"])
def test_preview_rejects_changed_membership_or_revision(change):
    s = store()
    t = capture(s)
    request = intent(s)
    if change == "capture":
        capture(s)
    elif change == "move":
        mutate(s, t, "update", project="different")
        capture(s)
    elif change == "update":
        mutate(s, t, change, title="new")
    elif change == "progress":
        mutate(s, t, change, work_status="waiting", note="waiting")
    else:
        mutate(s, t, change, note="reason")
    before = snapshot(s)
    error("project_snapshot_conflict", lambda: s.run("rename_project", request))
    assert snapshot(s) == before


def test_destination_rechecked_and_labels_are_exact():
    s = store()
    capture(s)
    request = intent(s)
    capture(s, "new project")  # distinct binary label
    target = capture(s, "New Project")
    mutate(s, target, "complete", note="finished")
    before = snapshot(s)
    error("project_exists", lambda: s.run("rename_project", request))
    assert snapshot(s) == before


def test_retry_historical_across_restart_and_later_rename(tmp_path):
    path = tmp_path / "tasks.sqlite"
    s = store(path)
    t = capture(s)
    request = intent(s)
    first = s.run("rename_project", request)
    s.run("rename_project", intent(s, "New Project", "Next", "next"))
    s._connection.close()
    s = store(path)
    before = snapshot(s)
    assert s.run("rename_project", request) == {**first, "replayed": True}
    assert snapshot(s) == before
    assert s.run("get", {"task_id": t["id"]})["data"]["project"] == "Next"
    error(
        "idempotency_conflict", lambda: s.run("rename_project", {**request, "new_project": "Else"})
    )


@pytest.mark.parametrize("phase", ["task", "event", "receipt"])
def test_storage_failure_rolls_back_everything(phase):
    s = store()
    capture(s)
    capture(s)
    request = intent(s)
    last = s._connection.execute("SELECT MAX(id) FROM tasks").fetchone()[0]
    trigger = {
        "task": f"BEFORE UPDATE ON tasks WHEN NEW.id='{last}'",
        "event": (
            f"BEFORE INSERT ON events WHEN NEW.task_id='{last}' AND NEW.operation='rename_project'"
        ),
        "receipt": "BEFORE INSERT ON receipts WHEN NEW.request_id='rename-1'",
    }[phase]
    s._connection.execute(
        f"CREATE TEMP TRIGGER fault {trigger} BEGIN SELECT RAISE(ABORT, 'fault'); END"
    )
    before = snapshot(s)
    with pytest.raises(TaskError):
        s.run("rename_project", request)
    assert snapshot(s) == before
    s._connection.execute("DROP TRIGGER fault")
    assert s.run("rename_project", request)["data"]["task_count"] == 2


def test_concurrent_requests_do_not_partially_relabel(tmp_path):
    path = tmp_path / "tasks.sqlite"
    s = store(path)
    capture(s)
    capture(s)
    request = intent(s)
    s._connection.close()
    barrier = Barrier(2)

    def run():
        local = store(path)
        barrier.wait()
        try:
            return local.run("rename_project", request)
        finally:
            local._connection.close()

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: run(), range(2)))
    assert sorted(r["replayed"] for r in results) == [False, True]
    s = store(path)
    assert (
        len(
            s._connection.execute(
                "SELECT * FROM events WHERE operation='rename_project'"
            ).fetchall()
        )
        == 2
    )


def test_corrupt_edge_is_not_repaired_by_rename():
    s = store()
    a = capture(s)
    b = capture(s, "other")
    s._connection.execute("INSERT INTO task_dependencies VALUES (?,?)", (a["id"], b["id"]))
    s._connection.commit()
    before = snapshot(s)
    error("storage_corrupt", lambda: intent(s))
    assert snapshot(s) == before


def test_bounded_preview_and_hash_target_binding(monkeypatch):
    s = store()
    capture(s)
    capture(s)
    assert intent(s)["expected_snapshot"] != intent(s, new="Different")["expected_snapshot"]
    before = snapshot(s)
    monkeypatch.setattr(task_project_rename, "MAX_PROJECT_TASKS", 1)
    error("project_rename_limit", lambda: intent(s))
    assert snapshot(s) == before


@pytest.mark.parametrize(
    "patch",
    [
        {"project": None},
        {"new_project": ""},
        {"new_project": " x"},
        {"new_project": "旧项目"},
        {"expected_snapshot": "A" * 64},
        {"expected_snapshot": True},
        {"request_id": "bad key"},
        {"unexpected": True},
    ],
)
def test_validation(patch):
    payload = {
        "project": "旧项目",
        "new_project": "new",
        "expected_snapshot": "a" * 64,
        "request_id": "key",
        **patch,
    }
    error("invalid_request", lambda: validate_request("rename_project", payload))


def test_native_parser_explicit_key_and_readable_presentation():
    s = store()
    capture(s)
    op, payload, _ = _parse('project-rename-preview --project "旧项目" --new-project "New Project"')
    preview = s.run(op, payload)
    text = render_task_result({"status": "ok", **preview}, operation=op, payload=payload)
    assert "no rename saved" in text and "All tasks: 1" in text
    digest = preview["data"]["snapshot"]
    command = (
        'rename-project --project "旧项目" --new-project "New Project" '
        f"--expected-snapshot {digest}"
    )
    error("invalid_request", lambda: _parse(command))
    op, payload, _ = _parse(command + " --request-id key")
    result = s.run(op, payload)
    text = render_task_result({"status": "ok", **result}, operation=op, payload=payload)
    assert "Project label renamed" in text
    assert "Synthetic" not in json.dumps(result)  # receipt is metadata-only


def test_old_label_reuse_is_untouched_by_receipt_replay():
    s = store()
    capture(s)
    request = intent(s)
    first = s.run("rename_project", request)
    newer = capture(s)
    assert s.run("rename_project", request) == {**first, "replayed": True}
    assert s.run("get", {"task_id": newer["id"]})["data"]["project"] == "旧项目"


@pytest.mark.parametrize("operation", ["project_rename_preview", "rename_project"])
def test_new_commands_not_available_as_model_tools(operation):
    from personal_agent.task_tool_contract import normalize_task_tool_request

    for tool in ("personal_tasks_read", "personal_tasks_write"):
        error(
            "invalid_request",
            lambda tool=tool: normalize_task_tool_request(tool, {"action": operation}),
        )


def test_text_help_contains_explicit_rename_workflow():
    text = render_task_result({"status": "ok", "data": {}}, operation="help", payload={})
    assert "project-rename-preview" in text and "--expected-snapshot HASH" in text
