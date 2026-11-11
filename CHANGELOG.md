# Changelog

English | [简体中文](CHANGELOG-zh.md)

This file distinguishes design work, development changes, and released capabilities. There is no production release yet.

## Unreleased

- Add manual production-package memory lifecycle acceptance across real Gateway restarts, with source-text loss, explicit SDK pending recovery, correction/forgetting and exact reentry suppression kept distinct from model or production acceptance (#139).

- Add explicit LOCAL source preview/retain and metadata status/cursor/discard commands, connecting canonical acceptance with actual host UUID and observed provenance; schema-13 preserves legacy receipt history and supports recovery after source loss, without automatic ingestion (#137).

- Add explicit native `source-list`/`source-show` commands for bounded current-session original-row review with metadata-only listing and snapshot-bound selection; no native/canonical writes, source receipts or automatic ingestion (#135).

- Add optional digest-bound canonical mutation receipt inspection through the local Memory SDK, separating historical outcomes from current record metadata without replaying payloads, writing cursors or enabling source acceptance (#131).

- Add a review-only receipt-bound reader that returns complete original native sources and validity in one bounded snapshot; fresh reads honor source invalidation, without enabling memory acceptance, retention authority or checkpoint-v2 (#129).

- Add a review-only metadata journal that recovers interrupted source receipt accounting by the same attempt without replaying native compression; source availability remains a fresh observation, not a memory checkpoint or two-database atomic guarantee (#127).

- Extend the optional API-v1 local Memory SDK with operator-gated metadata checkpoint creation, strict bounded receipt/status validation and isolated checkpoint conformance; historical replay is not current-state proof, and no native checkpoint-v2 or REST capability is enabled (#121).

- Extend the optional local Memory SDK with capability-gated metadata changes and operator-only durable consumer progress, strict payload-free result validation and reusable isolated progress conformance; CRUD-only adapters remain supported.

- Add a review-only pinned-host proposal for durable exact-key cron creation, retained deletion receipts and fail-closed locking; production scheduling, authorization and notification delivery remain unchanged.

- Add a fixed-checkpoint original local M1 acceptance ledger, executable reference checks and explicit delivery limits; no new runtime capability is enabled.

- Add manual packaged Gateway crash-recovery acceptance for durable writes whose client replies were not consumed; preserve exact scope and unknown-outcome guidance.

- Add explicit waiting-task follow-up dates and a due workbench, independent from deadlines and without automatic reminder delivery.

- Add explicit local task priorities and a bounded next-work view while preserving old ready ordering and historical retry receipts.

- Extend manual packaged Gateway acceptance to a Chinese dependency-plan lifecycle and explicit session recovery, without model calls or broader MVP claims.

- Add coordinated current-source local memory repack and durable interruption recovery; preserve old plaintext, require stopped legacy runtimes, and refuse historical restore.

- Add a versioned explicit local Memory SDK facade with strict results, truthful unknown write outcomes and reusable synthetic adapter conformance; no loader, provider switch or complete E2.6 claim.

- Add a pure bounded local-task projection into the shared Task wire shape, preserving terminal lifecycle and minimizing fields; no remote read, pagination or HTTP capability is enabled.

- Refuse stale FTS document/current-query coverage instead of reporting false freshness; add deterministic rebuild/forget contention and a finite #44 local acceptance candidate ledger.

- Add digest-bound operator-only snapshot list/show for bounded historical memory inspection, with later-forgotten text warnings and no restore or automatic recall.

- Add exact-input candidate source suppression and schema-11 accepted-source lineage; correction/forgetting blocks new same-input candidate effects, without semantic erasure or resurrecting historical receipts.

- Fix task/memory snapshot POSIX lock lifetime across hashing and historical reads; serialize controlled inspectors and preserve live-source locks, with real process contention regressions (#94).

- Add explicit private consistent memory snapshot creation/inspection with bounded SQLite copying, historical plaintext retention notices and truthful publication/crash failure handling; no restore or model-tool access.

- Add an unwired, default-denied enrollment ceremony and one-shot SQLite evidence with exact channel/session/policy fences and truthful cross-store failure semantics; no production authority or private reads are enabled.

- Add a finite 11-path/52-contract E0.4 evidence ledger with executable reference-integrity and pinned-source checks; acceptance awaits final merge verification and does not enable controlled writes.

- Add bounded delegation routing, rejected-admission inline fallback and cooperative-stop counterexamples; parent interruption does not revoke already-started effects, and controlled writes remain blocked.

- Add bounded remote file-RPC admission, response-loss replay and kernel fallback-selection contracts; inert endpoints do not establish backend containment or exactly-once effects.

- Add bounded persistent-kernel contracts for current-cell context/callback rebinding, policy veto and retirement after normal/error/timeout/interruption exits; no sandbox containment or production write authority is enabled.

- Add pinned-host concurrent connector contracts for per-item veto, mid-flight policy rechecks, timeout/late effects and explicit retry in primary and constructed-child loops; all controlled-write gates remain blocked.

- Record bounded [live native task conversation acceptance](docs/65-live-task-acceptance.md), including real-provider mutation evidence and post-disable refusal; no runtime behavior change or full MVP claim.

- Add scoped durable event-time watermarks to internal ActionIntent review, preserving stable terminal retries during clock correction.

- Run runtime artifact acceptance on exact pull-request heads with read-only credentials; keep downloadable artifact publication push-only.
### Changed

- Reconcile original E2.7 local-memory acceptance with independent review and exact-main CI; broader memory adapters, lifecycle, migration and deployment remain open.

- Verify the actual production package under default/read-only, frozen-worker and safe bootstrap modes using real negative dispatch and blueprint consumers. Preserve explicit local/native-scheduling opt-ins and unsupported text-worker refusal; no controlled-write authority or host-wide sandbox is added.

- Verify current SQLite policy and revocation inside a synthetic protected read handler under native frozen worker configuration, including direct dispatch, contention and audit failures. Reuse existing internal coordinators; no production write authority is added.

- Extend E0.4 boundary evidence to pinned terminal/browser and batched tool execution, preserving all controlled-write release blocks and distinguishing synthetic endpoints from real account, containment and revocation acceptance.

- Extend the blocked [write-path inventory](docs/13-enforcement-contracts.md) with real pinned-host RPC/MCP admission contracts and explicit response-loss, direct-registry and dishonest read-only counterexamples. Transport/approval doubles are limited and disclosed; no controlled write capability is enabled.

- Add test-only [native memory contracts](docs/76-native-memory-contracts.md) for E0.9 discovery, stores, retrieval and lifecycle boundaries on Hermes `22811165`; preserve strict checkpoint refusal and separate unsupported capabilities from runtime implementation.

- Improve unspaced questions in [Chinese automatic recall](docs/69-chinese-automatic-recall.md) with conservative multi-term selection, preserving explicit queries and access gates. Fixed-corpus misses remain; no general semantic understanding is claimed.

- Native `/personal-memory` now shows readable human views by default. Scripts must prefix `--json` to retain the original envelope; model tools, storage and authority are unchanged.


- Reconcile the integrated acceptance workflows with the current Hermes compatibility target; runtime-package verification now exercises the combined changes on exact PR heads.

- Advance the exact Hermes development target to `22811165`, preserving clean-source identity and Kanban hash guards. Keep historical host proposals on their original isolated baseline; this does not claim a broad support range or production installation.


- Added explicit [advisory native progress sync](docs/53-native-progress-observation.md): anchored identity checks, one latest metadata snapshot and durable retry receipts. Native state never changes local completion or dispatches work.

- Fix parked Kanban creation under the host’s safe DELETE-journal fallback; keep pre-existing journal refusal and test both native-default and DELETE modes.

- Added default-off [parked native Kanban handoff](docs/52-parked-kanban-handoff.md): explicit board, preview/digest commit, durable single-use claim and bounded read-only reconciliation. No worker dispatch, storage initialization or live acceptance.

### Added

- Add an opt-in readable native handoff/result-review workbench via leading `--text`, while preserving default JSON output unchanged and retaining explicit `--json`. Existing output-parsing scripts need no migration. Add a complete isolated packaged-Gateway operator journey; parked cards never imply worker dispatch or automatic local completion (#141).
- Added optional trusted-local retained-source admission, acceptance, discard and metadata recovery with schema-12 migration, exact-source suppression and an independent no-skip source cursor. The isolated native-source consumer requires explicit independent retention; no automatic ingestion or production activation.


- Add a [review-only native checkpoint source receipt proposal](docs/92-native-checkpoint-sources.md), isolated artifact verification and canonical native regressions; shipping provider v1, production pin and runtime activation remain unchanged (#125).

- Add internal caller-bound read-only native source resolution with exact content/lineage validation, finite admission limits and revision fences; no automatic capture, retention guarantee or checkpoint-v2 activation (#123).

- Add a manual-only installed-runtime Gateway task lifecycle acceptance candidate, with real ticket/WebSocket commands and restart readback; live execution remains separately gated.

- Added a versioned shared Hermes/DSH client API schema and conformance fixtures, plus fail-closed local diagnostics. No domain HTTP endpoint or remote permission is enabled.


- Add [native plugin and scheduling lifecycle contracts](docs/75-native-lifecycle-contracts.md) for exact-pin operator Project/Kanban/cron behavior, weak deduplication, partial creation, cancellation requests, uncertain history and a one-off local-only execution receipt. Tests and documented gaps do not enable production scheduling or plugin CRUD authority.
  Kanban checks distinguish the exact native SQLite safety warning and observed DELETE fallback from unexpected diagnostics, without changing host behavior or forcing WAL.

- Add reusable [offline synthetic connector fixtures](docs/74-synthetic-connector-fixtures.md) with durable fake-remote effects, finite idempotency, recovery oracles and pinned-host MCP stdio failure tests. Source prose and read-only hints grant no authority; production connectors remain disabled.

- Add operator-only [reviewed expired-memory cleanup](docs/73-reviewed-expired-memory-cleanup.md): complete bounded previews, snapshot-bound atomic forgetting and historical batch retries. No automatic deletion, tombstone removal or capacity reclamation.

- Add operator-only memory FTS inspection and explicit watermark-bound rebuild from canonical records. Unsafe configuration, unknown schema and canonical damage remain refusals; no automatic repair or payload restoration.

- Add explicit project-wide task date shifting with complete previews, atomic snapshot-bound apply and historical retry receipts. Terminal/undated tasks, native cards and reminders remain unchanged.

- Add operator-only new-memory Markdown drafts with explicit retention and preview-before-save. Exact apply retries return historical receipts even after forgetting, without recreating the record. This is manual capture, not generic file import.


- Add a private single-record Markdown edit draft with explicit preview, digest/CAS apply and discard. Schema v9 tracks bounded lifecycle metadata; target corrections/forgetting clean the managed draft, including edits.

- Add an opt-in private Markdown memory projection with explicit status/refresh/disable, safe mutation invalidation and crash recovery. Schema v8 requires a compatible writable migration; no model file tools or Markdown import.

- Add explicit multi-term local memory search with transactional FTS5 and short Chinese substring checks; preserve literal search/recall. Schema v7 atomically migrates owned stores and requires FTS5 trigram plus secure-delete support; read-only access never migrates.

- Add explicit digest-bound backup task preview and recovery as a fresh local record, with atomic retry receipts; no live-store replacement or execution-state restoration.
- Add bounded internal policy/revocation audit inspection with coherent epoch watermarks and fail-closed history validation; no production authority or external cancellation.
- Add internal atomic ActionIntent replacement with exact binding, durable retry links and strict v1-to-v2 migration; no approval or execution is enabled.


- Add coherent bounded internal pending-intent review snapshots with transactional expiry reconciliation; no approval or execution capability.


- Add exact-binding, same-scope atomic batch cancellation of internal ActionIntent drafts; no production approval or external cancellation is enabled.

- Add an internal metadata-only ActionIntent draft ledger with exact byte binding, durable cancellation/expiry and scoped retry identity; no approvals or external execution.

- Add bounded durable prepared-read audit metadata and exact-v1 enrollment migration without enabling owner reads or claiming delivery.

- Native schedule preview through explicit local CLI, with offset-aware reference/IANA timezone, bounded candidates and truthful DST-gap warnings; no scheduling or delivery.

- Add explicit digest-bound historical task browsing and inspection from private backups, without restoring or replaying live tasks.

- [Add explicit local task snapshots with integrity checks, private no-overwrite publication and metadata inspection; no automatic restore or export to external services.](docs/61-local-task-backups.md)

- Add cold runtime-package acceptance through native LOCAL conversation dispatch, with replay and denied-capability checks; deployed acceptance remains open.
- Added opt-in [Gateway bootstrap diagnostics](docs/gateway-boot-diagnostics.md) that preserve the upstream listener failure traceback, with read-only planning and offline regression coverage. Prepared a manual-only pinned upstream, credential-free native lifecycle CI gate for actual control/WebSocket attach, queued recovery and managed-worker execution. Approved-provider/plugin acceptance remains a separate gate.
- Add 11 host-free abrupt-process memory recovery tests for atomic candidate acceptance, forgetting and durable no-resurrection replay (refs #21); no live Gateway acceptance claim.
- Added 88 offline task-transaction process-crash cases across DELETE/WAL journals, covering atomic records, dependency edges, events and retry receipts; no production behavior change.

- Add explicit local project-label rename with bounded preview, atomic all-task updates, dependency preservation and durable retry receipts.

- [Project task dependencies](docs/51-project-task-dependencies.md) now enforce explicit same-project prerequisites before starting or completing work, with a ready queue and fresh dependency snapshots in review/focus. Cancelled prerequisites remain blockers; no worker is launched and no native Kanban state is modified.

- [Reviewed memory candidates](docs/50-reviewed-memory-candidates.md) add separately opted-in drafting from current native input, exact source quotes and native acceptance with an explicit retention choice. Candidates stay out of recall until accepted; expiry cleanup is lazy, and no extra model request or automatic canonical write is introduced.

- Added separately opted-in automatic session memory recall through the supported native turn hook: fresh bounded current records, shared expiry/revocation boundaries, no provider replacement or extra model request. Correction/forgetting affect new recall, not historical host context. See [49](docs/49-session-memory-recall.md).

- Added verified downloadable runtime artifacts for successful branch pushes: deterministic source-pinned archives, unchanged official static scanning and cold real-host task/reload acceptance. Findings and provenance accompany the package; no installer, host patch, model request or release is performed.

- Added an operator-facing native workbench to the review-only worker consumer: scoped request pages, truthful status, saved-draft viewing and pre-submission stop, with readable text and explicit `--json`. These commands neither launch nor retry work; already-admitted cancellation remains unavailable.

- Extended the review-only worker proposal with an isolated no-redirect HTTP client and durable single-claim/draft receipts. A restart never silently repeats a claimed request; completed observed drafts remain inspectable. No live system or production plugin is changed.

- Added a [review-only task-to-worker proposal](docs/48-task-worker-proposal.md): exact-route single text inference, explicit task-revision grants, no-tool lifecycle drafts and separate offline integration evidence. The production plugin and clean host compatibility pin remain unchanged.

- Added [atomic project-plan capture](docs/47-atomic-project-plans.md) through native commands, CLI and existing activated write tools: 1–20 tasks share one transaction/retry receipt, with whole-batch validation, crash rollback and restart-safe replay. Worker containment limitations remain explicit.

- Added [native task focus](docs/46-native-task-focus.md): an explicit session selection supplies fresh bounded task context through the real host turn hook. It shares task-tool admission, expires with activation and preserves historical prompt bytes; no worker dispatch or extra model call.

- [Explicit memory expiry](docs/45-explicit-memory-expiry.md) adds explicit UTC deadlines, default expiry filtering, deliberate inspection and schema-v5 migration. Expiry affects fresh recall eligibility, not stored status or deletion; native read-only recall never migrates storage.

- [Native checkpoint evidence boundaries](docs/43-native-checkpoint-boundary.md) add bounded I/O-free candidate preparation and pinned-host contracts. Stable UIDs, pending input and revision limits are verified; automatic ingestion and checkpoint-v2 remain disabled.

- Added readable native task command views, bounded task/review pages, safe continuation hints and explicit retry/error wording. Native commands now default to text; leading `--json` retains structured replies. CLI JSON defaults and model-tool schemas remain unchanged.

- Native recall now refuses host-detected managed-policy scopes before/after saved-config reads and before publishing a recall pack; raw user opt-in cannot override administrative revocation.

- [Optional native memory recall](docs/41-native-memory-recall.md): An explicitly selected real MemoryProvider can supply fresh bounded local-record context to supported native primary sessions. It performs no ingestion or canonical writes; strict native checkpoints remain unavailable.

- Added explicit local task progress (ready/in-progress/waiting/blocked) with notes, CAS and durable retries, native CLI/conversation/model entry points, progress filters and daily-review counts. Atomic task schema v1/v2/v3→v4 migration preserves legacy receipts and events; no worker dispatch or automatic status inference.

- Added a bounded daily task review across CLI, native conversation and activated task read tools: exact active counts, project filters, complete title summaries, serialized budgets and one-snapshot consistency. No schedule, new permission, model call or schema change.

- [Local memory metadata checkpoints](docs/39-local-memory-checkpoints.md): Explicit native commands create durable metadata-only markers with event/record consistency checks, watermark fencing and stale-status inspection. These do not back up payload or satisfy native compression checkpoints.

- Added native `personal-agent routing inspect`: profile-bound, identifier-free saved-config diagnostics with explicit effective-route unknowns, non-file/managed-worker refusal and unload guards. No backend activation, credential resolution, model calls or configuration writes.

- Added metadata-only local memory change pages and durable internal consumer cursors with CAS, exact receipt replay and quota limits. Atomic schema v1/v2→v3 migration preserves canonical records and receipts. No new model actions, background worker, native provider or compression-checkpoint guarantee.

- Added an offline worker-routing fixture evaluator and partial pinned native contracts: strict candidate constraints, exact pins, baseline qualification and minimized advisory reports. No live backend, provider calls, automatic switching or budget guarantees.

- Added explicit bounded memory recall through native commands and separately activated read tools: multi-keyword literal ranking, whole-record JSON budgets and current-record snapshots. Includes capability negotiation, correction/forgetting and fresh-process contracts; no automatic prompt injection, provider replacement or new storage schema.

- Added strict explicit-memory backend descriptor/capability/limit negotiation, metadata-only adapter discovery and exact reviewed-candidate checks, plus reusable offline conformance gates. No third-party import, loader, activation or native provider replacement.

- Added bounded local task operation history through CLI, native slash commands and activated task read tools. Existing metadata-only events survive restart and paginate by revision; same-page snapshot consistency, replay/CAS behavior and native admission are covered. No schema change, model call, worker dispatch or new authorization is introduced.

- Added separately activated native memory model tools with read/write TTL, live-turn admission and independent task permissions. Added model-origin provenance and exact-owned memory schema v1→v2 migration preserving legacy receipts; no automatic prefetch/extraction or real-provider acceptance.

- Added opt-in native `/personal-memory` operator records: remember, bounded literal search/list/export, revisioned correction and terminal forgetting. Dedicated private SQLite, metadata-only replay receipts and a narrow internal backend interface; native providers unchanged, with no automatic recall/extraction or public adapter loader.

- Added the bilingual pluggable-memory design, user-written adapter contract, default SQLite/Markdown authority rules, native single-provider compatibility, checkpoint/recall/deletion/migration gates, and E0.9/E2.6–E2.9 planning. Documentation only; no memory backend or ingestion is enabled.

- Added separately opted-in local task read/write model tools and 30-minute native session activation, live turn/route/profile/task checks, revocation and unload gates. Ordinary in-process mode only; no real-model acceptance or cross-process activation.
- Corrected pinned cron memory evidence: actual `skip_memory=False`, provider-owned cron write restrictions, and memory reload after compression.

- Added opt-in `/personal-tasks` commands in host-authorized native LOCAL conversations: capture, search, project groups, agenda, edits and completion using existing durable receipts/revisions. No task model tool, new remote entry or model call.
- Adopted the user-approved profile-first single-user local M1 route; Primary Bot and verified remote-owner enrollment become conditional future lanes. Added bilingual setup/trust-boundary guide and actual native in-process command-admission contracts.

- E0 native plugin foundation with a read-only readiness tool and an `in_process` CLI.
- Strict read-only configuration and argument validation. No personal-data or external-action tools.
- Pinned Hermes compatibility metadata, real discovery/dispatch/reload/unload/Doctor contracts, synthetic unit tests, and offline test guards.
- Reproducible check script and SHA-pinned GitHub Actions workflow.
- macOS and Windows system-file ignore rules, preserving existing Python rules, with Git behavior tests.
- Separate English originals and `-zh` Chinese README, changelog, and all design documents with language links.
- E0.4 synthetic failure-boundary contracts covering policy callbacks, dispatcher/middleware failures, direct registry dispatch, and managed/safe worker configuration.
- A read-only blocked-write inventory and `personal-agent coverage` CLI; no write authorization or host-wide enforcement is added.

- Detailed bilingual client/connector API design: plugin HTTP namespace, host authentication seams, canonical session transport, durable changes, approval/idempotency/recovery semantics, and explicit native-mobile blockers. No HTTP endpoints are implemented.
- E0.6 and E6.5–E6.7 work packages, with E5.1/E5.2 connector contract details.
- JSON-example syntax validation with regression tests; this does not validate API schemas or runtime behavior.

- Opt-in `local_tasks` CLI inbox with plugin-owned SQLite, stable request receipts, compare-and-set revisions, explicit completion/cancellation, bounded pages and terminal-state checks.
- Profile/mode gates, private POSIX main/sidecar files, unsafe-link/permission rejection and database ownership/schema checks; default diagnostics remain storage-free.
- Synthetic concurrency/rollback/storage tests, real-host CLI lifecycle tests and guarded top-level CLI subprocesses.
- Separate bilingual primary Bot binding design, including conditional E0.7/E1.6/E3.6 work packages; no binding code is enabled.

- Local date-only deadlines and bounded agenda, with explicit set/clear/view dates and existing idempotency/revision gates; no clock inference or reminder delivery.
- Atomic exact-schema v1→v2 upgrade preserving legacy digests/receipts, with rollback, concurrent-upgrade and old-request replay tests.

- Owner-entry diagnostics, an internal read-authorization evaluator and native context/IPC contracts; missing receiving-Bot provenance explicitly blocks private reads, with no production identity or grant issuance.

- Bilingual unified voice-session/provider contracts for local/online pipelines and realtime frontends, including capability negotiation, interruption/recovery, credentials/budgets/privacy and E0.8/E7.5–E7.7 planning. Design only; no microphone, online call or voice runtime feature is enabled.

- Offline `voice self-test` CLI, strict synthetic PCM capability/frame validation, bounded queues, duplicate/gap handling, generation/epoch fencing and interruption/recovery/close checks. No speech recognition, synthesis, capture, playback or native turn is performed.
- Native ASR/TTS discovery and pipe-host contracts with synthetic unavailable providers; file operations work across the tested host boundary, but streaming-session/generator return values are not usable there. No provider is registered by the production plugin.

- Review-only native voice IPC patch, provenance, separate guarded reproduction and bilingual limitations. Not applied, installed or integrated into the plugin; the official compatibility pin is unchanged.
- Local literal title/details search with state filtering and bounded creation-order pagination, preserving existing task schema, receipts and local-operator gates. No semantic retrieval or private channel access is enabled.

- Local project labels, exact project/unassigned filters and bounded per-project progress counts; atomic schema-v3 upgrades retain historical mutation digests and receipt bytes. No native project mapping or authorization scope is added.
- Review-only host command-context patch, license, provenance and bilingual integration gates. Historical 146 passing tests and 9 environment-blocked tests are recorded separately; the patch is not installed, integrated or an owner-authorization issuer.

- Opt-in native personal planning Automation Blueprint, with strict boolean configuration and native catalog/form/command integration. Registration creates no job or personal-data access; actual native scheduling has independent model/delivery costs and jobs survive plugin removal.

- Revised the review-only identity prototype to confine live command observations to registered command handlers, preserving generic hook/tool keyword data. Recorded 87 guarded tests and 14 static checks separately from unresolved historical socket failures; no production identity activation.
- Documented the minimum gated owner-summary path, including explicit local-data adoption and atomic host/policy admission.
- Preserve unified patch context whitespace through scoped Git attributes; upstream source whitespace checks still run.

- Added a default-disabled pending enrollment/policy persistence core, exact scoped CAS, terminal revocation, transactional audit and private POSIX storage checks. No activation, grant issuance, task adoption or production read entry point.

- Added an unwired default-denied read coordinator and SQLite current-policy guard, exact confirmations, bounded summary projections and revoke/expiry contention tests. Trusted host/resource adapters and durable read audit remain production gates.

### Boundaries

- Bounded E0.2–E0.3 native lifecycle contracts do not enable controlled native execution. Full E0.4 coverage, E0.6, identity/authorization, full domain storage, reminders, connectors, mobile, voice, and E9 model routing remain unimplemented.
- Local task storage is a trusted-local-operator feature, not owner authentication, native task execution or an OS sandbox. Windows storage, encryption, export/forget and full retention policy remain unsupported.
- The plugin does not secure other Hermes tools. The status reports a blocked release gate.
- Full install transactions and isolated-host execution have not been validated. The host-isolated CLI is unsupported by the pinned host.

## Design baseline: 2026-11-06

- Documented the Hermes-native personal-agent architecture, DSH research, authorization/revocation semantics, reliable delivery, memory, mobile/voice, and E0–E8 roadmap in commit `c254c86a17c61e1bd13d74d00d5b44016abab13d`.
- Added the native worker model/effort routing design, shadow-first rollout, host constraint gaps, open-source comparisons, and E9.1–E9.6 work packages in commit `e4eb446c0d0c20d3ce83aa20f7b5139261d593f9`.
- Those commits delivered designs and plans, not running product features.

Added [saved native attention review](docs/54-saved-native-attention.md): local snapshots only, overlapping buckets with unique counts, no live-board read or completion change.

[Gated task planning worker](docs/55-gated-plan-worker.md): Production-package integration is default-off and requires the exact reviewed host contract plus current consent; not installed or live-accepted.

[Explicit atomic plan dependencies](docs/56-atomic-plan-dependencies.md): Explicit one-based batch references save tasks and edges together, without automatic execution.

[Explicit task breakdown](docs/57-task-breakdown.md): Atomically captures steps, inherits prerequisites and makes the parent depend on every new step; no automatic execution or completion.

[Native result review and explicit local acceptance](docs/58-native-result-review.md): Review untrusted card text directly, then explicitly complete the local task with a rechecked digest and human note; no automatic completion or native mutation.
