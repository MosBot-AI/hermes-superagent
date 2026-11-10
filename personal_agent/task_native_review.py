"""Bounded attention summaries of saved local observations, never live native reads."""

import bisect
import json
from datetime import UTC, datetime, timedelta

from .task_native_sync import FAILURES, validate_observation

BUCKETS = ("awaiting_review", "board_closed", "identity_issue", "stale")
_COLUMNS = ("id", "title", "revision", "project", "due_date", "work_status", "priority")


def _size(data):
    return len(json.dumps(data, ensure_ascii=True, sort_keys=True))


def task_native_review(connection, request):
    """Use caller's read snapshot; scan all matching metadata, retain bounded samples.

    Counts are not bounded work. Output limits count escaped JSON characters, not
    tokens. Saved observations can be stale and never imply local completion.
    """
    from .tasks import TaskError

    cutoff = datetime.fromisoformat(request["on"]).replace(tzinfo=UTC) - timedelta(
        days=request["stale_after_days"]
    )
    cutoff_seconds = (cutoff - datetime(1970, 1, 1, tzinfo=UTC)).days * 86400
    clauses, parameters, filters = ["t.state='captured'"], [], {}
    if "project" in request:
        clauses.append("t.project=? COLLATE BINARY")
        parameters.append(request["project"])
        filters["project"] = request["project"]
    elif request.get("unassigned"):
        clauses.append("t.project IS NULL")
        filters["unassigned"] = True
    counts = dict.fromkeys(
        ("total_active", "active_observed", "active_unobserved", "unique_attention", *BUCKETS), 0
    )
    samples = {name: [] for name in BUCKETS}
    rows = connection.execute(
        "SELECT "
        + ",".join("t." + column for column in _COLUMNS)
        + ",t.sequence,p.observation FROM tasks t LEFT JOIN task_native_progress p "
        "ON p.task_id=t.id WHERE " + " AND ".join(clauses),
        parameters,
    )
    for row in rows:
        counts["total_active"] += 1
        raw = row[-1]
        if raw is None:
            counts["active_unobserved"] += 1
            continue
        try:
            if type(raw) is not str or len(raw) > 2048:
                raise TaskError("storage_corrupt")
            observation = validate_observation(json.loads(raw))
        except ValueError, TypeError, TaskError:
            raise TaskError("storage_corrupt") from None
        counts["active_observed"] += 1
        categories = []
        if observation["outcome"] == "current":
            if observation["status"] == "review":
                categories.append("awaiting_review")
            elif observation["status"] in ("done", "archived"):
                categories.append("board_closed")
        elif observation["outcome"] in FAILURES:
            categories.append("identity_issue")
        if observation["observed_at"] < cutoff_seconds:
            categories.append("stale")
        if categories:
            counts["unique_attention"] += 1
        item = {
            **dict(zip(_COLUMNS, row[: len(_COLUMNS)], strict=True)),
            "native_progress": observation,
        }
        for name in categories:
            counts[name] += 1
            sample = samples[name]
            bisect.insort(sample, (observation["observed_at"], row[-2], item))
            if len(sample) > request["per_bucket_limit"]:
                sample.pop()
    buckets: dict[str, dict] = {
        name: {"total": counts[name], "items": [], "omitted": counts[name]} for name in BUCKETS
    }
    data = {
        "on": request["on"],
        "stale_after_days": request["stale_after_days"],
        "stale_before": cutoff.isoformat().replace("+00:00", "Z"),
        "filters": filters,
        "counts": counts,
        "buckets": buckets,
    }
    for name in BUCKETS:
        bucket = data["buckets"][name]
        for _, _, item in samples[name]:
            bucket["items"].append(item)
            bucket["omitted"] -= 1
            if _size(data) > request["max_chars"]:
                bucket["items"].pop()
                bucket["omitted"] += 1
                # Preserve the oldest-first prefix; don't silently skip to smaller rows.
                break
    if _size(data) > request["max_chars"]:
        raise TaskError("invalid_request")
    return data
