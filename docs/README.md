# Hermes Superagent Design Documents

English | [简体中文](README-zh.md)

Status: **Design baseline, with E0 read-only plugin foundation development started; product capabilities are not yet implemented.** Verification date: 2026-11-06. Repository: `MosBot-AI/hermes-superagent`. See the [first development slice](12-foundation-progress.md) for current code and verification boundaries.

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
15. [Architecture decision records](adr/README.md): reasons for the constraints.

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

The design and project plan are established. The E0 native read-only plugin foundation is now being built and loaded in temporary test homes. There is no production deployment or connection to real personal data, and no claim that authorization, reminders, or mobile voice are usable. GitHub Projects tracks development; native Hermes Projects/Kanban will represent runtime work. They are different systems.

E9 remains a design for the native worker model routing plugin. The user reviewed and selected the plugin approach, but it is not implemented. The main agent keeps its responsibilities. See [11](11-worker-model-routing.md) for constraints, host gaps, references, and acceptance criteria.
