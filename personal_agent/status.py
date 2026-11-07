"""Bounded, non-personal diagnostics. This is not an authorization service."""

import os

from . import HERMES_BASELINE, PLUGIN_ID, VERSION
from .enforcement import build_enforcement_summary


def build_status(
    *,
    mode: str = "read_only",
    local_conversation: bool = False,
    local_model_tools: bool = False,
    local_memory: bool = False,
    memory_model_tools: bool = False,
) -> dict[str, object]:
    """Return a fresh result without consulting credentials, files, or providers."""
    if mode not in ("read_only", "local_tasks"):
        raise ValueError("unsupported mode")
    if type(local_conversation) is not bool or (local_conversation and mode != "local_tasks"):
        raise ValueError("invalid local conversation configuration")
    if type(local_model_tools) is not bool or (local_model_tools and not local_conversation):
        raise ValueError("invalid local model tools configuration")
    if type(local_memory) is not bool or (local_memory and not local_conversation):
        raise ValueError("invalid local memory configuration")
    if type(memory_model_tools) is not bool or (memory_model_tools and not local_memory):
        raise ValueError("invalid memory model tools configuration")
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
            "explicit_local_memory": local_memory and local_tasks,
        },
        "safety": {
            "plugin_write_tools_registered": local_model_tools or memory_model_tools,
            "local_cli_writes_enabled": local_tasks,
            "agent_personal_data_reads_enabled": (local_model_tools or memory_model_tools)
            and local_tasks,
            "agent_personal_data_reads_require_session_activation": True,
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
            "model_tools_configured": local_model_tools,
            "model_tools_require_session_activation": True,
            "new_remote_entry_enabled": False,
            "scope": (
                "Explicit commands under host session authorization; all admitted controllers "
                "share access. LOCAL is not physical-locality or independent owner proof."
            ),
        },
        "local_model_tools": {
            "implemented": True,
            "configured": local_model_tools,
            "schemas_registered_when_configured": True,
            "session_activation_required": True,
            "session_activation_observed": False,
            "supported_runtime": "native_in_process_only",
            "activation_lifetime_seconds": 1800,
            "scope": (
                "All model activity in an explicitly activated trusted local session; "
                "not verified human-origin instructions or remote owner identity."
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
        "local_memory": {
            "explicit_records_implemented": True,
            "bounded_literal_recall_implemented": True,
            "configured": local_memory,
            "enabled": local_memory and local_tasks,
            "surface": "trusted_native_local_command",
            "backend": "bundled_local_sqlite",
            "automatic_recall": False,
            "automatic_extraction": False,
            "native_provider_bridge": False,
            "third_party_adapter_loading": False,
            "markdown_projections": False,
            "model_tools_configured": memory_model_tools,
            "model_tools_require_separate_session_activation": True,
            "model_session_activation_observed": False,
            "model_tools_supported_runtime": "native_in_process_only",
            "scope": (
                "Explicit operator records, not identity, permission grants or fact verification. "
                "Current native providers are preserved. Model memory tools need separate "
                "configuration and per-session activation; model edits are not human proof."
            ),
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
