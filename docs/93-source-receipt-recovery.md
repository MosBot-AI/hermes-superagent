# 93. Review-only source receipt consumer recovery

English | [简体中文](93-source-receipt-recovery-zh.md)

## Status and value

[Issue #127](https://github.com/MosBot-AI/hermes-superagent/issues/127) extends the [source receipt proposal](92-native-checkpoint-sources.md) after merged [PR #126](https://github.com/MosBot-AI/hermes-superagent/pull/126). The host transaction already commits source archival and its metadata receipt together. That alone does not preserve consumer progress if a process stops after the host commit but before local accounting.

The isolated artifact now includes an explicit `RecoveryJournal` and a public proposed-host `source_request_identity(session_id, request)` helper. The helper validates the bounded request and computes the same receipt identity as commit without reading or changing a database. Identity is neither source validation nor authority. The journal writes metadata intent before host admission and can discover pending attempts after restart. It reconciles a matching host receipt without retaining the request payload or replaying compression.

This is implemented and tested as a review-only experiment, not submitted upstream, installed, activated or released. The shipping provider remains API v1; the compatibility pin remains Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. Parent #43/#45 remain open. No canonical memory write, ingestion, consumer cursor advancement, provider-v2 checkpoint, REST surface, model call, external delivery or automatic recovery loop is enabled.

## Protocol and outcomes

1. Explicitly create a journal for one existing native database and session. Opening is the default thereafter; a missing journal cannot silently become an empty queue.
2. `stage(request)` validates the exact canonical request and commits its attempt ID, expected receipt ID and source count in a separate local SQLite transaction. No source, summary or full request payload is copied. Existing attempt IDs must match exactly; at 4,096 retained rows, new admission fails without eviction.
3. `submit(request)` first commits that intent, then calls the proposed host commit with the same private request snapshot. An intent-write failure prevents host admission. A host error leaves a pending intent and returns `host_commit_unconfirmed`, even when the host may already have committed.
4. `pending(after=0, limit=100)` enumerates unrecorded attempts in stable sequence order. Page sizes are 1–100; the retained sequence is not renumbered. Pages are bounded observations, not a cross-page snapshot. Concurrent completion can remove rows from later pages, and a later traversal can discover new rows.
5. `reconcile(attempt_id)` only reads the host. A matching receipt, even if its sources have since been invalidated, permits an idempotent local `recorded` flag. A mismatch is rejected; an absent receipt leaves unrecorded intent pending. An inaccessible or replaced host returns `host_unavailable`. Recovery never invokes compression, creates a host database or generates a new attempt key.

If a host receipt is absent, retry requires an explicitly resupplied **identical** request and its original attempt ID. The journal deliberately cannot reconstruct or regenerate source/summary plaintext. Source changes or a lost compression lease can still make that retry fail. There is no automatic retry, abandonment, receipt garbage collection or capacity reset in this slice. Losing the journal, manual restore, cloned writers and source takeover are not supported recovery procedures.

The result distinguishes `accounting` (`pending` or historical `recorded`), `host_observation`, and `source_available_at_observation`. It always reports `durable_memory_checkpoint: false`. Recorded history does not prove that host receipt/source rows still exist. Every reconciliation reads the host afresh, including for an already recorded attempt. A previously recorded result plus a now-absent host receipt is reported as `recorded`/`absent`, not available.

## Transaction and privacy boundary

This is **not a two-database atomic transaction**. The order is local intent commit → native archive/receipt commit → local historical accounting commit. An interruption can leave an explicit pending intent. Exact request identity and retained host receipts make that gap reconcilable under the stated trust and retention assumptions.

There is no fence across the host status read and local accounting commit. Source deletion can happen between them. Accounting records only that a matching historical host transaction was observed. Availability is explicitly a prior snapshot observation, not recall authorization or a continuing retention guarantee. Later reads observe native invalidation, and the consumer never restores deleted text. Canonical memory acceptance, deletion suppression, source-reading authorization and cursor advancement need their own future protocol and tests.

The journal is a separate local metadata database, not a second transcript archive or canonical memory store. It contains the host's canonical path/device/inode, session ID, attempt IDs, receipt hashes, source counts, sequence and recorded flags. Identifiers and hashes are private metadata, not anonymous or safe to publish. Payload privacy applies to the journal, not to caller memory, supplied identifiers, native history, exports or filesystem backups. This is not a secure-erasure promise.

The explicit harness requires a user-owned mode-0700 journal parent and a mode-0600 regular single-link journal file. Creation is exclusive; symlinks, hardlinks, wrong bindings and unavailable stores fail closed. Host device/inode checks detect ordinary file replacement but do not constitute a security fence against malicious same-user code, concurrent filesystem tampering, inode reuse or rollback. Private files do not authenticate the human operator. Native admission and owner authorization remain the caller's responsibility. SQLite uses `synchronous=FULL` for journal transactions; subprocess crash evidence does not establish power-loss durability on every filesystem.

## Reproduction and verified scope

Use the [artifact reproduction instructions](../experiments/native-checkpoint-sources/README.md#reproduce-safely). Its checksum manifest covers the new journal, tests and host identity helper. The existing isolated CI job invokes both proposal test files against a separately staged exact host patch; production runtime packaging excludes the experiment.

The test suite uses real temporary SQLite databases and fresh subprocesses. It injects abrupt exit before host admission, inside the host archive transaction, after host commit before accounting, during local accounting, and after accounting. It also covers lost host return, local write failure, repeated/concurrent same-attempt submission, conflicts, pending pagination/capacity, wrong/missing/replaced stores, and source deletion before, after or between observation and accounting. No test uses a real model or personal source data. Executed counts and selected native regression files are in the manifest; full upstream-suite, production-provider and real-device acceptance are separate and not claimed.

[The source-read follow-on](94-receipt-source-reads.md) provides a separate explicit receipt-bound snapshot reader. It neither treats journal accounting as source-read authorization nor changes this historical accounting protocol.
