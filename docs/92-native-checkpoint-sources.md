# 92. Review-only native checkpoint source receipts

English | [简体中文](92-native-checkpoint-sources-zh.md)

## Status and dependency

[Issue #125](https://github.com/MosBot-AI/hermes-superagent/issues/125) follows the bounded preparation in [43](43-native-checkpoint-boundary.md), pinned native verification in [76](76-native-memory-contracts.md), and read-only source resolution in [91](91-native-source-resolution.md). The [isolated artifact](../experiments/native-checkpoint-sources/README.md) proposes a host-owned transaction seam on Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. It is review-only, unsubmitted and not activated. Existing historical documents retain their own tested scope; this proposal does not retroactively turn their evidence into a durable checkpoint.

## The narrower guarantee

A successful source read alone cannot fence future compression. The proposal prepares an explicit bounded request snapshot, then revalidates the bound current session, source references and revision at native commit admission. The JSON-compatible request is a mutable dictionary, deep-copied and revalidated at commit; its digest is fixed per admitted attempt. Supported source coverage and metadata receipt persistence share the existing archive/compaction transaction. There is no second transcript archive: original source payload remains only in native archived message rows, while receipts retain metadata.

Supported candidates are exact current plain user/assistant prose with unambiguous source identities, including supported ordered user merges. Unknown pending sources, unsupported lineage or source mismatches fail closed. The operation is limited to explicit owner in-place compression. It does not support session rotation, worker compression or app-server strict checkpointing, nor does it infer owner authority from a session identifier.

Permanent source update/delete triggers invalidate related metadata receipts for any changed source column except `display_order`, including reaction changes. Same-value no-op updates do not invalidate receipts. Ordinary native/SQL mutations from older code still hit these persisted triggers; conservative unavailability after unrelated metadata changes is acceptable. Read-only status inspects a single snapshot without creating missing schema. Finite capacity rejects further admission instead of silently evicting receipt history. Cancellation is checked before commit admission; a late cancellation does not undo an already committed result. After process interruption or uncertain return, reconcile using the same bound session and attempt. A receipt is historical transaction evidence, not proof that sources still qualify for recall or that a later memory write succeeded.

Persisted `_compressed_summary` rows are ineligible sources. The caller supplies only `role` and `content` for the single assistant summary; the host sets `_compressed_summary=True` on a fresh output copy, leaving the canonical request untouched across retry.

Post-read admission also limits the sum of string-character and byte-value lengths in each raw row to 262,144 and across the scan to 2,097,152. Serialized lineage is at most `1024 * 36 + 2` characters; canonical request JSON is at most 1,500,000 characters. These are post-read admission limits, not allocation-safety guarantees.

The trusted host-store boundary remains explicit. Raw schema tampering, manual database replacement, backup rollback and malicious in-process code are not covered. Source-retention and deletion semantics must not be advertised as universal secure erasure or as a generic filesystem durability guarantee.

## Verification and remaining work

The artifact includes a test/review consumer and isolated synthetic tests. Its verifier requires an exact staged host patch and source hashes before execution; native regressions run through `scripts/run_tests.sh`, not direct pytest. The separate CI job uses a disposable patched checkout, never the production runtime package. Refer to the artifact manifest for the actual selected execution results. Test implementation, a configured CI job and passing synthetic checks are distinct from a completed CI run, upstream acceptance and deployed acceptance.

The production compatibility pin, provider API v1 and runtime configuration remain unchanged. Automatic capture, capture/retention consent, provider integration, memory writes, cursor progression, generic worker/rotation support and complete E2.8 acceptance remain separate gates. This slice adds no public REST contract, background consumer, model call, listener, deployment or release.
