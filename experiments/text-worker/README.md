# Review-only task planning worker

English | [简体中文](README-zh.md)

## Status

This is an isolated host proposal plus a concrete experimental task consumer. It is **not installed, enabled, imported by the production plugin, submitted upstream or deployed**. The supported host pin remains `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. Do not apply this patch to an installed host or weaken plugin isolation to try it.

The [manifest](manifest.json) records the exact patch, source hashes, selected verification and limitations. The [host patch](text-worker-prototype.patch) retains the upstream [MIT license](LICENSE.hermes-agent). Distribution on this project's feature branch is not an upstream release.

## The narrow useful flow

The [experimental consumer](consumer.py) connects real local tasks to the proposed `ctx.subagent_lifecycle.launch_text` API:

1. An authorized native LOCAL session controller issues `/personal-plan-worker allow TASK_UUID REVISION REQUEST_ID`. This approves one selected active task snapshot, for at most 120 seconds, to OpenCode Go `deepseek-v4.1-flash`, with 1024 output tokens and a 30-second request timeout. Normal model usage can cost money. The command does not make a request.
2. During a real primary session turn, `personal_task_plan_preview` can consume that exact grant. Its only fields are `action` and `request_id`. The model cannot supply a goal, task, context, provider, model or permission. An observed task revision change at admission, expired/revoked grant, different session/route/profile or child turn refuses before launch. Task storage, the claim ledger and provider submission are not one transaction; a concurrent edit after the revision check does not retract the approved snapshot.
3. The consumer commits a durable single-use claim before the host call. The host admits a bounded, one-request text worker and returns its ordinary lifecycle handle. Only the original consumer keeps that capability. Repeated launch calls inspect the same handle or saved receipt; an exception or restart leaves an uncertain-outcome tombstone and never automatically retries.
4. Result inspection returns an **untrusted planning draft**, snapshot/current revisions and a stale flag. It never updates task state, creates a reminder, dispatches executable work or sends a message. Changed task state is not inferred from model claims.

`revoke REQUEST_ID` prevents an unstarted call. An already admitted call may finish; reload/unload does not retract provider data or cancel billing. The separate private `text-worker-ledger.sqlite3` retains task identifiers, snapshot hashes, request scope and observed terminal drafts. Snapshot text and live capability handles remain process-local. The public read-only `authorize_text_route` gate returns a non-secret fingerprint without creating a client or sending a request. Claiming binds the exact provider/model/base URL/API-mode fingerprint; both live and saved drafts require that approved route again before a fresh tool return. A saved draft survives reload and is checked against the current task revision when read. A completed but unobserved result can be lost and remains unknown.

Request IDs are profile-wide and bound to the original session/route/task/revision. Each consumer instance has an owner epoch: a restarted or concurrent instance can inspect its matching saved receipt but cannot adopt a pending authorization, steal a claim or retry an uncertain request. A new key is a new authorization, not recovery of the old operation. Never use a new key to retry an uncertain outcome. Retention is indefinite and bounded to 64 entries; capacity refuses new grants, with no automatic cleanup or eviction. Deleting the ledger destroys duplicate protection. This is a deliberately bounded experiment, not ongoing unattended orchestration. An observed configuration revocation permanently revokes unstarted grants; an unobserved disable→enable change is not detected without monotonic host revision fencing.

## Native request workbench

These explicit commands let the operator find and inspect requests without asking a model to call the preview tool. They use the same authenticated LOCAL session-control admission, profile and exact session/route scope as `allow`:

| Command suffix | Result |
|---|---|
| `list [--after KEY]` | Up to ten request-ID-ordered metadata records and a continuation key; no task text, draft, owner token or route fingerprint |
| `status KEY` | Authorization/receipt state with a truthful next step; a consumed request is not proof that a worker is still running |
| `draft KEY` | Already saved terminal receipt, untrusted draft and current task revision/staleness; no live polling or new model request |
| `stop KEY` | Revoke an unstarted grant; report cancellation unavailable for an admitted/unknown request without changing it |

For example, `/personal-plan-worker list` finds retained request IDs and `/personal-plan-worker draft plan-1` displays the saved draft. Native output defaults to readable text; `/personal-plan-worker --json status plan-1` returns structured data. Untrusted draft text is delimited and control characters are escaped. The model tool remains JSON-only and retains its exact approved-route gate.

`receipt_saved` does **not** mean the task was performed. After restart, a consumed request without a saved receipt remains `launch_outcome_unknown`; a pending grant owned by an earlier instance is not silently adopted. `stop` never turns an unknown remote outcome into “cancelled.” No workbench command launches, retries, harvests a live result, deletes a retained key or mutates a task. Lists expose only the count in this session/route, not other sessions' occupancy of the shared 64-entry ledger.

An explicit native draft view is a separate operator-read contract, not a model-route bypass. At the pinned host, `gateway/session_commands.py` returns plugin output as `exec`, and the reviewed CLI/TUI/Desktop handling displays that output instead of taking the model-send branch. This slice exercises the server command path; client branches were source-audited, not exercised in a live UI. Clients may retain display/cache data, and a user can copy it elsewhere. LOCAL controllers may be programmatic; this is not proof of a physical human or a guarantee that arbitrary future clients will not record output.

The native callback does not bind a current model parent. Therefore admitted-request cancellation is unavailable here: the workbench does not copy an old context or impersonate a parent to bypass that boundary. The existing model-tool preview path and host lifecycle API remain unchanged.

## Host restriction rather than a prompt promise

The existing unrestricted agent launch remains unchanged. The new text path is default-off, separately configured for a trusted plugin and an exact provider/model/base URL. It accepts only the current ordinary OpenAI-SDK chat-completions route. No saved delegation route, fallback chain or credential resolver is consulted. HTTPS endpoints must have no userinfo/query/fragment. SDK provider adapters, dynamic authentication and query overrides are rejected.

The host now owns a **dedicated no-redirect HTTPX client** with environment proxy/configuration disabled and transport retries disabled. It uses the exact approved HTTPS chat-completions target and the parent's already-resolved static API identity, without reading credential files, resolving another route or constructing another OpenAI SDK client. This avoids the SDK constructor's implicit environment-header discovery. Parent sockets, transports, headers, auth, hooks, redirects and proxy settings are not inherited or changed. The default redirect-following parent SDK client is compatible with this isolated path. TLS uses an explicit verified context and certifi roots, with no environment CA/keylog discovery. Compressed responses are refused; raw response bodies are bounded to 512 KB, parsed with the official response model, then normalized by the host transport. A provider-reported model mismatch fails after the response; this cannot undo the request.

The text path does not construct or run a full `AIAgent` child. It uses the real host transport and middleware with an immutable request and a guarded one-attempt callback. It sends only fixed planning instructions and the supplied task snapshot. It does not inherit parent history, prefills, tool schemas, request overrides, MCP permissions, recursive delegation, workspace creation, memory ingestion, compression or auxiliary model work. Tool-bearing replies are not dispatched. Arbitrary middleware request changes or extra attempts are refused.

The route gate prevents a **new model-tool** draft return under a changed route. It does not delete previous messages or stop the host from reusing existing parent history after a model switch. Do not treat this as conversation-wide cross-provider isolation.

This is not an OS/Python sandbox or protection from malicious same-process plugins, provider implementations or operators. Configured plugin trust is not proof that a physical human authored each call. Native LOCAL admission relies on the host's existing registered source/session controller checks; all authorized controllers share that session's authority. Provider internals and actual billed/served model behavior remain outside client-side proof. Timeout/cancel is cooperative and cannot undo a request already sent.

## Safe terminal diagnostics

Observed terminal receipts now retain only a fixed failure category and the existing local submission-callback attempt count (0, 1, or unavailable). Native `draft KEY` displays a fixed explanation for DNS, certificate verification, connect/read/write/pool timeout, connection/read/write/protocol failure, cancellation or an unclassified failure. It never displays raw exceptions, headers, URLs, certificate paths or provider response bodies. Unknown diagnostics become generic; malformed saved diagnostics are refused. Old receipts without this field remain readable, without invented history or a schema reset.

These are local observations, not proof of provider execution, delivery, billing or cancellation. No diagnostic reopens a grant or permits automatic retry, even if the count is zero. Exact-route disclosure checks and the one-attempt transport are unchanged. The feature remains part of the uninstalled experiment.

## Provider compatibility and actual acceptance attempt

OpenCode Go requires a session-affinity header. For the exact `opencode-go` provider and HTTPS `opencode.ai:443` origin only, the dedicated client now calls the official host affinity helper with a fresh one-shot identifier in an empty context. It does not inherit the parent/root session identifier or arbitrary headers. Both the configured `/inference/go/openai/v1` path and metadata `/zen/go/v1` path retain exact-target checks. Foreign origins, lookalike hosts and other providers do not receive this header. The selected offline lane now has 144 host and 107 consumer tests.

One explicitly authorized synthetic request used the official credential resolver and this transport at `https://opencode.ai/inference/go/openai/v1`, requesting only `deepseek-v4.1-flash`. It failed with `ConnectError` before an HTTP status or model response was available. Delivery is unconfirmed; no retry, fallback or alternative route was attempted. `config.yaml` remained unchanged; the official resolver can maintain credential metadata, so this is not a claim that the whole profile was unchanged. No native activation, worker launch or Gateway was involved. **Live worker/model acceptance is still open.**

A later local-only review found a concrete difference from the earlier successful SDK probes: those used HTTPX environment routing/CA defaults, while this dedicated client intentionally ignores environment proxies and uses certifi roots. The original exception cause and earlier environment snapshot were not retained, so a routing or CA mismatch is only a hypothesis, not a proven root cause. No request was repeated and no proxy/TLS policy was relaxed.

A separate official installation attempt for the production repository, in a fresh credential-free offline profile, stopped at the unchanged scanner: CAUTION, 50 findings, exit 1. No override was accepted; official listing and filesystem checks confirmed the plugin was absent. The repository install source includes development docs/tests and these experiments even though production registration does not import the worker. A reviewed runtime distribution is a future packaging task, not permission to bypass that verdict. Installation, activation and supported-host worker availability are unverified.

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

The [runner](run_tests.py) verifies exact base, staged patch bytes and consumer/test hashes before invoking the host's canonical test runner. It does not apply patches, install packages, provision an environment or configure a personal profile. `--check-only` validates those guards without executing host Python. The test lane uses temporary homes and HTTP mock transports, with no listeners, real model/provider calls or credentials. The concrete consumer tests run the real native command authorization, turn admission, SQLite task store, host lifecycle, dedicated HTTP request serialization and official response parsing.

The ordinary project checker tests artifact integrity only and continues testing the **clean unmodified host**. Exact-commit project CI is not the proposed host's upstream CI, nor a live-model acceptance result. The isolated experiment suite is a separate selected lane, not the full upstream suite. No previously denied Gateway socket test is retried.

## Remaining release gates

- Independent host API adoption/security review and a supported release, rather than applying a local patch to a user's installation.
- Real OpenCode Go `deepseek-v4.1-flash` acceptance with authorized configuration and observed wire/usage behavior; no different model or silent fallback.
- Production-grade reconciliation of unknown provider outcomes, durable provider execution identity, capacity/retention UX, concurrency limits and budget accounting before ongoing autonomous dispatch. Local atomic claims prevent automatic resubmission, not loss of unobserved results or exactly-once provider execution.
- Appropriate cancellation/timeout UX and reliable progress delivery. A short polling wait is not proof of remote cancellation.
- General tool-using workers need a separate enforceable capability design. This text-only preview is not code execution, a full worker orchestrator, Gateway end-to-end acceptance, automatic memory or completion of the MVP.
