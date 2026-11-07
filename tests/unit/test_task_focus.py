"""Fresh, bounded focus context with the same gate as existing task tools."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from test_session_task_tools import gate  # noqa: F401

from personal_agent import session_task_tools
from personal_agent.task_focus import (
    CONTEXT_PREFIX,
    MAX_CONTEXT_CHARS,
    UNAVAILABLE_CONTEXT,
    FocusedSessionTaskTools,
)


@pytest.fixture(autouse=True)
def use_focused_tools(monkeypatch):
    monkeypatch.setattr(session_task_tools, "SessionTaskTools", FocusedSessionTaskTools)


def capture(command, call, **fields):
    command("enable-write")
    result = call(
        {"action": "capture", "title": "Focused task", "request_id": "focus-task", **fields},
        "personal_tasks_write",
    )
    assert result["status"] == "ok"
    return result["data"]


def context(instance, **kwargs):
    return instance.turn_context(session_id="session", task_id="turn", **kwargs)


def data(instance):
    result = context(instance)
    assert len(result["context"]) <= MAX_CONTEXT_CHARS
    assert result["context"].startswith(CONTEXT_PREFIX)
    return json.loads(result["context"][len(CONTEXT_PREFIX) :])


def test_explicit_focus_reads_fresh_progress_without_mutation(gate):  # noqa: F811
    instance, command, call, _, _, opened = gate
    assert context(instance) is None
    command("enable-read")
    assert context(instance) is None
    assert not opened
    task = capture(command, call, details="Original context", project="Project A")
    other = call(
        {"action": "capture", "title": "UNRELATED-PROJECT", "request_id": "other"},
        "personal_tasks_write",
    )
    assert other["status"] == "ok"
    command("enable-read")
    selected = command("focus " + task["id"])
    assert selected["data"]["revision_at_selection"] == 1
    assert command("status")["data"]["focus_task_id"] == task["id"]
    snapshot = data(instance)
    assert snapshot["task"]["details"] == "Original context"
    assert snapshot["task"]["project"] == "Project A"
    assert "UNRELATED" not in json.dumps(snapshot)
    assert snapshot["omitted_fields"] == []
    command("enable-write")
    progress = call(
        {
            "action": "progress",
            "task_id": task["id"],
            "expected_revision": 1,
            "work_status": "blocked",
            "note": "Waiting for requirements",
            "request_id": "progress",
        },
        "personal_tasks_write",
    )
    assert progress["data"]["revision"] == 2
    snapshot = data(instance)["task"]
    assert snapshot["revision"] == 2 and snapshot["work_status"] == "blocked"
    assert snapshot["progress_note"] == "Waiting for requirements"
    done = call(
        {
            "action": "complete",
            "task_id": task["id"],
            "expected_revision": 2,
            "note": "User confirmed completion",
            "request_id": "complete",
        },
        "personal_tasks_write",
    )
    assert done["status"] == "ok"
    snapshot = data(instance)["task"]
    assert snapshot["state"] == "done" and snapshot["revision"] == 3
    assert snapshot["resolution_note"] == "User confirmed completion"
    assert call({"action": "show", "task_id": task["id"]})["data"]["revision"] == 3


def test_unicode_and_escaped_details_are_omitted_whole(gate):  # noqa: F811
    instance, command, call, *_ = gate
    task = capture(command, call, title="中文标题", details='内容\n"' * 1000)
    command("focus " + task["id"])
    snapshot = data(instance)
    assert snapshot["task"]["title"] == "中文标题"
    assert "details" not in snapshot["task"]
    assert snapshot["omitted_fields"] == ["details"]
    assert call({"action": "show", "task_id": task["id"]})["data"]["details"] == '内容\n"' * 1000


@pytest.mark.parametrize("verb", ["disable", "clear-focus"])
def test_clearing_focus_never_revives_it_on_enable(gate, verb):  # noqa: F811
    instance, command, call, *_ = gate
    task = capture(command, call)
    command("focus " + task["id"])
    command(verb)
    command("enable-write")
    assert context(instance) is None
    assert command("status")["data"]["focus_task_id"] is None
    assert call()["status"] == "ok"


def test_expired_focus_not_revived_by_reactivation(gate):  # noqa: F811
    instance, command, call, _, binding, opened = gate
    task = capture(command, call)
    command("focus " + task["id"])
    opened.clear()
    binding["now"] += 1800
    command("enable-read")
    assert context(instance) is None
    assert command("status")["data"]["focus_task_id"] is None
    assert not opened


def test_fresh_session_route_and_unload_do_not_expose_focus(gate):  # noqa: F811
    instance, command, call, _, binding, opened = gate
    task = capture(command, call)
    command("focus " + task["id"])
    opened.clear()
    assert instance.turn_context(session_id="other", task_id="turn") is None
    binding["key"] = "other-route"
    assert context(instance) is None
    binding["key"] = "route"
    instance.close()
    assert context(instance) is None
    assert command("focus " + task["id"])["error"]["code"] == "local_model_tools_unloaded"
    assert not opened


@pytest.mark.parametrize(
    "raw", ["focus", "focus invalid", "focus x y", "clear-focus extra", "focus " + "a" * 128]
)
def test_invalid_selection_preserves_previous_focus(gate, raw):  # noqa: F811
    instance, command, call, *_ = gate
    task = capture(command, call)
    command("focus " + task["id"])
    assert command(raw)["error"]["code"] == "invalid_request"
    assert command("focus " + str(uuid4()))["error"]["code"] == "not_found"
    assert data(instance)["task"]["id"] == task["id"]


def test_focus_without_activation_never_opens_storage(gate):  # noqa: F811
    _, command, _, _, _, opened = gate
    assert command("focus " + str(uuid4()))["error"]["code"] == "session_tools_not_activated"
    assert command("clear-focus")["data"]["focus_task_id"] is None
    assert not opened


def test_configuration_revokes_focus_without_read(gate):  # noqa: F811
    instance, command, call, config, _, opened = gate
    task = capture(command, call)
    command("focus " + task["id"])
    opened.clear()
    config["local_model_tools"] = False
    assert context(instance) is None
    config["local_model_tools"] = True
    command("enable-read")
    assert context(instance) is None
    assert not opened


def test_storage_failure_returns_no_stale_data_or_exception_details(gate, monkeypatch):  # noqa: F811
    instance, command, call, *_ = gate
    task = capture(command, call)
    command("focus " + task["id"])
    assert data(instance)["task"]["id"] == task["id"]
    execute = instance._execute

    def fail(*args):
        raise RuntimeError("SECRET PATH")

    monkeypatch.setattr(instance, "_execute", fail)
    assert context(instance) == {"context": UNAVAILABLE_CONTEXT}
    monkeypatch.setattr(instance, "_execute", execute)
    assert data(instance)["task"]["id"] == task["id"]


def test_focus_clear_waits_for_admitted_context_then_blocks_future(gate, monkeypatch):  # noqa: F811
    instance, command, call, *_ = gate
    task = capture(command, call)
    command("focus " + task["id"])
    admitted, release, clearing = threading.Event(), threading.Event(), threading.Event()
    execute = instance._execute

    def blocked(*args):
        admitted.set()
        assert release.wait(5)
        return execute(*args)

    def clear():
        clearing.set()
        return command("clear-focus")

    monkeypatch.setattr(instance, "_execute", blocked)
    with ThreadPoolExecutor(max_workers=2) as pool:
        read = pool.submit(context, instance)
        assert admitted.wait(5)
        clear_result = pool.submit(clear)
        assert clearing.wait(5)
        try:
            assert not clear_result.done()
        finally:
            release.set()
        assert read.result(timeout=5)["context"].startswith(CONTEXT_PREFIX)
        assert clear_result.result(timeout=5)["status"] == "ok"
    assert context(instance) is None
