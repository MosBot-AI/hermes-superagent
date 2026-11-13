# 08. Roadmap, Project Breakdown, and Acceptance

English | [简体中文](08-roadmap-and-acceptance-zh.md)

Current E2.7 checkpoint: [original local backend scope accepted](81-local-memory-acceptance.md) at main `15d690a`, with independent source/test review and successful exact-main CI. SQLite/FTS/projection/edit proposals/exact source suppression are implemented. #44 closes after the acceptance reconciliation is merged and verified; E2.6/E2.8/E2.9 and deployment remain separate. Historical precursor-only statements below retain their original scope.

## 1. Planning Principles

This is an implementation plan, not a completion report. Items that have not passed code, testing, deployment, and user acceptance must not be marked Done. See [12](12-foundation-progress.md) for the current E0.1/E0.2/E0.5 foundation-slice progress; this does not mean E0/M0 or the entire personal agent is complete.

Complete a safe, reliable vertical slice first, then add connectors, entry points, and proactivity. Advance phases according to dependencies and gates; do not invent timelines when team size and availability are unknown. GitHub Projects manages engineering delivery; runtime Hermes Projects/Kanban manages the user's affairs.

## 2. Milestones

| Milestone | Deliverable | Entry criteria | Exit gate |
|---|---|---|---|
| M0 Design and contracts | Pinned baseline, runnable synthetic tests, minimal public API mapping, write-path coverage inventory | This design is complete | Gaps and adaptation paths are clear; no reliance on imaginary APIs; uncovered write capability sets are disabled by default |
| M1 Profile-first local MVP | Trusted single-user local gateway/profile; durable tasks, project labels and native conversation entry, without a Bot | Applicable E0.1/E0.2/E0.4/E0.5, local E2.1/E2.2 slices and E6.8; E6.9 is next | Local restart, duplicate, revision, invalid-input and host-admission tests pass; unverified scope disclosed; no remote/outbound capability enabled |
| M2 Personal affairs | Facts/commitments, native multitasking, proactive observation, and reliable notifications; optional E9 routing shadow mode | M1; E9 shadow also requires a trusted-constraint baseline | Real-world scenarios work end to end; information correction and forgetting work; shadow mode does not change the actual model |
| M3 Connections and voice | Minimal read/write MCP set, mobile voice messages, optional real-time voice validation and E9 bounded model routing | M2 + connector risk review; routing also requires E9.5/E9.6 gates | Confirmation of critical voice fields, identity, and costs are controlled; routing quality/privacy/budget gates pass |
| M4 Release hardening | Recovery, backup, upgrades, rollback, security evaluations, and documentation | Core scenarios are complete | All release gates pass, with no unresolved P0 issues |

Original profile-first deterministic local M1 acceptance is recorded at the fixed checkpoint in [90](90-local-m1-acceptance.md), with exact-source Foundation and live Gateway evidence. This does not accept E6.9 natural-language use, full E4 reminders, remote/shared REST, or the entire Super Agent goal. The entry and exit criteria above are unchanged.

## 3. Epics and Work Packages

### E0. Verify Upstream Compatibility Contracts (P0, M0)

- E0.1: Pin the supported Hermes version/SHA; establish a source capability matrix and license/notice records.
- E0.2: Minimal native plugin registration, config_schema, plugin_data_dir, and tool/hook/ctx contract tests.
- E0.3: Verify public operations for Project/Kanban/cron creation, querying, cancellation, and receipts; record gaps as upstream seams rather than writing directly to the host DB.
- E0.4: Test pre_tool_call callback and dispatcher exceptions and middleware fallback; cover native tools, raw MCP, shell/browser, execute_code/RPC, batch calls, and workers. Disable write capability sets not protected by the action gate by default, or degrade them to read-only. Specifically verify read-only degradation when troubleshooting safe mode skips hooks, and that ordinary managed workers' frozen config does not prevent reading the current persistent policy revision.
- E0.5: Build offline synthetic source/connector fixtures so tests do not depend on real personal accounts.
- E0.6: Verify client transport contracts at the pinned host: dashboard API registration, trusted principal/profile propagation, canonical session RPCs, auth/isolation/file boundaries, and explicit unsupported modes. Depends on E0.1/E0.2 and uses E0.4 findings; this is not a claim that full write coverage is complete. See [14](14-client-api-contracts.md).

- E0.7 Verify Primary Bot Contracts (M0, In Progress) depends on E0.1/E0.2 and uses E0.4 findings. The [supported adapter map](15-primary-bot-binding.md#supported-adapter-status) links current-pin evidence for canonical discovery, Desktop routes, local Bot Mode refusal and retry, the saved Webapp token fallback, profile lifecycle, backup and restore, plugin state, subagent correlation, and Bot and cron delivery. The [retained native route](15-primary-bot-binding.md#current-pin-retained-native-profile-route) and [saved Webapp Desktop route](15-primary-bot-binding.md#current-pin-desktop-profile-retirement) cover live retirement and same-name hot serve on the same installation. The [native profile rename case](15-primary-bot-binding.md#current-pin-native-profile-rename) records a live rename that preserves the canonical pointer and stored session while authorized continuation fails closed. The [copied-install cases](15-primary-bot-binding.md#current-pin-copied-install-ambiguity) show that live Desktop inventory can combine two reachable installations whose scoped transcripts differ. The [native restore rotation case](15-primary-bot-binding.md#current-pin-restored-webapp-credential-rotation) covers target-only replacement of a copied Webapp credential over private Unix control while Webapp is off. The [serving Webapp sign-out case](15-primary-bot-binding.md#current-pin-serving-webapp-sign-out) covers revocation on the selected running Gateway, retained native and peer access, and Basic browser re-authentication to reopen the original chat. The [compressed history cases](15-primary-bot-binding.md#current-pin-compressed-history-adoption) cover named-profile native adoption and scoped opening of that history in local Linux Bot Mode. The [named managed worker case](15-primary-bot-binding.md#current-pin-native-managed-workerchannel) correlates a native child process, its admission and durable receipts on the ordinary local Gateway path. The [managed worker restart case](15-primary-bot-binding.md#current-pin-managed-worker-restart-reconciliation) covers the unknown admission after Gateway loss, explicit resolution and one queued follower completing on the successor. The [review-only saved-token proposal](../experiments/bot-webapp-canonical/README.md) has separate evidence. Remaining work includes upstream adoption and clean-pin revalidation of that fallback, packaged Desktop and other transport modes, supported LOCAL receipt migration after rename and other live profile transitions, authenticated installation continuity and owner-authorized recovery across copies and restores, trusted caller provenance, other managed worker modes, owner-bound worker grants and revocation, and broader author and receipt reconciliation. HTTP modes additionally require E0.6.

- E0.8 Verify Voice Provider Contracts (M0, offline verification) depends on E0.1/E0.2 and uses E0.4/E0.7 findings where applicable. The [current-pin compatibility inventory](voice-compatibility-inventory.md) and [dated protocol comparison](voice-provider-protocol-comparison.md) record the acceptance evidence and outstanding release gates by mode.

- E0.9: Verify Memory Provider Contracts (M0, Done; bounded native-contract verification): depends on E0.1/E0.2/E0.5. Verify actual native loading/lifecycle/single-external-provider, profile/cron/worker context, compression checkpoint and source-reference contracts, including unsupported isolation modes. This gate applies when personal memory is enabled; it does not block the existing local task loop. See [30](30-pluggable-memory-contracts.md).

Acceptance: Every reuse point has a behavioral test or an explicit blocker; the initial `requires_hermes` range comes from tests, not arbitrary version numbers. Produce a per-tool, per-path enforcement inventory. A capability set must not be enabled while it has unknown or bypassable write paths; prompt constraints cannot substitute for enforcement.

Current E0.4 progress: the [finite boundary ledger](13-enforcement-contracts.md#31-finite-acceptance-ledger) maps all 11 release paths and 52 unique contracts to exact pinned native entries, executable assertions, independent effect oracles and explicit limits. Production-package exposure, concurrent/alternate execution and delegation boundaries form an acceptance candidate, contingent on independent review, final ledger merge and main CI verification recorded on Issue #12. That scoped verification does not complete E0/M0 or E1 authorization, enable controlled writes, or establish host-wide read-only behavior. All runtime release gates remain blocked; production authorization, durable orchestration and external-effect outcomes remain downstream.

E0.6 is an independent optional-client contract lane. It does not gate the profile-first local M0/M1 exit; existing general E0 dependencies mean the applicable E0.1–E0.5 gates unless E0.6, E0.7, E0.8 or E0.9 is explicitly named. E0.7/E1.6/E3.6 are conditional gates for an enabled Primary Bot capability; they do not silently become prerequisites for the local inbox or an unbound local baseline.

### E1. Establish Identity, Authorization, and Audit (P0, M1)

Depends on E0.2/E0.4.

- E1.1: Owner and verified channel binding; classify group/third-party/forwarded/bot identities.
- E1.2: ActionIntent, grant, and approval schemas and revisions; bind approval to payload/target/expiry.
- E1.3: Operation-level checks in domain handlers and native approval adaptation; prohibit bypass through alternate paths after denial.
- E1.4: Soft pause, hard revoke, and emergency stop; establish transactional linearization points for authorization admission and revocation, cancel effects not yet admitted, and preserve truthful status and best-effort cancellation semantics for in-flight requests already admitted/sent.
- E1.5: Redacted audit, sensitive-data classification, and minimal credential exposure.
- E1.6: Bind Primary Bot (optional future, Backlog): depends on E0.7, E1.1–E1.5 and E2.1. Implement owner-confirmed enrollment/recovery, one active binding in its authority, revision/epoch fences, audit and roles. Binding alone enables no controlled writes.

Acceptance: All write operations in release scope are covered; spoofed identities, stale approvals, payload changes after approval, and policy failures cause no unauthorized side effects. Revocation race tests cover “revocation commits first/admission commits first but nothing has been sent/the remote has accepted but local outcome is unknown/the next action after revocation.” Assert against the transactional ordering of admission and revocation; do not promise to retract already authorized remote requests. A denied intent cannot be revived; a new instruction requires a new intent and fresh authorization.

Current preparatory implementation: [owner entry and read authorization](18-owner-entry-and-read-authorization.md) provides a pure internal evaluator and always-denying diagnostics. E0.7 source/IPC tests establish the missing public receiving-Bot identity. There is no production verified-context issuer, owner enrollment, live grant/policy authority or verified remote-owner private read access. The [pending enrollment/policy core](26-pending-enrollment-policy.md) persists prospective mappings and read scopes with CAS, terminal revoke and audit, but is unwired and cannot activate them. E0.7/E1 gates remain incomplete; binding is not enabled.

The [host-context experiment](23-host-command-context-experiment.md) packages a review-only prototype for E0.7. Source authenticity, current owner/policy admission and supported public IPC contracts remain separate gates. The local command-only repair has 87 guarded passing tests, but the historical nine environment-blocked tests remain unresolved; that experiment enables no Primary Bot or verified remote-owner private reads.

The [fenced read-admission core](27-fenced-read-admission.md) adds an internal default-denied coordinator and actual policy/revoke transaction guard, with synthetic authority/resource fixtures. This is partial E1.3/E1.4 preparation, not production identity, activation, task adoption or complete read audit.

### E2. Establish the Personal Domain and Memory (P0/P1, M1–M3)

Dependencies follow the trust mode. Explicit trusted-profile local memory reuses the profile-first deployment contract and local E1.5 audit/data-classification/secret-reference rules, not fabricated owner identity. Verified remote-owner exposure additionally requires applicable E1.1–E1.4 and explicit resource adoption. HTTP, Primary Bot and voice gates apply only to their selected modes.

- E2.1: SQLite schema/migrations, projects/commitments/facts/sources, and revision updates. Memory records/events/receipts distinguish trusted-profile and verified-owner namespaces; native tasks and transcripts retain authority.
- E2.2: Scope-based retrieval, explicit facts/inferences/conflicts, and only bounded summaries in native memory. Authorize before external queries and validate current revisions/deletions/sources before bounded context assembly; evaluate token limits and Chinese retrieval.
- E2.3: Correction, expiration, forgetting, export, and backup/restore tombstones. Preserve deletion precedence over re-extraction and require projection/index/provider purge receipts, retention-safe event payloads and restore suppression.
- E2.4: Person/project disambiguation and task-source associations; do not treat third-party reports as owner instructions. Distinguish semantic/episodic/procedural/task references, temporal conflicts and Chinese names/aliases; similarity is not identity proof.
- E2.5: Evaluate optional memory provider adaptation; remain compatible with the user's existing single provider rather than forcing replacement. Evaluate replaceable project MemoryBackend adapters and the optional native MemoryProvider bridge separately; users may supply a conforming adapter, with explicit selection/migration.
- E2.6: Define Pluggable Memory Contracts (M1, In Progress; narrow local precursor): depends on E0.9, local E1.5 audit/data-classification/secret-reference contracts and applicable local E2.1/E2.2 contracts. Define the versioned service/backend SDK, records/events/receipts, deletion semantics and conformance fixtures.
- E2.7: Build Local Memory Backend (M2, In Progress; explicit-record precursor): depends on E2.6, local E2.1/E2.2 and applicable E8.1/E8.2 harness. Implement canonical SQLite records/events/FTS, generated Markdown, bounded retrieval, correction/forgetting and explicit local commands.
- E2.8: Integrate Native Memory Lifecycle (M2, In Progress: recall and reviewed candidates): depends on E0.9/E2.6/E2.7 and applicable E6.8/E6.9 entry contracts. Add the optional single-slot bridge, consented source-bound candidates/recall and durable lifecycle/checkpoint handling with budgets. The bridge is not required for explicit local memory tools.
- E2.9: Validate Memory Migration and Recall (M3, Backlog): depends on E2.7/E2.8 and E8.1/E8.2/E8.3 harness. Validate adapter conformance, fenced export/cutover/restore/delete races and Chinese/long-horizon recall.

[43](43-native-checkpoint-boundary.md) adds pinned-host evidence gates and unwired candidate preparation; full checkpointing still needs source-coverage handoff bound to native commit, not UID presence or a successful return alone.

E0.9 is Done with [Issue #42 completion evidence](https://github.com/MosBot-AI/hermes-superagent/issues/42#issuecomment-6752608209), merged PR #83, successful [main CI](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42705321028) and the pinned native-contract matrix in [76](76-native-memory-contracts.md); E2.9 remains Backlog. This completes that verification gate, not E0, E2.8 or production deployment. E2.8 now has the optional read-only native recall slice in [41](41-native-memory-recall.md); ingestion and durable conversation checkpointing remain open. E2.6/E2.7 are In Progress only for the narrow explicit-record precursor below. [30](30-pluggable-memory-contracts.md) is the complete design, not an implementation report. Existing E2.1–E2.5 retain their checklist IDs and local-task evidence; no duplicate work packages are created.

Acceptance: Long-term facts have provenance or inference labels; they are not readable across profiles/group chats; retrieval tests after correction and deletion pass.

Current E2.1 precursor: [the opt-in local CLI task inbox](16-local-task-inbox.md) implements plugin-owned SQLite, atomic receipts, revision checks and explicit local completion/cancellation. It is not the full domain Task/memory store, verified owner identity or native dispatch. Remote/Bot/HTTP exposure still requires the applicable E1 gates. E6.8 permits only explicit local commands under the trusted single-user deployment contract; it does not complete E1 or the full E2.1.

The local follow-on adds [due dates and agenda](17-local-task-agenda.md), including atomic schema upgrades and legacy receipt compatibility tests. It advances a narrow local E2.1/E8.3 scope; it does not create reminders or complete E4 or the E1 gates.

Current E2.2 precursor: [local task search](22-local-task-search.md) retrieves literal title/details matches through the opt-in local CLI, reused by the E6.8 local conversation commands. It preserves the current schema and receipts; it is not agent memory, semantic retrieval or owner-authorized channel access. E1 and full E2.2 gates remain open.

A further local E2.1/E2.2 precursor adds [project groups](24-local-project-groups.md): labels, exact filtering, counts and schema-v3 compatibility. Labels are not stable domain/native project IDs or permission keys. This does not complete E2 or E3.1 and does not relax their E1 dependencies.

Current local memory precursor: [31](31-explicit-local-memory.md) implements opt-in native operator commands and a bounded SQLite backend behind an internal interface. It reuses the verified E6.8 command entry and local storage contracts, without enabling the provider modes still gated by E0.9. No automatic retrieval/ingestion, complete SDK, FTS/Markdown projections, consistent migration or native bridge is implemented; existing task model tools do not gain memory access. The separately enabled [memory model-tool follow-on](32-session-scoped-memory-tools.md) adds independent session activation and model-origin provenance; real-provider natural-language acceptance is still pending. These advance but do not complete E2.6/E2.7 or the full memory gates.

The [local task progress follow-on](42-local-task-progress.md) adds explicitly recorded working/waiting/blocker state, notes, revision-safe retries and active review filters. Task schema v4 preserves old receipts/events through an atomic upgrade. This is local state, not native worker liveness or E3.2/E3.5 completion.

[Session-scoped automatic recall](49-session-memory-recall.md) now connects the production standalone plugin to the supported native turn hook after separate session selection. It performs fresh bounded read-only retrieval without replacing the native provider or adding a model call. This advances the read side of E2.8; automatic extraction, real-model usefulness and durable conversation checkpoints remain open.

### E3. Connect Native Projects and Tasks (P0/P1, M1–M2)

Depends on E0.3, E1.1–E1.5, and E2.1.

- E3.1: Connect domain Projects to native Projects/boards, preserving the distinction between business context and working directories.
- E3.2: Task ↔ Kanban card/run mapping, acceptance contracts, dependencies, blockers, and review.
- E3.3: Public lifecycle API for temporary subagents, minimal context and toolsets, and parent-task aggregation.
- E3.4: Prioritize owner follow-ups, thread-to-task associations, context-only, and handback.
- E3.5: Restart reconciliation, unknown outcomes, completion evidence, and cancellation states.
- E3.6: Reconcile Primary Bot Sessions (conditional Bot-bound gate, M2 extensions; Backlog): depends on E1.6, E3.2/E3.5 and E4.3/E4.4. Resolve canonical roots/tips through verified adapters, correlate worker handoffs, and reconcile delivery/native receipts. No parallel transcript writer or automatic cross-host takeover.

Acceptance: Deduplicate one input into one task; do not mix context across projects; a short subtask exiting must not falsely report the whole task complete; long-running tasks remain queryable across restarts without duplicate dispatch.

[Project task dependencies](51-project-task-dependencies.md) add a profile-first E2/E6 precursor for the dependency/review part of E3.2: explicit same-project edges, atomic start/completion gates, a ready queue and coherent focus/review snapshots. This is not native Project/Kanban mapping, worker dispatch, or E3.5 cross-store reconciliation. Those remain open; the optional parked native-card handoff still needs its own durable uncertain-outcome handling.

### E4. Implement Reminders and Reliable Delivery (P0/P1, M1–M2)

Depends on E0.3, E1.1–E1.5, and E2.1.

- E4.1: One-time/recurring reminders and IANA timezones, with explicit DST, missed-window, and stopping semantics.
- E4.2: Reuse cron/heartbeat; record native job/run/occurrence references and domain objectives.
- E4.3: Plugin-owned effect/outbox/receipt records, with a clearly designated sole owner for native delivery.
- E4.4: Reconcile unknown outcomes, deduplicate, handle invalid routes and dead letters, and provide recovery entry points.
- E4.5: Quiet hours, notification coalescing, change detection, and separate attention/compute budgets.

Acceptance: Duplicate triggers, process interruption, send timeouts, restarts, and cancellation do not cause blind duplicate outbound sends; no change may remain silent; accepted is not presented as delivered.

Native E0.3/E4.2 precursor: [the planning blueprint](25-native-planning-blueprint.md) registers an optional template in Hermes’s existing catalog. It does not create or manage jobs, read the local inbox, or implement domain authorization/outbox/reconciliation. User-created native jobs outlive plugin removal; E4 remains incomplete and is separate from the deterministic local M1 acceptance.

### E5. Govern MCP and Plugins (P1, M2–M3)

Depends on E1/E4.3.

- E5.1: Connector capability registry: accounts, read/write operations, versioned input/output schemas, data classes, costs, actual idempotency retention, receipt levels, reconciliation/cancellation capabilities, and auth health.
- E5.2: One read-only connector and one controlled-write connector vertical slice, with typed prepare/execute/reconcile/cancel contracts, server-side semantic validation, per-effect admission, stable effect keys, and partial/unknown-outcome tests. Preparation with a remote side effect is itself a controlled operation.
- E5.3: Minimal toolsets, MCP trust/filters/OAuth, and disconnection/revocation handling.
- E5.4: Plugin sources, pinned versions, dependency updates, consent for expanded access, and a supply-chain inventory.
- E5.5: Persistent budgets and connector receipts; do not substitute native session estimates for billing records.

Acceptance: False read-only claims, incorrect scope, revoked credentials, and malicious tool results cannot produce unauthorized behavior; new connectors must complete risk and recovery contracts before writes are enabled. E5.1/E5.2 remain checklists within the existing Epic, not new IDs. Contract design can proceed from E0.6/E1.2; write enablement requires E1.3/E1.4, E4.3/E4.4 and the connector’s E0.4 path coverage. Native OAuth remains the credential owner. See [14](14-client-api-contracts.md) for concrete connector inputs, outputs and receipts.

### E6. Enable Local and Optional Mobile Entry Points (P1, M1–M3)

E6.1–E6.7 retain their remote/mobile dependencies on E1.1/E3/E4 as applicable. E6.8/E6.9 are the separate local lane below.

- E6.1: One primary mobile messaging channel, identity binding, text/attachments, and task/reminder routing.
- E6.2: Desktop/mobile continuity and short candidate lists for disambiguation; idempotency for duplicate messages and approval buttons. For a selected Primary Bot, E6.1/E6.2 also verify receiving-transport/runtime-profile bindings and shared-domain, separate-transcript continuity; a shared profile does not merge chats or prove bot-account isolation.
- E6.3: Personal overview, preferably reusing native dashboard/plugin UI; validate mobile layout.
- E6.4: TLS/auth/session revocation, attachment access, small-screen, and poor-network tests.
- E6.5: Build Domain API and Change Feed (M2, optional, Backlog): versioned typed REST over domain services, transactional dedup/outbox/change feed, authorized consistent snapshot and polling overview. Depends on E0.6, E1.1–E1.5, E2.1, E3.2/E3.5 and E4.2–E4.4; only individually verified adapters may be enabled.
- E6.6: Validate Client Recovery Flows (M3, optional, Backlog): multi-device, offline, replay, expiry, ACL, isolation and cancellation scenarios. Depends on E6.5, E6.2/E6.4 and the E8.1/E8.2 harness for these paths, not all of E8/M4. Artifacts also require E0.6 file-contract evidence.
- E6.7: Validate Native Mobile Sign-in (M3, optional, Blocked): depends on E0.6 auth findings, E1.1/E1.4/E1.5 and E6.4. The pinned native flow accepts only loopback callbacks; a supported target-phone callback and device-revocation contract must be proven before physical-device certification. Do not create a second plugin auth service.
- E6.8: Enable Local Task Conversations (M1, In progress): depends on E0.1/E0.2, applicable E0.4/E0.5 and local E2.1/E2.2 schema-v3 TaskStore slices. Explicitly enable deterministic `/personal-tasks` add/list/search/projects/show/update/done/cancel/agenda, reusing validation, revisions and receipts; projects remain labels, not native Projects.
- E6.9: Add Session-scoped Task Tools (M1, In progress): depends on E6.8 and tested host session-scoped tool context, admission and permission boundaries. Verify source/session binding, invalid arguments, replay and unsupported paths before adding bounded model task tools; no automatic enablement or production verified-owner claims. The opt-in native in-process tool slice is implemented; real-provider natural-language acceptance and cross-process support are still pending. See [29](29-session-scoped-task-tools.md).

Acceptance: Complete “create project → reminder → inspect/cancel → approve controlled action” on the target physical phone; old devices and forwarded approvals cannot perform operations. This is the optional mobile lane, not the local M1 exit; it does not depend on a custom app. Optional browser/PWA delivery can precede native-mobile certification. New client work remains unimplemented; detailed contracts and exact blockers are in [14](14-client-api-contracts.md).

Local E6.8/E6.9 supports only a trusted single-user local gateway/profile deployment. Normal native CLI/TUI sessions are gateway-backed with LOCAL sources; host SessionAuthority checks owner/operator session read/control, exact registered live source and admission. All already host-authorized owner/operator controllers share local data access. A profile is a storage/configuration partition, not human identity; LOCAL does not prove physical locality. Add no listener, authentication service or remote connector; exposed, multiuser and remote-messaging deployments are unsupported. Pending enrollment and fenced read-admission cores remain unwired for a future verified remote-owner lane, not prerequisites for explicit local commands.

### E7. Preserve Voice Task Continuity (P1/P2, M2–M3)

Production modes depend on applicable native/client identity contracts, E1.3 and E6.4 safety/device tests. E0.6/E6.5/E6.7 apply only when their optional HTTP or native-mobile modes are enabled. Synthetic adapter contracts/design can proceed first; the full optional phone API is not a prerequisite for all voice work.

- E7.1: Reuse STT/TTS for mobile voice messages, supporting Chinese and time/name corrections.
- E7.2: Voice action intents and visible confirmation; distinguish barge-in, stopping playback, and cancelling execution.
- E7.3: Audio privacy and retention, host relay/short-lived credentials, and visible provider costs.
- E7.4: Validate real-time voice feasibility; expand release only if device and cost criteria are met.
- E7.5: Define Unified Voice Session Contract (M2, M1 design prework; In progress, synthetic precursor only): depends on E0.8, E1.1/E1.2/E1.4/E1.5; optional HTTP facade also needs E0.6. Define profiles/capabilities, audio/control schemas, leases, turn/author ownership, budget/privacy and synthetic reference adapters.
- E7.6: Implement Local and Online Voice Adapters (M3, Backlog): depends on E7.5 and E7.1–E7.3; enabled actions additionally require E1.3 and relevant E0.4 coverage. Implement one local/mixed pipeline and one explicitly selected online realtime adapter without generalizing protocol compatibility.
- E7.7: Validate Duplex Recovery and Voice Quality (M3, Backlog): depends on E7.6, E6.4 and E8.1/E8.2 harness; linked task/effect recovery also needs E3.5/E4.4. Validate devices, latency, accuracy, barge-in, playback reconciliation, reconnect, budgets and privacy.

[19](19-unified-voice-provider-contracts.md) unifies E7.1–E7.4 configuration and safety semantics while retaining separate voice-message MVP and realtime-duplex gates. The [offline simulator](20-voice-contract-simulator.md) implements a narrow synthetic precursor and public ASR/TTS contract probes. E7.5 remains at the synthetic precursor stage. Production interfaces, online transmission and Primary Bot authority have separate enablement gates.

Acceptance: Misrecognition does not cause high-impact outbound actions; the same task can switch between text and voice; network loss or stopping voice does not falsely report cancellation of an external action. Real-time voice is a separate gate and does not block a completed voice-message MVP.

The [native voice IPC experiment](21-native-voice-ipc-experiment.md) preserves a separately tested host adaptation as a review artifact for a historical pin. The current compatibility inventory uses the official unpatched pin.

### E8. Complete Operations, Evaluation, and Release (P0/P1, Across M0–M4)

Dependencies are integrated as each capability arrives; cover all of them before release.

- E8.1: Correlation IDs, redacted logs, and health/budget/unknown-outcome dashboards.
- E8.2: Crash injection, concurrency, and provider/MCP/channel failure matrices.
- E8.3: Backup/restore, migrations, upgrade compatibility, rollback, and data retention.
- E8.4: Fixed scenario suites, observe-mode evaluation, false-positive and cost reports.
- E8.5: Installation, configuration, deactivation, permissions, privacy, and troubleshooting documentation.

For Primary Bot releases, extend E8.2 with identity/epoch/receipt and clone/restore fault cases, E8.3 with source-fenced owner-directed migration, and E8.5 with selection/pause/recovery procedures. Concurrent cloned authorities without an external fence remain unsupported, not a passing recovery scenario.

Acceptance: Run the full set of gates on the same release SHA; disclose skipped/failed items and do not present static checks as runtime verification.

For enabled memory, extend E8.1 with redacted source coverage, lag, tokens/costs and pending commit/purge metrics; E8.2 with checkpoint, unknown-commit and delayed-publication-after-forgetting races; E8.3 with source-fenced migration, inactive import, tombstone-preserving rollback and stale-generation invalidation; E8.5 with adapter authoring, selection, trust/retention and recovery guidance. These extend existing Epic checklists, not new IDs or completion claims.

### E9. Design and Validate the Worker Routing Plugin (P1, M0–M3)

Detailed design: [Worker Model and Reasoning-Effort Routing Plugin](11-worker-model-routing.md). Reuse the Hermes delegation backend to choose per task from the provider/model/effort set configured and permitted by the user, without changing the main agent model or requiring a gateway deployment. E9.1 is in progress with partial native contract evidence and an [offline constraint fixture precursor](35-offline-worker-routing.md). The [saved-config CLI inspection](38-routing-readiness-inspection.md) adds identifier-free native diagnostics without effective-route qualification. E9.2–E9.6 runtime work remains Backlog; no live shadow or automatic backend is enabled.

| ID | English work package title | Primary milestone | Deliverable and dependencies |
|---|---|---|---|
| E9.1 | Verify Hermes Routing Contracts | M0 | Depends on E0; plugin registration/route_task/schema pin, model capability inventory, uncovered paths, and compatibility tests |
| E9.2 | Define Trusted Route Context and Constraints | M1 | Depends on E9.1, the identity/grant/revocation/data-scope contracts in E1.1/E1.2/E1.4/E1.5, and the task/attempt identifier contract in E3.2; does not wait for all of E3 |
| E9.3 | Build Shadow Routing and Audit | M2 | Depends on E9.1/E9.2; advisory selection that does not change the actual route, redacted audit, and baseline evaluation |
| E9.4 | Enable Bounded Worker Routing | M3 | Depends on E9.3 and the E9.5/E9.6 enablement gates; bounded tasks, attempt/deadline/cost limits, and controlled fallback |
| E9.5 | Validate Effort and Fallback Policies | M2 | Depends on E9.1/E9.2; provider wire mappings, rejection of unknown capabilities, fallback privacy/permissions, cancellation, and no duplicate side effects; retest in M3 |
| E9.6 | Integrate Budget Admission and Release Gates | M3 | Depends on E9.2, admission/revocation in E1.3/E1.4, attempt/reconciliation contracts in E3.2/E3.5, audit metering in E8.1, and failure fixtures in E8.2; complete budget and routing release gates without waiting for all of E8/M4 |

Acceptance: Select only permitted candidates; do not override exact user pins; classifiers/reviewers/fallbacks are also subject to privacy and budget constraints; distinguish requested effort from effective wire effort and explicitly label unknowns. Without trusted context/budget enforcement, remain in shadow mode or reject the relevant automatic routing. Shadow results must not be presented as actual success rates for a new model; enablement requires independent replay/task-validation evidence. Failure to pass safety and cost limits cannot be excused by “cost optimization.”

## 4. Sequence for the First Usable Vertical Slice

Local-first sequence: applicable E0.1/E0.2/E0.4/E0.5 → local E2.1/E2.2 TaskStore slices → E6.8 deterministic conversation commands → local persistence, admission, failure, recovery and configuration acceptance in E8.1/E8.2/E8.3/E8.5 → M1 local MVP. Then add session-scoped model task tools under E6.9; command entry is not natural-language task management until separately verified.

The optional remote/mobile lane still requires E1.1–E1.5 → full E2.1 → E3.1/E3.2/E3.5 + E4.1–E4.4 → E6.1 and corresponding crash/revoke/delivery acceptance. Enabling Bot binding also requires E0.7 → E1.6 → E3.6. Custom clients retain independent optional gates; local commands activate none of these capabilities.

Full E2.1 still requires E1.5 data classification and audit conventions. Completing the local MVP does not complete broad E1, remote revocation, dispatch or E3.5/E4.4 reconciliation; each capability must pass its own gates before enablement. Preserve existing research and blocker records rather than marking them Done by redefining the local scope.

E9 is an optional enhancement; it must not turn the first version's fixed-model delegation into a system dependent on a new gateway. Its independent sequence is E9.1 → E9.2 → E9.3 shadow; E9.5/E9.6 may be validated in parallel, and E9.4 is enabled only after all gates pass. Do not launch automatic switching first and add trusted scope and cost controls later.

## 5. Suggested GitHub Projects Configuration

- Main Project: Hermes Personal Agent, describing objectives, the design baseline, and unimplemented status.
- Status: Backlog, Ready, In Progress, Blocked, In Review, Done. Blocked must include a reason and next step; do not label waiting for confirmation as In Progress.
- Fields: Epic (E0–E9), Milestone (M0–M4), Priority (P0/P1/P2), Area, Risk, Effort, Dependencies, Acceptance evidence. E9 Epic/work package titles use English; the documentation body continues in Chinese in the Chinese version.
- Views: Roadmap (Milestone), Execution (Status board), Security/Blockers, Mobile/Voice, Ready next.
- Create epics and independently acceptable work packages first; do not swamp the plan with hundreds of tiny tasks.
- Issue templates include outcome, scope/non-goals, dependencies, design links, acceptance, tests/security, and completion evidence. Close a parent epic only after all required work packages and acceptance checks are complete.

Project links, Issue numbers, and final fields must reflect actual creation results. If API/permission restrictions allow only Issues to be created, not a Project, explicitly record the discrepancy; do not present planning tables in docs as proof that a GitHub Project has been configured.

## 6. Proposed SLOs and Test Gates

These are targets to be measured, not commitments already achieved. Report separately using fixed devices, networks, and providers; do not use provider incidents to conceal local queueing problems.

| Metric | Initial target/gate | Measurement |
|---|---|---|
| Unauthorized side effects | 0 in the release test suite; any failure blocks release | Adversarial/fault injection |
| Duplicate inputs | The same idempotency key does not duplicate tasks/known outbound sends | Replay, concurrency, restart |
| Queueing of new user messages | No indefinite blocking by background work when the host is healthy; initially p95 < 2s to enter processing | Measure intake to turn admission, excluding model response |
| Reminder triggering | Initially p95 ≤ 60s scheduling lateness when host/channel are healthy | Record due, admitted, delivered; measure each segment |
| Memory quality | 100% source coverage; 0 cross-scope leaks in the test suite | Synthetic conflict/deletion/isolation cases |
| Recovery | Every crash point has a terminal state or visible unknown; no silent loss | Inject exit at every transaction/remote boundary |
| Voice | Measure first audible audio, transcription, and cancellation latency; set numeric targets after establishing device baselines | Chinese/noise/poor-network/interruption suite |
| Costs | Queryable per task and per day; no new automatic chargeable actions at the limit | Provider/MCP simulation and billing samples |

## 7. Definition of Done

Code review + corresponding design/ADR updates + unit/contract/integration tests + adversarial security cases + recovery tests + user-visible failure paths + compatibility version records + real acceptance evidence. For external systems, retain redactable receipts/readbacks rather than treating model prose as proof. State the reason and risk for every test not run.

The [bounded recall follow-on](36-bounded-memory-recall.md) adds explicit multi-keyword literal ranking and complete-record budgets over one current read snapshot. E2.7 remains In Progress; FTS and Markdown projections remain unimplemented. [41](41-native-memory-recall.md) later adds the limited E2.8 read-only native recall bridge.

[37](37-durable-memory-progress.md) adds local event-metadata change pages and durable consumer progress with atomic v3 migration. E2.7 remains In Progress; the cursor is not native transcript checkpoint coverage and does not complete E2.8.

[Explicit expiry](45-explicit-memory-expiry.md) adds UTC-bounded fresh recall eligibility and schema-v5 migration, not deletion or automatic ingestion. E2.7 remains In Progress; strict native checkpoint-v2, source reconciliation and native worker orchestration remain open. Time passage alone does not change revisions/events or certify checkpoint recall validity.

[Native task focus](46-native-task-focus.md) extends E6.9 with explicit session selection, fresh bounded context at turn start and actual host hook/API-message contracts. E6.9 remains In Progress: real-model natural-language acceptance, worker dispatch and complete MVP/release gates are not completed by this slice.

[Atomic project-plan capture](47-atomic-project-plans.md) advances the local E2.1/E6.9 workflow from one planned batch to durable tasks, project review and per-task focus. Pinned lifecycle/toolset contracts explain why the plugin still does not claim contained worker dispatch. E3.3/E3.5 and real-model acceptance remain incomplete.

[The task-to-worker proposal](48-task-worker-proposal.md) advances E3.3 feasibility through a review-only no-tool planning path and real host/consumer offline integration. Its dedicated no-redirect client, durable single-claim/draft receipts and scoped native operator workbench improve feasibility, but do not satisfy live provider acceptance, unknown-outcome reconciliation, budget control or general tool containment; E3.3/E3.5 stay incomplete.

[Reviewed candidate workflow](50-reviewed-memory-candidates.md) now implements a narrow E2.8 input-to-draft-to-operator-review path on supported hooks. Only explicit acceptance creates canonical memory; actual-model usefulness, durable transcript coverage and checkpoint-v2 remain open. Schema-v6 migration and lazy seven-day candidate expiry do not imply background deletion.

[Parked Kanban handoff](52-parked-kanban-handoff.md) adds explicit preview, single-use commit and bounded reconciliation into a shared native board. It does not complete worker dispatch, universal task mapping or live Kanban acceptance; those gates remain open.

[Native progress observation](53-native-progress-observation.md) closes a narrow explicit metadata readback loop for identity-bound parked cards. It does not close worker execution, universal task mapping or real-host live acceptance gates.

Added [saved native attention review](54-saved-native-attention.md): local snapshots only, overlapping buckets with unique counts, no live-board read or completion change.

[Gated task planning worker](55-gated-plan-worker.md): Production-package integration is default-off and requires the exact reviewed host contract plus current consent; not installed or live-accepted.

[Explicit atomic plan dependencies](56-atomic-plan-dependencies.md): Explicit one-based batch references save tasks and edges together, without automatic execution.

[Explicit task breakdown](57-task-breakdown.md): Atomically captures steps, inherits prerequisites and makes the parent depend on every new step; no automatic execution or completion.

[Native result review and explicit local acceptance](58-native-result-review.md): Review untrusted card text directly, then explicitly complete the local task with a rechecked digest and human note; no automatic completion or native mutation.

[Current-host text-worker preparation](101-current-host-text-worker.md) advances E3.3 adoption readiness on the supported pin. Frozen managed workers and isolated plugin-host operation remain unsupported; upstream or maintained-host adoption and live acceptance are separate gates. It does not complete E3/E9 or unblock reminders/checkpoint-v2.
