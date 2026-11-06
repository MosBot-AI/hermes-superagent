"""Bounded, non-personal diagnostics. This is not an authorization service."""

import os

from . import HERMES_BASELINE, PLUGIN_ID, VERSION
from .enforcement import build_enforcement_summary


def build_status(*, mode: str = "read_only", local_conversation: bool = False) -> dict[str, object]:
    """Return a fresh result without consulting credentials, files, or providers."""
    if mode not in ("read_only", "local_tasks"):
        raise ValueError("unsupported mode")
    if type(local_conversation) is not bool or (local_conversation and mode != "local_tasks"):
        raise ValueError("invalid local conversation configuration")
    platform_supported = os.name == "posix" and hasattr(os, "O_NOFOLLOW")
    local_tasks = mode == "local_tasks" and platform_supported
    return {
        "schema_version": "personal.status.v1",
        "status": "ok",
        "plugin": PLUGIN_ID,
        "version": VERSION,
        "mode": mode,
        "stage": "local_task_inbox" if local_tasks else "foundation",
        "compatibility": {
            "target_hermes_commit": HERMES_BASELINE,
            "runtime_commit_verified": False,
            "note": "The baseline is a test target, not a probe of the running host.",
        },
        "capabilities": {
            "diagnostics": True,
            "personal_data_storage": local_tasks,
            "local_task_inbox_cli": local_tasks,
            "local_task_agenda_cli": local_tasks,
            "identity_binding": False,
            "action_authorization": False,
            "reminders": False,
            "external_delivery": False,
            "worker_model_routing": False,
        },
        "safety": {
            "plugin_write_tools_registered": False,
            "local_cli_writes_enabled": local_tasks,
            "agent_personal_data_reads_enabled": False,
            "host_write_paths_enforced": False,
            "release_gate": "blocked",
            "reason": "Identity, authorization and write-path coverage are not implemented.",
            "scope": "This plugin does not disable or secure other Hermes tools.",
        },
        "local_task_inbox": {
            "available": platform_supported,
            "configured": mode == "local_tasks",
            "enabled": local_tasks,
            "platform_supported": platform_supported,
            "surface": "trusted_local_cli_only",
            "scope": "Plugin-owned tasks only; not native Kanban or a verified owner boundary.",
            "platform_gate": "POSIX private-file checks; Windows storage is not supported yet.",
        },
        "local_conversation": {
            "implemented": True,
            "configured": local_conversation,
            "enabled": local_conversation and local_tasks,
            "surface": "trusted_native_local_session",
            "model_tools_enabled": False,
            "new_remote_entry_enabled": False,
            "scope": (
                "Explicit commands under host session authorization; all admitted controllers "
                "share access. LOCAL is not physical-locality or independent owner proof."
            ),
        },
        "read_authorization": {
            "core_implemented": True,
            "production_context_issuer": False,
            "protected_reads_enabled": False,
            "missing_contracts": [
                "verified_receiving_transport",
                "owner_binding",
                "current_read_policy",
            ],
        },
        "enrollment_policy": {
            "persistence_core_implemented": True,
            "production_adapter_enabled": False,
            "activation_supported": False,
            "grant_issuance_supported": False,
            "scope": (
                "Unwired pending/revoked metadata only; profiles are not authenticated owners."
            ),
        },
        "read_admission": {
            "coordinator_implemented": True,
            "production_adapters_available": False,
            "default_enabled": False,
            "durable_read_audit_implemented": False,
            "scope": (
                "Internal fenced snapshot coordination only; no live authority or task reader."
            ),
        },
        "voice": {
            "synthetic_self_test_implemented": True,
            "live_voice_enabled": False,
            "microphone_enabled": False,
            "provider_connections_enabled": False,
            "scope": "Offline synthetic contract checks only; not working speech or calls.",
        },
        "automation_blueprints": {
            "planning_template_implemented": True,
            "default_enabled": False,
            "creates_jobs_on_load": False,
            "manages_existing_jobs": False,
            "scope": "Opt-in native template only; actual jobs use Hermes scheduling and policies.",
        },
        "write_path_inventory": build_enforcement_summary(),
    }
