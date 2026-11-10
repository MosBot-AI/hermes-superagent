"""Pure local-record projection; not an authorized reader or HTTP endpoint."""

import unicodedata
from typing import TypedDict
from uuid import UUID


class ClientTask(TypedDict):
    id: str
    title: str
    revision: str
    state: str
    wait_reason: str | None


class ClientTaskProjectionError(ValueError):
    """Redacted, non-retryable invalid-record failure, without source payloads."""

    def __init__(self) -> None:
        super().__init__("Invalid local task record for shared projection.")


def project_local_task(record: object) -> ClientTask:
    """Project an already-admitted current TaskStore record into the shared shape.

    This function performs no I/O or admission. Callers must acquire a current,
    authorized record; a successful projection does not prove scope or freshness.
    Progress describes recorded local work, not native-worker liveness. Terminal
    local lifecycle takes precedence over historical progress. Extra source fields
    are never copied, serialized, logged or used to infer execution outcomes.
    """
    if type(record) is not dict:
        raise ClientTaskProjectionError()
    task_id = record.get("id")
    title = record.get("title")
    revision = record.get("revision")
    lifecycle = record.get("state")
    progress = record.get("work_status")
    if type(task_id) is not str or len(task_id) != 36:
        raise ClientTaskProjectionError()
    try:
        identifier = UUID(task_id)
    except ValueError:
        raise ClientTaskProjectionError() from None
    if identifier.version != 4 or str(identifier) != task_id:
        raise ClientTaskProjectionError()
    if (
        type(title) is not str
        or not 1 <= len(title) <= 240
        or not title.strip()
        or any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in title)
        or type(revision) is not int
        or not 1 <= revision <= 2**63 - 1
        or type(lifecycle) is not str
        or lifecycle not in {"captured", "done", "cancelled"}
        or type(progress) is not str
        or progress not in {"ready", "in_progress", "waiting", "blocked"}
    ):
        raise ClientTaskProjectionError()
    wait_reason = None
    if lifecycle == "done":
        state = "completed"
    elif lifecycle == "cancelled":
        state = "cancelled"
    elif progress == "ready":
        state = "queued"
    elif progress == "in_progress":
        state = "running"
    else:
        state = "waiting"
        wait_reason = "local_" + progress
    return {
        "id": task_id,
        "title": title,
        "revision": str(revision),
        "state": state,
        "wait_reason": wait_reason,
    }
