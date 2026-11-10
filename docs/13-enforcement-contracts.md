# 13. Enforcement Contracts and Write-Path Inventory

English | [简体中文](13-enforcement-contracts-zh.md)

This page records the earlier E0 slice and its bounded RPC/MCP, terminal/browser, local-batch, persistent worker-policy and production-exposure follow-ons for [Issue #12](https://github.com/MosBot-AI/hermes-superagent/issues/12). See [16](16-local-task-inbox.md) for the newer opt-in local task inbox; it does not enable the native/external controlled-write paths described here.

This follow-on P0 slice advances E0.4 without enabling any controlled write capability. It adds reproducible failure-boundary tests and a machine-readable release inventory. The follow-ons exercise actual pinned RPC consumers/server dispatch, MCP admission, terminal/browser pre-execution guards and local batches in primary and delegated agent loops, and current durable policy checks in a protected synthetic read handler; they do not complete all alternate paths. E0.4, E0/M0, and E1 authorization remain incomplete.

## 1. What the implementation does

`personal_agent/enforcement.py` returns a fresh JSON-compatible inventory. Every known write path has `controlled_writes_enabled: false` and `release_gate: blocked`; unlisted paths are also unverified and blocked for this project's controlled-write release. The status tool includes only a bounded summary. In the default in-process plugin mode, `hermes personal-agent coverage` prints the full inventory.

This is a **read-only release report**, not an action authorizer, a live host inspection, or a sandbox. It does not disable another Hermes tool, intercept a direct API call, or turn an operator's existing tool configuration into a controlled environment. The baseline commit is evidence about the tested source, not a claim that the current host runs that commit. The pinned host skips plugin CLI registration in host-isolation mode.

## 2. Observed behavior at the pinned baseline

The original enforcement tests load a real directory plugin through real discovery. Its only handler records calls in memory. No fake manager, context, manifest parser, registry, or config loader is used. Callback behavior is controlled by the test fixture; the outer dispatcher test explicitly injects one escaping dispatcher exception.

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

### 2.1 Nested RPC admission and response-loss counterexample

[RPC contracts](../tests/contracts/test_nested_rpc_enforcement.py) call the actual `_rpc_server_loop` without its optional dispatch override. JSON framing, token comparison, allow-list, call budget, `_default_dispatch`, `model_tools`, plugin hooks/middleware and error logs remain native. Only the socket protocol endpoint is an in-memory double: no listener, socket connection, sandbox, shell or model is opened. The loaded fixture handler records effects in memory.

- Empty/mismatched/non-ASCII tokens, an empty server token, malformed JSON, an unavailable tool and an exhausted budget refuse before handler execution. Only dispatched attempts consume the budget; a hook-denied attempt still consumes one and is recorded by `tool_errors_since`.
- Normal plugin veto and callback failures stop the nested call. An explicitly injected exception escaping the outer hook dispatcher still reaches the handler. Nesting through RPC does not repair that existing failure domain.
- Two identical authenticated packets execute twice. The token, tool allow-list and call budget are neither an ActionIntent nor an idempotency key.
- The test executes the host-generated `_UDS_TRANSPORT_HEADER` client unchanged except for connection setup. Its transport double drops the first response **after** the real server/default dispatch completes. A one-shot client raises with one observed effect; a persistent client reconnects, repeats the same packet and returns after a second effect. This is a generated-client retry counterexample over an in-memory wire, not a live UDS/TCP or complete session-kernel test. Local session-kernel current-cell authority is covered separately in §2.9; remote filesystem polling and fallback selection are bounded separately in §2.10.

### 2.2 MCP admission versus declared read-only behavior

[MCP enforcement contracts](../tests/contracts/test_mcp_enforcement.py) reuse [74's SDK stdio facade](74-synthetic-connector-fixtures.md). They use actual MCP discovery, registry registration, native wrappers and stdio sessions. A separate read-only SQLite observer counts attempts/effects; returned prose is not the oracle. The only approval substitution is the synthetic UI endpoint returning deny, cancel or an exception, not the native trust gate.

- A real registered plugin veto or callback exception stops model-facing MCP dispatch before any remote execute attempt. With synthetic `trust: full`, direct registry dispatch of the same arguments bypasses that plugin callback and creates one fixture effect. This does **not** mean direct registry bypasses every MCP gate.
- Configured `trust: untrusted` write tools retain the native trust gate through both model and direct registry dispatch. Deny, cancel and approval-endpoint failure refuse before call-server acquisition, with zero remote execute attempts/effects.
- A deliberately dishonest `readOnlyHint: true` tool on the untrusted server creates an effect without a trust prompt. The annotation is a declaration, not effect-level authorization or isolation. [74](74-synthetic-connector-fixtures.md) separately records declaration-driven replay after an injected session-expiry error.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `rpc_token_allowlist_budget` | `test_rpc_invalid_tokens_never_reach_default_dispatch`, `test_rpc_empty_server_token_fails_closed`, `test_rpc_framing_allowlist_and_budget_refuse_before_dispatch` |
| `rpc_nested_hook_failure` | `test_rpc_default_dispatch_honors_plugin_denial_and_callback_failure` |
| `rpc_outer_dispatcher_failure` | `test_rpc_outer_dispatcher_failure_still_reaches_nested_handler` |
| `rpc_duplicate_request` | `test_rpc_identical_authenticated_requests_are_not_deduplicated` |
| `rpc_persistent_client_response_loss` | `test_generated_rpc_client_response_loss_can_replay_an_effect` |
| `mcp_plugin_veto_and_registry_bypass` | `test_registered_plugin_blocks_mcp_but_direct_registry_bypasses_plugin` |
| `mcp_native_trust_gate` | `test_native_untrusted_gate_stops_before_transport` |
| `mcp_dishonest_read_hint` | `test_untrusted_read_only_hint_is_not_effect_level_authorization` |

### 2.3 Terminal and browser admission at inert execution endpoints

[Terminal/browser contracts](../tests/contracts/test_shell_browser_enforcement.py) preserve native model/registry dispatch, the loaded plugin, terminal command/workdir guards and browser URL pre-scan. Terminal execution planning/acquisition, command execution and browser lifecycle/process endpoints are inert test substitutes. Reaching a recorded endpoint is **not** an executed shell command, real browser action or proof of backend containment. Process creation, DNS and socket connections are denied by the fixture. Each denial test includes an allowed control reaching the same endpoint.

- A profile-local native terminal deny rule refuses through both model and direct registry dispatch. A submitted `force: true` does not help: the public registry handler does not forward the internal helper's `force` argument, and the public schema does not expose it.
- Direct internal `terminal_tool(..., force=True)` reaches the synthetic backend despite that deny rule and the plugin's veto. The same call still refuses an invalid workdir before the backend. This documents separate Python helper authority, not a model-accessible force field.
- Normal plugin veto blocks terminal and `browser_exec` model calls. Direct registry calls skip that plugin veto; direct `browser_exec` helper calls do too. Native tool guards are distinct and still apply where tested.
- A cloud-metadata URL literal is refused by the real `browser_exec` pre-scan through model and registry routes, including with `browser.allow_private_urls: true`. A dynamically assembled URL passes this **literal pre-scan** and reaches the inert endpoint. Its code is never evaluated: actual harness/CDP URL admission and navigation remain unverified. The removed `browser_tool` compatibility stub is not mistaken for the current browser tool.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `shell_native_deny_and_force_surface` | `test_terminal_native_deny_survives_registry_and_model_force_argument` |
| `shell_internal_force_boundary` | `test_terminal_internal_force_skips_approval_but_not_workdir_guard` |
| `shell_plugin_registry_boundary` | `test_terminal_plugin_veto_does_not_cover_direct_registry` |
| `browser_metadata_literal_floor` | `test_browser_metadata_literal_is_blocked_before_backend` |
| `browser_plugin_helper_boundary` | `test_browser_plugin_veto_and_direct_helper_boundary` |
| `browser_dynamic_url_prescan_limit` | `test_browser_dynamic_url_is_not_evaluated_by_literal_prescan` |

### 2.4 Local bridge batches and constructed delegated children

The local-batch cases in [batch/worker contracts](../tests/contracts/test_batch_worker_enforcement.py) construct a real `AIAgent` and execute its real `run_conversation` loop. The loaded test plugin records in-memory effects independently of result prose. Only model-client/metadata endpoints are doubled; prompt caching, compression and trajectory saving are disabled for this isolated fixture. Local `tool_call` expansion, segment planning, per-item admission, plugin hooks, registry dispatch and message/result pairing remain native.

Each local-batch case runs on both a primary agent and a child produced by real `_build_child_agent`. The child asks for `terminal` outside its parent's configured toolsets and does not receive it. This proves the tested constructor selection and child loop, not `delegate_task` scheduling, background lifecycle or arbitrary delegated-code containment.

- A three-item local batch executes the allowed first/last items, denies the middle item before its handler, and returns three uniquely paired tool results. A partial denial does not make the whole batch atomic or undo earlier effects.
- A fixture handler records an effect and then raises, modeling a lost result after an effect. A new **scripted model response** emits the same item again and produces a second effect; both denied items remain denied. This is not automatic transport retry or a real model-behavior claim. Per-item result IDs and batch expansion do not provide effect-level idempotency.
- A new scripted model turn after an in-memory fixture policy change re-enters the current callback and refuses the previously allowed item. This establishes callback rechecking only, not current persistent policy reads, transactional revocation or worker cancellation.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `local_batch_item_veto` | `test_native_local_batch_veto_preserves_other_items_and_pairing` |
| `local_batch_uncertain_retry` | `test_native_local_batch_uncertain_item_retry_is_not_deduplicated` |
| `local_batch_policy_recheck` | `test_native_local_batch_retry_rechecks_changed_fixture_policy` |
| `delegated_child_toolset_and_batch_admission` | The same three cases under the `delegated-child` fixture, including constructor toolset assertions |

The `local_tool_batch` inventory row is separate from `connector_batch`: connector-only batches retain their own native dispatcher and are not validated by local bridge expansion. These local cases do not cover RPC/code batching or production connector authorization.

### 2.5 Connector-only batch partial results and explicit retry

`test_connector_only_batch_veto_partial_result_and_explicit_retry` in the same file calls real `model_tools` `tool_call` dispatch, which enters native connector-only batch dispatch and per-item model dispatch. Native availability checks, loaded-plugin admission/middleware, remote-call planning, file staging and result splicing remain in place. Only gateway client construction is replaced with an offline schemas/execute endpoint. The isolated profile has no credentials; default guest discovery availability is exercised without minting a guest credential, connecting to a gateway or testing authentication.

An allowed item records an effect, a denied item is refused before client acquisition, and an uncertain item records an effect before its synthetic client omits the result slot. Native output preserves indexed success/denial/`PROVIDER_ERROR` results. Repeating the outer call explicitly records the successful and uncertain effects again, while the denied item still never acquires a client. Client-acquisition IDs are exactly outer-call ID plus `#0`/`#2` on each attempt; they do not prove server idempotency. This is **caller-issued retry**, not the real `ToolGatewayClient` transport retry path.

The test uses primary-session context for direct model dispatch. It does not run a child connector loop, the concurrent batch executor, real gateway credential/permission resolution or production operation-level grants. The inventory ID `connector_batch_item_veto_partial_retry` maps to this assertion. All controlled-write gates remain blocked.

### 2.6 Frozen worker configuration with current durable read policy

[Worker-policy contracts](../tests/contracts/test_worker_policy_enforcement.py) launch a fresh process that calls the real `agent.managed_worker.bind_worker_policy` before runtime imports, loads a real directory fixture plugin and remains alive across multiple model-facing/direct-registry calls. The handler uses the existing [fenced read coordinator](27-fenced-read-admission.md) and [prepared-read audit](63-prepared-read-audit.md). No new runtime authorizer, production adapter, grant state or activation option is introduced.

The fixture explicitly supplies independent synthetic one-shot host confirmations and synthetic ownership/resource snapshots through its private test-control pipe. Pending database rows, `approved: true` and draft labels in model arguments cannot supply those adapters or handles. It reads only a fixed synthetic summary. Real owner adoption, `WorkerChannel`, provider inference, full managed-worker lifecycle and production write authority are outside this test.

- The same handler succeeds through both model and direct registry dispatch before a separate connection revokes or replaces the policy. Subsequent calls re-enter the handler but do not read the resource or commit another audit under stale versions. The PID stays unchanged and native config still returns its frozen value, even after the on-disk config becomes invalid. Current policy comes from the separate SQLite store, not a profile-config refresh.
- A no-op policy replacement advances policy revision/epoch. Only a newly issued independent synthetic confirmation matching the new policy can read again; the enrollment remains pending. A synthetic confirmation matching even the revoked row's current versions is still refused: terminal revocation is not a route to activate an enrollment.
- Admission-first ordering holds a real SQLite write lock during the bounded synthetic read. An independent zero-timeout contender observes `SQLITE_BUSY`; the separately initialized revoker attempts its own `BEGIN IMMEDIATE` and commits only after the admitted read completes. Its audit retains the admitted epoch. Revoke-first ordering holds the revoke transaction at COMMIT while the worker attempts admission; once revoke commits, no resource read or audit occurs. These tests do not promise to retract already-admitted data.
- Missing authority/resource adapters refuse before resource access. A consumed one-shot handle cannot replay through the other dispatch route. The dispatcher hook is not the policy gate: enforcement is inside the fixture handler's call to the coordinator.
- SQLite authorizer fault injection denies enrollment reads, audit insertion or COMMIT. Every case returns no summary and commits no prepared-read audit. Audit/COMMIT failures occur after the synthetic summary has already been read; the tests do not claim to undo that read. After fault removal, a fresh independent confirmation permits recovery.
- Troubleshooting safe bootstrap omits this fixture plugin/tool; actual registry/model attempts fail and no read audit is added. This verifies fixture-capability absence, not actual production-package fallback or host-wide read-only behavior. The separate actual-package evidence is recorded in §2.7.

The child environment uses an explicit allowlist and denies socket connections. The shared test-control reader enforces an absolute whole-frame deadline, byte limit and complete JSON-object framing, including partial-frame, EOF, consecutive-frame and oversize regression cases. Teardown closes streams, joins mutation threads and reaps the child. This is a fixture protocol, not the native owner/worker IPC or a new public API.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `worker_current_policy_recheck` | `test_live_worker_rechecks_persistent_policy_on_both_dispatch_paths` |
| `worker_missing_authority` | `test_pending_record_and_model_claims_do_not_replace_adapters` |
| `worker_transaction_failure` | `test_handler_storage_failures_return_no_data_or_committed_audit` |
| `worker_safe_capability_absence` | `test_safe_worker_suppresses_fixture_plugin_and_registry` |
| `worker_admission_before_revoke` | `test_admission_holds_sqlite_lock_before_competing_revoke` |
| `worker_revoke_before_admission` | `test_revoke_commit_wins_while_worker_waits_for_sqlite` |
| `worker_one_shot_cross_path` | `test_confirmation_is_consumed_across_dispatch_paths` |

### 2.7 Actual production-package exposure and fallback

[Production-exposure contracts](../tests/contracts/test_production_exposure.py) stage the unchanged manifest, entrypoint and modules in an isolated profile and load them in a fresh process. Module origins must be inside that installed-shaped package; the child has no repository-root import fallback. The native plugin manager, model-facing/direct-registry dispatch, command resolution and blueprint consumers remain real. An enforcement fixture does not stand in for the production package.

The finite matrix covers omitted defaults and explicit `read_only`, ordinary-managed and config-only frozen configurations, troubleshooting-safe bootstrap with valid opt-ins, clean-host unsupported text-worker opt-in, and three blueprint consumer states. Both dispatch routes are exercised within applicable cases.

- Default/read-only loading retains the diagnostic status tool, access diagnostic and CLI. Both dispatch routes actually reject optional manifest tools; task CLI mutation is disabled and forged identity/approval claims do not grant protected access. Successful status dispatch is the package-loading control.
- Ordinary-managed and config-only binding occurs before runtime imports. The package remains loadable, but editing disk configuration or a returned configuration copy does not acquire new opt-ins. The namespaced production read-admission service with missing authority/resource adapters refuses before storage access. This is configuration/admission evidence, not config-edit revocation or full worker lifecycle.
- Safe bootstrap suppresses the actual package, including an opted-in snapshot's tools, commands, hooks and blueprint. Negative calls include status; the absent plugin does not fabricate fallback diagnostics. No plugin storage or cron job is created, and pre-existing synthetic job bytes remain unchanged. Native builtin tools and existing jobs are not disabled by this observation.
- On the clean pin, `plan_worker: true` with local prerequisites and configured consent still reports `unsupported_host`; its command and preview tool remain unavailable. The native capability registry does not grant the unknown `llm.text_worker` capability. Guarded generic-launch and model endpoints observe no fallback. Opted-in local task/memory handlers refuse write-shaped calls without a live activated native turn, including direct registry calls without pre-tool admission.
- Default-off and safe-with-opt-in blueprint lookup, native slash inline creation and dashboard submission refuse the missing template before inert create/notification endpoints. An ordinary `read_only` plus `planning_blueprint: true` positive control reaches those same endpoints with default local delivery. No job or provider call is executed. This preserves ordinary native scheduling as an opt-in exception; it does not establish controlled scheduling authorization or cancellation.

Independent storage and endpoint-call observations accompany denial results. Test subprocesses use synthetic data and guarded endpoints, not a real scheduler, provider, account, credential or external effect. Optional local features and the separately selected native memory provider are not mislabeled as nonexistent modules; the unavailable authority is verified-owner/controlled external-effect admission.

The fixture substitutes pointer width during `croniter` import and disables `urllib3`'s import-time IPv6 bind probe. Network/process/SQLite entry points, generic worker launch and all four plugin LLM completion facades have zero-call refusal oracles. Blueprint creation and notification endpoints are inert recorders only inside their consumer cases. Native admission and registration gates are not replaced, and the parent bounds and reaps each child process.

| Contract ID | Focused assertion |
|---|---|
| `production_default_exposure` | `test_production_default_exposure` |
| `production_frozen_configuration` | `test_production_frozen_configuration` |
| `production_safe_bootstrap` | `test_production_safe_bootstrap` |
| `production_worker_unsupported` | `test_production_worker_unsupported` |
| `production_blueprint_consumers` | `test_production_blueprint_consumers` |

### 2.8 Native concurrent connector wrappers and timeout boundaries

Eight additional parameterized [batch/worker cases](../tests/contracts/test_batch_worker_enforcement.py) run the real primary and constructed-child conversation loops on the pinned host. The model endpoint emits multiple pure-connector `tool_call` wrappers. Native planning admits them to the concurrent executor; each wrapper still dispatches its own items sequentially. A two-party barrier and distinct endpoint thread IDs prove overlap, rather than treating batch syntax as concurrency. Gateway client endpoints remain offline synthetic doubles; no transport, credentials or production authority are exercised.

- Per-item plugin veto prevents endpoint execution/effects for the denied item while allowed concurrent siblings complete and result pairing retains model order.
- An entered endpoint waits while its concurrent sibling changes fixture policy. It still completes, but the next item in its wrapper rechecks the hook and is denied. This is in-memory callback rechecking, not durable revocation or cancellation of already-admitted work.
- With the official concurrent timeout configured, endpoints remain held until the scripted model receives timeout results. The independent effect ledger is empty then; releasing the workers produces late effects. Unstarted subsequent entries do not enter endpoint execution. Recorded timeout outcomes retain `effect_disposition: unknown` and are not overwritten by late completion.
- After late workers drain, an explicit scripted retry can repeat the effect; revoking fixture policy before that retry denies it. The executor does not establish exactly-once effects or gateway/server deduplication. Thread release and drain precede fixture teardown.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `concurrent_connector_item_veto` | `test_native_concurrent_batches_overlap_and_veto_each_item` |
| `concurrent_connector_policy_recheck` | `test_native_concurrent_batch_rechecks_policy_between_items` |
| `concurrent_connector_timeout_retry` | `test_native_concurrent_timeout_late_effect_and_retry` (allowed/revoked retry) |

All three assertions run under primary and constructed delegated-child contexts. Full delegation scheduling, background lifecycle, alternate execute-code routes and production operation-level authorization remain separate gates. All controlled-write release paths stay blocked.

### 2.9 Persistent local kernel cell authority

Ten [kernel authority cases](../tests/contracts/test_kernel_authority_enforcement.py) retain real `CellAuthority`, `_rpc_forever`, RPC admission/default model dispatch, loaded-plugin hooks, `_run_cell`, result handling and retirement against the pinned host. The wire and an already-created process's stdin/response queue are synthetic endpoints; no socket, process or sandbox is launched, and submitted code is never executed.

- One persistent wire switches from absent authority to cell one, retired cell one, cell two and retired cell two. Only the two active cells produce independent fixture effects; each records its captured ContextVar and task ID. The calling context is restored. This tests current-cell rebinding, not an authenticated owner identity.
- Current-cell RPC retains plugin veto and callback exception/SystemExit refusal before the handler. Native RPC attempt accounting includes authority denials.
- `_run_cell` retires authority after success, a reported cell exception, stdin failure, timeout and interruption. A subsequent RPC refuses without another effect. The synthetic process teardown endpoint is reached on stdin failure/timeout/interruption; this does not verify real process termination. Initial spawn failure remains outside this matrix.
- A real worker thread starts with callback B, dispatches under authority captured with callback A and the caller's ContextVar/task, then regains B and its original ContextVar. The fixture only observes callback identity; it invokes no approval or privileged operation. No admission/context/retirement implementation is replaced.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `kernel_current_cell_authority` | `test_persistent_rpc_current_authority_and_retirement` |
| `kernel_cell_plugin_veto` | `test_current_cell_rpc_preserves_plugin_veto` |
| `kernel_cell_retirement` | `test_run_cell_retires_authority_on_normal_and_error_exit` |
| `kernel_thread_context_restore` | `test_cell_captures_calling_context_and_restores_rpc_thread_callbacks` |

The remote polling/fallback-selection evidence is bounded separately in §2.10. Actual per-call execution, real subprocess/sandbox containment, full delegated/background lifecycle and operation-level production authority remain unverified. Retirement prevents subsequent dispatch; it does not retract an already-admitted effect. All controlled-write gates remain blocked.

### 2.10 Remote polling and fallback selection

Thirteen [remote execution cases](../tests/contracts/test_remote_execution_enforcement.py) retain pinned native `_rpc_poll_loop` parsing, token/sequence admission, allow-list/budget, default dispatch and loaded-plugin hooks, with an inert remote-filesystem endpoint. Invalid JSON, token and sequence requests are removed without a response or handler effect. Allowed requests use atomic response-write options; plugin veto and callback failures prevent effects. Independent fixture records, counters, logs and response attempts are asserted, not just returned prose.

A failed response write leaves the request present: the next poll dispatches it again and produces a second synthetic effect. This is evidence against exactly-once execution, not a recovery guarantee. `_execute_remote` selection is tested separately: kernel `None` or an exception enters the substituted per-call endpoint with the same task, tool set and limits; a reported kernel success/error does not fall back; missing Python prevents either endpoint. Kernel creation and per-call execution are not exercised by this selector test.

| Inventory contract ID | Executable assertion |
| --- | --- |
| `remote_poll_admission` | `test_remote_poll_invalid_requests_removed_without_effect`, `test_remote_poll_allowlist_budget_and_success` |
| `remote_poll_plugin_veto` | `test_remote_poll_plugin_denial_prevents_effect` |
| `remote_poll_response_replay` | `test_remote_response_failure_can_replay_effect` |
| `remote_fallback_selection` | `test_remote_kernel_fallback_selection` |

No remote shell, filesystem, kernel, sandbox, model or credential is used. Actual per-call process lifecycle, transport ownership and containment remain unverified. All controlled-write gates remain blocked; delegated/background boundaries and the final finite ledger remain outstanding for #12.

## 3. Controlled-write release inventory

| Path | Evidence in this slice | Release status |
|---|---|---|
| `native_dispatch` | Hook/outer-dispatch failures plus actual package default exposure and negative dispatch | Blocked; production operation-level authorization is not integrated |
| `direct_registry` | Hook bypass, actual package default absence and unactivated local-handler refusal | Blocked; local activation is not verified-owner action authority |
| `mcp` | Actual SDK stdio plugin-veto/direct-registry and native trust-gate boundaries; dishonest read-only counterexample | Blocked; no production per-action authorization or credential/outcome contract |
| `shell` | Native deny/workdir and public/internal force boundaries at an inert backend | Blocked; no real shell, containment or operation-level authority contract |
| `browser` | Native metadata-URL literal pre-scan and plugin/direct-helper boundaries at an inert endpoint | Blocked; no real navigation, authenticated write or outcome contract |
| `execute_code_rpc` | Native RPC dispatch/retry, current-cell authority (§2.9) and remote polling/fallback selection (§2.10) over inert endpoints | Blocked; replay counterexamples remain; real sandbox containment and full process lifecycle are unverified |
| `local_tool_batch` | Real primary/child loops, per-item veto, result pairing and explicit retry counterexample | Blocked; no durable effect idempotency or persistent revocation |
| `connector_batch` | Real per-item model dispatch, indexed partial results and explicit retry at an offline gateway client | Blocked; production grants, credentials, transport retry and server deduplication remain unverified |
| `short_worker` | Real child construction/local-batch loop and actual package unsupported text-worker no-fallback boundary | Blocked; scheduler, background lifecycle and production authority remain unverified |
| `managed_worker` | Native binding/current SQLite read-policy fences plus actual package frozen-config exposure and safe-bootstrap omission | Blocked; no production authority, write grant or full worker lifecycle |
| `scheduled_job` | Actual project blueprint absence/opt-in through native consumers at inert create endpoints | Blocked; no controlled authorization/cancel/delivery/reconciliation contract |

`synthetic_contract` and `pinned_host_boundary_contract` are bounded evidence labels, not full coverage of a named tool family. A successful in-memory probe does not prove shell, MCP, browser, external delivery, or real worker side effects are protected. The inventory is immutable internally and returns independent snapshots; mutating a report cannot grant a capability or change later reports.

## 4. Requirements before writes can be enabled

1. Introduce verified owner identity and scoped action intents/grants through E1, with trusted provenance rather than model-supplied approval flags.
2. Enforce authorization inside each domain action handler, including calls that do not traverse the model-facing hook pipeline. Failure of a policy store must not become permission.
3. Read the current persistent policy revision at action admission. A frozen worker config is not that authority. Follow the transaction ordering and in-flight limits in [the revocation design](06-plugins-mcp-and-security.md#8-revocation-audit-and-emergency-stop).
4. Validate every enabled path and narrow exposed tools, credentials, and execution environments so an unprotected alternate route cannot perform the same controlled effect.
5. Use appropriate OS/process isolation where the threat requires containment. In-process hooks and this inventory are not replacements for it.

No mode or configuration toggle in this slice enables controlled external-effect admission. Existing explicit local task/memory, parked-card and ordinary planning-blueprint opt-ins retain their own boundaries. It remains possible for an independently configured Hermes host to expose its own tools; this plugin does not claim control over those tools.

## 5. Evidence and limits

- Current target: Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, Linux, Python 3.14, isolated test homes and no account credentials, as recorded in [compatibility.json](../compatibility.json). The original slice used `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`; historical results remain separate from current exact-revision runs.
- The checker now runs every file under `tests/contracts` through the official per-file Hermes runner, in addition to unit tests, Ruff, ty, and bilingual document checks.
- Observed dispatcher failure applies to the tested `model_tools` wrapper, including default nested RPC dispatch. MCP observations cover the real stdio fixture and native trust wrapper, not all server transports or account policies. Terminal/browser observations stop at inert execution endpoints. Connector-only observations stop at an offline gateway client. Local-batch and constructed-child loops do not establish delegated scheduling or background lifecycle, while §2.8 separately exercises the native concurrent executor at synthetic connector endpoints. Current durable policy is now exercised inside a synthetic read handler under native worker binding. Actual-package exposure/fallback is bounded in §2.7. Actual containment, authenticated effects and complete managed-worker lifecycle remain separate evidence gaps. Earlier config/safe-mode probes alone did not establish those guarantees.
- No production account, API key, live model request, external send, or real connector write was needed. Future online tests need a separate scoped test setup and secure credential handoff; credentials must not enter chat, logs, or the repository.
- The later [E0.2–E0.3 lifecycle contracts](75-native-lifecycle-contracts.md) add bounded Project/Kanban/cron operator evidence and document missing supported plugin CRUD APIs; they enable no production capability. Untested E0.4 paths, E1-dependent write admission, E3 orchestration and E4 controlled scheduling remain separate gates. Passing this slice does not complete M0 or permit those write features to ship.

Reproduce focused native tests with absolute paths because the official runner changes its working directory:

```bash
HERMES_PYTHON=/absolute/path/hermes-test-venv/bin/python \
bash /absolute/path/hermes-agent/scripts/run_tests.sh \
  /absolute/path/hermes-superagent/tests/contracts/test_nested_rpc_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_mcp_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_shell_browser_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_batch_worker_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_worker_policy_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_production_exposure.py \
  --file-retries 0 -- \
  -o "pythonpath=/absolute/path/hermes-agent /absolute/path/hermes-superagent" -q --tb=short
python scripts/check.py --hermes /absolute/path/hermes-agent \
  --hermes-python /absolute/path/hermes-test-venv/bin/python
```

Use the prepared Python 3.14 test interpreter for `python` in the aggregate command. The earlier RPC/MCP files contain 21 parametrized cases; the terminal/browser, batch/worker, persistent-worker-policy and production-exposure files add their own bounded cases. Focused success does not stand in for the aggregate or full E0.4 acceptance. Exact executed results belong to Issue #12 and its linked PR. No host patch or production capability is introduced.

Current pinned sources:

- [Plugin dispatch behavior](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_dispatch.py)
- [Model-facing tool dispatch](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/model_tools.py)
- [Execution middleware](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/middleware.py)
- [Managed/safe worker policy](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/safe_worker_policy.py)
- [Upstream security model](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/SECURITY.md)

- [Code RPC server](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/code_execution_rpc.py) and [generated client](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/code_execution_tool.py)
- [MCP native admission and recovery](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/mcp_tool_handlers.py)

- [Terminal public handler and execution guards](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/terminal_tool.py) and [browser execution](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/browser_use_cli.py)
- [Local batch expansion](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/tool_call_batches.py) and [delegated child construction](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/delegate_tool.py)
- [Connector batch dispatch](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/connectors/dispatch.py)

## 6. E0.4 completion versus later capability enablement

E0.4 verifies boundaries, recovery limits and the bounded production exposure of each tested configuration, including default absence, safe-bootstrap omission and handler-level refusal. The project's verified-owner and controlled external-effect adapters remain unavailable. Explicitly enabled local task/memory changes, parked native-card operations and ordinary host-owned planning-blueprint scheduling retain their separately documented boundaries. E1 depends on E0.4; implementing all production identity, approval and external-outcome machinery cannot become a circular prerequisite for this verification package. Those capabilities must still remain disabled until their own gates pass.

Here a controlled external-effect route means a project-owned path that turns verified intent/approval into an admitted external send, modification or spend, including scheduling such an action. Its absence does not mean zero local mutation, no ordinary native scheduling, stopping existing jobs or host-wide containment. In particular, `planning_blueprint: true` is an independent opt-in even with `mode: read_only`; the native consumers can create an ordinary job, delivery is not restricted to `local`, and a configured provider can incur costs. See the [blueprint boundaries](25-native-planning-blueprint.md).

Before closing Issue #12, the remaining bounded evidence must establish:

1. Retain actual production-package exposure and negative-dispatch evidence under default/read-only, ordinary managed, config-only and troubleshooting safe bootstrap, as bounded in §2.7. A report-only inventory or absence of a test fixture tool is insufficient, and explicit ordinary native scheduling remains separate.
2. Native concurrent batch admission and the remaining delegated/background and execute-code alternate routes: a behavioral boundary test, or an explicit unsupported seam plus verified non-exposure from the project-controlled mode. Inert shell/browser endpoints do not establish backend containment.
3. A final finite ledger linking each path to its exact boundary, denial/non-exposure assertion, effect oracle and tested revision. Separate verified E0.4 boundaries, technically unavailable modes and downstream E1/E3/E4/E5 enablement work.

This project can prove that its controlled-write adapter is unavailable while an independently configured Hermes host still exposes native tools. It must not describe that result as host-wide read-only enforcement. Any later claim to contain the host or a general-purpose worker requires corresponding tool, credential and OS/process isolation evidence.
