# 79. Explicit consistent local memory snapshots

English | [简体中文](79-local-memory-snapshots-zh.md)

## Operator workflow

```text
/personal-memory snapshot-create before-change
/personal-memory snapshot-inspect before-change
/personal-memory --json snapshot-inspect before-change
```

These explicit native local commands require the existing `mode: local_tasks`, `local_conversation: true`, `local_memory: true` configuration and current trusted-profile/session admission. They are not model tools, automatic exports, remote-owner access or a new provider. Disabled/foreign origins refuse before snapshot storage. Loading/help do not create a database. This #44 slice does not complete general import/migration or source-level suppression.

Names are 1–64 ASCII letters/digits/underscores/hyphens, beginning with a letter/digit. The only destination is `memory/snapshots/NAME.sqlite3` beneath the current profile's private plugin-data directory. No arbitrary path, overwrite, upload, list/delete command or automatic cleanup is provided. Existing names refuse; inspect that name after an uncertain create rather than assuming a new name is the same retry.

Create returns schema version, namespace, event watermark, record/active/tombstone counts, byte length and SHA-256. `active_records` counts status-active rows, including expired records not yet forgotten; it is not the currently recallable count. Inspect returns the same metadata from the named historical file without returning private record bodies. It works without a live records.sqlite3, never creates/migrates that store, and rejects snapshots from a different profile namespace.

## Consistency and privacy

The supported memory store uses the current exact schema and DELETE journaling. Creation validates it inside a SQLite read transaction, then uses SQLite's backup API from that same snapshot. Concurrent correction or forgetting may complete afterward; the copy retains the earlier consistent record/tombstone/receipt/event state, not a mixture of independent live pages. A source read lock can delay a concurrent writer. The pre-existing `export` command remains a bounded live page, not this consistent artifact.

**Snapshots are plaintext and retain private historical content.** They include canonical records, pending model candidates, source/session metadata, receipts and stored maintenance metadata. Later corrections, forgetting or expired-record cleanup do not erase this copy, prior exports, opened descriptors or filesystem backups. The explicit command authorizes this local copy only, not sharing. It does not change expiry or install/select memory.provider.

Only the SQLite database is copied. `records.md`, `edit.md`, native MEMORY.md/USER.md, credentials and other profile files are not copied. Stored projection/draft metadata is historical and does not mean those external files exist in the snapshot. `restorable: false` is intentional: there is no restore/import/copy-back path, no authority transfer and no automatic reactivation. Do not replace a running live database with this artifact.

## Filesystem and failure contract

Existing directories and files must satisfy native POSIX ownership/privacy checks, no symlinks and single-link regular files; the snapshots directory is private, and new files are `0600`. Source and published snapshot sidecars are refused. The live source is checked without opening/closing a raw descriptor, which would risk dropping another same-process SQLite connection's POSIX locks. Unsupported WAL sources are rejected through SQLite validation; opening such an externally modified file can create WAL/SHM sidecars before refusal. This is not a VFS or malicious same-UID filesystem sandbox.

Copies are capped at 128 MiB with a cooperative 30-second deadline: source size is checked before integrity scanning, with progress/time checks during backup/hash. Blocking filesystem calls such as fsync are not forcibly interrupted by this deadline. Inspection rejects non-standalone SQLite headers before opening a published snapshot. It keeps its hash descriptor open from before the SQLite transaction until after SQLite closes, so hashing cannot drop the read lock. Inode/size checks detect ordinary replacement; hostile same-UID races remain outside the guarantee. The digest identifies bytes, not authenticated authorship or proof of a safe restore.

Publication uses a private random staging file, validates/hashes the copied database, fsyncs it, then creates the final name with a no-overwrite hard link, removes the staging name and fsyncs the directory. A published-file/late-directory-sync failure returns `snapshot_outcome_uncertain`; the destination may exist, and cleanup does not claim to roll it back. Failed cleanup is best-effort and does not replace that redacted outcome with filesystem details.

A real process crash before the link may leave an orphan staging file and no destination. A crash after the link but before staging unlink may leave two hardlinks. Inspection refuses this unsafe state; no automatic deletion or repair occurs. An operator must verify the matching owned inode before any separate offline cleanup, rather than bypassing the hardlink gate. Unknown staging files are not reused or adopted by a later create.

## Evidence

Tests cover metadata/canonical consistency, historical retention after forgetting, namespace/schema/config/source rejection, path and permission faults, size/time bounds, post-publication failure, persistent hardlink aliases, real process exit before/after linking, concurrent forgetting, and a separate-process writer that cannot commit during inspect hashing. Native contracts exercise real trusted-local commands, disabled/foreign/remote refusal and model-tool exclusion against the recorded compatibility pin. No real model, credentials, live provider, user profile or external transfer is used. This is synthetic validation, not deployment or user acceptance.

## Concurrent inspection lock lifetime (#94)

Controlled snapshot inspectors now share a process-local non-reentrant gate from private-file/header validation through SQLite and raw-descriptor cleanup. A second inspector waits only within its cooperative deadline, then returns `snapshot_timeout`; it cannot close a descriptor and release the first inspector's POSIX lock. Both task and memory connection helpers explicitly close connections if PRAGMA/progress setup fails. Cleanup still closes the raw descriptor and releases the gate if connection closure raises.

A synthetic two-inspector regression holds the first read at digest completion, rejects a deadline-limited second read, and verifies with a real separate-process writer that commit remains blocked until the first read finishes. This covers ordinary overlapping plugin inspections, not coordination with arbitrary unmanaged same-process SQLite connections on snapshot files or hostile same-UID access. No restore, authority, schema or release gate changes.
