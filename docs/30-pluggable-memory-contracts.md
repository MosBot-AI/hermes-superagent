# 30. Pluggable Personal Memory and Continuity

English | [简体中文](30-pluggable-memory-contracts-zh.md)

Implementation update: [31](31-explicit-local-memory.md) now provides a narrow explicit local-record precursor, with an internal backend seam and native commands. The full SDK, lifecycle, automatic retrieval/ingestion and migration contract below remain proposed; the source review and this local slice do not complete them.

**Status: target design with a narrow local precursor; full contract not implemented.** This document specifies replaceable personal-memory storage/retrieval, lifecycle adapters and acceptance gates. It does not install a provider, ingest conversations, enable extraction, replace a user's memory, or prove recall quality. Existing task tools and policy foundations are separate implementations, not this memory system.

The first product lane is [profile-first trusted local use](28-profile-first-local-conversations.md), with [session-scoped task tools](29-session-scoped-task-tools.md) separately enabled. Optional verified remote-owner, Primary Bot, HTTP and voice lanes retain their own gates. Memory does not require a canonical Bot Chat. Read [04](04-domain-data-and-memory.md), [06](06-plugins-mcp-and-security.md), [10](10-interface-contracts.md) and [19](19-unified-voice-provider-contracts.md) alongside this contract.

## 1. Decision and Non-Goals

Use a small, replaceable **MemoryBackend** behind a stable project-owned **MemoryService**. Ship a lightweight local backend using SQLite records/events/FTS plus readable Markdown projections. Users may select a reviewed alternative or write an adapter. Keep governance, current authorization, source attribution, deletion suppression, token budgets and task/action authority outside provider-generated prose.

The default design needs no vector service, external memory API, extra agent loop, parallel transcript database or custom phone app. Installing the base package changes no native memory configuration. A selected online embedding, extraction, reranking or storage service is a separate, explicit data/cost choice; local storage does not mean all model computation is offline.

There are two extension levels:

| Extension | Purpose | Boundary |
|---|---|---|
| Project `MemoryBackend` | Store/retrieve versioned personal records through the same service contract | Proposed interface; not an existing Hermes registry or `ctx.memory` API |
| Optional Hermes `MemoryProvider` bridge | Integrate the service with actual native prefetch/sync/checkpoint lifecycle | Must be deliberately selected in Hermes's single external-provider slot; not automatically added beside another external provider |

The project can retain a user's existing Hermes provider and offer its own explicit, authorized domain-memory tools without installing that bridge. In this mode, automatic native prefetch/checkpoint integration is **not** promised. A compatible existing provider could integrate the same service, but only under its tested contract. Do not impersonate `builtin`, chain hidden providers, use private host fields, or automatically overwrite `memory.provider` to evade the slot limit.

## 2. Verified Native and DSH Foundations

Hermes baseline is `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`; DSH reference is `8c32a9dc5d72c033816c6a8110b37f40cf94fba4`. Source inspection is not deployed behavior or a performance benchmark.

| Verified fact | Design consequence |
|---|---|
| Built-in MEMORY.md / USER.md default to 2,200 / 1,375 characters, with configurable bounded stores [M1] | Keep high-value preferences/index hints there, not the entire fact graph or activity history |
| Cached prompt snapshots reload memory after compression invalidation [M2] | Do not claim memory is either refreshed every token or frozen forever until `/new` |
| Native in-place compaction soft-archives old rows and writes active summary/tail transactionally; archived rows remain searchable [M3] | Hermes owns raw conversation retention and compression; summaries remain lossy and require evidence references |
| `session_search` provides FTS discovery/read/scroll, bounded content and source/ranking filters; explicit `profile=` can open another local profile [M4] | Native history is a recall source, not automatic plugin ACL enforcement or unrestricted evidence for every caller |
| MemoryManager rejects a second non-`builtin` external provider [M5] | One active external native provider; project adapters do not create multiple native slots |
| Native `MemoryProvider` has initialize/prefetch/sync/tool/session/pre-compress hooks and profile-scoping requirements [M6] | Adapt those actual methods; there is no generic native CRUD/event/export API promised here |
| Default checkpoint API is best-effort v1; optional required checkpoint needs v2-capable success [M7] | Advertise strict checkpoint support only after durable evidence and failure tests, not by setting a flag alone |
| Cron constructs agents with `skip_memory=False`, `skip_background_review=True`, and provider context `cron` [M8] | Background memory can be loaded; the adapter must enforce its own cron write policy; no universal host read-only guarantee |
| DSH persists task/evidence/effect objects and exposes bounded linked resources; its `core/memory.ts` is a test Map repository [M9] | Reuse the referenced-context/recovery idea, not a claim that DSH supplies production personal semantic memory |

Default native memory review is conditional, with the configured nudge interval and post-turn gates; it is not a guaranteed extraction after every message [M10]. External provider sync is asynchronous and may fail. A successful spoken acknowledgement is not a committed write receipt. DSH's underlying session-compression dependency is not independently audited by this project.

## 3. Memory Types and Sources of Truth

| Type | Contents | Authority and retrieval |
|---|---|---|
| Semantic | Preferences, people/relationships, environment facts and constraints | Versioned fact records with source, confidence, validity and explicit/inferred status |
| Episodic | Bounded account of a discussion or completed activity | Referenced episode summary with native session/event ranges, coverage and unresolved questions; not a transcript replacement |
| Task continuity | Goal, acceptance, constraints, current step, decisions and blockers | Task service/native run remain authoritative; memory stores references and a revision-tagged working snapshot |
| Procedural | Reusable tested workflow or technique | Native skill files/registry remain authoritative; proposed skill changes require the supported review/install flow |
| Working context | Current turn and recently relevant evidence | Ephemeral bounded context assembled for one invocation; not automatically promoted into durable facts |

Memory never stores a grant, approval, task-completion truth or external effect success merely because a summary says so. A recalled permission statement can locate the real policy/receipt, not replace it. A worker's claimed success is evidence awaiting the task's acceptance rules.

Records distinguish `observed_at`, `recorded_at`, `valid_from`, `valid_until`, and original timezone/wording where relevant. A new statement need not supersede an old fact in a different scope. Conflicting facts can coexist with a conflict relation; do not silently apply last-write-wins across people, projects or time ranges.

## 4. Default Local Storage and Markdown

The proposed local backend lives beneath the verified profile's `plugin-data/hermes-personal-agent/memory/`. It uses an owned SQLite database with:

- Record identity/revision/status, typed payload, source references and validity/scope metadata.
- A minimal mutation-event journal, idempotency receipts, tombstones and coverage/checkpoint watermarks.
- Rebuildable FTS indexes and projection-job state; optional embedding indexes remain derivative.
- Generated Markdown views for user profile, project/topic notes and episode summaries, with stable record IDs, revision and source links.

**SQLite is authoritative for this default backend; Markdown is a readable projection/export, not a second concurrent source of truth.** A commit atomically writes canonical changes, the event/receipt and projection jobs. Markdown is rendered afterward by atomic replace. A crash between DB commit and file rendering leaves a dirty projection that can be rebuilt; it does not revert the fact. Generated views display their revision/watermark and must not be silently treated as current when stale.

Every derived-artifact job carries its namespace retrieval epoch and covered record revisions/watermark. Publication must share a deterministic writer fence with corrections and forgetting: revalidate current revisions/tombstones while holding that fence through the local index commit or atomic file replacement. The forget operation commits suppression and purges under the same publication ordering, so a previously computed job cannot republish deleted text afterward. Checking only when a job starts, or marking a resurrected file stale for later repair, is insufficient. Cancellation discards pending output and private temporary files. Remote index publication needs generation-conditional writes or an equivalent proven fence; otherwise track/drain and reconcile older in-flight writes before the remote purge can be reported complete. Local suppression applies immediately while that remote outcome remains pending.

Manual Markdown edits can be imported only as explicit change proposals against the recorded base revision. Conflicting edits need review; arbitrary file edits do not become owner instructions, grant changes or immediate DB overwrites. Do not watch every Markdown file on the host, import another profile, or recursively index secret directories. Imported files have allowed roots, size/type limits and source labels.

Native MEMORY.md / USER.md are separate host-owned curated stores. The project may propose a bounded summary/index patch through the native memory tool when authorized, respecting write approval and capacity. It does not replace those files, bypass native staging, or claim its Markdown views are automatically loaded into Hermes's prompt. Optional native-summary failures do not erase committed project records.

Use tested private-file protections and explicit storage-platform support, not an unverified claim of encryption or same-UID isolation. SQLite is not encryption. Do not force WAL on filesystems where native compatibility rules disallow it; select and test a supported journal mode. Backup and retention include journal/sidecar and Markdown artifacts.

## 5. Versioned Records, Events and Receipts

Illustrative record, not an implemented schema:

```json
{
  "schema_version":"personal.memory.record.v1",
  "record_id":"mem_example",
  "revision":3,
  "namespace_id":"namespace_example",
  "kind":"semantic",
  "status":"confirmed",
  "subject_ref":"person_owner",
  "scope":{"project_refs":["project_example"],"data_class":"ordinary_preference"},
  "value":{"predicate":"weekly_report_language","value":"zh-CN"},
  "sources":[{"source_ref":"source_example","relation":"direct_user_statement"}],
  "valid_from":"2026-11-06T00:00:00Z",
  "valid_until":null,
  "supersedes":[],
  "index_revision":3
}
```

`namespace_id` is a server-bound storage/authority namespace, not a bearer credential or an inferred owner ID. Local trusted-profile and verified-owner namespaces are distinct modes. Claim fields supplied by a model are validated against the caller context and source authority, never accepted as authentication.

A source reference resolves to a native message/event, authorized connector object, explicit import or operator edit. Preserve issuer/account, author classification, original event ID, content hash and a minimal permitted excerpt when needed. Native row IDs can change when compaction carries/clones rows [M3]; bind stable host/source IDs where available and store enough lineage/hash evidence to resolve safely. An unresolved reference is `source_unavailable`, not a fabricated quote.

Events use stable `event_id`, namespace, operation ID, record ID, previous/new revision, event type, source references, policy epoch and committed sequence. Candidate states are `candidate → confirmed / inferred → superseded / retracted / expired`; forgetting adds a suppression/tombstone state distinct from expiration. Mutation ordering is by committed sequence, not client clocks.

An exact mutation retry with the same namespace/operation/key and payload hash returns its original receipt. Changed content under that key conflicts. Compare-and-set rejects stale record revisions. One source can yield several candidates; an extraction key additionally includes source revision, extractor/config version and candidate identity. Re-running extraction does not create duplicates or overwrite a human correction.

Event sourcing means reproducible current state from the retained lawful event/payload set, not eternal retention of deleted private text. Store payloads separately from minimal event metadata where necessary; purge/redact content and derivatives under the deletion policy. Checksums and identifiers may also be personal data and have retention rules. After a payload purge, replay preserves its tombstone without reconstructing the forgotten content.

## 6. Pluggable Backend Contract

The following methods and descriptors are project-owned proposals. They are not native Hermes APIs, an HTTP specification or a sandbox for third-party Python.

| Method | Required contract |
|---|---|
| `describe()` | Static version/capability metadata; no network, secrets or personal content |
| `open(bound_context, config)` | Bind one verified namespace and reviewed endpoint/credential references; reject unsupported capability/config combinations |
| `apply(mutation, expected_revision, idempotency_key)` | Durable canonical mutation or typed pending/unknown result; return record/event revision and commit receipt |
| `get(record_ids, read_scope, snapshot)` | Bounded current records, with revisions, deletion/expiry checks and source refs; no hidden widening |
| `search(query, filters, budget, snapshot)` | Bounded candidate records/snippets with score semantics and index watermark; stale/partial/unsupported is explicit |
| `changes(after_sequence, limit)` | Authorized bounded canonical changes, retention floor and next cursor; not raw transcript streaming |
| `checkpoint(coverage, idempotency_key)` | Record covered event/source range and durable evidence refs; success means the promised durability boundary passed |
| `export_snapshot(scope, watermark)` | Versioned portable manifest/records/sources/tombstones/receipts; no credentials or live grants |
| `import_snapshot(manifest, migration_id)` | Validate first, stage idempotently, preserve identity/provenance and require explicit activation |
| `health(local_only)` / `close(deadline)` | Redacted local readiness or explicitly allowed remote probe; bounded drain with unsaved/pending counts |

Descriptor fields include API/schema version, adapter version, durable-write/CAS/idempotency/snapshot support, supported memory kinds, exact deletion semantics, event retention, query languages/tokenizers, ranking units, maximum sizes, export format, checkpoint support, deployment mode and data recipients. `installed`, `configured`, `healthy`, `index_current` and `certified_for_mode` are different states.

Optional methods return `unsupported`, not empty success. Unknown major versions or required fields fail closed; compatible minor additions are negotiated. Namespace and endpoint selection come from trusted configuration, not model-supplied paths, URLs, SQL or plugin module strings. Provide a small adapter SDK, schema fixtures and conformance suite rather than asking users to copy internal service classes.

For authoring, propose the Python entry-point group `hermes_personal_agent.memory_backends` (a new project SDK mechanism, **not** a Hermes-defined group). An entry points to `create_backend(host, config)`, which returns an unopened instance implementing the negotiated interface. `host` supplies only scoped metadata, bounded logging/clock hooks and reviewed resource/secret resolvers; it does not grant an arbitrary owner or global DB handle. The bundled local adapter uses the same conformance suite. Enumerate entry-point metadata without importing modules, reject duplicate/reserved adapter IDs, then load only the explicitly selected reviewed package. Importing custom code itself executes code and is not sandboxed. Package/dependency admission follows the installation owner's supported Hermes environment workflow, not a runtime `pip install` shortcut. The optional native bridge is a separate real `hermes_agent.memory_providers` entry or directory provider [M11]; these two registration mechanisms must not be conflated.

A user-written backend may use different storage. To replace the canonical store, it must implement durable revisioned mutations, exact replay receipts, current-read/deletion semantics and portable export, or explicitly disable the unsupported modes. A search-only remote service is a **derived index adapter**, not a replacement canonical backend. The core keeps current policy, local suppression and operation tracking outside that search index.

For remote canonical storage, a local operation journal and remote commit cannot share a SQLite transaction. Use a pending operation/outbox, stable remote idempotency key, receipt query and reconciliation. Report `pending` or `unknown` until verified, never “saved” from HTTP acceptance alone. Do not read an unconfirmed new revision as committed. If the remote backend cannot prove current deletion/revision constraints, do not serve cached results in a strict mode.

## 7. Configuration and Safe Selection

Illustrative future configuration, **not a current plugin.yaml option**:

```json
{
  "schema_version":"personal.memory.config.v1",
  "enabled":false,
  "mode":"trusted_profile",
  "backend":{"adapter_id":"local_markdown_sqlite","adapter_api":"1","credential_ref":null},
  "native_bridge":{"enabled":false},
  "extraction":{"automatic":false,"default_state":"candidate","model_ref":null},
  "retrieval":{"token_budget":2400,"max_records":12,"query_timeout_ms":300},
  "network":{"allowed_destinations":[],"automatic_fallback":false},
  "checkpoint":{"required":false},
  "retention":{"raw_transcript_copy":false,"debug_content":false}
}
```

Numbers are proposed starting limits for benchmarking, not measured performance. A local query deadline is not a promise that arbitrary native/plugin code can be forcibly stopped; bound inputs, result size and concurrency, fence late results and report unfinished work.

Selecting a backend is an operator/user configuration action with a preview of affected profile, records, recipients, costs, credential handling and restart needs. No first-run scan or cloud upload is implied. Preserve the currently active backend until migration/activation succeeds. No silent provider fallback, fallback to another profile, or automatic download of model weights.

Discovery imports no arbitrary code. Admit reviewed packages through the supported Hermes installation/dependency flow; honor project-plugin opt-in and declared dependencies [M11]. Custom code runs with its host's privileges unless a verified isolation boundary says otherwise. Installation approval and data-sharing approval are separate; a read-only label does not prove network or filesystem containment.

## 8. Native MemoryProvider Bridge

When explicitly selected, the optional bridge implements the actual `MemoryProvider` ABC and uses the same service/backend as explicit tools, avoiding duplicate writers:

| Native method/hook | Bridge behavior |
|---|---|
| `is_available()` | Local configuration/dependency readiness only; no network probe or paid call |
| `initialize(session_id, **kwargs)` | Bind a fresh provider instance to the supplied Hermes home and runtime context; never rebind process-global personal state |
| `system_prompt_block()` | Small static usage/index guidance, not an ever-growing history dump |
| `prefetch(query, session_id=...)` | Authorized bounded context pack for the supported trust mode; safe empty/degraded result on ordinary lookup failure |
| `sync_turn(..., messages=..., turn_author=...)` | Queue source-bound candidates from eligible completed turns; avoid reingesting the full message list on each call |
| `on_turn_start(...)` | Observe current author/session metadata without promoting it to owner authority |
| `on_session_switch(...)` / `on_session_end(...)` | Rebind session coverage/cursors, reconcile durable work and respect real reset/branch/rewind boundaries |
| `on_pre_compress(...)` | Candidate extraction/evidence checkpoint according to negotiated v1/v2 semantics; never claim a durable checkpoint from a queued request |
| `get_tool_schemas()` / `handle_tool_call(...)` | Namespaced bounded commands through MemoryService and current policy; no core-name shadowing |
| `shutdown()` | Bounded drain, durable retry state and explicit abandoned/pending outcomes |

Native prefetch receives text/session metadata, not a universally authenticated owner/grant. `turn_author`, `user_id`, `caller_gsk`, profile names and `agent_context` do not independently prove permission. In trusted-profile mode, enable automatic recall only for the explicitly accepted single-user installation/session exposure boundary. In mixed-user or remote-owner mode, absent trusted current identity/scope means no protected automatic recall. Explicit tools are subject to their own verified native adapter, not an automatic workaround.

The manager suppresses relevant subagent hooks, but providers must still obey the contract for `cron` and other non-primary contexts [M6, M8]. This bridge defaults to no automatic canonical fact/skill changes from cron/workers. Permitted scheduled analysis may emit candidates tied to original sources through a separately approved domain path. A worker summary cannot become “the user said” or a new standing preference.

Non-primary automatic-fact restrictions do not make a required continuity checkpoint a no-op. Native v2 pre-compress hooks are not suppressed by the subagent turn-hook gate. For each enabled cron/subagent mode, either permit a narrowly scoped durable continuity/evidence checkpoint without promoting new semantic facts, or explicitly refuse strict compression. A checkpoint succeeds only when its reclaimed source coverage is durably resolved; an unpersisted source or queued save cannot count as covered.

The built-in memory store can remain alongside the single external bridge. Conversely, an existing third-party provider can remain active while project tools use the local backend; report which layer owns which record. Registering another native provider, pretending to be `builtin`, or hiding a multiprovider router is not the compatibility plan.

## 9. Continuous Conversations, Compaction and Scheduled Runs

Each invocation rebuilds a bounded working view from durable state rather than hoping the current prompt still contains everything. A proposed context pack includes relevant confirmed preferences, current task references/revisions, unresolved decisions, recent applicable episodes and compact source pointers. Small explicit follow-ups reuse the current task reference; a broad search for an empty greeting is unnecessary.

Native Hermes remains the transcript and compression owner. Do not add a competing context engine merely to install memory. The bridge tracks source/event coverage and task snapshot revisions across compression, branches and resets. A compaction summary is a derived aid, not direct-user evidence; never extract the same summary recursively as a new fact. Branches do not silently inherit all permissions or revise their parent's facts.

Before compaction, save a **working checkpoint** when supported: task IDs/revisions, goal/constraints, decisions, pending approvals/effects by reference, unresolved questions, completed extraction watermark, evidence ranges and remaining candidates. The checkpoint does not duplicate raw conversation or restore stale approval authority. Missing native durable source mapping is an explicit capability gap.

Strict `compression.checkpoint_required` is optional, default off, and requires a tested API v2 bridge [M7]. The bridge must commit its stated checkpoint before success; exceptions/timeouts block the affected compression when strict mode is armed. This may halt a full-context session when storage is unavailable, an explicit durability/availability trade-off. Do not enable it on unsupported native modes, including the pin's incompatible `codex_app_server` path. A non-strict failure reports degraded preservation and retains source references; it is not a successful checkpoint.

Scheduled work starts from its persistent goal, permitted namespace/task scope, current policy and last successful coverage watermark. It queries changed records and current task truth, rather than importing the main conversation wholesale. Native cron owns scheduling. Job creation, model costs, recipient access and delivery permissions remain separate. `skip_background_review=True` means a scheduled run is not guaranteed to perform the ordinary post-turn learning review.

After a restart, reconcile pending commits and extraction jobs from durable receipts/watermarks, then rebuild indexes/projections as needed. Do not replay uncertain external actions, make an expired grant current, or promise that provider async queues survived a crash. “Nothing found,” “index behind,” “source missing” and “backend unavailable” are distinct outcomes.

## 10. Retrieval and Token Budgets

The MemoryService, not provider prose, decides what may enter context:

1. Derive current trusted namespace, permitted record kinds/data classes and task/project scope before any external query or private payload fetch.
2. Resolve explicit task/record/source references first; query exact structured fields, time ranges and scoped FTS next. Optional vector/reranking is a later configured path.
3. Apply validity, tombstones, revision/index watermark and conflict checks; verify candidates against authoritative metadata before loading content. Recheck current access before returning the pack.
4. Rank by task relevance, explicitness, recency/validity and source quality. Preserve meaningful contradictions instead of hiding them behind one high score.
5. Deduplicate records/episodes/native summary overlap, pack to the negotiated budget and return expandable references for omitted detail.

Token accounting includes wrappers, citations and metadata. Use the selected model's tokenizer where available; otherwise use a conservative byte/character ceiling and label the estimate. Do not use an English words-to-tokens ratio for Chinese or promise exact counts without a compatible tokenizer. Reserve space for the user, tool results and output; the proposed 2,400-token memory budget may shrink but cannot silently grow to exhaust context.

Return `used_tokens` or estimated usage, budget, included record/revision/source refs, omitted count/reasons, index watermark, snapshot/cursor and degradation flags. Sensitive content must not appear in these diagnostics. A timeout can return a smaller proven-safe pack; it cannot bypass scope or serve revoked cached text. An empty authorized pack is preferable to unverified memory.

Do not bypass MemoryService by handing an unconstrained `session_search(profile=...)` call to a remote memory backend. Native cross-profile search remains available under the host's separate authority, so this plugin cannot claim to secure every native tool. Its own history adapter must explicitly restrict selected profiles, sessions and content classes [M4].

## 11. Chinese Retrieval and Quality

The default backend starts with ordinary structured filters and SQLite FTS. Detect actual tokenizer capabilities. Chinese names and one/two-character terms need explicit testing: native Hermes has trigram and optional CJK-bigram support, but that extension is not automatically installed into this plugin database [M12].

Use a tested CJK segmentation/bigram index or a bounded literal fallback for short terms; do not silently perform an unbounded full-table scan. Preserve original text and map normalized query tokens back to it. Traditional/simplified conversion, pinyin, aliases and entity linking are optional expansions, never silent identity merges. Similar personal names require evidence and scope, not embedding proximity.

Evaluate exact dates/numbers, mixed Chinese/English project names, homophones, short names, negation, temporal changes and same-name people. Compare FTS-only with any optional embedding/reranker on a fixed consented or synthetic corpus. Measure retrieval recall, answer evidence accuracy, stale-fact exposure, incorrect person merges and false memory writes separately; a fluent answer is not a recall benchmark.

## 12. Write, Correction and Forgetting Workflow

A model proposes candidates; deterministic service validation checks source/author, trust mode, sensitivity, scope, conflicts, limits and existing corrections. Explicit permitted “remember” instructions may commit a confirmed fact; inferred or third-party facts remain clearly labeled and cannot become authority. Automatic extraction is separately opt-in and uses bounded per-turn/per-day jobs and costs. No permanent preference is inferred from a one-off task choice without sufficient evidence.

A correction creates a new revision and links the superseded fact. Re-extraction of an old source cannot resurrect it: store source coverage and correction/tombstone precedence. Confidence is a provider/model estimate with a stated origin, not authentication. Candidate review exposes the exact proposed change and source references without requiring the user to read the whole history.

Forgetting first commits a local suppression/tombstone and advances the namespace retrieval epoch. New reads, cached packs, queued candidates and index queries must respect it immediately under the defined read-admission ordering. A result already admitted/delivered cannot be retracted. Then remove or redact canonical payloads, FTS/vector entries, generated Markdown, permitted source excerpts and remote replicas with per-destination receipts. Apply section 4's publication fence to every queued or in-flight derivative writer; do not report a destination purged while an older write can still restore its content. An offline remote store stays suppressed locally and reports `purge_pending`; no silent “deleted everywhere.”

Native transcript deletion and deletion at an original external service are separate authorized actions. Explain backup retention, provider retention, logs and practical secure-deletion limits. Export/import/restore must carry tombstones and suppression precedence so old backups do not repopulate forgotten facts. Keep only necessary non-content audit metadata under its own retention policy; do not retain full deleted payloads in an immutable event log.

## 13. Identity, Untrusted Content and Secrets

Trusted-profile mode inherits the [28](28-profile-first-local-conversations.md) single-user installation contract; it does not mint a verified remote owner. Host-authorized `LOCAL` controllers may be remote, and same-process/same-UID code is not isolated. Model tools require explicit session activation where specified in [29](29-session-scoped-task-tools.md). Neither native-memory configuration nor a copied profile directory silently activates project memory.

Verified-owner mode additionally requires its real host/issuer/tenant/actor bindings, current policy/grants and resource adoption. Scope every cache, operation key, index, provider tenant and background context by the bound namespace/authority. Profile names, paths, copied install IDs and record IDs are locators, not identity proofs. Cross-profile transfer is explicit migration/sharing, not a search convenience. Optional Primary Bot designation is a preferred coordination target, not memory ownership.

Retrieved content is untrusted evidence: fence/label it, preserve attribution, and never execute embedded instructions, URLs, scripts or claimed permissions. Source IDs and structured allowlists can restrict retrieval; they do not make a third-party statement true. Prompt injection detection is defense-in-depth, not authorization. Do not promote model summaries into system-level instructions or overwrite native SOUL/AGENTS policies.

Resolve credentials through reviewed native secret references, never memory bodies/config exports/model context/logs. Disclose external storage, embedding, extraction and reranking recipients separately; sending a query may itself reveal private information. Enforce endpoint/origin/TLS and redirect/SSRF rules. A local backend with cloud extraction still transmits data. No secret redaction promise is absolute; minimize content before transmission and test known sensitive patterns.

## 14. Migration, Replacement and Failure Recovery

Backend replacement is an explicit, previewed migration, not changing one setting and hoping both stores agree:

1. Verify source/destination capabilities, version, recipients, costs and required permission. Produce a dry-run manifest with selected namespaces, counts, types, references and unsupported fields.
2. Pause new memory mutations/extraction and fence the source writer. Complete or reconcile pending/unknown commits. Capture a consistent watermark plus canonical records, retained events, tombstones, correction relations and receipts. Carry the namespace publication fence and invalidate old-generation projection/index jobs at both ends.
3. Export portable JSON plus readable Markdown and attachment/reference manifests with hashes. Exclude credentials, live grants, authentication handles, active provider sessions and raw transcripts unless separately selected and permitted.
4. Import into an inactive destination idempotently by migration ID. Preserve stable record/source/event identity and provenance; validate counts, revisions, deletion precedence and unresolved references. Rebuild derivative indexes, never copy embedding vectors between incompatible models as if equivalent.
5. Run scoped sample queries and policy/deletion/recovery checks without enabling user traffic. Obtain explicit activation under the current epoch, switch the pointer once, and retire the source writer. Never automatically keep two authoritative writers.
6. Keep a bounded rollback plan and source retention decision. A rollback must incorporate changes/tombstones after cutover or stop for reconciliation; an old snapshot cannot erase a later correction or deletion.

Initial implementation uses stop-before-start single-authority migration, not active-active replication. If the source is unavailable or cannot be fenced, remain blocked/read-only as specified; no automatic clone takeover. Restored stores require a verified current authority and suppression ledger before serving private data. A copied database cannot prove its own freshness.

On local projection/index failure, canonical operations may remain committed while those derivatives are marked stale and rebuilt. On canonical storage failure, refuse new mutations rather than fall back to volatile memory with a false save receipt. Use bounded retry, stable operation identity and visible pending/unknown status. Deactivation stops new project admissions; it does not delete native memory, erase already transmitted data or uninstall another provider.

## 15. Cost, Latency and Observability

Default local CRUD/FTS/projection work uses no paid memory API. Extraction, summaries, embeddings, reranking, external storage and native-provider sync may consume model/API resources. Track per-operation and per-day budgets, model/price/config revision, estimated/reported/settled usage and unknown charges; do not treat a missing provider usage field as zero.

Prioritize user-facing retrieval. Coalesce background extraction by source watermark, limit concurrency, batch bounded updates and skip unchanged sources. Do not repeatedly send the entire conversation or re-embed unchanged records. Preserve FIFO dependencies for corrections/deletions; background work cannot overwrite a newer user decision. Native lifecycle callbacks must not block the conversation on slow remote extraction.

Measure p50/p95 cold/warm retrieval, context assembly, commit, projection lag and index lag on declared corpus/hardware/model. The illustrative 300 ms local query timeout is a proposed operating limit, not a measured result or universal SLA. Log redacted IDs, stage timings, counts, budget and degradation reasons by default, not queries, fact text, raw audio/transcripts or credentials.

## 16. Errors and Acceptance Matrix

Errors use `code`, `stage`, `operation_id`, `retryable`, optional `retry_after_ms`, `outcome_known`, and a bounded redacted message. Stable codes include `memory_disabled`, `scope_unavailable`, `permission_denied`, `capability_unavailable`, `revision_conflict`, `idempotency_conflict`, `budget_exhausted`, `index_stale`, `source_unavailable`, `checkpoint_unavailable`, `commit_unknown`, `purge_pending`, `migration_blocked`, and `backend_unavailable`. Raw provider exceptions are not user-visible data.

| Scenario | Required evidence |
|---|---|
| Default installation, existing external provider | No memory-store creation, ingestion, selection change, network or background job; external slot unchanged |
| Local backend, process restart | Committed records/receipts survive; Markdown/FTS rebuild from canonical state |
| Crash after commit before projection | Original receipt remains true; stale file is detected and repaired, not imported as newer state |
| Duplicate source/event and mutation retries | Exact dedup, changed-payload conflict, no duplicate candidate or lost correction |
| Concurrent correction/deletion/extraction | CAS and tombstone ordering prevent stale resurrection; pause an old projection/index job after payload read, finish forgetting, then resume it without restoring Markdown/FTS/vector content |
| Wrong profile/owner/tenant, copied IDs | No private retrieval or provider query before current scope validation |
| Malicious source or summary | Instructions stay evidence; no grant/task completion/SOUL mutation from recalled text |
| Long chat and repeated compression | Bounded context, resolvable source lineage, no recursive summary-as-fact drift |
| Required checkpoint absent/failing | Honest block at supported boundary, including cron/subagent continuity; no v2 success from no-op, queued/partial writes or unresolved source coverage |
| Cron/worker recall and candidate generation | Context-specific permissions and budgets; no automatic canonical writes from non-primary contexts |
| Lost remote ACK, eventual index, backend outage | Pending/unknown reconciliation, no blind duplicate mutation or unsafe cache fallback |
| Forgetting across cache/index/Markdown/provider/backup | Immediate local suppression, tracked remote purge and restore tombstones |
| Provider switch and failed cutover | Dry run, inactive import, single writer, stable IDs and safe rollback; no credential/grant copy |
| Chinese short terms, mixed scripts, conflicting names | Bounded query cost, measured recall and no unauthorized person merge |
| Token/latency/cost exhaustion | Smaller safe pack or explicit unavailable result; no automatic cloud escalation |
| Host/adapter upgrade and isolated mode | Exact ABI/config/lifecycle tests; unsupported IPC/dependency/authority modes remain disabled |

Run synthetic corpora and fake backends first, then approved real-data/provider/device probes. No source review, document check or unrelated local-task test completes these release gates. Ship a sample adapter and the same conformance suite for user-written adapters; passing unit fixtures does not certify malicious-code containment or every Hermes entry path.

## 17. Work Packages and Enablement Order

| ID | Milestone/status and dependencies | Deliverable |
|---|---|---|
| E0.9 Verify Memory Provider Contracts | M0; Backlog; E0.1/E0.2/E0.5 | Public loading/lifecycle/single-slot, profile/cron/worker, compression checkpoint and source-reference matrix; actual isolation gaps |
| E2.6 Define Pluggable Memory Contracts | M1; In Progress (local precursor); E0.9, local audit/data-classification/secret-reference contracts in E1.5 and applicable local E2.1/E2.2 contracts | Versioned backend/service, record/event/receipt/deletion semantics, SDK fixtures and trust-mode gates |
| E2.7 Build Local Memory Backend | M2; In Progress (local precursor); E2.6, local E2.1/E2.2 and applicable E8.1/E8.2 harness | SQLite canonical records/events/FTS, Markdown projections, correction/forgetting, bounded retrieval and explicit local commands |
| E2.8 Integrate Native Memory Lifecycle | M2; Backlog; E0.9/E2.6/E2.7 and applicable E6.8/E6.9 entry contracts | Optional single-slot bridge, consented candidates/recall, scheduled/compaction checkpoints, source coverage and budgets |
| E2.9 Validate Memory Migration and Recall | M3; Backlog; E2.7/E2.8, E8.1/E8.2/E8.3 harness | Adapter conformance, export/cutover/restore/delete fault tests and Chinese/long-horizon recall evaluation |

Existing E2.1/E2.2 schema and retrieval, E2.3 correction/forgetting/export, E2.4 disambiguation/associations and E2.5 optional-provider evaluation remain in their current Epic checklist; extend them rather than creating duplicate items. Memory does not block the already implemented local task loop. Verified remote-owner modes additionally require applicable E1.1–E1.4 and resource-adoption gates; HTTP, Primary Bot and voice dependencies apply only to those selected modes. A native provider bridge is optional, not a prerequisite for local explicit memory tools or permission to displace the user's existing provider.

Start with explicit local records and deterministic retrieval, add tested source-bound candidate extraction, then optional native lifecycle integration. Only add remote or vector backends with a concrete need and measured benefit. At initial design publication all packages were Backlog. E2.6/E2.7 now have the narrow In Progress precursor in [31](31-explicit-local-memory.md); other packages remain Backlog.

## 18. Pinned Evidence

- M1: [Bounded file store and snapshot](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/memory_tool_store.py#L177-L248).
- M2: [Prompt cache and compression reload](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/system_prompt.py#L802-L837).
- M3: [Transactional in-place archive and tail identity](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_state_messages.py#L907-L950) and [searchable compacted rows](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_state_search.py#L255-L280).
- M4: [Search modes/content/source limits](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/session_search_tool.py#L1-L48) and [explicit cross-profile read](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/session_search_tool.py#L603-L649).
- M5: [Single external-provider enforcement](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py#L283-L321).
- M6: [Provider lifecycle and profile contract](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_provider.py#L83-L199), [per-turn prefetch](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_context.py#L999-L1027) and [completed-turn sync](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/run_agent.py#L888-L917).
- M7: [Required checkpoint handling](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/conversation_compression.py#L2885-L2921), [v2 success requirement](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py#L701-L755), [default-off configuration](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/agent_init.py#L1415-L1437) and [unsupported app-server boundary](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/conversation_compression_checkpoint.py#L95-L107).
- M8: [Cron construction](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/scheduler.py#L2499-L2516), [context passed to providers](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/agent_init.py#L1155-L1166) and [subagent hook suppression](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py#L261-L266).
- M9: DSH [persisted domain objects](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/store.ts#L61-L90), [bounded references](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/resources.ts#L83-L115), [recovery](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/executor/dsh.ts#L520-L536) and [test-only memory repository](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/memory.ts#L1-L15).
- M10: [Memory nudge](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_context.py#L798-L808) and [post-turn review gates](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_finalizer.py#L591-L617).
- M11: [Actual provider installation and ABI guide](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/memory-provider-plugin.md).
- M12: [Native CJK index capabilities and fallbacks](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_state_fts.py#L1-L32).
