# Explicit dependencies in atomic plans

English | [简体中文](56-atomic-plan-dependencies-zh.md)

## One batch, explicit prerequisites

`capture_plan` now accepts an optional `depends_on` list for each task. Each number is a **one-based position in the same submitted batch**, not a task UUID or a priority. Forward references are allowed. Order alone creates no dependency; omitted `depends_on` and `[]` normalize to the previous no-edge behavior.

```text
/personal-tasks plan --project "Launch" --tasks-json '[{"title":"Draft"},{"title":"Review","depends_on":[1]},{"title":"Publish","depends_on":[2]}]' --request-id launch-with-links-1
```

The existing CLI accepts the same `plan --tasks-json` arguments. After existing explicit write activation, `personal_tasks_write` accepts the same per-item field in `capture_plan`. No separate planning model or new activation mechanism is added. Use shell/platform-appropriate quoting; `--tasks-json` is an inline array, not a file path.

For a batch of N tasks, positions must be integers from 1 through N. Booleans, duplicates, self-references, references outside the batch and cycles are rejected. All tasks share the explicitly selected project label. References to existing tasks still use the separate explicit [dependency-edit workflow](51-project-task-dependencies.md); no relationship is inferred from task text.

## Atomic storage and existing gates

All new tasks, their dependency edges, initial metadata events and the shared receipt commit together or not at all. Current task schema remains v6; this slice adds no schema migration. Historical no-edge plan receipts remain historical results. Reuse the same request ID and identical normalized plan after an uncertain response rather than inventing another batch.

The existing `ready` query and start/complete checks immediately account for the saved prerequisites. Only a prerequisite marked done satisfies an edge; cancellation is not success. Saving the plan does not mark work blocked, start a worker, complete anything, create native Kanban cards or schedule a reminder. A returned plan is a local record, not an execution plan approval.

## Acceptance scope

This uses the existing clean pinned host command, CLI and activated model-write surfaces. No host patch, installation retry, provider request, real-model acceptance or Gateway action is introduced. Offline fixtures exercise the implementation; no numerical or live acceptance claim is made here. [Atomic plan capture](47-atomic-project-plans.md) and [project dependencies](51-project-task-dependencies.md) describe the earlier slices; [the roadmap](08-roadmap-and-acceptance.md) retains the remaining orchestration gates.
