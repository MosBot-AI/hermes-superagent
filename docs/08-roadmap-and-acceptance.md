# 08. Roadmap, Project Breakdown, and Acceptance

English | [简体中文](08-roadmap-and-acceptance-zh.md)

## 1. Planning Principles

This is an implementation plan, not a completion report. Items that have not passed code, testing, deployment, and user acceptance must not be marked Done. See [12](12-foundation-progress.md) for the current E0.1/E0.2/E0.5 foundation-slice progress; this does not mean E0/M0 or the entire personal agent is complete.

Complete a safe, reliable vertical slice first, then add connectors, entry points, and proactivity. Advance phases according to dependencies and gates; do not invent timelines when team size and availability are unknown. GitHub Projects manages engineering delivery; runtime Hermes Projects/Kanban manages the user's affairs.

## 2. Milestones

| Milestone | Deliverable | Entry criteria | Exit gate |
|---|---|---|---|
| M0 Design and contracts | Pinned baseline, runnable synthetic tests, minimal public API mapping, write-path coverage inventory | This design is complete | Gaps and adaptation paths are clear; no reliance on imaginary APIs; uncovered write capability sets are disabled by default |
| M1 Reliable vertical slice | One owner, one project, one mobile text entry point, one reminder, controlled actions | E0.1–E0.5 applicable gates, E1.1–E1.5, and recovery/reconciliation foundations are complete | Restart/duplicate/denial/revocation tests pass; no enabled write path is known to bypass the action gate |
| M2 Personal affairs | Facts/commitments, native multitasking, proactive observation, and reliable notifications; optional E9 routing shadow mode | M1; E9 shadow also requires a trusted-constraint baseline | Real-world scenarios work end to end; information correction and forgetting work; shadow mode does not change the actual model |
| M3 Connections and voice | Minimal read/write MCP set, mobile voice messages, optional real-time voice validation and E9 bounded model routing | M2 + connector risk review; routing also requires E9.5/E9.6 gates | Confirmation of critical voice fields, identity, and costs are controlled; routing quality/privacy/budget gates pass |
| M4 Release hardening | Recovery, backup, upgrades, rollback, security evaluations, and documentation | Core scenarios are complete | All release gates pass, with no unresolved P0 issues |

## 3. Epics and Work Packages

### E0. Verify Upstream Compatibility Contracts (P0, M0)

- E0.1: Pin the supported Hermes version/SHA; establish a source capability matrix and license/notice records.
- E0.2: Minimal native plugin registration, config_schema, plugin_data_dir, and tool/hook/ctx contract tests.
- E0.3: Verify public operations for Project/Kanban/cron creation, querying, cancellation, and receipts; record gaps as upstream seams rather than writing directly to the host DB.
- E0.4: Test pre_tool_call callback and dispatcher exceptions and middleware fallback; cover native tools, raw MCP, shell/browser, execute_code/RPC, batch calls, and workers. Disable write capability sets not protected by the action gate by default, or degrade them to read-only. Specifically verify read-only degradation when troubleshooting safe mode skips hooks, and that ordinary managed workers' frozen config does not prevent reading the current persistent policy revision.
- E0.5: Build offline synthetic source/connector fixtures so tests do not depend on real personal accounts.
- E0.6: Verify client transport contracts at the pinned host: dashboard API registration, trusted principal/profile propagation, canonical session RPCs, auth/isolation/file boundaries, and explicit unsupported modes. Depends on E0.1/E0.2 and uses E0.4 findings; this is not a claim that full write coverage is complete. See [14](14-client-api-contracts.md).

Acceptance: Every reuse point has a behavioral test or an explicit blocker; the initial `requires_hermes` range comes from tests, not arbitrary version numbers. Produce a per-tool, per-path enforcement inventory. A capability set must not be enabled while it has unknown or bypassable write paths; prompt constraints cannot substitute for enforcement.

Current E0.4 progress: [synthetic failure contracts and a blocked-write inventory](13-enforcement-contracts.md) are implemented. This is partial evidence, not complete path coverage or permission to enable writes.

E0.6 is an independent optional-client contract lane. It does not gate the channel-first M0/M1 exit; existing general E0 dependencies mean the applicable E0.1–E0.5 gates unless E0.6 is explicitly named.

### E1. Establish Identity, Authorization, and Audit (P0, M1)

Depends on E0.2/E0.4.

- E1.1: Owner and verified channel binding; classify group/third-party/forwarded/bot identities.
- E1.2: ActionIntent, grant, and approval schemas and revisions; bind approval to payload/target/expiry.
- E1.3: Operation-level checks in domain handlers and native approval adaptation; prohibit bypass through alternate paths after denial.
- E1.4: Soft pause, hard revoke, and emergency stop; establish transactional linearization points for authorization admission and revocation, cancel effects not yet admitted, and preserve truthful status and best-effort cancellation semantics for in-flight requests already admitted/sent.
- E1.5: Redacted audit, sensitive-data classification, and minimal credential exposure.

Acceptance: All write operations in release scope are covered; spoofed identities, stale approvals, payload changes after approval, and policy failures cause no unauthorized side effects. Revocation race tests cover “revocation commits first/admission commits first but nothing has been sent/the remote has accepted but local outcome is unknown/the next action after revocation.” Assert against the transactional ordering of admission and revocation; do not promise to retract already authorized remote requests. A denied intent cannot be revived; a new instruction requires a new intent and fresh authorization.

### E2. Establish the Personal Domain and Memory (P0/P1, M1–M2)

Depends on E1.1/E1.5.

- E2.1: SQLite schema/migrations, projects/commitments/facts/sources, and revision updates.
- E2.2: Scope-based retrieval, explicit facts/inferences/conflicts, and only bounded summaries in native memory.
- E2.3: Correction, expiration, forgetting, export, and backup/restore tombstones.
- E2.4: Person/project disambiguation and task-source associations; do not treat third-party reports as owner instructions.
- E2.5: Evaluate optional memory provider adaptation; remain compatible with the user's existing single provider rather than forcing replacement.

Acceptance: Long-term facts have provenance or inference labels; they are not readable across profiles/group chats; retrieval tests after correction and deletion pass.

### E3. Connect Native Projects and Tasks (P0/P1, M1–M2)

Depends on E0.3, E1.1–E1.5, and E2.1.

- E3.1: Connect domain Projects to native Projects/boards, preserving the distinction between business context and working directories.
- E3.2: Task ↔ Kanban card/run mapping, acceptance contracts, dependencies, blockers, and review.
- E3.3: Public lifecycle API for temporary subagents, minimal context and toolsets, and parent-task aggregation.
- E3.4: Prioritize owner follow-ups, thread-to-task associations, context-only, and handback.
- E3.5: Restart reconciliation, unknown outcomes, completion evidence, and cancellation states.

Acceptance: Deduplicate one input into one task; do not mix context across projects; a short subtask exiting must not falsely report the whole task complete; long-running tasks remain queryable across restarts without duplicate dispatch.

### E4. Implement Reminders and Reliable Delivery (P0/P1, M1–M2)

Depends on E0.3, E1.1–E1.5, and E2.1.

- E4.1: One-time/recurring reminders and IANA timezones, with explicit DST, missed-window, and stopping semantics.
- E4.2: Reuse cron/heartbeat; record native job/run/occurrence references and domain objectives.
- E4.3: Plugin-owned effect/outbox/receipt records, with a clearly designated sole owner for native delivery.
- E4.4: Reconcile unknown outcomes, deduplicate, handle invalid routes and dead letters, and provide recovery entry points.
- E4.5: Quiet hours, notification coalescing, change detection, and separate attention/compute budgets.

Acceptance: Duplicate triggers, process interruption, send timeouts, restarts, and cancellation do not cause blind duplicate outbound sends; no change may remain silent; accepted is not presented as delivered.

### E5. Govern MCP and Plugins (P1, M2–M3)

Depends on E1/E4.3.

- E5.1: Connector capability registry: accounts, read/write operations, versioned input/output schemas, data classes, costs, actual idempotency retention, receipt levels, reconciliation/cancellation capabilities, and auth health.
- E5.2: One read-only connector and one controlled-write connector vertical slice, with typed prepare/execute/reconcile/cancel contracts, server-side semantic validation, per-effect admission, stable effect keys, and partial/unknown-outcome tests. Preparation with a remote side effect is itself a controlled operation.
- E5.3: Minimal toolsets, MCP trust/filters/OAuth, and disconnection/revocation handling.
- E5.4: Plugin sources, pinned versions, dependency updates, consent for expanded access, and a supply-chain inventory.
- E5.5: Persistent budgets and connector receipts; do not substitute native session estimates for billing records.

Acceptance: False read-only claims, incorrect scope, revoked credentials, and malicious tool results cannot produce unauthorized behavior; new connectors must complete risk and recovery contracts before writes are enabled. E5.1/E5.2 remain checklists within the existing Epic, not new IDs. Contract design can proceed from E0.6/E1.2; write enablement requires E1.3/E1.4, E4.3/E4.4 and the connector’s E0.4 path coverage. Native OAuth remains the credential owner. See [14](14-client-api-contracts.md) for concrete connector inputs, outputs and receipts.

### E6. Enable a Mobile Work Entry Point (P1, M1–M3)

Depends on E1.1/E3/E4.

- E6.1: One primary mobile messaging channel, identity binding, text/attachments, and task/reminder routing.
- E6.2: Desktop/mobile continuity and short candidate lists for disambiguation; idempotency for duplicate messages and approval buttons.
- E6.3: Personal overview, preferably reusing native dashboard/plugin UI; validate mobile layout.
- E6.4: TLS/auth/session revocation, attachment access, small-screen, and poor-network tests.
- E6.5: Build Domain API and Change Feed (M2, optional, Backlog): versioned typed REST over domain services, transactional dedup/outbox/change feed, authorized consistent snapshot and polling overview. Depends on E0.6, E1.1–E1.5, E2.1, E3.2/E3.5 and E4.2–E4.4; only individually verified adapters may be enabled.
- E6.6: Validate Client Recovery Flows (M3, optional, Backlog): multi-device, offline, replay, expiry, ACL, isolation and cancellation scenarios. Depends on E6.5, E6.2/E6.4 and the E8.1/E8.2 harness for these paths, not all of E8/M4. Artifacts also require E0.6 file-contract evidence.
- E6.7: Validate Native Mobile Sign-in (M3, optional, Blocked): depends on E0.6 auth findings, E1.1/E1.4/E1.5 and E6.4. The pinned native flow accepts only loopback callbacks; a supported target-phone callback and device-revocation contract must be proven before physical-device certification. Do not create a second plugin auth service.

Acceptance: Complete “create project → reminder → inspect/cancel → approve controlled action” on the target physical phone; old devices and forwarded approvals cannot perform operations. M1 uses an existing messaging channel and does not depend on E6.5–E6.7 or a custom app. Optional browser/PWA delivery can precede native-mobile certification. New client work remains unimplemented; detailed contracts and exact blockers are in [14](14-client-api-contracts.md).

### E7. Preserve Voice Task Continuity (P1/P2, M3)

Depends on E6/E1.3.

- E7.1: Reuse STT/TTS for mobile voice messages, supporting Chinese and time/name corrections.
- E7.2: Voice action intents and visible confirmation; distinguish barge-in, stopping playback, and cancelling execution.
- E7.3: Audio privacy and retention, host relay/short-lived credentials, and visible provider costs.
- E7.4: Validate real-time voice feasibility; expand release only if device and cost criteria are met.

Acceptance: Misrecognition does not cause high-impact outbound actions; the same task can switch between text and voice; network loss or stopping voice does not falsely report cancellation of an external action. Real-time voice is a separate gate and does not block a completed voice-message MVP.

### E8. Complete Operations, Evaluation, and Release (P0/P1, Across M0–M4)

Dependencies are integrated as each capability arrives; cover all of them before release.

- E8.1: Correlation IDs, redacted logs, and health/budget/unknown-outcome dashboards.
- E8.2: Crash injection, concurrency, and provider/MCP/channel failure matrices.
- E8.3: Backup/restore, migrations, upgrade compatibility, rollback, and data retention.
- E8.4: Fixed scenario suites, observe-mode evaluation, false-positive and cost reports.
- E8.5: Installation, configuration, deactivation, permissions, privacy, and troubleshooting documentation.

Acceptance: Run the full set of gates on the same release SHA; disclose skipped/failed items and do not present static checks as runtime verification.

### E9. Design and Validate the Worker Routing Plugin (P1, M0–M3)

Detailed design: [Worker Model and Reasoning-Effort Routing Plugin](11-worker-model-routing.md). Reuse the Hermes delegation backend to choose per task from the provider/model/effort set configured and permitted by the user, without changing the main agent model or requiring a gateway deployment. All work packages below remain to be implemented and are currently Backlog.

| ID | English work package title | Primary milestone | Deliverable and dependencies |
|---|---|---|---|
| E9.1 | Verify Hermes Routing Contracts | M0 | Depends on E0; plugin registration/route_task/schema pin, model capability inventory, uncovered paths, and compatibility tests |
| E9.2 | Define Trusted Route Context and Constraints | M1 | Depends on E9.1, the identity/grant/revocation/data-scope contracts in E1.1/E1.2/E1.4/E1.5, and the task/attempt identifier contract in E3.2; does not wait for all of E3 |
| E9.3 | Build Shadow Routing and Audit | M2 | Depends on E9.1/E9.2; advisory selection that does not change the actual route, redacted audit, and baseline evaluation |
| E9.4 | Enable Bounded Worker Routing | M3 | Depends on E9.3 and the E9.5/E9.6 enablement gates; bounded tasks, attempt/deadline/cost limits, and controlled fallback |
| E9.5 | Validate Effort and Fallback Policies | M2 | Depends on E9.1/E9.2; provider wire mappings, rejection of unknown capabilities, fallback privacy/permissions, cancellation, and no duplicate side effects; retest in M3 |
| E9.6 | Integrate Budget Admission and Release Gates | M3 | Depends on E9.2, admission/revocation in E1.3/E1.4, attempt/reconciliation contracts in E3.2/E3.5, audit metering in E8.1, and failure fixtures in E8.2; complete budget and routing release gates without waiting for all of E8/M4 |

Acceptance: Select only permitted candidates; do not override exact user pins; classifiers/reviewers/fallbacks are also subject to privacy and budget constraints; distinguish requested effort from effective wire effort and explicitly label unknowns. Without trusted context/budget enforcement, remain in shadow mode or reject the relevant automatic routing. Shadow results must not be presented as actual success rates for a new model; enablement requires independent replay/task-validation evidence. Failure to pass safety and cost limits cannot be excused by “cost optimization.”

## 4. Sequence for the First Usable Vertical Slice

E0.1–E0.5 (including applicable write-path coverage and disabling uncovered capability sets) → E1.1–E1.5 (identity, authorization, execution checks, hard revocation, audit/data classification) → E2.1 → E3.1/E3.2/E3.5 + E4.1–E4.4 (including task recovery, unknown outcomes, and delivery reconciliation) → E6.1 → corresponding crash/revoke/delivery tests in E8.1/E8.2 → M1.

Start E2.1 once the E1.5 data classification and audit conventions are clear. M1 cannot skip E1.4 and still claim revocation passes, nor defer recovery/reconciliation in E3.5/E4.4 and claim the reliable vertical slice is complete. Only then add broader automatic proactivity and more connectors. Identity, safety, and recovery are not “a final layer to add later.”

E9 is an optional enhancement; it must not turn the first version's fixed-model delegation into a system dependent on a new gateway. Its independent sequence is E9.1 → E9.2 → E9.3 shadow; E9.5/E9.6 may be validated in parallel, and E9.4 is enabled only after all gates pass. Do not launch automatic switching first and add trusted scope and cost controls later.

## 5. Suggested GitHub Projects Configuration

- Main Project: Hermes Personal Agent, describing objectives, the design baseline, and unimplemented status.
- Status: Backlog, Ready, In Progress, Blocked, In Review, Done. Blocked must include a reason and next step; do not label waiting for confirmation as In Progress.
- Fields: Epic (E0–E9), Milestone (M0–M4), Priority (P0/P1/P2), Area, Risk, Effort, Dependencies, Acceptance evidence. E9 Epic/work package titles use English; the documentation body continues in Chinese in the Chinese version.
- Views: Roadmap (Milestone), Execution (Status board), Security/Blockers, Mobile/Voice, Ready next.
- Create epics and independently acceptable work packages first; do not swamp the plan with hundreds of tiny tasks.
- Issue templates include outcome, scope/non-goals, dependencies, design links, acceptance, tests/security, and completion evidence. Close a parent epic only after all required work packages and acceptance checks are complete.

Project links, Issue numbers, and final fields must reflect actual creation results. If API/permission restrictions allow only Issues to be created, not a Project, explicitly record the discrepancy; do not present planning tables in docs as proof that a GitHub Project has been configured.

## 6. Proposed SLOs and Test Gates

These are targets to be measured, not commitments already achieved. Report separately using fixed devices, networks, and providers; do not use provider incidents to conceal local queueing problems.

| Metric | Initial target/gate | Measurement |
|---|---|---|
| Unauthorized side effects | 0 in the release test suite; any failure blocks release | Adversarial/fault injection |
| Duplicate inputs | The same idempotency key does not duplicate tasks/known outbound sends | Replay, concurrency, restart |
| Queueing of new user messages | No indefinite blocking by background work when the host is healthy; initially p95 < 2s to enter processing | Measure intake to turn admission, excluding model response |
| Reminder triggering | Initially p95 ≤ 60s scheduling lateness when host/channel are healthy | Record due, admitted, delivered; measure each segment |
| Memory quality | 100% source coverage; 0 cross-scope leaks in the test suite | Synthetic conflict/deletion/isolation cases |
| Recovery | Every crash point has a terminal state or visible unknown; no silent loss | Inject exit at every transaction/remote boundary |
| Voice | Measure first audible audio, transcription, and cancellation latency; set numeric targets after establishing device baselines | Chinese/noise/poor-network/interruption suite |
| Costs | Queryable per task and per day; no new automatic chargeable actions at the limit | Provider/MCP simulation and billing samples |

## 7. Definition of Done

Code review + corresponding design/ADR updates + unit/contract/integration tests + adversarial security cases + recovery tests + user-visible failure paths + compatibility version records + real acceptance evidence. For external systems, retain redactable receipts/readbacks rather than treating model prose as proof. State the reason and risk for every test not run.
