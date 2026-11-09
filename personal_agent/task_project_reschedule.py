"""Bounded date-only project rescheduling under the task store's transaction."""

import hashlib
import json
from datetime import date, timedelta

MAX_PROJECT_TASKS = 100
MAX_PREVIEW_CHARS = 16000


def _snapshot(store, request):
    from .tasks import TaskError, _date

    rows = store._connection.execute(
        "SELECT id,revision,state,due_date FROM tasks "
        "WHERE project=? COLLATE BINARY ORDER BY id LIMIT ?",
        (request["project"], MAX_PROJECT_TASKS + 1),
    ).fetchall()
    if not rows:
        raise TaskError("project_not_found")
    if len(rows) > MAX_PROJECT_TASKS:
        raise TaskError("project_reschedule_limit")
    items = []
    excluded = {"terminal": 0, "undated": 0}
    for task_id, revision, state, due_date in rows:
        task = store._get(task_id)
        if type(revision) is not int or not 1 <= revision < 2**63 - 1:
            raise TaskError("storage_corrupt")
        if state in {"done", "cancelled"}:
            excluded["terminal"] += 1
        elif state != "captured":
            raise TaskError("storage_corrupt")
        elif due_date is None:
            excluded["undated"] += 1
        else:
            try:
                _date(due_date)
            except TaskError:
                raise TaskError("storage_corrupt") from None
            try:
                moved = (date.fromisoformat(due_date) + timedelta(days=request["days"])).isoformat()
            except OverflowError, ValueError, TypeError:
                raise TaskError("project_date_range") from None
            items.append(
                {
                    "id": task_id,
                    "title": task["title"],
                    "revision": revision,
                    "old_due_date": due_date,
                    "new_due_date": moved,
                }
            )
    digest = hashlib.sha256(
        json.dumps(
            ["project-reschedule-v1", request["project"], request["days"], rows],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    summary = {
        "project": request["project"],
        "days": request["days"],
        "task_count": len(rows),
        "affected_count": len(items),
        "excluded_counts": excluded,
        "items": items,
        "snapshot": digest,
    }
    # Reject the complete review, never silently shorten the set being approved.
    if len(json.dumps(summary, ensure_ascii=True, sort_keys=True)) > MAX_PREVIEW_CHARS:
        raise TaskError("project_reschedule_limit")
    return summary


def preview(store, request):
    return _snapshot(store, request)


def reschedule(store, request, now):
    from .tasks import TaskError

    summary = _snapshot(store, request)
    if summary["snapshot"] != request["expected_snapshot"]:
        raise TaskError("project_snapshot_conflict")
    if not summary["items"]:
        raise TaskError("project_no_dated_tasks")
    for item in summary["items"]:
        cursor = store._connection.execute(
            "UPDATE tasks SET due_date=?,revision=revision+1,updated_at=? "
            "WHERE id=? AND revision=? AND state='captured'",
            (item["new_due_date"], now, item["id"], item["revision"]),
        )
        if cursor.rowcount != 1:
            raise TaskError("revision_conflict")
        store._record_event(
            {"id": item["id"], "revision": item["revision"] + 1},
            "reschedule_project",
            now,
        )
        store._get(item["id"])
    return {**summary, "rescheduled_at": now}
