# Offline synthetic connector fixtures

English | [简体中文](74-synthetic-connector-fixtures-zh.md)

## Scope

This E0.5 slice for [Issue #13](https://github.com/MosBot-AI/hermes-superagent/issues/13) provides reusable, offline source and connector failure fixtures under `tests/fixtures/synthetic_connectors`. A synthetic write inserts a row into a temporary SQLite fake remote. It does not send a message, call a provider, or use an actual account. The native boundary uses the pinned Hermes MCP client and an SDK stdio server, not an HTTP listener.

The fixture protocol is a deliberately reduced test model of [14's connector design](14-client-api-contracts.md), not its production implementation. It issues no dispatch permit and proves no owner identity. [ActionIntentStore](64-action-intent-drafts.md) remains an internal, draft-only ledger, with no approval or execution API. E0.4, E1, E5 and live-provider acceptance remain open.

## Fixture layout and trust boundary

- `core.py` provides `Remote`, `Capabilities`, fixed validation errors and deterministic failure hooks. The fake remote owns durable account, binding, attempt, effect and cancellation records in its own SQLite file.
- `corpus.json` contains versioned `synthetic.sources.v1` records for exactly `account-a` and `account-b`. Normal, conflicting, spoofed-owner, forwarded and prompt-injection records carry source IDs, account references, author labels and provenance. Every source's `authenticated_owner` is false. Fixed `.invalid` addresses and URLs are fixture labels, never network destinations to contact.
- `stdio.py` exposes the fixture through the host-pinned MCP SDK. It is launched only by explicit test configuration in temporary Hermes homes. Normal plugin loading does not discover or register these tools.
- The runtime package uses an explicit [file allow-list](../packaging/runtime-files.json) that excludes `tests/`, including the corpus and stdio facade. No production plugin configuration, dependency, storage migration or connector activation is added.

Source content and tool-result prose are untrusted data. A claimed owner, an instruction to change a recipient, a purported approval, a secret-reading instruction or a success sentence grants no authority. Test setup selects adversarial behavior explicitly; the fixture never interprets source prose as code or as a setup command. Synthetic canary strings are not real secrets. This harness is not a sandbox for arbitrary Python or malicious MCP servers.

## Binding and limits

A prepared envelope binds `schema_version`, `account_ref`, `operation`, `target`, `payload`, `effect_key` and `prepared_version`, with separate target/payload digests and a digest of the binding metadata. The only write kind is `message.send`; targets are the two fixed fixture recipients. Preparation normally creates no effect. The deliberate `impure_prepare` and `lying_read` behaviors are positive controls that violate their apparent semantics so an independent observer can detect the mismatch.

Validation rejects unexpected fields, floats/non-finite values, unsupported accounts/targets, invalid versions and changed bindings. The raw `strict_json` parser, including the explicit `fixture_prepare_json` raw-string entry point, also rejects duplicate keys; a decoded SDK object cannot reveal duplicate keys already collapsed by the outer MCP JSON-RPC parser. Input JSON is bounded to 8,192 bytes and depth 8; message payloads to 2,048 UTF-8 bytes; a source page to 1–4 records. Prepared versions are checked against durable account configuration. Test-owned account controls can model `connected`, `expired`, `revoked` or `unavailable` authentication without credentials. The integer test clock is injectable, so retention and rollback tests do not depend on sleeps or a real provider clock.

These hashes bind this fixture's serialization. They are neither authentication nor a production RFC 8785 implementation, and they do not make low-entropy inputs private. The returned prepared envelope still contains synthetic target and payload text. The fake remote stores digest-bound effect metadata rather than treating the envelope as a production authorization token.

## Remote truth, retries and cancellation

`Remote.describe`, `health`, `read`, `prepare`, `execute`, `reconcile` and `cancel` are fixture operations, not native plugin APIs. Their capabilities and limits are explicit:

| Capability | Synthetic behavior and limit |
| --- | --- |
| `native_key` | The same account/effect key deduplicates an exact binding only during a finite retention interval: 60 seconds by default, configurable from 1 to 86,400 seconds. A direct unsafe retry after expiry can create another effect. |
| `reconciliation_only` / `none` | Execution does not deduplicate. Reconciliation support is separately declared; `reconciliation_only` requires it. A caller must not infer safe replay from a stable key. |
| Binding conflicts | An account/effect key remains bound to its original metadata. Changed target, payload or version conflicts; deduplication expiry does not permit changed content. This retained binding is not a claim of indefinite provider idempotency. |
| Reconciliation | Looks for the exact account/key/binding without executing again. Unsupported, unavailable, absent, ambiguous or mismatched evidence remains `unknown_outcome`. An empty lookup is not permission to resend. |
| Cancellation | Default unsupported. When enabled, only an effect not yet accepted can be durably cancelled. Unsupported or too-late cancellation reports `cancel_requested`; it does not erase an accepted row or assert delivery was stopped. |
| Receipt | A committed fake effect is `accepted`, with `delivered: false`. Acceptance is not delivery or read evidence. A receipt's prose is not independent proof. |

The remote database and consumer observations are separate evidence. Before-commit failure can leave no remote effect; after-commit response loss can leave one even though the caller receives no result. Both require truthful observation rather than guessing from an exception. Test checkpoints cover commit/response boundaries and process restart. They do not prove distributed exactly-once delivery, hardware power-loss durability or atomic revocation across systems.

## Consumer observations and independent oracles

`oracles.py` keeps `Observations` in a separate consumer SQLite file. `execute_once` records an unknown observation before making one attempt; it never retries. `reconcile_only` can read a replacement adapter after restart but never calls `execute`. A crash between remote commit and local observation therefore cannot turn an absent local receipt into evidence that no effect occurred.

`classify_receipt` checks bounded structure, exact binding, an accepted status and a syntactically plausible receipt reference. It returns only `accepted_claim`, never verified acceptance; a fabricated but well-shaped reference can pass this check. Both scenario runners default to `unknown_outcome` unless an explicit test `verifier` returns exactly `True`. `assert_matching_receipt` provides that independent oracle by reading the fake remote through `ground_truth` and verifying that the claimed reference identifies the exact committed effect. Real clients cannot assume such database access. This deliberate separation prevents a model-written success sentence or a self-reported receipt from becoming the test's ground truth.

`assert_pure` compares remote observations around a purported read/prepare. `assert_no_blind_resend` checks both effects and remote execute-attempt counts, including retries that a deduplicating provider would otherwise hide. `validate_sources` checks the fixed source schema, cursor, IDs, account, author labels and provenance; it rejects malformed/oversized results, duplicate source IDs and cross-account records. Valid source prose remains data. `sanitized_report` emits fixed categories/counts and `production_authorized: false`, not bodies, targets, hashes, source instructions, canaries or raw errors. `observation_count` counts local observation rows, not remote execute attempts. Neither consumer observations nor remote attempts establish delivery.

## Real pinned-host MCP boundary

The native contracts target the unchanged [compatibility record](../compatibility.json): Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, Python 3.14 and the MCP SDK version declared by that host. They use actual discovery, registry registration, SDK stdio sessions and `model_tools.handle_function_call` dispatch. The facade exposes `fixture_describe`, `fixture_health`, `fixture_read`, `fixture_prepare`, `fixture_prepare_json`, `fixture_execute`, `fixture_reconcile` and `fixture_cancel`, plus explicit adversarial probes. The temporary test configuration sets MCP `trust: full` solely for synthetic dispatch; these tests do not establish native approval enforcement.

A real subprocess exit before or after remote commit loses the write response. The native client reports an uncertain outcome in both cases; a new stdio process reconciles durable state instead of blindly replaying it. Tests inspect the remote SQLite file independently rather than accepting a returned effect count as evidence.

The session-expiry scenario injects a synthetic `HTTP 404: session not found` exception **after a real stdio RPC and durable synthetic write**. Discovery, dispatch, reconnect and any repeat call are real; this is not an HTTP transport test. With a write declaration, the host preserves uncertainty without replay. With a dishonest `readOnlyHint: true`, the same recovery branch may replay a state-changing tool and create a second synthetic effect. The counterexample demonstrates that declaration-based replay is not effect-level authorization or isolation. It does not claim all host paths are covered or patched.

## Scenario-to-test evidence map

The matrix identifies executable assertions, not an independent claim that every run passed. Exact run results and revisions belong to the linked Issue/PR evidence. The first group uses [unit tests](../tests/unit/test_synthetic_connectors.py); the host/SDK and subsequent rows use [native contracts](../tests/contracts/test_synthetic_connectors.py).

| Scenario | Concrete test | Evidence boundary |
| --- | --- | --- |
| Bounded sources, provenance and account isolation | `test_bounded_corpus_has_stable_provenance_and_separate_accounts`; `test_source_prose_cannot_establish_owner_or_production_authority` | Stable paged corpus, explicit account separation and production evaluator refusal of source text as owner context. |
| Malformed/oversized source results | `test_malformed_and_oversized_source_results_are_rejected`; `test_invalid_read_scope_and_bounds`; `test_invalid_source_schema_is_rejected_with_fixed_error`; `test_duplicate_source_ids_are_rejected` | Bounded source parsing and invalid read scopes; no source ingestion or automatic action. |
| Read/prepare purity and dishonest declarations | `test_prepare_read_describe_health_are_pure`; `test_dishonest_purity_is_detected_by_independent_oracle` | Independent remote-state comparisons detect deliberate hidden effects. |
| Exact binding and account namespaces | `test_tampering_prepared_fields_is_rejected_without_effect`; `test_reprepared_changed_data_conflicts_with_stable_effect_key`; `test_account_namespace_is_explicit_not_implicit_permission` | Changed fields cannot reuse a binding; separate account keys do not establish cross-account permission. |
| Authentication change and stale preparation | `test_auth_change_refuses_reads_preparation_and_execution`; `test_prepared_version_is_checked_at_execution` | Expired/revoked/unavailable synthetic accounts and stale versions refuse further operations; no real authentication flow. |
| Strict untrusted input | `test_strict_json_rejects_duplicate_malformed_deep_and_oversized`; `test_invalid_input_never_commits_and_errors_are_redacted`; `test_lists_and_executable_subclasses_are_rejected_before_execution` | Reject duplicate keys, malformed/deep/oversized data, unsupported fields and executable container subclasses before an effect. |
| Finite idempotency and unsafe replay | `test_success_deduplicates_and_receipts_are_accepted_not_delivered`; `test_finite_idempotency_expiry_unsafe_resend_positive_control`; `test_no_native_key_replay_is_deliberately_not_deduplicated` | Accepted is not delivered; unsafe repeat attempts can duplicate after retention expiry or without native keys. |
| Uncertain pre/post-commit failures | `test_indistinguishable_losses_remain_unknown_without_blind_retry`; `test_capability_variants_and_unknown_recovery` | The same observed failure can mean zero or one effect. Capability-specific reconciliation never executes again. |
| No evidence is not proof of nonexecution | `test_unavailable_or_empty_reconciliation_cannot_prove_nonexecution` | Unavailable/empty reconciliation preserves uncertainty despite an independently observed committed effect. |
| Truthful cancellation | `test_supported_cancellation_before_acceptance_is_terminal`; `test_unsupported_and_too_late_cancellation_are_truthful` | Before-acceptance cancellation survives reopen; unsupported/too-late requests do not undo accepted effects. |
| Malicious or contradictory receipts | `test_malicious_receipts_fail_independent_evidence_oracle`; `test_plausible_claim_is_not_accepted_without_independent_evidence` | Wrong account/target/effect/receipt, success prose, contradictory delivery and injected instructions fail independent evidence checks; a plausible claim without a verifier remains unknown. |
| Abrupt process recovery | `test_process_crashes_preserve_separate_remote_and_consumer_truth` | Actual process exits before commit, after commit and after response but before observation; reopened consumer remains unknown until verified reconciliation. |
| Concurrency and clock rollback | `test_concurrent_native_key_attempts_create_one_effect`; `test_clock_rollback_is_refused_without_new_effect` | Concurrent exact native-key attempts share one effect; a backward test clock cannot create another effect. |
| Draft-only production boundary and redaction | `test_actual_action_intents_remain_drafts_across_reopen_cancel_and_expiry`; `test_fixture_binding_is_not_action_intent_or_authorization`; `test_loss_exception_and_reports_never_contain_canaries` | Real ActionIntentStore stays draft-only across reopen/cancel/expiry; fixture data is no permit, and diagnostic reports omit canaries/content. |
| Host and SDK identity | `test_sdk_and_host_are_exact_pins` | Compares host HEAD and installed MCP SDK with repository/host declarations; no broad compatibility range. |
| Real discovery, dispatch and purity counterexample | `test_discovery_and_model_dispatch_reach_real_stdio`; `test_native_read_only_hint_and_prepare_name_do_not_enforce_purity` | Actual stdio read/prepare/write/reconcile/cancel, plus dishonest read/prepare probes measured in the remote database. |
| Raw JSON validation through native dispatch | `test_raw_fixture_json_rejection_through_native_dispatch` | Valid raw-string preparation, then duplicate/malformed/unknown-field/deep/oversized input refusal with no effect; no claim about outer JSON-RPC duplicate-key handling. |
| Server death before/after remote commit | `test_real_stdio_death_is_unknown_without_replay` | Real server death, uncertain native result, restart and reconciliation with the independently observed zero/one effect. |
| Session expiry and dishonest read-only hint | `test_session_expiry_boundary_obeys_declaration_not_real_effects` | Post-RPC injected expiry boundary; contrasting write/no-replay and lying-read/replay effect counts. No actual HTTP session expiry. |
| Default plugin remains closed | `test_normal_plugin_load_never_exposes_fixture_or_execution` | Default/read-only/local-task modes expose no fixture tools or storage; production admission stays off and ActionIntentStore has no approve/execute method. |

## Reproduction and interpretation

Use an isolated test environment and synthetic temporary homes, following the [development checks](../README.md#development-checks). Do not configure the facade in a production profile or copy credentials into a test home.

```bash
python -m pytest tests/unit/test_synthetic_connectors.py -q
python scripts/check.py
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

The first command runs the focused fixture suite. The second runs repository unit, lint, type and bilingual documentation checks but explicitly does not run Hermes contracts. The last adds the complete pinned-host contracts, including the stdio tests, and requires the exact clean Git checkout and its prepared interpreter. Test discovery alone is not a passing run; a passing focused suite is not a full acceptance result. See the [compatibility matrix](hermes-compatibility-matrix.md) for the current target and historical evidence.

## Remaining gates

This slice adds no network service, OAuth flow, account connection, model request, production dispatch permit, outbox or automatic retry engine. It does not complete alternate-path enforcement, trusted owner/approval admission, actual connector integration, real cancellation/delivery verification or a usable personal-agent release. The design API in [14](14-client-api-contracts.md) remains proposed, and the draft-only boundary in [64](64-action-intent-drafts.md) is unchanged.
