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
        "synthetic_contract",
        "Callback failures block, but an escaping dispatcher failure can continue execution. "
        "Operation-level authorization is not integrated.",
        ("hook_callback_failure", "hook_timeout", "outer_dispatcher_failure"),
    ),
    WritePath(
        "direct_registry",
        "synthetic_contract",
        "Direct registry dispatch does not invoke pre_tool_call hooks. "
        "Handlers must enforce their own operation-level authorization.",
        ("direct_registry_without_hooks",),
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
        "not_tested",
        "No shell/backend containment or operation-level authorization contract yet. "
        "A tool hook is not an OS sandbox.",
    ),
    WritePath(
        "browser",
        "not_tested",
        "No browser write-path, session identity, or external outcome contract yet.",
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
        "connector_batch",
        "not_tested",
        "No per-item authorization, partial-outcome, or retry contract yet.",
    ),
    WritePath(
        "short_worker",
        "not_tested",
        "No per-action grant, revocation, or tool-surface coverage for delegated workers yet.",
    ),
    WritePath(
        "managed_worker",
        "synthetic_contract",
        "Ordinary workers retain frozen config; troubleshooting safe workers skip hooks. "
        "Current persistent policy checks are not integrated.",
        ("managed_worker_frozen_config", "safe_worker_hook_suppression"),
    ),
    WritePath(
        "scheduled_job",
        "not_tested",
        "No scheduled-job authorization, cancellation, delivery, or reconciliation contract yet.",
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
