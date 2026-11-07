"""Bounded, non-personal diagnostics. This is not an authorization service."""

import os
import re

from . import HERMES_BASELINE, PLUGIN_ID, VERSION
from .enforcement import build_enforcement_summary


def validate_kanban_configuration(mode, conversation, enabled, board):
    """Validate declarations only; never inspect the native host or its storage."""
    if type(enabled) is not bool or type(board) is not str:
        raise ValueError("invalid kanban handoff configuration")
    if enabled and (
        mode != "local_tasks"
        or not conversation
        or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", board) is None
    ):
        raise ValueError(
            "kanban_handoff requires local_tasks, local_conversation and an explicit board"
        )


def build_status(
    *,
    mode: str = "read_only",
    local_conversation: bool = False,
    local_model_tools: bool = False,
    local_memory: bool = False,
    memory_model_tools: bool = False,
    memory_candidates: bool = False,
    kanban_handoff: bool = False,
    kanban_handoff_board: str = "",
    plan_worker: bool = False,
    plan_worker_registered: bool = False,
    plan_worker_host: str = "not_checked",
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
    if type(memory_candidates) is not bool or (memory_candidates and not memory_model_tools):
        raise ValueError("invalid memory candidates configuration")
    validate_kanban_configuration(mode, local_conversation, kanban_handoff, kanban_handoff_board)
    if type(plan_worker) is not bool or (plan_worker and not local_model_tools):
        raise ValueError("invalid plan worker configuration")
    if type(plan_worker_registered) is not bool or plan_worker_host not in (
        "not_checked",
        "unsupported_host",
        "consent_required",
        "available",
        "host_check_failed",
    ):
        raise ValueError("invalid plan worker host observation")
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
            "atomic_project_plan_capture": local_tasks,
            "atomic_project_plan_dependencies": local_tasks,
            "local_project_task_dependencies": local_tasks,
            "dependency_ready_queue": local_tasks,
            "saved_native_attention_review": local_tasks,
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
            "dependency_max_per_task": 20,
            "plan_dependency_positions": "explicit_one_based_batch_only",
            "plan_dependencies_atomic_with_capture": True,
            "dependency_requires_exact_named_project": True,
            "dependency_satisfaction": "only_done_prerequisites",
            "dependency_gates_start_and_complete": True,
            "dependency_revision_scope": "owned_fields_and_edges_not_prerequisite_state",
            "ready_queue_order": "oldest_capture_sequence_not_priority",
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
        "native_attention_review": {
            "implemented": True,
            "enabled": local_tasks,
            "source": "saved_local_task_observations_only",
            "native_access": False,
            "automatic": False,
            "changes_completion": False,
            "live_verified": False,
            "model_read_requires_existing_session_activation": True,
        },
        "plan_worker": {
            "implemented": True,
            "configured": plan_worker,
            "registered": plan_worker_registered,
            "host": plan_worker_host,
            "enabled": plan_worker
            and plan_worker_registered
            and plan_worker_host == "available"
            and local_tasks,
            "reload_required": plan_worker
            and not plan_worker_registered
            and plan_worker_host == "available",
            "task_grant_required": True,
            "route_verified": False,
            "provider": "opencode-go",
            "model": "deepseek-v4.1-flash",
            "changes_task_state": False,
            "tools_allowed": False,
            "automatic": False,
            "installed_or_live_verified": False,
            "scope": (
                "One explicitly granted planning draft; requires adopted text-worker host contract."
            ),
        },
        "kanban_handoff": {
            "configured": kanban_handoff,
            "enabled": kanban_handoff and local_conversation and local_tasks,
            "command_registered": local_conversation,
            "native_runtime_verified": False,
            "native_schema_verified": False,
            "operation_checks_required": True,
            "dispatch_enabled": False,
            "native_progress_sync_implemented": True,
            "native_progress_sync_enabled": kanban_handoff and local_conversation and local_tasks,
            "native_progress_sync_surface": "explicit_native_local_command_only",
            "native_progress_sync_advisory_only": True,
            "native_progress_sync_automatic": False,
            "native_progress_sync_changes_completion": False,
            "native_progress_sync_requires_anchored_identity": True,
            "native_progress_sync_live_verified": False,
            "surface": "explicit_native_local_command",
            "scope": "Parked shared-board card only; not worker dispatch or task completion.",
        },
        "local_model_tools": {
            "implemented": True,
            "configured": local_model_tools,
            "schemas_registered_when_configured": True,
            "session_activation_required": True,
            "session_activation_observed": False,
            "supported_runtime": "native_in_process_only",
            "activation_lifetime_seconds": 1800,
            "task_focus_implemented": True,
            "task_focus_requires_explicit_selection": True,
            "task_focus_max_context_chars": 12000,
            "task_focus_persists_across_restart": False,
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
            "metadata_change_feed_implemented": True,
            "durable_consumer_cursors_implemented": True,
            "native_compression_checkpoint": False,
            "configured": local_memory,
            "enabled": local_memory and local_tasks,
            "surface": "trusted_native_local_command",
            "backend": "bundled_local_sqlite",
            "automatic_recall": None if memory_model_tools else False,
            "session_recall_implemented": True,
            "session_recall_requires_explicit_command": True,
            "session_recall_activation_observed": False,
            "session_recall_max_context_chars": 6000,
            "session_recall_max_records": 6,
            "session_recall_status_command": "/personal-memory-tools status",
            "automatic_extraction": False,
            "candidate_workflow_implemented": True,
            "candidate_capture_configured": memory_candidates,
            "candidate_capture_requires_session_selection": True,
            "candidate_capture_activation_observed": False,
            "candidate_acceptance_requires_native_review": True,
            "candidate_pending_expiry_days": 7,
            "candidate_expiry_cleanup": (
                "lazy_on_successful_candidate_operation_or_explicit_purge_not_background"
            ),
            "candidate_metadata_capacity": 1000,
            "native_provider_bridge": False,
            "native_provider_bridge_scope": "not_registered_by_standalone_plugin",
            "optional_native_provider": "personal-records",
            "native_provider_activation_inspected": False,
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
        "routing": {
            "offline_fixture_evaluator_implemented": True,
            "saved_config_inspection_cli_implemented": True,
            "effective_session_observed": False,
            "shadow_ready": False,
            "automatic_routing_ready": False,
            "plugin_live_routing_enabled": False,
            "scope": "Saved local declarations and synthetic fixtures only; no routing authority.",
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
