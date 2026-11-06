# 17. Local Due Dates, Agenda and Schema Upgrade

English | [简体中文](17-local-task-agenda-zh.md)

**Implemented local CLI extension, not reminder delivery.** The opt-in [local inbox](16-local-task-inbox.md) now accepts date-only deadlines and provides an agenda for an explicitly selected date. The same local-operator/profile boundary remains. No model, channel, HTTP, worker, scheduler, Primary Bot binding or outbound action is enabled.

This advances the E2.1 local-store precursor and its E8.3 schema-compatibility tests. It does not complete E1, E2, E4 or M1. Hermes remains pinned to `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`; no new host API or provider credential is needed.

## 1. Dates Mean Calendar Dates

`due_date` is an optional Gregorian date in exact `YYYY-MM-DD` format. It is not a timestamp or reminder occurrence. A task due on 2028-02-29 has no inferred hour, offset, timezone or delivery deadline. Dates must exist in the calendar; leap days are validated. Whitespace, alternate formats, natural language, timestamps and invalid types are refused before opening task storage.

The agenda requires `--on`; it never silently uses the computer's date or the user's presumed location. The operator selects the calendar date to compare. An overdue item has `due_date < on`, and an item due that day has `due_date == on`. Undated, future, done and cancelled tasks are excluded.

For time-of-day, IANA timezone, DST, recurrence, quiet hours and actual delivery, the E4 contracts still need implementation. Do not convert a date-only value into midnight or claim a notification will arrive.

## 2. Commands

Enable `mode: local_tasks` in an isolated tested profile as described in [16](16-local-task-inbox.md). Existing commands remain compatible.

```bash
hermes personal-agent tasks capture \
  --title "Prepare the weekly review" \
  --due-date 2028-02-29 --request-id dated-capture-001
hermes personal-agent tasks agenda --on 2028-02-29 --limit 20
```

Use the actual UUID and current revision returned by capture or show:

```bash
TASK_ID="UUID returned by capture"
hermes personal-agent tasks update "$TASK_ID" \
  --expected-revision 1 --due-date 2028-03-01 --request-id dated-edit-001
hermes personal-agent tasks update "$TASK_ID" \
  --expected-revision 2 --clear-due --request-id dated-clear-001
```

`--due-date` and `--clear-due` are mutually exclusive on update. Clearing maps to an explicit `due_date: null`; omitting both preserves the current value. Capture accepts an optional date string, not a clear flag. An update may change only the date, or combine it with title/details. Existing revision, terminal-state and request-ID rules still apply.

| Operation | Date contract | Result |
|---|---|---|
| `capture` | Optional `due_date` string | Current task includes a date or null |
| `update` | Optional date string or explicit null | Date set/cleared, revision incremented once |
| `show` / `list` | No new required input | Current tasks include nullable `due_date` |
| `agenda` | Required `on`, optional limit and after | Active tasks due on/before on, oldest due date first |

The envelope remains `personal.local-tasks.v1`. New current task views add `due_date`. The agenda data has `on`, `items`, `next_cursor` and `has_more`. Limit defaults to 20 and must be 1–100. Pass the returned UUID as `--after` for the next page with the same `--on` date.

## 3. Agenda Ordering and Concurrent Changes

Ordering is `due_date` ascending, then creation sequence ascending for equal dates. The query asks for at most limit plus one rows, so neither command output nor the result set is unbounded. This is live keyset pagination, not a consistent multi-page snapshot or a change feed.

The cursor is resolved in the current profile's own store. A missing, undated or later-than-on cursor is rejected with `invalid_cursor`. A dated task that was completed between pages can still anchor the next page, although it is no longer an agenda item. A date edit between pages can move the anchor or change membership, causing omissions or repeats; restart from the first page for a fresh overview. Reusing a cursor with a different on date changes the query and is not continuation of the original view.

Completing/cancelling a task removes it from future agenda queries without deleting its record, date or original receipts. Editing or clearing a date is a normal atomic mutation, not schedule creation or cancellation.

## 4. Transactional Schema v1 to v2 Migration

The plugin owns only its profile-local `tasks.sqlite3`. Existing profile/file/sidecar guards apply before opening it. With explicit local_tasks mode, the first valid task command initializes a fresh v2 store or upgrades an exact recognized v1 store. This includes list, show and agenda: a logical read can perform the plugin's own initialization/migration. Status, coverage and read_only refusal do not open or migrate task storage.

The migration checks the application ownership marker and the exact supported v1 schema under `BEGIN IMMEDIATE`, adds nullable `due_date`, updates the schema version and commits atomically. Existing task IDs, revisions, dates of creation/change, events and receipt bytes remain unchanged. Pre-existing tasks have no due date. Fresh and upgraded v2 stores must pass the same schema verification.

A failure before commit rolls back both the schema and version change; the same original store can be retried after the cause is resolved. Concurrent initialization is serialized. Foreign, newer and modified schemas are refused rather than repaired, replaced or partially adopted. SQLite corruption and busy errors retain their existing redacted behavior.

This is a one-way supported upgrade. Older plugin code that only knows v1 must refuse v2; automatic downgrade is not implemented. Back up a real profile using an independently verified consistent backup procedure before upgrading. No new backup/restore command, automatic backup, retention policy or cross-host migration is provided here. Copying an open database without its transaction state is not a supported backup procedure.

## 5. Receipt Compatibility

Adding a date does not change the canonical payload of old commands that omitted the field. An old v1 capture/update retry with the same operation, request ID and payload must still find the original digest after migration. The migration never rewrites receipts.

Replay returns the original historical result exactly, so a v1 receipt may **lack** the `due_date` key. This is distinct from a fresh current read with `due_date: null`. After replay, use show for the current state. Do not backfill an old receipt from current task data, because the current revision or date might have changed.

A new explicit date or explicit clear under an already-used key is a different payload and is refused with `idempotency_conflict`. Use a new request ID for a new edit, while preserving the current expected revision. Migration itself does not create a user mutation, increment task revisions or invent a completion event.

## 6. Verification and Remaining Scope

Tests cover strict date/leap-day/type validation, set/clear/replay/CAS, exclusion of terminal/undated/future tasks, deterministic equal-date pagination, bounded pages and restart persistence. Migration fixtures exercise real v1 schema/data/digests, old receipt replay, interrupted and concurrent upgrades, foreign/newer/modified schema refusal and rollback. Pinned-host contracts exercise the registered CLI and clean top-level CLI subprocesses with socket-connect guards.

Only synthetic local profiles are used. No API Key, real account, provider request, native cron job, mobile-device identity or outbound send is involved. Run the [full repository checker](../README.md#development-checks) against the exact commit before using its compatibility claim. Independent review and CI do not turn this local feature into verified owner authorization or reminder delivery.

The data remains plaintext and subject to the local OS account and the privacy/retention limits in [16](16-local-task-inbox.md). The next agent/channel/HTTP integration still requires E1 and applicable enforcement/recovery gates; the local agenda does not bypass them.
