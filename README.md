# Hermes Personal Agent

English | [简体中文](README-zh.md)

A Hermes-native personal-agent plugin designed for one main agent to manage projects, commitments, reminders, and constrained workers. See the [design index](docs/README.md). It does not run a second agent loop or require another API gateway.

## Current status

The first development slice is the **E0 native plugin foundation**, not a usable personal-agent MVP.

- Native loading through `plugin.yaml` and synchronous `register(ctx)`.
- A read-only `personal_agent_status` tool and, in `in_process` plugin mode, the `hermes personal-agent status` CLI.
- Strict rejection of any mode other than `read_only`. No personal-data writes, external delivery, scheduling, or model routing are registered.
- Offline unit tests and real discovery, registry dispatch, configuration, and unload contracts against a pinned Hermes commit.

This plugin **does not disable or secure other Hermes tools**. E0.4 write-path coverage and E1 identity/authorization are incomplete, so this foundation must not be used to enable controlled write operations. Its status explicitly reports `release_gate: blocked`. See the [first-slice implementation record](docs/12-foundation-progress.md) and [changelog](CHANGELOG.md).

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

`python scripts/check.py` alone runs repository unit tests, Ruff, ty, and bilingual document structure/link checks, and explicitly reports Hermes compatibility **NOT RUN**. Test-tool versions come from the pinned Hermes dev group, not plugin runtime dependencies.

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

## License

[MIT](LICENSE). Upstream test sources are not bundled with this plugin. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution and licensing.
