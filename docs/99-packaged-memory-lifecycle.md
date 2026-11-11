# 99. Packaged memory lifecycle acceptance

English | [简体中文](99-packaged-memory-lifecycle-zh.md)

## Scope and evidence

[Issue #139](https://github.com/MosBot-AI/hermes-superagent/issues/139) adds an explicitly run acceptance lane for the [observed-source retention commands](98-observed-source-retention.md) in the actual production runtime package. It uses the unmodified Hermes pin `2281116525106e3c109993ccb5dc74d02bfc1427`, the official installer and authenticated native Gateway transport in fresh synthetic profiles. No provider credential, model turn, real personal data or host patch is involved.

The test implementation is not itself a successful run. The Issue and linked PR record the exact source commit, package verification, executed tests, independent review and live workflow result. Passing unit checks of the workflow is static evidence only. A live failure remains a failure even if all contracts and package checks pass. This slice does not close [E2.6](https://github.com/MosBot-AI/hermes-superagent/issues/43), [E2.8](https://github.com/MosBot-AI/hermes-superagent/issues/45), model usefulness, automatic ingestion or production deployment.

## Real process and source lifecycle

The [packaged memory tests](../acceptance/live/test_packaged_gateway_memory.py) use the existing official-install fixture and real Gateway subprocess helpers. Session creation, resume and memory commands travel through native authenticated WebSocket RPC. Each restart stops the previous process and verifies a different process/instance; resetting an in-process plugin manager is not called a restart.

Synthetic original rows are added through public `SessionDB.append_message` while the Gateway is stopped. Native source review and retention then use `source-list`, `source-show`, `source-preview` and `source-retain`, with the exact reviewed snapshot, explicit retention choice and saved request key/digest. The test checks complete content, original role, observed provenance, exact retry and one completed cursor advance. No model is asked to manufacture a transcript.

After a full stop, public `SessionDB.clear_messages` removes the test session's original rows. The native database and session remain present so a new Gateway can actually resume that session. The new process must see no original rows, yet `source-status`, `source-cursor` and canonical record reads must recover the authorized independent snapshot. This is evidence of **missing original text**, not a missing native database, power failure or a native/current-at-commit guarantee. Existing white-box contracts separately check that metadata operations do not open native storage or hydrate record payloads; output inspection alone cannot establish those internal facts.

Canonical corrections and forgetting use the existing native commands. Fresh reads must show their current revision/status while the saved accepted decision remains historical. After another restart, newly seeded original rows containing the same exact text must be refused with `source_suppressed`, even with new message UIDs, request keys and consumers. Read-only database oracles check integrity, record/event/decision counts and forgotten payload removal. They do not write acceptance state.

## Pending setup is a separate SDK fixture

The production native `source-retain` command stages and accepts synchronously; there is no stage-only native command. For deterministic pending recovery, a separate fresh Python process loads the **installed package** through the real host loader and invokes the API-v1 `LocalMemorySDK` operation `source_stage` with a previously reviewed preview payload. Read-only loader introspection identifies the loaded package and verifies module paths; it is not a new public host API or mutation of host admission. This is trusted, explicitly bound synthetic SDK setup, not a forged receipt, direct SQL write or model-authorized import.

With the Gateway stopped, the test clears the original rows. A new Gateway then checks the pending decision and unchanged completed cursor, refuses a wrong digest, explicitly discards the exact saved key/digest and confirms terminal retry without a second cursor advance or new record. Fresh exact-content reentry is still suppressed.

This demonstrates recovery of a supported SDK-staged decision through real packaged native commands. It does **not** demonstrate killing the Gateway between the staging and acceptance commits. Existing low-level process fault tests cover their own transaction boundaries; neither lane should be relabeled as the other. No timing-racy kill, production monkeypatch or automatic unknown-outcome retry is used to fill that evidence gap.

## Reproduce in an isolated environment

The manual-only [Native Gateway workflow](../.github/workflows/native-gateway.yml) prepares the exact host/interpreter, builds and verifies the committed runtime, stages it as a local Git source and uses the unchanged official installation/scan path before running both task and memory acceptance. A scan or installation refusal stops the run. The previously refused full repository must not be installed, the scanner must not be changed, and existing isolation policy must not be weakened.

For a separately prepared local run, first follow the [runtime verification and staging guide](runtime-distribution.md#verify-then-stage-a-local-git-source) using the exact source commit under test instead of substituting the older task-only checkpoint. Supply absolute paths to the clean pinned host, verified and Git-staged runtime package, and prepared Python 3.14.9 interpreter:

```sh
export HERMES_TEST_ROOT="/absolute/path/to/pinned-hermes"
export HERMES_RUNTIME_PACKAGE="/absolute/path/to/verified-staged-runtime"
export HERMES_SOURCE_COMMIT="FULL_40_CHARACTER_TESTED_SOURCE_COMMIT"
"/absolute/path/to/hermes-test-venv/bin/python" -m pytest -q \
  acceptance/live/test_packaged_gateway_memory.py
```

These are explicit live tests, excluded from the default unit suite. Use disposable profiles only. If the environment refuses a native socket or installation step, retain the exact error and report live acceptance as blocked; do not bypass the restriction. JUnit artifacts contain synthetic test evidence, not provider logs or personal databases.

The 2026-11-11 local preparation run verified and officially installed the unchanged runtime from base main `48dfc8662226cb668e21b0fc434af4943c324470`; its official scan passed. The first Gateway exited before session creation because its private control listener returned `[Errno 1] Operation not permitted`. No memory command or recovery phase executed locally, and no socket bypass or retry was attempted. The separate GitHub-hosted workflow must provide exact-source live evidence; installation success does not replace it.

## Operator meaning

- Save the preview query before retention. After an uncertain result or source loss, inspect that original key/digest rather than inventing a new key or replaying unavailable text.
- Native source retention and canonical retention are independent. Deleting source text does not revoke a separately authorized canonical snapshot.
- Pending discard resolves the pending source decision and suppresses its exact text. It does not forget an accepted record; use canonical forgetting for that.
- Corrections, expiry and forgetting affect fresh reads. They do not retract previous model/client context, transcripts, backups or exports, and exact-text suppression is not semantic erasure.
- The result is bounded deterministic package/Gateway evidence. It is not broad lifecycle coverage, checkpoint-v2, live-model acceptance, remote-owner authorization or permission to deploy into a daily profile.
