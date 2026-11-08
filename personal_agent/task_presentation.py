"""Deterministic human-readable views of existing task results, never new actions."""

import json
import shlex

_PAGE_ITEMS = 20
_REVIEW_ITEMS = 5
_STATUS = {
    "ready": "ready",
    "in_progress": "in progress",
    "waiting": "waiting",
    "blocked": "blocked",
}
_ERRORS = {
    "project_not_found": "The exact source project label has no tasks.",
    "project_exists": "The destination label is already in use. Groups are never merged.",
    "project_rename_limit": "This group exceeds the 1,000-task rename limit. Nothing changed.",
    "project_snapshot_conflict": "The source group changed. Preview again before renaming.",
    "breakdown_in_progress": (
        "An in-progress task cannot be broken down. Explicitly record a non-running "
        "work status after reviewing actual work, then retry from its current revision."
    ),
    "dependency_limit": (
        "Existing prerequisites plus new steps exceed the 20-prerequisite limit. "
        "No steps or links were saved; review the plan without dropping required prerequisites."
    ),
    "dependency_cycle": "These prerequisites would form a cycle. No dependency change was saved.",
    "dependency_project_required": "Dependencies require a named project on the target task.",
    "dependency_project_mismatch": "Every prerequisite must share the target's exact project.",
    "dependencies_unsatisfied": (
        "Starting or completing is blocked until every prerequisite is marked done. "
        "Cancelled prerequisites also block; no work was dispatched."
    ),
    "dependency_project_locked": (
        "This project label is locked by dependencies. Explicitly remove the related edges first."
    ),
    "invalid_request": "Invalid task command. Check the required fields and bounds with help.",
    "not_found": "Task not found. List the inbox and use an ID returned by it.",
    ("revision_conflict"): (
        "The task changed. Read its current revision and reconcile before editing."
    ),
    ("idempotency_conflict"): (
        "This request ID was already used with different arguments. Check the "
        "original request before making a new change."
    ),
    ("terminal_state"): (
        "This task is already done or cancelled. Progress and edits cannot reopen it."
    ),
    "invalid_cursor": "This page cursor is no longer valid. Start a fresh list or history read.",
    ("storage_busy"): (
        "Task storage is busy. For a write, retry later with the same request ID "
        "and identical arguments."
    ),
    ("storage_corrupt"): (
        "Task storage could not be read safely. Stop changes and inspect a supported backup."
    ),
    ("unsupported_schema"): (
        "This task database version or structure is unsupported. Use a compatible"
        " plugin; no repair was attempted."
    ),
    ("foreign_database"): (
        "The storage file is not a recognized task database. It was not adopted or repaired."
    ),
    ("unsafe_storage_file"): (
        "Task storage failed its private-file checks. No permission repair was attempted."
    ),
    ("unsafe_storage_path"): (
        "Task storage failed its private-path checks. No permission repair was attempted."
    ),
    "unsupported_storage_platform": "Task storage is not supported on this operating system.",
    ("profile_context_changed"): (
        "The active profile changed or disappeared. Reload the intended profile before using tasks."
    ),
    "invalid_configuration": "Task configuration is invalid. Review the trusted local task setup.",
    "local_tasks_disabled": "Local tasks are disabled in this profile.",
    "local_conversation_disabled": "Local task conversation commands are disabled in this profile.",
    "unsupported_origin": "This command is unavailable from this session origin.",
    ("storage_error"): (
        "The task operation failed. Do not assume a write succeeded; inspect the "
        "task or retry the identical request ID and arguments."
    ),
    ("local_tasks_unavailable"): (
        "The task operation is unavailable. Do not assume a write succeeded; "
        "inspect the task before making another change."
    ),
    ("connection_in_transaction"): (
        "Task storage is already in a transaction. No nested operation was started."
    ),
    "not_initialized": "Task storage is not initialized.",
}


def _quoted(value: str) -> str:
    # Delimit stored text and escape newlines/controls rather than allowing it
    # to masquerade as a status line or a generated command.
    return json.dumps(value, ensure_ascii=False)


def _command(prefix: str, operation: str, fields: dict) -> str:
    parts = [*shlex.split(prefix), operation]
    if "task_id" in fields:
        parts.append(fields["task_id"])
    for key, value in fields.items():
        if key == "task_id" or value is None or value is False:
            continue
        flag = "--" + key.replace("_", "-")
        parts.extend([flag] if value is True else [flag + "=" + str(value)])
    if prefix == "hermes personal-agent tasks":
        parts.extend(("--format", "text"))
    return shlex.join(parts)


def _native_progress_lines(task: dict, *, full: bool) -> list[str]:
    if "native_progress" not in task:
        return ["  Native board: unknown (not recorded in this receipt)."]
    observation = task["native_progress"]
    if observation is None:
        return ["  Native board: no observations recorded."]
    outcome = observation["outcome"]
    states = {
        "triage",
        "todo",
        "scheduled",
        "ready",
        "running",
        "blocked",
        "review",
        "done",
        "archived",
    }
    unavailable = {
        "missing",
        "duplicate",
        "identity_changed",
        "key_changed",
        "identity_unavailable",
    }
    if outcome == "current" and observation["status"] in states:
        label = observation["status"]
    elif outcome in unavailable and observation["status"] is None:
        label = outcome + "; status unavailable"
    else:
        label = "unverified; status unavailable"
    lines = [
        f"  Native board observed {label} (not local completion)"
        + f" | UTC epoch seconds: {observation['observed_at']}"
    ]
    if full:
        lines.append(
            f"  Handoff: {observation['handoff_id']} | native card: {observation['card_id']}"
            + f" | exported revision: {observation['exported_revision']}"
        )
    return lines


def _task_lines(task: dict, *, full: bool = False) -> list[str]:
    state = task["state"] if "state" in task else "captured"
    work = _STATUS.get(task.get("work_status"), "not recorded in this receipt")
    phase = work if state == "captured" else state
    lines = [
        f"- {_quoted(task['title'])} [{phase}]",
        f"  ID: {task['id']} | revision: {task['revision']}",
    ]
    if task.get("project") is not None:
        lines.append("  Project: " + _quoted(task["project"]))
    lines.append("  Due: " + (task.get("due_date") or "not set"))
    if all(key in task for key in ("dependencies_satisfied", "unsatisfied_dependency_count")):
        lines.append(
            "  Prerequisites: "
            + (f"{len(task['dependencies'])} | " if "dependencies" in task else "")
            + f"unsatisfied: {task['unsatisfied_dependency_count']} | "
            + ("satisfied" if task["dependencies_satisfied"] else "blocked")
        )
        if full:
            for dependency in task.get("dependencies", []):
                lines.append(
                    f"    {dependency['task_id']} | revision: {dependency['revision']} | "
                    f"state: {dependency['state']}"
                )
    else:
        lines.append("  Prerequisites: unknown (not recorded in this receipt).")
    lines.extend(_native_progress_lines(task, full=full))
    if full:
        if task.get("details"):
            lines.append("  Details: " + _quoted(task["details"]))
        if task.get("progress_note"):
            label = "Progress note" if state == "captured" else "Last recorded progress note"
            lines.append(f"  {label}: " + _quoted(task["progress_note"]))
        if task.get("progress_updated_at"):
            lines.append("  Progress recorded: " + task["progress_updated_at"])
        if task.get("resolution_note"):
            lines.append("  Resolution note: " + _quoted(task["resolution_note"]))
    return lines


def _help(prefix: str) -> str:
    return "\n".join(
        [
            "Local task workbench",
            (
                "Record and review tasks here. These commands do not execute work"
                " or schedule reminders."
            ),
            "",
            "Capture: " + prefix + ' add "Title" --project "Demo" --request-id capture-1',
            "Plan: "
            + prefix
            + ' plan --project "Demo" --task "First" --task "Second" --request-id plan-1',
            "Break down: "
            + prefix
            + (
                ' breakdown TASK_ID --expected-revision N --task "First" --task "Second" '
                "--request-id breakdown-1"
            ),
            (
                "Breakdown preserves and inherits existing prerequisites, then makes the "
                "original task depend on every new step. It never completes the original task."
            ),
            "Review: " + prefix + " review --on YYYY-MM-DD",
            "Saved native attention: " + prefix + " native-review --on YYYY-MM-DD",
            "Blocked: " + prefix + " list --work-status blocked",
            "Projects: " + prefix + " projects",
            "Rename preview: " + prefix + " project-rename-preview --project OLD --new-project NEW",
            "Rename: " + prefix + " rename-project --project OLD --new-project NEW "
            "--expected-snapshot HASH --request-id KEY",
            "Rename includes terminal tasks and preserves edges; destination must be unused.",
            "Available: " + prefix + " ready [--project LABEL | --unassigned]",
            "Dependencies: "
            + prefix
            + (
                " dependencies TASK_ID --expected-revision N "
                "(--needs ID [--needs ID...] | --clear) --request-id dependencies-1"
            ),
            "Dependencies replace the whole set; same named project, at most 20, no cycles.",
            "Starting/completing requires all prerequisites done; cancelled also blocks.",
            (
                "Ready pages are oldest first, not priority or dispatch. "
                "Nothing advances automatically."
            ),
            "Details: " + prefix + " show TASK_ID",
            "Progress: "
            + prefix
            + (
                " progress TASK_ID --expected-revision N --work-status "
                'in_progress --note "Progress" --request-id progress-1'
            ),
            "Finish: "
            + prefix
            + ' done TASK_ID --expected-revision N --note "Result" --request-id done-1',
            "Edit: "
            + prefix
            + ' update TASK_ID --expected-revision N --title "Title" --request-id edit-1',
            "Cancel: "
            + prefix
            + ' cancel TASK_ID --expected-revision N --note "Reason" --request-id cancel-1',
            "History: " + prefix + " history TASK_ID",
            "",
            "Use returned IDs and revisions, and an explicit date. Project names are exact labels.",
            (
                "Work status: ready, in_progress, waiting or blocked. A status is"
                " not worker execution evidence."
            ),
            (
                "For an uncertain write, reuse its request ID and identical "
                "arguments. No automatic retry."
            ),
            (
                "Use /personal-tasks --json COMMAND for structured results, "
                "including admission errors."
            ),
        ]
    )


def _page(data: dict, operation: str, payload: dict, prefix: str) -> list[str]:
    items = data["items"]
    shown = items[:_PAGE_ITEMS]
    labels = {
        "list": "Task inbox",
        "search": "Task search",
        "ready": "Available local work (oldest first, not priority)",
        "agenda": "Tasks due on or before " + payload.get("on", ""),
    }
    lines = [labels[operation]]
    if operation == "ready":
        lines.append(f"Total eligible: {data['total_eligible']}")
        lines.append(
            "Captured tasks with recorded ready status and all prerequisites done. "
            "No dispatch or execution evidence."
        )
    if "project" in payload:
        lines.append("Project: " + _quoted(payload["project"]))
    elif payload.get("unassigned"):
        lines.append("Project: unassigned")
    if "work_status" in payload:
        lines.append("Work status: " + _STATUS[payload["work_status"]])
    if "query" in payload:
        lines.append("Literal query: " + _quoted(payload["query"]))
    if not shown:
        lines.append("No tasks on this page for these filters.")
    for task in shown:
        lines.extend(_task_lines(task))
    lines.append(f"Shown: {len(shown)} task(s). Details and progress notes are not shown here.")
    more = len(items) > len(shown) or data["has_more"]
    if more:
        fields = {k: v for k, v in payload.items() if k not in ("after", "limit")}
        fields.update(limit=_PAGE_ITEMS, after=shown[-1]["id"])
        lines.append("More: " + _command(prefix, operation, fields))
    lines.append("Inspect: " + _command(prefix, "show", {"task_id": "TASK_ID"}))
    return lines


def _review(data: dict, prefix: str) -> list[str]:
    counts = data["counts"]
    lines = [f"Task review for {data['on']} (upcoming through {data['through']})"]
    filters = data["filters"]
    if "project" in filters:
        lines.append("Project: " + _quoted(filters["project"]))
    elif filters.get("unassigned"):
        lines.append("Project: unassigned")
    if "work_status" in filters:
        lines.append("Work status: " + _STATUS[filters["work_status"]])
    lines.append(
        f"Active: {counts['total_active']} | overdue: {counts['overdue']} | "
        f"today: {counts['due_today']} | upcoming: {counts['upcoming']} | "
        f"later: {counts['later']} | undated: {counts['undated']}"
    )
    progress = data["progress_counts"]
    lines.append(
        "Recorded progress: " + ", ".join(f"{_STATUS[key]} {progress[key]}" for key in _STATUS)
    )
    dependency_counts = data.get("dependency_counts")
    if dependency_counts is not None:
        lines.append(
            f"Prerequisites: satisfied {dependency_counts['satisfied']}, "
            f"blocked {dependency_counts['blocked']} (not execution evidence)"
        )
    else:
        lines.append("Prerequisite counts: unknown (not recorded in this receipt).")
    for name, label in (
        ("overdue", "Overdue"),
        ("due_today", "Due today"),
        ("upcoming", "Upcoming"),
        ("undated", "No due date"),
    ):
        bucket = data["buckets"][name]
        shown = bucket["items"][:_REVIEW_ITEMS]
        lines.extend(["", f"{label}: {bucket['total']}"])
        for task in shown:
            lines.extend(_task_lines(task))
        omitted = bucket["total"] - len(shown)
        if omitted:
            lines.append(f"Not shown: {omitted} task(s), due to result or display limits.")
        elif not shown:
            lines.append("None.")
    lines.extend(
        [
            "",
            f"Later than {data['through']}: {counts['later']} task(s), count only.",
            "This is a dated overview, not a priority or execution decision.",
            "Details/blocker notes: " + _command(prefix, "show", {"task_id": "TASK_ID"}),
            "Browse: " + _command(prefix, "list", {**filters, "limit": _PAGE_ITEMS}),
        ]
    )
    return lines


def _native_review(data: dict) -> list[str]:
    counts = data["counts"]
    lines = [
        f"Saved native attention review for {data['on']}",
        "Saved observations need manual verification; not live state or local completion.",
        f"Stale before {data['stale_before']} (UTC; explicit date, not background monitoring).",
        f"Active: {counts['total_active']} | observed: {counts['active_observed']} | "
        f"unobserved: {counts['active_unobserved']}",
        f"Unique attention: {counts['unique_attention']} (buckets may overlap).",
        "Unobserved does not mean no linked card exists.",
    ]
    filters = data["filters"]
    if "project" in filters:
        lines.append("Project: " + _quoted(filters["project"]))
    elif filters.get("unassigned"):
        lines.append("Project: unassigned")
    for name, label in (
        ("awaiting_review", "Saved board awaiting review"),
        ("board_closed", "Saved board done or archived"),
        ("identity_issue", "Saved identity issue"),
        ("stale", "Stale saved observation"),
    ):
        bucket = data["buckets"][name]
        shown = bucket["items"][:_PAGE_ITEMS]
        lines.extend(["", f"{label}: {bucket['total']}"])
        for task in shown:
            lines.extend(_task_lines(task))
        omitted = bucket["total"] - len(shown)
        if omitted:
            lines.append(f"Not shown: {omitted} task(s), due to result or display limits.")
        elif not shown:
            lines.append("None.")
    lines.append("Local snapshots only. No board refresh, completion, unblocking or dispatch.")
    return lines


def _render(result: dict, *, operation: str, payload: dict, prefix: str) -> str:
    request_id = result.get("request_id") or payload.get("request_id")
    if result["status"] != "ok":
        code = result["error"]["code"]
        known = code if code in _ERRORS else "local_tasks_unavailable"
        lines = ["Task request failed: " + known, _ERRORS[known]]
        if request_id:
            lines.append("Request ID: " + request_id)
        return "\n".join(lines)
    data = result["data"]
    if operation == "help":
        return _help(prefix)
    if operation in ("list", "search", "agenda", "ready"):
        lines = _page(data, operation, payload, prefix)
    elif operation in ("project_rename_preview", "rename_project"):
        preview = operation == "project_rename_preview"
        lines = [
            "Project rename preview (no rename saved)." if preview else "Project label renamed.",
            "From: " + _quoted(data["project"]),
            "To: " + _quoted(data["new_project"]),
            f"All tasks: {data['task_count']} (including done and cancelled).",
            "States: " + json.dumps(data["state_counts"], sort_keys=True),
            "Snapshot: " + data["snapshot"],
            "No native project, worker, reminder or external resource was changed.",
        ]
        if preview:
            lines.append(
                "Confirm explicitly with rename-project, this snapshot and a stable request ID."
            )
        elif result.get("replayed"):
            lines.insert(0, "Replayed historical receipt; read current tasks for live state.")
    elif operation in ("capture_plan", "breakdown"):
        breakdown = operation == "breakdown"
        label = "Task breakdown" if breakdown else "Plan"
        lines = [
            f"{label} saved: {len(data['items'])} task(s).",
            "Project: " + _quoted(data["project"]),
        ]
        if result.get("replayed"):
            lines.insert(0, "Replayed saved plan receipt. Use show for each task's current state.")
        if breakdown:
            lines.append("Original task (not completed):")
            lines.extend(_task_lines(data["parent"]))
            inherited = data["inherited_dependency_ids"]
            lines.append(f"Existing prerequisites inherited by every new step: {len(inherited)}.")
            for task_id in inherited:
                lines.append("  Inherited prerequisite: " + task_id)
            lines.append(
                "Original task now depends on every new step and all its previous prerequisites. "
                "Finishing steps only unblocks it; "
                "explicit review and completion are still required."
            )
            lines.append(
                "Cancelling the original task does not cancel its steps. "
                "These are editable dependency links, not exclusive subtask ownership."
            )
        positions = {task["id"]: index for index, task in enumerate(data["items"], 1)}
        for index, task in enumerate(data["items"], 1):
            lines.append(f"Plan item {index}:")
            lines.extend(_task_lines(task))
            prerequisites = task.get("dependencies", [])
            if prerequisites:
                needs = sorted(
                    positions[item["task_id"]]
                    for item in prerequisites
                    if item["task_id"] in positions
                )
                if needs:
                    lines.append("  Needs plan item(s): " + ", ".join(map(str, needs)))
                if any(item["task_id"] not in positions for item in prerequisites):
                    lines.append(
                        "  Also requires the inherited prerequisites listed above."
                        if breakdown
                        else "  Some prerequisite IDs are outside this receipt; use show."
                    )
        if all(isinstance(task.get("dependencies"), list) for task in data["items"]):
            links = sum(len(task["dependencies"]) for task in data["items"])
            if breakdown:
                links += len(data["items"])  # New original-task -> step edges, not preserved edges.
            lines.append(f"Saved prerequisite links: {links}. Input order is not execution order.")
        else:
            lines.append("Prerequisite metadata unavailable in this historical receipt.")
        lines.append(
            "All tasks and explicit links saved together. No task started, completed or dispatched."
        )
        if breakdown:
            lines.append("Original: " + _command(prefix, "show", {"task_id": data["parent"]["id"]}))
        lines.append("Browse: " + _command(prefix, "list", {"project": data["project"]}))
        lines.append("Ready: " + _command(prefix, "ready", {"project": data["project"]}))
    elif operation == "native_review":
        lines = _native_review(data)
    elif operation == "review":
        lines = _review(data, prefix)
    elif operation == "projects":
        shown = data["items"][:_PAGE_ITEMS]
        lines = ["Project labels"]
        for item in shown:
            lines.append(
                f"- {_quoted(item['project'])}: active {item['captured']}, "
                f"done {item['done']}, cancelled {item['cancelled']}"
            )
        unassigned = data["unassigned_counts"]
        lines.append(
            f"Unassigned: active {unassigned['captured']}, done {unassigned['done']}, "
            f"cancelled {unassigned['cancelled']}"
        )
        if not shown:
            lines.append("No project labels on this page.")
        if len(data["items"]) > len(shown) or data["has_more"]:
            lines.append(
                "More: "
                + _command(prefix, operation, {"limit": _PAGE_ITEMS, "after": shown[-1]["project"]})
            )
        lines.append("Projects are local labels, not native project or permission boundaries.")
    elif operation == "history":
        lines = [
            f"Task history: {data['task_id']}",
            f"Current state: {data['current_state']} | revision: {data['current_revision']}",
        ]
        shown = data["items"][:_PAGE_ITEMS]
        lines.extend(
            f"- Revision {item['revision']}: {item['operation']} at {item['timestamp']}"
            for item in shown
        )
        if not shown:
            lines.append("No operations after this revision.")
        if len(data["items"]) > len(shown) or data["has_more"]:
            lines.append(
                "More: "
                + _command(
                    prefix,
                    operation,
                    {
                        "task_id": data["task_id"],
                        "limit": _PAGE_ITEMS,
                        "after_revision": shown[-1]["revision"],
                    },
                )
            )
        lines.append(
            "Operation metadata only, not prior text, verified authorship or execution proof."
        )
    else:
        headings = {
            "capture": "Task saved.",
            "update": "Task record updated.",
            "progress": "Local progress recorded.",
            "set_dependencies": "Task prerequisites replaced.",
            "complete": "Task marked done in the local inbox.",
            "cancel": "Task marked cancelled in the local inbox.",
            "get": "Task details",
        }
        lines = [headings[operation], *_task_lines(data, full=True)]
        if result.get("replayed"):
            lines.insert(
                0,
                (
                    "Replayed saved receipt. This may be an older revision; use "
                    "show for current state."
                ),
            )
        if operation != "get":
            lines.append(
                "This changes a local record only; no work, reminder or "
                "external action was executed."
            )
            lines.append("Inspect: " + _command(prefix, "show", {"task_id": data["id"]}))
    if request_id:
        lines.append("Request ID: " + request_id)
    return "\n".join(lines)


def render_task_result(
    result: dict, *, operation: str, payload: dict, prefix: str = "/personal-tasks"
) -> str:
    """Render an existing result without storage/config/model access or mutations.

    Never turn a committed write into a presentation error. If an unexpected
    legacy shape cannot be rendered, retain the real structured receipt instead.
    """
    try:
        return _render(result, operation=operation, payload=payload, prefix=prefix)
    except KeyError, TypeError, ValueError, IndexError:
        return json.dumps(result, ensure_ascii=True, sort_keys=True)
