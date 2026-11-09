# Project-wide task date shifting

English | [简体中文](71-project-task-reschedule-zh.md)

## Preview the whole change

A project moving by a week should not require separate task edits that can partly succeed. This explicit local operator workflow previews and atomically shifts the calendar dates of the active, dated tasks in one exact project label.

```text
/personal-tasks project-reschedule-preview --project "Launch" --days 7
/personal-tasks reschedule-project --project "Launch" --days 7 --expected-snapshot HASH --request-id launch-delay-1
```

Use the actual snapshot from preview. Negative days bring dates forward. The equivalent CLI prefix is `hermes personal-agent tasks`; native output is readable by default with leading `--json` available, while CLI supports `--format text`. Apply requires an explicit stable request ID. Neither command asks a model, contacts a board, changes a native card, schedules a reminder or sends a notification.

The exact project label retains existing case-sensitive validation: 1–80 characters, no leading/trailing whitespace or control characters. Unassigned tasks are not a project label. `--days` is a nonzero integer between -3650 and 3650 inclusive. It shifts Gregorian **calendar dates**, not elapsed hours, timezones, working days, holidays or reminder times. No current date is inferred.

Preview includes every affected task's ID, title, revision and old/new due date, plus the counts excluded because they are done/cancelled or active without a date. There is no automatic date assignment. Active means `captured`, including recorded ready/in-progress/waiting/blocked work statuses; shifting a date does not unblock or start work. An existing group with no eligible tasks may be previewed, but applying it is refused.

A project may contain at most 100 tasks including exclusions. The complete ASCII-escaped JSON preview data, excluding the transport envelope, must fit 16,000 characters (not tokens); oversized groups or output are refused, not truncated into a partial approval. Task details, progress notes, result text and native output are not included. View individual tasks separately when their dates require more context. If a group's preview exceeds the limits, use explicit individual updates instead of assuming this operation covers only the visible portion.

## Snapshot, transaction and retry

The snapshot binds the exact project, day offset and the complete ordered member set with IDs, revisions, states and due dates, including excluded tasks. A new member, a task moved out, a revision change or a terminal-state change makes an older preview stale. The snapshot is a concurrency check, not an authorization token or a lock held across commands. Existing profile and local-operator admission still applies; model-tool schemas do not gain this bulk write.

Apply rechecks the whole group in one `BEGIN IMMEDIATE` transaction. Every eligible task receives its shifted date, one revision increment, a timestamp and a `reschedule_project` metadata event. Any invalid date, overflow, stale snapshot or failed write rolls back the whole batch. Dates outside the supported Gregorian range are rejected. Existing task state, dependency edges, work status, notes, resolution evidence and saved native observations remain unchanged. The operation does not infer date ordering from dependencies or change dependency readiness.

New revisions invalidate existing revision-bound edits, grants and snapshots. Native cards and earlier handoff evidence are not synchronized or refreshed. Already delivered model context is not rewritten.

Retry an uncertain result with the **same request ID and identical arguments**, including the original snapshot. Exact retries return the historical receipt even after later edits or a process restart; they never shift dates again or touch newly added members. A reused key with changed arguments conflicts. A fresh key is a new change, not a retry. Read current task state after a historical receipt. There is no automatic retry, automatic rescheduling, cancellation of outside work or general terminal-task editing permission.

No schema migration is introduced. As with existing task commands, opening a supported older store can perform its normal initialization/migration even for a logical preview. Output bounds are not large-store latency guarantees. Plaintext local storage and native history retain their existing privacy limits.

## Verification boundary

Validation covers full previews and exclusions, exact labels and limits, positive/negative shifts, leap days and year boundaries, overflow, stale group membership/revisions, concurrency, mid-transaction failure, process crashes and historical replay. Pinned-host native command/CLI contracts verify parsing, admission and readable/JSON behavior without model calls or a live Gateway.

Final run counts and exact commits belong in the linked PR evidence. This is the local task-date slice within #40, not completion of all E6/M1 acceptance, production deployment, real-user acceptance or proof of reminder delivery.
