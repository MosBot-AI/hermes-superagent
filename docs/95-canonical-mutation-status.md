# 95. Read-only canonical mutation outcomes

English | [简体中文](95-canonical-mutation-status-zh.md)

## Scope and value

[Issue #131](https://github.com/MosBot-AI/hermes-superagent/issues/131) adds an optional read-only result inspection operation to the trusted-local [Memory SDK](85-local-memory-sdk.md). An interrupted `remember`, `correct` or `forget` can already have committed even when its caller received no usable acknowledgement. Inspection lets a caller recover the canonical receipt using previously retained request metadata, without resupplying the original text or executing a mutation again.

The existing SQLite store remains authoritative. This is an additive API-v1 capability, with no schema migration, new database, provider selection or native lifecycle hook. CRUD-only adapters remain supported. No new native command, model tool or REST route exposes the operation. The Hermes compatibility pin remains `2281116525106e3c109993ccb5dc74d02bfc1427`.

This result primitive is a prerequisite for future source acceptance. It does not accept a source, grant retention permission, advance any cursor, enable automatic ingestion or advertise native checkpoint-v2. The [source receipt proposal](94-receipt-source-reads.md) remains isolated and inactive; a native source receipt is not a canonical-memory receipt. Parent #43/#45 stay open.

## Bind the original request before writing

`mutation_request_identity(operation, payload)` is a pure helper for the three canonical record mutations. It validates and normalizes the request exactly as the backend does, then returns only `operation`, `request_id` and `expected_digest`. The digest is SHA-256 over the existing compact, sorted-key, Unicode-preserving JSON encoding of `[operation, normalized_request]`. Historical digest semantics are unchanged: default topic treatment is preserved, and omitted expiry is not silently converted into explicit null.

Retain that metadata privately before submitting an authorized mutation. The later `mutation_receipt_status` request is exactly that identity object. It contains no original content, topic, source text, namespace selector, path, URL or SQL. Metadata and digests are not anonymous data, authentication, capability tokens or permission to read another profile. The trusted opener still owns the current namespace and read admission. Existing SDK admission still performs its bounded export check and can read a record payload before this operation is invoked; the metadata-only guarantee applies to the status call itself, not the entire SDK lifetime. This helper does not persist a recovery journal for the caller.

The optional `mutation_receipt_status` capability is checked before dispatch. An adapter without it must refuse explicitly. The operation reads only the already bound store; it does not discover stores, create missing storage, migrate a read-only store or fall back to another backend.

## Interpret historical and current results separately

The SDK envelope always has `replayed: false` because inspection is a fresh read, not mutation replay. Both successful states include `evaluated_at`, a canonical UTC-second timestamp for that read.

- `state: committed` contains `receipt`, the historical six-field mutation receipt (`record_id`, `revision`, `status`, `operation`, `request_id`, `event_sequence`), and a separate `current` object (`record_id`, `revision`, `status`, `expired`). Both are read in the same canonical-store SQLite snapshot. Expiry is evaluated for that snapshot-time read; `expired` is not a statement about later reads.
- `state: absent_at_snapshot` contains no receipt or record metadata. No matching request was observed in that validated snapshot. A writer may still commit afterward, so absence is not permission to issue a fresh key or proof that an interrupted attempt can never finish.
- A matching request key with a different digest or operation fails with `idempotency_conflict`, without disclosing the stored digest or receipt.
- Storage failure, malformed evidence or inconsistent receipt/event/record relationships fail closed. They do not return successful absence. The SDK reports redacted read errors (`backend_failure` or `invalid_result` as applicable), never arbitrary backend exception text.

A historical `remember` receipt can still say `active` after correction, expiry or forgetting. Only the separate current metadata describes the record in this read snapshot. Inspection never restores content, rewrites a receipt or undoes suppression. A committed receipt proves the backend's historical mutation boundary, not current source availability, factual truth, model recall eligibility, delivery or permission for another action.

The bundled backend validates bounded metadata and receipt/event/current-record relationships within its existing read transaction. The scan admits at most 1,000 records, 11,000 events, 12,000 receipt rows (including existing expired-cleanup batch receipts), and 10,000 nonterminal events. Canonical receipt JSON is limited to 2,048 characters; existing cleanup batch envelopes are bounded to 16,384 bytes before fetching. These internal batches are validated for compatibility, not exposed as a new status operation. It checks all links before reporting absence so a missing receipt for a committed event cannot masquerade as an uncommitted request. It does not select record content, topic, source or session labels for this operation. Strict SDK validation checks exact fields, identifiers, integer and Boolean types, requested operation/key, historical-to-current revision and terminal-state relationships, and absence shape. Passing validation cannot detect a malicious adapter that fabricates otherwise coherent evidence; reviewed in-process adapters remain trusted code.

## Recovery and privacy boundaries

If the write acknowledgement was lost, reopen the same trusted store and inspect the saved identity. Do not automatically repeat the mutation, change its key or mark a downstream source processed. Keep failure or absence unresolved until the actual writer's outcome and any later action are authorized and known. This operation itself performs no retries and changes no records, events, receipts, source suppressions or consumer cursors.

The supported local store does not provide protection against malicious raw database edits, a fabricated adapter, manual replacement or restoring an old backup. A snapshot inspection is not a publication fence for a subsequent independent write. A result already returned may become historical immediately after its read transaction ends. Neither hash binding nor a matching record ID establishes cross-store atomicity.

Only bounded metadata is returned. Identifiers and request hashes still need private handling. Existing receipt retention remains unchanged; inspection does not promise secure erasure of old database pages, logs, backups, exports or copies already delivered elsewhere.

## Verification and remaining acceptance protocol

The separate optional `run_mutation_status_conformance(factory, isolated_synthetic=True)` runner in `personal_agent.memory_conformance` uses a caller-owned empty synthetic store, different from the CRUD/progress/checkpoint suites. It deliberately writes its own fixtures; only the status operations are read-only. It exercises the implemented capability across reopen, committed/absent observation, changed-request conflicts, historical correction and terminal forgetting. Tests also cover malformed adapters and storage, read-only operation, lost acknowledgements, abrupt process exits around COMMIT, and deterministic concurrent correction/forgetting. Run the repository's full checks and pinned native contracts as described in [the execution workflow](github-project-workflow.md); the PR records executed counts and exact-head CI. Test presence alone does not establish passing or production acceptance.

Future source-bound acceptance still requires honest provenance, explicit retention/acceptance authority, source identity and suppression checked inside the canonical writer transaction, durable decision outcomes and a separately defined source-consumption cursor. Existing `consumer_advance` tracks caller-reported local **record-event** progress; native row IDs, receipt-journal sequence numbers and a future acceptance queue are not interchangeable with it. A source cursor must not skip unresolved admitted decisions or imply that all native history was processed.

A promise that the native source stays valid through canonical publication requires a proven host/publication fence. Merely checking the source again just before writing is insufficient. An independently authorized retained snapshot can instead have explicit import semantics, with the clear disclosure that later native transcript deletion does not itself forget canonical memory. That mode still must honor canonical correction and forgetting, cannot forge the current-input candidate route, and does not satisfy a strict current-source-validity gate. No such acceptance mode or fence is implemented here. Native source, canonical memory and later consumer accounting retain separate commit boundaries.
