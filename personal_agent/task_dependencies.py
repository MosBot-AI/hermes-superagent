"""Local dependency graph checks; callers own the SQLite snapshot/transaction."""

SCHEMA = {
    "task_dependencies": """CREATE TABLE task_dependencies (
        task_id TEXT NOT NULL, dependency_id TEXT NOT NULL,
        PRIMARY KEY(task_id, dependency_id))"""
}


def _fail(code):
    from .tasks import TaskError

    raise TaskError(code)


def metadata(connection, task):
    from .tasks import TaskError, _task_id

    # Broken incoming edges are corrupt too, not permission to move an endpoint.
    if connection.execute(
        "SELECT 1 FROM task_dependencies d LEFT JOIN tasks t ON t.id=d.task_id "
        "WHERE d.dependency_id=? AND (t.id IS NULL OR t.project IS NULL "
        "OR ? IS NULL OR t.project != ? COLLATE BINARY) LIMIT 1",
        (task["id"], task["project"], task["project"]),
    ).fetchone():
        _fail("storage_corrupt")
    rows = connection.execute(
        "SELECT d.dependency_id,t.revision,t.state,t.project FROM task_dependencies d "
        "LEFT JOIN tasks t ON t.id=d.dependency_id WHERE d.task_id=? "
        "ORDER BY d.dependency_id LIMIT 21",
        (task["id"],),
    ).fetchall()
    if len(rows) > 20 or any(
        row[1] is None
        or task["project"] is None
        or row[3] != task["project"]
        or row[2] not in ("captured", "done", "cancelled")
        for row in rows
    ):
        _fail("storage_corrupt")
    for row in rows:
        try:
            _task_id(row[0])
        except TaskError:
            _fail("storage_corrupt")
        if row[0] == task["id"] or type(row[1]) is not int or row[1] < 1:
            _fail("storage_corrupt")
    dependencies = [
        dict(zip(("task_id", "revision", "state"), row[:3], strict=True)) for row in rows
    ]
    blocked = sum(row[2] != "done" for row in rows)
    return {
        **task,
        "dependencies": dependencies,
        "dependencies_satisfied": not blocked,
        "unsatisfied_dependency_count": blocked,
    }


def check_project_change(connection, task, project):
    if (
        project != task["project"]
        and connection.execute(
            "SELECT 1 FROM task_dependencies WHERE task_id=? OR dependency_id=? LIMIT 1",
            (task["id"], task["id"]),
        ).fetchone()
    ):
        _fail("dependency_project_locked")


def replace(connection, task, ids):
    if task["project"] is None:
        _fail("dependency_project_required")
    for dependency in ids:
        if dependency == task["id"]:
            _fail("dependency_cycle")
        row = connection.execute(
            "SELECT project,state FROM tasks WHERE id=?", (dependency,)
        ).fetchone()
        if row is None:
            _fail("not_found")
        if row[0] != task["project"]:
            _fail("dependency_project_mismatch")
        if task["work_status"] == "in_progress" and row[1] != "done":
            _fail("dependencies_unsatisfied")
        # UNION (not UNION ALL) also terminates on an already-corrupt cyclic graph.
        if connection.execute(
            "WITH RECURSIVE reachable(id) AS (SELECT ? UNION SELECT d.dependency_id "
            "FROM task_dependencies d JOIN reachable r ON d.task_id=r.id) "
            "SELECT 1 FROM reachable WHERE id=?",
            (dependency, task["id"]),
        ).fetchone():
            _fail("dependency_cycle")
    connection.execute("DELETE FROM task_dependencies WHERE task_id=?", (task["id"],))
    connection.executemany(
        "INSERT INTO task_dependencies VALUES (?,?)", [(task["id"], dep) for dep in ids]
    )


def ready(connection, request, get):
    clauses = ["state='captured'", "work_status='ready'"]
    args = []
    if "project" in request:
        clauses.append("project=? COLLATE BINARY")
        args.append(request["project"])
    elif request.get("unassigned"):
        clauses.append("project IS NULL")
    rows = connection.execute(
        "SELECT id,sequence,project FROM tasks WHERE "
        + " AND ".join(clauses)
        + " ORDER BY sequence ASC",
        args,
    ).fetchall()
    eligible = [(metadata(connection, {"id": row[0], "project": row[2]}), row[1]) for row in rows]
    eligible = [(task, seq) for task, seq in eligible if task["dependencies_satisfied"]]
    after = 0
    if request["after"] is not None:
        cursor = connection.execute(
            "SELECT sequence FROM tasks WHERE id=?", (request["after"],)
        ).fetchone()
        if cursor is None:
            _fail("invalid_cursor")
        after = cursor[0]
    remaining = [task for task, seq in eligible if seq > after]
    items = [get(task["id"]) for task in remaining[: request["limit"]]]
    more = len(remaining) > len(items)
    return {
        "items": items,
        "next_cursor": items[-1]["id"] if more else None,
        "has_more": more,
        "total_eligible": len(eligible),
    }


def normalize_plan_references(items):
    """Validate batch-local one-based references and DAG before any transaction.

    Return parallel sorted lists; callers omit empty lists from normalized intent
    so earlier plans retain their historical request digest.
    """
    graph = []
    for position, item in enumerate(items, 1):
        references = item.get("depends_on", [])
        if type(references) is not list or len(references) > len(items):
            _fail("invalid_request")
        if any(type(value) is not int or not 1 <= value <= len(items) for value in references):
            _fail("invalid_request")
        if len(set(references)) != len(references):
            _fail("invalid_request")
        if position in references:
            _fail("dependency_cycle")
        graph.append(sorted(references))
    visiting, visited = set(), set()

    def visit(position):
        if position in visiting:
            _fail("dependency_cycle")
        if position in visited:
            return
        visiting.add(position)
        for prerequisite in graph[position - 1]:
            visit(prerequisite)
        visiting.remove(position)
        visited.add(position)

    for position in range(1, len(items) + 1):
        visit(position)
    return graph


def next_tasks(connection, request, get):
    """Bounded top-N, not a cursor page or execution/authorization decision.

    Scan eligible metadata in the caller's read snapshot for accurate totals;
    only selected records materialize payload. Bounds are not CPU/SLA promises.
    """
    clauses, args = ["state='captured'", "work_status='ready'"], []
    if "project" in request:
        clauses.append("project=? COLLATE BINARY")
        args.append(request["project"])
    elif request.get("unassigned"):
        clauses.append("project IS NULL")
    rows = connection.execute(
        "SELECT id,project,priority FROM tasks WHERE "
        + " AND ".join(clauses)
        + " ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,"
        + " due_date IS NULL,due_date ASC,sequence ASC",
        args,
    )
    total, selected = 0, []
    for task_id, project, priority in rows:
        if priority not in ("high", "normal", "low"):
            _fail("storage_corrupt")
        current = metadata(connection, {"id": task_id, "project": project})
        if current["dependencies_satisfied"]:
            total += 1
            if len(selected) < request["limit"]:
                selected.append(task_id)
    return {
        "items": [get(task_id) for task_id in selected],
        "total": total,
        "omitted": total - len(selected),
        "limit": request["limit"],
        "ordering": "priority_high_normal_low_then_due_date_undated_last_then_capture_order",
        "scope": "active_manually_ready_dependency_satisfied",
        "authority": "planning_data_not_permission_or_dispatch",
    }
