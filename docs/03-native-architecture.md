# 03. Hermes-Native Architecture

English | [简体中文](03-native-architecture-zh.md)

## 1. Overall Approach

This repository delivers a **Hermes-native personal-agent plugin and supporting skills**. Hermes discovers, enables, and schedules the plugin, which registers tools, context, commands, and necessary UI extensions. Hermes owns the LLM loop, sessions, providers, tool calls, native approvals, gateway, cron, Kanban, MCP, and voice.

```text
User: Desktop / CLI / Mobile messaging / Voice
                  │ Verified identity + session routing
                  ▼
Hermes Gateway / Session / Agent Loop
                  │
      personal-agent native plugin
      ├─ Context: Projects, commitments, preferences, task summaries
      ├─ Domain: Work models, evidence, authorization, proposals
      ├─ Policy: Operation-level scope, approval binding, revocation checks
      ├─ Adapters: Project / Kanban / cron / MCP / delivery
      └─ Storage: Plugin-owned SQLite + attachment references
                  │
Hermes native tools / MCP / official platform adapters / restricted workers
                  │
External services or isolated execution environments
```

The main agent is the Hermes session itself, not another “persona” running inside the plugin. The plugin does not duplicate a separate agent loop either. Auxiliary LLM calls should prefer the official `ctx.llm` and its credential/budget rules; verify specific capabilities through E0 contract tests first.

The default route is a **profile-first, trusted single-user local MVP**: the main agent remains a native Hermes session, with no Bot selection or binding required. A profile partitions configuration/storage; it is not a human identity. Normal native CLI/TUI sessions are gateway-backed and use a LOCAL source. Host SessionAuthority enforces owner/operator session read/control, exact registered live source and admission; all already host-authorized owner/operator controllers share local data access. LOCAL does not prove physical locality, so only a trusted single-user local gateway/profile deployment is supported, not exposed, multiuser or remote-messaging deployments.

The opt-in `/personal-tasks` feature currently being implemented is a deterministic command entry point reusing schema-v3 TaskStore for add/list/search/projects/show/update/done/cancel/agenda; projects are labels only. It adds no listener, authentication service, remote connector, native Project or model task tool. Pending enrollment and read-admission cores remain unwired for a future verified remote-owner lane and do not block these explicit local commands.

Binding an existing native **Bot Mode Bot** to its verified profile and canonical Bot Chat is an optional future capability, not an implemented setting or local MVP prerequisite. Profile-scoped plugin loading does not prove owner identity or distinguish primary, ordinary and worker sessions. [15](15-primary-bot-binding.md) preserves owner-confirmed enrollment, cross-connection identity, session roles, recovery and migration gates without changing Hermes's default Bot.

## 2. Existing Capabilities and Added Value

| Layer | Reuse from Hermes | Added by this project | Explicit non-goals |
|---|---|---|---|
| Reasoning | Agent loop, providers, interruption, compression | Tools and working protocols for personal affairs | A second loop/provider stack |
| Sessions | SessionDB, gateway routes, profiles | Owner bindings and domain-object references | Replacing the transcript store |
| Projects | Projects/workspaces, Kanban boards | Domain support for non-code projects, commitments, and material | Directly changing the host database schema |
| Long-running tasks | Kanban dispatcher, goal contract | Task mapping, result acceptance, cross-task summaries | A custom worker supervisor |
| Short parallel work | `ctx.subagent_lifecycle` or native delegation | Minimal context and reduced permissions | Claiming handles can recover across restarts |
| Worker model selection | `DelegationProvider.route_task` and host provider/effort encoding | Optional native routing plugin, capability inventory, shadow mode/budgets/audit | A second agent controller or mandatory gateway; assuming all worker paths are covered |
| Scheduling | Cron, session heartbeat | User intent, budgets, stop and external-send policies | A parallel cron daemon |
| Memory | MEMORY/USER, session search, a single external provider | Structured facts, sources, corrections, permission-aware retrieval | Activating multiple memory providers simultaneously by default |
| Connections | MCP, OAuth, plugin catalog | Connector risk inventory and minimal tool sets | A third OAuth/token store |
| Entry points | Official messaging adapters, web/desktop, STT/TTS | Personal overview, acceptance testing for mobile flows | A custom mobile chat and calling stack in the first version |

## 3. Plugin Module Boundaries (Proposed)

```text
plugin.yaml                     # Manifest, dependencies, configuration, capability declarations
__init__.py                     # register(ctx), thin registration layer
personal_agent/
  domain/                      # Project/commitment/fact/automation/approval objects
  services/                    # Domain actions and transaction boundaries
  policy/                      # Identity, authorization, action hashes, revocation revisions
  adapters/                    # Calls only verified public Hermes extension surfaces
  storage/                     # Migrations, repositories, outbox
  tools/                       # Small, explicit tool schemas and handlers
  context/                     # Bounded dynamic context with sources
  observability/               # Redacted events, metrics, diagnostics
skills/                        # inbox-review, project-review, weekly-review, etc.
tests/                         # Unit, contract, recovery, security, channel tests
```

This is a proposed target directory structure, not the current module layout. Current scoped implementations include the [foundation](12-foundation-progress.md), [local inbox](16-local-task-inbox.md), [internal read evaluator](18-owner-entry-and-read-authorization.md), and [native planning template](25-native-planning-blueprint.md). They do not complete the domain services or authorization gates. Start with one plugin package to avoid unnecessary microservices. Split out an optional package only if an independent memory provider becomes necessary, so installing the basic functionality does not replace the user's current provider.

## 4. Single Authorities for Data and Execution

1. Hermes is authoritative for conversation and model-execution state.
2. Native Kanban/run state is authoritative for workers; the domain `task` stores references and business acceptance, without maintaining a competing worker lifecycle.
3. Native cron/heartbeat is authoritative for scheduled triggers; domain automations store goals and policies without independently recalculating and dispatching the same occurrence.
4. The plugin database is authoritative for personal facts, commitments, authorization proposals, source mappings, and the external-action ledger.
5. External receipts/read-back determine whether an external action succeeded, not “the model says it sent it.”

Do not pretend that SQLite and remote systems share a global transaction. A domain transaction first writes the intent and outbox entry, then hands execution to an adapter and records the receipt afterward. An unknown remote result enters `unknown` and is reconciled, rather than immediately resent.

## 5. Rules for Using Hermes Extension Points

- Register tools, hooks, commands, and skills through `register(ctx)`; use the official `plugin_data_dir` / `plugin_db` for runtime data, not the installation directory.
- The general compatibility boundary is officially documented ctx/ABC/event behavior, not an assumption that arbitrary internal Python imports remain stable forever.
- `pre_llm_call` injects only bounded, relevant, sourced data. If it fails, the main conversation may continue, but restricted writes must not be allowed as a consequence.
- In the pinned source reviewed here, `pre_tool_call` is **fail-closed** for callback exceptions, timeouts, and still-running callbacks. Failures in `tool_request` and `tool_execution` middleware may allow downstream execution to continue, so they cannot serve as the sole permission boundary.
- Hook callbacks do not perform external side effects. Domain handlers that produce side effects recheck permissions, revisions, idempotency, and approvals themselves.
- `ctx.subagent_lifecycle` is available only during an active parent turn; after process exit, `reconnect` does not restore execution. Use Kanban for long-running work.
- Prefer integrating a worker-routing plugin through the `delegate_task` backend, leaving the main agent's model unchanged. The public lifecycle, initial Kanban workers, cron, and auxiliary calls do not automatically pass through that backend; current route_task lacks a complete trusted RouteContext and atomic budget admission. See [11](11-worker-model-routing.md) for the minimum general extensions required, effort mapping, and activation gates.
- Native `desktop_project` is currently a GUI tool set; do not assume it is visible to mobile sessions by default. Project operations across entry points require E0 verification of an available adapter path.
- Do not directly import `hermes_cli.projects_db` / `kanban_db` to modify data or write directly to `jobs.json` / SessionDB. If a public write entry point is missing, first verify official command/dispatch support; propose the smallest general upstream extension only when the required seam is genuinely absent.

## 6. Context Assembly

For each turn, give the main agent only identity and current scope, a current project summary, relevant commitments, a few facts, active-task changes, and pending approvals. Retrieve long documents on demand. Label each fragment with its source, time, and trust level; separate retrieved external text from user commands.

Begin with a configurable context-budget cap and tune it through tests on actual models. Do not place all personal data in every request just to “remember everything.” Profiles do not share context by default. Workers receive only a handoff snapshot, not the entire user profile and complete chat history.

## 7. Deployment and Upgrades

The minimum local MVP deployment is a trusted single-user Hermes host, one profile and a plugin data directory, using native gateway-backed CLI/TUI. It requires neither continuous uptime, a mobile channel nor Bot enrollment. Future reminders and remote entry points require their own availability and identity gates. Run untrusted code in a restricted environment supported by Hermes, and separately verify filesystem/network/credential isolation; process isolation alone is not a sandbox.

The version lock records the Hermes SHA, plugin version, schema version, enabled connectors, and test results. Before upgrading, back up the plugin database and configuration, run contract and recovery tests, then enable the upgrade on a limited basis. Do not automatically upgrade to an unverified `main` and claim compatibility. Rolling back code is not the same as rolling back data; migrations must state their reversibility and recovery plan.
