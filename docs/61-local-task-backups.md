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

No command replaces a live store or imports an older snapshot. Restoring old task state could resurrect terminal tasks, old revisions or native references; full recovery requires a separate stop-before-start, authority-aware workflow. Do not copy a backup over a running profile or use it to trigger old external work. For now it is a verified recovery artifact for deliberate offline inspection, not automatic recovery.

Synthetic tests cover DELETE/WAL snapshots, concurrent commits, preserved rows and receipt replay in an isolated test copy, safe publication, duplicate names, unsafe files, schema refusal without mutation, corruption/sidecars, size/deadline limits, late sync failure and redacted CLI errors. Pinned-host tests exercise native registration, creation, reload/inspection and live mode revocation. No personal data, real model, Gateway, provider call or MacBook is used in this slice. Exact counts and CI belong to the final commit; broader #17/E8 criteria remain open.
