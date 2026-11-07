"""Saved attention is a read-only advisory view, not a live board claim."""

import copy

from personal_agent.status import build_status
from personal_agent.task_presentation import render_task_result


def result():
    item = {
        "id": "task-id",
        "title": "中文任务 ✅",
        "revision": 2,
        "project": None,
        "due_date": None,
        "work_status": "blocked",
        "native_progress": {
            "handoff_id": "handoff-id",
            "card_id": "card-id",
            "outcome": "current",
            "status": "done",
            "observed_at": 1,
            "exported_revision": 1,
        },
    }
    names = ("awaiting_review", "board_closed", "identity_issue", "stale")
    return {
        "status": "ok",
        "data": {
            "on": "2026-11-07",
            "stale_after_days": 7,
            "stale_before": "2026-10-31T00:00:00Z",
            "filters": {},
            "counts": {
                "total_active": 2,
                "active_observed": 1,
                "active_unobserved": 1,
                "unique_attention": 1,
            },
            "buckets": {
                name: {"total": 1, "items": [copy.deepcopy(item)], "omitted": 0} for name in names
            },
        },
    }


def test_saved_review_is_advisory_and_does_not_mutate():
    value = result()
    before = copy.deepcopy(value)
    text = render_task_result(value, operation="native_review", payload={})
    assert value == before
    for expected in (
        "中文任务 ✅",
        "Unique attention: 1",
        "buckets may overlap",
        "manual verification",
        "not live state or local completion",
        "Unobserved does not mean no linked card",
        "2026-10-31T00:00:00Z",
        "[blocked]",
        "not local completion",
    ):
        assert expected in text
    assert "handoff-id" not in text
    assert "card-id" not in text


def test_omitted_empty_and_filter_labels():
    value = result()
    value["data"]["filters"] = {"project": "演示"}
    for bucket in value["data"]["buckets"].values():
        bucket.update(total=4, items=[], omitted=4)
    text = render_task_result(value, operation="native_review", payload={})
    assert 'Project: "演示"' in text
    assert text.count("Not shown: 4") == 4
    for bucket in value["data"]["buckets"].values():
        bucket.update(total=0, items=[], omitted=0)
    assert render_task_result(value, operation="native_review", payload={}).count("None.") == 4


def test_status_reports_saved_only_without_handoff_enablement():
    status = build_status(mode="local_tasks")
    view = status["native_attention_review"]
    assert view["enabled"]
    assert not status["kanban_handoff"]["enabled"]
    assert view["source"] == "saved_local_task_observations_only"
    for key in ("native_access", "automatic", "changes_completion", "live_verified"):
        assert view[key] is False
    assert not build_status()["native_attention_review"]["enabled"]


def test_real_store_projection_renders_without_private_details():
    import sqlite3
    from uuid import uuid4

    from personal_agent.tasks import TaskStore

    store = TaskStore(sqlite3.connect(":memory:"))
    store.initialize()
    task = store.run(
        "capture", {"title": "真实本地摘要", "details": "PRIVATE DETAILS", "request_id": "capture"}
    )["data"]
    handoff = str(uuid4())
    store.sync_native(
        {
            "task_id": task["id"],
            "handoff_id": handoff,
            "expected_revision": 1,
            "request_id": "sync",
        },
        lambda _: {
            "handoff_id": handoff,
            "card_id": "t_1234abcd",
            "outcome": "current",
            "status": "review",
            "observed_at": 1,
            "exported_revision": 1,
        },
    )
    value = {"status": "ok", **store.run("native_review", {"on": "2026-11-07"})}
    text = render_task_result(value, operation="native_review", payload={})
    assert "Unique attention: 1" in text
    assert "真实本地摘要" in text
    assert "Saved board awaiting review: 1" in text
    assert "Stale saved observation: 1" in text
    assert "PRIVATE DETAILS" not in text
    assert "t_1234abcd" not in text
    store._connection.close()
