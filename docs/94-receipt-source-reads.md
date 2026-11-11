# 94. Review-only receipt-bound original-source reads

English | [简体中文](94-receipt-source-reads-zh.md)

## Status and value

[Issue #129](https://github.com/MosBot-AI/hermes-superagent/issues/129) extends the [host receipt proposal](92-native-checkpoint-sources.md) and [consumer recovery journal](93-source-receipt-recovery.md) after merged [PR #128](https://github.com/MosBot-AI/hermes-superagent/pull/128). Historical accounting does not provide the original text needed by a future source-bound consumer. Reading receipt status and source text separately can combine incompatible observations across deletion or correction.

The isolated proposal adds `read_receipt_sources(db, session_id, attempt_id, expected_receipt_id)`. It reads receipt validity, exact membership and original source rows within one native SQLite read snapshot. The explicit test consumer opens a read-only native store and invokes that operation; it neither consumes the recovery journal nor saves returned text.

This is review-only, unsubmitted and inactive. It is not a shipping memory provider or automatic capture path. Hermes remains pinned to `2281116525106e3c109993ccb5dc74d02bfc1427`, the shipping provider stays API v1, and parent #43/#45 remain open. No canonical memory acceptance, cursor advancement, provider-v2 checkpoint, background reader, REST surface, model call, installation or release is enabled.

## Binding and results

The trusted caller supplies the exact `SessionDB`, current session, attempt and expected receipt hash. The operation has no request-selected file path, SQL or source-row selector. A well-formed expected hash that does not match the bound receipt raises the fixed `receipt_mismatch` error without returning source text. Invalid caller arguments raise a fixed safe request error. Identifiers and hashes are private metadata, not human authentication, authorization or anonymous publication-safe data.

- `available_at_snapshot`: `available` is true, with the exact receipt ID and complete `sources` list. Each source contains `row_id`, `role`, `content`, `message_uid` and `absorbed_message_uids`, ordered by native row ID. Content is the original decoded plain text. Separate native rows remain separate, including rows represented by a merged user candidate during preparation. Generated compaction summaries are never reconstructed as original evidence.
- `absent`: no matching receipt exists in that snapshot. No source payload is returned and missing receipt schema is not created.
- `invalidated_or_unknown`: receipt/source validity cannot be established, including ordinary source mutation or deletion. No partial source payload is returned.
- `unavailable`: storage, schema, decoding or bounded-output validation failed. The result contains no source payload or raw backend exception text.

Every result reports `durable_memory_checkpoint: false`. Availability is an observation, not a canonical write, memory cursor, delivery receipt or continuing authorization. The caller must separately establish permission to read, retain, use or transmit source material. Source text remains untrusted evidence rather than instructions or proof of authorship or truth.

## Bounds and deletion boundary

A successful read admits at most 256 original rows, 1,024 aggregate message identities, 16,384 decoded content characters per row and 65,536 content characters in total. Serialized lineage is at most 36,866 characters. Raw row string-character and byte-value lengths are limited to 262,144 per row and 2,097,152 in total. The canonical ASCII-encoded JSON result is limited to 1,500,000 bytes. Rows are accepted all-or-none. These are post-read admission/output limits, not a guarantee that the native SQLite driver never allocates larger inputs.

The existing persisted update/delete triggers continue to invalidate receipts. A mutation committed before the next read snapshot prevents fresh source return. Under WAL, a deletion committed while a reader holds an earlier snapshot can coexist with a complete historical result. The next read observes invalidation. When native safety checks select DELETE journal mode, the reader snapshot can block a concurrent writer commit; after the snapshot is released, that writer can finish and the next read observes the mutation. A read-side lock timeout is an unavailable read, never partial success. The harness respects the native journal-mode decision and exercises both native-selected mode and explicitly configured DELETE mode without forcing WAL past a safety gate. The operation never mixes a pre-deletion status with post-deletion rows and never restores deleted payload. Deletion after a result was returned cannot retract copies already held by a caller, model context, logs, exports or backups. This is neither secure erasure nor a fence between source read and a later memory write.

The trusted native-store assumptions remain unchanged: raw schema tampering, malicious in-process code, manual replacement, clones and backup rollback are outside the contract. A bound receipt is not a capability token. Receipt and journal metadata are not a second transcript archive; this operation introduces no durable payload store.

## Verification and next gates

Use the [artifact reproduction instructions](../experiments/native-checkpoint-sources/README.md#reproduce-safely). The manifest binds the staged host patch, reader consumer and new source-read test file. The isolated CI job runs proposal tests against a separately patched disposable host, followed by selected native regressions. Production runtime packaging continues to exclude the experiment.

Tests use real temporary native SQLite stores with synthetic text. Coverage includes exact receipt/session binding, restart, native row ordering and merged-user inputs, missing sources, mutation/deletion before and during reads, bounded output, malformed storage and no-schema-creation behavior. Actual executed counts are recorded in the manifest and PR evidence; test presence alone does not establish a passing run. Full upstream, real-model and production-provider acceptance are separate and not claimed.

A later memory consumer still needs explicit retention/acceptance authorization, deletion suppression across publication, durable memory outcomes and cursor advancement. A source read and an independently committed memory write are not an atomic cross-store transaction. This slice deliberately does not close those gates.
