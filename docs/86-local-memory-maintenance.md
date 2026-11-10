# 86. Fenced Local Memory Repack

English | [简体中文](86-local-memory-maintenance-zh.md)

## What this does

This operator-only workflow compacts a consistent copy of the **current** bundled SQLite memory store, verifies its exact logical contents, and switches to it while preserving the original file. A durable journal supports explicit recovery after interruption. It is same-profile storage maintenance, not historical snapshot restore, disaster recovery, cross-profile transfer, a schema conversion or general adapter migration.

The [existing snapshot commands](79-local-memory-snapshots.md) remain historical and `restorable: false`. Maintenance accepts no snapshot name, arbitrary source/destination path or external data. A missing/corrupt current source cannot be reconstructed from an old snapshot. This restriction prevents using stale backups to resurrect later corrections or forgotten records.

## Deployment prerequisite

**Stop old runtimes before installing this lock-aware version.** Older idle SQLite handles do not honor the new coordination file and can keep writing an old inode after rename. Neither a SQLite transaction nor this Python code can prove such handles are gone. The guarantee covers the updated controlled plugin entry points, not old binaries, arbitrary SQL clients or hostile same-UID code. This is not authentication or a sandbox.

Updated writer and read-only openers hold a shared lock throughout their entire connection lifetime, including multi-transaction projection/edit operations. Index maintenance and live snapshot creation participate too. Repack takes the exclusive lock, with bounded waiting. The fixed private lock inode is permanent: never remove or replace it to clear contention. An existing store's read-only opener may create that coordination file, but does not create/migrate the database.

## Operator workflow

Use an existing trusted-local session with the ordinary `local_tasks`, `local_conversation` and `local_memory` opt-ins. These commands are not model tools or remote-owner access. Configuration/session admission happens before storage work.

```text
/personal-memory maintenance-preview
/personal-memory maintenance-prepare repack-1 --expected-watermark 42
/personal-memory maintenance-status repack-1
/personal-memory maintenance-commit repack-1
```

Use the watermark actually returned by preview, not the illustrative `42`. Prepare checks it again under exclusive access. A changed watermark refuses instead of silently choosing a newer source. Names have 1–64 ASCII letters/digits/underscores/hyphens and begin with a letter/digit.

Prepare creates a fixed private staged database, copies the current consistent source and runs SQLite `VACUUM`. Exact schema and all table values must match, including canonical records, events, durable receipts, terminal tombstones, pending candidates and source suppression. Repack does not rewrite facts, reset capacity, erase tombstones or make old request IDs new. File size need not shrink.

Once a pending journal exists, ordinary controlled memory reads/writes, live snapshots and index maintenance refuse. This persists across process restarts. Status exposes metadata only. Historical snapshot inspection stays available, with its existing historical-content warnings.

Commit revalidates source/stage identity and digests. It preserves the source at a fixed private `maintenance/NAME.old.sqlite3`, then installs the verified stage as the live store. It records completion before clearing the pending guard. This is a specific controlled cutover, not a general overwrite/import operation. It neither restores nor repopulates external Markdown/editor files, changes provider selection, copies credentials or changes owner authority.

## Interruption and recovery

```text
/personal-memory maintenance-status repack-1
/personal-memory maintenance-recover repack-1
```

Reuse the same name. Recovery finishes the recorded intent; there is no rollback command. A `preparing` journal can reconstruct only its recorded, non-authoritative staging inode from the unchanged source. A `prepared`/`switching` journal permits only the exact expected source/stage/preserved-old layouts. Unexpected bytes, identity, namespace, sidecars or journal fields refuse rather than guessing from timestamps or which file looks newest.

Once completion is recorded and ordinary access resumes, subsequent corrections/forgetting may change the new store. Repeating commit/recover returns the historical operation metadata without replacing or rolling back those new writes. Do not interpret that receipt as a fresh check of the current store.

`maintenance_outcome_unknown` means effects may already exist. Inspect the same operation; do not start a different name as an automatic retry. A crash before publishing the first journal may leave an unadopted private staging file. It is never adopted by inference or automatically deleted; a conflicting name refuses and requires separately verified offline cleanup. Atomic journal publication can similarly leave a private orphan temporary file; later operations never adopt it. Malformed or unexplained pending state also remains blocked.

## Privacy and limits

The original database is retained as plaintext. Later forgetting in the new live store does not erase preserved old files, historical snapshots, exports or already delivered data. Repack has no physical-erasure guarantee, and provides no automatic cleanup, upload or sharing. Names/metadata and commands can enter host history.

Private ownership, restrictive modes, no symlinks, single-link regular files and standalone DELETE-journal format are required. The existing 128 MiB and cooperative 30-second bounds apply; kernel filesystem calls such as fsync are not forcibly interruptible. Inspection keeps raw hash descriptors alive until SQLite closes so it does not prematurely release POSIX record locks. Lock acquisition has a separate bounded wait.

## Evidence and remaining scope

Tests exercise process contention, interruption windows, persistent pending guards, exact recovery, same-request receipts, terminal forgetting, unsafe paths and native admission/model-tool refusal on synthetic profiles. Process-exit tests and directory-fsync ordering checks do not simulate physical power loss or certify every filesystem. No actual user store, paid model or external data recipient is used. Passing tests is not deployment evidence.

This closes only the bounded maintenance package [#106](https://github.com/MosBot-AI/hermes-superagent/issues/106) after final merge verification. Broader [#43](https://github.com/MosBot-AI/hermes-superagent/issues/43) and [#46](https://github.com/MosBot-AI/hermes-superagent/issues/46) retain their historical restore, remote/multi-kind contracts, adapter cutover and native lifecycle gates. The shared client REST contract is unchanged.
