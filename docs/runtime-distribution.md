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
Pull-request runs still check source contracts but do not publish a runtime package.
These are 30-day CI artifacts, not releases, signatures or installation approval.
Check the repository, branch, commit and completed workflow before trusting a download;
`PROVENANCE.json` and hashes prove correspondence, not authorship.

The artifact contains `hermes-personal-agent.tar.gz`, `VALIDATION.json` and
`SHA256SUMS`. The tarball contains the standalone `hermes-personal-agent/` directory.
Keep the validation report beside it, not inside the plugin. The GitHub artifact
ZIP digest differs from the inner tarball's SHA-256.

The push pipeline runs source and clean-host contracts first, then builds twice
from the exact checked-out commit, with no Git replacement objects. Archives have
sorted entries, fixed timestamps/owners and `0644` files / `0755` directories;
the two compressed archives must be byte-identical. It extracts the resulting
archive and verifies it again against the committed source before testing.

The unchanged pinned host's official `plugin_guard` scans the entire extracted
package. Its full findings are retained; only `safe` proceeds to package loading.
A safe verdict is **not zero findings**: the protective SQLite header/journal
bytes currently produce one medium obfuscation finding. No finding is suppressed,
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
