# Reviewable Native Voice IPC Experiment

English | [简体中文](README-zh.md)

## Status and scope

The local Hermes prototype packaged here addresses a concrete compatibility gap: native speech consumers cannot use a hosted plugin's live ASR session or TTS iterator at the pinned upstream baseline. It adds a typed pipe bridge to those existing consumer paths. It is not another agent, an audio gateway, a new provider, or a working voice-call release.

The prototype is based on Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`, in branch `prototype/typed-voice-streams`. The prototype source is separate from the clean upstream checkout and the local identity prototype; that source has no Git remote. Its patch is now packaged in the Personal Agent development branch for review, without runtime integration. The local prototype commit below is provenance, not a published commit link. This directory packages the reviewed patch as an experiment only. No upstream publication, deployment, PR or merge is performed by this packaging work. The Personal Agent's official compatibility pin is unchanged.

## Implemented path

- Existing ASR consumer `tools.transcription_streaming.open_streaming_session` obtains a typed hosted `TranscriptionStreamSession`, feeds PCM, observes partial text and obtains the final envelope.
- Existing TTS consumer `tools.tts_streaming.resolve_streaming_provider` obtains a configured hosted `TTSProvider` and lazily pulls PCM through the existing streamer.
- Dedicated `voice_open`, `voice_op`, `voice_close` and batched `voice_release` messages use the existing per-profile plugin-host pipe. No new listener or transport is introduced by the bridge.
- Only the recognized ASR/TTS ABC and its corresponding stream method enter this path. Arbitrary callbacks, markers, annotations and unrelated return objects do not gain a general-purpose remote-object interface.
- Consumers close supported leases on completion, errors, cancellation, early exit and the native byte cap. Older in-process sessions/iterators without `close` remain supported.

## Bounds and lifecycle

The bridge limits one host to 32 active voice entries, each chunk to 1 MiB, cumulative audio per stream to 32 MiB, and encoded opening arguments or each accepted text field to 64 KiB. These are prototype compatibility limits, not negotiated production audio-profile limits.

TTS uses pull-based iteration: a request advances one chunk, with no eager iterator materialization. A session permits one operation in flight. ASR finalization is single-use. Invalid output, errors, closure, provider unload and host generation changes invalidate the affected handle; old streams are not resumed on a restarted host.

A timed-out or closed operation can still be executing inside its provider. Its entry continues to consume capacity until that call and optional cleanup return. Cleanup runs separately, preserving the profile context, so a blocking provider cleanup does not hold unrelated pipe calls. The close acknowledgement means a logical fence and scheduled cleanup, not that remote computation or billing stopped. Cleanup acknowledgements use a separate bounded wait. Garbage-collection release is best effort and is flushed on a subsequent host call, not an immediate cleanup guarantee.

## Verification interpretation

New tests use real `PluginManager` discovery, a separate plugin-host PID, the existing pipe, and existing native ASR/TTS consumers. Provider engines are deterministic fixtures, not real speech services. They verify transport, results, profile/provider resolution and lifecycle behavior rather than recognition accuracy, audible playback or latency.

The historical final selected runner was `run-tests.sh`; its results and environment fingerprints are preserved in [manifest.json](manifest.json). The portable runner here is `run_tests.py`, described below. A historical exploratory run also executed two existing loopback WebSocket STT tests successfully; those are not part of the final pipe-focused runner. The existing larger TTS suite was skipped because its module requires unavailable `numpy`. Neither fact is counted as full voice certification. The nine previously restricted identity socket tests were not run or retried.

A separately authorized follow-up used the same lock to build a fresh isolated PM environment with NumPy 2.5.4 and sounddevice 0.5.6. The previously skipped TTS file passed 44 tests with no failures or skips, including its loopback fixtures; provider/device behavior remains mocked. The original 88-package environment was unchanged. The new environment has 90 packages with no version changes to existing packages. This resolves the missing-NumPy test gap; it does not mean the full 164 distinct tests were rerun together in the new environment. Both fingerprints and the exact one-file scope are recorded under `numpy_tts_follow_up` in the manifest. The portable no-listener selection is unchanged.

## Remaining release gates

- This patch is not adopted by upstream or shipped by the Personal Agent plugin. Official-pin tests still correctly describe the old `Opaque` return boundary.
- Native ASR's feeder queue remains unbounded. Bridge limits do not establish end-to-end buffering, deadline or memory guarantees.
- The generic IPC exception envelope and thread dispatcher are unchanged. A per-profile plugin process is not a sandbox against hostile plugins or same-OS-user access.
- No owner identity, enrollment, permission grant, Primary Bot binding, private read, native turn, external effect, provider credential, microphone or device permission is added.
- No online provider, real ASR/TTS engine, audio hardware, actual call or latency/quality test was used. An API Key is not needed for the present verification.
- Before product activation: adopt a supported host seam, complete bounded native media admission/cancellation, identity/session binding and budget/privacy controls, then validate the selected actual provider and device through an authorized secure setup.

This advances the feasibility evidence for E0.8/E7.5. It does not complete either work package or start E7.6/E7.7 production rollout.

## Revision and results

Local commit: `40889c64e1e2fbf194ec7ece73a63e7d84c52420`. The 13-file selected run passed 120 tests with no failures and one module skip; the final two new files passed 17 tests after the last annotation-only edit. All 14 upstream static checks passed. Two reviewed catch-all annotations preserve required failure-envelope and best-effort-close contracts without adding provider-data logs. Patch application was checked against the clean baseline without modifying it.

## Review and manual reproduction

The exact seven-file patch is [typed-voice-stream-prototype.patch](typed-voice-stream-prototype.patch). Its SHA-256 is `3e49d2993c9d1eadc7cf3c65e3f0ba0e63a750040f2ef757db7dd4a93330d2df`. Upstream-derived material retains the [Hermes MIT license](LICENSE.hermes-agent). The manifest lists every artifact and changed upstream file. Nothing here is installed or applied by the plugin, its packaging, or its normal checker.

Use only a separately prepared **disposable, credential-free** Hermes Git checkout at the exact base. Do not modify the official clean compatibility checkout, an installed Hermes, a production profile or this project's checkout. Obtain the base and provision a Python 3.14 test interpreter separately through the upstream-supported workflow; this runner never fetches or installs dependencies. The historical environment fingerprint is provenance, not proof that your environment matches the lock.

After reviewing the patch, set absolute paths appropriate for your machine:

```bash
set -eu
ARTIFACT="/path/to/hermes-superagent/experiments/voice-ipc"
COPY="/path/to/disposable-hermes"
PYTHON="/path/to/prepared-test-venv/bin/python"
test "$(git -C "$COPY" rev-parse HEAD)" = 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
test -z "$(git -C "$COPY" status --porcelain)"
sha256sum "$ARTIFACT/typed-voice-stream-prototype.patch"
git -C "$COPY" apply --check "$ARTIFACT/typed-voice-stream-prototype.patch"
# Deliberate manual application, only in this disposable copy:
git -C "$COPY" apply --index "$ARTIFACT/typed-voice-stream-prototype.patch"
"$PYTHON" "$ARTIFACT/run_tests.py" --checkout "$COPY" --python "$PYTHON" \
  --disposable-copy --check-only
"$PYTHON" "$ARTIFACT/run_tests.py" --checkout "$COPY" --python "$PYTHON" \
  --disposable-copy
```

Stop if any guard command fails. Compare the printed checksum with the value above before applying. Do not commit the applied patch in the disposable copy: the runner requires HEAD at the exact base, an exact staged patch, no unstaged tracked changes and no untracked non-ignored files. `--check-only` does not execute upstream Python. The guard rejects assume-unchanged and skip-worktree index flags before comparing diffs. It compares only Git-visible tracked/staged source; it does not authenticate all on-disk or ignored content. Use a fresh trusted disposable checkout and a trusted prepared interpreter, never a production tree. The runner executes trusted reviewed test code, not a security sandbox.

The portable runner invokes the canonical upstream `bash scripts/run_tests.sh` with an explicit, already prepared `HERMES_PYTHON`, a temporary HOME/runtime path and a minimal credential-free environment. At this exact base the runner honors that interpreter when `pytest` imports. `__HERMES_TESTS_REEXEC=1` makes a failed environment check exit rather than enter provisioning; the explicit runtime path prevents discovery of the account's shared tool store. The wrapper first checks Python 3.14 and `pytest`. It never substitutes the internal dispatcher for the canonical runner.

`portable_test_files` selects **12 files**, excluding both `tests/tools/test_transcription_streaming.py` and `tests/tools/test_tts_streaming.py`, plus all identity socket tests. The historical TTS module was skipped because `numpy` was absent, but can create a loopback WebSocket listener when its dependencies are present. It must therefore stay outside this portable lane. The historical 13-file 120-pass/one-module-skip result remains historical evidence, not a promised result for this different selection. No listener test should be added without separate review. This packaging work has not rerun the voice suites.

The normal project checker continues to require the clean official pin and its `Opaque` compatibility boundary. Passing this patched copy to `scripts/check.py --hermes ...` is a mismatch: its source-cleanliness guard should reject it. Do not weaken those tests or substitute this experiment for official compatibility results. Reviewable evidence is not native integration or live-voice certification.
