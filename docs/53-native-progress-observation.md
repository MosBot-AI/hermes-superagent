# Advisory native progress observations

English | [简体中文](53-native-progress-observation-zh.md)

## Explicit sync, not execution

`/personal-handoff sync HANDOFF --task TASK --expected-revision N --request-id KEY` is an operator-only command under the existing default-off `kanban_handoff` configuration. It reads bounded native metadata and atomically saves one latest advisory `native_progress` snapshot, a local revision/event and a durable retry receipt. It never changes local state, work status, progress notes, dependencies or completion. Selecting another eligible handoff replaces only that advisory snapshot. No model tool, automatic synchronization, worker dispatch or native write is introduced.

A fresh sync requires the current opt-in, a confirmed identity-bound handoff for the exact source task UUID, and an unchanged expected revision of a captured local task. An identical retry returns the original durable receipt before ledger/native/creation-enabled checks, even if the local task is now terminal. It is a historical result, not a fresh observation. Conflicting reuse of the request key is refused; missing or uncertain native outcomes never trigger recreation.

## Durable identity before observation

Native creation records `{card_id, created_at, created_event_id}` into the handoff ledger before the native transaction commits. A crash after this binding is still uncertain, not permission to resubmit. Observation must match the card ID, handoff key, timestamp and original creation event. Duplicate keys, replacement, key changes or a missing original event after garbage collection prevent treating another card as the original. This is identity checking, not an event-watermark or total-order guarantee.

If creation committed but its response was lost, another authorized native actor may have advanced the original card before explicit reconciliation. With the exact persisted anchor and a matching current card, reconciliation can report `identity_confirmed` and confirm historical creation even when the card is no longer parked. This enables a subsequent explicit sync; it does not claim the card remains parked, that execution succeeded, or that the local task is complete. Missing, duplicate or mismatched identity still fails closed.

All v1 records that had already attempted creation are permanently `legacy_unbound` and cannot sync: a later observation is not proof of the original creation identity. An unattempted v1 prepared record may acquire its anchor during a future explicit creation. No implicit adoption or recreation occurs.

## Presentation contract

The snapshot contains only `handoff_id`, `card_id`, `outcome`, `status`, `observed_at` (UTC epoch seconds), and `exported_revision`. Native title/body, messages and run output are not copied back. `current` observations support the native states triage, todo, scheduled, ready, running, blocked, review, done and archived. The other outcomes are missing, duplicate, identity_changed, key_changed and identity_unavailable; their status is null, never a retained old native status.

Task detail and bounded task/review views label this as **Native board observed … (not local completion)**. Native done/review does not complete or otherwise advance the local task. A missing field in an old receipt means unknown history; a current null field means no observation recorded. New observations replace the previous advisory snapshot, not the original handoff or historical receipts. Status reports configured availability, not verified native runtime or live acceptance. The saved snapshot becomes local task data and can be returned by separately activated task-model read tools. This adds no model sync action or provider call; the focus projection is not automatically enriched. Because syncing itself increments the local revision, comparing exported/current revision alone is not a content-staleness test.

## Limits

[Parked handoff](52-parked-kanban-handoff.md) source/schema checks, shared-board boundaries and trusted-host import assumptions still apply. Observation uses read-only SQL, which may still cause SQLite WAL bookkeeping. Current opt-in and task CAS are rechecked, but native and local databases are not one atomic transaction: the native card can change immediately after observation. Stored timestamps identify the local observation time, not proof of freshness or provider execution.

This milestone has offline fixture coverage only. No installation, live Kanban, Gateway or model acceptance is claimed, and existing scanner restrictions are unchanged. [Roadmap](08-roadmap-and-acceptance.md) worker orchestration and universal task mapping remain incomplete.


[The native handoff workbench](100-native-handoff-workbench.md) now provides readable default views and explicit `--json` compatibility across this complete operator journey. Its manual packaged-Gateway lane and exact-source execution evidence are separate from this original offline milestone.
