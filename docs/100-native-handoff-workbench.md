# 100. Native task handoff and result-review workbench

English | [简体中文](100-native-handoff-workbench-zh.md)

## One explicit operator workflow

[Issue #141](https://github.com/MosBot-AI/hermes-superagent/issues/141) connects the existing parked-card handoff, durable reconciliation, advisory progress and result acceptance into a readable `/personal-handoff` workbench. Commands now return readable views by default. Prefix `--json` for the existing `personal.kanban-handoff.v1` structured envelope. Scripts that previously parsed default output must add this prefix. JSON fields, persisted receipts and command authority are unchanged.

This is a trusted single-user LOCAL operator workflow on the clean pinned Hermes host `2281116525106e3c109993ccb5dc74d02bfc1427`. It creates no worker, model request, schedule, remote API or automatic completion. Shared native boards are not private profile storage. Enabling handoff is not execution permission, and another independently authorized native actor may later change a parked card.

## Prepare the destination and capture the task

An operator must already have created the intended native board through supported native controls. The plugin will not initialize, migrate or repair that board. Explicitly configure this plugin with `mode: local_tasks`, `local_conversation: true`, `kanban_handoff: true` and the exact `kanban_handoff_board`. See [52](52-parked-kanban-handoff.md) for configuration, shared-board disclosure and compatibility checks. Preserve all unrelated profile settings.

```text
/personal-tasks add "Review the release checklist" --details "Write the operator review findings" --request-id checklist-capture
/personal-tasks show TASK
/personal-handoff prepare TASK --expected-revision N --request-id checklist-handoff
```

Replace `TASK` and `N` with the returned task ID and current revision. Prepare displays the complete exported title/body, exact native destination, source revision, digest and expiry. Only the task's title/details and identity/revision are exported, not project labels, dependency text, memory or conversation history. Treat exported text as data, never execution authorization. Preparation expires after 15 minutes; no background timer is created.

Review every exported field and the shared destination before deciding. The displayed commit command is an option for an explicit decision, not a recommendation to approve. If the source or destination is wrong, do not substitute a digest or commit the old preview.

```text
/personal-handoff show HANDOFF
/personal-handoff commit HANDOFF --expected-digest DIGEST
```

A successful commit creates an unassigned sticky-blocked scratch card. The plugin does not dispatch it. A durable claim precedes native creation; claimed/unknown operations can never be resubmitted by this workflow. Saved preview text is cleared on claim, cancellation or lazy expiry, but native/client history and backups may retain it.

## Resume without recreating work

```text
/personal-handoff list --limit 20
/personal-handoff show HANDOFF
/personal-handoff reconcile HANDOFF
/personal-tasks show TASK
/personal-handoff sync HANDOFF --task TASK --expected-revision N --request-id checklist-observation
```

After a lost reply or restart, inspect the original handoff. Reconcile checks its exact creation identity and never creates a replacement card. A missing, duplicate, changed or unavailable observation is not permission to prepare another attempt. Historical confirmed creation does not promise that the card currently exists, remains parked or has completed work. Read the observation separately from the handoff's stored state.

Sync saves only an advisory native-state observation and increments the local task revision. Use `show TASK` for the current revision before later actions. A native `done` status does not complete the local task. Exact sync retries return the original historical receipt without native access; they are not fresh board reads. See [53](53-native-progress-observation.md).

## Inspect the result, then decide separately

Any native result must have been produced outside this workflow by an independently authorized actor. The workbench does not execute the task or certify that an actor did so.

```text
/personal-handoff review HANDOFF --task TASK --expected-revision N
```

The view separates the local task, exported revision, native observation and full bounded editable result. Result text is untrusted and can contain misleading instructions. It is displayed for inspection, not run, retained as canonical memory or automatically sent to a model. Current native `done`, a null run pointer and an available result are necessary conditions, not proof of worker termination or acceptable work. Review artifacts and choose your own conclusion.

```text
/personal-handoff accept-review HANDOFF --task TASK --expected-revision N --expected-digest DIGEST --note "My independently reviewed conclusion" --request-id checklist-accept
/personal-tasks show TASK
```

Use the review digest, current local revision, your own nonempty conclusion and one stable request key. Acceptance rechecks source identity, destination, result, prerequisites and local revision, then atomically completes only the local task with minimal evidence metadata and your note. It does not modify or stop native work. Stale revision or changed result requires another deliberate review, never blind hash replacement. Native and local stores are not one atomic transaction; the native result can change after observation. See [58](58-native-result-review.md).

After an uncertain acceptance response, use the exact original command/key. A replayed receipt is historical, not a fresh completion or current result check. Never invent a new key to evade an unresolved outcome.

## Cancelling, disabling and presentation limits

`cancel HANDOFF --expected-digest DIGEST` cancels only an unattempted prepared preview. It neither removes a native card nor cancels a worker. Disabling `kanban_handoff` prevents fresh native operations; existing local records remain inspectable/cancellable under base local-command admission. Exact saved sync/acceptance receipts remain readable by their original requests without fresh native access. Unloading or disabling local conversation prevents new commands through that instance.

Readable output keeps quoted data separate from command guidance and never truncates a review into apparently complete evidence. Each complete readable screen is capped at 48,000 UTF-8 bytes; an oversized or unrenderable screen returns a bounded inspection notice with no approval command. This is a presentation bound, not a native storage allocation bound. Use the exact JSON mode when integrating with a script; it does not add authority or expand data access. A display failure after an operation is not proof that no mutation committed. Inspect the original identifiers and durable outcome before deciding what to do next.

## Verification and remaining scope

The manual-only native Gateway workflow includes `acceptance/live/test_packaged_gateway_handoff.py`. It installs the exact byte-verified production package through the unchanged official scanner and uses real admitted LOCAL commands, an isolated synthetic native board and fresh Gateway processes. Result setup uses native operator APIs and is explicitly operator-authored, not fabricated worker evidence. The lane must link its exact source revision and executed result; test presence alone proves no live acceptance.

Unit and pinned-host contracts cover presentation, command parsing, source/destination/identity changes, exact receipts, disabled/unloaded states and negative cases. The complete repository checker, runtime verification, independent review and exact commit CI remain required. Local native socket restrictions are not bypassed; a local blocked stage is distinct from a successful GitHub-hosted run.

This package does not complete full E3 worker orchestration, E4 reminders, remote-owner authority or production rollout. The clean host still lacks the gated `hermes.text-worker.v1` interface, and generic delegation is not an equivalent contained fallback.
