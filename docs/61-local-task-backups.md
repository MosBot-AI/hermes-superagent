# Explicit Local Task Backups

English | [简体中文](61-local-task-backups-zh.md)

## Status and scope

Implemented development slice of #17 (E2.1/E8.3), not full backup/restore or M1 acceptance. The local operator can create and inspect a consistent standalone snapshot of this profile's `tasks.sqlite3`. It includes task text, historical receipts, revisions, dependency edges and saved native observations. It excludes memory, enrollment/grants, credentials, host sessions, native Kanban state and all other databases. It is not a whole-profile backup, an encrypted vault, a cross-profile migration or permission to replay an external effect.

Only the native local CLI exposes this operation. There is no conversation command, model tool, scheduler, network transfer, automatic backup or automatic restore. The existing `mode: local_tasks` opt-in is required and rechecked with the bound profile before each command. No new configuration or provider is selected.

## Usage

```bash
hermes personal-agent task-backup create --name before-upgrade
hermes personal-agent task-backup inspect --name before-upgrade
```

Names are 1–64 ASCII letters, digits, underscores or hyphens, starting with a letter or digit. No arbitrary destination path or overwrite option is accepted. Files are stored in the current profile's `plugin-data/hermes-personal-agent/task-backups/NAME.sqlite3`. The directory is private (0700), and snapshots are private regular files (0600, one hardlink). Existing unsafe files or directories are refused, never repaired. Private paths and task payload are not printed.

Both commands return `personal.task-backup.v1` JSON containing the name, task-schema version, structural/integrity result, counts for tasks/receipts/events/dependencies, byte size and SHA256. A successful `inspect` returns the same metadata while the snapshot remains unchanged. The digest detects byte changes against a separately retained receipt; it does not establish authenticity or trust in a supplied database. `automatic_restore: false` explicitly distinguishes the snapshot from a restorable whole-profile export.

## Consistency and failure behavior

Creation opens an existing task database read-only and starts a read transaction. It validates the exact current schema and runs SQLite integrity and foreign-key checks without initializing, migrating or checkpointing the source. SQLite's backup API copies that same snapshot, including committed WAL content, into a private temporary file. The output is converted to DELETE journaling, closed, checked, hashed and synced before atomic no-replacement publication. A directory sync precedes the success response.

A writer committing after the source snapshot is established does not partially enter the backup. The backup is a point-in-time view, not necessarily the latest state when the command returns. A long read can delay rollback-journal writers; keep backups occasional. Supported size is at most 512 MiB of logical database pages/output, with a 30-second processing budget plus bounded SQLite lock waits. This is not a real-time deadline or a power-loss durability guarantee for arbitrary filesystems.

Existing names return `backup_exists`; they are never overwritten. Missing stores return `backup_not_found`, and are not created. Foreign, modified or non-current schemas fail closed. Inspect refuses any journal/WAL/SHM sidecars. A timeout or validation failure before publication leaves no named backup; normal cleanup removes the temporary file. Process termination can leave a private `.pending-*` file, which is not a completed backup and is never automatically adopted. If directory sync or output delivery fails after publication, inspect the same name before retrying; do not assume failure means no file exists. No automatic retry or cleanup of user snapshots occurs. A process exit between link publication and temporary-name removal can leave the named snapshot and a `.pending-*` alias pointing to the same inode. Inspection deliberately returns `unsafe_storage_file` until an operator verifies the matching inode/ownership and removes only that temporary alias offline. Do not delete an unverified link or bypass the hardlink check; a new backup name can be used after the source is verified.

Filesystem checks cover pre-existing symlinks, hardlinks, non-private files and writable directories. They do not isolate malicious same-UID or same-process code racing the filesystem. Snapshots are cleartext and can retain historical task text even after live edits. The user controls retention and any later sharing; disabling/uninstalling does not delete snapshots.

## Recovery boundary and verification

No command replaces a live store or imports an older snapshot wholesale. Selective copying into a new task is described below. Restoring old task state could resurrect terminal tasks, old revisions or native references; full recovery requires a separate stop-before-start, authority-aware workflow. Do not copy a backup over a running profile or use it to trigger old external work. For now it is a verified recovery artifact for deliberate offline inspection, not automatic recovery.

Synthetic tests cover DELETE/WAL snapshots, concurrent commits, preserved rows and receipt replay in an isolated test copy, safe publication, duplicate names, unsafe files, schema refusal without mutation, corruption/sidecars, size/deadline limits, late sync failure and redacted CLI errors. Pinned-host tests exercise native registration, creation, reload/inspection and live mode revocation. No personal data, real model, Gateway, provider call or MacBook is used in this slice. Exact counts and CI belong to the final commit; broader #17/E8 criteria remain open.

## Historical recovery reads

The explicit local CLI can now browse and retrieve historical task fields without replacing the live database:

```bash
hermes personal-agent task-backup tasks --name before-upgrade --sha256 DIGEST --limit 10
hermes personal-agent task-backup tasks --name before-upgrade --sha256 DIGEST --after TASK_UUID
hermes personal-agent task-backup show --name before-upgrade --sha256 DIGEST --task-id TASK_UUID
```

Use the exact lowercase SHA256 returned by `create` or `inspect`. Every page and single-task read rechecks that digest before returning content; changed snapshots fail with `backup_changed`. This binds pages to the selected bytes, not to an authenticated origin. There is no arbitrary path, model tool, native conversation command or network upload. The existing live profile/mode checks still apply. A missing live task database does not prevent reading a valid named snapshot and is never recreated by a read.

`tasks` returns newest-first ID, title, saved state/revision, due date, project and work status, with an opaque task-ID cursor, default 10 and maximum 20 items. `show` returns the selected task's stored fields, including details and notes. Neither returns receipt bodies, dependency edges or native-observation metadata. Returned text is historical untrusted data, not instructions, current task state, owner authority or permission to replay an effect. Tasks completed or changed since the snapshot remain unchanged in the live store. Content previously edited out of the live store may still be present in the backup and in the terminal output; this is deliberate explicit recovery inspection, not forgetting or reactivation.

All reads retain the private-path, exact-schema, integrity, sidecar and processing-budget gates. The SQLite read transaction stays open while hashing and selecting rows, preventing an ordinary DELETE-journal writer from committing a different snapshot between those steps. Filesystem isolation against malicious same-UID code is still not promised. A selected row exceeding 32,000 stored bytes, or a historical result exceeding 80,000 ASCII-serialized JSON characters, fails without returning a partial result. `invalid_cursor`, `not_found`, `backup_record_too_large` and `backup_result_too_large` are explicit read failures. SQLite/path errors are redacted. No initialization, migration, task mutation, receipt replay, import or restore is performed.

Inspection and recovery reads now reject non-DELETE SQLite header modes before opening the file (`backup_not_standalone`). This prevents SQLite from creating WAL/SHM sidecars even when a modified WAL-mode snapshot was cleanly closed and had no sidecars initially.

## Explicit recovery as a new task

The local operator can preview and copy one selected historical task into the current profile:

```bash
hermes personal-agent task-backup recover-preview --name before-upgrade --sha256 DIGEST --task-id TASK_UUID
hermes personal-agent task-backup recover-copy --name before-upgrade --sha256 DIGEST --task-id TASK_UUID --request-id recovery-1
```

Preview validates the snapshot and task, returns only the fields eligible for copying, and never opens or creates the live task store. It is a useful review step, not a one-use approval token: `recover-copy` is itself the explicit local operator command and can be called independently. Both require the exact selected snapshot digest. The CLI retains its live profile/mode and private-file checks; there is no model tool or conversation alias.

Copy creates a **new** captured task at revision 1 with a fresh ID, current timestamps, empty progress/resolution notes and normal ready status. Only title, details, optional project label and due date are copied. It never imports the old ID, state, timestamps, progress, dependencies, receipts, native observations or authority. Even a historical completed task becomes a new local record, not a reversal of the original task's completion. No existing task is replaced, no external work is executed and no worker is dispatched. An old due date remains explicitly historical, not a new notification request. This is selective text recovery, not database restoration or a full-profile migration. `automatic_restore` remains false.

The original snapshot SHA256, original task ID and normalized copied fields are bound to the live store's durable request receipt. Use the same request ID and exact selection after an uncertain response. A successful replay returns the original new-task ID and historical revision without duplicating or undoing later changes. A different source/task or changed fields under the same key fails with `idempotency_conflict`; a new key deliberately creates another copy. The task, `recover_copy` history event and receipt commit together or roll back together. No schema migration is added.

Every retry still validates and reads the named source snapshot first. Keep that snapshot unchanged until the recovery outcome is known. If it is removed or changed, retry fails closed rather than replaying a receipt without its source; inspect the live tasks instead of inventing a new key. Identical snapshot bytes under another valid name represent the same source. SHA256 binds content, not authenticity. Historical text can contain untrusted instructions and is revalidated as ordinary task fields before the live store is opened. The explicit command displays copied text in terminal output; no provider receives it automatically.

Tests cover pure preview with missing live storage, fresh-record semantics, unchanged original tasks, durable replay after later completion, changed source/key conflicts, invalid text/digest/task/request refusal, atomic event-failure rollback, and actual pinned-host CLI reload/mode revocation. These are isolated synthetic tests, not real-device/provider acceptance or a complete backup/restore claim.
