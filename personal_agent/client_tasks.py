"""Shared task projections for trusted code holding a selected local store."""

import base64
import hmac
import secrets
import unicodedata
from typing import Literal, TypedDict
from uuid import UUID

from .client_api import MAX_TASK_PAGE_SIZE, SCHEMA_VERSION
from .tasks import TaskError, TaskStore


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


class ClientTaskPageData(TypedDict):
    items: list[ClientTask]
    next_cursor: str | None
    consistency: Literal["live"]


class ClientTaskPage(TypedDict):
    schema_version: str
    data: ClientTaskPageData


class ClientTaskPageError(ValueError):
    """Stable, redacted failure at the shared page boundary."""

    def __init__(
        self,
        code: Literal["invalid_request", "cursor_invalid", "internal_unavailable"],
        *,
        retryable: bool = False,
    ) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(f"Shared task page failed ({code}).")


class SharedTaskPager:
    """Bind continuations to one already-admitted store and caller scope.

    The trusted caller must admit every read of the selected collection. Use one
    pager per scope and discard it when that scope, admission or store changes.
    """

    def __init__(self, store: TaskStore) -> None:
        self._store = store
        self._cursor_key = secrets.token_bytes(32)

    def _encode_cursor(self, task_id: str) -> str:
        anchor = task_id.encode("ascii")
        signature = hmac.digest(self._cursor_key, anchor, "sha256")
        return base64.urlsafe_b64encode(anchor + signature).decode("ascii").rstrip("=")

    def _decode_cursor(self, cursor: str) -> str:
        # An ASCII UUID plus a SHA-256 tag encodes to 91 unpadded characters.
        if len(cursor) != 91 or not cursor.isascii():
            raise ClientTaskPageError("cursor_invalid")
        try:
            raw = base64.b64decode(cursor + "=", altchars=b"-_", validate=True)
            anchor = raw[:36].decode("ascii")
        except ValueError:
            raise ClientTaskPageError("cursor_invalid") from None
        if not hmac.compare_digest(self._encode_cursor(anchor), cursor):
            raise ClientTaskPageError("cursor_invalid")
        return anchor

    def page(self, *, limit: int = 32, cursor: str | None = None) -> ClientTaskPage:
        if type(limit) is not int or not 1 <= limit <= MAX_TASK_PAGE_SIZE:
            raise ClientTaskPageError("invalid_request")
        if cursor is not None and (type(cursor) is not str or not 1 <= len(cursor) <= 2048):
            raise ClientTaskPageError("invalid_request")
        after = None if cursor is None else self._decode_cursor(cursor)
        try:
            rows = self._store.read_shared_task_fields(after, limit)
            items = [project_local_task(row) for row in rows[:limit]]
        except TaskError as error:
            raise ClientTaskPageError("internal_unavailable", retryable=error.retryable) from None
        except ClientTaskProjectionError:
            raise ClientTaskPageError("internal_unavailable") from None
        next_cursor = self._encode_cursor(items[-1]["id"]) if len(rows) > limit else None
        return {
            "schema_version": SCHEMA_VERSION,
            "data": {"items": items, "next_cursor": next_cursor, "consistency": "live"},
        }


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
