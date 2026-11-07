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
remain incomplete. The worker experiment is excluded and unsupported by the
pinned production host. The package registers no worker and changes no provider.

Official Git-subdirectory installation exists, but is not performed here. It
still requires unchanged scanning, consent and PM admission; dependency-free does
not guarantee an offline or environment-neutral installation. Update support for
subdirectory packages remains unverified.
