"""Model-facing task schemas and pure validation, without storage or admission.

Only ``show`` is an alias (for TaskStore's ``get``). Optional fields must be
omitted when irrelevant to an action; null is not a general omission marker.
The flat schemas describe the union of action fields, while validate_request
owns action-specific requirements, bounds, normalization and rejection.
"""

from .tasks import TaskError, validate_request

_READ_ACTIONS = (
    "list",
    "show",
    "search",
    "projects",
    "agenda",
    "history",
    "review",
    "ready",
    "next",
    "followups",
    "native_review",
)
_WRITE_ACTIONS = (
    "capture",
    "capture_plan",
    "breakdown",
    "update",
    "complete",
    "cancel",
    "progress",
    "set_dependencies",
)

PERSONAL_TASKS_READ_SCHEMA = {
    "name": "personal_tasks_read",
    "description": (
        "Read this profile's local task inbox; results become visible to the configured model. "
        "No external action, scheduling or reminders. Recorded work_status is explicit local "
        "progress, not proof of native execution. Work-status filters select active tasks only. "
        "Projects are exact task labels, not "
        "native Project entities. Use only fields relevant to the selected action. "
        "show/history require task_id from an earlier result; never invent IDs. search requires "
        "literal query text. agenda requires an explicit on date and returns active tasks "
        "due on or before it. list/search default to captured. projects returns label counts. "
        "review requires an explicit on date and returns exact active-task counts plus bounded "
        "title summaries for overdue, due-today, upcoming and undated tasks in one snapshot. "
        "Its omitted counts include all unshown tasks; use show/list/agenda for details. "
        "review is not priority inference, task execution or a reminder. "
        "ready returns only captured tasks with recorded ready status and all prerequisites done, "
        "oldest first by creation sequence, not priority. It never dispatches work or proves "
        "execution. Cancelled prerequisites block; missing dependency fields in old receipts "
        "mean unknown, not clear. next returns top eligible tasks by explicit high/normal/low "
        "priority, due date (undated last), then capture order. Default limit 5, maximum 20, "
        "no after cursor. Ranking is planning data, not permission or dispatch. "
        "followups requires explicit on: returns active waiting/blocked tasks whose "
        "follow_up_on is at or before it, ordered by follow-up date, priority, capture order. "
        "Default limit 20, maximum 100, no after cursor. It never schedules reminders, "
        "contacts anyone or changes task status. Do not infer today. "
        "native_review requires explicit on and reads saved native observations only, never "
        "refreshes a board. It groups captured tasks by saved review status, saved done/archived "
        "status, identity issues and observations older than UTC midnight(on)-stale_after_days. "
        "Buckets may overlap; unique_attention is deduplicated. Saved native done/archived is "
        "not local completion or permission to complete; inspect actual results separately. "
        "Missing observations do not prove no linked card. No native action or model sync occurs. "
        "history returns operation metadata in revision order, not previous task text or "
        "proof the real-world task was performed. For history, pass returned next_cursor "
        "as after_revision; other pages use after. Pages are live, not frozen snapshots."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action"],
        "properties": {
            "action": {"type": "string", "enum": list(_READ_ACTIONS)},
            "task_id": {
                "type": "string",
                "format": "uuid",
                "description": "show/history only: exact canonical UUIDv4 returned by this store.",
            },
            "query": {"type": "string", "minLength": 1, "maxLength": 240},
            "state": {
                "type": "string",
                "enum": ["captured", "done", "cancelled", "all"],
                "description": "list/search only; defaults to captured.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": (
                    "list/search/projects/agenda/history/ready default to 20; "
                    "next defaults to 5 and permits at most 20; "
                    "followups defaults to 20, maximum 100."
                ),
            },
            "after": {
                "type": ["string", "null"],
                "description": (
                    "list/search/projects/agenda/ready only: returned next_cursor, or null. "
                    "projects uses an exact label (1-80 characters); others use a task UUIDv4."
                ),
            },
            "after_revision": {
                "type": "integer",
                "minimum": 0,
                "maximum": 2**63 - 1,
                "description": (
                    "history only: exclusive revision cursor from next_cursor; defaults to 0. "
                    "Use the same task_id across pages."
                ),
            },
            "project": {
                "type": "string",
                "minLength": 1,
                "maxLength": 80,
                "description": (
                    "list/search/agenda/review/ready/next/followups/native_review: "
                    "exact case-sensitive label, "
                    "no outer whitespace. "
                    "Mutually exclusive with unassigned."
                ),
            },
            "unassigned": {
                "type": "boolean",
                "description": (
                    "list/search/agenda/review/ready/next/followups/native_review: "
                    "true selects unlabeled tasks."
                ),
            },
            "work_status": {
                "type": "string",
                "enum": ["ready", "in_progress", "waiting", "blocked"],
                "description": (
                    "list/search/agenda/review only: filter recorded active progress. "
                    "With list/search, state must be omitted or captured."
                ),
            },
            "stale_after_days": {
                "type": "integer",
                "minimum": 1,
                "maximum": 365,
                "description": "native_review only: UTC calendar-day age cutoff; defaults to 7.",
            },
            "lookahead_days": {
                "type": "integer",
                "minimum": 0,
                "maximum": 90,
                "description": "review only: days after on included in upcoming; defaults to 7.",
            },
            "per_bucket_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "review/native_review: maximum summaries per bucket; defaults to 5.",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 2048,
                "maximum": 64000,
                "description": (
                    "review/native_review: ASCII-serialized data budget outside the tool envelope; "
                    "defaults to 16000; native_review caps at 32000. "
                    "Summaries are omitted whole, never text-truncated."
                ),
            },
            "on": {
                "type": "string",
                "format": "date",
                "description": (
                    "agenda/review/native_review/followups: "
                    "explicit YYYY-MM-DD date; never infer today."
                ),
            },
        },
    },
}

PERSONAL_TASKS_WRITE_SCHEMA = {
    "name": "personal_tasks_write",
    "description": (
        "Record explicitly requested changes in this profile's local task inbox only. "
        "No external action, scheduling or reminders; completing a record does not perform "
        "the task. Results become visible to the configured model. Every write requires a "
        "stable request_id: reuse it with identical arguments on retry, never generate a "
        "fresh key after an uncertain outcome. capture requires title. "
        "capture_plan requires project and 1-20 task objects in tasks; "
        "it saves all tasks, explicit prerequisite links and one replay receipt atomically, "
        "or saves none. Do not call "
        "capture separately after an uncertain capture_plan. Preserve the same task order "
        "and retry key. A plan records explicitly requested tasks and prerequisites, "
        "not execution or a native Project. The normalized request must fit 32000 "
        "ASCII-serialized characters. Each plan task has title and optional details/due_date "
        "and depends_on: unique ONE-BASED positions in the same ordered tasks array. "
        "Only record explicitly requested prerequisites; order alone creates none. "
        "Forward references are allowed; cycles, self references and out-of-range positions "
        "are rejected. Omitted/empty depends_on means no prerequisites. These local links "
        "gate start/completion but never dispatch work. "
        "breakdown requires task_id, expected_revision and 1-20 explicit task objects in tasks, "
        "not project: use the captured, not-in-progress parent's existing named project. "
        "Only record an explicitly requested breakdown. Every step inherits ALL parent "
        "prerequisites; the parent preserves those and depends on every new step. "
        "Combined prerequisite limits still apply. No parent details are copied, no work is "
        "executed, and no aggregate completion happens automatically. One atomic receipt "
        "covers parent and steps; retry identical arguments/key, never separate captures. "
        "update requires "
        "at least one of title/details/due_date/project/priority/follow_up_on. "
        "update/complete/cancel/progress/set_dependencies require "
        "task_id and expected_revision from a prior read for compare-and-swap (CAS); "
        "never invent IDs or revisions. On revision conflict, read and reconcile first. "
        "complete/cancel/progress require a nonblank note. progress also requires work_status "
        "and records a local working/waiting/blocker update, never starts a worker or verifies "
        "external progress. Only use fields relevant to the action. "
        "set_dependencies requires dependency_ids: replace the entire set with 0-20 unique "
        "canonical UUIDs from prior reads; [] clears it. Only make explicitly requested changes. "
        "Target and prerequisites must share one non-null exact project, without cycles. "
        "Starting (in_progress) or completing requires all prerequisites done; cancelled blocks. "
        "No automatic advancement or dispatch. Projects are labels, not native Project entities. "
        "update/progress may set follow_up_on only for active waiting/blocked tasks, or null "
        "to clear it. It is separate from due_date; ready/in_progress/complete/cancel clear it. "
        "Never pass it to capture, capture_plan or breakdown. No automatic reminder or outreach. "
        "Dates and priority changes must be explicit. Priority is high/normal/low, "
        "not permission, urgency inference or dispatch. Omit priority unless explicitly requested; "
        "new tasks then store normal, not a parent-inherited value."
    ),
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "request_id"],
        "properties": {
            "action": {"type": "string", "enum": list(_WRITE_ACTIONS)},
            "request_id": {
                "type": "string",
                "pattern": "^[A-Za-z0-9._-]{1,128}$",
                "minLength": 1,
                "maxLength": 128,
                "description": "Stable write/retry key; required even for capture.",
            },
            "task_id": {
                "type": "string",
                "format": "uuid",
                "description": (
                    "update/complete/cancel/progress/set_dependencies/breakdown: "
                    "canonical UUIDv4 from a result."
                ),
            },
            "expected_revision": {
                "type": "integer",
                "minimum": 1,
                "maximum": 2**63 - 2,
                "description": (
                    "update/complete/cancel/progress/set_dependencies/breakdown: "
                    "revision from a prior read."
                ),
            },
            "dependency_ids": {
                "type": "array",
                "minItems": 0,
                "maxItems": 20,
                "uniqueItems": True,
                "items": {"type": "string", "format": "uuid"},
                "description": "set_dependencies only: complete replacement set; [] clears it.",
            },
            "title": {"type": "string", "minLength": 1, "maxLength": 240},
            "tasks": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "description": (
                    "capture_plan/breakdown: ordered tasks; breakdown inherits the parent project."
                ),
                "items": {
                    "type": "object",
                    "required": ["title"],
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string", "minLength": 1, "maxLength": 240},
                        "details": {"type": "string", "maxLength": 5000},
                        "priority": {"type": "string", "enum": ["high", "normal", "low"]},
                        "due_date": {"type": "string", "format": "date"},
                        "depends_on": {
                            "type": "array",
                            "maxItems": 19,
                            "uniqueItems": True,
                            "items": {"type": "integer", "minimum": 1, "maximum": 20},
                            "description": (
                                "Explicit prerequisite positions, ONE-BASED in this tasks array. "
                                "Forward references allowed; no self references or cycles. "
                                "Omitted or [] means no batch-local edges; order implies none. "
                                "Breakdown still inherits every existing parent prerequisite."
                            ),
                        },
                    },
                },
            },
            "details": {"type": "string", "maxLength": 5000},
            "follow_up_on": {
                "type": ["string", "null"],
                "format": "date",
                "description": "update/progress only: explicit YYYY-MM-DD; null clears follow-up.",
            },
            "priority": {
                "type": "string",
                "enum": ["high", "normal", "low"],
                "description": "capture/update only: explicitly requested local planning priority.",
            },
            "due_date": {
                "type": ["string", "null"],
                "format": "date",
                "description": "capture/update: YYYY-MM-DD. Null clears it on update only.",
            },
            "project": {
                "type": ["string", "null"],
                "minLength": 1,
                "maxLength": 80,
                "description": (
                    "capture/capture_plan/update: exact case-sensitive label, no outer whitespace. "
                    "capture_plan requires a non-null label. "
                    "Null means unassigned (clears the label on update)."
                ),
            },
            "work_status": {
                "type": "string",
                "enum": ["ready", "in_progress", "waiting", "blocked"],
                "description": "progress only: explicitly requested local work status.",
            },
            "note": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "complete/cancel/progress: explicit resolution or progress note.",
            },
        },
    },
}


def normalize_task_tool_request(tool_name: str, arguments: dict) -> tuple[str, dict]:
    """Return TaskStore.run arguments; no identity or authorization comes from input."""
    if not isinstance(tool_name, str) or not isinstance(arguments, dict):
        raise TaskError("invalid_request")
    if tool_name == "personal_tasks_read":
        allowed = _READ_ACTIONS
    elif tool_name == "personal_tasks_write":
        allowed = _WRITE_ACTIONS
    else:
        raise TaskError("invalid_request")
    action = arguments.get("action")
    if not isinstance(action, str) or action not in allowed:
        raise TaskError("invalid_request")
    operation = "get" if action == "show" else action
    payload = {key: value for key, value in arguments.items() if key != "action"}
    return operation, validate_request(operation, payload)
