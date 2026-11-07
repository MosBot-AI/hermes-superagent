# 40. Bounded Daily Task Review

English | [简体中文](40-daily-task-review-zh.md)

Implemented: one read-only overview of active local tasks through the existing CLI, native `/personal-tasks` command and activated `personal_tasks_read` tool. Exact counts and bounded title summaries help the user review commitments without loading every task's details. This is not an automatic planner, reminder, priority model or task executor.

## 1. Use the Existing Local Entry Points

Use the existing [local task configuration](16-local-task-inbox.md). No new setting or permission is introduced. Dates below are synthetic; supply the intended calendar date explicitly.

```text
hermes personal-agent tasks review --on 2026-11-07
/personal-tasks review --on 2026-11-07 --project "Demo"
/personal-tasks review --on 2026-11-07 --unassigned --lookahead-days 14
/personal-tasks review --on 2026-11-07 --per-bucket-limit 3 --max-chars 8000
```

Native commands still require `mode: local_tasks` and `local_conversation: true` in a trusted single-user profile. Model reads additionally require `local_model_tools: true` and current `/personal-tools enable-read` or `enable-write` activation in the same native session. The model request is:

```json
{"action":"review","on":"2026-11-07","lookahead_days":7,"per_bucket_limit":5,"max_chars":16000,"project":"Demo"}
```

`project` and `unassigned` are optional and mutually exclusive. The [progress follow-on](42-local-task-progress.md) also adds optional `work_status` filtering for active tasks. Project labels match exactly, including case and literal punctuation. `unassigned: true` selects unlabeled tasks; false does not filter. There is no separate project entity, native Kanban mapping or cross-profile read. Review does not accept `limit`, `after`, `state`, write fields or caller-supplied identity/context.

## 2. Dates, Counts and Summary Order

`on` is a required valid `YYYY-MM-DD` date. No clock, location or timezone is inferred. `lookahead_days` is an integer from 0 to 90, default 7. The response's `through` is `on` plus that many calendar days, inclusive for the upcoming bucket. An overflowing date is rejected, not clamped.

Only tasks currently in `captured` state contribute. Counts cover every matching active task, including tasks omitted from the summaries:

- `overdue`: due date before `on`.
- `due_today`: due date equal to `on`.
- `upcoming`: due date after `on` and on or before `through`.
- `later`: due date after `through`; count only, no sampled titles.
- `undated`: no due date.
- `total_active`: the sum of those five disjoint counts.

The four summary buckets are `overdue`, `due_today`, `upcoming` and `undated`, each containing `total`, `items` and `omitted`. Dated items sort by due date, then original capture order. Undated items use original capture order. This deterministic order does not infer importance, effort, blockers or willingness to work. Done and cancelled tasks are excluded. With a zero-day lookahead, upcoming is empty and all future dated tasks count as later.

The response also includes `progress_counts` for ready/in_progress/waiting/blocked; these sum to total_active. Each summary contains only `id`, `title`, `project`, `due_date`, current `revision` and `work_status`. Details, progress/resolution notes, receipts and operation history are not loaded or returned. Titles and project labels can still be personal or contain untrusted text. The reader does not follow instructions stored in them. Use `show` for current full details before deciding on a change; revisions remain subject to normal compare-and-swap checks.

## 3. Output Bounds and Snapshot Semantics

`per_bucket_limit` defaults to 5 and accepts integers from 1 to 20. `max_chars` defaults to 16000 and accepts integers from 2048 to 64000. Booleans, floats, strings and null are not accepted as integers. The budget measures `len(json.dumps(data, ensure_ascii=True, sort_keys=True))`, including the date/filter/count/bucket metadata and complete summaries, but excluding the outer CLI/slash/tool envelope. This is an ASCII serialized-character budget, not a token estimate or total provider-context limit.

Summaries are considered in overdue, today, upcoming, undated order. If the next whole summary does not fit, that bucket stops; later buckets may still fit smaller summaries. Titles, IDs and revisions are never truncated. `omitted = total - len(items)` accounts for both per-bucket limits and the shared budget. A positive total with no items means summaries were omitted, not that no task exists. Review has no pagination cursor; use existing `list`, `agenda`, `search` and `show` readers to inspect more tasks. `later` intentionally has only a count.

All counts and summaries share one deferred SQLite read transaction. A concurrent change cannot make a single result mix before/after states. A later review is a fresh snapshot and may differ. No durable snapshot, completion proof or frozen cross-call cursor is promised. Read failures release the transaction and preserve task records, events and receipts. The task-progress follow-on upgrades owned v1/v2/v3 stores to schema v4; review itself adds no migration.

## 4. Privacy, Admission and Verification

Existing profile, source, session, active-turn, TTL, revocation and unload gates remain in force. Default read-only mode opens no task storage. Model results enter the configured model context and normal host retention; the summary budget does not make that transmission offline. This plugin does not secure other Hermes tools. Do not enable the local lane on an exposed/shared gateway or disable isolation to expose it.

Review adds no background job, native blueprint task access, automatic prompt injection, notification, model/provider call or external action. An explicit native command performs only deterministic local reads after the existing storage opener verifies or upgrades the store. It does not complete real-provider natural-language acceptance or the broader M1 release gates.

Synthetic tests cover date/leap-year boundaries, exact counts and filters, complete-summary/Unicode budgets, stable ordering, omitted counts, terminal exclusion, concurrent changes, rollback after read failures, legacy migration and restart. Pinned-host contracts cover CLI reload, native command/model result parity, current read activation, malformed arguments, wrong session/origin, absent turn and disable denial. All tests use temporary profiles and a network guard, without credentials or personal accounts.
