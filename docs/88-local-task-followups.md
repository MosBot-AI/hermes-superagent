# 88. Explicit Waiting-Task Follow-ups

English | [简体中文](88-local-task-followups-zh.md)

## Scope

A waiting or blocked task can carry an explicit `follow_up_on` calendar date independently from its deadline (`due_date`). The user opens the follow-up view to decide what to revisit. This is planning data, **not an automatic reminder**, background wake-up, delivery promise, permission or dispatch. It does not contact anyone or change a waiting task to ready.

This capability belongs to the trusted-profile native CLI and already activated session task tools. Shared REST Task artifacts and client projections remain unchanged; this does not establish shared API parity or authenticated HTTP availability. Reminder scheduling and delivery in #19 remain separate.

## Record and revise a date

```text
/personal-tasks progress TASK_ID --work-status waiting --note "Awaiting a reply" --follow-up-on 2030-01-10 --expected-revision 1 --request-id waiting-date
/personal-tasks update TASK_ID --follow-up-on 2030-01-12 --expected-revision 2 --request-id postpone-followup
/personal-tasks update TASK_ID --clear-follow-up-on --expected-revision 3 --request-id clear-followup
```

A non-null date is allowed only on an active task whose resulting work status is `waiting` or `blocked`. Dates use strict `YYYY-MM-DD`; no time zone, clock time, inferred today or automatic urgency is added. The update and progress commands require the current revision. Explicit clearing uses null at the tool boundary. Omitted fields preserve the current date when staying waiting/blocked. Moving to ready/in-progress or completing/cancelling clears the date in the same transaction. Deadlines are not moved.

Capture, plan, breakdown and selected-text recovery do not accept follow-up dates: newly created tasks have no date. This prevents a recovered historical task from silently restoring scheduling metadata. Ordinary dependency and admission rules continue to apply.

## Open the due workbench

```text
/personal-tasks followups --on 2030-01-10
/personal-tasks followups --on 2030-01-10 --project "Project name" --limit 20
/personal-tasks followups --on 2030-01-10 --unassigned
```

The date is required. The view includes only active waiting/blocked tasks with a stored follow-up date on or before it. Results sort by follow-up date, high/normal/low priority, then capture sequence. Future dates, unset dates, ready/in-progress and terminal tasks are excluded. It does not infer that dependencies are satisfied or that action is authorized.

The default limit is 20, maximum 100. The response includes `items`, `total`, `omitted`, `limit`, `on`, exact `ordering` and `scope`, and `authority=planning_data_not_reminder_or_dispatch`. This is a fresh bounded top-N view, not a cursor page. Output bounds are not a large-store CPU or latency guarantee. Reads do not mutate dates, status or activation. Existing agenda, ready and next semantics remain unchanged.

## Migration and historical records

Schema 8 adds the nullable field. Exact recognized schemas 1–7 migrate transactionally with existing task identities, revisions, events, dependencies and native references intact; old tasks have null. Original receipt bytes and omitted-field request digests remain unchanged. A historical receipt may lack this field or show an earlier date: use `show` to read current state, and reuse the exact original request ID for uncertain write retries.

Schema-6/7 snapshots remain immutable and read-only; a missing stored follow-up date is presented as null without changing artifact bytes. Selected-text recovery creates a new task without follow-up scheduling metadata. Existing private-storage, snapshot and recovery safety gates remain in force.

## Verification boundary

Migration/rollback, replay/CAS, strict input/state rules, terminal cleanup, sorting/filtering, current presentation and native admission require tests. The manual official-package real Gateway test separately checks setting a waiting date, explicit due-date queries, rescheduling/stale refusal, restart persistence and completion removal using synthetic records and read-only database inspection. Offline tests alone do not prove live acceptance.

Delivery is tracked in [#111](https://github.com/MosBot-AI/hermes-superagent/issues/111), advancing the local task workflow under #5 and #4. No model call, natural-language acceptance, automatic notification, remote-owner authority, shared REST expansion or full MVP completion is claimed.
