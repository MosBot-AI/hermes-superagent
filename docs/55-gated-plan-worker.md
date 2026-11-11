# Gated task planning worker integration

English | [简体中文](55-gated-plan-worker-zh.md)

The [current-pin candidate](101-current-host-text-worker.md) remains review-only. Frozen managed-worker configuration and isolated plugin-host proxies are unsupported; the candidate does not establish a usable Gateway planning worker. Later clean-host runtime-package acceptance does not imply worker-host installation or acceptance.

## Package integration, not deployment acceptance

This slice moves the reviewed text-only task consumer, durable ledger and presentation into the production package and connects them to the real plugin entrypoint. It does not install the plugin or adopt the host patch upstream. The supported clean host pin `2281116525106e3c109993ccb5dc74d02bfc1427` lacks the required API/capability and must register no planning worker.

`plan_worker` defaults to false. Registration requires the exact host contract `text_worker_contract == 'hermes.text-worker.v1'` and current canonical `llm.text_worker` consent, as well as the local task/conversation/model-tool prerequisites. A matching method name alone is not enough. Unsupported or unconsented hosts do not fall back to generic subagent launch, `ctx.llm`, another provider or another model.

The worker toolset is `personal_agent_plan_worker`. Required lifecycle methods must also be available. Unsupported or unconsented registration leaves ordinary plugin features available and reports the reason in status. If registration was skipped, enabling configuration or granting consent requires plugin reload. Every worker operation rechecks the current contract marker and consent. `plan_worker` requires `local_model_tools=true`, which in turn requires local tasks and local conversation.

## Explicit one-task authorization

The native `/personal-plan-worker` surface supports `allow TASK_UUID REVISION REQUEST_ID`, `revoke REQUEST_ID`, and the saved-request workbench `list`, `status KEY`, `draft KEY`, `stop KEY`. Native commands do not launch work. The `personal_task_plan_preview` tool consumes an explicit grant or retrieves its result through `launch`/`result` with the request ID. It cannot invent a grant, expand its task scope or execute a plan.

A grant expires after 120 seconds. The only provider/model is OpenCode Go `deepseek-v4.1-flash`, with an approved exact endpoint, up to 1024 output tokens and a 30-second request timeout. Authorization discloses that selected task data will be transmitted and ordinary model usage may be charged. The context allowlist is task ID, revision, title, state, project, due date, work status and bounded details. Dependency and native-progress metadata are not added implicitly. There are no worker tools or external task actions; the response is an untrusted planning draft, never task completion.

## Retained boundaries

The durable local claim is committed before a host request. Unknown or unobserved outcomes are not automatically retried or recovered by a new grant after restart. Never use a new key to retry an uncertain request. Revoking or stopping an unstarted request prevents its launch; this consumer does not provide in-flight cancellation or reverse usage charges.

The private ledger retains identifiers, hashes and observed terminal drafts, not the task snapshot text. It is bounded to 64 entries with no automatic cleanup or eviction, and terminal receipts must fit 32000 ASCII-serialized characters. Capacity needs trusted review, not deletion to enable duplicate submission. Already returned conversation content cannot be retracted. Model-tool result reads retain the exact approved route gate; explicit native saved-draft views go to the client, which may display or cache them, not automatically to a model.

Host profile binding, consent revocation, dedicated non-redirect transport, no environment-derived routing, fixed safe diagnostics and one-attempt behavior remain part of the [reviewed host proposal](48-task-worker-proposal.md). A contract marker is a trusted-host compatibility declaration, not a sandbox against malicious installed host code.

## Evidence and remaining gates

The integration is exercised only with an isolated patched host and offline MockTransport fixtures. It adds no live model, network, installation or Gateway acceptance claim. The earlier authorized synthetic provider attempt ended in `ConnectError` with no HTTP status or model response and no retry. The earlier official installation attempt was blocked by the unchanged scanner; no override or bypass is authorized by this package wiring.

Host adoption, authorized installation, genuine provider execution and complete runtime acceptance remain open. General worker orchestration, provider-side unknown-outcome reconciliation, budget/concurrency policy and tools-capable workers are not completed. See the [roadmap](08-roadmap-and-acceptance.md) and [experimental evidence](../experiments/text-worker/README.md).
