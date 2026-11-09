# Hermes Superagent Design Documents

English | [简体中文](README-zh.md)

Status: **Design baseline plus E0 contracts, local task storage and opt-in native conversation commands/model tools; the full personal-agent MVP is not yet implemented.** Verification date: 2026-11-06. Repository: `MosBot-AI/hermes-superagent`. See the [first development slice](12-foundation-progress.md) for current code and verification boundaries.

The user selected a profile-first single-user local MVP: manage tasks and project labels through an existing native session before optional Primary Bot/remote enrollment. Profiles remain partitions, not identities. Primary Bot, remote/multi-user, mobile and voice gates remain requirements of their respective future modes; see [28](28-profile-first-local-conversations.md) and the [roadmap](08-roadmap-and-acceptance.md).

## Purpose

Extend Hermes into a long-lived personal agent for one user: one main agent understands projects, affairs, personal information, reminders, and communication, with a small number of constrained workers when needed. Reuse Hermes's native runtime, plugins, memory, tasks, scheduling, MCP, messaging, and voice rather than building a separate external agent.

## Reading order

1. [Product goals and scope](01-product-and-scope.md): users, capabilities, and explicit exclusions.
2. [DSH research and decisions](02-dsh-research-and-decisions.md): lessons from the source and reporting, with necessary corrections.
3. [Hermes-native architecture](03-native-architecture.md): boundaries between the host, plugin, domain state, and execution.
4. [Domain data and memory](04-domain-data-and-memory.md): projects, commitments, information, provenance, corrections, and forgetting.
5. [Proactivity, scheduling, and delivery](05-automation-and-delivery.md): reliable reminders, recovery, idempotency, and messages.
6. [Plugins, MCP, and security](06-plugins-mcp-and-security.md): open extensions, action authorization, identity, and revocation.
7. [Mobile and voice](07-mobile-and-voice.md): reuse existing entry points while preserving one agent's continuity.
8. [Roadmap and acceptance](08-roadmap-and-acceptance.md): dependency-ordered epics, work packages, and testable criteria. Follow the [GitHub Project workflow](github-project-workflow.md) to claim, implement and verify work.
9. [Upstream evidence and verification boundaries](09-upstream-evidence.md): pinned research sources. The [Hermes compatibility matrix](hermes-compatibility-matrix.md) maps the current E0.1 baseline to behavior tests and remaining gates.
10. [Interfaces and end-to-end contracts](10-interface-contracts.md): proposed events, tools, adapters, and vertical flows.
11. [Worker model routing plugin](11-worker-model-routing.md): select authorized provider/model/effort routes, starting in shadow mode.
12. [First development slice](12-foundation-progress.md): the native read-only plugin, real contract tests, and remaining gates.
13. [Enforcement contracts and write-path inventory](13-enforcement-contracts.md): observed failure boundaries and still-blocked write paths.
14. [Client, authorization, and connector API contracts](14-client-api-contracts.md): proposed HTTP routes, canonical session transport, recovery, and explicit native-mobile blockers.
15. [Primary Bot binding and continuity](15-primary-bot-binding.md): proposed selection of an existing native Bot, verified roles, recovery and fencing.
16. [Opt-in local task inbox](16-local-task-inbox.md): implemented local CLI persistence, replay/revision checks and explicit limits.
17. [Local due dates and agenda](17-local-task-agenda.md): date semantics, bounded queries and transactional schema upgrades.
18. [Owner entry and read authorization](18-owner-entry-and-read-authorization.md): internal evaluator, native identity gaps and non-personal diagnostics.
19. [Unified voice session and provider contracts](19-unified-voice-provider-contracts.md): replaceable local/online speech interfaces, capabilities, interruption/recovery and safety gates.
20. [Offline voice contract simulator](20-voice-contract-simulator.md): synthetic frame/queue/recovery self-test and verified native provider limitations.
21. [Native voice IPC experiment](21-native-voice-ipc-experiment.md): reviewable host patch, actual consumer evidence and unintegrated release limits.
22. [Local task search](22-local-task-search.md): literal title/details matching, bounded pages and unchanged local-only gates.
23. [Host command-context experiment](23-host-command-context-experiment.md): review-only command-specific identity-observation patch, guarded evidence and the minimum owner-summary integration path.
24. [Local project groups](24-local-project-groups.md): task labels, exact filters, progress counts and schema-v3 migration.
25. [Native planning blueprint](25-native-planning-blueprint.md): opt-in integration with native planning forms and explicit job lifecycle/cost boundaries.
26. [Pending enrollment and policy persistence](26-pending-enrollment-policy.md): unwired administrative metadata, CAS/revocation, private storage and remaining owner-admission gates.
27. [Fenced read admission](27-fenced-read-admission.md): default-denied confirmation/snapshot seams, actual policy transaction ordering and unimplemented production adapters.
28. [Profile-first local task conversations](28-profile-first-local-conversations.md): opt-in native commands, task/project-label lifecycle and trusted single-user deployment boundary.
29. [Session-scoped task tools](29-session-scoped-task-tools.md): explicitly activated in-process model task access, privacy/revocation boundaries and pending real-model acceptance.
30. [Pluggable memory contracts](30-pluggable-memory-contracts.md): proposed replaceable backend/SDK, SQLite authority and Markdown projections, optional native bridge, bounded recall, deletion and migration.
31. [Explicit local memory](31-explicit-local-memory.md): user-controlled native remember/search/correct/forget commands, bounded records and partial adapter seam; no automatic recall or provider replacement.
32. [Session-scoped memory tools](32-session-scoped-memory-tools.md): independent 30-minute read/write activation, model provenance, v1→v2 migration and pending real-model acceptance.
33. [Memory adapter admission](33-memory-adapter-admission.md): strict explicit-record descriptors, capability/limit checks, metadata-only review and reusable offline conformance gates; no third-party loading.
34. [Local task operation history](34-local-task-history.md): persistent revision-ordered metadata, bounded pages and existing native read gates.
35. [Offline worker routing](35-offline-worker-routing.md): strict synthetic candidate filtering, baseline gating and partial native routing contracts; no live backend.
36. [Bounded explicit memory recall](36-bounded-memory-recall.md): multi-keyword literal ranking, whole-record JSON budgets, current revisions and one read snapshot; no automatic prompt injection.
37. [Durable local memory progress](37-durable-memory-progress.md): metadata change pages, internal CAS/idempotent consumer cursors and atomic schema-v3 migration; not native compression checkpointing.
38. [Saved routing inspection](38-routing-readiness-inspection.md): native local declaration diagnostics without credential/model resolution or routing activation.
39. [Local memory metadata checkpoints](39-local-memory-checkpoints.md): Explicit native commands create durable metadata-only markers with event/record consistency checks, watermark fencing and stale-status inspection. These do not back up payload or satisfy native compression checkpoints.
40. [Daily task review](40-daily-task-review.md): one-snapshot active counts, title-only summaries, exact project filters and output budgets.
41. [Optional native memory recall](41-native-memory-recall.md): An explicitly selected real MemoryProvider can supply fresh bounded local-record context to supported native primary sessions. It performs no ingestion or canonical writes; strict native checkpoints remain unavailable.
42. [Local task progress](42-local-task-progress.md): explicit working/waiting/blocker notes, revision-safe writes, active filters and atomic schema-v4 migration.
43. [Native checkpoint evidence boundaries](43-native-checkpoint-boundary.md) add bounded I/O-free candidate preparation and pinned-host contracts. Stable UIDs, pending input and revision limits are verified; automatic ingestion and checkpoint-v2 remain disabled.
44. [Readable task workbench](44-readable-task-workbench.md): native human views, explicit JSON compatibility, safe pagination and accurate retry/error messages.
45. [Explicit memory expiry](45-explicit-memory-expiry.md): adds explicit UTC deadlines, default expiry filtering, deliberate inspection and schema-v5 migration. Expiry affects fresh recall eligibility, not stored status or deletion; native read-only recall never migrates storage.
46. [Native task focus](46-native-task-focus.md): explicitly select one task for fresh bounded main-turn context, with session activation, whole-field budgets and retained-history boundaries.
47. [Atomic project plans](47-atomic-project-plans.md): all-or-none multi-task capture, durable shared receipts, native/model/CLI flows and verified worker-dispatch limits.
48. [Task-to-worker proposal](48-task-worker-proposal.md): isolated opt-in text-only host patch and concrete task consumer; not production worker dispatch.
49. [Session automatic recall](49-session-memory-recall.md): separately selected bounded fresh reads through supported native hooks.
50. [Reviewed memory candidates](50-reviewed-memory-candidates.md): live-input drafts, separate local review, atomic acceptance and explicit retention limits.
51. [Project task dependencies](51-project-task-dependencies.md): atomic same-project prerequisite gates, ready work, fresh snapshots and no dispatch.
52. [Architecture decision records](adr/README.md): reasons for the constraints.

## Keep three kinds of statements separate

- **Verified upstream capabilities:** found in pinned Hermes/DSH source or official documentation; this does not mean this repository implements them.
- **Project design:** domain models, policies, interfaces, and adapters still to build. Tool names, tables, and events in the design are proposed interfaces.
- **Unverified items:** need prototypes and integration tests, not invented upstream APIs.

Research baselines: Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4` and DSH Superagent `8c32a9dc5d72c033816c6a8110b37f40cf94fba4`. `main` changes continuously. Implementation must select a compatibility-tested release and record its exact SHA. These documents are not a permanent guarantee about all behavior in the latest release.

## Hard design constraints

1. One main identity and authorization principal; projects and sessions do not become separate personas.
2. Do not duplicate the Hermes agent loop, session store, cron scheduler, Kanban dispatcher, or OAuth stack.
3. External material is evidence, not authorization. A message arriving through the user's account does not make quoted instructions owner-authored.
4. Prompts, Mandates, MCP read-only hints, and Python plugin loading are not security isolation.
5. External sends, modifications, spending, and similar actions require a verifiable intent and renewed authorization checks before execution. Retries cannot expand permissions.
6. New user requests take priority over background work. Proactivity must be explainable, pausable, budgeted, quiet when appropriate, and deduplicated.
7. Runtime state, personal data, and credentials do not belong in this public repository. It contains designs, synthetic examples, and implementation code.

## Current deliverables

The design and project plan are established. The E0 foundation and opt-in local task inbox run in temporary test homes. Local CLI persistence and opt-in native LOCAL session commands are implemented; activated in-process model task tools are implemented, while remote-channel/HTTP personal-data access is not. There is no production deployment or connection to real personal data, and no claim that authorization, reminders, or mobile voice are usable. GitHub Projects tracks development; native Hermes Projects/Kanban will represent runtime work. They are different systems.

E9 has a selected native worker-routing design, an offline constraint evaluator and partial native contract tests. The live routing backend is not implemented. The main agent keeps its responsibilities. See [11](11-worker-model-routing.md) for constraints, host gaps, references, and acceptance criteria.

- [Saved native attention review](54-saved-native-attention.md)

[Gated task planning worker](55-gated-plan-worker.md): Production-package integration is default-off and requires the exact reviewed host contract plus current consent; not installed or live-accepted.

[Explicit atomic plan dependencies](56-atomic-plan-dependencies.md): Explicit one-based batch references save tasks and edges together, without automatic execution.

[Explicit task breakdown](57-task-breakdown.md): Atomically captures steps, inherits prerequisites and makes the parent depend on every new step; no automatic execution or completion.

[Native result review and explicit local acceptance](58-native-result-review.md): Review untrusted card text directly, then explicitly complete the local task with a rechecked digest and human note; no automatic completion or native mutation.

- [Gateway bootstrap diagnostics](gateway-boot-diagnostics.md): read-only planning and opt-in traceback capture; not transport acceptance.
- [Task transaction process-recovery evidence](task-transaction-recovery.md): 88 isolated crash cases; not full M1 acceptance.
[Atomic project-label rename](60-project-label-rename.md): explicit whole-group preview and revision-safe relabeling, preserving dependencies and terminal states.

- [Explicit local task backups](61-local-task-backups.md)

- [Native schedule preview](62-native-schedule-preview.md)

- [Durable prepared-read audit](63-prepared-read-audit.md): internal committed snapshot metadata, not delivery proof or production identity.

- [Durable internal ActionIntent drafts](64-action-intent-drafts.md): metadata binding and terminal drafts only, not approval or execution.

- [Live native task conversation acceptance](65-live-task-acceptance.md): real TUI/provider capture, lookup, update, completion and post-disable refusal on exact revisions.

- [Local multi-term memory search](66-local-memory-full-text-search.md): transactional FTS5, short Chinese terms and unchanged literal contracts.

- [Readable native memory workbench](67-readable-memory-workbench.md): human views and explicit JSON output, without new storage or authority.
- [Private Markdown memory projection](68-private-memory-projection.md): explicit refresh, fixed private files and fenced crash recovery; SQLite remains canonical.

- [Bounded Chinese automatic recall](69-chinese-automatic-recall.md): shared local query planning and conservative matching, with fixed synthetic evidence; explicit search and authority are unchanged.
- [Private Markdown memory edit drafts](70-private-memory-edit-drafts.md): editor-based first capture with explicit retention, plus digest/revision-bound corrections; preview before saving, without editing the generated projection.

- [Project-wide task date shifting](71-project-task-reschedule.md): preview all affected dates, then atomically shift active dated tasks with snapshot checks and durable retry receipts.

- [Memory index inspection and recovery](72-memory-index-recovery.md): check canonical/index correspondence and explicitly rebuild derived FTS under the current event watermark, without restoring forgotten records.

- [Reviewed expired-memory cleanup](73-reviewed-expired-memory-cleanup.md): inspect complete bounded batches, then forget the exact snapshot with historical retry receipts and managed-file cleanup.

- [Offline synthetic connector fixtures](74-synthetic-connector-fixtures.md): durable fake-remote effects, bounded untrusted sources, failure/reconciliation oracles and real pinned-host MCP stdio counterexamples; test-only, without production authority.
