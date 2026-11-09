# Live Native Task Conversation Acceptance

English | [简体中文](65-live-task-acceptance-zh.md)

## Exact scope

On 2026-11-09, a synthetic single-user task conversation passed through the actual native Hermes TUI and the real OpenCode Go `deepseek-v4.1-flash` route. This supplies the missing bounded live-provider evidence for [issue #41](https://github.com/MosBot-AI/hermes-superagent/issues/41), not full personal-agent MVP acceptance.

- Plugin source: `e01bd2cd405dd7f36b87896ede13fa70f7cfeace` (main before this documentation change).
- Host source: `bf0203a794a07aac3ff764972ab9087baa4e4f4e` on the authorized Linux test laptop.
- Provider: `opencode-go`; model: `deepseek-v4.1-flash`; endpoint: `https://opencode.ai/zen/go/v1`.
- A fresh, separate profile, synthetic task data and existing authorized credentials were used. No fallback provider was configured. The ordinary profile and its running Gateway were not stopped or reconfigured.
- The plugin runtime was exported with the repository builder, then scanned, installed and enabled through the official installer. No scanner override, plugin isolation bypass or host patch was used. The host warned about the unknown optional `llm.text_worker` capability; `plan_worker` remained off and worker compatibility is not accepted.

The host is newer than the exact offline development target in `compatibility.json`. This is evidence for the tested task-conversation path on that one host revision, not a compatibility-target change, a broad version range or acceptance of Kanban, scheduling, workers or other adapters.

## Observed cycle

The tester submitted ordinary natural-language requests through the real TUI, not direct calls to plugin handlers. The session was explicitly activated with `/personal-tools enable-write`. Saved native tool results and the isolated task database were checked, rather than treating model prose as evidence.

| Step | Observed result |
| --- | --- |
| Capture one synthetic task under a synthetic project label | One task, `captured`, revision 1 |
| Look up that project and update the task details | A real `personal_tasks_read` call followed by the update; `captured`, revision 2 |
| Complete the same task | `done`, revision 3 |
| Run `/personal-tools disable`, then request reads and a new-marker write | Both tools returned `status: error`, `data: null`, `error.code: session_tools_not_activated`, `retryable: false` |

After disabling, the SQLite logical dump was identical before and after the refused operations: SHA256 `32ca3f17c4f79421986a03df3548fe0d9389ce00e64a53528c3c30a4f84965fb`. Counts remained one task, three events and three receipts. This digest describes the synthetic run, not a reusable expected digest for another run. Session route metadata confirmed the stated provider, model and endpoint (12 API calls and 10 tool calls). SQLite integrity was `ok`. The exported provenance file SHA256 was `c291ff856ff9e193b26a00f776b73f500ab097c20b54a5e9b098da3a291b86db`. After shutdown, the owned test Gateway process no longer existed. Local completion is a task-record change, not proof that real-world work was done.

## Reproduction procedure and isolation

1. Read repository instructions and the supported-mode documentation. Check the actual host revision and existing processes without exposing credentials. Use a new disposable profile; never reuse the normal profile or stop a Gateway merely because it is running.
2. Start from a strict environment allowlist. The tested launcher retained only `PATH`, `HOME`, `USER`, `LOGNAME`, `TERM`, `LANG` and `LC_ALL`, then added the isolated `HERMES_HOME`, `PYTHONDONTWRITEBYTECODE=1` and the existing `OPENCODE_GO_API_KEY` in memory. Establish this environment before running any Hermes command; every subsequent install, configure, enable and chat invocation must use the same allowlist and isolated HERMES_HOME, not only the TUI. Never print the key, put it in command-line arguments, persist it in test scripts or copy the entire normal environment/configuration.
3. Export the exact plugin source with `scripts/build_runtime_distribution.py`. Use the official installer on the original exported runtime, following its local-source requirements: `hermes plugins install "file://$RUNTIME" --yes-deps --enable`. Do not edit out findings or use force/scan overrides. A new profile may require the host's official dependency preparation before its launcher works.
4. Configure only the isolated profile for `mode: local_tasks`, `local_conversation: true`, and `local_model_tools: true` under `plugins.entries.hermes-personal-agent.settings`. Set its model route explicitly to the provider/model/endpoint above and `fallback_providers: []`. Keep unrelated adapters disabled.
5. Run a real PTY: `hermes chat --tui --provider opencode-go --model deepseek-v4.1-flash --toolsets personal_agent --max-turns 8 --run-budget 120 --ignore-rules`. Here `--ignore-rules` skips host AGENTS/SOUL, memory and preloaded-skill prompt injection for this synthetic fixture (repository instructions were read before testing); it does not disable host authorization, plugin admission or scanner checks. Explicitly activate the test session, request capture, project lookup/edit and completion, and check actual tool results plus stored state after each step.
6. Disable the session tools, take a logical database snapshot, and request both a read and a write containing a new synthetic marker. Verify structured refusal and no database change. Never infer refusal merely from apologetic model text or absence of a tool call.
7. Exit the TUI and stop only the Gateway launched for that isolated profile, verifying its exact process identity. Keep credentials and raw local histories private. Record hashes, route, state transitions and redacted results instead of publishing raw terminal recordings.

The initial launcher attempt inherited `FEISHU`/`HERMES_*` settings and the host tried to claim an already-used Feishu app. Its official conflict protection refused the attempt. That test TUI was stopped; the ordinary Gateway was not stopped. The corrected allowlist launch is the run described above. A separate profile name alone is therefore insufficient isolation. The first dependency-less profile launch also failed normally; official dependency preparation resolved that setup issue. Neither failed launch is counted as a passing task interaction.

## Limits

This run covers one TUI session and one synthetic task on one exact host/provider combination. It does not establish real remote/multi-user owner identity, hosted-plugin/managed-worker support, mobile or voice acceptance, reminders or delivery, restart recovery, worker execution, full project orchestration, latency/SLA guarantees or broad model reliability. Previously recorded restart and offline contract evidence is separate and is not silently attributed to this newer host. No independent physical UI inspection beyond the actual PTY was performed.

Cloud checks of the unchanged plugin source passed 2,957 unit tests, Ruff lint/format, `ty 0.0.89` and bilingual documentation checks. These checks and the live run have different scopes. This document adds evidence, not a new runtime feature or a production release. The parent E6/M1 goals remain incomplete.
