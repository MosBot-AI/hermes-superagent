# 01. Product Goals and Scope

English | [简体中文](01-product-and-scope-zh.md)

## 1. What the User Should Get

Users do not want to maintain a fleet of agents. They want an assistant that understands them, remembers progress, and keeps moving their affairs forward. The main agent owns cross-project priorities, context, and external communication; project threads and workers are internal means of getting work done. The preferred deployment is a personal, self-hosted Hermes instance, with support for a small number of independent profiles later. Building a multi-tenant SaaS is outside the first phase.

The core loop is: **receive the request → clarify the goal and boundaries → persist the work → gather evidence → execute authorized actions → record actual results → deliver → follow up when necessary**. Answering once and losing subsequent commitments does not meet the personal-agent goal.

The approved first step is a **profile-first, trusted single-user local MVP**, without Bot binding. A profile is a storage/configuration partition, not a human identity. Start with durable tasks and project labels in native Hermes local conversations; remote authorization, cross-device continuity and a selected Primary Bot remain optional future capabilities. The scenarios and objects below describe the longer-term target, not implemented features.

## 2. Core User Scenarios

| Scenario | Example input | Expected behavior | Completion evidence |
|---|---|---|---|
| Manage projects | “Plan the next steps for project A and watch its blockers” | Link the existing project, distinguish actions from reference material, and produce tasks with owners, dependencies, and acceptance criteria | Visible tasks and sources; evidence for completed items |
| Manage commitments | “I promised to send them a proposal on Friday” | Record the commitment and time zone; prepare material when needed; authorize external sending separately | Commitment status, deadline, and delivery outcome |
| Manage personal information | “Use Chinese for reports like this from now on, and keep them as short as possible” | Save the explicit preference and its scope; support viewing, correcting, and deleting it | Correct application to the next relevant task, without overgeneralizing globally |
| Remind/monitor | “Remind me at nine tomorrow morning; tell me when you find a change” | Distinguish a one-time reminder from conditional monitoring; establish a durable job, expiry, and destination | Inspectable schedule, run history, and delivery status |
| Connect plugins | “Connect my calendar and project tools” | Identify required data, account, scopes, and operation permissions; prefer existing Hermes MCP/plugin capabilities | Healthy connections; visible, revocable read/write permissions |
| Continue on mobile | “How is that project from earlier going?” | Verify the owner's identity, locate the corresponding project and conversation, and keep group-chat content out of private memory | The same task state, sources, and permissions |
| Interact by voice | “Tell me what I need to do today; postpone the second item” | Use voice for interaction and domain tools for actual changes; ask only the smallest necessary question when ambiguous | Structured confirmation and the actual updated state |

These are synthetic scenarios only. They do not constitute pre-authorization to send data to third parties or call services.

## 3. Product Objects

- **Person/Owner**: The sole individual authorized to grant permission, together with their verified channel bindings.
- **Project**: A long-lived work context with goals, scope, material, and related tasks; it may link to a native Hermes Project.
- **Commitment**: A promise made by the user or another person, including an owner, deadline, dependencies, and the latest evidence.
- **Task**: An actionable work item; tasks requiring durable execution map to Hermes Kanban cards.
- **Fact/Preference**: Personal information with a source and scope, kept separate from task state rather than mixed into one memory store.
- **Automation**: A combination of trigger, observation/action scope, destination, budget, and stop conditions, mapped to native cron/heartbeat.
- **ActionIntent/Approval**: A precise action and its authorization evidence. “Work on the project” must not be interpreted as unlimited permission to send externally or spend money.
- **Artifact/Delivery**: An output and its recipients, external references, accessibility, and sending outcome.

## 4. Strategy for One or a Few Main Agents

Use one `personal` main profile by default. Start research, coding, and organizing workers temporarily for each task and release them afterward, rather than creating a long-lived “manager” for every project. Add a second main profile only when data, credentials, or work identities genuinely require isolation, such as personal versus company work.

The main agent retains control of priorities and user communication. Workers receive a minimal task description, necessary facts, and a narrow tool set. They cannot expand scope, change lasting preferences, establish permanent authorization, or duplicate reports to the user. Use native durable Kanban for long-running execution; do not treat in-memory subagent handles as a reliable task queue.

## 5. End-to-End Flows Required in the First Version

1. Explicitly enable native LOCAL conversation commands `/personal-tasks` in a trusted single-user local gateway/profile deployment, reusing schema-v3 TaskStore.
2. Support add/list/search/projects/show/update/done/cancel/agenda; projects are labels only, with no native Project entities or dispatch yet.
3. Validate input, revisions and atomic receipts, and verify persistence across restarts and failure paths; agenda is not a reminder.
4. Rely on host SessionAuthority checks for owner/operator session read/control, exact registered live source and admission. All already host-authorized owner/operator controllers share local data access; a LOCAL label does not prove physical locality.
5. Add no listener, authentication service or remote connector; exposed, multiuser and remote-messaging deployments are unsupported. Pending enrollment and read-admission cores remain for a future verified remote-owner lane, not prerequisites for these explicit local commands.
6. Add validated session-scoped model task tools next under E6.9; no natural-language model task tool exists now, and none is automatically enabled.
7. Add mobile, Bot binding, reminders/monitoring, MCP writes, workers and voice in stages after their own gates pass; they do not block the local MVP.

## 6. Non-Goals

- Do not build another long-running agent runtime or let an external orchestration framework take control of Hermes.
- Do not automatically turn every email or message into a task, or default to continuous reading or recording.
- Do not build a general-purpose plugin marketplace, mobile operating-system assistant, telephone dialing, real-time calling infrastructure, or all-purpose knowledge graph in the first version.
- Do not treat a model's self-check as a permission boundary or promise end-to-end exactly-once behavior across external systems.
- Do not give every worker arbitrary terminal, browser, unknown MCP, or sensitive-credential access by default.
- Do not validate the first version with high-impact scenarios such as automatic purchasing, financial trading, or medical decisions.

## 7. Measurement

Acceptance primarily asks whether work actually reaches completion: missed commitments; late, duplicate, or misrouted reminders; unapproved side effects; effective memory corrections; consistent state after recovery; user-interruption latency; and cost per completed task. Subjective “intelligence” scores can supplement but cannot replace safety and reliability tests. See [08](08-roadmap-and-acceptance.md) for specific SLOs and tests.
