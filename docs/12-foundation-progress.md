# 12. First Development Slice: Native Plugin Foundation

English | [简体中文](12-foundation-progress-zh.md)

Current-target update: [76](76-native-memory-contracts.md) records the separate E0.9 native memory verification matrix for Hermes `22811165`. It does not change the historical foundation results below or enable durable checkpoint-v2, remote identity or production writes.

This page records an earlier E0 slice. See [16](16-local-task-inbox.md) for the newer opt-in local task inbox; it does not enable the native/external controlled-write paths described here.

This page records actual implementation boundaries. It does not turn the other design documents into completed features. The slice covers initial portions of E0.1/E0.2/E0.5; the E0 epic and M0 milestone remain incomplete. It is not an M1 usable release.

## Implemented

- A native directory plugin with `plugin.yaml`, synchronous `register(ctx)`, and relative plugin imports.
- A `personal_agent_status` tool and, in the default `in_process` mode, `hermes personal-agent status`. Both return the same versioned JSON readiness report. Host isolation skips CLI registration; do not disable a user's existing isolation setting for this CLI.
- Configuration accepts only `mode: read_only`. Host schema warnings are not enforcement; unsupported values are rejected before any tools register.
- The tool accepts no business arguments. Forged `approved`, owner, action, or private-body fields are rejected without reflecting the input in the error.
- Explicit reporting of unimplemented data, authorization, reminder, delivery, and routing capabilities and the reason the release gate remains blocked.
- No third-party runtime dependencies, agent loop, scheduler, account connections, network calls, background threads, database, or credential reads.
- A pinned upstream SHA in `compatibility.json`, source/license records, a reproducible check script, and a CI workflow.
- Preserved existing Python ignore rules, with additional macOS/Windows system-file rules and Git behavior tests.

“Read-only” describes this plugin's current tools, not host isolation. The plugin does not intercept or disable native shell, MCP, browser, RPC, batch, or worker tools. Those paths have not passed E0.4 and must not be presented as controlled personal-agent write capabilities.

## Actual compatibility contracts

Baseline: Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`, Python 3.14, Linux, and the default `in_process` plugin mode. Tests use the official PM-built frozen dependency environment and `scripts/run_tests.sh`. Full host-isolation subprocess tools, Windows/macOS runtime contracts, and mobile contracts have not been executed.

| Contract | Test | Scope of evidence |
|---|---|---|
| Manifest / entry point / tools | Copy the actual plugin into a temporary home and run real `PluginManager.discover_and_load()` | No mocked ctx; proves only this plugin's behavior at the recorded SHA |
| Configuration / defaults | Real config.yaml, omitted defaults, and six invalid values | `config_schema.default` is not injected automatically; code supplies its default |
| Tool results | Real scoped registry dispatch and string-result JSON parsing | Handlers return JSON strings, not ordinary dicts |
| Enable / disable | Real allow/deny configuration without replacing the gate | Disabled plugins register neither the tool nor CLI |
| Reload / unload | Force reload and dispatch, valid-to-invalid/disabled reload, then unload | Clears this plugin's tool and CLI registrations; no global registry-count assertions |
| CLI | Registered argparse setup and handler | Matching status output, not a complete terminal/mobile E2E test |
| Doctor | Real host Doctor | Supplemental manifest/load verification, not a substitute for discovery and business calls |
| Package metadata | Read the staged, actual pyproject with the pinned host's PM declaration reader | No runtime requirements or package installation; the plugin itself does not import PM internals |
| Public storage helper | Call `plugins.plugin_storage.plugin_data_dir` only in temporary homes | Follows the active profile on each call and rejects traversal; it is not a ctx method. The status tool never calls this directory-creating API |

Unit tests and host contracts are separate. Without `--hermes`, the checker runs unit/lint/type checks and prints compatibility NOT RUN. When contracts are requested, a missing environment, wrong SHA, dirty tracked upstream files, or non-3.14 interpreter fails. It records the Python version, upstream `uv.lock` SHA256, and installed-package inventory fingerprint. The interpreter is caller-supplied; those observations do not attest that any arbitrary interpreter exactly matches the lock. The recorded local environment was built with `python -m pm.build_env --source . --out <fresh-path> --group dev --group test` against the pinned checkout.

Tests use synthetic inputs, temporary homes, and blocked Python socket connections. This is not a malicious-plugin process sandbox and does not claim to block every subprocess network path.

## Remaining work

1. E0.3: the later [native lifecycle contracts](75-native-lifecycle-contracts.md) cover bounded Project/Kanban/cron operator behavior and missing plugin CRUD seams. This historical slice did not include those probes. Weak native deduplication, cancellation requests and uncertain attempts must not be treated as controlled execution or reliable delivery.
2. E0.4: per-tool/path coverage, hook/dispatcher/middleware failures, safe mode, managed workers, and revocation. A write set cannot be enabled before its gate passes.
3. E0.5: the later [offline synthetic connector fixtures](74-synthetic-connector-fixtures.md) add durable fake-remote and pinned-host MCP stdio scenarios. This historical foundation slice alone had no complete connector simulator; the later harness does not complete E0.4, E1, E5 or real-provider acceptance.
4. E1: verified owner identity, grants, intent hashes, approvals, transactional admission/revocation, and redacted audit.
5. Only after these gates, add domain storage and the reliable reminder/task vertical slice. E9 routing remains Backlog; automatic switching does not jump ahead.

## Verification record

See the repository [README](../README.md) for reproduction. Unit tests, Ruff lint/format, ty, and pinned-host contracts are run before the slice is submitted. Exact counts and remote CI results belong to the corresponding branch/PR evidence. A commit is not evidence that CI passed. No real-account, mobile, voice, or live-provider tests were run.
