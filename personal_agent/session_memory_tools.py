"""Separate session activation for local memory, never inherited from task access."""

from .memory_backend import MemoryError, MemoryService
from .memory_storage import open_memory_backend
from .memory_tool_contract import normalize_memory_tool_request
from .session_task_tools import SessionTaskTools
from .task_cli import current_profile_home
from .tasks import TaskError


class SessionMemoryTools(SessionTaskTools):
    """Reuse the tested turn/activation mechanism with separate state and scope."""

    reply_schema = "personal.session-memory-tools.v1"
    write_tool_name = "personal_memory_write"
    unavailable_code = "memory_model_tools_unavailable"
    disclosure = "Memory content and source references enter this session's configured model."
    help_text = (
        "enable-read: let this session's configured model read local memory for 30 minutes. "
        "enable-write: additionally let it remember, correct and forget local records. "
        "disable: revoke future memory-tool admission; admitted work may finish. "
        "status: inspect activation without memory data. Memory and task activations are "
        "independent. All model activity and admitted controllers in this session share "
        "access, not proof of a fresh human instruction. Model edits are labeled "
        "activated_session_model, not verified operator statements or permissions. "
        "Memory results reach the configured model and normal host history; ordinary "
        "model costs may apply. Forget does not erase already returned text, host history "
        "or backups. No native provider replacement, automatic extraction or external action. "
        "In-process native CLI/TUI/Desktop only; do not disable isolation."
    )

    def _configured(self) -> None:
        if self._closed:
            raise TaskError("memory_model_tools_unloaded")
        if not self.bound_home.is_dir() or current_profile_home() != self.bound_home:
            raise TaskError("profile_context_changed")
        mode = self.read_config("mode", "read_only")
        conversation = self.read_config("local_conversation", False)
        memory = self.read_config("local_memory", False)
        models = self.read_config("memory_model_tools", False)
        if mode not in ("read_only", "local_tasks") or any(
            type(value) is not bool for value in (conversation, memory, models)
        ):
            self._activations.clear()
            raise TaskError("invalid_configuration")
        if mode != "local_tasks" or not conversation or not memory or not models:
            self._activations.clear()
            raise TaskError("memory_model_tools_disabled")

    def _normalize(self, tool_name: str, arguments: dict) -> tuple[str, dict]:
        try:
            return normalize_memory_tool_request(tool_name, arguments)
        except MemoryError as error:
            raise TaskError(error.code, retryable=error.retryable) from None

    def _execute(self, operation: str, payload: dict, session_id: str) -> dict:
        try:
            with open_memory_backend(
                self.bound_home, session_id, source_kind="activated_session_model"
            ) as backend:
                return MemoryService(backend).execute(operation, payload)
        except MemoryError as error:
            raise TaskError(error.code, retryable=error.retryable) from None
