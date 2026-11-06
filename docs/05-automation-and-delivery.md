# 05. Proactive Work, Scheduling, and Delivery

English | [简体中文](05-automation-and-delivery-zh.md)

## 1. Proactivity Is Not Unlimited Autonomy

The proactive module identifies work worth advancing and acts within the user’s authorization. Every automation has a goal, data sources, action scope, destination, frequency, budget, and expiration/stop conditions. The default is reading, organizing, and reporting to the owner. Messaging third parties, modifying external systems, and spending require matching permissions.

Background checks remain quiet when there are no useful changes. They must not invent tasks to demonstrate that they are “working,” or accept instructions embedded in external content. User disablement, revocation, and new messages take priority over continued background execution.

## 2. Three Mechanisms with Distinct Responsibilities

| Type | Native mechanism | Lifecycle | Example |
|---|---|---|---|
| Observation within the current session | session `/heartbeat` | One per session; runs only on idle turns; explicit cleanup semantics at reset/switch and other boundaries | Check whether the current PR has finished |
| Standing reminders/reports/monitoring | Hermes cron | Persistent jobs, timezones, execution ledger, result delivery | Tomorrow at 9 a.m.; Friday briefings |
| Work requiring sustained progress | Hermes Kanban/goal | Dependencies, worker attempts, acceptance, blocking, and recovery | Multi-step research; project delivery |

Do not poll every task with a single high-frequency cron or put a long task into an endless `/goal`. Persisted heartbeat state does not mean it runs without a live CLI/gateway. Installation and service health must be visible.

## 3. Minimum Automation Record

`goal`, `trigger_spec`, `timezone`, `source_scope`, `allowed_effects`, `destination_binding`, `quiet_hours`, `priority`, `dedupe_window`, `max_runs/cost`, `expires_at`, `stop_when`, `native_job_id`, `created_from_source`.

For relative times, retain the creation instant and resolved absolute time. For “every day at nine,” retain local calendar semantics and the IANA zone. DST transitions need explicit policies for ambiguous/nonexistent times; storing only a UTC offset is insufficient. Fixed-timezone reminders do not automatically follow the user’s location after travel; location-following reminders require an explicit mode.

## 4. Reliable Execution Chain

```text
Native trigger + native occurrence/run id
  → Verify automation is still valid, authorization is not revoked, and budget is sufficient
  → Idempotently claim domain evaluation (when needed)
  → Read incremental evidence
  → Generate observation / action proposal
  → Decide whether it warrants an interruption
  → effect / delivery outbox
  → Native channel send or connector action
  → receipt / unknown / retryable failure
  → Reconciliation + stop condition
```

The plugin outbox handles only domain side effects it owns; it must not duplicate responsibility for Hermes’s existing cron delivery queue. Adapters must choose one delivery owner: when using native cron delivery, synchronize from its receipts; when using plugin-owned delivery, disable that job’s automatic duplicate delivery. A single result must not be sent by both.

## 5. Idempotency and Unknown Outcomes

- Scheduling deduplication key: `profile + automation_id + native_occurrence_id`, not a timestamp that changes on retry.
- External action key: `intent_id + payload_hash + destination`. Pass an idempotency key when supported by the receiver and save its receipt.
- If the receiver lacks idempotency support, first query whether the target already contains the specified object/marker. If the query is inconclusive, mark the outcome unknown and request necessary confirmation rather than blindly resending.
- “Queued,” “accepted by the platform,” “confirmed delivered,” and “read by the user” are distinct states. Many platforms lack delivery/read receipts; the UI must acknowledge uncertainty.
- A crash between remote success and local commit requires remote reconciliation. A transactional outbox cannot guarantee end-to-end exactly-once execution.

Hermes already has reliability mechanisms for cron execution, occurrences, and delivery. Test and reuse them first rather than reimplementing its tick lock, worker reclaim, or next_run_at algorithms.

## 6. Reminder Deduplication and Interruption Budgets

Before notifying, check the latest source data, whether the task is complete, the most recent equivalent notification, user quiet hours, destination permissions, and information validity. Default priority: urgent with clear impact > deadline-bound blockers > scheduled briefings > suggestions. Frequency and quotas are configurable product rules, not hidden magic values.

Build a rule-based shortlist before having the model assess content value. No reply does not mean consent to keep nudging, nor does it permanently disable all proactive features. Follow only that automation’s repetition and escalation rules. Do not send expired information. If nothing changes, record only the run ledger entry.

## 7. User Interruption, Pausing, and Revocation

To pause an automation, first update persistent state and the policy revision, then stop future triggers and cancel pending intents that are still cancellable. Actions already submitted to external services cannot “undo history.” Record what happened, check whether compensation is possible, and explain truthfully.

Running workers check current persistent authorization before every tool admission that can produce side effects. Do not assume a worker has stopped merely because it received a “permissions changed” notification or a profile snapshot was edited. Admission and revocation are ordered at the transactional linearization point in [06 §8](06-plugins-mcp-and-security.md#8-revocation-audit-and-emergency-stop). Already-admitted in-flight requests can only be cancelled on a best-effort basis; remote execution cannot be guaranteed to be withdrawn. Cancellation is a request state; mark cancelled only after confirmation from the worker/external receipt. A phone going offline, session reset, or reply to an old message must not automatically restore invalid authorization.

## 8. Failure Categories

| Failure | Handling |
|---|---|
| Temporary read timeout/429 | Bounded exponential backoff, respect retry-after, retain cursor |
| Revoked credentials/insufficient permissions | Disable the affected action, mark blocked, and do not bypass using different credentials/channels |
| Model failure | Fall back to a templated reminder or leave pending; never fabricate completion |
| policy/approval service unavailable | Fail closed for side-effecting actions; read-only operations and ordinary chat may degrade gracefully |
| Outbound timeout with possible success | Mark unknown; continue only after read-back or a human decision |
| gateway restart | Use native recovery plus domain reconciliation; do not replay all old notifications |
| Recipient/group changes | Revalidate the route; sensitive content does not automatically follow an unknown new group |
| Budget exhausted | Pause background work and send the owner one consolidated, actionable notice |

## 9. Minimum Observability

Correlate every run using `automation_id / native_job_id / native_run_id / intent_id / effect_id / delivery_id`. Expose the last successful read, next trigger, last notification, stop reason, retry count, and cost estimate. Logs must not store complete personal documents or tokens. The health page must distinguish “scheduling works but delivery failed” from “never ran.”
