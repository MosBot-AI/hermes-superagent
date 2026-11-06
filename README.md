# Hermes Personal Agent

English | [简体中文](README-zh.md)

A Hermes-native personal-agent plugin designed for one main agent to manage projects, commitments, reminders, and constrained workers. See the [design index](docs/README.md). It does not run a second agent loop or require another API gateway.

## Current status

Implemented development slices include the **E0 native foundation** and an **opt-in local CLI task inbox**. This is not yet a complete personal-agent MVP.

- Native loading through `plugin.yaml` and synchronous `register(ctx)`.
- A read-only `personal_agent_status` tool and, in `in_process` plugin mode, the `hermes personal-agent status` CLI.
- Default `read_only` mode opens no task storage. Explicit `local_tasks` enables a profile-local CLI inbox: capture, search, project grouping, list/show, update, complete and cancel, plus explicit due dates and agenda with durable replay receipts and revision checks. No personal-data model tool or model routing is registered, and plugin loading creates no schedule or external delivery.
- Offline unit tests and real discovery, registry dispatch, configuration, and unload contracts against a pinned Hermes commit.
- Follow-on E0.4 failure-boundary contracts and a read-only inventory of ten blocked write paths. `hermes personal-agent coverage` shows the evidence; it does not authorize or disable host tools.

This plugin **does not disable or secure other Hermes tools**. E0.4 write-path coverage and E1 identity/authorization are incomplete, so this foundation must not be used to enable agent-driven or external write operations. Local task edits are separate explicit local-operator commands. Its status explicitly reports `release_gate: blocked`. See the [first-slice implementation record](docs/12-foundation-progress.md), [enforcement contracts](docs/13-enforcement-contracts.md), and [changelog](CHANGELOG.md).

The detailed [client and connector API contracts](docs/14-client-api-contracts.md) are design work only. No HTTP API is registered by this plugin yet. M1 uses an existing mobile messaging channel; a custom native phone app has separate authentication and recovery gates.

The [local task inbox guide](docs/16-local-task-inbox.md) documents opt-in, commands, persistence and privacy limits. [Due dates and agenda](docs/17-local-task-agenda.md) explain date semantics and the original v1→v2 store upgrade; they do not deliver reminders. The [primary Bot binding design](docs/15-primary-bot-binding.md) selects an existing native Bot/canonical chat, but binding and owner authentication are not implemented.

The [owner-entry/read-authorization foundation](docs/18-owner-entry-and-read-authorization.md) adds a pure internal evaluator and `/personal-access` / `hermes personal-agent access` denial diagnostics. Public source context lacks verified receiving-Bot/account provenance, so production identity issuance and private reads remain disabled; this is not completed owner authorization.

The [unified voice design](docs/19-unified-voice-provider-contracts.md) covers local ASR/TTS/VAD, user-configured online APIs and explicitly adapted realtime frontends under shared lifecycle/recovery contracts, preserving real backend differences. The [offline voice simulator](docs/20-voice-contract-simulator.md) now exercises a narrow synthetic contract through `hermes personal-agent voice self-test`. It uses generated silence only, with no microphone, speech model, provider call or native turn. Account connections and live voice remain unimplemented.

The [local search guide](docs/22-local-task-search.md) adds literal title/details retrieval with bounded pages. A separate [native voice IPC experiment](docs/21-native-voice-ipc-experiment.md) includes a reviewable host patch and verification record; it is not applied or integrated by this plugin.

The [local project groups](docs/24-local-project-groups.md) add explicit task labels, project filters and progress counts, with a schema-v3 upgrade preserving old receipts. These are local groups, not native Projects or permission scopes. The [host command-context experiment](docs/23-host-command-context-experiment.md) packages a separate unintegrated identity-observation patch and its remaining gates; no owner authorization is enabled. Its command-only repair is verified separately with 87 guarded tests; nine historical socket setup failures remain unresolved.

The opt-in [native planning blueprint](docs/25-native-planning-blueprint.md) is available through Hermes’s existing Blueprint/Cron interfaces. Loading registers a template only, not a job. Native scheduling can incur model costs; existing jobs survive plugin removal. Default delivery is local, not a tool or privacy sandbox.

The [pending enrollment/policy core](docs/26-pending-enrollment-policy.md) now persists prospective mappings and scopes with transactional revisions, terminal revocation and audit. Its internal opener is disabled by default and has no registered runtime entry point. These records do not authenticate an owner, issue grants or adopt local tasks.

The [fenced read-admission core](docs/27-fenced-read-admission.md) adds current-policy transaction ordering and bounded immutable summary coordination. Only synthetic tests supply trusted confirmations/resources; no production adapters, runtime entry point or task adoption are enabled.

## Development checks

`compatibility.json` records the Hermes baseline commit. The current runtime target is Python 3.14. A single tested SHA does not justify a broad `requires_hermes` version range.

Prepare the official Hermes checkout and test environment in separate directories. Do not use a production `HERMES_HOME` or copy account credentials:

```bash
git clone https://github.com/NousResearch/hermes-agent.git ../hermes-agent
git -C ../hermes-agent checkout --detach 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
cd ../hermes-agent
export HERMES_HOME="$(mktemp -d)"
export HERMES_RUNTIME_DIR="$(mktemp -d)"
python -m pm.build_env --source . --out ../hermes-test-venv --group dev --group test
cd ../hermes-superagent
../hermes-test-venv/bin/python scripts/check.py \
  --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

Environment preparation downloads dependencies from official sources. Tests use synthetic inputs, temporary homes, and a Python socket connection guard; they do not access real personal accounts. The checker verifies the upstream HEAD and clean tracked sources, records Python and lock/package fingerprints, and invokes the official Hermes `scripts/run_tests.sh`. Missing checkouts or dependencies fail rather than silently skipping compatibility checks. The recorded package inventory is evidence of the interpreter used, not proof that an arbitrary supplied environment exactly matches the lock.

`python scripts/check.py` alone runs repository unit tests, Ruff, ty, and bilingual document structure/link and JSON-example syntax checks, and explicitly reports Hermes compatibility **NOT RUN**. Test-tool versions come from the pinned Hermes dev group, not plugin runtime dependencies.

## Try it in an isolated Hermes profile

This is not a production installation recommendation. Use the pinned, tested Hermes checkout and a temporary profile. Consult that version's `hermes plugins install --help` and install a reviewed **full 40-character commit SHA**. `--ref` does not accept branch names, and a GitHub tree URL is not a replacement for the pin. Explicitly enable the plugin afterward. Its ID is `hermes-personal-agent`.

Current runtime contract tests cover the default `plugins.isolation: in_process`. Under `plugins.isolation: host`, Hermes skips `ctx.register_cli_command`, so this CLI is unavailable. Full isolated-host tool execution has not been tested. Do not disable an existing isolation setting just to expose this CLI.

The host's `config.yaml` uses:

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: read_only
```

Preserve existing entries when combining this with your configuration; do not replace the entire `plugins` section. Enabling the plugin does not change `delegation.backend`, the main model, credentials, tool overrides, or other permissions. Whether `personal_agent_status` appears in the model's tool surface also depends on the session's toolset selection. CLI status does not require an LLM call.

To try the local inbox, explicitly change only this plugin’s mode to `local_tasks` and follow [the command examples](docs/16-local-task-inbox.md#2-enable-and-use). It uses POSIX private-file checks and is tested on Linux; Windows task storage is unsupported. It does not bind a Bot, dispatch native work or need an API Key. Task text is plaintext local data, not a secret store.

## License

[MIT](LICENSE). The review-only voice and command-context experiments include limited upstream-derived patches and their licenses; the Hermes host itself is not vendored or modified by plugin installation. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and licensing.
