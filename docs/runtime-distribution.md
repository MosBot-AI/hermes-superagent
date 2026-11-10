# Offline runtime distribution

[简体中文](runtime-distribution-zh.md)

This export is a standalone plugin package, not installation or admission approval.
The existing scanner refusal and findings remain valid; no installation retry is
part of this work. Any future installation must retain scanning and obtain all required consent.

Commit the builder, explicit `packaging/runtime-files.json`, guides and runtime
sources first. Run that exact committed builder with a full source SHA:

```text
python scripts/build_runtime_distribution.py --source-commit FULL_SOURCE_SHA --output-dir NEW_DIRECTORY
python scripts/build_runtime_distribution.py --source-commit FULL_SOURCE_SHA --output-dir NEW_DIRECTORY --verify
```

The parent directory must exist. Output must not exist. Only committed Git blobs
are read; working-tree changes are not included. A later distribution commit may
contain the generated tree; its SHA differs from the source SHA. No generated
copy is committed by the builder. `PROVENANCE.json` hashes every shipped source
file, plus the builder and specification. It excludes its own hash. Verification
reconstructs expected bytes from the source commit; hashes are not signatures.

All production Python files, original metadata, MIT license and third-party
notices are preserved unchanged. Research, tests and experimental host patches
remain in the source repository, accessible at the recorded source commit.
Relative links in the original notices refer to that full source tree.
The optional native memory-provider build declaration is not activated or shipped.

Defaults remain `read_only`, with personal storage and conversation/model-memory
tools disabled. Explicit local opt-ins require a trusted single-user profile;
LOCAL is not proof of physical locality. Local task/memory text is plaintext and
may enter host history or configured models after separate activation. This
plugin does not secure other Hermes tools. Release gates and real-model acceptance
remain incomplete. Experimental host patches and comparative consumers are excluded
from the runtime export; the [gated production planning modules](55-gated-plan-worker.md)
are distinct package sources. `plan_worker` defaults off. The unchanged pinned
host registers no worker because it lacks the exact reviewed text-worker contract.
On a compatible adopted host, registration additionally requires current
`llm.text_worker` consent and the local task/conversation/model-tool prerequisites.
Operations recheck those gates; there is no generic-launch or provider fallback.
Packaging neither enables these options nor installs or upgrades the host.

Official Git-subdirectory installation exists, but is not performed here. It
still requires unchanged scanning, consent and PM admission; dependency-free does
not guarantee an offline or environment-neutral installation. Update support for
subdirectory packages remains unverified.

## Downloadable push-build package

Successful branch **push** runs of `Foundation checks` produce
`hermes-personal-agent-runtime-FULL_COMMIT_SHA` in the run's **Artifacts** section.
Pull-request runs also build and validate the exact PR head commit, including the
cold conversation gate, but do not publish a runtime package. They use the ordinary
`pull_request` event, a read-only token, no persisted checkout credentials and no
repository secrets; no privileged `pull_request_target` execution is introduced.
These are 30-day CI artifacts, not releases, signatures or installation approval.
Check the repository, branch, commit and completed workflow before trusting a download;
`PROVENANCE.json` and hashes prove correspondence, not authorship.

The artifact contains `hermes-personal-agent.tar.gz`, `VALIDATION.json` and
`SHA256SUMS`. The tarball contains the standalone `hermes-personal-agent/` directory.
Keep the validation report beside it, not inside the plugin. The GitHub artifact
ZIP digest differs from the inner tarball's SHA-256.

Both push and pull-request pipelines run source and clean-host contracts first, then builds twice
from the exact checked-out commit, with no Git replacement objects. Archives have
sorted entries, fixed timestamps/owners and `0644` files / `0755` directories;
the two compressed archives must be byte-identical. It extracts the resulting
archive and verifies it again against the committed source before testing.

The unchanged pinned host's official `plugin_guard` scans the entire extracted
package. Its full findings are retained; only `safe` proceeds to package loading.
A safe verdict is **not zero findings**. The fixed `ed6bcdc15d883dc429f2dbb0559a62204965ab04`
artifact has six medium obfuscation findings: three Chinese Unicode-range patterns
and three SQLite header/journal byte patterns. Read the actual `VALIDATION.json`;
other revisions can have different findings. No finding is suppressed,
no scanner rule is changed, and CAUTION cannot be overridden by this workflow.
This direct static scan is not the installer's catalog, consent or PM admission.
The original full-repository install refusal remains a separate unresolved event.

The scanner and host loader execute from a fresh snapshot materialized from the
pinned Git blobs, not the caller's working tree or ignored bytecode. No original
host files are changed. This avoids hidden index flags or stale bytecode silently
substituting the scanner or loader while Git status appears clean.

Cold acceptance uses a fresh `python -I -B` process and a disposable synthetic
profile, with the source repository absent from the import path and global
`personal_agent` imports blocked. The actual host discovers the copied runtime
package. Default read-only registration must create no task storage or worker;
explicit test-only local-task configuration must capture, update, reload and
replay one task without duplication. Network connections, listeners and child
processes are refused (the scanner may only inventory bytecode using its exact
read-only Git command). No installer, operational profile, credentials, Gateway
listener or model is used. These test guards are not an OS sandbox against
malicious native extensions. A failed gate produces no downloadable package.

## Local archive and acceptance

After building a committed runtime directory, create an exclusive archive outside it:

```text
python scripts/build_runtime_distribution.py --source-commit FULL_SOURCE_SHA --output-dir RUNTIME_DIRECTORY --archive-file NEW_ARCHIVE.tar.gz
python scripts/check_runtime_distribution.py --repo SOURCE_CHECKOUT --source-commit FULL_SOURCE_SHA --package RUNTIME_DIRECTORY --hermes CLEAN_PINNED_HOST --hermes-python PREPARED_PYTHON --report NEW_REPORT.json
```

The report must be outside the source, runtime and host directories. Use an already
prepared trusted host/test interpreter; the checker installs nothing. It requires
an exact clean host, verifies all files before scanning and refuses a missing or
changed runtime directory before any package import. Archive integrity checks are
repeated after acceptance. This covers only the synthetic in-process CLI flow;
live installation, native clients/Gateway, model tools and worker adoption remain
separate acceptance gates. Do not retry a denied installation with this artifact.

## Packaged native conversation gate

The same verified runtime also runs in a separate cold process through the pinned
host's native LOCAL command dispatcher. A synthetic authenticated in-memory
transport captures and reads a task, reloads the plugin, and manually repeats the
same request without duplication. Missing read or control capability must be
rejected before any task mutation. Imported plugin modules must come from the
verified package, not the source checkout. Network, listeners, subprocesses,
model tools and worker registration remain disabled.

This additional gate tests the artifact's conversation entry point. It is not an
installation, login, real transport, CLI/TUI or model-provider acceptance result;
their exact-checkpoint evidence must be checked separately; the original #40
local-conversation scope has since closed, without accepting the whole product. The validation report records this separately
as `conversation_acceptance`, and any failure prevents a passing package report.

## Fixed-checkpoint operator entry

The verified development artifact for source `ed6bcdc15d883dc429f2dbb0559a62204965ab04`
(tree `24bae909c2caf97e11620a1d9a660cba22272670`) is
[`hermes-personal-agent-runtime-ed6bcdc15d883dc429f2dbb0559a62204965ab04`](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656/artifacts/13785725174).
It belongs to successful main [Foundation run 42859787656](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656),
artifact ID `13785725174`, and expires **2026-12-10 17:04:08 UTC**. Download may require
GitHub sign-in. This is a 30-day CI artifact, not a published release or permanent
update channel. Do not substitute a later artifact without a new review.

The downloaded ZIP SHA-256 is
`cf4fa2b3fdf55a53b42d29b5aa51889b42f5c46abe7d14ed6e6ce61a8bed9943`.
The tarball SHA-256 is
`e2be57dadc9cb4fedebb7b822d3a2553e8014b3b9ba25396a695da10d45a3e86`.
Independent read-only verification matched the ZIP digest, both inner checksums,
all 83 shipped source files against committed Git blobs, and the validation
report's provenance. No installation or model call was performed by that audit.
The report says `installation_performed: false`; real transport acceptance is
separate in the [fixed local M1 ledger](90-local-m1-acceptance.md).

### Verify, then stage a local Git source

Use a trusted source checkout containing that exact commit and the pinned host
`2281116525106e3c109993ccb5dc74d02bfc1427` with its officially prepared Python 3.14.9
environment. The [development setup](../README.md#development-checks) prepares the
host; it downloads dependencies, does not provision provider credentials, and is
not a requirement to use your daily profile. Stop older runtimes before upgrading
an existing memory store to the maintenance-lock-aware implementation.

After checking the ZIP digest, unpack it into a new directory. In that directory:

```bash
sha256sum -c SHA256SUMS
tar -xzf hermes-personal-agent.tar.gz
```

Set `SOURCE` to the absolute trusted source checkout and `RUNTIME` to the absolute
extracted `hermes-personal-agent` directory. Run the verifier **before** creating
`.git`: strict runtime verification intentionally rejects extra directories.

```bash
python "$SOURCE/scripts/build_runtime_distribution.py" --repo "$SOURCE" \
  --source-commit ed6bcdc15d883dc429f2dbb0559a62204965ab04 \
  --output-dir "$RUNTIME" --verify
git -C "$RUNTIME" init -b main
git -C "$RUNTIME" add .
git -C "$RUNTIME" -c user.name=Acceptance -c user.email=acceptance@example.invalid \
  commit -m 'test: stage verified runtime'
PACKAGE_COMMIT="$(git -C "$RUNTIME" rev-parse HEAD)"
```

The official `file://` installer clones a Git repository, not a plain extracted
folder. This local staging commit is distinct from the source commit recorded
in `PROVENANCE.json`; do not pass the original source SHA as the staged repository's
`--ref`. Keep `VALIDATION.json` and `SHA256SUMS` beside, not inside, the runtime tree.

### Isolated install and deterministic use

Use a fresh private profile and user home, never copy a daily `.env` or credentials.
Set `HOST`, `HERMES_PYTHON`, `PROFILE`, `USER_HOME` and `RUNTIME_DIR` to absolute
paths; create the last three as separate private directories. Run from `HOST`.
For **each** installation and subsequent command, use this same clean environment:

```bash
cd "$HOST"
env -i PATH="$PATH" HOME="$USER_HOME" LANG=C.UTF-8 \
  HERMES_HOME="$PROFILE" HERMES_RUNTIME_DIR="$RUNTIME_DIR" \
  "$HERMES_PYTHON" -m hermes_cli.main plugins install "file://$RUNTIME" \
  --ref "$PACKAGE_COMMIT" --yes-deps --enable
```

`--yes-deps` explicitly consents to the installer's normal dependency preparation;
`--enable` enables the reviewed plugin. Keep the official scan, catalog checks and
capability consent. A refusal stops this path: no `--force`, `--allow-removed`,
scanner edits or isolation downgrade. If dependency downloads need existing
approved proxy/CA settings, preserve only those settings explicitly, not a whole
daily environment; never disable TLS verification. The pinned tested lane is a
new trusted single-user in-process profile, not a change to an existing hosted
isolation policy. Other host versions require their own compatibility review.

In that isolated profile, preserve installer-created configuration and set only
this plugin's `mode: local_tasks` and `local_conversation: true` as shown in
[the local session guide](28-profile-first-local-conversations.md#2-enable-the-existing-session-entry).
Leave model tools, workers, memory, external connectors and providers off unless
separately requested. Repeat the clean environment prefix with
`"$HERMES_PYTHON" -m hermes_cli.main personal-agent tasks list` for deterministic
CLI use. In an admitted native LOCAL session use `/personal-tasks help` and then
`/personal-tasks add "Synthetic first task" --request-id first-task-1`.
Use returned IDs/revisions and stable retry keys. The CLI does not need a model;
the host's interactive UI may have separate prerequisites, and no provider is
configured by these steps. Task text is plaintext and can enter host history.
