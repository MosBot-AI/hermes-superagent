# 98. Explicit observed-source retention

English | [简体中文](98-observed-source-retention-zh.md)

## Implemented boundary

[Issue #137](https://github.com/MosBot-AI/hermes-superagent/issues/137) connects the [native source review workbench](97-native-source-workbench.md) to [canonical retained-source acceptance](96-retained-source-acceptance.md) through explicit LOCAL commands. It uses the public SessionDB read API on Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, without a host patch. This is implemented production-package code, not installation, deployment or live personal-data acceptance.

The existing `mode: local_tasks`, `local_conversation: true`, `local_memory: true`, admitted profile and exact current Gateway-backed LOCAL session gates apply. There is no automatic ingestion, model-tool entry, provider activation, checkpoint-v2 or HTTP/API contract change. Native text remains untrusted evidence, not permission or verified authorship. Commands cannot select another profile, database path or session.

## Review, preview and explicitly retain

First use `source-list` and `source-show` as described in document 97. Choose one eligible original row, then supply your own consumer, expected completed sequence and request key:

```text
/personal-memory source-preview UID --expected-snapshot HASH --consumer-id reviewed --expected-sequence 0 --request-id retain-001 --retention independent_snapshot --keep
/personal-memory source-retain UID --expected-snapshot HASH --consumer-id reviewed --expected-sequence 0 --request-id retain-001 --retention independent_snapshot --keep --expected-digest DIGEST
```

Replace `UID` and `HASH` with the reviewed selection, and `DIGEST` with preview's `query.expected_digest`. Sequence `0` is appropriate only for a new consumer with no completed decisions. For an existing consumer inspect its cursor first. The consumer ID is lowercase, starts with a letter and has at most 64 characters from letters, digits, `_`, `.` and `-`. Request keys contain 1–128 ASCII letters, digits, `_`, `.` or `-`. Do not generate a fresh key to bypass an uncertain outcome.

Both commands require `--retention independent_snapshot` and exactly one of `--keep` or `--expires-at UTC`. `--keep` explicitly selects no canonical expiry; alternatively use a valid UTC timestamp such as `2030-01-01T00:00:00Z`. Optional `--topic LABEL` is part of the reviewed request. Keep every argument identical between preview and retain, adding only `--expected-digest`. The existing `/personal-memory --json ...` form is supported.

Preview returns the complete canonical `payload`, including exact source content, topic, provenance and retention, plus the payload-free `query` containing request ID and normalized digest. It also reports selection metadata, absorbed UIDs, `canonical_admission: false` and `automatic_ingestion: false`. Save the query before attempting retain. Preview reads native data but neither opens canonical storage nor reserves a pending slot; it does not guarantee later canonical admission.

Retain rereads the same expected native observation, obtains the actual host `store_instance_id` within that snapshot, validates the complete request and checks its normalized digest before staging. A changed digest returns `source_preview_changed`; a changed observation returns `source_snapshot_changed`. Re-list and review again rather than blindly replacing a hash. After successful checks, retain stages and accepts through the existing explicit-local-operator writer. Canonical acceptance creates one record/event/receipt and resolves one source sequence transactionally; retries do not create another record or advance twice.

Canonical content must fit 2,048 characters and its supported text controls; topic must fit 128 characters. Oversized or unsupported text is refused, never truncated or summarized. A row can be valid for read-only show yet invalid for retention. The workbench's separate whole-observation limits and exclusion rules still apply.

## Honest provenance and schema compatibility

Observed imports use `kind: observed_native_snapshot` and `observation_id`, never a fabricated `receipt_id`. They preserve original role, exact UTF-8 content fingerprint and source identity. The source identity hashes the tagged tuple `native_original_v1`, actual host store UUID, native session ID and original message UID. The observation ID binds the reviewed snapshot and that UUID. Missing or malformed host identity refuses capture with `source_store_identity_unavailable`; it is not created or repaired by the reader.

Observation hashes remain bound to the profile path/filesystem binding and native revision/rows. Moving or copying a store can therefore invalidate a previously reviewed observation even when its UUID remains unchanged. The UUID-derived source identity can survive an intact move/copy; it is provenance continuity, not clone fencing, verified ownership or authority. Copied databases sharing the UUID are not made independent sources by changing their path.

The identity formula matches the earlier receipt experiment when that caller actually used the same host UUID. Arbitrary legacy trusted-caller identities are not remapped or declared equivalent. Exact fingerprint suppression still applies across current-input, legacy receipt and observed-source routes, subject to the documented exact-match limits.

Writable schema-13 migration adds tagged observed provenance while preserving every schema-12 decision's receipt provenance, request digest, historical output and suppression state. Old `retained_native_snapshot` sources keep their `receipt_id` and original request format. New observed sources have `observation_id` instead. There is no invented native receipt or silent rewriting of historical import identities. Read-only status/cursor never migrate an older store; use an explicitly authorized writable path when migration is needed.

## Status, pending recovery and discard

```text
/personal-memory source-status retain-001 --expected-digest DIGEST
/personal-memory source-cursor --consumer-id reviewed
/personal-memory source-discard retain-001 --expected-digest DIGEST
```

Status and cursor use existing-only read-only canonical metadata. They never reopen native text, hydrate canonical payloads, create a store, migrate it or repair it. Missing canonical storage reports `memory_store_missing`, not an empty successful result. Status reports the saved decision and current record metadata separately; a historical accepted receipt does not promise that the current record is active, unchanged or unexpired. Metadata and fingerprints still require private handling.

Each consumer has at most one unresolved pending slot. Staging stores metadata and digest, not source content, topic or a session label. A pending slot does not advance the completed cursor or automatically expire. If native deletion or loss prevents a subsequent retain, the slot remains visible through status/cursor and can be explicitly discarded with its exact saved key/digest. Discard does not read native text, creates no canonical record and resolves only the matching pending decision. It advances that consumer's source cursor and suppresses the exact source fingerprint; it does not undo an accepted record. Use canonical forget for that.

After an unknown commit outcome, inspect the original key/digest before retrying. An accepted decision can be reconciled without native availability. Replaying the native retain command still rereads its reviewed source, so replay can fail after the original observation disappears even when the canonical commit succeeded. Status is the recovery route, not proof that the native source still exists. An absent decision means absent only in the inspected snapshot; an earlier writer may still commit later. Do not infer that it is safe to substitute a key or overtake an unresolved attempt.

## Independent lifetimes and suppression

An explicitly authorized independent snapshot already captured by retain may be accepted if native text disappears after the read. There is no native-current-at-commit guarantee or cross-store atomic transaction. Native deletion does not forget canonical memory, and canonical forgetting does not erase native rows, backups, exports, client history or previously returned context.

Canonical correction/forgetting and retained-source discard enforce existing exact source/fingerprint suppression across routes. Fresh request keys, consumer IDs or observations cannot resurrect the same suppressed source. This is not semantic erasure or detection of all paraphrases. Historical accepted outcomes remain historical and do not restore forgotten payloads. Existing decision/consumer bounds, pending-slot semantics and canonical writer locking from document 96 continue to apply.

## Verification and remaining gates

The follow-on [packaged lifecycle acceptance lane](99-packaged-memory-lifecycle.md) exercises real Gateway processes and original-text loss, with explicitly separate SDK-staged pending setup. Its exact-source run evidence is required; test implementation alone does not establish live acceptance.

Run repository and documentation checks:

```sh
python scripts/check.py
python scripts/check_docs.py
git diff --check
```

Run the separate pinned-host suite with isolated temporary homes and synthetic sources:

```sh
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

Use the [development-check setup](../README.md#development-checks) for the exact checkout/interpreter prerequisites. Review command parsing, full preview and digest binding, real SessionDB UUID/snapshot reads, one-record retries, schema migration, metadata-only recovery without native storage, pending source loss/discard, unknown outcomes, cross-route suppression, malformed/oversized text, origin gates and read-only behavior. The PR's executed checks, exact revisions and independent review are the evidence; this document does not hardcode provisional counts or claim full lifecycle, production or model acceptance. Automatic source selection, broader native coverage and full memory roadmap acceptance remain separate work.
