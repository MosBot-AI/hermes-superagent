# Review-Only Host Command Context Experiment

English | [简体中文](README-zh.md)

## Status and provenance

This bundle preserves a local upstream prototype for review. It is **not installed, applied, shipped or enabled** by this project. The official compatibility pin and production plugin remain unchanged; protected reads remain disabled. There is no upstream PR, deployment or upstream publication implied by distributing this patch on the project feature branch.

- Official source: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent).
- Base: `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`.
- Local prototype: `adfb1feb207943d2bb539555adcbb667bcb571ab`, tree `2eed0582216b9bdec676ac9787f8a7cb724dbe54`, branch `prototype/verified-command-context`.
- That local commit is provenance, not a published commit link; the prototype has no configured remotes.
- Exact nine-file [patch](command-context-prototype.patch), SHA-256: `ab47d5f7c25c4cbc007332cb05e4f5dbf146ba701ef90cd77e09df10a5af1f20`.
- Upstream-derived code retains the [Hermes MIT license](LICENSE.hermes-agent).

[manifest.json](manifest.json) records source, patch and evidence hashes, changed files, historical results, limitations and future integration gates. [verification.json](verification.json) and [installed-packages.json](installed-packages.json) are unchanged historical receipts. The project commit/status in the former describes the earlier verification snapshot, not this branch's current tip. Full raw logs are not included because they contain machine-specific paths; these structured receipts are not independently reproducible full logs.

## What the prototype observes

The existing Telegram immediate command path captures direct human DM ingress after its existing gate. A short-lived receipt belongs to the original event, not a serializable SessionSource flag. It pins the receiving numeric Bot account, adapter generation, actor, original command, native routing identity and an existing matching live session entry. Unsupported, forwarded, edited, bot-authored, transformed, batched or restored events are ineligible; changed or cancelled events fail closed.

Native command dispatch provides an optional, signature-filtered `command_context`. Its one-shot `consume()` returns a versioned host transport observation or no observation. Scope exit retires retained handles. Hosted plugins receive a dedicated random host-owned ticket through the existing pipe; consumption checks invocation lifetime and host generation. Ordinary JSON, Record restoration, plugin names or RPC correlation origins cannot mint that ticket. New diagnostic paths avoid logging identity strings or token-bearing SDK URLs.

This is **not owner enrollment, an owner grant, Primary Bot identity binding, or full authorization**. A receiving Bot account observation is not canonical Primary Bot discovery. A live matching session is not proof of authenticated ownership. Consumed dictionaries are copyable data, never authority to accept back from a caller. No private read, native turn, external effect or permission is enabled.

## Evidence and its limits

Historical checks reported 70 new contract tests passed (35 producer/observation and 35 callback/IPC). The expanded selection reported **146 passed and 9 failed at environment setup**. Those nine temporary gateway control socket binds returned `EPERM` / `Operation not permitted`, before acceptance assertions. One historically permitted rerun of the three affected files failed the same way. These tests were not skipped, passed or resolved.

Affected files: `tests/gateway/test_cli_plugin_command_in_gateway.py` (six), `tests/gateway/test_cli_plugin_command_own_socket.py` (two), and `tests/gateway/test_plugin_command_choice.py` (one failure; its other test passed). This is not a full-green result. All 14 upstream static checks and the clean-base patch application check passed historically. Packaging does not rerun any upstream or identity/socket tests.

Tests used synthetic ingress fixtures, including native producer → gateway handler → real hosted child consumer. They did not validate live Telegram accounts, real polling/webhooks, network/TLS authentication, devices or remote CI. Python 3.14.9 and an observed 88-package PM environment were used; the fingerprint is not an attestation of exact lock equivalence. No API Key is needed for artifact review and a key would not fix the socket restriction.

## Remaining design and integration gates

1. Establish an upstream-supported **command-only** context seam. The prototype intercepts `command_context` across generic callable proxies; custom hooks using that keyword can behave differently hosted versus in-process. Resolve the collision and prove compatibility before adoption.
2. Provide monotonic policy, route, connection and session revision fencing. Snapshot equality does not detect historical A→B→A (ABA) changes and cannot close revocation/action races. One-shot consumption is not an atomic permission-to-action transaction.
3. Design first-session enrollment explicitly: first-ever commands without an existing native session receive no observation. Never compensate with a caller-supplied identity or restored flag.
4. Implement canonical Primary Bot discovery/binding, explicit owner enrollment and current persisted grants. Check owner, policy, grant, session and worker provenance atomically at each protected-read/action admission, with revocation and recovery behavior.
5. Review the same-UID/shared-process trust assumption. This is not a Python sandbox, per-plugin isolation within a shared host, or protection against malicious local OS peers. Official SDK endpoint configuration is not independent network attestation.
6. Separately review and authorize a suitable environment for the nine blocked socket tests; do not automatically retry them. Then validate live ingress and safe diagnostics through authorized secure setup, complete lifecycle/replay/cancellation/restart tests and release review.

This advances E0.7 feasibility evidence only. It does not complete E0.7, E1, Primary Bot binding or any private-read release gate. See [integration record](../../docs/23-host-command-context-experiment.md).

## Offline review and apply-check only

There is deliberately **no executable test runner** in this artifact. Project artifact tests inspect files and hashes only; they do not import or execute the patch. Do not copy the historical test selection into an automatic retry workflow.

For a non-mutating application check, independently prepare a trusted, disposable, credential-free Hermes Git checkout at the exact base. Do not use an installed Hermes, production profile, this project, or the official clean compatibility checkout. Review the patch and verify its hash before checking it:

```bash
set -eu
ARTIFACT="/path/to/hermes-superagent/experiments/command-context"
COPY="/path/to/disposable-hermes"
test "$(git -C "$COPY" rev-parse HEAD)" = 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
test -z "$(git -C "$COPY" status --porcelain)"
printf '%s  %s\n' ab47d5f7c25c4cbc007332cb05e4f5dbf146ba701ef90cd77e09df10a5af1f20 "$ARTIFACT/command-context-prototype.patch" | sha256sum --check -
git -C "$COPY" apply --check "$ARTIFACT/command-context-prototype.patch"
```

Stop if any guard fails. These commands neither apply the patch nor execute upstream code. They do not authenticate ignored content or hidden index changes; use a fresh trusted checkout. An apply-check proves patch applicability only, not behavior or security. Runtime application/testing requires a separate reviewed plan. Do not point the normal project checker at a patched tree or weaken its official-pin/cleanliness/unsupported-context expectations to make this experiment pass.
