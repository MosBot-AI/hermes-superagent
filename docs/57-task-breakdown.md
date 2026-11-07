# Explicit task breakdown into a local subplan

English | [简体中文](57-task-breakdown-zh.md)

## Turn an existing task into actionable steps

`breakdown` captures explicitly supplied steps and links them to an existing task in one transaction. It is a user-directed local task operation, not automatic model conversion or worker dispatch. The source task must be captured, have a non-null project label and not be in progress. Use its current UUID and revision:

```text
/personal-tasks breakdown TASK_UUID --expected-revision N --tasks-json '[{"title":"Prepare draft","details":"Use the agreed outline"},{"title":"Review draft","depends_on":[1]}]' --request-id breakdown-1
```

Replace `TASK_UUID` and `N` with values returned by task show. The CLI uses `hermes personal-agent tasks breakdown` with the same arguments. `--tasks-json` is an ordered inline JSON array, not a filename; quote it for the shell/client. There is no project parameter: every new step inherits the parent's exact project label, not a native Project ID. After existing explicit write activation, the existing task model-write tool supports the same `breakdown` action; this is not permission for a model to invent a decomposition without user direction.

Each step uses the [atomic plan](56-atomic-plan-dependencies.md) fields `title`, optional `details`, optional `due_date`, and optional `depends_on`. Dependency numbers are one-based positions in this new batch; forward references are allowed, but cycles, self-references, duplicates, out-of-range values and non-integers are refused. No order is inferred. Step text and dates are explicit: parent private text is not copied into them.

## Dependency semantics, not a hidden hierarchy

The parent's existing prerequisites are preserved and inherited by **every** new step. The parent additionally depends on **all** new steps, not merely the last listed one. The number of existing parent prerequisites plus new tasks must be at most 20; otherwise the whole operation fails. Existing dependency and same-project restrictions remain in force.

New steps are captured at revision 1 with recorded work status ready. The parent's revision increments once, without changing its work status. All new tasks, edges, metadata events, the parent update and the shared receipt commit together or not at all.

Inheritance is a snapshot at the breakdown transaction: later edits to the parent's prerequisites do not propagate to the steps, and later edits to steps do not rewrite the parent's set.

These are ordinary editable dependency edges, not a durable exclusive parent-child hierarchy. A step can participate in other explicitly recorded relationships. Cancelling the parent does not cancel its steps. Completing steps can satisfy prerequisites but never automatically completes the parent. A cancelled prerequisite does not count as done.

## Manual follow-through

1. Inspect the returned parent and step IDs and their dependencies.
2. Use `/personal-tasks ready --project "Exact label"` to inspect eligible local tasks. A newly captured ready status alone does not bypass inherited prerequisites.
3. Carry out work separately and explicitly record progress/completion using current revisions and request IDs. The existing start/complete gates require prerequisites to be done.
4. After all parent prerequisites and new steps are done, inspect and explicitly complete the parent if the real work is finished. Nothing advances or completes automatically.

An identical retry returns the original durable receipt even after later task edits. It is history, not the current state. After an uncertain result, reuse the same key and identical arguments; do not invent a new key or split the request into individual captures, which could create duplicates.

## Scope and remaining gates

The existing task configuration, local command admission and activated model-write checks remain unchanged. This adds no provider request, native Kanban write, schedule, worker execution, installation retry or Gateway action. It does not claim live-model or installed-host acceptance. It makes task-to-subplan record keeping practical, but does not complete E3.2/E3.3 or the [remaining orchestration roadmap](08-roadmap-and-acceptance.md).
