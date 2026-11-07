# 51. Project Task Dependencies and Ready Work

English | [简体中文](51-project-task-dependencies-zh.md)

The local task workflow can now enforce explicit sequencing inside a named project:
record prerequisites, see what is currently clear to work on, and refuse to start
or complete a dependent task prematurely. This runs through the existing supported
native commands, CLI and activated task tools. It does not dispatch workers, create
native Kanban cards, schedule reminders or infer authorization from task text.

## 1. A Practical Project Flow

Use the existing opt-in `local_tasks` setup and native conversation configuration.
Capture a plan as before, then use its returned task IDs:

```text
/personal-tasks plan --project "Launch" --task "Draft" --task "Review" --request-id launch-1
/personal-tasks dependencies REVIEW_ID --needs DRAFT_ID --expected-revision 1 --request-id review-needs-draft
/personal-tasks show REVIEW_ID
/personal-tasks ready --project "Launch"
```

The IDs above are placeholders for actual canonical UUIDs. `dependencies` replaces
the **entire** prerequisite set, not just one edge. Repeat `--needs` for multiple
prerequisites, or explicitly pass `--clear` to remove the set. Both the current
revision and a stable request ID are required; this command never invents a retry
key. Each task accepts at most 20 unique prerequisite IDs. Duplicate, missing,
self-referential or cyclic links are refused.

Every linked task must have the same exact, non-null project label. Assign
unassigned tasks first. Labels remain case-sensitive local groups, not native
Project IDs, ownership, identities or security boundaries. No title-based or
cross-project matching is inferred.

Complete the draft explicitly, then inspect the newly available review task:

```text
/personal-tasks done DRAFT_ID --expected-revision 1 --note "Draft checked" --request-id draft-done
/personal-tasks ready --project "Launch"
/personal-tools enable-read
/personal-tools focus REVIEW_ID
```

Use actual current revisions. Linking increments the dependent task's revision.
Focus selects context only and does not start work. To mark progress or completion,
use the existing commands after examining the current task; the dependency gate
runs again inside the write transaction. CLI equivalents begin with
`hermes personal-agent tasks`. Native views are readable text, with leading
`--json` for structured results; CLI defaults to JSON, with `--format text` available.

## 2. Enforcement and Explicit Progress

Only a prerequisite recorded as `done` satisfies a dependency. An active or cancelled
prerequisite blocks the dependent task. Cancellation is not success. Removing an
obsolete requirement must be an explicit dependency change, not an automatic
response to cancellation.

When any prerequisite is unsatisfied, `progress --work-status in_progress` and
`done` are refused. Adding an unsatisfied prerequisite to an already in-progress
task is also refused: explicitly change its progress first if the new requirement
really applies. A dependent task can always be cancelled. Setting dependencies,
start/complete checks, revision updates, metadata events and retry receipts share
one `BEGIN IMMEDIATE` transaction, so concurrent edits cannot pass stale checks.

Manual `work_status` remains independent. The plugin never silently changes ready,
working, waiting or blocked notes after a prerequisite changes. `ready` returns
only active tasks whose recorded work status is `ready` and whose prerequisites
are all done. It orders by oldest capture sequence, not inferred importance,
deadlines or model priority. It is an advisory work list, not permission to act,
a worker launch, proof of availability or evidence of real-world completion.

Project changes are refused while a task has any incoming or outgoing dependency
edge, including terminal edges. No connected task is silently moved and no edge is
automatically deleted. Dependency editing remains limited to active tasks; a
cancelled dependent's retained edge can therefore continue to prevent its active
prerequisite from moving projects. This deliberately conservative restriction is
not a bulk project-renaming or terminal-history editing workflow.

## 3. Read Snapshots, Focus and Retry Semantics

Fresh task records include `dependencies` (bounded prerequisite IDs, revisions and
states), `dependencies_satisfied` and `unsatisfied_dependency_count`. They do not
copy prerequisite titles, details or instructions. Missing or inconsistent stored
references fail closed rather than becoming falsely satisfied. Daily review adds
satisfied/blocked dependency counts over its filtered active tasks. Bounded views
continue to report omitted records, not pretend the sample is exhaustive.

Show, list, search, agenda, ready, review and focused task context use a shared
SQLite read snapshot for related data. Separate calls/pages remain live. Ready
pages accept `--limit` and `--after`, plus an exact `--project` or `--unassigned`;
keep the same filters while paging. `total_eligible` covers the matching current
queue, not merely the displayed page. Concurrent changes can change later pages.
Ready/review can scan all matching task metadata internally; output bounds are not
a CPU-time or large-store latency guarantee.

A task's revision covers its own fields and dependency edges, **not a globally
frozen dependency snapshot**. Completing a prerequisite changes a dependent's
derived readiness without changing the dependent's revision. Focus refreshes these
fields each turn and labels their scope. Already supplied model/history context
is historical and is not rewritten or erased.

Exact retries retain the existing receipt-first behavior: the original success
receipt is returned without reapplying the mutation, even after later state
changes or process restart. Read again for current state. Changed arguments with
an old key conflict. Input prerequisite IDs are sorted before hashing, so changing
only their order is the same request; duplicates are still invalid. An uncertain
write must be retried with the same key and arguments, not a new key.

Schema v5 adds the dependency relation with an atomic upgrade from exact owned
v1–v4 schemas. Existing task fields, revisions, metadata events, receipts and their
serialized bytes are preserved. Historical receipts can lack dependency fields;
the UI reports them as unknown rather than clear. History remains operation,
revision and timestamp metadata, not a reconstruction of old edge sets. As with
existing task commands, opening a store can initialize or migrate it even for a
logical read. Older plugin versions cannot read the upgraded schema.

## 4. Model Tools and Native Integration Boundary

After existing explicit read activation, `personal_tasks_read` can use `ready`.
After write activation, `personal_tasks_write` can use `set_dependencies` with
`task_id`, `expected_revision`, `dependency_ids` and `request_id`. The model must
record explicitly requested relations using returned IDs, not infer execution
permission from descriptions. Existing live-turn/profile/route, revocation,
child/cron and unsupported-mode checks remain unchanged. No extra model is called.
Plan capture itself still has no indexed/nested dependency syntax.

This is a profile-first E2/E6 precursor for the dependency/readiness part of E3.2
through supported native entry points, not task-to-Kanban mapping or E3.3 worker
orchestration. The pinned host's
public `kanban_list` calls `recompute_ready`, and normal Kanban/Project reads can
initialize or migrate stores. They are not silently used as read-only inspection.
The model-facing `kanban_create` defaults to running and requires an assignee;
it can also subscribe to notifications and inherit project workspace context.

The official CLI can explicitly create a blocked, unassigned scratch card, but
safe cross-store handoff needs durable uncertain-outcome and archival/retry
reconciliation. It remains a separate next step, not a capability claimed by this
release. See the [native source](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/kanban_tools.py).

## 5. Verification

Offline synthetic tests cover graph cycles and concurrent opposite edges,
start/link races, project changes on either endpoint, cancellation, rollback,
receipt replay, migrations and coherent read snapshots. Real pinned-host
contracts cover plan capture, dependencies, refused premature progress/completion,
prerequisite completion, ready selection, focus and process restart, plus existing
admission refusals. No installer, live provider, Gateway listener, native dispatch
or production user data is used. Prior installation/network restrictions remain.
