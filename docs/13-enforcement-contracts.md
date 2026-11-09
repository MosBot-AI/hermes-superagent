# 13. Enforcement Contracts and Write-Path Inventory

English | [简体中文](13-enforcement-contracts-zh.md)

This page records an earlier E0 slice. See [16](16-local-task-inbox.md) for the newer opt-in local task inbox; it does not enable the native/external controlled-write paths described here.

This follow-on P0 slice advances E0.4 without enabling any controlled write capability. It adds reproducible failure-boundary tests and a machine-readable release inventory. E0.4, E0/M0, and E1 authorization remain incomplete.

## 1. What the implementation does

`personal_agent/enforcement.py` returns a fresh JSON-compatible inventory. Every known write path has `controlled_writes_enabled: false` and `release_gate: blocked`; unlisted paths are also unverified and blocked for this project's controlled-write release. The status tool includes only a bounded summary. In the default in-process plugin mode, `hermes personal-agent coverage` prints the full inventory.

This is a **read-only release report**, not an action authorizer, a live host inspection, or a sandbox. It does not disable another Hermes tool, intercept a direct API call, or turn an operator's existing tool configuration into a controlled environment. The baseline commit is evidence about the tested source, not a claim that the current host runs that commit. The pinned host skips plugin CLI registration in host-isolation mode.

## 2. Observed behavior at the pinned baseline

The new tests load a real directory plugin through real discovery. Its only handler records calls in memory. No fake manager, context, manifest parser, registry, or config loader is used. Callback behavior is controlled by the test fixture; the outer dispatcher test explicitly injects one escaping dispatcher exception.

| Boundary | Observed result | Consequence |
|---|---|---|
| `pre_tool_call` explicit block | Synthetic handler is not reached | A normal veto works on this tested dispatch path |
| Registered callback raises `RuntimeError` or `SystemExit` | Block directive, in both inline and bounded modes | Callback failure is fail-closed, not equivalent to dispatcher failure |
| Callback timeout and suppressed retry | Both calls block; no handler call | The timed-out callback can remain alive; hooks must not perform side effects |
| Same call identity while callback is still running | Second delivery blocks before a timeout; the first completes once after release | Active-call suppression is distinct from timeout backoff |
| Execution middleware raises before `next_call` | Downstream handler still executes once | This failure is fail-open, not an authorization denial |
| Middleware raises after `next_call` or calls it twice | The tested chain does not replay the completed handler | Do not infer broader transport idempotency from this local result |
| Exception escapes the outer hook dispatcher | `model_tools` continues to the handler | A caught callback error and a dispatcher failure are different failure domains |
| Direct registry dispatch | No `pre_tool_call` hook or execution middleware | Low-level calls do not inherit the model-facing pipeline |
| Troubleshooting safe worker | Plugin discovery and hooks are suppressed | A missing plugin cannot protect writes or provide its own fallback diagnostics |
| Ordinary managed worker / config-only worker | Plugins and hooks remain active; config stays frozen | A later profile edit is not immediate revocation |

Worker probes run in fresh processes because the bootstrap policy is bound once before runtime imports. They verify that mutating a returned config or replacing the on-disk config does not change the frozen snapshot. Their environments use an explicit variable allowlist and temporary homes, with socket connections denied inside each child. Timed-out test hooks are released through Events and joined during teardown; the host itself does not promise to kill an abandoned callback.

The tests are [native enforcement contracts](../tests/contracts/test_enforcement_boundaries.py). The fixture is test-only and never installed as part of the plugin's runtime tool surface.

## 3. Controlled-write release inventory

| Path | Evidence in this slice | Release status |
|---|---|---|
| `native_dispatch` | Synthetic hook and outer-dispatch failure contracts | Blocked; operation-level authorization is not integrated |
| `direct_registry` | Synthetic bypass-of-hooks contract | Blocked; handlers need their own operation-level checks |
| `mcp` | No end-to-end raw MCP write contract | Blocked |
| `shell` | No backend containment or operation-level write contract | Blocked |
| `browser` | No authenticated write/outcome contract | Blocked |
| `execute_code_rpc` | No end-to-end nested-call authority contract | Blocked |
| `connector_batch` | No per-item authorization/partial-result/retry contract | Blocked |
| `short_worker` | No delegated side-effect/revocation contract | Blocked |
| `managed_worker` | Synthetic frozen-config and safe-mode contracts | Blocked; current persistent policy checks are absent |
| `scheduled_job` | No authorization/cancel/delivery/reconciliation contract | Blocked |

“Synthetic contract” is not full coverage of a named tool family. A successful in-memory probe does not prove shell, MCP, browser, external delivery, or real worker side effects are protected. The inventory is immutable internally and returns independent snapshots; mutating a report cannot grant a capability or change later reports.

## 4. Requirements before writes can be enabled

1. Introduce verified owner identity and scoped action intents/grants through E1, with trusted provenance rather than model-supplied approval flags.
2. Enforce authorization inside each domain action handler, including calls that do not traverse the model-facing hook pipeline. Failure of a policy store must not become permission.
3. Read the current persistent policy revision at action admission. A frozen worker config is not that authority. Follow the transaction ordering and in-flight limits in [the revocation design](06-plugins-mcp-and-security.md#8-revocation-audit-and-emergency-stop).
4. Validate every enabled path and narrow exposed tools, credentials, and execution environments so an unprotected alternate route cannot perform the same controlled effect.
5. Use appropriate OS/process isolation where the threat requires containment. In-process hooks and this inventory are not replacements for it.

No mode or configuration toggle in this slice enables writes. It remains possible for an independently configured Hermes host to expose its own tools; this plugin does not claim control over those tools.

## 5. Evidence and limits

- Baseline: Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`, Linux, Python 3.14, isolated test homes, and no account credentials.
- The checker now runs every file under `tests/contracts` through the official per-file Hermes runner, in addition to unit tests, Ruff, ty, and bilingual document checks.
- Observed dispatcher failure applies to the tested `model_tools` wrapper. Other wrappers and direct MCP helpers were inspected in source only, not exercised as end-to-end writes.
- No production account, API key, live model request, external send, or real connector write was needed. Future online tests need a separate scoped test setup and secure credential handoff; credentials must not enter chat, logs, or the repository.
- The later [E0.2–E0.3 lifecycle contracts](75-native-lifecycle-contracts.md) add bounded Project/Kanban/cron operator evidence and document missing supported plugin CRUD APIs; they enable no production capability. Untested E0.4 paths, E1-dependent write admission, E3 orchestration and E4 controlled scheduling remain separate gates. Passing this slice does not complete M0 or permit those write features to ship.

Pinned sources:

- [Plugin dispatch behavior](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py)
- [Model-facing tool dispatch](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py)
- [Execution middleware](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/middleware.py)
- [Managed/safe worker policy](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/safe_worker_policy.py)
- [Upstream security model](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/SECURITY.md)
