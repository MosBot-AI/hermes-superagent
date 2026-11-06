# Hermes Superagent Design Documents

English | [简体中文](README-zh.md)

Status: **Design baseline plus E0 contracts and an opt-in local CLI task inbox; the full personal-agent MVP is not yet implemented.** Verification date: 2026-11-06. Repository: `MosBot-AI/hermes-superagent`. See the [first development slice](12-foundation-progress.md) for current code and verification boundaries.

## Purpose

Extend Hermes into a long-lived personal agent for one user: one main agent understands projects, affairs, personal information, reminders, and communication, with a small number of constrained workers when needed. Reuse Hermes's native runtime, plugins, memory, tasks, scheduling, MCP, messaging, and voice rather than building a separate external agent.

## Reading order

1. [Product goals and scope](01-product-and-scope.md): users, capabilities, and explicit exclusions.
2. [DSH research and decisions](02-dsh-research-and-decisions.md): lessons from the source and reporting, with necessary corrections.
3. [Hermes-native architecture](03-native-architecture.md): boundaries between the host, plugin, domain state, and execution.
4. [Domain data and memory](04-domain-data-and-memory.md): projects, commitments, information, provenance, corrections, and forgetting.
5. [Proactivity, scheduling, and delivery](05-automation-and-delivery.md): reliable reminders, recovery, idempotency, and messages.
6. [Plugins, MCP, and security](06-plugins-mcp-and-security.md): open extensions, action authorization, identity, and revocation.
7. [Mobile and voice](07-mobile-and-voice.md): reuse existing entry points while preserving one agent's continuity.
8. [Roadmap and acceptance](08-roadmap-and-acceptance.md): dependency-ordered epics, work packages, and testable criteria.
9. [Upstream evidence and verification boundaries](09-upstream-evidence.md): pinned sources, links, and contracts needing further tests.
10. [Interfaces and end-to-end contracts](10-interface-contracts.md): proposed events, tools, adapters, and vertical flows.
11. [Worker model routing plugin](11-worker-model-routing.md): select authorized provider/model/effort routes, starting in shadow mode.
12. [First development slice](12-foundation-progress.md): the native read-only plugin, real contract tests, and remaining gates.
13. [Enforcement contracts and write-path inventory](13-enforcement-contracts.md): observed failure boundaries and still-blocked write paths.
14. [Client, authorization, and connector API contracts](14-client-api-contracts.md): proposed HTTP routes, canonical session transport, recovery, and explicit native-mobile blockers.
15. [Primary Bot binding and continuity](15-primary-bot-binding.md): proposed selection of an existing native Bot, verified roles, recovery and fencing.
16. [Opt-in local task inbox](16-local-task-inbox.md): implemented local CLI persistence, replay/revision checks and explicit limits.
17. [Local due dates and agenda](17-local-task-agenda.md): date semantics, bounded queries and transactional schema upgrades.
18. [Owner entry and read authorization](18-owner-entry-and-read-authorization.md): internal evaluator, native identity gaps and non-personal diagnostics.
19. [Unified voice session and provider contracts](19-unified-voice-provider-contracts.md): replaceable local/online speech interfaces, capabilities, interruption/recovery and safety gates.
20. [Offline voice contract simulator](20-voice-contract-simulator.md): synthetic frame/queue/recovery self-test and verified native provider limitations.
21. [Native voice IPC experiment](21-native-voice-ipc-experiment.md): reviewable host patch, actual consumer evidence and unintegrated release limits.
22. [Local task search](22-local-task-search.md): literal title/details matching, bounded pages and unchanged local-only gates.
23. [Host command-context experiment](23-host-command-context-experiment.md): review-only identity-observation patch and explicit integration gates.
24. [Local project groups](24-local-project-groups.md): task labels, exact filters, progress counts and schema-v3 migration.
25. [Architecture decision records](adr/README.md): reasons for the constraints.

## Keep three kinds of statements separate

- **Verified upstream capabilities:** found in pinned Hermes/DSH source or official documentation; this does not mean this repository implements them.
- **Project design:** domain models, policies, interfaces, and adapters still to build. Tool names, tables, and events in the design are proposed interfaces.
- **Unverified items:** need prototypes and integration tests, not invented upstream APIs.

Research baselines: Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4` and DSH Superagent `8c32a9dc5d72c033816c6a8110b37f40cf94fba4`. `main` changes continuously. Implementation must select a compatibility-tested release and record its exact SHA. These documents are not a permanent guarantee about all behavior in the latest release.

## Hard design constraints

1. One main identity and authorization principal; projects and sessions do not become separate personas.
2. Do not duplicate the Hermes agent loop, session store, cron scheduler, Kanban dispatcher, or OAuth stack.
3. External material is evidence, not authorization. A message arriving through the user's account does not make quoted instructions owner-authored.
4. Prompts, Mandates, MCP read-only hints, and Python plugin loading are not security isolation.
5. External sends, modifications, spending, and similar actions require a verifiable intent and renewed authorization checks before execution. Retries cannot expand permissions.
6. New user requests take priority over background work. Proactivity must be explainable, pausable, budgeted, quiet when appropriate, and deduplicated.
7. Runtime state, personal data, and credentials do not belong in this public repository. It contains designs, synthetic examples, and implementation code.

## Current deliverables

The design and project plan are established. The E0 foundation and opt-in local task inbox run in temporary test homes. Local CLI persistence is implemented; broader agent/channel/HTTP personal-data access is not. There is no production deployment or connection to real personal data, and no claim that authorization, reminders, or mobile voice are usable. GitHub Projects tracks development; native Hermes Projects/Kanban will represent runtime work. They are different systems.

E9 remains a design for the native worker model routing plugin. The user reviewed and selected the plugin approach, but it is not implemented. The main agent keeps its responsibilities. See [11](11-worker-model-routing.md) for constraints, host gaps, references, and acceptance criteria.
