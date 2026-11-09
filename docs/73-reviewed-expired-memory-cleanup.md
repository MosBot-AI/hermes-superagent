# Reviewed expired-memory cleanup

English | [简体中文](73-reviewed-expired-memory-cleanup-zh.md)

## Purpose and explicit workflow

[Expiry](45-explicit-memory-expiry.md) excludes a record from fresh recall when its deadline passes, but leaves its active canonical payload stored. This operator-only workflow previews a bounded set of already-expired records and explicitly forgets exactly the reviewed batch. It does not infer a retention period, schedule deletion or turn expiry into an automatic stored-state transition.

```text
/personal-memory expired-preview --before 2026-11-01T00:00:00Z --limit 10
/personal-memory forget-expired --before 2026-11-01T00:00:00Z --limit 10 --expected-snapshot SHA256 --request-id expired-cleanup-1
```

The cutoff above is synthetic. Choose an actual cutoff that is no later than the trusted current UTC time, review the complete preview, and substitute its snapshot digest for SHA256. Keep the same cutoff and limit on apply. The limit defaults to 10 and must be between 1 and 20. Apply requires an explicit stable request ID; it does not generate one. Each subsequent batch needs a fresh preview, its own digest and a new request ID; applying an old request never means “forget the next batch.” An empty selection cannot be applied.

Both successful native operations deliberately retain complete structured output in the `personal.local-memory.v1` envelope, including when the native workbench normally uses readable text. No review field is simplified away. Scripts should still put `--json` before the operation for stable structured errors as well as results. These operations are available only through the explicit local operator CLI/native route under the existing trusted single-user profile boundary. They do not add model-tool operations, change model-tool schemas, activate a provider, call a model, or authorize remote access.

## What the preview binds

`--before` accepts only a valid canonical UTC second, `YYYY-MM-DDTHH:MM:SSZ`; local times, offsets, fractional seconds, date-only values and relative durations are rejected. Trusted evaluation time is captured after acquiring the database snapshot, not before a lock wait; apply holds the shared writer fence. A new request refuses a cutoff later than that time. A clock rollback can therefore make a previously valid but unapplied cutoff temporarily invalid; it does not permit forgetting future records.

Eligible records are still active, have an explicit expiry, and satisfy `expires_at <= before`. The cutoff is inclusive. Records with no expiry, a later expiry or forgotten status are not selected. Selection is ordered by expiry ascending, then creation sequence. The preview data uses `personal.memory.expired-preview.v1`. It includes every selected record's complete content and metadata in `items`, `eligible_count`, `selected_count`, `remaining_count`, the canonical event `watermark`, `evaluated_at` and a SHA-256 `snapshot` digest. Review the text and metadata, not merely the count or digest. Stored prose is untrusted data, not instructions, authorization or proof of authorship.

The digest binds the namespace, fixed cutoff, limit, canonical event watermark, ordered eligible record identities and selected records. Evaluation time is reported but is not part of that digest. Thus ordinary time passage does not silently widen the reviewed set or invalidate a still-valid fixed-cutoff review. A supported canonical mutation advances the watermark and makes an earlier preview stale, including a mutation to a record outside the selected batch. Apply reselects and rechecks the digest under the writer fence; it never silently rebases a changed preview.

The complete preview data has a 64,000-character ASCII-JSON serialization budget. This is not a token budget. Escaping can make non-ASCII text cost more than its visible character count. A batch that exceeds the budget fails closed with `retention_preview_too_large` and guidance to lower the limit; neither record content nor metadata is truncated or silently omitted to fit. Obtain and review a fresh smaller preview instead of applying a partial display.

## Forgetting and historical retries

Apply uses one shared SQLite writer transaction and the ordinary forget path for every selected record. Successful commit clears canonical content, topic, source/session metadata and expiry; writes terminal tombstones and ordinary forget events; removes the selected records from FTS; and saves a metadata-only batch receipt together. The whole database batch commits or rolls back. Forgotten IDs cannot be corrected back into active records.

Keep the apply request ID, cutoff, limit and expected snapshot unchanged when retrying an uncertain result. An exact successful retry returns its historical receipt before checking current time or selecting records. It does not forget another batch, replay file cleanup or claim the original targets' current state. A changed payload under an existing key conflicts. For a new batch, inspect current state, obtain a new preview and use a new key. No empty no-op batch receipt is created.

The receipt uses `personal.memory.expired-forget.v1` and contains `forgotten_count`, the historical `remaining_count`, previous/final watermarks and ordinary per-record forget receipts, rather than forgotten text. Records, events and receipts retain IDs, ordering/revision information, timestamps and digests needed for terminality and safe retries. These can still be personal metadata. This is logical forgetting, not removal of tombstones or history metadata, and it does not free the existing total-record capacity.

## Managed files and failure recovery

The ordinary forgetting safeguards also apply to an enabled [private projection](68-private-memory-projection.md) and an active [correction draft](70-private-memory-edit-drafts.md) targeting a selected record. Known generated projection/staging files must be invalidated, and the registered target draft/staging must be removed, including manual draft edits. Drafts for other targets and new-record drafts are not silently consumed. Existing ownership, permissions, link and unknown-file checks remain enforced. A backend without the required file adapter cannot bypass managed-file cleanup.

The writer fence orders cleanup against projection refresh, draft publication and concurrent canonical changes, so an older publisher cannot republish a successfully forgotten record. Cleanup failures prevent database commit. However, **SQLite and the filesystem are not one atomic resource**: earlier file removals cannot be rolled back if later cleanup or the database transaction fails. Canonical records may remain active while a projection or registered draft file is missing. Do not infer that records were forgotten just because a file disappeared.

After an error or interruption, inspect current canonical state and the relevant projection/draft status before deciding what to do. Reuse the original key and identical arguments for an uncertain apply; do not generate a fresh key as a retry. A missing projection can be rebuilt by an explicit refresh from current canonical records. A ready draft with a missing file is not silently reconstructed, because that could discard the operator's edits; explicit discard clears the registration. Follow the projection and edit-draft recovery guides for interrupted publication and unsafe or unknown files. A historical cleanup retry does not remove unknown replacement files.

## Scope and verification boundary

This slice introduces no new schema version or model-tool contract. Schema v10 remains current. The adapter advertises the optional `reviewed_expired_cleanup` capability; adapters without it do not silently receive these operations. Existing safe storage, namespace, migration and operator admission requirements continue to apply. Unlike index maintenance, these commands use the ordinary compatible writable opener, which may initialize or migrate a supported owned store; neither is a read-only-provider operation. It does not install or deploy the plugin, choose a provider, enable automatic retention cleanup, remove tombstones, compact capacity, restore backups, or suppress extraction of the same fact from a source. A new explicit capture remains a separate action.

Forgetting cannot retract host conversation history, previously returned results, already-open file descriptors, editor buffers, exports, copies, backups or provider-held context. SQLite and FTS cleanup are not guaranteed physical-media erasure. Previewing complete text may itself place it in ordinary host history. Do not use this plaintext memory workflow for secrets.

Verification must cover exact cutoff equality and future-cutoff refusal; null/future/forgotten exclusions; stable ordering, counts and complete bounded previews; stale snapshots after corrections, expiry changes or unrelated canonical writes; clock movement and post-lock evaluation; exact historical retries, request collisions and empty-apply refusal; atomic multi-record events/FTS/tombstones; managed-file cleanup, transaction failures and abrupt-process recovery; and native operator admission with unchanged model-tool refusal. Check the linked PR for completed test results and the exact compatibility revision. Synthetic profiles and fault injection are not live-user or production acceptance, and this bounded #44 slice does not complete the broader memory roadmap.
