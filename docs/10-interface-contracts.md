# 10. Proposed Interfaces and End-to-End Contracts

English | [简体中文](10-interface-contracts-zh.md)

Everything on this page is a **proposed contract** for this project, not a claim that Hermes already provides APIs with these names. Exact naming will be frozen after E0. Domain services should be decoupled from UI/models; entry through an agent tool, a mobile button, or background scheduling must use the same state and permission checks.

For concrete client HTTP routes, host authentication, canonical session transport, durable change feeds, and connector schemas, see [14](14-client-api-contracts.md). That design is also unimplemented; this page defines the common domain layer.

[15](15-primary-bot-binding.md) adds the proposed Primary Bot binding service, owner-confirmed control operations, binding epochs and server-derived session roles. These are not general model tools or new native Hermes RPCs. A canonical conversation, worker result or Bot message never supplies owner authority by itself.

[19](19-unified-voice-provider-contracts.md) defines the proposed common voice-session/component interface for local and configured online speech backends. Media frames, provider cancellation and playback recovery are separate from durable domain commands; a voice-provider tool/delegation event remains a proposal to Hermes, not a direct action executor.

## 1. EventEnvelope

```json
{
  "schema_version": "personal.event.v1",
  "event_id": "opaque-source-event-id",
  "source_instance_id": "verified-connector-instance",
  "source_type": "message",
  "actor": {
    "external_id": "source-authenticated-id",
    "is_bot": false,
    "owner_binding_id": "binding-id-or-null"
  },
  "thread_ref": "source-native-thread-id",
  "occurred_at": "2026-11-06T09:00:00Z",
  "received_at": "2026-11-06T09:00:02Z",
  "body_ref": "permission-scoped-content-reference",
  "content_hash": "sha256-of-normalized-content",
  "correlations": [],
  "trust_class": "untrusted_content"
}
```

Actor/auth metadata comes from the connector/platform's trusted channel; names claimed in the body do not override it. The local identity service resolves owner_binding_id rather than accepting arbitrary values supplied remotely. Correlations aid retrieval only; they do not inherit authorization.

Deduplication is based on source_instance_id + event_id. For sources that support edits, also store revision/content_hash; an edited event requires updated evidence but does not directly repeat an old action. Advance cursors/watermarks only after that batch of events has been durably persisted, and deduplicate overlap between polling and webhooks.

## 2. Minimal Domain Tool Surface

Do not expose all database CRUD to the model. Initial tools can be grouped into the following small sets, with a minimal allowed set selected at supported session/worker creation boundaries or an explicitly supported next-turn rebuild. The pinned host freezes tool and prompt surfaces for a session/worker to preserve cache behavior; do not assume arbitrary mid-turn tool-schema mutation. Current policy must still be checked before every controlled action:

| Proposed tool | Key inputs | Output/side effects |
|---|---|---|
| `personal_context` | query, project/task ref, scope, limit | Bounded facts and sources; unauthorized entries are not returned |
| `personal_project` | action, project ref, expected_revision | Create/update business projects, linking through a native adapter when needed |
| `personal_commitment` | action, content, due, timezone, source refs | Modify commitment state; return revision and audit references |
| `personal_task` | action, outcome, acceptance, constraints, task ref | Map to native Kanban/workers rather than directly creating a parallel executor |
| `personal_fact` | propose/correct/forget, fact ref, scope, sources | Explicit facts/inferences; sensitive/conflict paths may require confirmation |
| `personal_automation` | create/inspect/pause/resume/cancel, trigger, destination | Execute through native cron/heartbeat; return native ref and schedule preview |
| `personal_action` | prepare/inspect/cancel, action kind, target, payload | Produce a precise intent; approval is not a parameter the model can set to true itself |

The ability to execute controlled actions is not exposed as an `approved: true` or “ignore policy” parameter. Approval receipts come from verified human interaction and host approval paths; the server revalidates principal, hash, expiry, and policy revision. If a controlled connector can be bypassed through another raw tool, reduce the current toolset/credential scope or mark it as failing the release gate.

## 3. Common Result Structure

```json
{
  "status": "awaiting_approval",
  "object_ref": "intent-id",
  "revision": 3,
  "summary": "Please confirm the recipient and the content to send.",
  "evidence_refs": ["source-id"],
  "native_refs": {},
  "next_action": {
    "kind": "human_approval",
    "request_ref": "approval-request-id"
  },
  "error": null
}
```

`status` uses a structured enum: ok, awaiting_approval, denied, blocked, conflict, not_found, retryable_failure, unknown_outcome, cancel_requested, cancelled. Denied is terminal for the current intent and is not handled as retryable_failure. `summary` is human-readable text only; business state must not be inferred by parsing it. Errors include stable codes, retryability, and necessary remediation without exposing tokens/raw sensitive payloads.

## 4. NativeAdapter Contracts

Domain services integrate with Hermes through adapters; E0 tests determine which supported path to use among official ctx/tool dispatch/CLI/API interfaces.

| Adapter | Required behavior | Capabilities that must not be assumed |
|---|---|---|
| ProjectAdapter | list/resolve/create/link, returning stable native IDs | Mobile inherently has the desktop_project tool |
| TaskAdapter | create with idempotency, get state/attempt, request cancel, read result | Arbitrary private DB imports are stable; succeeded means business done |
| ScheduleAdapter | create/update/pause/cancel/read next-run/read execution | Directly editing jobs.json is supported; cron automatically runs MemoryProvider |
| DeliveryAdapter | resolve verified route, submit, get receipt/reconcile | Every platform can prove delivery/read status |
| ShortWorkerAdapter | launch/status/cancel/result, restricted toolsets | Lifecycle handles survive across processes; all request fields are available |
| ConnectorAdapter | read/write capability, auth health, idempotency/reconcile | Read-only annotations guarantee server-side semantics |

All adapters return stable external refs and capability flags. Services lacking idempotency or receipts must explicitly report that limitation rather than inventing success guarantees. Adapter compatibility tests detect native API changes; the domain schema should not change frequently with internal module refactors.

## 5. Three Acceptance Paths

### A. Create a Reminder

Owner sends request → Event deduplication/identity verification → Parse time and timezone → Domain automation prepared → Native scheduler creates job → Save native ref/reconciliation key → Show schedule to owner → Occurrence arrives → Check that it remains valid → Sole delivery owner sends → Save receipt. If the native job was created but the domain writeback failed, a retry first reads by idempotency/correlation rather than creating a second job.

### B. Prepare and Send Content

Owner request → Retrieve authorized sources → Produce draft/artifact → Precise action intent → Determine whether an existing grant covers it → If needed, show recipients/content/attachments/impact → Verify approval → Reread revision before execution → Connector sends → Record receipt → Confirm the actual result externally. A send timeout enters unknown/reconcile; changing critical body content or recipients after approval invalidates the old approval.

### C. Interrupt a Project Worker

Main agent creates task and acceptance criteria → Native Kanban dispatches work/short worker → Owner's new message preempts the foreground → Explain/modify original task → Update scope/revision → Worker verifies before its next side effect → cancel_requested or continue within narrower scope → Enter review/done according to native results and acceptance criteria. A worker finishing cannot reuse an expired grant; later third-party events provide evidence only and do not automatically resume the task.

## 6. Protocol Evolution

Manage schema_version independently for each object contract; new fields are optional, while semantic changes require migration. Clients must not parse the string structure of opaque IDs. Freeze object references, source permissions, state enums, and error codes through contract tests. Allow backup and dry-run before migration; on failure preserve the old working state rather than allowing a partially upgraded system to start outbound actions.
