"""Optional real Hermes MemoryProvider. Never imported by standalone registration."""

import os

from agent.memory_provider import (  # ty: ignore[unresolved-import]
    MemoryProvider,
    RecallStatus,
    is_trivial_prompt,
)

from .memory_backend import MemoryError
from .memory_lifecycle import PROVIDER_NAME, MemoryRecallLifecycle
from .task_cli import current_profile_home


def read_native_config(home):
    from agent.safe_worker_policy import worker_config_snapshot  # ty: ignore[unresolved-import]
    from hermes_cli import managed_scope  # ty: ignore[unresolved-import]
    from hermes_cli.config_backend import (  # ty: ignore[unresolved-import]
        FileBackend,
        get_config_backend,
    )

    if (
        worker_config_snapshot() is not None
        or os.environ.get("HERMES_PLUGIN_HOST_PROCESS") == "1"
        or managed_scope.get_managed_dir() is not None
    ):
        raise MemoryError("native_recall_runtime_unsupported")
    if current_profile_home() != home:
        raise MemoryError("profile_context_changed")
    try:
        backend = get_config_backend()
    except SystemExit:
        raise MemoryError("native_recall_runtime_unsupported") from None
    if type(backend) is not FileBackend:
        raise MemoryError("native_recall_runtime_unsupported")
    config = backend.read_user_doc(home)
    # Raw user opt-in cannot override a managed policy layer. This narrow
    # provider refuses any host-detected scope, including empty/malformed policy,
    # rather than treating the host's fail-open policy parser as authorization.
    if managed_scope.get_managed_dir() is not None:
        raise MemoryError("native_recall_runtime_unsupported")
    if current_profile_home() != home:
        raise MemoryError("profile_context_changed")
    return config


class PersonalRecordsProvider(MemoryProvider):
    """Fresh read-only recall; API v1 must never satisfy required native checkpoints."""

    pre_compress_checkpoint_api_version = 1

    def __init__(self):
        self._lifecycle = MemoryRecallLifecycle(read_native_config)

    @property
    def name(self):
        return PROVIDER_NAME

    def is_available(self):
        return self._lifecycle.available()

    def unavailable_reason(self):
        return (
            "Explicit personal-records recall opt-in and trusted local "
            "in-process configuration without a managed policy scope required."
        )

    def initialize(self, session_id, **kwargs):
        self._lifecycle.initialize(
            session_id,
            hermes_home=kwargs.get("hermes_home"),
            platform=kwargs.get("platform"),
            agent_context=kwargs.get("agent_context"),
        )

    def get_tool_schemas(self):
        return []

    def prefetch(self, query, *, session_id=""):
        # Pass empty input through the lifecycle to clear any prior recall count.
        return self._lifecycle.prefetch(
            "" if type(query) is not str or is_trivial_prompt(query) else query,
            session_id=session_id,
        )

    def recall_status(self):
        count = self._lifecycle.recall_count()
        return RecallStatus(provider_label="Personal records", count=count) if count else None

    def on_session_switch(self, new_session_id, **kwargs):
        self._lifecycle.switch_session(new_session_id)

    def shutdown(self):
        self._lifecycle.shutdown()


def register(ctx):
    """Native provider loader only. Standalone plugin registration is unchanged."""
    ctx.register_memory_provider(PersonalRecordsProvider())
