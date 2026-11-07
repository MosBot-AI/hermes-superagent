# Task-to-worker delegation proposal

English | [简体中文](48-task-worker-proposal-zh.md)

## What advanced

The [review-only text-worker bundle](../experiments/text-worker/README.md) connects an explicitly approved local task revision to one native-host text request and a lifecycle result. It includes a proposed host API, exact-route opt-in, guarded one-attempt execution, a concrete experimental command/model consumer and reproducible offline tests. It is not loaded by the production plugin.

The consumer's fixed flow is task selection → short-lived one-task grant → real primary turn admission → immutable task snapshot → text worker → draft with revision/staleness metadata. It never marks a task complete or interprets returned instructions as authority. There is no general worker tool execution.

## Why this is a separate experiment

The pinned public lifecycle's general child launch can inherit tools, saved routes, MCP toolsets, recursive delegation and workspace behavior. An empty list or a prompt saying “do not use tools” cannot provide the needed bound. Changing those defaults globally would also change legitimate host behavior.

The proposal adds a distinct opt-in text-only method instead. Its narrow request does not construct a full agent, inherit parent conversation or enter the full child workspace/auxiliary workflow. The [bundle](../experiments/text-worker/README.md) explains the enforced limits, synthetic evidence and unverified provider boundaries. The official compatibility pin, ordinary model-tool surface and readiness claims remain unchanged.

## Next acceptance

Upstream adoption and real authorized OpenCode Go `deepseek-v4.1-flash` validation are still required. Durable execution receipts, restart/unknown-outcome reconciliation and cost/concurrency controls must precede ongoing autonomous worker orchestration. General tool-using workers need separately enforceable permissions. Gateway transport and automatic memory gates remain open.

See [atomic project plans](47-atomic-project-plans.md), [worker routing](11-worker-model-routing.md) and [roadmap](08-roadmap-and-acceptance.md). This prototype advances feasibility; it does not complete those acceptance criteria.
