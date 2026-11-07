# Changelog

English | [简体中文](CHANGELOG-zh.md)

This file distinguishes design work, development changes, and released capabilities. There is no production release yet.

## Unreleased

### Added

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

- E0.3, full E0.4 coverage, E0.6, identity/authorization, full domain storage, reminders, connectors, mobile, voice, and E9 model routing remain unimplemented.
- Local task storage is a trusted-local-operator feature, not owner authentication, native task execution or an OS sandbox. Windows storage, encryption, export/forget and full retention policy remain unsupported.
- The plugin does not secure other Hermes tools. The status reports a blocked release gate.
- Full install transactions and isolated-host execution have not been validated. The host-isolated CLI is unsupported by the pinned host.

## Design baseline: 2026-11-06

- Documented the Hermes-native personal-agent architecture, DSH research, authorization/revocation semantics, reliable delivery, memory, mobile/voice, and E0–E8 roadmap in commit `c254c86a17c61e1bd13d74d00d5b44016abab13d`.
- Added the native worker model/effort routing design, shadow-first rollout, host constraint gaps, open-source comparisons, and E9.1–E9.6 work packages in commit `e4eb446c0d0c20d3ce83aa20f7b5139261d593f9`.
- Those commits delivered designs and plans, not running product features.
