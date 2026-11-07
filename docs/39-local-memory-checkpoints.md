# 39. Local Memory Metadata Checkpoints

English | [简体中文](39-local-memory-checkpoints-zh.md)

Follow-on: [45](45-explicit-memory-expiry.md) upgrades owned stores to schema v5 while preserving checkpoint receipts. A metadata checkpoint certifies stored revisions/events/statuses, not time-valid recall eligibility. Time passage alone causes no event or revision and need not make a checkpoint stale.

Status: implemented explicit metadata-only checkpoints for the local record store. These add verified event/current-record linkage and durable recovery markers beyond the caller-reported [consumer cursors](37-durable-memory-progress.md). They do not checkpoint a native conversation, produce a backup, publish projections, perform extraction or satisfy Hermes required checkpoint-v2. The generic `checkpoint` and `native_lifecycle` backend capabilities remain unsupported.

## 1. Capture and Inspect

With [local memory](31-explicit-local-memory.md) explicitly enabled, use the existing trusted native LOCAL session:

```text
/personal-memory changes
/personal-memory checkpoint --expected-watermark 2 --request-id checkpoint-pass-1
/personal-memory checkpoint-status CHECKPOINT_ID
```

Replace `2` with the current watermark from `changes`, and `CHECKPOINT_ID` with the UUID returned by capture. A checkpoint validates and captures the current retained record-event metadata within one `BEGIN IMMEDIATE` transaction. It checks that each record begins with `remember`, subsequent revisions increase by one, terminal forgetting is not followed by another mutation, and every current record revision/status agrees with its final event. The bounded scan covers at most 1,000 records and 11,000 events, including at most 10,000 nonterminal mutations. Inconsistent or over-limit state fails without a checkpoint receipt.

The expected watermark is required. If a correction, forgetting or new record commits after observation and before capture, `watermark_conflict` rejects the attempt. Read the latest state before choosing a new request; do not claim the old observation was captured. Empty stores may capture watermark zero. This is a record-state fence, not an assertion that a consumer processed any events.

The receipt contains a checkpoint UUID, request ID, event watermark, record/event counts, active/forgotten counts and a SHA-256 of ordered record IDs/revisions/statuses and event metadata. It contains no record content, content hash, topic, source label or session identifier. The hash is not an authentication signature and does not check payload integrity. Metadata identifiers and hashes can still be personal information. The receipt explicitly reports `restorable: false` and `native_checkpoint: false`.

## 2. Historical Receipts and Current Status

Capture and its receipt commit together using the existing SQLite durability settings. An exact retry returns the original immutable receipt with `replayed: true`, even if later writes have changed the store. A different expected watermark under the same request ID returns `idempotency_conflict`. Request IDs have a separate namespace from canonical edits and consumer progress. A generated key is echoed by the command; after an uncertain result, reuse the original key and payload rather than inventing a replacement.

`checkpoint-status` recomputes metadata in one read snapshot and reports `is_current` plus `current_watermark`. Later canonical changes make older markers stale; consumer-cursor changes do not. This status is true only for that read snapshot and may become stale immediately afterward. An already returned result cannot be retracted. Reading an unknown UUID returns `checkpoint_not_found`, not an empty success. Neither replay nor status changes or restores records.

There are at most 256 immutable checkpoint receipts per store. Exact retries still work at quota. `checkpoint_limit` does not block canonical correction/forgetting or reading existing markers. No deletion, pruning, automatic checkpoint scheduling or reset is implemented. Do not use repeated checkpoint creation as an unbounded heartbeat.

## 3. Scope and Future Lifecycle Work

Creation requires the existing trusted operator-bound backend before any replay lookup. Model-bound backends cannot create or replay these receipts. The new create/status actions are absent from model tool schemas and do not become available through task or memory tool activation. The slash command retains native host session admission and the profile/private-file checks of the explicit local memory lane; it is not verified remote-owner identity.

Internal reviewed adapters negotiate the optional `local_metadata_checkpoint` capability; creation also needs durable writes, CAS and idempotency. Internal operations are `checkpoint_create` with `expected_watermark` and `request_id`, and `checkpoint_status` with `checkpoint_id`. This does not add a provider loader or the proposed public lifecycle SDK.

These markers do not preserve native source/message ranges, pending approvals, task truth, effects, Markdown files or personal payloads. They cannot recover forgotten text, authorize actions, prove external publication, detect a complete old database restore, or protect against same-UID tampering. Old backups remain subject to the unresolved suppression/restore protocol. No native provider is selected or displaced, no host memory files are edited, and strict native pre-compression checkpoint success remains unavailable. Native source coverage, optional bridge selection, shutdown/drain semantics and projection publication fencing remain separate work.

## 4. Schema and Verification

The owned SQLite memory schema advances from v3 to v4 by adding `record_checkpoints`. Exact v1/v2 databases first receive their prior migrations, then the checkpoint table, within the same writer transaction. Namespace and exact schema are checked before and under the writer lock. Failures roll back the entire migration. Existing canonical data, tombstones, event ordering, consumer state and original receipt bytes stay unchanged. A read open can perform this migration; earlier builds reject v4. Back up private plugin data before upgrading, but do not overwrite current data with an old backup that revives forgotten text.

Synthetic tests cover empty/current/stale markers, correction/forgetting, bounded metadata privacy, missing capabilities, strict input validation, quota isolation, simultaneous same-key requests, writer contention, rollback and uncertain-commit recovery. Exact migration tests include preserved v3 consumer receipts and rollback from v1/v2/v3. Native dispatch tests verify host admission and unchanged provider configuration. Fresh guarded processes exercise restart, stale detection, model-action refusal and historical replay after terminal forgetting.

These are offline store and native dispatcher contracts, not real-model or native lifecycle acceptance. No live provider, account, socket listener, production profile or remote write is used.
