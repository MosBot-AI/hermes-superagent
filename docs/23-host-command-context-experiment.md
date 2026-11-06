# 23. Host Command Context Experiment

English | [简体中文](23-host-command-context-experiment-zh.md)

## Decision

Package the existing native-command provenance prototype as a [review-only experiment](../experiments/command-context/README.md), not as a plugin capability. The exact patch, Hermes MIT license, machine-readable source/hash manifest and historical evidence are versioned together. No executable runner is included. Normal installation and checks must not apply or execute it.

The official compatibility pin remains `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. The local prototype commit `adfb1feb207943d2bb539555adcbb667bcb571ab` is provenance, not an upstream release or published commit. No private read, owner grant, account access, Primary Bot binding or external effect is activated.

## Evidence boundary

The native Telegram immediate human-DM path issues a short-lived original-event receipt, then a one-shot context. Hosted consumers use a host-held ticket through the existing pipe. This demonstrates a host transport observation seam, **not owner identity or authorization**. The observed receiving Bot ID is not canonical Primary Bot discovery. Restored JSON/Record data cannot replace the live handle; a consumed dictionary is only data.

Historical results are **70 new tests passed; 146 total passed and 9 failed at socket setup with EPERM**. The nine failures did not reach acceptance assertions; a historically approved rerun also failed. Fourteen upstream static checks passed. No identity/socket tests are rerun by this packaging work. These are historical structured receipts, not new execution or full-green upstream certification. Real Telegram ingress, network authentication, real accounts and remote CI remain unverified.

## Gates before integration

- Resolve the generic `command_context` keyword collision by restricting IPC interception to explicit command invocations and testing hosted/in-process compatibility.
- Add monotonic policy/route/session/connection revision fencing, including ABA changes, and atomic permission-to-read/action admission rather than relying on snapshot equality.
- Design first-session enrollment: this prototype requires an already existing matching live native session and does not bootstrap owner identity.
- Complete canonical Primary Bot discovery/binding, explicit owner enrollment, current persisted policy/grant checks, worker provenance, revocation and recovery.
- Review same-UID and shared-process trust: neither in-process Python nor plugins sharing a hosted process are mutually isolated by this seam.
- Separately authorize an appropriate environment for the nine unresolved socket tests, with no automatic retry. Validate actual ingress and privacy-safe diagnostics through secure setup before release review.

The artifact README contains bilingual design details and non-mutating `git apply --check` guidance for a separately prepared disposable checkout. Project static artifact tests verify inventory, hashes, historical classifications, licensing and absence of an executable runner; they do not execute upstream code. No API Key is needed for this review, and keys would not fix the socket restriction.

This advances E0.7 feasibility evidence only. E0.7, E1 and protected-read release gates remain open. The separate [voice experiment](../experiments/voice-ipc/README.md) does not supply missing identity/authorization guarantees. Do not combine the two patches or treat either as production support without integration review.
