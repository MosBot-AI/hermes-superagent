# 20. Offline Voice Contract Simulator

English | [简体中文](20-voice-contract-simulator-zh.md)

## 1. Implemented Scope

This is an offline development precursor for E0.8/E7.5, not working speech or calls. It implements strict synthetic media configuration, framing, bounded queues and lifecycle checks. The [production voice design](19-unified-voice-provider-contracts.md) still requires trusted identity, authorization, budgets, real provider adapters and device validation.

The production plugin registers no speech provider, microphone, audio device, HTTP endpoint or model tool for this feature. The self-test neither reads personal tasks nor submits a native turn. It uses only generated zero-valued PCM bytes in memory, never audio files, transcripts, accounts or credentials. Installing it does not change Hermes voice/provider settings. No API Key is needed.

## 2. Run the Local Self-Test

In an isolated, tested Hermes profile with this plugin enabled:

```bash
hermes personal-agent voice self-test
```

The native CLI is available only in the pinned host's `in_process` plugin mode. The host-isolated CLI is skipped by Hermes; do not disable isolation to get this command. Default `read_only` and explicit `local_tasks` modes can both run the diagnostic without opening task storage.

Success returns one JSON object with `schema_version: personal.voice.self-test.v1`, `status: ok`, `simulation: true`, a bounded `checks` list, `live_voice_enabled: false`, `microphone_used: false`, `provider_calls: 0` and `native_turns_submitted: 0`. The 23 fixed checks report individual boolean outcomes. A reported failure returns a nonzero exit code. This command accepts no provider, endpoint, key, audio-file, microphone or production-profile options.

`personal-agent status` separately reports the implemented synthetic check and disabled live capabilities. Passing it proves only the listed simulation invariants, not recognition accuracy, audible playback, latency, network compatibility or production authorization.

## 3. Narrow Simulation Contract

`personal_agent.voice` owns `SyntheticVoiceAdapter`, `simulation_config()` and `run_voice_self_test()`. Its schemas deliberately use `personal.voice.simulation-config.v1`, `personal.voice.simulation-frame.v1` and `personal.voice.simulation-capabilities.v1`. They are not aliases for the proposed production profile, audio or provider APIs in document 19.

| Area | Implemented constraint |
|---|---|
| Configuration | Exact field set and types; only `pcm_s16le`, 16000 Hz, mono and no turn detector |
| Frames | Exact integer duration of 10–60 ms; declared sample count and payload length must match; only zero-valued bytes accepted |
| Queues | Each direction is bounded by configured frame capacity, at most 500 ms; fractional frame capacity is rounded down |
| Ordering | Sequence starts at zero, increments by one and uses exact frame-duration timestamps |
| Duplicate handling | Only the latest accepted frame is retained for exact duplicate recognition; conflicts and older retries are rejected |
| Input gaps/overflow | Flush input and require explicit recovery; never label incomplete input committed |
| Output gaps/overflow | Flush output and advance its generation so late chunks cannot re-enter |
| Recovery | Compare the expected epoch, discard old fixtures, advance epoch/generation; only the immediately previous recovery retry is recognized |
| Interrupt | Stop simulated output, advance its generation and recognize an immediate retry; input is independent; native work interruption is always `unsupported` |
| Close | Terminal and idempotent; clears fixture queues and rejects later media/recovery |

Unknown fields/versions, bool-as-int, unsupported rates/channels, malformed lengths and non-silent payloads are rejected. No resampling or codec conversion occurs. A frame cannot become valid by changing its rate label. State and diagnostic output are bounded; snapshots contain only counters and simulation flags, never payload bytes.

The adapter is single-threaded. `append_input`/`append_output` queue fixtures; `drain_fixture` discards them and is not a device playback acknowledgement, ASR completion or native admission. `recover` creates a new simulated epoch, not resumed provider state. The versioned self-test is not a production service API or a general-purpose audio validator.

## 4. Verified Native Provider Boundaries

Pinned host: `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. New contract fixtures load synthetic providers through real `PluginManager` discovery and public `ctx.register_transcription_provider` / `ctx.register_tts_provider` calls. Their availability is explicitly false. They exist only in temporary test profiles, not production registration.

- ASR/TTS provider objects retain their expected ABC types in both tested modes. File-operation results cross the plugin-host pipe; TTS `ValueError` is preserved, while ASR uses its success/error envelope.
- The optional ASR stream is a one-utterance object. The fixture's single-use behavior is tested, not claimed as universal host enforcement for every provider.
- Streaming flags cross IPC, but the tested ASR stream-session object has no usable `push_audio`/`finalize` methods in the child-to-parent projection, and the TTS generator is not iterable there. A true flag does not establish usable isolated streaming.
- File-only ABC defaults reject streaming; no cancellation guarantee is supplied. Unknown capability queries return false.
- Built-in provider-name collisions are rejected. Unload removes the scoped providers. Registration does not change provider/model configuration.

These results do not prove that native Desktop built-ins cannot stream, or that every possible hosted streaming transport is impossible. They identify the tested plugin return-object boundary. Implement a supported streaming bridge or another verified native path before enabling that mode; do not turn off isolation or use a parallel privileged gateway as a workaround.

## 5. Tests and Remaining Gates

The repository checker runs offline unit tests, Ruff, ty, bilingual checks, native provider contracts and the actual top-level CLI in a guarded subprocess. Test inputs are generated fixtures. No socket listener, microphone permission, real audio, model weights, account or paid API is required for this slice.

The separate local identity prototype is not bundled or imported. Its unverified socket-dependent tests remain blocked and were not retried by this work. The production [owner boundary](18-owner-entry-and-read-authorization.md), Primary Bot binding and private reads remain disabled.

Before real voice: implement and verify the selected ASR/TTS or realtime bridge, identity/session binding, recipient and budget admission, controllable input/output leases, trustworthy playback accounting, native-turn cancellation and recovery. Then obtain any needed provider-specific credential through a secure handoff and run authorized device/live-provider tests. E0.8/E7.5 are partial work, E7.6/E7.7 remain Backlog, and no voice release gate is complete.
