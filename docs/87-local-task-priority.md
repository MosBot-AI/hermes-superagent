# 87. Explicit Local Task Priorities

English | [简体中文](87-local-task-priority-zh.md)

## Purpose and scope

Task priority is explicit planning data: `high`, `normal` or `low`. It helps choose among work that is already eligible. It is not permission, inferred urgency, a budget, worker dispatch or a reminder. Due dates do not silently change priority. Ordinary task state, dependency, revision and session-admission gates still apply.

The vocabulary matches the DSH domain priority enum inspected at `b0f3a52c4ab2cf5258e65ea4b7974cd044782505`. This is a local native/task-tool capability, not a new shared REST field. The authoritative shared Task projection and its pinned contracts remain unchanged; no HTTP availability or cross-backend feature parity is claimed.

## Explicit editing

```text
/personal-tasks add "Organize project materials" --priority high --request-id priority-capture
/personal-tasks update TASK_ID --priority low --expected-revision 1 --request-id priority-edit
/personal-tasks show TASK_ID
```

The local CLI and already enabled/session-activated task tools expose the same values. Plan and breakdown JSON items may specify priority independently. Omission means `normal` for newly stored tasks; it is not silently inserted into historical request hashes. Invalid enum values, nulls, booleans and unknown fields refuse. A priority-only change still requires the current revision and creates the ordinary durable event/receipt. Terminal tasks retain their existing mutation rules.

Priority must reflect an explicit user choice, not a model's inferred permission or standing preference. It is visible in current task views and focused-task context. Existing narrowly approved planning-worker disclosures do not silently gain extra fields.

## Choosing next work

```text
/personal-tasks next --limit 5
/personal-tasks next --project "Project name" --limit 5
/personal-tasks next --unassigned --limit 5
```

`next` considers only active `captured` tasks with manually recorded `work_status=ready` and every prerequisite `done`. A cancelled, missing or unsatisfied prerequisite does not become acceptable merely because its dependent has high priority. Results sort by `high`, `normal`, `low`; within each priority, earlier explicit due dates come first, undated tasks last, then capture order.

The default limit is 5, maximum 20. Results include `total`, `omitted`, `limit`, the exact `ordering`, eligibility `scope` and `authority=planning_data_not_permission_or_dispatch`. This is a fresh bounded top-N view, not a paginated snapshot; it accepts no `after` cursor. Counts can inspect the eligible metadata set, so the output limit is not a large-store CPU/latency guarantee. The existing `ready` view retains its oldest-first ordering and cursor semantics. Neither query changes focus, task state or dispatches work.

## Migration and historical evidence

Schema 7 adds priority while retaining task IDs, revisions, capture sequences, dependencies, native references, events and receipts. Previously stored tasks become `normal`. Only exact recognized prior schemas are migrated, transactionally; a malformed schema is not adopted.

Existing receipt text and request hashes remain unchanged. Replaying a historical request may therefore return a receipt without priority; that is historical evidence, not a fresh current read and not proof that a later priority edit disappeared. Use `show` for current state. The explicit default and omitted-field compatibility are tested separately.

Historical schema-6 snapshots remain read-only and their bytes are not migrated. A priority absent from their stored task shape is presented as `normal`; this does not rewrite the historical artifact or confer authority. Snapshot inspection/copy and private-storage safety gates remain in force. The existing selected-text `recover-copy` operation still creates a new task with normal priority; it does not inherit historical priority or restore execution authority.

## Verification and boundaries

Tests cover schema migration/rollback, omitted-field replay, exact historical receipts, strict values, priority-only CAS, dependencies, filters/ties, presentation, native commands and existing model-tool admission without model calls. The manual official-package Gateway acceptance must separately verify real create/update/selection and restart behavior on the exact candidate. Offline tests alone do not establish that live result.

This bounded feature advances E3.4 under [#5](https://github.com/MosBot-AI/hermes-superagent/issues/5), with delivery tracked in [#109](https://github.com/MosBot-AI/hermes-superagent/issues/109). It does not complete broader E3, natural-language acceptance, remote-owner authority, reminders or the full Super Agent.
