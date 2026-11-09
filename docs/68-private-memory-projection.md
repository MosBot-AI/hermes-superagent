# Private Markdown memory projection

English | [简体中文](68-private-memory-projection-zh.md)

## Explicit local operator workflow

SQLite remains the only canonical memory store. A generated Markdown file makes whole records inspectable outside the command view without enabling an importer, watcher, model file tool or external integration.

```text
/personal-memory projection-status
/personal-memory projection-refresh
/personal-memory projection-disable
/personal-memory --json projection-status
```

The first explicit refresh enables the projection. Status, refresh and disable return structured metadata; they do not change model tool schemas or grant model access to these operations. Existing local-memory admission and profile checks still apply. Status does not enable the projection or generate a Markdown file; ordinary native storage opening may still initialize or migrate the SQLite store.

The only destination is `memory/records.md` inside the current profile's private plugin-data directory, beside `records.sqlite3`. No arbitrary output path is accepted. Hermes `MEMORY.md` and `USER.md` are untouched. The reserved staging file is `.records.md.pending`; it is managed recovery state, not an editable document. POSIX private directories and owned regular single-link files are required; newly generated files use mode `0600`.

## Snapshot meaning and editing

The file includes namespace, canonical event watermark, evaluation time and complete active records with IDs, revisions, source metadata and expiry. Expired active records remain included and labelled; forgotten payloads are excluded. Quoted JSON in indented Markdown code blocks preserves Chinese while escaping controls and preventing stored Markdown/HTML from becoming generated headings or links. Stored text is not instructions, permission or verified provenance.

This is a snapshot, not a backup or a live view. Check `current`, `dirty`, `stale_by_time`, file/staging presence and published/pending metadata using status. Passing the next expiry boundary can make a snapshot stale without any new event; a clock rollback to before evaluation also marks it stale. Status itself describes one observation, not a guarantee against later changes.

Do not edit the managed file. Use explicit memory corrections and then refresh. An unexpected content hash is a conflict, not permission to overwrite. Unsafe files or a conflict can also block canonical changes while projection is enabled, because those changes must safely invalidate the old view first. Resolve the file condition as a local operator rather than bypassing the protection. There is no automatic refresh or Markdown import.

Use `projection-disable` to stop managing the projection. Under the writer fence it validates and removes the known generated destination and controlled staging file, syncs the directory, and then removes projection metadata. Canonical memories are unchanged. Repeating disable is safe when already disabled and no unknown files exist; an unknown or edited file remains a conflict, not an invitation to force-delete. A later explicit refresh can enable the projection again.

## Publication, mutation and recovery

Schema v8 adds persistent projection metadata. A compatible writable opener migrates older supported stores; read-only access cannot perform migration. An enabled projection requires the correctly bound private-file adapter for subsequent canonical mutation, including candidate acceptance. A bare backend cannot bypass file invalidation.

Refresh uses two durable phases, not an atomic SQLite-and-filesystem transaction:

1. Under the SQLite writer fence, render a canonical snapshot and commit a pending publication identity, watermark, digest and evaluation metadata.
2. Reacquire the same fence, verify the pending identity and current watermark, regenerate and verify the digest, then write/fsync the staging file, atomically replace the destination and fsync its directory. Commit the publication receipt afterward.

A competing canonical change invalidates the pending snapshot. It removes the known published file and controlled staging payload under the same writer fence before the canonical transaction can commit. Thus a paused older renderer cannot republish forgotten content after a successful forget. File invalidation failure prevents that canonical change from committing; callers must not treat the error as a successful edit.

A crash may leave pending metadata, a staging file, a missing projection or a generated file whose final database receipt was not committed. Durable pending digests distinguish known generated content from an unknown edited destination. A later explicit refresh reconciles and rebuilds from current canonical records rather than replaying an old cached snapshot. A failed database commit after file removal can leave the old canonical record with no projection; refresh reconstructs it. Inspect current state before retrying an uncertain write, retaining its request ID and identical arguments where applicable.

No mechanism retracts an already opened file descriptor, a copied document, backups or filesystem snapshots. Same-user hostile filesystem mutation is outside the trusted local deployment boundary. The projection does not claim secure physical erasure, cross-platform support or live-user acceptance.

## Verification scope

Validation must cover schema migration and read-only refusal, ordinary changes and candidate acceptance, idempotent retries, refresh/forget concurrency, crash boundaries, pending-publication recovery, manually edited files, unsafe paths/links, expiry-only staleness and rendering injection. Offline synthetic profiles are not deployment evidence. See the linked PR for the exact completed test results and compatibility revision.
