# 23. Host Command Context Experiment

English | [简体中文](23-host-command-context-experiment-zh.md)

## Decision

Package the existing native-command provenance prototype as a [review-only experiment](../experiments/command-context/README.md), not as a plugin capability. The exact patch, Hermes MIT license, machine-readable source/hash manifest and historical evidence are versioned together. No executable runner is included. Normal installation and checks must not apply or execute it.

The official compatibility pin remains `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. The revised local prototype commit `b93642ca32739d4426293603e66175a72582de98` is provenance, not an upstream release or published commit. No private read, owner grant, account access, Primary Bot binding or external effect is activated.

## Evidence boundary

The native Telegram immediate human-DM path issues a short-lived original-event receipt, then a one-shot context. Hosted consumers use a host-held ticket through the existing pipe. This demonstrates a host transport observation seam, **not owner identity or authorization**. The observed receiving Bot ID is not canonical Primary Bot discovery. Restored JSON/Record data cannot replace the live handle; a consumed dictionary is only data.

Historical results are **70 new tests passed; 146 total passed and 9 failed at socket setup with EPERM**. The nine failures did not reach acceptance assertions; a historically approved rerun also failed. Fourteen upstream static checks passed. These remain historical structured receipts, not full-green upstream certification. Real Telegram ingress, network authentication, real accounts and remote CI remain unverified.

## Command-only revision evidence

The original `adfb1feb207943d2bb539555adcbb667bcb571ab` receipt is preserved separately. The revised patch selects only the exact handler bound by native `register_command`, with a dedicated `invoke_command` operation; generic callables retain ordinary `command_context` data and cannot import an observation descriptor. No new issue/export RPC is exposed. This removes a compatibility defect in the prototype, not the owner-authorization blocker.

A separately audited, socket-guarded run passed **87 tests** (35 producer, 35 existing host, 17 new regressions), plus all **14 static checks**. Production launcher/entry-point selection was retained; temporary test-only sitecustomize blocks networking in the child, with a verified guard marker and distinct PID. These tests overlap historical results and are not additive. The nine restricted socket cases were not run, and live ingress/full upstream acceptance remain unverified. The child ref table retains its existing cooperative-host trust assumption.

## Gates before integration

- Adopt a supported public command-only host seam. The local repair now limits `command_context` handling to the exact registered command handler; generic hook/tool keyword compatibility is tested, but upstream acceptance and per-plugin authentication are not implied.
- Add monotonic policy/route/session/connection revision fencing, including ABA changes, and atomic permission-to-read/action admission rather than relying on snapshot equality.
- Design first-session enrollment: this prototype requires an already existing matching live native session and does not bootstrap owner identity.
- Complete canonical Primary Bot discovery/binding, explicit owner enrollment, current persisted policy/grant checks, worker provenance, revocation and recovery.
- Review same-UID and shared-process trust: neither in-process Python nor plugins sharing a hosted process are mutually isolated by this seam.
- Separately authorize an appropriate environment for the nine unresolved socket tests, with no automatic retry. Validate actual ingress and privacy-safe diagnostics through secure setup before release review.

The artifact README contains bilingual design details and non-mutating `git apply --check` guidance for a separately prepared disposable checkout. Project static artifact tests verify inventory, hashes, historical classifications, licensing and absence of an executable runner; they do not execute upstream code. No API Key is needed for this review, and keys would not fix the socket restriction.

This advances E0.7 feasibility evidence only. E0.7, E1 and protected-read release gates remain open. The separate [voice experiment](../experiments/voice-ipc/README.md) does not supply missing identity/authorization guarantees. Do not combine the two patches or treat either as production support without integration review.

## Minimum gated end-to-end path

The first useful protected operation can be a bounded task-summary reply in a verified owner DM. It need not call a model, run a worker, inject a canonical turn or merge transcripts. This is a proposed sequence, not an enabled workflow:

1. Choose an explicit bootstrap authority. A possible design is trusted deployment-operator provisioning of an exact pending external issuer/actor/receiving-account allowlist, with scope, revision and audit receipt. This requires an explicit design/setup decision before use; local UID, a profile name or the first sender is not authenticated owner proof. Pending records cannot issue live contexts or grants.
2. Obtain independent current native ingress proof, including monotonic route/connection/session fencing and host-instance lifetime. If setup creates a normal DM session first, verify that session exists and require a fresh protected command afterward. No private output or first-message self-enrollment is allowed. A copied observation dictionary is never proof.
3. Match the live actor against the already authorized pending mapping, then confirm a short-lived actor/receiver/session/scope-bound challenge under current revisions. Session-exact grants cannot silently transfer to a replacement session.
4. Resolve and confirm the existing Hermes canonical Bot separately through a supported registry/route adapter. The Telegram receiving-account ID is not canonical Bot identity. The DM remains `owner_entry`; it does not become the canonical transcript.
5. Explicitly preview and adopt the task collection to expose. Current local tasks have no `owner_id` column or remote grant association. New enrollment must not silently acquire every existing local record. Use owner-scoped resources or a rigorously enforced single-owner authority/store, with migration and recovery rules.
6. Implement one defined authorized-read admission: consume live host proof, serialize host invalidation and database revocation with admission, load current persisted enrollment/binding/grant, and read only a bounded `tasks.summary` projection in a consistent resource/policy snapshot. Simply wrapping `evaluate_read()` around `TaskStore.run("list", ...)` is not atomic: the current store owns its own transactions, while host state lives elsewhere. Revocation before admission denies; a previously admitted read may finish, and a reply already handed to transport cannot be retrospectively withdrawn.
7. Validate restore/clone fencing and the supported deployment. A restored database's own old epoch cannot prove freshness; concurrent clones stay disabled without an external authority. Resolve the nine blocked tests only in a separately authorized suitable environment, then test secure real ingress and safe diagnostics before activation.

Unrestricted preparation can implement pending enrollment storage, versioned policies and admission contracts behind a disabled adapter. It must not manufacture remote authorization. Setup later requires the selected authoritative Bot/profile, exact external owner/receiver pair, explicitly adopted task collection and secure native account connection. No such deployment choice, credential setup or permission grant has been made by this patch. Provider API keys do not fix missing identity or the socket restriction.
