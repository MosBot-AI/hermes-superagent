# 108. Inspect Memory Record Origins

English | [简体中文](108-memory-record-origins-zh.md)

## Implemented boundary

[Issue #157](https://github.com/MosBot-AI/hermes-superagent/issues/157) adds explicit LOCAL `origin RECORD_ID` inspection and the optional API-v1 `record_origin` capability. This is a bounded local operator contract, not an extension to the shared public REST API, automatic ingestion, remote access, model tool or complete E2.6/E2.8 acceptance. Synthetic checks are not deployment or live personal-data acceptance.

```text
/personal-memory origin RECORD_ID
/personal-memory --json origin RECORD_ID
```

Use the canonical UUID record ID returned by existing record operations. The existing local-memory configuration, admitted profile, current Gateway-backed LOCAL session and maintenance fences still apply. Disabled, foreign-session, remote and model paths remain denied. The native route uses the managed existing-only readonly opener, with no creation, migration or SDK export admission. Missing stores return `memory_store_missing`; missing records return `not_found`. Invalid query fields or IDs return `invalid_request`.

## Exact metadata contract

The SDK request contains exactly `{record_id}`. Its result is `{data, replayed: false}`. Data has exactly these fields:

- `namespace_id`, requested `record_id`, and canonical UTC-second `evaluated_at` bind the observation.
- `current` contains `record_id`, `revision`, `status`, `expires_at` and `expired`. Expiry is calculated against that same evaluation second; an active record at its expiry boundary is expired. Forgotten records have null expiry and `expired: false`.
- `current_editing_route` is `explicit_local_operator` or `activated_session_model` for an active record, and null for a forgotten record. This is the latest editing route, not original authorship.
- `origin` is exactly one variant below.
- Fixed `scope` is `historical_acceptance_and_current_metadata_at_read_snapshot`; fixed `notice` explains the limits below. These values are validated, not adapter-supplied claims.

| Origin kind | Additional fields | Evidence limit |
| --- | --- | --- |
| `observed_native_snapshot` | `role`, `consumer_id`, `source_sequence`, `acceptance`, `suppressed` | Stored user/assistant role from an explicitly accepted observed snapshot. |
| `retained_native_snapshot` | Same fields | Stored user/assistant role from a receipt-backed retained snapshot; no fresh native receipt lookup. |
| `reviewed_candidate` | `candidate_id`, `acceptance`, `suppressed` | Historical reviewed acceptance only; erased quote, source and session fields are not reconstructed. |
| `unavailable` | `reason: no_durable_lineage` | Existing record without a durable lineage link, including direct records and historical candidates lacking that link. |

`acceptance` contains only `record_id`, `revision: 1`, `status: active` and `event_sequence`. It is historical even after correction, expiry or forgetting. Consumer IDs and source sequences are bounded local decision references, not authority. Original origin is never inferred from the current editing route. Stored role labels and hash-based linkage do not verify authorship, truth, endorsement or permission.

Suppression means exact-source anti-reentry, not necessarily that this record is forgotten: corrections suppress reentry, and another accepted record sharing the source may remain active. The query does not open the original source or assert its availability. Source deletion does not erase independently retained historical acceptance, reconstruct forgotten payload or authorize retrying a write.

The result is limited to 4,096 UTF-8 bytes of compact JSON data. It excludes canonical/source content, topic, quote, paths, session labels/references, source/request fingerprints, turn hashes and raw source identity objects. Native receipt and observation IDs are intentionally omitted. Record and candidate identifiers are still private correlation metadata.

## Integrity and snapshot rules

A deferred canonical read transaction establishes the SQLite snapshot before sampling expiry time. Namespace/schema, canonical record/event/receipt relationships, retained decisions and existing candidate lineage/suppression anchors are checked consistently inside that snapshot. Bounded SQL projections reject oversized values before JSON parsing; duplicate JSON keys and malformed historical receipts fail closed. Candidate acceptance must match its canonical `candidate.accept.<candidate_id>` receipt and current record relationship. Pending or discarded candidate parents cannot support an accepted origin.

The operation never calls payload-oriented `memory_sources.validate`, candidate mutation/cleanup dispatch, native-source openers or cursor advancement. It reads only bounded metadata, including historical receipts, and performs no canonical writes. Unrelated pending candidate payload is not hydrated. Existing schema and other operation validators are unchanged.

Dangling, conflicting or dual lineages, malformed/oversized/duplicate-key receipts and unverifiable relationships produce backend `storage_corrupt`, never an arbitrary preferred origin or successful `unavailable`. Missing lineage is not automatically corruption: older accepted candidates may legitimately have no durable lineage link. No missing fields are reconstructed. Read results can become stale immediately after the transaction ends.

## Optional SDK and conformance

`record_origin` requires optional `record_origin` plus `explicit_records`. Existing CRUD-only adapters remain compatible and receive `capability_unavailable` before dispatch. Activated-model SDK bindings are refused with `source_scope_required` before backend dispatch even when the capability is advertised. Strict result validation checks exact fields, namespace/request binding, variant exclusivity, current expiry/status/route, historical acceptance and output bounds. Invalid replies return `invalid_result`; unexpected backend failures return redacted `backend_failure`, not absence. Native storage corruption retains its explicit error.

SDK constructor/export admission can read payload. The metadata-only guarantee applies to this operation and the native readonly path, **not the entire SDK lifecycle**. Reviewed adapters remain trusted Python code; validation is not a sandbox or proof of honest read-only implementation. There is no dynamic loading, factory replacement, backend cutover, restore or schema change.

`memory_conformance.run_record_origin_conformance(factory, isolated_synthetic=True)` uses one fresh caller-owned synthetic store. It deliberately creates, corrects and forgets a direct record, reopens the store and verifies unavailable lineage plus historical retry without resurrection. Source-family provenance/corruption requires adapter-specific fixtures; the generic runner does not require optional source ingestion. Both bundled storage and an independent test metadata adapter run it. Do not point this writing conformance runner at a real profile.

## Verification and remaining gates

Focused unit suites cover user/assistant observations, retained receipts, reviewed candidates, direct/legacy absence, edits by either route, exact expiry, forgetting, historical retry, concurrent mutation snapshots, SQL payload/write denial, corruption and malformed SDK replies. Fresh-process tests inspect origins before and after normal/interrupted canonical repack. Native contracts cover human/JSON output, admission, missing source availability, restart and managed no-create/no-migrate readers against Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`.

The runtime file declaration and reviewed checkpoint-source experiment bindings include the new module without altering the host patch or weakening hash guards. Exact-head full unit/native/proposal/runtime checks, independent review and merged-main CI evidence belong to the PR. No model call, deployment, public REST change, recall-semantic change or frozen recall fixture/report modification is introduced. Parent #43/#45/#46 acceptance remains open.
