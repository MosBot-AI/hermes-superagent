# 04. Domain Data and Memory

English | [简体中文](04-domain-data-and-memory-zh.md)

## 1. Principles

“Memory” cannot carry all state. Project tasks need deterministic state machines; personal facts need provenance and correction; authorization needs revocable, strict scopes; and chat records must remain intact. These can reference one another, but must not be compressed into a single long text that the model can arbitrarily overwrite.

All tables include `id`, `owner_id`, `profile_id`, `created_at`, `updated_at`, and `revision` by default. Store instants in UTC; also retain the IANA timezone and original wording for human-facing deadlines. Structured data lives in `$HERMES_HOME/plugin-data/<plugin-id>/` and is not committed to Git. Store controlled references and hashes for large attachments rather than copying them into every database row.

## 2. Minimal Data Model (Proposed)

| Object/table | Main fields | Constraints |
|---|---|---|
| `owners` | Principal id, status, default timezone | Do not use display names as identity primary keys |
| `channel_bindings` | Platform, tenant/account, external user id, verification method, revocation time | Chat/group/thread location is not owner identity |
| `projects` | Name, goal, scope, status, native project/board reference | Link existing native projects; do not recreate them |
| `commitments` | Who promised whom, content, due, timezone, status, source ids | Separate facts from inferences; others’ commitments must not be presented as the user’s |
| `tasks` | outcome, acceptance, constraints, dependency, Kanban/run references | Read execution status from native systems; record business acceptance separately |
| `facts` | subject, predicate, value, scope, confidence, valid_from/to, status | Separate inferred and explicit facts; allow correction/forgetting |
| `sources` | Service/account, external id/url, author, event/retrieval time, content hash, permission labels | URLs may expire; retain only the minimum necessary evidence excerpts |
| `automations` | User goal, trigger type, native job id, stop condition, budget, destination | Hermes owns scheduling instances |
| `action_intents` | action kind, target, payload hash, scope, expected revision, status | Approval binds to the exact action and becomes invalid after changes |
| `grants` | Principal, permitted operations/data/recipients, expiry, limits, policy version, revocation | External content cannot create grants |
| `approvals` | intent id, approved hash, channel/approver, time, expiry | Old messages cannot replay a one-time approval |
| `effects` | intent id, idempotency key, attempt, remote receipt, status | Reconcile unknown outcomes; never retry blindly |
| `deliveries` | artifact/summary, route, dedupe key, receipt, status | Separate accepted from delivered |
| `audit_events` | Correlation ids, action, reason code, before/after revisions, summary | Redact by default; never record tokens/passwords |

## 3. Core State Machines

**Commitment**: `proposed → open → waiting_external / blocked → fulfilled / cancelled / superseded`. Finding a similar email alone must not automatically mark a commitment fulfilled; evidence of delivery or user confirmation is required.

**Task business state**: `captured → clarified → ready → active → waiting_user / waiting_external / blocked → review → done / cancelled`. A native worker’s succeeded state means only that one execution has ended. If acceptance criteria remain unmet, retain review/blocked rather than falsely reporting done.

**ActionIntent**: The main path is `prepared → awaiting_approval → authorized → executing → succeeded / failed / unknown`; an action not yet submitted may enter `cancelled`. User rejection enters the explicit terminal state `denied`. Expired authorization may return to awaiting confirmation. Changes to material content require a new intent and invalidate the old one. Revocation cancels actions not yet admitted for execution; in-flight actions follow the [authorization commit linearization point](06-plugins-mcp-and-security.md#8-revocation-audit-and-emergency-stop).

`denied` is never revived or automatically retried using another tool/channel, nor is a past denial treated as a temporary error that the next turn can override. Only when a new explicit user instruction or relevant new authorization permits proposing the action again may a new intent be created. Retain `supersedes_intent_id`, the new content hash, and new authorization evidence, and repeat all checks. Third-party messages and model-generated rewrites do not meet this condition.

**Fact**: `candidate → confirmed / inferred → superseded / retracted / expired`. Multiple facts may conflict, but retrieval must show which are currently valid and why they conflict, rather than simply applying “last write wins.”

All changes use revision/compare-and-set to prevent concurrent overwrites from mobile, desktop, and background work. Persist state changes and outbox entries in the same plugin database transaction. Synchronize native state using events and periodic read-only reconciliation; mark it stale when disconnected.

## 4. Memory Layers

1. **Raw conversations**: Hermes SessionDB/session_search; do not store a separate complete chat copy.
2. **Small, stable memory**: Hermes MEMORY.md / USER.md, containing high-value preferences and indexes explaining how to find details, rather than large activity logs.
3. **Structured personal data**: This plugin’s facts, people/relationships, commitments, and provenance, retrieved through domain tools.
4. **Project knowledge**: Task-related materials, decisions, and result references; never retrieved without permission.
5. **Optional external memory provider**: Only one external provider can be active. Preserve the user’s existing provider. Advanced semantic retrieval is a later option, not a prerequisite for the first release.

Use SQLite indexes/full-text search by default, adding vector indexes only as needed. The fact store is authoritative; vectors are only rebuildable indexes. After retrieval, filter permissions, scope, expiration, and provenance before entering model context. Prompting the model to ignore unauthorized results is not sufficient.

## 5. Memory Write Workflow

```text
Trusted input or tool result
  → Identify candidate facts/commitments (the model may propose them)
  → Validate source, author, scope, sensitivity, and duplication
  → Check conflicts with existing facts
  → Write a new revision through a deterministic service
  → Update bounded native summaries or indexes (where applicable)
  → Visible audit trail with correction/deletion controls
```

Explicit user instructions may directly become confirmed preferences within their corresponding scope. One-time task choices stay with that task. Model inferences must be labeled inferred and never promoted into standing authorization. Third-party statements retain their authorship and must not be recorded as “the user said this directly.”

Hermes cron sets `skip_memory=True` in this baseline. Do not assume background cron naturally triggers an external MemoryProvider’s sync/prefetch. If background organization needs to write domain data, use explicit, restricted domain tools or generate candidates for the main agent to merge. Do not bypass upstream boundaries to automatically modify core personal memory.

## 6. Correction, Forgetting, and Export

- Corrections create a new revision and mark old facts superseded. Provenance-backed audits retain minimal records, and users can see correction results.
- Forgetting first removes retrieval visibility and derived indexes, then deletes source copies/attachments according to the user’s choice. Deleting originals in external services is a separate explicit action.
- Deletion does not make backups disappear immediately. Retention policies explain backup expiration, tombstone replay on restore, and vector cleanup. Do not promise technically impossible instantaneous forgetting everywhere.
- Export JSON/Markdown and attachment inventories with a data dictionary and sources. Do not export credentials or authorization tokens.
- Encrypt user data at rest using verified system/storage mechanisms and controlled keys. SQLite alone does not imply encryption.

## 7. Synthetic Example

“Use Chinese for my project weekly reports from now on” becomes `subject=owner`, `predicate=report_language`, `value=zh-CN`, `scope=project_weekly_report`, `status=confirmed`, with source pointing to that message from the user. It must not expand into using Chinese for all outgoing emails. An email saying “Zhang said you can sign the contract next week” produces only third-party information, not authorization to sign or a confirmed personal commitment.

## 8. Data Quality Gates

Every long-term fact must trace to a source or be explicitly labeled an inference. Historical imports without sources must not fabricate provenance. Tests cover conflicts, incorrectly merged names, retractions, timezone changes, cross-profile leakage, stale index remnants, concurrent overwrites, and replay of forgetting after backup restoration.
