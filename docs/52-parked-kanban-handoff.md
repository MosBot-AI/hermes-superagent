# Parked native Kanban handoff

English | [简体中文](52-parked-kanban-handoff-zh.md)

## Scope and opt-in

This is an explicit local-task-to-native-card handoff, not a worker launch, universal task mapping or completion signal. Default `kanban_handoff: false` leaves creation disabled. Enabling requires `mode: local_tasks`, `local_conversation: true` and an explicit `kanban_handoff_board` matching `[a-z0-9][a-z0-9_-]{0,63}`. Even the `default` board must be named explicitly. Native boards are shared across host profiles, not private plugin storage.

`/personal-handoff` is registered whenever local conversation is enabled, including when handoff creation is disabled, so retained records can still be inspected or cancelled. Registration and status do not import native Kanban, probe its version or open its database. Status reports configuration, not verified host support. The native source/session controller checks are not proof of a physical human or remote owner identity.

## Explicit workflow

- `prepare TASK --expected-revision N --request-id KEY` previews one exact task snapshot. Only title/details and task ID/revision are included; the exact approved native root, board and database path are shown.
- `commit ID --expected-digest SHA` approves that preview, not a newer task. The preview expires after 15 minutes; source revision is rechecked and a durable single-use claim is committed before the native write.
- `list [--limit N --after ID]` returns metadata only, never preview title/body. Use `show ID` or the original `prepare` response to inspect the exact payload and destination before approving its digest.
- `cancel ID --expected-digest SHA` cancels an unclaimed preview; it does not undo a native card or prove remote cancellation.
- `reconcile ID` performs a bounded read-only lookup of the exact handoff key, including archived cards. Missing, duplicate and conflicting observations remain explicit. It never creates another card.

Creation parks a sticky blocked card without an assignee, using scratch workspace semantics, with no project, parent tasks or provider selection. Nothing dispatches or executes it. Claimed/unknown outcomes are never automatically retried or reset. A different key is not recovery of an uncertain operation. A new explicit prepare request may replace only a definitely unattempted cancelled or expired preview. The old request key remains terminal and cannot be reused; claimed, unknown or confirmed records continue to block duplicate handoffs for that source revision and destination. Payload is purged at claim, cancellation or lazy expiry; up to 1,000 metadata records remain. There is no background expiry service. Clearing is logical payload removal, not erasure of journals, backups or native history. Another authorized native actor can later unblock the card; this handoff grants no execution authority.

## Native boundary and evidence limits

The adapter targets host commit `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`, an existing private native database with the exact expected schema, and the host's tracked connection plus `write_txn`/`create_task` path. It does not invoke a CLI, initialize a board, migrate or repair storage. Native/version/schema checks occur only during operations and fail closed. Existing rollback journals are refused before opening the board; only this adapter’s own verified active DELETE-mode write transaction may have its newly created journal. Native WAL safety fallback remains unchanged; tests cover native-default and explicit DELETE modes. Read-only observer SQL may still cause SQLite WAL bookkeeping; it is not a promise of zero filesystem effects. Pin checks follow native imports: they check compatibility of a trusted installed host, not pre-execution integrity against malicious host code or same-process plugins. Local project labels, dependencies, memory and conversation text are not exported or synchronized.

This slice uses offline fixtures only. No live Kanban, installation, Gateway or model acceptance is claimed. Existing scanner and installation restrictions remain unchanged. See the [roadmap](08-roadmap-and-acceptance.md), [local task dependencies](51-project-task-dependencies.md) and [worker proposal](48-task-worker-proposal.md) for distinct unfinished gates.

[Advisory progress sync](53-native-progress-observation.md) adds explicit metadata observation for newly identity-bound handoffs, not dispatch or automatic local completion.
