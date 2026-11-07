# 34. Local Task Operation History

English | [简体中文](34-local-task-history-zh.md)

Implemented: bounded operation history for an existing local task through the CLI, native `/personal-tasks` command and separately activated `personal_tasks_read` tool. This is a narrow E2.1/E3.5 recovery aid, not native worker reconciliation, task execution, a reminder or a new authorization surface.

## 1. Read the Stored Progress

Use the same trusted single-user profile and existing [local task opt-in](16-local-task-inbox.md). Substitute a task ID returned by `list`, `search` or `show`:

```text
hermes personal-agent tasks history TASK_ID --limit 20
hermes personal-agent tasks history TASK_ID --after-revision 20 --limit 20
/personal-tasks history TASK_ID --limit 20
/personal-tasks history TASK_ID --after-revision 20 --limit 20
```

The native slash command requires the existing `local_conversation: true` setting and host session admission. For model use, the existing `local_model_tools: true` setting and current `/personal-tools enable-read` or `enable-write` activation remain required. No extra setting or activation is added. The read tool accepts:

```json
{"action":"history","task_id":"00000000-0000-4000-8000-000000000001","limit":20,"after_revision":0}
```

The example UUID is synthetic. Use an actual returned ID rather than copying it into a live request. A model can inspect history after an uncertain write but should still read the task's current contents with `show` and reconcile the original request. History does not return request IDs, prove that a particular retry key committed, or replace retrying an identical payload with its original stable key.

## 2. Bounded Result and Cursor Contract

History returns `task_id`, `current_revision`, `current_state`, `items`, `has_more` and `next_cursor` inside the entry point's existing `data` envelope. Each item contains only `revision`, `operation` and the original UTC `timestamp`. Operations are `capture`, `update`, `complete` or `cancel`, ordered by increasing task revision. Task titles, details, project labels, old field values, resolution notes and receipt bodies are not included.

`limit` defaults to 20 and accepts integers from 1 to 100. `after_revision` defaults to 0, which starts at the beginning. To continue a non-final page, pass its integer `next_cursor` as `after_revision` with the **same task ID**. This is different from the `after` string field used by other readers. A positive cursor must identify an existing event for that task; a future or missing revision returns `invalid_cursor`. Unknown task IDs return `not_found`. Wrong types, unrelated fields, missing IDs and invalid bounds return the existing redacted `invalid_request` error.

Each page's current metadata and events share one SQLite read snapshot. Pages are live, not a frozen export: a later page may report a higher current revision if another operation committed. Revisions provide ordering even if wall-clock timestamps are equal or the system clock changes. Replaying a successful request or rejecting a stale revision/idempotency conflict does not add an event. A final page has `has_more: false` and `next_cursor: null`; reading after the current revision yields no items. To poll for later events, retain the last returned event revision, not a null cursor.

## 3. Persistence, Privacy and Limits

History reads the existing schema-v3 `events` table and adds no migration, new record type, automatic ingestion or background work. Existing v1/v2 stores retain their event rows through the already-supported upgrade. Metadata survives plugin reload and process restart. The operation itself uses a deferred read transaction; the existing storage opener still performs its standard schema verification or supported legacy upgrade.

This is operation metadata, not a verified author audit or a transcript. It does not distinguish CLI/slash/model authors, record which fields changed, reconstruct old task content or prove that a real-world task was performed. `complete` means the local record was marked done. This feature does not solve broader task retention, restore, deletion or native Kanban/worker reconciliation requirements.

Metadata can still be personal. Model-tool results enter the configured model context and normal host history, subject to the same privacy, cost and retention boundaries as other [task tools](29-session-scoped-task-tools.md). Every read retains the existing profile/session/route/turn/TTL gates. Read-only plugin mode, unsupported origins, absent activation, disable and unload do not become bypassable through `history`. No remote endpoint, second model call, scheduler job or external action is added.

## 4. Verification

Synthetic unit tests cover terminal and active tasks, ordered bounded pages, private-content omission, successful retry deduplication, rejected-write behavior, task separation, same-page read consistency under a concurrent append, persistence, legacy migration, validation and transaction cleanup after injected failures. Pinned-host contracts cover real CLI reload, native slash dispatch, activated model-tool dispatch, read activation, wrong-session/no-turn/disable denial and malformed-cursor handling.

Tests use temporary profiles and no credentials, live model or network calls. The existing real-provider natural-language acceptance gate remains pending; passing deterministic history contracts does not complete E3.5 or M1 end-to-end acceptance.
