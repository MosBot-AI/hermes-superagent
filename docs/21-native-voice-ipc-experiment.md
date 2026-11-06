# 21. Native Voice IPC Experiment

English | [简体中文](21-native-voice-ipc-experiment-zh.md)

## 1. What Is Included

A [reviewable patch and verification manifest](../experiments/voice-ipc/README.md) preserve a tested, separate Hermes host prototype. **The patch is not installed, imported or applied by this plugin.** It is not an upstream release or an integrated Personal Agent voice feature. The project's official compatibility baseline remains `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`.

The [official-pin contract tests](20-voice-contract-simulator.md) still correctly observe unusable `Opaque` stream return objects. The experiment shows a concrete adaptation path beyond that limitation; it does not rewrite the baseline's behavior or make production voice available.

No main-branch merge, upstream contribution, deployment, provider account, microphone permission or actual call is part of this artifact. It needs no API Key.

## 2. Actual Native Consumer Paths

The patch changes existing host behavior rather than adding another simulator or an agent loop:

- ASR: `tools.transcription_streaming.open_streaming_session` obtains a typed hosted `TranscriptionStreamSession`, feeds PCM and receives partial/final text through the existing isolated plugin-host pipe.
- TTS: `tools.tts_streaming.resolve_streaming_provider` obtains the configured hosted provider; the existing streamer pulls PCM incrementally instead of receiving an unusable iterator placeholder.
- Dedicated `voice_open`, `voice_op`, `voice_close` and batched `voice_release` messages carry only the recognized ASR/TTS stream contracts. They do not create a general remote-object interface.
- Native consumers close supported leases on completion, errors, cancellation, early exit and byte-cap termination. Legacy in-process objects without `close` remain compatible.

These native consumer functions are host implementation paths, not newly declared public plugin APIs. The public ASR/TTS registrars are producer registration surfaces; they do not establish a general `ctx.voice` consumer facade. Host-isolated plugin CLI registration is still unsupported. Do not import internal dispatchers or disable isolation to pretend those gaps are solved.

## 3. Bounds and Lifecycle

The prototype limits active handles/sessions to 32 per host, a chunk to 1 MiB, cumulative audio to 32 MiB per stream, and opening arguments or each accepted text field to 64 KiB. Those are compatibility limits, not the production profile negotiation in [19](19-unified-voice-provider-contracts.md).

TTS advances one chunk per pull, with no eager materialization. Each session permits one operation in flight; ASR finalization is single-use. Invalid results, errors, close, unload and host-generation changes fence affected handles. Old streams do not resume automatically after a host restart.

Closing requests a logical fence and schedules cleanup. It does not interrupt blocking provider computation, prove cleanup completed or stop billing. Busy computation and cleanup continue occupying child capacity until they return. Cleanup is separate from unrelated pipe calls; close acknowledgements have a bounded wait. Garbage-collection release is best effort, flushed by a later host call. The parent bounds pending handle/release bookkeeping and retries uncertain cleanup acknowledgements without reviving the stream.

## 4. Verified Evidence

The patch was tested in a disposable exact-base source copy with real plugin discovery, a distinct child PID, the existing pipe and the native consumer paths above. Engines were deterministic fixtures, not actual speech services.

- Selected regression run: 120 tests passed, no failures, one module skipped across 13 files.
- The two new bridge/consumer files contain 17 passing tests, also rerun after the final annotation-only edit. They are included in the 120, not 17 additional distinct tests.
- All 14 upstream static checks passed. Two reviewed catch-all annotations preserve the native failure-envelope and best-effort-close contracts without adding provider-data logs.
- The skipped larger TTS module requires unavailable `numpy`. A historical exploratory run separately passed two existing loopback WebSocket STT tests; those are excluded from the final pipe-focused runner. The nine restricted identity socket tests were not run or retried.
- A separately authorized follow-up prepared a fresh PM environment from the same lock with NumPy 2.5.4 and sounddevice 0.5.6. The previously skipped TTS file then passed 44 tests, with zero failures/skips. Its loopback fixtures passed; real providers/playback remain mocked. The original environment and runtime dependencies were unchanged. This resolves the missing-NumPy test gap, not the product gates, and is not a rerun of all 164 distinct tests in that new environment. The manifest preserves both environment fingerprints.
- Patch checksum, exact base and local prototype revision are recorded in the experiment manifest. The local prototype revision is provenance, not a published upstream commit link.

The regular project checker continues to require clean official-pin sources. It must reject the patched copy. Use the experiment's separate review instructions; do not relax `compatibility.json` or edit the expected `Opaque` test to manufacture a pass.

## 5. Remaining Product Gates

The native ASR feeder queue remains unbounded. Bridge limits do not establish whole-pipeline buffering, memory, concurrency or deadline guarantees. Generic IPC exceptions and dispatch remain unchanged, and a per-profile plugin process is not a hostile-plugin or same-OS-user sandbox.

No production identity issuer, owner binding, private read, permission grant, Primary Bot activation, native turn, external effect or device access is added. No actual recognition accuracy, audible playback, latency, online service, billing or mobile-device behavior was validated.

Adopting a supported host seam, completing media admission/cancellation and identity/session/budget/privacy controls, then validating an explicitly chosen real provider and device are separate steps. This artifact advances E0.8/E7.5 evidence only. E7.6/E7.7 production rollout remains Backlog, and no voice release gate is complete.
