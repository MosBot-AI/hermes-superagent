"""Read-only release evidence. This inventory is not an action authorizer.

Pinned host boundary probes use synthetic effects. They establish a few failure
behaviors, not coverage of every real write tool. No entry in this development
inventory enables writes.
"""

from dataclasses import asdict, dataclass

from . import HERMES_BASELINE


@dataclass(frozen=True)
class WritePath:
    path_id: str
    evidence: str
    blocker: str
    contract_ids: tuple[str, ...] = ()


_WRITE_PATHS = (
    WritePath(
        "native_dispatch",
        "pinned_host_boundary_contract",
        "Callback failures block, but an escaping dispatcher failure can continue execution. "
        "Actual default package exposure and negative dispatch are tested; this is not "
        "production operation-level authority or host-wide enforcement.",
        (
            "hook_callback_failure",
            "hook_timeout",
            "outer_dispatcher_failure",
            "production_default_exposure",
        ),
    ),
    WritePath(
        "direct_registry",
        "pinned_host_boundary_contract",
        "Direct registry dispatch does not invoke pre_tool_call hooks. "
        "Actual package tools are absent by default; opted-in local handlers refuse "
        "without a live activated turn. This is not verified-owner write authority.",
        (
            "direct_registry_without_hooks",
            "production_default_exposure",
            "production_worker_unsupported",
        ),
    ),
    WritePath(
        "mcp",
        "pinned_host_boundary_contract",
        "Real stdio dispatch tests plugin veto, direct-registry bypass and native trust denial. "
        "A dishonest readOnlyHint still permits a synthetic effect. Production per-action "
        "authorization, credential scope and receipts remain unverified.",
        ("mcp_plugin_veto_and_registry_bypass", "mcp_native_trust_gate", "mcp_dishonest_read_hint"),
    ),
    WritePath(
        "shell",
        "pinned_host_boundary_contract",
        "Native deny/workdir guards and public versus internal force paths are exercised "
        "against an inert backend. Direct registry skips plugin admission. No actual shell, "
        "backend containment or operation-level authorization contract is established.",
        (
            "shell_native_deny_and_force_surface",
            "shell_internal_force_boundary",
            "shell_plugin_registry_boundary",
        ),
    ),
    WritePath(
        "browser",
        "pinned_host_boundary_contract",
        "Native metadata-URL literal admission and plugin/direct-helper boundaries are tested "
        "against an inert browser endpoint. Dynamic URLs exceed literal pre-scan coverage. "
        "No real navigation, session identity, write outcome or containment is established.",
        (
            "browser_metadata_literal_floor",
            "browser_plugin_helper_boundary",
            "browser_dynamic_url_prescan_limit",
        ),
    ),
    WritePath(
        "execute_code_rpc",
        "pinned_host_boundary_contract",
        "Native RPC token/allow-list/budget and default nested dispatch are exercised over "
        "an in-memory wire. Persistent client response loss can replay an effect. No sandbox, "
        "remote poll transport or session-kernel authority-rebinding contract is claimed.",
        (
            "rpc_token_allowlist_budget",
            "rpc_nested_hook_failure",
            "rpc_outer_dispatcher_failure",
            "rpc_duplicate_request",
            "rpc_persistent_client_response_loss",
        ),
    ),
    WritePath(
        "local_tool_batch",
        "pinned_host_boundary_contract",
        "Real local tool_call expansion and agent loops preserve per-item veto and pairing. "
        "A new model-emitted retry can repeat a completed synthetic effect; in-memory "
        "fixture policy rechecks do not establish durable revocation or effect idempotency.",
        ("local_batch_item_veto", "local_batch_uncertain_retry", "local_batch_policy_recheck"),
    ),
    WritePath(
        "connector_batch",
        "pinned_host_boundary_contract",
        "Native per-item dispatch and veto retain indexed partial results against an offline "
        "gateway client. Native concurrent wrappers recheck fixture policy per item; timeout "
        "can precede late effects and an explicit outer retry can repeat them. "
        "Production grants, credentials, transport retry and server deduplication "
        "remain unverified.",
        (
            "connector_batch_item_veto_partial_retry",
            "concurrent_connector_item_veto",
            "concurrent_connector_policy_recheck",
            "concurrent_connector_timeout_retry",
        ),
    ),
    WritePath(
        "short_worker",
        "pinned_host_boundary_contract",
        "Native child construction narrows requested toolsets to the parent's selection; "
        "its real loop retains tested local-batch gates. No delegate_task scheduler, "
        "background lifecycle, production per-action grants or persistent revocation is verified. "
        "The actual package's unsupported text-worker opt-in does not fall back to generic launch.",
        ("delegated_child_toolset_and_batch_admission", "production_worker_unsupported"),
    ),
    WritePath(
        "managed_worker",
        "pinned_host_boundary_contract",
        "Fresh native worker binding retains frozen config while a synthetic read handler "
        "rechecks current SQLite policy and revocation on both dispatch routes. "
        "Actual package frozen-config exposure and safe-bootstrap omission are also tested. "
        "No production authority, write grant or complete managed-worker lifecycle is integrated.",
        (
            "managed_worker_frozen_config",
            "safe_worker_hook_suppression",
            "worker_current_policy_recheck",
            "worker_missing_authority",
            "worker_transaction_failure",
            "worker_safe_capability_absence",
            "worker_admission_before_revoke",
            "worker_revoke_before_admission",
            "worker_one_shot_cross_path",
            "production_frozen_configuration",
            "production_safe_bootstrap",
        ),
    ),
    WritePath(
        "scheduled_job",
        "pinned_host_boundary_contract",
        "Actual package blueprint absence and explicit opt-in are tested through native "
        "consumers at inert creation endpoints. Opt-in ordinary jobs are not controlled "
        "actions; no authorization, cancellation, delivery or reconciliation guarantee is added.",
        ("production_blueprint_consumers",),
    ),
)


def build_enforcement_inventory() -> dict[str, object]:
    """Return an independent JSON-compatible snapshot with no live host probing."""
    paths = []
    for item in _WRITE_PATHS:
        row = asdict(item)
        row["contract_ids"] = list(item.contract_ids)
        row["controlled_writes_enabled"] = False
        row["release_gate"] = "blocked"
        paths.append(row)
    return {
        "schema_version": "personal.enforcement.v1",
        "baseline_hermes_commit": HERMES_BASELINE,
        "scope": "personal-agent controlled-write release; not a host-wide permission policy",
        "runtime_enforcement_verified": False,
        "is_action_authorization": False,
        "release_gate": "blocked",
        "paths": paths,
        "other_observations": {
            "tool_execution_middleware": "A callback failure can continue downstream execution.",
            "timeout": "A timed-out callback may still run; callbacks must not perform effects.",
        },
        "unlisted_paths": "blocked and unverified",
    }


def build_enforcement_summary() -> dict[str, object]:
    """Keep model-visible diagnostics bounded; full evidence is available in the CLI."""
    return {
        "catalog_version": "personal.enforcement.v1",
        "known_write_paths": len(_WRITE_PATHS),
        "controlled_write_paths_enabled": 0,
        "runtime_enforcement_verified": False,
        "release_gate": "blocked",
        "unlisted_paths": "blocked and unverified",
    }
