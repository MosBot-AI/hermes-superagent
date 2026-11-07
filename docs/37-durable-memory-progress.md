# 37. Durable Local Memory Progress

English | [简体中文](37-durable-memory-progress-zh.md)

Status: implemented bounded event-metadata reads and durable internal consumer cursors. This supplies restart/retry groundwork for later local projection and lifecycle workers. It does not implement a background worker, native MemoryProvider bridge or a successful native pre-compression checkpoint. The backend still declares `checkpoint` unsupported.

## 1. Read the Metadata Change Feed

With the existing [local memory configuration](31-explicit-local-memory.md), a trusted native LOCAL session can read:

```text
/personal-memory changes --after-sequence 0 --limit 20
/personal-memory changes --after-sequence 20 --through-sequence 42 --limit 20
```

Use actual sequence values from the first response, not these illustrative numbers. The command returns only committed event sequence, record ID, record revision and operation (`remember`, `correct`, `forget`). It does not return old or current content, topic, session/source labels, request keys or content digests. An old `remember` event is historical metadata, not a claim that the record is still active. Forgotten payload cannot be reconstructed from this feed. IDs and operation metadata can still be personal information and enter normal host command history.

`limit` defaults to 20 and accepts 1–50. `after_sequence` defaults to zero; `through_sequence` defaults to the current committed event watermark. The returned upper bound can be reused for later pages while other writes continue. `next_sequence` is the last returned sequence, or the unchanged lower bound for an empty page. `has_more` refers only to that upper bound. `current_watermark` may be higher on later pages. Records and watermark for each page are read in one transaction; the feed does not create a frozen snapshot of payload text.

Negative, non-integer, future, reversed or unknown nonzero sequence anchors fail explicitly. The retained event stream currently has no pruning, so `retention_floor` is zero. Record/event quotas remain unchanged. Namespace/profile ownership is bound by the existing storage opener, not by caller-selected paths or model arguments. This action is not added to the model tool schema.

## 2. Internal Consumer Cursor Contract

Trusted local code can use `MemoryService.execute("consumer_get", {"consumer_id": "projection"})` to inspect progress. An unknown consumer returns revision/sequence zero and `registered: false` without creating state. IDs are bounded lowercase slugs, not human identities, grants or native session names. There is no cursor-write slash command, model action or registered background hook.

Illustrative internal advance request:

```json
{"consumer_id":"projection","expected_revision":0,"through_sequence":42,"request_id":"projection-pass-1"}
```

Pass this to `consumer_advance` only after the consumer has completed the work it intends to acknowledge. Revision zero creates the cursor; subsequent changes must match the current revision and strictly increase the sequence. The sequence must be zero or an existing committed record-event sequence and cannot be in the future. State update and metadata-only receipt commit in one `BEGIN IMMEDIATE` transaction with the store's existing durability settings. An operator-bound backend is required even to replay a prior advance. A model-bound backend is denied before receipt lookup.

An identical request key and payload returns the original historical receipt. A different payload under that key conflicts. Old receipt replay never rewinds the live cursor. Consumer keys share a separate receipt namespace from memory record mutation keys. After any uncertain result, reconcile using the same key and `consumer_get`; a failure response alone does not prove no commit occurred. Never blindly use a new key or reset progress.

There are at most 32 consumers and 10,000 cursor mutation receipts per store. Exact retries remain available at quota. Cursor quota exhaustion does not prevent canonical record correction or terminal forgetting under their separate quotas. No cursor deletion, pruning or automatic reset is added.

## 3. What a Cursor Does Not Prove

A cursor is explicitly `caller_reported_local_record_progress_not_native_checkpoint`. The store proves only that the progress record and its receipt were durably committed. It does not prove the caller read every event, successfully published a file, completed an external effect, captured a native conversation, preserved pending approvals or resolved source evidence.

A consumer must not advance past unprocessed work. Any future projection publisher must separately fence output against current record revisions and tombstones, then coordinate publication/recovery with progress acknowledgement. Advancing a scalar cannot make a stale output safe. There is no atomic transaction with remote systems or generated files in this slice, and no authority can be recovered from a cursor.

The full [memory lifecycle design](30-pluggable-memory-contracts.md) still requires verified source coverage, explicit bridge selection, permitted modes, bounded shutdown and real native checkpoint-v2 contracts. Strict compression must remain unavailable rather than treating these cursors as that guarantee. Existing native providers, configuration and model routing are unchanged; no automatic external transmission is introduced.

## 4. Storage Upgrade and Compatibility

The exact owned memory database advances to schema v3 with `consumer_cursors` and `consumer_receipts`. A v2 upgrade adds those tables atomically. A v1 upgrade first applies the existing provenance migration and then adds both tables in the same transaction. Namespace/application/schema checks are repeated under the writer lock. Unknown, modified or foreign schemas fail closed. Failure creating either progress table rolls back the entire upgrade, including the v1 record-table rebuild.

Existing record IDs, revisions, latest source labels, tombstones, ordering high-water marks, event rows and exact original receipt bytes/digests are retained. Even a read-only first open can perform the upgrade. Back up private plugin data before upgrading; earlier builds reject v3. There is no downgrade or portable restoration protocol. Do not replace current data with an old backup that revives forgotten payload or rewinds processed events.

The optional descriptor capabilities are `metadata_changes` and `durable_consumer_cursor`. Service admission additionally requires durable writes, CAS and idempotency for advancement, and checks ordinary page limits before invoking the backend. Missing capability fails without fallback. The descriptor API remains v1; the storage schema version is separately v3. This is not the full public adapter SDK.

## 5. Verification and Remaining Work

Synthetic tests cover bounded/frozen pages, deletion-safe metadata, exact retries, stale/regressive/future rejection, independent consumers, quotas, same-key and competing-key concurrency, transaction rollback, uncertain post-commit recovery, snapshot contention and exact v1/v2 migration. Native contracts exercise the actual slash dispatcher, owner admission, unchanged provider configuration and four guarded fresh processes retaining cursor progress through correction/forgetting and old-receipt replay. Activated model tools reject the new internal actions.

No live model, external account, socket listener, scheduled job or production profile is used. E2.7 gains local durability groundwork. Native lifecycle E2.8, checkpoint evidence coverage, projection fencing, full export/import and E2.9 recovery acceptance remain unfinished.
