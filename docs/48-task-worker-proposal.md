# Task-to-worker delegation proposal

English | [简体中文](48-task-worker-proposal-zh.md)

## What advanced

The [review-only text-worker bundle](../experiments/text-worker/README.md) connects an explicitly approved local task revision to one native-host text request and a lifecycle result. It includes a proposed host API, exact-route opt-in, guarded one-attempt execution, a dedicated no-redirect client, durable single-claim/draft receipts, a concrete experimental command/model consumer and reproducible offline tests. It is not loaded by the production plugin.

The consumer's fixed flow is task selection → short-lived one-task grant → real primary turn admission → immutable task snapshot → text worker → draft with revision/staleness metadata. It never marks a task complete or interprets returned instructions as authority. There is no general worker tool execution.

## Operator-facing workbench

The native `/personal-plan-worker` command now supports `list [--after KEY]`, `status KEY`, `draft KEY` and `stop KEY`. Output defaults to readable text; leading `--json` preserves structured responses. Lists show ten scoped metadata records at a time, never task text or draft content. `receipt_saved` means a worker receipt exists, not that the task was performed.

`draft` displays an already saved terminal receipt directly through the audited native command output path, with current revision/staleness information and escaped untrusted text. It does not poll a live worker or send a model request. This explicit operator read is separate from the model tool, whose exact-route disclosure check is unchanged. Native clients can display/cache output; LOCAL does not prove a physical human is the caller.

`stop` revokes only an unstarted grant. For an admitted/unknown request, it reports that cancellation is unavailable and preserves the consumed request. It neither fabricates a parent binding nor creates a new request. The workbench does not recover lost results, remove retained keys or make the proposal a supported installed feature.

## Why this is a separate experiment

The pinned public lifecycle's general child launch can inherit tools, saved routes, MCP toolsets, recursive delegation and workspace behavior. An empty list or a prompt saying “do not use tools” cannot provide the needed bound. Changing those defaults globally would also change legitimate host behavior.

The proposal adds a distinct opt-in text-only method instead. Its narrow request does not construct a full agent, inherit parent conversation or enter the full child workspace/auxiliary workflow. The [bundle](../experiments/text-worker/README.md) explains the enforced limits, synthetic evidence and unverified provider boundaries. The official compatibility pin, ordinary model-tool surface and readiness claims remain unchanged.

## Restart and client behavior

The host proposal no longer borrows the parent HTTP client. It builds an isolated no-redirect, no-environment-proxy client for the exact approved route, with no SDK-constructor credential discovery or shared-client mutation. The existing host payload builder, request/execution middleware, lifecycle and response normalization remain in the path. This is still a host patch requiring formal adoption, not an installed integration.

The consumer records its single-use claim before dispatch in a separate private SQLite ledger. A crash or lost acknowledgement cannot make that request eligible again. Claims and both live/saved drafts are bound to the original exact route fingerprint, which is checked before fresh tool disclosure. This does not retract existing conversation history after a model switch. Observed terminal drafts are saved and can be read after reload; an unobserved result remains unknown, not inferred successful or retried. Pending authorization belongs to the original consumer instance. A new instance cannot silently inherit it. The bounded ledger retains tombstones and refuses new grants at capacity.

## Next acceptance

Upstream adoption and real authorized OpenCode Go `deepseek-v4.1-flash` validation are still required. Production-grade unknown-outcome reconciliation, durable provider-side execution identity and cost/concurrency controls must precede ongoing autonomous worker orchestration. The local ledger is not a provider execution transaction or a guarantee of exactly-once remote delivery. General tool-using workers need separately enforceable permissions. Gateway transport and automatic memory gates remain open.

See [atomic project plans](47-atomic-project-plans.md), [worker routing](11-worker-model-routing.md) and [roadmap](08-roadmap-and-acceptance.md). This prototype advances feasibility; it does not complete those acceptance criteria.
