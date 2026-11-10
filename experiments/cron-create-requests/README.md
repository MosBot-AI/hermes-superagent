# Review-only native cron create request keys

English | [简体中文](README-zh.md)

This unsubmitted host patch targets `2281116525106e3c109993ccb5dc74d02bfc1427`. It is not installed, a public plugin SDK, an identity authority or a reminder feature. The production compatibility pin and runtime package remain unchanged. E1 admission, notification delivery and Issue #19 remain incomplete. No model, ticker, network delivery or production profile is exercised by this experiment.

## Contract

The existing internal `cron.scheduler.create_job_with_scheduler_registration` accepts an optional `request_key`. Without it, its original job-shaped result remains unchanged. With it, strict JSON-compatible complete create arguments (including signature defaults) are bound by a versioned SHA-256 digest. Keys are profile-local, 1–128 ASCII letters/digits/`_.:-`. Equivalent spellings are not coalesced. Changed parameters conflict, including destinations, scripts, model/provider, authorization-relevant toolsets and time policy.

The result separates `creation` (`job_id`, immutable digest, lifecycle `state`) from `current_job` and `replayed`. `creation.state` advances to `removed`; it is not an immutable historical receipt. A replay reads current state and does not revert later edits, pause, completion or deletion. Relative schedules are resolved only on first creation. The digest describes requested arguments, not dynamically resolved defaults or current job bytes. It is not an authentication signature and does not authorize callers.

A request binding and its new native job are written in the same fsynced JSON envelope and atomic replace. All save paths preserve the ledger. Deletion, including completed one-shot sweeping, retains a tombstone: retry never recreates the job. Capacity is 1,024 permanent keys per profile; new keys then fail closed, existing replays remain possible. Arguments are bounded at 64 KiB and the store at 16 MiB. There is no automatic ledger eviction or reset command.

Only an explicitly builtin/default configured scheduler with no call to the generic provider resolver are admitted. External providers are rejected before job persistence, even if native provider resolution would silently fall back. Builtin registration is a no-op: the persisted store remains the scheduler's authority, and retry recovers the original ID without registering a second trigger. No claim of generic external-provider reconciliation is made. `enabled` means currently enabled, not executed or delivered; `delivery_verified` is always false.

## Deliberate host changes and limits

- All job writers now require a successful cross-process lock, including unkeyed writes. Timeout/unavailable backend refuses rather than degrading to an in-process lock. Nested locks cannot switch stores. This changes native availability behavior and needs upstream review.
- Malformed JSON (including NaN/Infinity, even in legacy stores), duplicate keys, damaged/version-unknown ledger and over-limit stores fail closed. Keyed stores cannot use automatic junk-dropping/counter-reset repairs. Recovery is not implemented; do not hand-edit away the ledger.
- **Stop all old runtimes before adoption.** Old code drops the ledger and ignores these rules. Its deletion of the entire ledger cannot be reliably detected by this proposal. Concurrent legacy processes, manual store replacement, rollback from a backup and malicious in-process code are outside the guarantee.
- Atomic rename plus file/directory fsync and same-key reconciliation cover the tested process-cut windows, not a universal power-loss or filesystem guarantee. An exception after replacement may mean committed success; `create_outcome_unknown` must be reconciled by the same key, never a fresh key. Lock failure occurs before creation. Persistent failure can remain unresolved.
- Existing native ownership, occurrence execution, cancellation and delivery remain unchanged. No caller-controlled path, extra service, parallel scheduler, model tool, CLI flag or plugin background consumer is added. The internal API is not production authorization.

## Reproduce safely

Use a separately provisioned Python 3.14 environment and a disposable credential-free host checkout at the exact base. Do not use the production compatibility checkout or a daily profile. Review the patch first, then apply and stage it yourself:

```sh
git -C "$DISPOSABLE_HOST" apply --check "$ARTIFACT/cron-create-requests.patch"
git -C "$DISPOSABLE_HOST" apply --index "$ARTIFACT/cron-create-requests.patch"
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON" --check-only
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON"
```

The runner never downloads, installs, applies patches, starts gateways or changes the compatibility pin. It checks exact base, staged diff/tree, source hashes, untracked changes and index masking. Child processes receive sanitized environments and explicitly import the patched host; networking is denied. All stores are synthetic temporary profiles. Tests cover replay, parameter conflicts, concurrency, before/after-replace process death, pause, removal, actual completion sweeping, capacity, corruption and unsupported providers. These are host-store contracts, not actual scheduled occurrences or user notifications. The manifest records the observed selected test result; it is not full upstream certification.

Upstream source in the patch is covered by [the retained license](LICENSE.hermes-agent). Nothing has been submitted upstream or released.
