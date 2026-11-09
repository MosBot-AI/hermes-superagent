# 76. Native Memory Provider Contracts

English | [简体中文](76-native-memory-contracts-zh.md)

## Scope and baseline

This test-only E0.9 slice addresses [Issue #42](https://github.com/MosBot-AI/hermes-superagent/issues/42). It verifies native memory reuse points and records unsupported boundaries. It does not implement automatic ingestion, durable project checkpoint-v2, a source resolver, remote identity, or a new memory backend. Installation and provider selection remain explicit; no user profile, account or production setting changes.

The exact target is [Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427), recorded in [compatibility.json](../compatibility.json), with the separate Python 3.14 environment. Tests use clean pinned source and disposable synthetic profiles. This is fixed-revision evidence, not a broad support range, installed deployment or real-model acceptance. Historical evidence in [30](30-pluggable-memory-contracts.md) and [43](43-native-checkpoint-boundary.md) retains its original pin; this matrix adds the current-target verification separately.

The matrix identifies assertions and their limits. Execution results belong to the exact Issue/PR revision and must not be inferred merely from the presence of tests. E0.9 verification and E2.8 durable lifecycle implementation are separate gates; recording an unsupported contract does not enable it.

## Acceptance matrix

| Contract | Evidence | Boundary |
| --- | --- | --- |
| Provider discovery, selection and dependency admission | `test_native_memory_admission.py` | Native directory/entry-point listing and loading, activation and failure paths. Metadata-only listing must be distinguished from availability probes that can import provider code. No runtime dependency installation is authorized. |
| Single external slot | `test_native_memory_provider.py::test_native_manager_refuses_second_external_provider` | Actual manager refuses a second external provider. Builtin coexistence does not permit a project adapter to impersonate builtin or silently chain providers. |
| Builtin MEMORY.md / USER.md | `test_native_memory_stores.py` | Native capacity and reload contracts, not replacement of host stores or an unlimited fact archive. |
| Native history retrieval | `test_native_session_search.py` | Actual stored content, bounded result shapes, source handling, explicit profile reads and FTS/CJK behavior. Search visibility is not a caller authorization boundary. |
| Provider lifecycle and context wiring | `test_native_memory_wiring.py`; existing `test_native_memory_provider.py` | Host callback/context behavior and product refusal are separate assertions. Cron and subagents are not universally memory-free or read-only. |
| Profile, session and live revocation | `test_native_memory_provider.py` | Selected personal-records recall rejects stale sessions, foreign homes, nonprimary/remote contexts, disabled configuration and managed-scope changes. This is not remote-owner authentication or same-UID process isolation. |
| Asynchronous write outcomes | `test_native_checkpoint_boundary.py::test_async_turn_sync_failure_is_not_a_checkpoint_receipt` | A drained queue can include failed sync callbacks; queue completion and an assistant acknowledgement are not durable write receipts. |
| Checkpoint v1/v2 and strict failure | `test_native_checkpoint_boundary.py`; `test_native_memory_provider.py::test_actual_manager_preserves_required_checkpoint_failure` | Best-effort v1 is not strict checkpoint support. Native v2 accepts a normal callback return without validating a durable receipt; provider errors propagate through the required gate. The project provider remains v1 and strict mode fails closed. |
| Source identity and compression | `test_native_checkpoint_boundary.py` | Stable UIDs, merge lineage and revisions exist, but pending/unidentified constituents and unbound callback input prevent assuming complete durable source coverage. Native app-server strict-checkpoint restrictions remain explicit. |

Test paths above are relative to `tests/contracts/`. Existing [provider contracts](../tests/contracts/test_native_memory_provider.py) and [checkpoint contracts](../tests/contracts/test_native_checkpoint_boundary.py) are reused rather than duplicated. Internal native consumer imports are exact-pin test seams, not new supported production plugin APIs.

## Concrete behavior and counterexamples

### Discovery and activation

`test_metadata_listing_never_imports_but_availability_discovery_does` distinguishes the public name-only listing from availability discovery, which executes synthetic provider imports. `test_directory_precedence_then_entry_point` covers bundled, user, project and bare-module entry-point precedence. The inactive-provider test proves that inspection neither changes the selected provider nor registers inactive skills; it does not claim that explicitly loading arbitrary provider code is inert.

Missing dependency/import failures are tested without allowing subprocess installation or configuration mutation. Disabled user-directory providers are refused before import. **A bare-module entry point is different:** `plugins.disabled` does not park it in `in_process` mode on this pin. Host-isolation mode refuses that bare-module entry point before import. This is a documented native limitation, not permission to bypass the selected isolation mode or assume a generic disable gate. The project's own recall configuration checks remain separate.

`test_directory_provider_host_mode_runs_in_separate_process` additionally loads a real hosted directory-provider proxy. The provider reports a different process ID and its module is absent from the parent interpreter; the transient host is stopped afterward. This demonstrates process separation, not filesystem/network sandboxing or a full security audit.

### Builtin stores and refresh

`test_builtin_caps_boundary_and_overflow_preserve_disk` checks default MEMORY.md / USER.md capacities of 2,200 / 1,375 characters and configured limits. Chinese content proves that these limits count characters, not UTF-8 bytes. At-capacity content persists; overflowing add and replace fail without changing the files, and reopening preserves accepted contents.

`test_actual_prompt_invalidation_reloads_external_store` uses the real store, prompt assembly and invalidation functions with inert agent state, not a live model constructor. A second store changes both files; the original prompt remains stale until invalidation reloads memory and clears cached prompt state. The refreshed prompt contains both changes. A second parametrized path executes actual `compress_context` → `_rebuild_system_prompt_at_boundary` → invalidation → prompt rebuild, retaining native candidate admission and post-boundary bookkeeping. Its summary phase is synthetic; model/external preparation, lease acquisition/adoption, tool refresh and telemetry are substituted, and no durable session database participates in this wiring case. The separate real SessionDB compaction test does not make these two cases a combined atomic commit/prompt proof. Neither path establishes model compression quality, per-token reload or permanent freezing until a new session.

### History search, source identity and output budgets

- `test_real_fts_english_chinese_and_supported_short_cjk_fallback` observes actual English FTS5, Chinese trigram and short-CJK canonical LIKE-scan routing, then verifies the native tool returns the stored message ID and source. This is a fixed synthetic query set, not a general linguistic quality benchmark or a test of every missing-index recovery mode.
- `test_discovery_browse_source_filters_are_not_acl` shows CLI and cron results, with cron ranked after interactive content. Kanban, subagent and tool sessions are hidden from discovery/browse but remain directly readable by ID. `test_tool_role_uses_supported_canonical_fallback` verifies explicit tool-role search; default discovery does not return that tool body.
- `test_read_scroll_discovery_bounds_and_attribution` verifies read head-20/tail-10 selection and 2,000-character content truncation; discovery messages and bookends have 4,000/1,200-character limits. Truncation appends an ellipsis. **Scroll only bounds the window to 20 on each side, at most 41 messages; individual scroll content is not capped.** The test retains more than 6,000 characters per message as a counterexample. Never treat native scroll as a safe aggregate content budget without a separate bound.
- `test_browse_and_discovery_limit_clamps` checks result limits clamp to 1–10. Source/session/message/model attribution is checked against actual synthetic rows, not generated summaries.
- `test_compaction_archives_are_discoverable_not_active_context` distinguishes archived originals from active summary context; discovery and anchored scroll can retrieve old evidence. `test_archived_session_is_not_deleted_or_an_access_boundary` separately proves session archival is neither deletion nor read denial.
- `test_explicit_other_profile_reads_are_readonly_and_bare_id_does_not_fan_out` verifies explicit `profile=` and `profile/id` reads, read-only database access and unchanged foreign database bytes. A bare ID does not scan other profiles. These are native routing semantics, not permission to access another profile.

- `test_rewind_is_hidden_from_discovery_and_live_scroll_is_rejected` distinguishes rewind from erasure: default discovery/live messages hide the rewound row, while explicit inactive search retains it. Live-context scroll is refused, but explicit historical scroll outside that current-lineage guard can still read the retained row.

### Lifecycle and constructor wiring

`test_public_manager_serializes_sync_end_switch_and_reverse_shutdown` checks FIFO lifecycle delivery, reverse shutdown and error containment; `test_public_session_switch_forwards_branch_rewind_and_ignores_empty_id` checks switch arguments. Combined with the existing asynchronous failure test, this distinguishes callback delivery from durable write success.

`test_actual_turn_sync_boundary_skips_interrupted_provider_writes_and_prefetch` invokes the actual `AIAgent._sync_external_memory_for_turn` consumer on minimal state with a real manager/executor and synthetic recording provider. An interrupted turn submits neither sync nor queued prefetch; the completed control submits sync then prefetch and preserves the supplied session, transcript and author fields. This is consumer-boundary evidence, not a full agent/model run or authentication of those author fields.

The cron and delegation tests execute actual native construction paths and capture constructor arguments at a synthetic agent boundary. Cron retains memory but disables background review. Ordinary delegation skips memory; required-checkpoint delegation loads memory with `memory_agent_context="subagent"`. These tests do not construct a live model client, execute a scheduled occurrence or prove provider writes are safe in nonprimary contexts. Existing product-provider tests separately refuse recall outside the supported primary/local scope.

## Source and authorization limits

Native `session_search` can explicitly read another local profile. That feature is not permission for the personal agent to widen its own retrieval scope. A native session ID, source label, UID or returned content does not establish a verified remote owner or authorize subsequent effects. Project recall continues to enforce its narrower profile/session/configuration boundaries.

The host's search indexes and the project's local-record FTS index are different systems. Passing local memory search tests does not establish native transcript-search behavior or general Chinese semantic recall. Capacity limits and truncated views must not be described as complete evidence coverage.

The checkpoint evidence in [43](43-native-checkpoint-boundary.md) remains decisive: source references require exact reconciliation and a host-owned coverage/retention relationship with the compression commit fence. A v2 capability flag, successful callback string, valid UID or drained queue supplies none of those guarantees by itself. This package does not upgrade the project provider to v2 or silently archive raw transcripts elsewhere.

## Verification and remaining gates

All scenarios use synthetic content and temporary stores; no real provider request, credential, listener, remote write or installed schedule is required. The new tests and existing provider/checkpoint contracts must run through the repository's pinned-host check workflow. Lint, type, unit and bilingual documentation checks remain separate checks, and exact totals are recorded with executed results rather than copied from historical runs.

Focused local runs passed 37 new cases on each of SQLite `3.53.1` and `3.46.1`: 12 admission, 10 wiring, 6 builtin and 9 search cases. Both environments used Python `3.14.9` and the canonical native runner. These are focused results, not aggregate unit/contract counts or CI acceptance.

E0.9 can be accepted as bounded native-contract verification only after its tested/unsupported matrix and exact-pin results are reviewed. E2.8 automatic capture, durable receipts and source-bound checkpoint integration remain open, as do remote identity, unsupported isolation modes and deployed/provider acceptance. The E0 epic, M0 milestone and a production release are not implied by this slice.
