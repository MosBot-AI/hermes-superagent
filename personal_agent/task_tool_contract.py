"""Model-facing task schemas and pure validation, without storage or admission.

Only ``show`` is an alias (for TaskStore's ``get``). Optional fields must be
omitted when irrelevant to an action; null is not a general omission marker.
The flat schemas describe the union of action fields, while validate_request
owns action-specific requirements, bounds, normalization and rejection.
"""

from .tasks import TaskError, validate_request

_READ_ACTIONS = ("list", "show", "search", "projects", "agenda", "history")
_WRITE_ACTIONS = ("capture", "update", "complete", "cancel")

PERSONAL_TASKS_READ_SCHEMA = {
    "name": "personal_tasks_read",
    "description": (
        "Read this profile's local task inbox; results become visible to the configured model. "
        "No external action, scheduling or reminders. Projects are exact task labels, not "
        "native Project entities. Use only fields relevant to the selected action. "
        "show/history require task_id from an earlier result; never invent IDs. search requires "
        "literal query text. agenda requires an explicit on date and returns active tasks "
        "due on or before it. list/search default to captured. projects returns label counts. "
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
                "description": "All reads except show; defaults to 20.",
            },
            "after": {
                "type": ["string", "null"],
                "description": (
                    "All reads except show/history: returned next_cursor, or null. "
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
                    "list/search/agenda only: exact case-sensitive label, no outer whitespace. "
                    "Mutually exclusive with unassigned."
                ),
            },
            "unassigned": {
                "type": "boolean",
                "description": "list/search/agenda only: true selects unlabeled tasks.",
            },
            "on": {
                "type": "string",
                "format": "date",
                "description": "agenda only: explicit YYYY-MM-DD date; do not infer a date.",
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
        "fresh key after an uncertain outcome. capture requires title. update requires "
        "at least one of title/details/due_date/project. update/complete/cancel require "
        "task_id and expected_revision from a prior read for compare-and-swap (CAS); "
        "never invent IDs or revisions. On revision conflict, read and reconcile first. "
        "complete/cancel require a nonblank note. Only use fields relevant to the action. "
        "Projects are labels, not native Project entities. Dates must be explicit."
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
                "description": "update/complete/cancel: exact canonical UUIDv4 from a result.",
            },
            "expected_revision": {
                "type": "integer",
                "minimum": 1,
                "maximum": 2**63 - 2,
                "description": "update/complete/cancel: revision returned by a prior read.",
            },
            "title": {"type": "string", "minLength": 1, "maxLength": 240},
            "details": {"type": "string", "maxLength": 5000},
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
                    "capture/update: exact case-sensitive label, no outer whitespace. "
                    "Null means unassigned (clears the label on update)."
                ),
            },
            "note": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "complete/cancel only: explicit nonblank resolution note.",
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
