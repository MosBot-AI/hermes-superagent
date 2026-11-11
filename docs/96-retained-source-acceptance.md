# 96. Explicit retained-source acceptance

English | [简体中文](96-retained-source-acceptance-zh.md)

## Implemented boundary

The follow-on [explicit observed-source retention](98-observed-source-retention.md) adds native LOCAL commands and schema-13 migration with separate, honestly tagged `observed_native_snapshot` provenance. The account below describes the #133 receipt path and shared acceptance protocol; its legacy provenance, digests and historical outputs remain unchanged. “Not a native command” describes the original #133 slice, not the added #137 commands.

[Issue #133](https://github.com/MosBot-AI/hermes-superagent/issues/133) adds actual canonical SQLite acceptance of an explicitly retained original native source. This is an optional API-v1 Memory SDK operation family, with schema-12 writable migration and an isolated runnable consumer of the [receipt-bound source proposal](94-receipt-source-reads.md). It is not automatic ingestion, a new model tool, a native command, an HTTP route, host adoption, installation or production activation. The host compatibility pin remains `2281116525106e3c109993ccb5dc74d02bfc1427`.

The trusted local operator must separately authorize retaining the selected source as an independent snapshot and choose canonical retention: an explicit `expires_at` timestamp or explicit null. The required `retention: independent_snapshot` field records these import semantics; it does not authenticate a user or turn a model payload into permission. Both the SDK binding and canonical writer require the existing `explicit_local_operator` route. Model-bound and read-only writers cannot borrow this authority. Reviewed in-process Python remains trusted code, not a sandbox against fabricated sources or forged bindings.

## Sources remain evidence

The isolated consumer reads one exact original row from a receipt-bound native read snapshot. It does not treat compaction summaries as direct sources or import an entire transcript. The selected content must fit the existing 2,048-character canonical record limit. Importing a row preserves its original `user` or `assistant` role, exact content fingerprint, stable source identity and native receipt identity. A source identity is independent of the acceptance request key, consumer ID and receipt attempt, so changing these cannot turn the same selected original into a fresh source.

The canonical record's existing `source` field still identifies its latest editing route, `explicit_local_operator`; it never claimed immutable original authorship. The separate immutable decision provenance has `kind: retained_native_snapshot` and retains the original role and source metadata. Inspect it through `source_status`, alongside the canonical record's current revision/status/expiry. Neither a user-role row, matching substring, fingerprint nor successful receipt establishes factual truth, verified human authorship or authority. Imported text remains untrusted evidence, including when recalled.

A source fingerprint is SHA-256 of exact UTF-8 content, matching existing current-input candidate suppression. Whitespace or content changes create a different exact fingerprint. This is not semantic duplicate detection, anonymity, secret storage or complete person/source identity resolution. Trusted callers must bind the correct native store and profile; arbitrary source metadata is not a lookup API or permission to open another store.

## One pending slot, then an actual acceptance transaction

The optional capability is `retained_source_acceptance`. Existing CRUD-only adapters remain compatible and explicitly refuse unsupported operations. No dynamic adapter loader, provider selection or REST contract changes are introduced.

1. Prepare the complete import request and retain the pure `source_request_identity` result before admission. The normalized digest binds content, topic, explicit retention, source provenance, consumer, expected source sequence and request key. The identity contains only the key and digest, not original text, and grants no authority.
2. `source_stage` durably reserves the next slot for that consumer. Only bounded metadata and the request digest are stored; no new copy of content, topic or session label is retained in the staging table. Staging creates no canonical record/event and advances no cursor. Only one unresolved slot can exist per consumer. A second key is refused while that slot is pending, including after restart.
3. `source_accept` must match the already staged request exactly. Under the canonical `BEGIN IMMEDIATE` writer lock, it checks source suppression, creates the canonical record/event/receipt, records retained-source lineage and resolves the slot. The source cursor advances with that same canonical commit. It does not reuse the current-input candidate route or manufacture a candidate anchor.
4. `source_discard` explicitly resolves the exact pending key/digest without creating a record. It suppresses that exact source fingerprint and clears matching pending current-input drafts. The discarded decision remains terminal and advances this consumer's source cursor. It is not an automatic skip or a cancellation of a different in-flight writer.
5. `source_status` reads an exact saved key/digest, without mutation replay or source text. `source_cursor` reports that consumer's completed sequence and any pending slot. Neither creates, migrates or writes storage when used with the supported existing read-only opener.

All decisions and suppression metadata are retained, with at most 1,000 decisions and 64 consumers, and no silent eviction. Limits refuse new admissions; existing acceptance, discard and canonical forgetting do not need another decision/suppression allocation. A metadata-only pending slot has no automatic expiry or timeout-based release. The caller owns any authorized retained payload needed to finish acceptance and may explicitly discard an unfinishable slot.

## Three different progress domains

The source cursor is the contiguous sequence of this consumer's explicitly admitted decisions, each resolved by acceptance or discard. It is derived from validated durable rows in the same canonical transaction; a pending row stops later admission. It is not a native row ID, native receipt-journal offset, canonical record-event cursor or measure of all native history. Ordinary `remember`, `correct` and `forget` do not advance it. Existing `consumer_advance` remains local record-event accounting and cannot resolve a source slot.

An absent status means only absent in the inspected snapshot. An older attempted admission can still acquire the writer lock later. Retain and reconcile the original key; do not interpret absence as permission to substitute a new key or source. The enforced pending-slot guarantee begins at committed admission, not at an unobserved caller-side attempt or network request.

## Retry, correction and forgetting

A repeated exact stage observes the existing decision. Exact accepted/discarded retries return historical decision receipts without making another record, advancing a cursor twice or restoring payload. Changed request content, provenance, retention or sequence under the same key is an idempotency conflict. A different key for an already admitted source identity is refused. Internal canonical receipt keys are checked for collisions before creating lineage, so unrelated historical records cannot be silently relabeled.

Canonical correction and forgetting mark retained-source suppression in the same writer transaction and remove matching pending current-input drafts. Acceptance checks both retained-source and current-input suppression inside its writer transaction. A fresh key, consumer or native receipt cannot bypass exact source identity/fingerprint suppression. Suppression capacity is reserved by the existing decision row, so exhausted admission quota cannot prevent forgetting. Canonical retention cleanup uses the same terminal forget path.

`source_status` separates the historical decision's original `remember` receipt from current canonical metadata. An old accepted receipt may still say `active` while the current record is corrected, expired or forgotten. Status exposes no record content/topic/session label. Fingerprints and identifiers still need private handling. SDK construction retains its ordinary bounded export admission check, which can read payload; the metadata-only promise applies to the source status/cursor operation, not the entire SDK lifetime.

## Independent-store and privacy limits

The native source read/receipt, canonical admission/acceptance and any caller-owned retained payload have separate lifetimes. This implementation does not claim a distributed transaction or that a native source stays current until canonical publication. An independently authorized snapshot can be accepted after later native transcript deletion. That deletion does not automatically forget its canonical record; the operator must use canonical correction/forgetting when appropriate. Conversely, canonical forgetting does not erase native transcript rows, historical backups, exports, caller-held payloads or previously returned model context.

The isolated consumer and tests use the review-only host proposal. They do not patch an installed host, enable checkpoint-v2, install/activate a provider or call a model. Automatic source selection, background extraction, full native source coverage, publication fencing for a current-source-validity mode and complete #43/#45 acceptance remain open. Raw database edits, malicious Python adapters and replacement with old backup files are outside the supported integrity boundary; metadata validation is fail-closed evidence checking, not tamper-proof storage.

## Verification

The optional `run_retained_source_conformance(factory, isolated_synthetic=True)` suite uses a dedicated empty synthetic store. It exercises actual stage/accept/discard, reopen, independent cursor behavior, historical retries and forgetting. Unit tests cover SDK capability/scope admission, bounded malformed requests/results, canonical suppression, migration, transaction failures, real subprocess exits around COMMIT and concurrent writers. The isolated source proposal tests exercise real native and canonical SQLite stores, including source deletion after explicitly authorized capture.

Run the [development checks](../README.md#development-checks) and the source proposal's separate harness. The PR records executed counts, exact commits, independent review and package evidence. Test presence alone is not passing evidence, a production release or full native lifecycle acceptance.
