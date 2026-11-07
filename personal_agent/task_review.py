"""One snapshot of active task counts and bounded summaries, without scheduling."""

import json
import sqlite3
from datetime import date, timedelta

from .task_dependencies import metadata

_SUMMARY_COLUMNS = ("id", "title", "project", "due_date", "revision", "work_status")


def task_review(connection: sqlite3.Connection, request: dict) -> dict:
    """Read inside the caller's transaction; request has already been validated.

    Dates are explicit calendar values, not a system-clock or timezone guess.
    Summary counts cover every matching active task, not just the sample. Task
    text is untrusted content; this reader neither follows nor executes it.
    """
    on = request["on"]
    through = (date.fromisoformat(on) + timedelta(days=request["lookahead_days"])).isoformat()
    where = "state = 'captured'"
    parameters = []
    filters = {}
    if "project" in request:
        where += " AND project = ? COLLATE BINARY"
        parameters.append(request["project"])
        filters["project"] = request["project"]
    elif request.get("unassigned"):
        where += " AND project IS NULL"
        filters["unassigned"] = True
    if "work_status" in request:
        where += " AND work_status = ?"
        parameters.append(request["work_status"])
        filters["work_status"] = request["work_status"]
    # A single aggregate starts the read snapshot before individual summaries.
    counts = connection.execute(
        "SELECT count(*), coalesce(sum(due_date < ?), 0), "
        "coalesce(sum(due_date = ?), 0), "
        "coalesce(sum(due_date > ? AND due_date <= ?), 0), "
        "coalesce(sum(due_date > ?), 0), coalesce(sum(due_date IS NULL), 0), "
        "coalesce(sum(work_status = 'ready'), 0), "
        "coalesce(sum(work_status = 'in_progress'), 0), "
        "coalesce(sum(work_status = 'waiting'), 0), "
        "coalesce(sum(work_status = 'blocked'), 0) "
        f"FROM tasks WHERE {where}",
        (on, on, on, through, through, *parameters),
    ).fetchone()
    names = ("total_active", "overdue", "due_today", "upcoming", "later", "undated")
    totals = dict(zip(names, counts[:6], strict=True))
    buckets: dict[str, dict] = {
        name: {"total": totals[name], "items": [], "omitted": totals[name]}
        for name in ("overdue", "due_today", "upcoming", "undated")
    }
    active = connection.execute(
        f"SELECT id,project FROM tasks WHERE {where}", parameters
    ).fetchall()
    blocked = sum(
        not metadata(connection, {"id": row[0], "project": row[1]})["dependencies_satisfied"]
        for row in active
    )
    data = {
        "dependency_counts": {"satisfied": len(active) - blocked, "blocked": blocked},
        "on": on,
        "through": through,
        "filters": filters,
        "counts": totals,
        "progress_counts": dict(
            zip(("ready", "in_progress", "waiting", "blocked"), counts[6:], strict=True)
        ),
        "buckets": buckets,
    }
    conditions = (
        ("overdue", "due_date < ?", (on,)),
        ("due_today", "due_date = ?", (on,)),
        ("upcoming", "due_date > ? AND due_date <= ?", (on, through)),
        ("undated", "due_date IS NULL", ()),
    )
    for name, condition, dates in conditions:
        bucket = buckets[name]
        if not bucket["total"]:
            continue
        rows = connection.execute(
            f"SELECT {','.join(_SUMMARY_COLUMNS)} FROM tasks WHERE {where} AND {condition} "
            "ORDER BY due_date ASC, sequence ASC LIMIT ?",
            (*parameters, *dates, request["per_bucket_limit"]),
        ).fetchall()
        for row in rows:
            item = metadata(connection, dict(zip(_SUMMARY_COLUMNS, row, strict=True)))
            item.pop("dependencies")
            bucket["items"].append(item)
            bucket["omitted"] -= 1
            if len(json.dumps(data, ensure_ascii=True, sort_keys=True)) > request["max_chars"]:
                # Do not split a title, ID or revision, and do not claim an
                # omitted task is absent. Later buckets may still fit a row.
                bucket["items"].pop()
                bucket["omitted"] += 1
                break
    return data
