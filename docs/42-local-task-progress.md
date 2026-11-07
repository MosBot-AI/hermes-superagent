# 42. Durable Local Task Progress

English | [简体中文](42-local-task-progress-zh.md)

Implemented: explicit working, waiting and blocker records for existing active local tasks. The CLI, native `/personal-tasks` command and activated task model tools share the same revisions, durable receipts and progress filters. This advances local task recovery and review; it does not dispatch a worker, verify native execution, create a dependency graph or complete E3.2/E3.5.

## 1. Record a Progress Update

Use the existing [trusted local task configuration](28-profile-first-local-conversations.md) and a real task ID/current revision from `show`, `list` or another successful result. Each update requires a work status and a nonblank explanation.

```text
hermes personal-agent tasks progress TASK_ID --expected-revision 1 --work-status in_progress --note "Started reviewing the draft" --request-id progress-1
/personal-tasks progress TASK_ID --expected-revision 2 --work-status blocked --note "Waiting for the missing attachment" --request-id progress-2
/personal-tasks progress TASK_ID --expected-revision 3 --work-status ready --note "Attachment received; ready for review" --request-id progress-3
/personal-tasks list --work-status blocked --project "Demo"
/personal-tasks review --on 2026-11-07 --work-status waiting
```

CLI mutations require `--request-id`. Native conversation commands may generate and return a fresh key if omitted, as with other existing writes. After an uncertain result, retry the same command and exact key; a fresh key is not a safe retry. Progress writes also require the existing model write activation when called through `personal_tasks_write`:

```json
{"action":"progress","task_id":"00000000-0000-4000-8000-000000000001","expected_revision":3,"request_id":"progress-3","work_status":"ready","note":"Attachment received; ready for review"}
```

The UUID/date are synthetic examples, not live task references. Model tools must use IDs and revisions returned by the store and record only the user's explicitly requested local progress. Activated model activity is not verified human-origin evidence. No new configuration, registration, permission or model call is added.

## 2. Lifecycle and Progress Are Separate

The existing lifecycle remains `captured`, `done` or `cancelled`. Active tasks have `state: captured`; recording progress does not complete, cancel or reopen them. `work_status` is one of:

- `ready`: no active working/waiting/blocker label is recorded. It is the initial value, not a claim that acceptance criteria or execution authorization are satisfied.
- `in_progress`: local work has explicitly been recorded as underway. It does not establish that any native process or worker is currently alive.
- `waiting`: an explicit pause pending input or another event. No watcher, deadline or automatic resume is created.
- `blocked`: an explicit blocker prevents further work. No dependency or escalation is inferred from the note.

Every active task may transition to any of these values, including the same status with a new note. Each new accepted request increments the task revision once, updates `updated_at` and `progress_updated_at`, stores the current `progress_note`, and appends a `progress` metadata event. `note` accepts 1–2000 characters, must contain non-whitespace text and follows the existing multiline/control-character checks.

Task `update` cannot change progress fields; it preserves the recorded status/note/timestamp. Use `progress` for an explicit change, including clearing a blocker with `ready` and an explanation. Due date, project, title and details are not changed by progress. `resolved_at` and `resolution_note` stay unset for active records. Complete/cancel retain the last progress values as historical context, while lifecycle state becomes terminal. Further progress is rejected with `terminal_state`; a preserved `blocked` value on a done task is not an active blocker.

## 3. Inspect Progress and Retry Safely

Full task readers return `work_status`, `progress_note` and `progress_updated_at`. `list`, literal title/details `search`, `agenda` and [daily review](40-daily-task-review.md) accept optional exact `work_status` filtering, combined with existing project/unassigned filters. For list/search, `state` must be omitted or `captured` when a work-status filter is present; terminal records remain available with ordinary `show` or unfiltered state reads. Search deliberately does not search progress notes.

Daily review returns `progress_counts` for all matching active tasks, with keys `ready`, `in_progress`, `waiting` and `blocked`; their sum equals `counts.total_active`. Summary items include `work_status`, but not the progress note or timestamp. The existing shared output budget and single-snapshot behavior still apply. Totals describe the full matching population even when summaries are omitted; they are not worker-health metrics.

History exposes only revision, operation and timestamp, not the progress note or previous statuses. The current note is replaceable, but old write receipts, normal host history and backups may retain prior note text. This is not a private append-only work log or a verified-author audit, and editing a note is not erasure.

All writes use the existing task-level compare-and-swap and idempotency contracts. A stale revision returns `revision_conflict`; read current state and reconcile before making a new change. Reusing a key with a different payload returns `idempotency_conflict`. A successful identical retry returns its original saved receipt with `replayed: true`, even after later updates. That old receipt is not current task state; use `show` if current state is needed. An uncertain outcome never triggers an automatic retry or additional work.

## 4. Atomic Task Schema v4 Upgrade

Fresh task stores use schema v4. Exactly recognized owned v1/v2/v3 stores upgrade inside the existing single transaction: preserve the prior due-date/project upgrades as needed, then add `work_status`, `progress_note` and `progress_updated_at`. Existing records receive `ready`, an empty note and a null progress timestamp. No past activity is inferred for active or terminal records.

Task IDs, prior fields, sequence order, revisions, event rows and receipt bytes are preserved. Old successful request retries retain their original response shape, so legacy receipts may omit the new fields. A fresh `show`/list returns the current complete shape. Fresh and migrated stores have identical checked DDL. Unknown/modified schemas, extra indexes/triggers/tables and foreign databases still fail closed without repair. A failure at any migration step rolls back the entire upgrade.

Task schema v4 is independent of the dedicated memory database's schema. The existing private file/profile protections remain unchanged. Older plugin versions reject the newer task schema: there is no automatic downgrade, table rebuild or restore procedure in this slice. Retain a supported backup before upgrading any real profile, and do not replace a database while the host is using it. Tests use disposable synthetic profiles only; no production data has been migrated by this development work.

## 5. Admission, Privacy and Evidence

The existing source/profile/session/turn/TTL/unload gates apply to every read and write. `enable-read` cannot record progress. Missing write activation, wrong session/origin, stale revision, terminal state and malformed fields do not mutate data. Progress texts are ordinary plaintext local task data, not a secret store; full task results enter the configured model context and host history under the existing activation contract. The plugin does not authenticate each sentence or secure other host tools. Shared/exposed gateways and unsupported isolation paths remain out of scope.

Tests cover all status transitions, note replacement, unchanged lifecycle, terminal refusal, concurrent CAS, replay after later edits/restart, exact project/status filters, same-snapshot review counts, note omission in review/history, failure rollback, and independently constructed legacy v1/v2/v3 migrations with preserved receipts. Pinned-Hermes contracts exercise CLI reload, native slash-to-model continuity, read-versus-write activation, wrong-session/absent-turn/disable refusal and redacted validation failures. Unit and native contracts are offline; no real-provider natural-language acceptance, native worker reconciliation, reminders or external actions are claimed.

Follow-on: [project dependencies](51-project-task-dependencies.md) add explicit same-project prerequisite sets and a ready queue. Current task storage is schema v5; atomic v1–v4 migration preserves historical receipts. Plan capture itself still does not infer or accept indexed dependencies, and no native Kanban or worker integration is enabled.
