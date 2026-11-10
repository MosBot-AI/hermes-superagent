# Explicit local memory index inspection and recovery

English | [简体中文](72-memory-index-recovery-zh.md)

## Purpose and operator workflow

SQLite canonical records remain the authority. The FTS index is a derived search structure, not a backup. A missing or outdated derived row can make term search miss a valid record even when SQLite and FTS internal integrity checks pass. This workflow checks the index against canonical records and offers explicit recovery from supported derived-index inconsistency.

```text
/personal-memory index-status
/personal-memory index-rebuild --expected-watermark N
```

Use the actual canonical event watermark returned by index-status, not a guessed number. Inspect the status before deciding to rebuild. Both operations are operator-only under the existing trusted single-user profile boundary. They do not add a model tool, select a provider, call a model, read a source document or contact a remote service. Rebuild is never automatic and normal search does not silently invoke it.

The workflow requires an existing owned current-schema store. It does not create a missing database, migrate an older database or adopt a foreign namespace. Unknown schemas, unsafe files, unsupported storage and disabled persistent FTS secure-delete settings remain refusals, not invitations to repair security settings. Use the normal explicitly chosen compatible writer workflow for supported schema upgrades, not index maintenance as a shortcut.

## What status proves

Inspection validates canonical structure and bounded record/event consistency before trusting records as a rebuild source. It checks the correspondence in both directions: active canonical rows missing from FTS, extra FTS rows without an active canonical counterpart, and content/topic mismatches. It also checks FTS internal consistency. Results contain counts, state and the current event watermark, never stale indexed text or canonical payload.

Expired active records belong in the index under the existing contract; fresh queries still filter them by expiry. Forgotten records do not belong there. A healthy result applies only to this inspection snapshot, not all later reads, restored copies or external mutations. Search_terms now verifies logical document correspondence and complete current-query coverage before reporting `index_stale: false`; this is not a global forensic health check.

Inspection uses a fresh database connection and acquires the shared writer fence before its first FTS access. This avoids treating a long-lived connection's stale FTS configuration cache as persisted corruption. The native FTS integrity command uses an SQL INSERT-shaped control command; status is therefore not a SQLite query-only operation. It checks within a rollback-only subtransaction and does not commit new canonical or index-content changes. SQLite may recover an already existing safely owned rollback journal from an interrupted transaction; this is not a promise of byte-for-byte unchanged files. It can briefly contend with normal writes. A WAL-format file without existing sidecars may cause SQLite to create bookkeeping sidecars before its mode is detected and refused; maintenance does not switch the journal mode or continue. A refusal is therefore not a guarantee of no filesystem side effects. The path checks deliberately avoid opening and closing a raw database descriptor that could release another same-process SQLite connection's POSIX locks.

## Explicit rebuilding and recovery limits

Rebuild rechecks the expected watermark and canonical validity under the same writer transaction used to recreate and verify the index. It uses only current active canonical records, never cached payload or old index contents. Both logical correspondence and FTS internal integrity must pass before commit. The fixed FTS virtual table and its derived shadow tables are the only reconstruction target; no arbitrary table or SQL input is accepted.

Canonical records, revisions, events, receipts, expiry, Markdown projections and editable drafts are not modified. A concurrent correction or forget is ordered by the shared writer fence: a rebuild cannot publish an older cached fact after a committed forget. Any failure before commit rolls back the derived changes. The operation is not a repair for damaged canonical data, unknown database formats or unsafe settings. If safe attribution cannot be established, stop rather than guessing which facts to preserve.

There is no request ID or stored historical maintenance receipt. Repeating rebuild at the same current watermark safely reconstructs the same derived state; a supported canonical mutation advances that watermark and makes the old request stale. After an uncertain result or restart, inspect current status. A new status is a fresh check, not proof of what an interrupted invocation did. The watermark is a supported-write concurrency fence, not protection against arbitrary direct database modification or stale backup replacement.

This is logical index recovery, not physical-media erasure, backup restore, source-level re-extraction suppression or a promise to find data missing from the canonical store. Previous history, open readers, copied files and backups retain their existing limits. No installation or deployment is part of the workflow.

## Verification boundary

The acceptance matrix covers missing, extra and mismatched FTS rows, forgotten-row residue, actual inverted-index failures, unsafe configuration and canonical corruption refusals, old-schema/missing-file handling, watermark conflicts, concurrent correction/forgetting, transaction failures, process crashes and safe repeats. It includes independent fresh-connection SQLite/FTS checks on the supported test builds, plus pinned-host operator admission and model-tool refusal.

Exact run counts and versions are recorded with the linked PR. Synthetic fault injection does not establish that normal supported writes currently corrupt the index, nor does it certify production database repair. This is a bounded #44 recovery slice; broader import, source suppression, migration and live acceptance remain open.

Current search freshness now fails closed with `index_stale` on logical document or current-query coverage drift, within one read transaction and before pagination. No partial results or automatic repair. See [acceptance evidence](81-local-memory-acceptance.md).
