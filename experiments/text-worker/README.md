# Review-only task planning worker

English | [简体中文](README-zh.md)

## Status

This is an isolated host proposal plus a concrete experimental task consumer. It is **not installed, enabled, imported by the production plugin, submitted upstream or deployed**. The supported host pin remains `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. Do not apply this patch to an installed host or weaken plugin isolation to try it.

The [manifest](manifest.json) records the exact patch, source hashes, selected verification and limitations. The [host patch](text-worker-prototype.patch) retains the upstream [MIT license](LICENSE.hermes-agent). Distribution on this project's feature branch is not an upstream release.

## The narrow useful flow

The [experimental consumer](consumer.py) connects real local tasks to the proposed `ctx.subagent_lifecycle.launch_text` API:

1. An authorized native LOCAL session controller issues `/personal-plan-worker allow TASK_UUID REVISION REQUEST_ID`. This approves one selected active task snapshot, for at most 120 seconds, to OpenCode Go `deepseek-v4.1-flash`, with 1024 output tokens and a 30-second request timeout. Normal model usage can cost money. The command does not make a request.
2. During a real primary session turn, `personal_task_plan_preview` can consume that exact grant. Its only fields are `action` and `request_id`. The model cannot supply a goal, task, context, provider, model or permission. A changed task revision, expired/revoked grant, different session/route/profile or child turn refuses before launch.
3. The host admits a bounded, one-request text worker and returns its ordinary lifecycle handle. Only the consumer keeps that capability. Repeated launch calls inspect the same handle; an exception leaves an uncertain-outcome tombstone and never automatically retries.
4. Result inspection returns an **untrusted planning draft**, snapshot/current revisions and a stale flag. It never updates task state, creates a reminder, dispatches executable work or sends a message. Changed task state is not inferred from model claims.

`revoke REQUEST_ID` prevents an unstarted call. An already admitted call may finish. Reload/unload loses the consumer's process-local grants/results; it does not retract provider data or cancel billing. There is no durable restart-safe execution receipt. Reauthorizing after an uncertain outcome can duplicate a call, so the help explicitly warns against doing it. The bounded grant table retains tombstones rather than silently evicting them. An observed configuration revocation permanently revokes unstarted grants; an unobserved disable→enable change is not detected without monotonic host revision fencing.

## Host restriction rather than a prompt promise

The existing unrestricted agent launch remains unchanged. The new text path is default-off, separately configured for a trusted plugin and an exact provider/model/base URL. It accepts only the current ordinary OpenAI-SDK chat-completions route. No saved delegation route, fallback chain or credential resolver is consulted. HTTPS endpoints must have no userinfo/query/fragment. SDK provider adapters, dynamic authentication, query overrides, redirect-following HTTP clients, HTTP authentication and event hooks are rejected.

**The ordinary OpenAI SDK defaults to following redirects, so an existing default Hermes/OpenCode Go client can be refused.** The proposal needs a supported dedicated no-redirect client before real deployment. It never changes the parent client or network settings to make a test pass. A provider-reported model mismatch fails after the response; this cannot undo the request.

The text path does not construct or run a full `AIAgent` child. It uses the real host transport and middleware with an immutable request and a guarded one-attempt callback. It sends only fixed planning instructions and the supplied task snapshot. It does not inherit parent history, prefills, tool schemas, request overrides, MCP permissions, recursive delegation, workspace creation, memory ingestion, compression or auxiliary model work. Tool-bearing replies are not dispatched. Arbitrary middleware request changes or extra attempts are refused.

This is not an OS/Python sandbox or protection from malicious same-process plugins, provider implementations or operators. Configured plugin trust is not proof that a physical human authored each call. Native LOCAL admission relies on the host's existing registered source/session controller checks; all authorized controllers share that session's authority. Provider internals and actual billed/served model behavior remain outside client-side proof. Timeout/cancel is cooperative and cannot undo a request already sent.

## Reproduce the selected offline evidence

Use a fresh, trusted, credential-free disposable source copy at the exact host base, an already prepared Python 3.14 test interpreter, and the reviewed artifact. Review the patch before staging it. These are deliberate experiment steps, not a production installer:

```bash
set -eu
ARTIFACT="/path/to/hermes-superagent/experiments/text-worker"
COPY="/path/to/disposable-hermes"
PYTHON="/path/to/existing-test-venv/bin/python"
test "$(git -C "$COPY" rev-parse HEAD)" = 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
test -z "$(git -C "$COPY" status --porcelain)"
git -C "$COPY" apply --check "$ARTIFACT/text-worker-prototype.patch"
git -C "$COPY" apply --index "$ARTIFACT/text-worker-prototype.patch"
"$PYTHON" "$ARTIFACT/run_tests.py" --checkout "$COPY" --python "$PYTHON" --disposable-copy
```

The [runner](run_tests.py) verifies exact base, staged patch bytes and consumer/test hashes before invoking the host's canonical test runner. It does not apply patches, install packages, provision an environment or configure a personal profile. `--check-only` validates those guards without executing host Python. The test lane uses temporary homes and HTTP mock transports, with no listeners, real model/provider calls or credentials. The concrete consumer tests run the real native command authorization, turn admission, SQLite task store, host lifecycle, request transport and OpenAI SDK serialization.

The ordinary project checker tests artifact integrity only and continues testing the **clean unmodified host**. Exact-commit project CI is not the proposed host's upstream CI, nor a live-model acceptance result. The isolated experiment suite is a separate selected lane, not the full upstream suite. No previously denied Gateway socket test is retried.

## Remaining release gates

- Independent host API adoption/security review and a supported release, rather than applying a local patch to a user's installation.
- Real OpenCode Go `deepseek-v4.1-flash` acceptance with authorized configuration and observed wire/usage behavior; no different model or silent fallback.
- A durable task execution ledger with restart recovery, explicit reconciliation of unknown outcomes, concurrency limits and budget accounting before ongoing autonomous dispatch.
- Appropriate cancellation/timeout UX and reliable progress delivery. A short polling wait is not proof of remote cancellation.
- General tool-using workers need a separate enforceable capability design. This text-only preview is not code execution, a full worker orchestrator, Gateway end-to-end acceptance, automatic memory or completion of the MVP.
