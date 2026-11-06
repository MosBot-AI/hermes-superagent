# 24. Local Project Groups

English | [简体中文](24-local-project-groups-zh.md)

**Implemented development slice: explicit local task grouping and progress counts.** A trusted local operator can organize the existing inbox by a single project label, filter its tasks and inspect each group's current counts. This is not a native Hermes Project, Kanban board, worker assignment, authorization scope or completed personal-agent MVP.

This extends the [local inbox](16-local-task-inbox.md), [agenda](17-local-task-agenda.md) and [literal search](22-local-task-search.md) on the same pinned Hermes baseline. It needs no API Key. Production owner identity, Primary Bot binding and personal-data channel/HTTP access remain disabled; see [18](18-owner-entry-and-read-authorization.md) and the [host-context experiment](23-host-command-context-experiment.md).

## 1. Enable and Organize

Use the existing isolated-profile setup and explicit `mode: local_tasks` opt-in from [16](16-local-task-inbox.md). Default `read_only` still refuses all task commands before opening storage. The CLI requires the tested `in_process` host mode; do not disable existing isolation to expose it.

```bash
hermes personal-agent tasks capture \
  --title "Review the migration plan" --project "Website" \
  --due-date 2026-11-20 --request-id website-capture-001
hermes personal-agent tasks list --project "Website"
hermes personal-agent tasks search --query "migration" --project "Website"
hermes personal-agent tasks agenda --on 2026-11-20 --project "Website"
hermes personal-agent tasks projects --limit 20
```

A task has at most one nullable `project` label. New tasks without a label are unassigned. Labels are exact, case-sensitive strings of 1–80 characters with no surrounding whitespace, line breaks or forbidden control/format characters. Unicode normalization is not performed. `Website`, `website` and visually similar Unicode strings can therefore identify different groups. Labels are not IDs or proof that an external project exists.

Copy the task UUID and current revision from the response:

```bash
TASK_ID="UUID returned by capture"
hermes personal-agent tasks update "$TASK_ID" \
  --project "Website launch" --expected-revision 1 --request-id website-move-001
hermes personal-agent tasks update "$TASK_ID" \
  --clear-project --expected-revision 2 --request-id website-clear-001
hermes personal-agent tasks list --unassigned
```

Assignment changes use the existing revision and request-ID gates. `--project` and `--clear-project` are mutually exclusive. Terminal tasks cannot be edited or regrouped; their historical group remains visible in counts and explicit terminal-state queries. No bulk rename, project entity creation, deletion, archive or project lifecycle command is added. A group exists while at least one task carries that exact label, including terminal tasks.

## 2. Filters and Summary Contract

`list`, `search` and `agenda` accept mutually exclusive `--project NAME` or `--unassigned`. Without either, all project assignments are eligible. Existing state/date/query filters still apply: list/search default to `captured`; agenda includes only captured tasks due on or before its explicit date. A filter matching no tasks returns an empty page, not an error.

`projects` accepts `--limit` (1–100, default 20) and `--after` (a valid project label). It returns the existing `personal.local-tasks.v1` CLI envelope. Its `data` is shaped as follows; numbers are an illustrative local snapshot:

```json
{
  "items": [
    {"project": "Website", "captured": 2, "done": 1, "cancelled": 0, "total": 3}
  ],
  "unassigned_counts": {"captured": 1, "done": 0, "cancelled": 0, "total": 1},
  "next_cursor": null,
  "has_more": false
}
```

Counts include all task states and only this profile's plugin-owned store. Each projects response uses one read snapshot for its label buckets and unassigned counts; separate page requests remain live and may reflect intervening edits. Unassigned counts are returned separately on every page and must not be summed across pages. They are not a named bucket, do not consume the label-page limit and do not have a cursor. Completion counts represent local operator assertions, not independently verified external outcomes.

Groups are ordered by SQLite binary text order, ascending. The cursor is the last label when another page exists. It is a syntactically valid keyset boundary rather than a signed token and remains usable if that label later disappears. Pages are live, not a stable multi-page snapshot: edits between calls can change counts and membership. Do not use totals across multiple calls as an atomic report. The cursor for list/search remains a task UUID; agenda retains its date/sequence cursor semantics. Keep the same filters while paging tasks.

## 3. Persistence and Compatibility

The store's current schema version is 3. Initialization accepts only the exact owned v1/v2 schemas or exact v3 schema. It atomically adds the missing `due_date` and/or nullable `project` columns, verifies the resulting schema and commits. Foreign or structurally modified databases are refused rather than repaired. Existing tasks become unassigned; no project is inferred from titles or details.

The upgrade preserves task IDs, creation sequence, timestamps, revisions, events, request digests and serialized receipt bytes. Omitting new capture/update fields does not insert new defaults into old request digests. A replay returns its original historical receipt, which can omit `due_date` or `project`; a fresh show/list/search/agenda returns the current task representation including both nullable fields. Explicit values, including an explicit clearing operation, are distinct requests. Do not reuse an old request ID for changed content.

An upgraded database is not readable by the older schema-v2 plugin. Rollback is not an automatic down-migration. Backup/restore remains unimplemented; plan recovery before using experimental schema upgrades with valuable data. A derived group read does not mutate task records or receipts, but opening any task command can initialize or migrate storage, so this is not a zero-disk-write promise.

## 4. Safety and Remaining Product Gates

- Existing profile binding, explicit opt-in, POSIX private-directory/main-file/sidecar checks, redacted errors and pre-storage validation apply unchanged. Windows task storage remains unsupported; Linux is tested.
- The local OS account is trusted. A project label does not isolate tasks from other code running as that user, change a permission grant or authenticate an owner. Do not expose these commands through an untrusted remote executor.
- Labels, task text and counts are plaintext local data. Arguments may appear in shell history or process listings. No credentials, account connections, remote writes or background work are introduced.
- There is no model tool for this data, private slash-command access, HTTP endpoint, native Project/Kanban mapping, dispatch, schedule or reminder delivery. No existing release gate is opened by grouping.

This is a narrow E2.1/E2.2 local precursor. E3.1 native project mapping and E1 owner/action authorization remain separate requirements in [08](08-roadmap-and-acceptance.md). Integration must use stable domain/native IDs and verified authority, not promote these display labels into identity or permission keys.

## 5. Verification Scope

Project unit tests cover validation, exact filtering, unassigned tasks, grouping/counts, pagination, revision/idempotency behavior, and v1/v2 migration with historical receipt preservation. Pinned-host contracts exercise the actual registered CLI, its mode/profile/storage gates and synthetic persistence. The [repository checker](../README.md#development-checks) runs these with the existing offline guard and fixed upstream checkout.

Tests do not authorize a real owner, exercise production accounts or validate the restricted identity socket cases. The separately packaged host-context patch is not applied by installation or by the ordinary project checks.
