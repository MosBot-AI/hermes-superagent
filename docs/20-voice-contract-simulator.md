# 20. Offline Voice Contract Simulator

English | [简体中文](20-voice-contract-simulator-zh.md)

A separate [review-only host patch](21-native-voice-ipc-experiment.md) demonstrates typed streaming across the existing pipe in a disposable prototype. It is not integrated or activated by this plugin; official-pin findings below remain unchanged.

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

### Current-Pin File Voice Dispatch

The [file-dispatch contracts](../tests/contracts/test_voice_provider_contracts.py) exercise the clean Hermes pin `2281116525106e3c109993ccb5dc74d02bfc1427` under Python 3.14.9. They call the native file entry points with synthetic providers registered through real `PluginManager` discovery in both `in_process` and `host` modes. Built-in TTS readiness and synthesis are substituted at their engine boundaries for the fallback cases. Tests use generated media and temporary profiles. Exact run results are tracked on [Issue #36](https://github.com/MosBot-AI/hermes-superagent/issues/36).

| Native path | Behavior covered |
| --- | --- |
| `tools.transcription_tools.transcribe_audio` | Explicit selection reaches the registered fixture when its availability probe returns true. The fixture receives the per-call model and configured language and prompt. An unavailable fixture, disabled STT or an explicitly selected unregistered provider returns a failure without switching to an automatically detected backend. |
| `tools.tts_tool.text_to_speech_tool` | The configured provider controls dispatch when a call supplies a different `provider` argument. Explicit selection reaches the registered fixture even when its availability probe returns false. The fixture receives the configured voice, model, speed and normalized output format. If the provider writes partial output before raising, the dispatcher returns an error, removes the staged partial file and preserves the existing destination. |
| `tools.tts_tool.check_tts_requirements` | Listing readiness returns false for the unavailable fixture and for an unregistered name. Direct file synthesis can still run in both cases, so the listing result is insufficient to establish direct-call behavior. |
| Built-in file TTS fallback | An unregistered configured name can select Edge synthesis while the success response still reports the configured name. If Edge is unavailable, the dispatcher can select local NeuTTS and report `neutts`. If neither is available, it returns an error. |

A file TTS caller needs to validate the configured route before dispatch when changing the engine or sending text to an online service requires consent. The reported provider can differ from the engine that ran. The tests call the native dispatchers directly and qualify the file paths in the table.

### Current-Pin Streaming Consumers

The [streaming contracts](../tests/contracts/test_voice_provider_contracts.py) use the same clean Hermes pin and temporary profile setup as the file contracts. Native consumers call synthetic providers registered by the real plugin manager in `in_process` and `host` modes. The fixtures use generated PCM and text.

| Native path | Behavior covered |
| --- | --- |
| `tools.transcription_streaming.streaming_available` and `open_streaming_session` | A selected plugin with `streaming_capable` can pass the probe and open a session even when its availability check returns false. Disabled streaming, disabled STT, a file-only provider and a missing provider return no stream. In process, the fixture returns partial and final transcripts for 16 kHz mono s16le input. The worker also converts 32 kHz input to 16 kHz, and the fixture receives the expected pairwise-averaged samples. In `host` mode, the consumer can open its wrapper and then return an empty-transcript failure when it accesses the projected session object. |
| ASR session cancellation | In process, cancelling while the synthetic provider is blocked in `finalize` makes the wrapper report cancellation. The provider can still finish after it is released. Its late result is suppressed by the wrapper in this tested sequence. |
| `tools.tts_streaming.resolve_streaming_provider` | A ready fixture resolves at its declared 22,050 Hz mono s16le rate. Its configured voice, model and speed reach the provider with the PCM format. In process the consumer reads the expected chunks. In `host` mode the call reaches the provider subprocess, then the first pull raises because the projected generator cannot be iterated. An explicitly selected unavailable, invalid-rate, file-only or missing streamer returns no streamer and does not substitute the configured ready provider. |

The ASR wrapper and TTS resolver are native consumer entry points for these tests. The plugin registration methods remain the public provider extension surface. A streaming capability, successful open or successful resolution alone gives insufficient evidence of usable audio in `host` mode.

### Current-Pin Playback and Interruption

The [speaker contracts](../tests/contracts/test_voice_provider_contracts.py) and [voice control contracts](../tests/contracts/test_native_voice_control.py) exercise the clean Hermes pin `2281116525106e3c109993ccb5dc74d02bfc1427` with synthetic PCM, a fake player and fake agents. The speaker contracts route through the native temporary WAV path and read the submitted file in the fake player.

| Native path | Behavior covered |
| --- | --- |
| `tools.tts_tool_speaker.stream_tts_to_speaker` | In process, the fake player receives the three expected 22,050 Hz mono 16-bit PCM frames. In `host` mode, iteration fails after the registered provider receives the call, yet the fake player receives a valid WAV header with zero frames. Both paths remove the temporary WAV and set the pipeline completion event. The failure stays on the streaming path, with no file-synthesis call in this test. |
| Local speaker stop during synthesis | The stop flag does not release the blocked synthetic provider. After the test releases it, the player receives no late PCM. A second WAV whose drain had already started reaches the fake player with zero frames. |
| TUI sidecar full-duplex interruption | Playback-phase interruption stops streaming and fallback media, then emits the interruption event. Generation-phase interruption also asks both running agents in the sidecar process to interrupt after stopping media. The idle agent receives no request. |
| TUI LOCAL typed-stop helper | The helper changes the target LOCAL session's voice mode. Stopping another session leaves the active capture callback usable. Stopping the capture's own session fences later callbacks. Both stops request TTS stop through the shared sidecar function. The test invokes the helper directly. Wire authorization and admission require separate evidence. |

The pipeline completion event and player invocation can both occur without any PCM reaching the player. Device playback acknowledgement, provider-side cancellation and confirmed native-turn cancellation remain open.

### Current-Pin Native Audio WebSocket Admission

The [audio ASGI contracts](../tests/contracts/test_native_voice_audio_asgi.py) send synthetic frames to the native dashboard app through `GatewayRuntimeAPI` on clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The harness uses the actual native ticket store and two temporary profiles. It mints synthetic local interactive tickets through the store and supplies a ready runner fixture.

| Native path | Behavior covered |
| --- | --- |
| Local WebSocket admission | A fresh interactive ticket opens the stream and negotiates `hermes-gateway-v1`. Missing and already-consumed tickets receive close code `4401` before any new provider call. The STT route also refuses a ticket with the wrong purpose, a selector for a different profile and an Origin-bearing local handshake. Synthetic provider markers identify the ticket's profile and its scoped configuration. |
| `/api/audio/transcribe-stream` | The registered in-process STT fixture receives the submitted 16 kHz PCM and configured hints. The route sends the final transcript envelope and closes. |
| `/api/audio/speak-stream` | The registered in-process TTS fixture receives the text and configured settings. The route declares 22,050 Hz mono output and sends the expected PCM chunks and end message. In `host` mode the provider receives the call, then stream projection fails at the first pull. The route sends a `fallback` message and closes. File synthesis and PCM output are absent in that exchange. |

The tests exercise the app boundary with in-memory ASGI messages. Ticket issuance by a trusted remote authority, a real listener, device playback, credential delivery, and live provider or device acceptance require separate evidence.

## 5. Tests and Remaining Gates

The repository checker runs offline unit tests, Ruff, ty, bilingual checks, native provider contracts and the actual top-level CLI in a guarded subprocess. Test inputs are generated fixtures. No socket listener, microphone permission, real audio, model weights, account or paid API is required for this slice.

The separate local identity prototype is not bundled or imported. Its unverified socket-dependent tests remain blocked and were not retried by this work. The production [owner boundary](18-owner-entry-and-read-authorization.md), Primary Bot binding and private reads remain disabled.

Before real voice: implement and verify the selected ASR/TTS or realtime bridge, identity/session binding, recipient and budget admission, controllable input/output leases, trustworthy playback accounting, native-turn cancellation and recovery. Then obtain any needed provider-specific credential through a secure handoff and run authorized device/live-provider tests. E0.8/E7.5 are partial work, E7.6/E7.7 remain Backlog, and no voice release gate is complete.
