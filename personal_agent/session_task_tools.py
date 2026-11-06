"""Opt-in tools for an explicitly activated, trusted native local session.

Pinned in-process host routing, not a human identity issuer. Schemas are profile
wide; admission is checked inside every handler. All model activity in an active
session shares access. Managed workers/hosted plugins do not share activations.
"""

import json
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .conversation_tasks import _supported_origin
from .task_cli import current_profile_home, open_task_store
from .task_tool_contract import normalize_task_tool_request
from .tasks import TaskError

ACCESS_SECONDS = 1800
MAX_ACTIVE_SESSIONS = 64
LOCAL_CLIENTS = frozenset({"cli", "tui", "desktop"})
HELP = (
    "enable-read: allow bounded task data into this session's configured model for 30 minutes. "
    "enable-write: additionally allow local task changes for 30 minutes. "
    "disable: revoke future tool admission; already admitted work may finish. "
    "status: inspect activation without task data. All model activity and admitted controllers "
    "in this session share access. No external actions. In-process native CLI/TUI/Desktop only; "
    "managed workers and isolated plugin hosts are unsupported. Do not disable isolation."
)


def _bound_key() -> str:
    from gateway.session_context import bound_session_key  # ty: ignore[unresolved-import]

    return bound_session_key()


@contextmanager
def native_tool_turn(bound_home: Path, session_id: str, task_id: str) -> Generator[str]:
    """Pinned host adapter: require a live contextual turn, never env-only admission."""
    from agent.delegation_context import (  # ty: ignore[unresolved-import]
        is_delegated_child_process_context,
    )
    from agent.relay_runtime import active_turn  # ty: ignore[unresolved-import]
    from gateway.session_context import get_session_env  # ty: ignore[unresolved-import]

    if type(session_id) is not str or not session_id or type(task_id) is not str or not task_id:
        raise TaskError("no_active_local_turn")
    turn = active_turn(session_id)
    if turn is None:
        raise TaskError("no_active_local_turn")
    # Finalization uses this same lock in the pinned host. No liveness claim is
    # made about a string copied from tool arguments or the process environment.
    with turn.finalize_lock:
        if (
            active_turn(session_id) is not turn
            or turn.task_id != task_id
            or turn.lease.session_id != session_id
            or turn.lease.profile_key != str(bound_home)
            or turn.lease.platform not in LOCAL_CLIENTS
            or turn.lease.parent_session_id
            or is_delegated_child_process_context()
            or get_session_env("HERMES_CRON_SESSION", "") not in ("", "0")
        ):
            raise TaskError("no_active_local_turn")
        key = _bound_key()
        if type(key) is not str or not key:
            raise TaskError("no_active_local_turn")
        yield key


class SessionTaskTools:
    """Process-local activation; unload closes even retained command/tool callbacks."""

    reply_schema = "personal.session-task-tools.v1"
    help_text = HELP
    write_tool_name = "personal_tasks_write"
    unavailable_code = "local_model_tools_unavailable"
    disclosure = "Task results enter this session's configured model context."

    def __init__(self, *, bound_home: Path, read_config: Callable[[str, object], Any]):
        self.bound_home = bound_home
        self.read_config = read_config
        self._lock = threading.RLock()
        self._activations: dict[tuple[str, str], tuple[str, float]] = {}
        self._closed = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._activations.clear()

    def _configured(self) -> None:
        if self._closed:
            raise TaskError("local_model_tools_unloaded")
        if not self.bound_home.is_dir() or current_profile_home() != self.bound_home:
            raise TaskError("profile_context_changed")
        mode = self.read_config("mode", "read_only")
        conversation = self.read_config("local_conversation", False)
        models = self.read_config("local_model_tools", False)
        if mode not in ("read_only", "local_tasks") or any(
            type(value) is not bool for value in (conversation, models)
        ):
            self._activations.clear()
            raise TaskError("invalid_configuration")
        if mode != "local_tasks" or not conversation or not models:
            self._activations.clear()
            raise TaskError("local_model_tools_disabled")

    def _prune(self) -> None:
        now = time.monotonic()
        self._activations = {
            key: value for key, value in self._activations.items() if value[1] > now
        }

    @classmethod
    def _reply(cls, *, data=None, error=None, request_id=None, replayed=False) -> str:
        return json.dumps(
            {
                "schema_version": cls.reply_schema,
                "scope": "activated_trusted_local_session",
                "status": "error" if error else "ok",
                "data": data,
                "error": {"code": error.code, "retryable": error.retryable} if error else None,
                "request_id": request_id,
                "replayed": replayed,
            },
            ensure_ascii=True,
            sort_keys=True,
        )

    def command(
        self, raw_args: str, *, platform="", source=None, session_id="", session_key=""
    ) -> str:
        try:
            # Unlike task CLI compatibility, activation requires actual LOCAL
            # callback context and its no-environment-fallback route binding.
            if (
                platform != "local"
                or not _supported_origin(platform, source, session_id, session_key)
                or _bound_key() != session_key
            ):
                raise TaskError("unsupported_origin")
            with self._lock:
                self._configured()
                if type(raw_args) is not str or len(raw_args) > 128:
                    raise TaskError("invalid_request")
                verb = raw_args.strip()
                if verb in ("", "help"):
                    return self._reply(data={"help": self.help_text})
                if verb not in ("enable-read", "enable-write", "disable", "status"):
                    raise TaskError("invalid_request")
                self._prune()
                key = (session_id, session_key)
                if verb == "disable":
                    self._activations.pop(key, None)
                elif verb.startswith("enable-"):
                    if (
                        key not in self._activations
                        and len(self._activations) >= MAX_ACTIVE_SESSIONS
                    ):
                        raise TaskError("activation_capacity_reached")
                    self._activations[key] = (
                        "write" if verb == "enable-write" else "read",
                        time.monotonic() + ACCESS_SECONDS,
                    )
                entry = self._activations.get(key)
                return self._reply(
                    data={
                        "access": entry[0] if entry else "disabled",
                        "expires_in_seconds": max(0, int(entry[1] - time.monotonic()))
                        if entry
                        else 0,
                        "model_data_disclosure": self.disclosure,
                        "trust_boundary": (
                            "All model activity in this activated session; not human-origin proof."
                        ),
                    }
                )
        except Exception as error:
            return self._reply(
                error=error if isinstance(error, TaskError) else TaskError(self.unavailable_code)
            )

    def _normalize(self, tool_name: str, arguments: dict) -> tuple[str, dict]:
        return normalize_task_tool_request(tool_name, arguments)

    def _execute(self, operation: str, payload: dict, session_id: str) -> dict:
        with open_task_store(self.bound_home) as store:
            return store.run(operation, payload)

    def run(self, tool_name: str, arguments: dict, *, session_id="", task_id="", **_context) -> str:
        request_id = None
        try:
            with native_tool_turn(self.bound_home, session_id, task_id) as session_key:
                # Lock order: turn finalization, then activation. Revocation
                # waits for admitted bounded storage work, never cancels a commit.
                with self._lock:
                    self._configured()
                    self._prune()
                    entry = self._activations.get((session_id, session_key))
                    if entry is None:
                        raise TaskError("session_tools_not_activated")
                    if tool_name == self.write_tool_name and entry[0] != "write":
                        raise TaskError("session_write_not_activated")
                    operation, payload = self._normalize(tool_name, arguments)
                    request_id = payload.get("request_id")
                    result = self._execute(operation, payload, session_id)
                    return self._reply(**result, request_id=request_id)
        except Exception as error:
            return self._reply(
                error=error if isinstance(error, TaskError) else TaskError(self.unavailable_code),
                request_id=request_id,
            )
