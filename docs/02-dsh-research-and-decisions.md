# 02. DSH Superagent: Source Code, Reporting, and Design Decisions

English | [简体中文](02-dsh-research-and-decisions-zh.md)

## 1. Research Subject and Strength of Evidence

This review examines [deepseek-ai/dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype) under the official organization, pinned to commit [8c32a9dc5d72c033816c6a8110b37f40cf94fba4](https://github.com/deepseek-ai/dsh-superagent-prototype/commit/8c32a9dc5d72c033816c6a8110b37f40cf94fba4), dated 2026-10-31T12:06:31Z. This was the only public commit returned by the query performed for this review, and releases returned an empty array. The tag list was not verified, so this does not establish that there are no tags.

The README explicitly describes it as a research prototype, not an official DeepSeek product. The public version has been adapted and is not identical to the internal version or design article; some directions in the article are unimplemented. This document distinguishes “visible in source,” “proposed in the article,” and “recommended by this project,” rather than treating popularity or media judgments as evidence of stability. [README](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/README.md)

The package is version 0.1.0, uses TypeScript ESM, and depends on DSH/Cordis interfaces. It is not an independent library that becomes a native plugin simply by replacing its executor with Hermes. Reused code must retain the MIT notice. This proposal prioritizes learning from the domain design rather than porting the entire runtime. [package.json](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/package.json), [LICENSE](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/LICENSE)

## 2. The Problem DSH Actually Solves

It primarily coordinates a team's work around one code repository, rather than providing a complete personal assistant. Its core pipeline is `Source → Trigger → Thread → Eval → Mandate → Ticket → Assignment → Executor`, with Channel handling the write side of replies. A Trigger is a deduplicated event, a Thread is a serial evaluation/discussion unit, a Ticket is an authorized unit of work, an Assignment binds one execution, and a Mandate is an immutable authorization snapshot. Tasks do not disappear when a model session ends. [Domain model](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/001-domain.md#L25-L60), [Engine](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/engine.ts)

Its most valuable lesson for Hermes is: **tasks, evidence, authorization, execution attempts, and message delivery must be recoverable objects, not just chat context.** However, Hermes already has foundations such as Kanban, cron, and sessions, so the project should add domain mappings rather than copy DSH's second execution system.

## 3. Mechanisms Worth Learning From Directly

### 3.1 Deterministic Admission Before Model-Based Semantic Judgment

Policy first classifies events as explicit/inferred/inadmissible using trusted actors, bot flags, direct addressing, scope, and rules. Accepting inferred work requires auto mode and a matching enabled rule; the default observe mode records only would_accept. Rules, mode, and Source policy form a version hash, and stale evaluations cannot continue to commit. The model should not decide for itself whether it has permission. [policy.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/policy.ts#L111-L242)

**Adoption**: Personal-agent has two gates: IntakeGate and ActionGate. The former determines whether an event becomes a candidate work item; the latter determines whether each specific side effect is authorized. Start in observe mode, then enable limited automatic behavior one category at a time.

### 3.2 Follow-Up Events Go Directly to the Task That Owns Them

Subscriptions let subsequent messages in the same Thread reach the worker directly without every message passing through a Router LLM. A context-only subscription provides context but grants no authority to make new requests and cannot wake a finished task. Out-of-scope events are handed back for a new evaluation. [intake.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/intake.ts), [Authorization documentation](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/002-authorization.md)

**Adoption**: Reduce duplicate task creation through explicit source/thread/task associations; an association supplies context only. Owner follow-ups may continue while authorization remains valid. Third-party follow-ups can only provide evidence or trigger already-authorized conditions, not expand a grant.

### 3.3 Transactions Write State; Durable Effects Execute External Actions

Core is a synchronous, I/O-free domain engine; state changes and effect enqueueing share a transaction. SQLite WAL, a single-process state-directory lock, effect kind/key deduplication, and generations prevent an old attempt from deleting a new payload. Later is distinct from failure and does not increase the failure count. [Store](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/store.ts#L50-L160), [Effects](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/effects.ts#L60-L145)

**Adoption**: The plugin's own domain state and side-effect outbox share a transaction. Reuse Hermes-owned cron, Kanban, and delivery paths directly, without duplicate dispatchers or senders.

### 3.4 Replies Are Business Objects

DSH distinguishes acknowledgement, answer, result, and attention. Results return to the task's origin, while answers return to the message that asked the question. The outbox saves receipts; GitHub comments are checked using stable markers, and Feishu uses message.id for idempotency. Permanently unreachable deliveries are marked dropped; “queued” must not be treated as “sent.” [Replies](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/replies.ts), [Outbox](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/outbox.ts), [GitHub channel](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/sources/github-channel.ts), [Feishu channel](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/sources/feishu-channel.ts)

**Adoption**: Distinguish question, approval, blocked, result, delivery_failed, and unknown outcome. Show people “why you are needed” and “what happens next,” while keeping the complete trace in an inspectable audit trail.

### 3.5 Put Human Attention Before Throughput

The prototype defaults to maxWorkers=3 and reserves an additional slot for human follow-up/status requests. Background jobs and subagents still consume actual runtime capacity instead of pretending to be idle. The executor has rules for moving foreground work into the background, bounded waiting, cleanup, and recovery. [Execution documentation](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/003-execution.md#L23-L61)

**Adoption**: Use a small number of workers, reserved foreground capacity, priority for user interruptions, and real backpressure. These numbers are prototype choices, not Hermes performance guarantees to copy.

### 3.6 Referenced Context, Not an Unlimited Prompt

Cards carry summaries and expandable resources. Resource reads are restricted to objects related to the current Ticket/Thread and have pagination/text limits. Visible IDs should resolve to their sources. However, resource API restrictions are not OS isolation. [Resource interface](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/007-architecture.md#L534-L595), [resources.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/resources.ts)

**Adoption**: Expand project summaries, sources, and artifact-reference graphs on demand. Manage long-term user facts through Hermes memory and a domain fact store, rather than placing all task history in USER.md.

## 4. Safety and Product Assumptions That Must Change

| Prototype boundary | Facts and risks | Hermes personal-agent decision |
|---|---|---|
| Mandate | Admission/recovery validation, worker tool allowlists, and a Ticket ended guard exist; free-text scope is not deterministic validation of every command/external send | Add operation-level authorization, payload/recipient binding, and revalidation before execution |
| Execution environment | Sessions use `danger-full-access`; the same OS user is used; CLI wrappers do not isolate files and networks | Minimize exposure of personal sensitive data and credentials; put untrusted execution in a verified isolated environment |
| Identity | No cross-Source identity mapping | Minimal Owner + VerifiedAccountBinding; display names do not authorize actions |
| Recovery | Human follow-ups in the original thread may attempt to recover an ended Ticket; scope judgment depends on the worker | Third-party messages cannot automatically restore permission for external operations |
| Policy changes | Live Tickets are notified without immediate revocation; pause need not interrupt the current turn | Separate soft pause from hard revocation; check the latest policy revision before committing an action |
| Idempotency | A reply outbox mechanism does not make every action in a worker's unrestricted shell exactly-once | Define idempotency/receipt/unknown/reconcile behavior for each effect category |
| Project assumptions | GitHub/Feishu/PR-specific dependencies remain | Unify artifact/receipt/result without disguising personal affairs as PRs |
| Memory | `core/memory.ts` provides InMemoryRepositories for tests, not long-term personal memory | Reuse Hermes memory and add provenance, correction, forgetting, and scope |

Execution-environment evidence: [sessions.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/sessions.ts#L137-L154), [Deployment permissions](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/006-deployment.md#L13-L19), [mandateInstructions](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/executor/dsh.ts#L88-L95). For identity/recovery, see the [Domain model](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/001-domain.md#L39-L59) and [Authorization documentation](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/002-authorization.md). For revocation, see [policyEffects/revalidate](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/policy.ts#L144-L241). For other boundaries, see [Recovery rules](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/003-execution.md#L144-L152), [Source-specific dependencies](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/007-architecture.md#L275-L287), and [core/memory.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/memory.ts).

These are design differences required when moving a research prototype into a personal-data setting, not exploit conclusions unsupported by runtime verification.

## 5. Cross-Checking Articles and News

- The official Chinese article is linked through a [WeChat public-account article](https://mp.weixin.qq.com/s/zoS7GlReWPhfCjENGxXCdg), whose body could not be read during this review. The [DeepSeek Harness X link](https://x.com/DeepSeekHarness/status/2116857257245987236) returned 403; access restrictions were not bypassed.
- An accessible attributed republication is available from [ChainCatcher](https://www.chaincatcher.com/article/2300676). It presents design discussions of Router/Worker, Inline/Spill, multi-hop recall, asynchronous interaction, separation of compute/state/environment, and an independent Watchdog. The republication is not an official site; implementation claims remain grounded in the pinned source.
- [The Next Web, 2026-11-01](https://thenextweb.com/news/deepseek-super-agent-open-source-coding-agent) reports its experimental nature, single-repository scope, optional Feishu support, and reduced coordination burden, while also explaining that it is not an official product.
- The readable portion of [South China Morning Post, 2026-11-01](https://www.scmp.com/tech/article/3372884/deepseek-unveils-ai-super-agent-coding-race-openai-anthropic) describes its goal of reducing manual coordination of multiple agents. No technical details were inferred from the unreadable body.

The article's scheduling experiments include synthetic messages and time-consuming mock tools. They are not benchmarks for real coding quality, personal-assistant effectiveness, or safety, and do not establish that “multiple agents are inherently cheaper.” The prototype does provide deployment guidance for startup recovery, health checks, and a service that uses an independent profile to run checks hourly, so it would be inaccurate to say broadly that it has “no watchdog.” However, the full architecture described in the article, including a general semantic Watchdog, multi-environment stateless compute, and an endpoint daemon, has not been demonstrated to be implemented. [Deployment checks](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/006-deployment.md#L133-L141)

## 6. Final Decision

Learn from DSH's separation of tasks and execution, direct event routing, transactional effects, structured attention, and referenced context. Add the personal domain, owner identity, operation-level authorization, immediate revocation, memory governance, and notification budgets on top of Hermes-native foundations. In the first phase, complete a reliable single-host end-to-end loop; do not port the DSH/Cordis runtime or copy its full-access, single-repository team deployment assumptions.

This was a source-code and literature review; neither DSH nor Hermes tests were run. DSH's [test directory](https://github.com/deepseek-ai/dsh-superagent-prototype/tree/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/tests) may inform test-case organization, but it is not evidence that this project's tests have passed.
