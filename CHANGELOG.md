# Changelog

English | [简体中文](CHANGELOG-zh.md)

This file distinguishes design work, development changes, and released capabilities. There is no production release yet.

## Unreleased

### Fixed

- Manage local memory resources across constructor, admission and cleanup failures, preserving primary errors, reporting deferred cleanup failures on successful exit and attempting all registered cleanup. Add explicit reviewed factory SDK sessions with readonly enforcement and durable synthetic conformance (#155).

- Refresh the inactive checkpoint-source proposal’s reviewed canonical source bindings for retained-source discovery and add unit checks that catch stale experiment checksums before host testing; patch/tree integrity guards remain unchanged.

- Add deterministic retained-source deadline, reviewed cleanup and recovery acceptance through registered native recall, including legacy/observed provenance, historical retries and cross-route suppression; runtime behavior and frozen relevance labels remain unchanged (#149).

- Anchor recognized automatic-recall questions to all literal subject/attribute terms, preserving names inside clear slots and legacy behavior for ambiguous syntax; explicit search/recall and one-read budgets stay unchanged. Add frozen development and independent confirmation evaluations with disclosed limits (#147).

- Add independently frozen longitudinal memory diagnostics through the actual native recall hook at 28/250/1000 retained records, with honest relevance misses, complete-context budgets, fresh-process/repack invariants and retained-source migration evidence; no production retrieval changes (#145).

- Port the review-only no-tool worker proposal to the supported host, reject stale/frozen authorization and handle known backend outages; preserve default-off clean-host behavior and separate adoption/release gates (#143).

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

- Verify native Bot sender recovery with the officially installed recipient across abrupt Gateway loss and planned restart. The review candidates preserve the original task, delivery and sender completion identity on both tested Hermes bases (#33).

- Port the review-only Bot sender recovery patch to a separate upstream Hermes snapshot. Verify local recovery without an unattended Bot inference and preserve hosted sandbox isolation and ordinary process wakes (#33).

- Verify one native reply push and follow-up to a viewed local sender when the receiving profile has the officially installed runtime package. The case checks canonical Bot Chat, task replay and same-input sender retry (#33).

- Retry temporarily unavailable receipts for terminated Bot waiters in the review-only candidate. The isolated cases verify exit-only fallback after the retry window and recovery from simultaneous result and checkpoint write failures when the previous checkpoint and output survive (#33).

- Add review-only read-only receipt recovery for a terminated Bot waiter. The original sender completion can include the verified reply or shutdown failure, with an exit-only fallback when target evidence mismatches (#33).

- Verify planned restart with an active native Bot waiter. The review-only candidate collects a drained reply and preserves a killed waiter's process-exit notice in the sender profile. Exact retry continues to reconcile the original recipient receipt (#33).

- Keep the original local Bot handoff in the review-only Hermes checkpoint after a scoped result-write failure. The successor rebuilds the result and preserves pending, consumed and already-admitted behavior without resending (#33).

- Compare native planned Bot reply restart on the clean pin and reviewed Hermes candidate. The candidate restores one saved pending completion, and a scoped result write failure reproduced a recovery gap in the prior candidate while the original recipient receipt stays available (#33).

- Extend the review-only Hermes sender recovery patch to finished waiters. An outstanding completion can replay after owner loss, with durable consumption and native admission deduplication (#33).

- Add a review-only Hermes patch that restores one native sender completion after each of two abrupt Gateway loss scenarios. The clean compatibility pin remains in use (#33).

- Verify a settled Bot reply remains available under its original delivery ID after abrupt Gateway loss before the waiter reads it. Exact receipt replay starts no new inference. The isolated case observes no recovered sender completion (#33).

- Verify in-flight Bot delivery reconciliation after abrupt Gateway loss. The successor marks the original recipient admission interrupted, preserves the ambiguous receipt and does not resend on an exact retry. Automatic sender completion was absent in the isolated case (#33).

- Verify a local Bot reply persists after its only viewer disconnects. Reopening the original chat returns one completion note, and retrying the original input does not resend the Bot request (#33).

- Verify a native Bot reply reaches a viewed local sender once. The recipient receipt, sender event and stored completion correlate to one delivery, which starts one follow-up turn in isolated Linux acceptance (#33).

- Verify same-install Bot reply persistence in an isolated Linux operator case. One native target receipt and one unconsumed sender completion record carry the same delivery ID and synthetic reply (#33).

- Verify that an ordered native process wait returns the complete Bot reply and suppresses the additional sender transcript row once the fallback sees the result was consumed (#33).

- Verify native non-push reply persistence with the officially installed plugin in the receiving profile. The isolated Linux operator case also checks installed task replay after sender completion (#33).

- Verify one native notify-only Bot delivery and its exact settled replay across a Gateway restart with the officially installed plugin in the receiving profile (#33).

- Verify the officially installed plugin can capture and reopen a task in the same hidden canonical Bot Chat across a local Gateway restart (#33).

- Verify a deferred native cron result transfers to the original named Bot Chat after a local Gateway restart. The source spool, one receiver admission and the completed receipt retain the same delivery ID (#33).

- Verify generation-fenced Stop for a named managed worker waiting on a native clarification. The manual case checks the interrupted receipt and the queued successor's independent completion (#33).

- Verify live deletion and same-name recreation of a named profile. The retained Gateway connection refuses the old canonical chat and resolves a distinct chat created explicitly on the fresh profile (#33).

- Record the pinned Hermes behavior after a live named-profile rename. The roster retains the original canonical Bot Chat, and the native Gateway refuses to reopen it when the stored local receipt still references the old route (#33).

- Verify named-profile managed worker recovery after a Gateway crash. The manual case checks that the original admission stays unknown on retry and that explicit resolution lets the queued successor finish once with its own receipt (#33).

- Verify ordinary named-profile prompt execution in a real native managed worker with a synthetic loopback model. The manual Gateway case correlates the worker, admission and terminal receipt and checks that a same-ID retry does not start another execution (#33).

- Verify that signing out of one serving Webapp closes its browser connection while the installation's native client and a second installation's clients keep their existing sessions (#33).

- Verify native adoption of existing compressed history in a named profile and its subsequent opening in Linux Desktop Bot Mode. The acceptance checks that Desktop shows the named history when the default profile contains a different chat with the same session ID (#33).

- Verify native backup and restore of a synthetic Webapp credential, followed by target-only rotation with Webapp disabled. The manual Gateway acceptance checks that the stopped source and archive remain unchanged (#33).

- Add real Linux Electron acceptance for copied installation markers and stopped synthetic home copies. When Desktop discovery shows only the primary route, explicitly scoped reads still reach each Gateway's own transcript, including copies with equal session IDs (#33).

- Verify live retirement and same-name hot serve over retained native Gateway and Linux Electron WebSockets. The Desktop Bot Mode click shows retry while the named profile is absent and opens its original chat after hot serve (#33).

- Verify the saved Webapp token Bot Mode lookup on the clean Hermes pin and a separate proposed build. The proposal scopes the existing chat probe to the selected backend profile and restores the retry prompt after an uncertain empty lookup (#33).

- Add real Linux Electron acceptance for Bot Mode canonical chat refusal and retry. The fixture checks that permission refusal and an uncertain empty lookup leave the current view intact before an ordinary retry opens the existing chat (#33).

- Add exact-pin contracts for profile-scoped plugin state and parent-bound subagent handles through native in-process and hosted dispatch. Document the remaining Primary Bot adapter gates (#33).

- Verify same-name profile routing in the pinned Linux Electron source build through real Desktop SDK, IPC and WebSocket calls. A removed route is refused while its backend and the surviving route remain reachable (#33).

- Add manual acceptance for native Bot delivery over the pinned Gateway's Unix control socket and loopback WebSocket. Verify terminal receipt repair and same-ID replay after restart using a synthetic loopback model (#33).

- Verify native backup and import at the pinned Hermes revision. Import refuses an owned destination before publication. Stopped restore preserves the destination runtime epoch floor and carries the installation marker and Bot Chat lineage from the archive (#33).

- Verify same-install `message_agent` admission at the pinned Hermes revision. The receiving authority records the Bot author and the local ticket principal separately, and an ordinary session is refused before handoff (#33).

- Verify deferred cron Bot Chat recovery at the pinned Hermes revision. After a successful native admission reply is lost, a same-ID retry recovers the queued receipt and leaves one durable admission (#33).

- Verify the pinned native profile lifecycle and distinguish native profile cloning from a stopped installation copy with matching Bot Chat markers (#33).

- Verify pinned Desktop profile route composition for same-name profiles, connection aliases, stale inventory and failed scoped requests. Run the dependency-free Node fixture in foundation CI (#33).

- Verify the native Bot Chat roster on the pinned Hermes host using synthetic local tickets, including canonical root and compression tip, profile scope, and unavailable targets (#33).

- Document exact-pin offline voice compatibility and dated GPT-Live, OpenAI Realtime and Gemini Live protocol differences, with separate readiness states and release gates for each mode (#36).

- Recognize bounded Chinese possessive naming questions with literal subject/attribute slots; fail closed for marker-only slots while preserving one-read budgets and explicit retrieval (#151).

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

- Verify Telegram command denials through the real plugin host child. The command RPC omits receiver and message provenance, and native allowlist refusals stop before IPC (#14).

- Verify owner-entry denials through the native Telegram command adapter and Gateway. Direct, forwarded and edited DMs can have the same public source fields, and Gateway still checks its current allowlist after adapter intake (#14).

- Verify the review-only SSH draft recovery in locally built unsigned Linux x64 AppImages for both continuation modes and reject a mismatched build before launch (#33).

- Verify SSH draft isolation across an endpoint edit when two installations share the same profile and chat ID, with recovery available again on the original endpoint in the review build (#33).

- Add a review-only Hermes Desktop proposal to recover an uncertain SSH text draft from the scoped native journal after abrupt exit and block unchanged resubmission (#33).

- Verify explicit SSH Bot Chat reopen after abrupt Desktop exit. The native prepared submission survives, while the restored draft and its retry identity are lost in the tested window (#33).

- Verify scoped stored-message inspection before SSH Bot Chat resume after Gateway loss. The read preserves the interrupted turn and starts no inference. Explicit resume can start native continuation (#33).

- Verify that the restored SSH draft retains its retry guard after fully exiting and relaunching Desktop before reopening the interrupted Bot Chat, with native continuation enabled or disabled (#33).

- Verify that the restored draft retains its retry guard after reloading the Desktop renderer following SSH acknowledgement and Gateway loss, with native continuation enabled and disabled (#33).

- Verify combined SSH acknowledgement and Gateway loss. Desktop restores the draft and guards one explicit retry. Reopening starts one native continuation by default and none with native continuation disabled (#33).

- Verify OpenSSH Bot Mode recovery after remote Gateway process loss. Explicit reopen triggers one native continuation by default. Disabling native continuation recovers the chat without another provider request (#33).

- Verify that a lost legacy SSH prompt acknowledgement restores the draft and that Desktop warns on its explicit retry without resubmitting. The original reply remains available in the reopened chat (#33).

- Verify that a legacy SSH Bot Mode turn can finish while the transport is down and that an explicit reopen reads the committed reply without resubmitting. Record the missing durable admission receipt (#33).

- Verify that Desktop refuses an SSH endpoint whose host key changed and resumes the original Bot Chat after an explicit trust update and retry (#33).

- Verify live SSH endpoint replacement across separate installations. Desktop closes the original socket and opens the replacement chat, while a captured route descriptor can resolve to the replacement under the same connection ID (#33).

- Verify that a saved SSH alias survives explicit retry after a connection loss. Record that a live alias edit switches Bot Mode to the new target while a stale SDK descriptor can still read the previous served profile (#33).

- Verify Bot Mode refuses to open a cached SSH row during a real OpenSSH interruption and reopens the original remote chat on explicit retry after reconnection (#33).

- Verify a saved OpenSSH profile alias from the Desktop SDK through Bot Mode. The source-built and bundled Linux x64 clients keep the connection-local route while opening the remote named chat (#33).

- Verify Bot Mode opens the existing remote named chat over a saved OpenSSH key connection in source-built and bundled Linux x64 Desktop, with a same-name local profile and unchanged chat stores (#33).

- Verify compressed Bot Chat hydration over the saved Webapp token in source-built and bundled Linux x64 Desktop. Same-ID decoys in three other profile stores remain outside the selected transcript (#33).

- Reproduce the saved Webapp Bot Chat fallback in a bundled Linux x64 AppImage and verify named-profile scoping and explicit retry in the matching review image (#33).

- Verify local Bot Mode refusal and retry from a bundled Linux x64 AppImage built at the pinned Hermes revision. The acceptance checks the running packaged executable and opens the original canonical chat on explicit retry (#33).

- Add explicit LOCAL `origin RECORD_ID` and optional SDK `record_origin` inspection, separating historical acceptance, current state and latest editing route through bounded readonly metadata without reconstructing forgotten payload or claiming authorship/authority (#157).

- Add optional operator-only retained-source discovery and native LOCAL recovery pages with snapshot-fenced pagination, exact status identities and metadata-only reads; no schema migration or automatic replay/discard.

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
