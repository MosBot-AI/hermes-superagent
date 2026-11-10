# 84. Packaged Gateway lifecycle acceptance

English | [简体中文](84-packaged-gateway-live-zh.md)

## Scope and status

Issue #50 tracks the actual transport prerequisite for #40 and the profile-first local MVP. This slice adds a **manual-only acceptance candidate**, not a claim of passing live acceptance or full MVP completion. The ordinary PR/unit suite verifies preparation only. The new test must pass in the explicit `Native Gateway acceptance` workflow before its behavior is accepted.

The workflow builds the current committed production runtime with its provenance manifest, verifies it, and stages it as an isolated local Git source. The pinned official Hermes installer scans, installs and enables that package in a disposable private profile. A refused scan or failed installation fails the test; no bypass flags are used. Installation alone may use existing runner proxy/CA routing for official Python dependencies. No provider secrets are inherited, and the Gateway receives a smaller environment without proxy/provider configuration.

The host pin remains `2281116525106e3c109993ccb5dc74d02bfc1427`. Only its real process/control/WebSocket helper functions are reused. The existing upstream lifecycle test uses a loopback fake model; **the separate packaged test does not reuse that model, its harness, or a fabricated runner**. It calls no `prompt.submit` and supplies no provider credentials. The pinned host requires a non-empty model label to restore even a command-only session policy; the isolated config names `deepseek-v4.1-flash` as metadata only. No provider is configured or called.

## Acceptance chain

1. Start the unmodified `gateway.run` process and require real readiness/discovery.
2. Reject unauthenticated WebSocket attachment; mint an official private-control session ticket and attach using the native protocol.
3. Create a local session; invoke the installed `/personal-tasks --json` command over `slash.exec`.
4. Verify task creation, same-key replay without duplication, revision 2 update, stale-revision refusal, and invalid-input refusal.
5. Perform normal identity-targeted planned shutdown and require process exit, absent control channel, and closed API port.
6. Start a new Gateway instance, obtain a new ticket, explicitly resume the original session, and read back the same task/revision/title and replay receipt.
7. Stop cleanly again; independently check both host database and exact plugin task database read-only, including task ID/revision/title and no duplicate row.

Only synthetic task text is used. The test's failure cleanup kills only its own subprocess if normal stop fails; that is cleanup, not successful lifecycle evidence. JUnit receipts are uploaded, not raw profiles, tickets, logs or databases.

## Running and limits

Run the workflow explicitly from a reviewed branch/revision. It is never triggered on pushes or PRs. The test lives in `acceptance/live`, outside the offline `tests/conftest.py` network guard and default `tests/unit` collection and requires `HERMES_TEST_ROOT`, `HERMES_RUNTIME_PACKAGE` and `HERMES_SOURCE_COMMIT` from the workflow's verified build.

Local cloud verification still encounters `EPERM` at `AF_UNIX` construction, including the supported elevated-review probe. No local Gateway start or policy workaround is attempted after that result. Successful GitHub-hosted execution would establish that runner's bounded acceptance, not repair the local cloud restriction or identify its kernel-policy cause.

This does not establish natural-language/model behavior, bare `--continue` behavior for slash-only sessions, crash recovery, TUI UI acceptance, remote-owner authority, shared REST API completion or external effects. Existing earlier MacBook/Mac mini evidence remains separate, and those computers are not used by this workflow.
