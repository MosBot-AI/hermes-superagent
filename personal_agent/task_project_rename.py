"""Explicit whole-label rename; the caller owns the read/write transaction."""

import hashlib
import json

MAX_PROJECT_TASKS = 1000


def _snapshot(store, request):
    from .tasks import TaskError

    connection = store._connection
    rows = connection.execute(
        "SELECT id,revision,state FROM tasks WHERE project=? COLLATE BINARY ORDER BY id LIMIT ?",
        (request["project"], MAX_PROJECT_TASKS + 1),
    ).fetchall()
    if not rows:
        raise TaskError("project_not_found")
    if len(rows) > MAX_PROJECT_TASKS:
        raise TaskError("project_rename_limit")
    if connection.execute(
        "SELECT 1 FROM tasks WHERE project=? COLLATE BINARY LIMIT 1", (request["new_project"],)
    ).fetchone():
        raise TaskError("project_exists")
    counts = {"captured": 0, "done": 0, "cancelled": 0}
    for task_id, revision, state in rows:
        if type(revision) is not int or not 1 <= revision < 2**63 - 1 or state not in counts:
            raise TaskError("storage_corrupt")
        # Validate all endpoints before modifying any of them. Never repair broken
        # cross-label/dangling edges as a side effect of renaming.
        store._get(task_id)
        counts[state] += 1
    digest = hashlib.sha256(
        json.dumps(
            ["project-rename-v1", request["project"], request["new_project"], rows],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    return rows, {
        "project": request["project"],
        "new_project": request["new_project"],
        "task_count": len(rows),
        "state_counts": counts,
        "snapshot": digest,
    }


def preview(store, request):
    """Return a metadata-only snapshot, not permission or a cross-call lock."""
    return _snapshot(store, request)[1]


def rename(store, request, now):
    from .tasks import TaskError

    rows, summary = _snapshot(store, request)
    if summary["snapshot"] != request["expected_snapshot"]:
        raise TaskError("project_snapshot_conflict")
    for task_id, revision, _ in rows:
        cursor = store._connection.execute(
            "UPDATE tasks SET project=?,revision=revision+1,updated_at=? WHERE id=? AND revision=?",
            (request["new_project"], now, task_id, revision),
        )
        if cursor.rowcount != 1:
            raise TaskError("revision_conflict")
        store._record_event({"id": task_id, "revision": revision + 1}, "rename_project", now)
    # Check the whole graph only after all endpoints have moved within the same
    # transaction. Terminal state, resolution, notes, edges and native receipts
    # are untouched. Old snapshots/grants become stale via each task's revision.
    for task_id, _, _ in rows:
        store._get(task_id)
    return {**summary, "renamed_at": now}
