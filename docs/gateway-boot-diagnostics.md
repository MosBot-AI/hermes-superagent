# Gateway bootstrap diagnostics

English | [简体中文](gateway-boot-diagnostics-zh.md)

Refs [#50](https://github.com/MosBot-AI/hermes-superagent/issues/50) and parent [#40](https://github.com/MosBot-AI/hermes-superagent/issues/40).

## Known failure and evidence boundary

The historical Gateway log reports `Gateway control socket failed to start: [Errno 1] Operation not permitted`, followed by a fatal bootstrap failure. The pinned host's `GatewayControlServer.start()` catches the exception and logs its message without the traceback. Consequently the log does not identify the failing system call. The socket's final `chmod` is suppressed by upstream and cannot itself cause this particular fatal path. Other path operations and the `asyncio.start_unix_server` socket/create/bind/listen sequence remain candidates.

Linux defines EPERM as an operation not permitted; it is not a request for a GitHub approval or an API credential failure. Ordinary path search/access denial at `bind` is documented as EACCES. A seccomp filter can return an errno without executing a system call, but seeing `Seccomp: 2` does not identify a matching rule or prove the historical cause. See [bind(2)](https://man7.org/linux/man-pages/man2/bind.2.html) and [kernel seccomp documentation](https://docs.kernel.org/userspace-api/seccomp_filter.html).

## Read-only planning

Use the pinned host and its existing interpreter. By default this command verifies the clean host revision, reports non-secret process policy indicators and prints a plan. It does not start a Gateway, create a socket, install anything or create the output directory.

```sh
python scripts/diagnose_gateway_boot.py \
  --hermes /path/to/pinned/hermes \
  --hermes-python /path/to/hermes-venv/bin/python \
  --output /private/new-evidence-directory
```

The local regression tests use synthetic exceptions and mocked subprocess execution. They verify traceback preservation, restricted module invocation, private evidence creation, failure exit propagation, refusal to overwrite evidence and a credential-free environment. They are not native transport acceptance.

## Native execution prerequisite

Only add `--run-native` when the selected execution context is independently confirmed to permit the unchanged official private transport. This flag is an accidental-execution guard, not permission to bypass platform policy. Do not disable seccomp, relax socket permissions, substitute TCP, use sudo, or move a denied operation elsewhere to evade its restriction. A generic claim that CI supports networking is not proof that a specific policy permits this operation.

The runner delegates to the pinned upstream `evals/shared_gateway/normal_boot.py`. A small interpreter launcher only restores the current exception traceback on the control listener's existing failure warning; it does not patch the host, socket functions, peer checks or admission. The upstream probe provides a disposable credential-free profile, a PATH/LANG/TZ-only inherited environment, a bounded readiness deadline and cleanup of its own Gateway process group. No provider key, plugin, real user data or model request is supplied. The runner creates a new mode-0700 evidence directory and will not overwrite it.

Artifacts are `PLAN.json`, `BOOT.json` and `BOOT.log`, plus the diagnostic launcher. Keep raw logs private until reviewed; paths and traceback details may identify the executor. A successful upstream descriptor verdict only establishes bootstrap readiness. It does not establish authenticated client attachment, model task execution, persistence after actual Gateway restart or completion of #40/#50. Failed execution should retain the traceback and exact source revision before any remedy is proposed.

## New evidence and the supported CI gate

A single credential-free diagnostic was admitted through the execution tool's supported elevated-review path. The preserved traceback proves that this attempt failed inside Python's `socket.socket(AF_UNIX, SOCK_STREAM)` construction, before `bind`, `listen` or pathname checks. Therefore changing directory permissions, shortening paths or changing the final socket mode cannot fix this particular failure. The exact kernel-policy rule remains unproven; the local execution environment is not claimed repaired.

A separate manual-only GitHub-hosted `ubuntu-latest` workflow is prepared to run the pinned upstream `tests/gateway/test_unified_gateway_native_live.py` suite. [GitHub documents this runner as a fresh VM](https://docs.github.com/en/actions/reference/runners/github-hosted-runners). The unchanged official test uses private temporary profiles and a loopback synthetic model, not provider credentials or an external fallback model. It exercises actual control tickets, WebSocket attachment, submissions/receipts, multiple-client ordering, queued recovery after owner death, safe-mode managed workers and planned-stop cleanup. This is a normal native integration regression gate, not a change to the restricted local executor or its policy.

The workflow does not run on PRs or pushes; it requires a separate explicit dispatch. This manual CI workflow has not been dispatched. Separately, the authorized MacBook probe passed the three upstream lifecycle tests and a synthetic source-fixture plugin task/restart/deduplication flow on `22811165`; see the [compatibility evidence](hermes-compatibility-matrix.md). This does not establish official installation or real-provider acceptance. When dispatched, the gate runs sequentially with an eight-minute step bound and publishes the synthetic JUnit receipt, which can include failure output/traceback snippets. Standalone raw Gateway log files are not uploaded. A pass establishes the host lifecycle in that runner, not local-cloud usability or plugin task acceptance with OpenCode Go. #40/#50 remain open until their actual provider/plugin and restart criteria are verified.
