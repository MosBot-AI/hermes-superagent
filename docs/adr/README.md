# Architecture Decision Records

English | [简体中文](README-zh.md)

Status: design adopted, pending implementation validation. Date: 2026-11-06.

## ADR-001: Native Hermes Plugin, No Parallel Agent Runtime

**Decision:** Extend Hermes through `plugin.yaml + register(ctx)`, native tools/skills, public ctx APIs, and ABCs. Reuse the agent loop, gateway, SessionDB, cron, Kanban, MCP, and voice.

**Rationale:** The user wants Hermes itself to become a personal agent. Duplicating execution, session, and scheduling systems creates dual state, upgrade costs, and gaps in permission enforcement. DSH/Cordis serves only as a design reference.

**Trade-off:** Stay within official extension surfaces. Start with contract spikes; where capabilities are missing, propose minimal general-purpose upstream extensions instead of directly changing the core or writing privately to host databases. See [03](../03-native-architecture.md).

## ADR-002: One Main Identity, Tasks Separate from Sessions

**Decision:** Default to one main profile/owner. Projects are context, and workers are temporary or Kanban-managed execution resources. A business Task links to native cards/runs and is not a chat session.

**Rationale:** Tasks must survive across sessions, devices, and restarts. An idle or ended session does not prove task completion. Multiple personas increase the user's coordination burden.

**Trade-off:** Task references, acceptance checks, and state reconciliation are required. Add main profiles only when data/identity isolation requires them. See [01](../01-product-and-scope.md) and [04](../04-domain-data-and-memory.md).

## ADR-003: Separate Intake and Action-Authorization Gates

**Decision:** IntakeGate determines candidate work. Before each side effect is committed, ActionGate checks owner, grant, scope, payload, recipient, limits, and the latest policy revision.

**Rationale:** DSH Mandate provides a useful task-level boundary, but cannot replace action-level enforcement for personal sensitive data. Prompts and automatic summaries cannot grant permission.

**Trade-off:** Connectors must implement fine-grained action semantics and approvals; some actions must be completed by a human. Distinguish precisely between fail-closed pre_tool_call callbacks and fail-open middleware, and recheck in the handler. See [06](../06-plugins-mcp-and-security.md).

## ADR-004: Domain Transactions with an Outbox, No End-to-End Exactly-Once Promise

**Decision:** Commit plugin-owned state and plugin-owned effects in the same SQLite transaction. Hermes remains authoritative for native scheduling/delivery. External actions use idempotency, receipts, and unknown/reconcile states.

**Rationale:** There is no shared transaction across databases and external services. A request timeout does not prove that execution did not occur. LLM recovery prompts are not reliability guarantees.

**Trade-off:** Reconciliation and human handling of a small number of unknown outcomes are necessary. Do not take over the native delivery queue a second time. See [05](../05-automation-and-delivery.md).

## ADR-005: Memory Is Sourced Data, Not an Authorization Database

**Decision:** Combine native sessions/stable summaries, structured facts/commitments, and on-demand project knowledge. Keep the user's existing memory provider by default.

**Rationale:** Facts can expire, conflict, or be withdrawn. Long-term permissions cannot be restored from model summaries. Hermes allows only one external provider, and cron defaults to skip_memory.

**Trade-off:** Correction, forgetting, index cleanup, and scope-aware retrieval are required. Do not build a large knowledge graph in the MVP. See [04](../04-domain-data-and-memory.md).

## ADR-006: Observe First; Hard Revocation Is Separate from Soft Pause

**Decision:** Proactive features start with read-only observation/proposals and are enabled later by scenario and risk. Pause stops new work. Revocation and action admission are linearized by transaction commit order in the same authoritative store, blocking subsequent admissions and invalidating old approvals. Cancellation of previously admitted in-flight requests is best effort; do not promise to retract actions already accepted remotely.

**Rationale:** Reducing the user's attention burden must not depend on granting unlimited autonomy. Telling a running worker that permissions changed does not mean the execution layer has revoked them.

**Trade-off:** Durable budgets, deduplication, policy revisions, and revocation-race tests are required. See [05](../05-automation-and-delivery.md) and [06](../06-plugins-mcp-and-security.md).

## ADR-007: Reuse Messaging for Mobile First; Decouple Voice from Execution

**Decision:** Start with mobile text/voice messages through official gateways, then validate native web/mobile and real-time voice. The voice frontend has no separate channel for authorizing side effects.

**Rationale:** Native entry points already exist. Building a new mobile chat/calling stack would distract from reliable end-to-end workflows. Stopping playback must be distinguished from canceling an external action.

**Trade-off:** Validate each target channel and device separately rather than claiming immediate availability on every platform. See [07](../07-mobile-and-voice.md).

## ADR-008: Single-Host Reliability Before Multiple Execution Environments

**Decision:** Default to one continuously online Hermes host. Use available native execution backends, introducing remote lease/fencing/reconnect contracts only when requirements are clear.

**Rationale:** A single-host lock and SQLite do not provide distributed consistency. A future architecture described in an article cannot be treated as an implemented MVP.

**Trade-off:** Failure of the single host temporarily makes the service unavailable. Service health, backups, and recovery targets must be explicit. See [08](../08-roadmap-and-acceptance.md).

## ADR-009: Deliver Worker Model Routing as a Native Plugin, Starting with Shadow Mode

**Decision:** Reuse DelegationProvider.route_task to choose among provider/model/effort combinations the user has configured and permitted. Keep the main agent's model and responsibilities unchanged. Start with local shadow mode, then enable bounded routing only after trusted context, privacy, budget, effort/fallback, and quality gates pass.

Installing/enabling the plugin does not automatically change the backend. Explicit owner selection defaults to shadow mode and requires an authorized static baseline. Configure a missing baseline first instead of guessing one from the parent route. Actual automatic selection requires a separate explicit setting.

**Rationale:** Task-level model routing needs neither a new API gateway nor a second brain. The current interface cannot carry a complete trusted RouteContext or atomic budget admission, so define minimal general-purpose host extensions rather than treating model parameters as authorization. Switchyard/LiteLLM/vLLM SR are optional references, not mandatory runtime dependencies.

**Trade-off:** Pin provider capabilities, record requested/effective effort, count classifier/reviewer/retry costs in the total, and cover paths not controlled by the native backend. If capabilities are unknown or hard limits cannot be demonstrated, remain in shadow mode or refuse the affected automatic selection. User pins, data-recipient scope, and cost limits take precedence over automatic optimization. See [11](../11-worker-model-routing.md).
