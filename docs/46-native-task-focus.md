# 46. Native Session Task Focus

English | [简体中文](46-native-task-focus-zh.md)

## 1. What is usable

An explicit focus connects one stored task to the next native conversation turns. After selecting a task, the main agent receives its latest revision, title, project label, due date, recorded progress and bounded details at each turn start. You can say “help me with the next step” without copying the task record again. Focus itself never starts a worker, changes task state, grants external permissions or sends an extra model request.

This extends the existing [session task tools](29-session-scoped-task-tools.md), not the memory provider. It uses the same trusted single-user, native in-process CLI/TUI/Desktop support and exact session/route activation. A task label is not a native Project or permission scope. Default read-only loading registers no focus hook.

## 2. Use an existing task

Enable `mode: local_tasks`, `local_conversation: true` and `local_model_tools: true` in an eligible isolated test profile, as described in [29](29-session-scoped-task-tools.md). Preserve the existing provider, isolation and other settings. In that native session:

```text
/personal-tasks list
/personal-tools enable-read
/personal-tools focus <exact-task-id-from-list>
Help me decide the next step for this task.
/personal-tools status
/personal-tools clear-focus
```

The placeholder must be replaced with an actual returned task UUID. Selection requires active read or write access and an existing task; an invalid or missing ID leaves the previous selection unchanged. Status reports the selected ID without reading task text. Clearing focus leaves task tools available. Use `/personal-tools disable` to revoke both future task-tool admission and future focus snapshots.

For explicitly requested local edits, first use `/personal-tools enable-write`. Focus never enables writes itself. Existing model tools still require exact task IDs, current revisions and stable retry keys. Selecting a different task replaces the old focus only in that session. No related tasks, full profile, conversation transcript or memory records are included.

## 3. Freshness and budgets

The hook performs a fresh store read at the start of each admitted turn, including after a task is edited, blocked, completed or cancelled. It does not refresh between individual model/tool calls within the same turn: use `personal_tasks_read` before edits and reconcile revision conflicts. Completed/cancelled records retain historical progress fields; their presence is not evidence of current worker activity. Task and memory content cannot select the focus or grant permission.

The complete serialized context, including its source/warning prefix, is at most 12,000 ASCII characters. Identity, revision and state are kept; progress notes are preferred to long background details. Large optional fields are omitted whole and listed in `omitted_fields`, not silently cut. The model can retrieve needed fields through the existing `show` action. This is a character budget, not a token or billing guarantee; the configured model's usual context costs apply.

On a storage failure after admission, the next context says refresh failed without exposing stale text, exception details or paths. Unsupported or inactive sessions receive no focus context. The normal conversation can continue; task focus is not an enforcement layer for other Hermes tools.

## 4. Lifecycle and privacy

Focus is process-local and lasts no longer than the existing 30-minute task activation. Refreshing an unexpired activation preserves focus; activating again after expiry does not revive it. Clear, disable, unload, reload, process restart or observed configuration/profile invalidation removes it. Focus clearing and activation changes share the same lock as admitted reads: a snapshot admitted first may still reach the current turn, but future admissions stop.

The hook supplies API-bound user context through Hermes's native `pre_llm_call` path, not by modifying the system prompt or rewriting previous turns. The host may preserve previously sent context in history/sidecars for prompt-cache replay. Clearing focus, expiry and task correction do not erase earlier model context, history or backups. All admitted controllers and model activity in the selected session share its data, as with task tools; this is not independent owner authentication.

Delegated children, cron, messaging, foreign profile/session/route, absent live turn, managed workers and hosted-plugin execution do not gain focus access. Do not turn off isolation to use it. The plugin neither selects a provider/model nor uses the native memory provider slot.

## 5. Evidence and remaining acceptance

Unit tests cover fresh revisions, whole-field budgets, Unicode escaping, invalid selections, exact-session scope, expiry/re-enable, clear/disable, configuration changes, storage failures and admission/clear ordering. Pinned-host contracts exercise real plugin registration, slash-command authorization, native turn/route context, the host hook collector and API-content composer, plus worker/cron exclusion and unload/reload. Tests use synthetic data and temporary profiles with network connections blocked; they do not start a Gateway socket or call a model.

This is a native context integration, not real-provider language-quality acceptance or full GUI/transport validation. Real-model acceptance remains pending under E6.9. Native worker dispatch/reconciliation, remote owner authentication and complete MVP/release gates remain open.

Pinned Hermes source: [turn context](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_context.py), [plugin hooks](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py), and the [existing admission evidence](29-session-scoped-task-tools.md#6-pinned-host-evidence).
