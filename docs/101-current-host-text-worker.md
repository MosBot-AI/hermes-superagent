# Current-host text-worker preparation

English | [简体中文](101-current-host-text-worker-zh.md)

## Scope

Issue [#143](https://github.com/MosBot-AI/hermes-superagent/issues/143) prepares the existing no-tool text-worker proposal for the supported Hermes commit `2281116525106e3c109993ccb5dc74d02bfc1427`. It does not adopt or install a modified host. The clean host still has no `hermes.text-worker.v1` contract, and the production plugin still registers no planner there.

The original proposal targeted `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. Its patch did not apply to the current pin in `hermes_cli/middleware.py` and `hermes_cli/plugins.py`. More importantly, current configuration and execution semantics require fresh security checks. A successful patch application alone would not qualify this port.

The candidate remains a trusted local, in-process, single-request planning service. “Text-only” means no tools or full child agent, not local inference. The separately authorized request sends the selected task snapshot to OpenCode Go `deepseek-v4.1-flash`; normal provider usage may cost money. No model request is part of this preparation slice.

## Current-host boundaries

- `PluginContext` now lives in `plugins_context.py`. Its lifecycle property must use the originating plugin identity and profile, rather than shadowing the profile-bound capability mixin with the old general lifecycle property.
- Middleware retains current narrow-signature dispatch and warning behavior. The text path additionally rejects repeated downstream execution, including a violation swallowed by middleware. Ordinary callers retain their existing behavior.
- Current configuration may return `FailedConfigRead` with last-known-good settings. Such a mapping is not current consent. Capability and route admission must refuse it, rather than reuse an old grant.
- `ConfigBackendUnavailable` is a known `SystemExit` subtype. A backend failure must refuse admission or leave a truthful failed terminal result if execution was already admitted. This does not make a failed or unknown request retryable, and does not swallow arbitrary process-exit conditions.
- Managed workers intentionally bind frozen session configuration before importing runtime code. Calling the ordinary configuration loader again does not observe later revocation. This candidate refuses frozen-worker contexts instead of treating that snapshot as live authority.
- Isolated plugin-host proxies do not expose the real read-only contract property required by the production consumer. They remain unsupported. Do not weaken the property check or change a user's isolation setting to make the experiment appear usable.

The exact route, profile binding, separate consent, bounded immutable payload, no-redirect/no-environment transport, one-attempt guard and durable local claim remain required. The service does not inherit tools, parent history, MCP, recursive delegation, a workspace or auxiliary model work. A returned draft is untrusted data, not evidence of task completion.

The unchanged native dispatcher can itself read configuration before entering the consumer, for example while resolving a pre-tool hook timeout. A backend outage there can abort dispatch before the candidate handles it. This slice does not claim a normalized error response across every host entry point and does not add a global `SystemExit` catch. No worker request is admitted by that earlier failure.

## Why a passing candidate is not Gateway adoption

Normal Gateway-backed execution can use managed workers. Refusing their frozen configuration is an intentional safety boundary, not a completed integration. Supported use in that mode needs a host-owned current authorization path with defined admission/revocation ordering and process-bound execution identity. Re-reading the same worker snapshot, reading around the host's configuration policy, or switching to unrestricted general delegation is not that contract.

The general lifecycle is not a fallback: an empty toolset can mean inheritance; MCP and delegation tools can be added; child initialization can inherit history-related and memory behavior. The project retains executable counterexamples in `tests/contracts/test_worker_routing_contracts.py`.

## Adoption choices and milestone dependencies

Both deployment choices need an explicitly reviewed host release and genuine exact-route acceptance:

1. **Upstream adoption.** Prepare the current-pin implementation and security rationale, then obtain authorization before submitting it to NousResearch. Upstream review can shape the public API and reduce long-term divergence, but acceptance and release timing are external dependencies. Preparation in this repository is not an upstream submission.
2. **A maintained host distribution.** Explicitly choose an owner for the fork or patch series, version/release identity, security updates, compatibility rebases, packaging, rollback and support. This offers control over delivery but creates continuing host-maintenance responsibility. A disposable patched checkout is not such a distribution, and this issue does not choose it for the user.

Either choice still requires the managed-worker/isolated-plugin contracts appropriate to the intended deployment, supported installation and consent, and live provider evidence. A host marker only declares compatibility of trusted code; it is not a sandbox against malicious code in the same process.

This is a direct E3.3 prerequisite. Full E3.3/E3.5 remains open for durable execution identity, provider-side unknown-outcome reconciliation, budget/concurrency policy and truthful cancellation. Text planning does not provide general tools-capable workers. E9 bounded routing depends on its own trusted-context and budget gates and does not become ready through this port.

E4 reminders separately need native creation/reconciliation and delivery ownership. E2.8 checkpoint/source proposals have different native transaction and retention contracts. Neither is automatically satisfied by adopting this worker API. Existing explicit local task, handoff and memory workflows continue on the unchanged clean pin.

## Evidence and retained limits

The [artifact manifest](../experiments/text-worker/manifest.json) and [runner](../experiments/text-worker/run_tests.py) bind the current patch, sources and selected offline tests to the exact host. Historical old-pin test counts, the earlier `ConnectError` provider attempt and the earlier repository-install scanner refusal remain historical evidence, not results for this candidate. Later clean-host packaged Gateway acceptance, including [#142](https://github.com/MosBot-AI/hermes-superagent/pull/142), did not install this worker proposal.

Selected host/consumer and cold-package tests are not the full upstream suite, real Gateway worker acceptance or live provider acceptance. Test HTTP transports use synthetic data; no personal profile, credential, provider request or previously denied socket operation is needed. Independent review and exact-source CI evidence are linked from #143 and its PR before completion.

The ledger still retains at most 64 records, does not evict tombstones and does not recover an unobserved provider result. No diagnostic, restart or new key authorizes retrying an uncertain request. Configuration ABA without a monotonic authority revision, post-admission changes, past conversation disclosure and provider billing remain explicit limitations.
