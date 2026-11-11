# Review-only native checkpoint source receipts

English | [简体中文](README-zh.md)

[Issue #125](https://github.com/MosBot-AI/hermes-superagent/issues/125) proposes a host-owned source receipt for explicitly requested owner in-place compression on Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. This unsubmitted patch is not installed or activated. The shipping provider stays API v1, the production compatibility pin is unchanged, and E2.8 remains incomplete. See [the design and boundary](../../docs/92-native-checkpoint-sources.md).

## Internal contract

The proposed host module `hermes_state_checkpoint_sources` exposes:

- `prepare_source_request(db, session_id, attempt_id, candidates, compacted_messages, *, lock_holder=None)`: read-only explicit preparation against the selected native session.
- `commit_source_request(db, session_id, request, *, cancelled=None)`: revalidate source coverage and revision, then archive through the native compression transaction together with the metadata receipt.
- `source_receipt_status(db, session_id, attempt_id)`: read-only snapshot inspection; absent receipt schema is not created by inspection.

Candidates use `[{role, content, uids: [primary, *absorbed]}]`; compacted output is exactly one summary message, `[{role: "assistant", content: ...}]`, with no carried messages or extra options. The full active scan admits at most 256 rows and 65,536 content characters; selected coverage must be contiguous. Capacity is 4,096 receipts and 1,048,576 source bindings, without eviction. Status is `committed_available`, `invalidated_or_unknown` or `absent`. Commit replay reports historical `committed` only, not current availability.

Candidate coverage is deliberately limited to exact active plain user/assistant sources and supported ordered user merges. Pending input, unknown lineage and unsupported coverage are refused rather than guessed. The receipt does not copy transcript payload; retained original text exists only in native archived message rows. Permanent native triggers invalidate the metadata receipt when any source column changes except `display_order`, including reaction changes. Same-value no-op updates do not invalidate it. Ordinary native/SQL mutations from older code still encounter these persisted triggers; conservative unavailability after unrelated metadata changes is acceptable. Finite receipt capacity refuses new admissions rather than evicting existing history.

Persisted `_compressed_summary` rows are ineligible sources. The caller supplies only `role` and `content` for the single assistant summary; the host sets `_compressed_summary=True` on a fresh output copy, leaving the canonical request untouched across retry.

Post-read admission also limits the sum of string-character and byte-value lengths in each raw row to 262,144 and across the scan to 2,097,152. Serialized lineage is at most `1024 * 36 + 2` characters; canonical request JSON is at most 1,500,000 characters. These are post-read admission limits, not allocation-safety guarantees.

Preparation does not reserve sources or authorize execution. Commit admission must recheck them. The optional cancellation predicate applies before commit admission; it is not a promise to undo a committed transaction. After an interrupted or uncertain return, inspect the same session/attempt receipt instead of treating an exception as proof that no write occurred. A historical receipt is not current memory coverage, a model result, delivery evidence or an authorization grant.

Only explicit owner in-place compression is in scope. Session rotation, worker compression, app-server strict checkpointing, automatic ingestion and provider-v2 activation remain unsupported. This is a trusted in-process host API, not isolation against malicious code, raw schema tampering, manual database replacement or backup rollback. No parallel transcript archive, memory store, scheduler or runtime loop is added.

## Reproduce safely

Use a separately provisioned Python 3.14 environment and disposable credential-free host checkout at the exact base. Review the patch, then apply and stage it explicitly:

```sh
git -C "$DISPOSABLE_HOST" apply --check "$ARTIFACT/native-checkpoint-sources.patch"
git -C "$DISPOSABLE_HOST" apply --index "$ARTIFACT/native-checkpoint-sources.patch"
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON" --check-only
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON"
```

The runner verifies the exact base, staged patch/tree, artifact source hashes, untracked files and hidden index flags. It never downloads, installs, applies patches, starts listeners or changes the production pin. Proposal tests run with a sanitized environment and temporary synthetic home. Native regressions use the pinned host's canonical `scripts/run_tests.sh` and its per-file process isolation, with the explicitly prepared interpreter. Test presence is not passing evidence; executed counts belong in the reviewed manifest. CI uses a separate disposable host job and does not activate this proposal in the runtime package.

`consumer.py` is an explicit test/review consumer, not a shipping provider registration or automatic hook. The artifact contains synthetic test evidence only. There are no real model calls, credentials, production profiles or external delivery checks. Upstream-derived patch material is covered by [the retained license](LICENSE.hermes-agent). Nothing has been submitted upstream or released.

## Interrupted consumer accounting

[Issue #127](https://github.com/MosBot-AI/hermes-superagent/issues/127) adds `recovery.py` and `test_recovery.py`. The host also exposes `source_request_identity(session_id, request)`, a bounded metadata identity helper with no database access or source admission. `RecoveryJournal(path, host_path, session_id, create=True)` explicitly initializes a private journal; omit `create` to reopen it. `stage` precedes host admission, `submit` explicitly submits an identical bound request, `pending` lists bounded pending attempts, and `reconcile` reads the same host receipt before historical local accounting. No full request, source or summary text is retained in the journal.

Read [the recovery protocol and boundaries](../../docs/93-source-receipt-recovery.md) before use. An absent receipt needs explicit identical-request resupply, not an automatic retry. Source availability is a fresh observation, not guaranteed by accounting. The two stores are not atomic; no canonical memory or cursor is written. This remains an isolated synthetic harness, not production enablement.
