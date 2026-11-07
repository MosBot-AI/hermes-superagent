# 47. Atomic Project Plan Capture

English | [简体中文](47-atomic-project-plans-zh.md)

## 1. User workflow

Save an explicitly requested project plan as 1–20 ordinary local tasks in one operation. Either every task, its initial history event and one shared retry receipt commit together, or none do. This avoids a half-saved plan or duplicated tasks when a multi-task capture is interrupted and retried.

Each item remains independently editable, reviewable, focusable and completable using the existing task tools. The shared project is an exact label, not a native Project. There is no separate mutable plan entity, dependency graph, priority ordering, worker dispatch or reminder. A plan can add to an existing label; it does not replace that label's tasks. Duplicate titles are allowed because equal text does not prove equal intent.

## 2. Native command and CLI

Use the existing trusted local task configuration. The native conversation command requires a stable request ID even on the first attempt:

```text
/personal-tasks plan --project "Demo launch" --task "Prepare draft" --task "Review draft" --request-id launch-plan-1
/personal-tasks list --project "Demo launch"
/personal-tasks review --on 2030-01-01 --project "Demo launch"
```

Native output defaults to readable text with exact IDs/revisions. Prefix with `/personal-tasks --json plan ...` for JSON. The CLI uses `hermes personal-agent tasks plan` with the same flags; its default is JSON and `--format text` selects the readable view. Plan receipts preserve input order; normal task lists retain their existing newest-first order. Neither order creates dependency or priority semantics.

For details or explicit dates, use `--tasks-json` instead of repeated `--task`. Its value is an inline JSON array, not a filename. Quote it for the shell/platform being used; the native command uses POSIX quoting.

```text
/personal-tasks plan --project "Demo launch" --tasks-json '[{"title":"Prepare draft","details":"Use the approved outline"},{"title":"Review draft","due_date":"2030-01-02"}]' --request-id launch-plan-2
```

Do not submit both forms. Unknown/nested identity, approval, project, dependency or retry-key fields are rejected. Duplicate JSON object keys, non-JSON constants, invalid dates, oversized input and a single invalid task reject the entire plan before storage is opened.

## 3. Existing model tool

After the existing `/personal-tools enable-write` activation, ask the main agent to save the tasks you want under the selected project label. The existing `personal_tasks_write` tool now accepts:

```json
{
  "action": "capture_plan",
  "project": "Demo launch",
  "tasks": [
    {"title": "Prepare draft", "details": "Use the approved outline"},
    {"title": "Review draft", "due_date": "2030-01-02"}
  ],
  "request_id": "launch-plan-2"
}
```

The tool uses the same live-turn/profile/session/route checks as single-task writes. Read activation alone is insufficient. It does not call a separate planning model, change providers, grant workers access or expand memory access. Results reach the configured model under the existing task-tool disclosure; live natural-language acceptance remains pending.

Tasks require a title and may include details and a due date. Titles are limited to 240 characters, details to 5,000, and the project label to 80. The normalized whole request, including the project, request ID, default empty details and JSON escaping, must fit 32,000 ASCII-serialized characters. Explicit dates are required; no clock/timezone inference occurs. The receipt returns every task's canonical UUID, initial revision and existing record fields.

## 4. Retry and recovery

Reuse the same request ID, ordered tasks and project after an uncertain result. Replaying the committed plan returns the exact saved receipt without inserting tasks again, even after restart or later edits to individual records. Read each task for its current state: a replay receipt may describe an older revision. Reordering items, changing fields/project, or reusing a single-task write key raises `idempotency_conflict` and changes nothing. Omitted details and an explicitly empty details string normalize identically.

Do not split an uncertain plan into individual `capture` calls or invent a new plan key just to retry. Those are new operations and can create duplicates. A new key is appropriate only for a distinct, intentionally new plan. Invalid input has no partial effect; a storage interruption may have an unknown response outcome, so inspect/retry the original request rather than assuming failure.

Task schema remains v4. Existing stores and historical receipts need no new migration. Each created task receives a revision-1 `capture_plan` metadata event; no old task payload is added to history. The plan receipt contains task text, as ordinary capture receipts do, and is local plaintext rather than a secret store.

## 5. Why worker dispatch stays separate

The pinned public native lifecycle seam is not a per-plugin containment contract. An empty `allowed_toolsets` becomes inherited tools; per-launch timeouts and per-tool blocking are unsupported. Host delegation policy can append inherited MCP toolsets or recursive-delegation capability after a narrowed request. Requested role is compatibility metadata; the builder derives effective role from depth/configuration. These are host semantics, not a new permission grant from this plugin.

Therefore plan capture does not launch a supposedly tool-free worker, change host isolation/delegation settings, or claim E3.3/E3.5 completion. A future contained dispatch flow needs verified effective tools, fixed route/fallback constraints, durable attempt/reconciliation and cancellation semantics. Prompt text such as “only plan” cannot replace those controls.

Pinned source: [public subagent lifecycle](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/subagent_lifecycle.py), [child toolsets](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_toolsets.py), and [child construction](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool.py).

## 6. Verification and limits

Tests cover nested validation, escaped budgets, durable ordered receipts, concurrent identical requests, conflicting keys, whole-transaction rollback at insert/event/receipt failures, process exit during an unfinished batch, restart replay and unchanged schema. Native tests connect command/model/CLI writes to project review, individual progress and task focus, including read-only refusal, foreign/worker scope denial and plugin reload.

Two pinned-host boundary tests demonstrate empty-allowlist inheritance and configuration-dependent MCP/orchestrator additions without constructing a real worker or resolving credentials. All tests use synthetic data and temporary profiles. No Gateway socket, provider request, real account, main-branch update or production deployment is part of this slice. The existing release gate remains blocked.

Follow-on: [project dependencies](51-project-task-dependencies.md) add explicit same-project prerequisite sets and a ready queue. Current task storage is schema v5; atomic v1–v4 migration preserves historical receipts. Plan capture itself still does not infer or accept indexed dependencies, and no native Kanban or worker integration is enabled.
