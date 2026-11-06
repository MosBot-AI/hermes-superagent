# 19. Unified Voice Session and Provider Contracts

English | [简体中文](19-unified-voice-provider-contracts-zh.md)

**Status: proposed design, not implemented.** Users may select local speech processing, configured online speech APIs, or a supported realtime speech-to-speech service through one application-level interface. This document defines new plugin-owned contracts, not an existing Hermes `VoiceProvider` API. No microphone, provider account, live audio API or paid call was used to prepare this design. No real-device latency/accuracy certification is implied.

This scope is an in-app live voice conversation and voice messages, not a PSTN dialer or permission to call third parties. Hermes remains the personal agent and tool authority. The voice layer does not replace the main Bot, native session runtime, authorization, worker routing or credential system. Read [07](07-mobile-and-voice.md), [14](14-client-api-contracts.md), [15](15-primary-bot-binding.md) and [18](18-owner-entry-and-read-authorization.md) for those boundaries.

## 1. Decision: One Contract, Explicit Capabilities

Unify **session lifecycle, audio metadata, events, cancellation, recovery, authorization and metering**, not vendors' wire protocols or quality claims. Three adapter families share the contract:

| Family | Data path | Required distinction |
|---|---|---|
| `pipeline` with local components | Microphone → local VAD/ASR → native Hermes turn → local TTS → speaker | Local built-ins may be file/utterance based, not true incremental streaming |
| `pipeline` with online or mixed components | Microphone → selected ASR → Hermes → selected TTS | ASR and TTS can have different recipients, regions, prices and failure modes |
| `realtime_frontend` | Microphone ↔ configured speech-to-speech service; work requests go to Hermes | Frontend and Hermes are different model roles; protocol-specific delegation and recovery need explicit adapters |

ASR and STT mean the same speech-recognition stage here. Users select a named, tested **voice profile**, not an arbitrary API URL expected to work everywhere. Each profile specifies adapter/protocol family, model/version constraints, components, voices, transport, allowed data destinations, credential references, limits and authorized fallback order. Choosing an OpenAI-compatible transcription/TTS endpoint does not prove compatibility with OpenAI Realtime, GPT-Live, Gemini Live or another realtime protocol.

Installation changes no current provider, model, credential path, microphone permission or fallback policy. Setup shows which components run on the device, Hermes host and external services. Enabling an online profile requires the user's permitted data-sharing and spending scope. An unavailable or unknown selected backend fails visibly; it never silently selects a different online service.

## 2. Verified Native Foundation and Gaps

Hermes source baseline is `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. The following are source-verified facts, not certification of this plugin:

| Existing native surface | Reuse and limit |
|---|---|
| `TranscriptionProvider`, `ctx.register_transcription_provider` [V1] | File transcription plus optional one-utterance stream; stream input is 16 kHz mono s16le PCM; final result is an envelope, not a raising method |
| `TTSProvider`, `ctx.register_tts_provider` [V2] | File synthesis, optional PCM streaming with declared sample rate, warm/release; streaming must be thread-safe; failure conventions differ from ASR |
| `/api/audio/transcribe-stream` and `/api/audio/speak-stream` [V3] | Native audio streaming has specific frame/control formats; not arbitrary plugin WebSockets or a unified realtime provider registry |
| Local faster-whisper/local command and NeuTTS/KittenTTS/Piper paths [V4] | Current built-in local ASR falls back to utterance files; listed local TTS paths use sentence synthesis rather than guaranteed chunked PCM |
| Native microphone endpointing/barge-in [V4] | RMS/silence and playback-aware detection exist; a public interchangeable neural `VADProvider` registrar was not found |
| `voice.voice_chat_mode: gpt-live` [V5] | Specific client-delegation protocol: host exchanges SDP, Desktop owns WebRTC, delegation enters Hermes and commentary returns to the voice frontend; not a generic realtime API bus |
| Native chained client-direct and relay modes [V6] | Some Desktop/serve/dashboard paths can return long-lived provider keys to trusted client memory; the `webapp` surface forces relay; these are different security properties |
| Native interruption paths [V7] | Playback stop and agent interruption are only partly separated; one TUI path interrupts all running sessions. Existing provider ABCs do not guarantee a cancellable blocking finalize |

New `VoiceSessionAdapter`, component-VAD interface and unified controls below are **proposed internal interfaces**. Reuse the existing ASR/TTS registrars where their semantics fit. Do not shadow built-in provider names or import the internal streaming `@register` decorator as a public plugin ABI. If supporting a new realtime backend requires a generic host voice-session extension, specify and test that seam with this concrete consumer before enabling it.

An isolated dashboard plugin HTTP response is buffered and cannot be assumed to carry SSE/WebSocket/audio streams [14](14-client-api-contracts.md). Prefer proven native audio/media transports and a small control adapter. Missing trusted session identity, profile routing, streaming or cancellation support is a release blocker for that mode; do not turn isolation off, create a parallel privileged gateway, or treat a hosted-authentication boolean as an owner principal.

## 3. Components, Configuration and Negotiation

### 3.1 Proposed voice profile

```json
{
  "schema_version":"personal.voice.profile.v1",
  "id":"voice_local_example",
  "revision":1,
  "family":"pipeline",
  "adapter_id":"native_pipeline_bridge",
  "components":{"asr":"configured_local_asr","tts":"configured_local_tts","vad":"configured_local_vad"},
  "audio_network_policy":"local_audio_only",
  "transport_preference":["native_host_stream"],
  "turn_detection":"local_vad",
  "fallback_policy":{"automatic":false,"approved_profile_ids":[]},
  "limits":{"max_call_seconds":1800,"max_utterance_seconds":60,"input_buffer_ms":500,"output_buffer_ms":500},
  "retention":{"raw_audio":"ephemeral_tempfile","debug_capture":false}
}
```

These limits are proposed defaults, not native/provider limits. A realtime profile selects an explicit realtime adapter and configured model instead of an ASR/TTS component pair. Optional namespaced provider options are allow-listed, versioned and schema-validated; unknown fields are rejected, not forwarded as arbitrary API arguments. Secrets and raw URLs are not client command fields. The server resolves reviewed endpoint and credential references.

`local_audio_only` means speech processing does not send raw audio to an external API; it does **not** mean the Hermes language model, tools or whole assistant are offline. Text sent to a cloud Hermes model is a separate disclosed data path. Fully offline operation needs local agent/tool dependencies too. “Local” identifies the selected device/host, not necessarily the phone: remote Hermes-host ASR still sends microphone audio over that trusted host connection.

Local model/engine installation remains explicit. Record code and model-weight licenses, source/checksum, hardware/memory requirements, startup/download costs and verified language support separately. Use reputable supported packages; do not assume a model license follows its code's license. Downloading a model is not a latency/quality benchmark, and naming a plugin does not prove it is installed.

### 3.2 Capabilities are negotiated, not inferred

Each adapter exposes a versioned descriptor with: family/protocol revision; deployment modes; input/output encodings, rates and channels; streaming/partial/final transcript support; turn-detection owners; cancellation; playback accounting/reconciliation; resume/context-restore behavior; session/deadline limits; usage units; credential-delivery modes; supported locales/voice IDs; and documented privacy/data recipients.

Example capability fragment:

```json
{
  "schema_version":"personal.voice.capabilities.v1",
  "adapter_id":"example_realtime_adapter",
  "family":"realtime_frontend",
  "protocol_revision":"reviewed-adapter-revision",
  "transports":["provider_websocket"],
  "input_formats":[{"encoding":"pcm_s16le","sample_rate_hz":24000,"channels":1}],
  "output_formats":[{"encoding":"pcm_s16le","sample_rate_hz":24000,"channels":1}],
  "turn_detection":["provider_vad","manual"],
  "transcripts":{"input":"optional_partial_final","confidence":"unavailable"},
  "interruption":{"generation_cancel":true,"playback_reconciliation":"explicit_played_offset"},
  "recovery":{"provider_resume":false,"safe_context_restore":true},
  "usage_units":["input_audio_tokens","output_audio_tokens"],
  "credential_delivery":["host_only"],
  "verified":false
}
```

This is illustrative, not a claim about any named vendor. A session opens only when required features intersect with tested adapter, host and device capabilities. The response names the **selected** profile revision, actual codec/rate, protocol, transport, VAD owner, semantic-submission owner, limits, privacy scope and fallback policy. No valid intersection returns `voice_capability_unavailable`; there is no guessing or implicit reinterpretation.

Keep `installed`, `configured`, `credential_resolvable`, `health_checked` and `certified_for_mode` separate. Native GPT-Live `available` checks whether a key resolves, not whether the account, endpoint, model or network actually works [V5]. Health checks must not start paid calls or transmit sample audio without authorization; a provider's catalog `is_available()` remains local/non-networking.

## 4. Proposed Uniform Adapter Contract

All names in this section are project-owned design. Adapter failures normalize to typed errors while preserving the native provider's actual failure and retry semantics. An unsupported optional method returns `unsupported`; it must not simulate success.

| Method | Contract |
|---|---|
| `describe()` | Return static/local capability metadata without credentials or network calls |
| `open(trusted_context, negotiated_config, open_key)` | Reserve budget, bind one native conversation and open the selected media path; return session handle and actual negotiation |
| `append_audio(handle, frame)` | Bounded audio input for the declared stream epoch; no hidden format conversion or transcript submission |
| `end_input(handle, utterance_id, end_reason)` | Close one utterance according to the sole turn controller; partial text is not automatically a native command |
| `submit_backend_output(handle, request_ref, output)` | Speak/relay authorized Hermes output under the current generation; distinguish literal TTS from model paraphrase |
| `interrupt(handle, target, interrupt_id)` | Target playback, provider generation, native turn, or explicit domain effect separately; return requested/confirmed/unsupported/unknown for each |
| `ack_played(handle, output_ref, played_boundary)` | Record actual device playback progress when the transport can measure it; not merely bytes received |
| `reconcile_interruption(handle, output_ref)` | Repair provider conversation state where supported; return exact/provider-managed/approximate/unsupported result |
| `recover(handle, last_control_cursor, recovery_key)` | Reauthorize and reconcile; either resume verified provider state or open a marked new media epoch with safe context |
| `close(handle, reason, close_key)` | Idempotently stop capture/media and release leases; separately report whether native work remains active |

The proposed VAD component contract consumes declared-format frames and emits activity/timing observations. It cannot identify the owner, approve actions, submit native turns or decide who may interrupt. The ASR bridge normalizes native envelope errors; the TTS bridge catches native synthesis exceptions and honours concurrency constraints. If a native stream has no inner cancellation method, stopping delivery drops late output but may leave compute running until its deadline. Report that cost/resource condition; do not label it cancelled.

One live call binds to one verified owner/profile/native session and, where used, one Primary Bot binding epoch. Changing the foreground tab or default profile cannot retarget it. Multiple viewers may observe only with host permissions; only one capture/turn-control lease owns input. Device handover revokes the old lease and creates a new media epoch before accepting new input. Unverified cross-device handover is unavailable.

## 5. Audio Frames, Flow Control and Events

### 5.1 Media envelope

For project-controlled byte streams, use explicit metadata:

```json
{
  "voice_call_id":"call_example",
  "stream_id":"mic_example",
  "stream_epoch":2,
  "utterance_id":"utterance_example",
  "sequence":41,
  "timestamp_us":820000,
  "sample_count":480,
  "format":{"encoding":"pcm_s16le","sample_rate_hz":24000,"channels":1},
  "payload_bytes":960
}
```

The payload is binary, not embedded in JSON in the preferred transport. Timestamps are relative to the stream's monotonic clock. Validate sample alignment, length, rate/channels, sequence and maximum frame size before decoding. A proposed PCM framing target is 20 ms, negotiated within 10–60 ms, with a 64 KiB per-frame ceiling. WebRTC RTP/codec negotiation is handled by the WebRTC stack; do not wrap RTP in this JSON format or send WebSocket audio commands over an unrelated data channel.

Actual resampling is required between device rates, native ASR's 16 kHz format and vendor-specific formats. Merely changing a rate label corrupts audio and timing. Preserve sample-count/played-offset mapping through conversion. Native TTS output may reveal its rate on the first audio chunk; do not assume all providers emit 24 kHz. Opus voice-message files are not live PCM call frames.

Bound input/output queues by negotiated duration and bytes, with high/low watermarks, backpressure and cancellation priority. Do not build unbounded queues during a network stall. If input loss or overflow makes an utterance incomplete, emit `audio_gap`, end/discard that incomplete segment and request repetition; do not silently commit it as complete. On output interruption flush queued audio and reject late chunks from an older generation. A partially heard answer must not restart from the beginning after a streaming error.

### 5.2 Separate durable control from ephemeral media

Control events use `schema_version`, `voice_call_id`, `event_id`, monotonic control `sequence`, `stream_epoch`, applicable `utterance_id/request_id/output_id`, `native_admission_ref`, `occurred_at` and a typed payload. Exact retries deduplicate by event/command identity within the bound authority. Provider IDs are correlated, never used as owner identity. Schema major versions are negotiated and unknown command fields rejected.

Event families are `call.ready/state_changed/closed`, `capture.started/stopped`, `speech.started/ended`, `transcript.partial/final/corrected`, `request.proposed/admitted/settled`, `audio.started/chunk/ended`, `generation.finished`, `playback.progress/finished/stopped`, `interruption.requested/reconciled`, `usage.updated`, `recovery.required/restored`, and `error`. `generation.finished` does not mean playback finished, and neither means an external action succeeded.

Persist minimal call/control state, native admission references, effect receipts and budget records. Raw audio/chunks and partial captions are ephemeral by default and are **not** the durable domain change feed. The optional API in [14](14-client-api-contracts.md) may expose authorized call summaries/invalidations; replaying that feed does not replay microphone audio. Redacted control replay can request a snapshot when a cursor expires. It cannot resurrect old grants or synthesize unheard audio as already delivered.

Full duplex needs orthogonal states: connection (`opening/ready/recovering/closing/closed/failed`), capture (`off/listening/muted`), input activity, provider generation, native turn and playback. Listening, generating and playing can overlap. Do not encode correctness in one exclusive listening/thinking/speaking enum.

## 6. Turns, Hermes Ownership and Action Safety

Exactly one negotiated controller owns utterance commit: local VAD, provider VAD or push-to-talk/manual. Additional VAD may observe metrics or suppress echo but cannot independently commit. AEC, noise suppression, echo-safe barge-in and short pre-roll are explicit component capabilities, not implicit benefits of having VAD. Speaker diarization/voice similarity is not authentication. Mute stops capture/transmission, not just the UI meter.

Exactly one semantic-submission path owns each request: finalized ASR for a pipeline, or verified frontend delegation for realtime mode. Do not admit both an ASR transcript and a realtime function/delegation event for the same utterance. Map each logical request to one stable native admission key and receipt, independent of reconnecting provider session IDs. Partial transcripts only update captions. Final text corrections carry a new revision and an explicit relation to the original request; they never silently repeat an accepted action.

In `realtime_frontend`, the online model may handle greetings, clarification and conversational delivery within the approved scope. Factual work, memory, planning, tools and controlled actions remain Hermes responsibilities. The adapter exposes only a constrained backend-delegation bridge; provider tool calls are **proposals** evaluated by Hermes. Disable provider-hosted tools or direct service credentials that bypass that boundary. A provider without a verified delegation/proposal bridge cannot advertise equivalent personal-agent realtime capability.

The frontend receives only consented context, not the whole profile or tool catalog. Native session ownership and owner provenance still need proof under [15](15-primary-bot-binding.md) and [18](18-owner-entry-and-read-authorization.md). The caller saying “I am the owner,” a speaker match, transcript text or a model-generated tool argument cannot fill missing identity. Voice cannot turn a blocked trusted-context seam into permission.

Separate the **voice frontend model**, **ASR/TTS component models**, **native Hermes turn model**, and **worker model routing**. The pinned chained implementation can use `auxiliary.voice_chat`, while GPT-Live delegations take a different path [V8]. The chosen effective model and recipient must be visible and governed by policy; unified voice must not silently change main/worker models or claim E9 covers these calls.

For recipients, amounts, dates, destructive actions and disclosures, construct the exact typed intent and confirmation preview through the planned shared policy service. ASR confidence is optional/unknown when the provider does not supply it. Transcription from speech-to-speech models is not guaranteed to represent exactly what the audio model inferred. Voice paraphrase is not an approval record: preserve exact structured details in the trusted UI, and use a supported verified approval channel. Ambiguous speech, background speakers, a replayed recording or a casual acknowledgement cannot expand authorization. Corrections invalidate affected stale intents.

## 7. Interruption, Stop and End-Call Semantics

| User/control event | Required behavior |
|---|---|
| Stop playback / barge-in | Mute local playback immediately, flush output queue, fence old output generation, request provider-generation cancellation and reconcile what was heard |
| Explicit stop-current-work | Also request interruption/cancellation of the **bound native turn** through its supported control path; report its receipt/state |
| Explicit cancel external action | Use the domain effect's separately authorized cancellation/reconciliation contract; stopping audio is not rollback |
| Mute microphone | Stop capture/transmission; keep receive/playback behavior explicit; do not cancel accepted tasks by implication |
| End call | Close media and revoke the capture lease; show any native tasks still running; do not claim that all work was cancelled |

Barge-in policy may also request cancellation of the bound native turn when configured, but never iterate over unrelated sessions. The pinned TUI's broader interruption behavior is a compatibility limitation, not the desired contract [V7]. An adapter unable to target interruption safely must disable that coupled action and expose the narrower playback-only behavior, rather than advertising full isolation.

Track generated, transported and actually played audio boundaries separately. Where supported, send the played boundary back to the provider and truncate/reconcile unheard output. Realtime services differ: OpenAI WebSocket uses explicit playback accounting/truncation, while some WebRTC paths manage it provider-side; Gemini does not expose an identical OpenAI-style truncation contract [V9]. Capabilities state `exact`, `provider_managed`, `approximate` or `unsupported`. If provider state cannot be reconciled safely, discard that media context and restart with a marked, approved safe summary, or fall back to text.

Cancellation results are typed: `requested | confirmed | unsupported | already_terminal | unknown`, with target scope and observation time. A cancel ACK does not prove a remote action was undone or provider billing stopped. Late audio/transcripts/tool proposals from a cancelled generation are discarded or retained solely for reconciliation; they cannot create new native commands.

## 8. Recovery, Fallback and Session Limits

The application `voice_call_id` outlives network connections; provider session IDs and media epochs may change. Keep credential expiry, new-session deadline, call deadline, provider session lifetime and resume-handle expiry separate. Provider APIs have different limits and can change them; use adapter-versioned negotiated values, not one universal “token TTL.” A short-lived credential may permit multiple or overridable sessions, so it is not itself an action or budget boundary [V10].

On disconnect: stop stale playback, prevent new semantic submissions, preserve native receipts, and show recovering/offline. Use bounded jittered retry under the reconnect deadline. Revalidate credential, owner/profile, binding epoch, grants, budget and target before resuming. A refreshed token does not restore a revoked grant.

If a provider has tested resume support, use only its latest applicable handle and declared resumability rules. Treat handles as secret session material. Otherwise start a new provider session and announce a discontinuity; restore only authorized, committed context and actual playback boundaries. Never blindly replay uncertain audio, old tool requests or accepted native turns. OpenAI Realtime, GPT-Live and Gemini Live are separate protocol families, not interchangeable reconnect strategies [V9, V10].

For an interrupted uncommitted utterance, request repetition unless exact resume is proven. For a native request whose ACK was lost, query its stable receipt before resubmitting. Native work may continue after the browser disappears; on reconnect show its true state rather than starting another turn.

Fallback is an explicit allow-listed policy with destination, mode, data classes, limits and voice/model changes. No silent local-to-cloud or cross-vendor audio/context transfer. Preserve the selected provider for sentence/file fallback when authorized, without replaying partially heard audio. Switching provider mid-utterance or after uncertain work first requires reconciliation; a new profile starts a new media epoch. If required semantics or permission are missing, stop safely or downgrade to push-to-talk/text and explain the actual limitation.

Online failure, rate limits, unknown engine names and missing local models must not trigger the native unknown-TTS-name path into an unintended online default [V4]. The unified selector validates exact provider identity before calling the native dispatcher. A strict local-audio policy tests outbound network containment, not only prompt settings.

## 9. Privacy, Credentials and Deployment

Default to no durable raw-audio retention and no transcript/audio content in operational logs. The example's `ephemeral_tempfile` policy permits bounded temporary media needed by native file-based ASR/TTS: use private access-controlled storage, a documented processing deadline, deletion on completion/error, startup/crash cleanup and exclusion from backups where supported. Explain any platform exceptions, user-saved recordings, native transcripts and provider retention. Strict `memory_only` may be negotiated only after all components and fallback paths are verified not to write persistent storage, or use an explicitly verified RAM-backed path with matching swap/crash guarantees; otherwise reject that requirement or select a different implementation. Deleting a disk file after processing is not an in-memory guarantee. Provider data use varies by endpoint, account tier, region and resume settings; no generic zero-retention/training promise is made [V11]. Resuming cloud sessions can retain more context than stateless ASR.

Before online activation, disclose who receives microphone audio, transcript, selected context, synthesized text and provider metadata; why; region/retention where verified; and applicable costs. Reuse valid approved scope, but a materially different recipient/data class or broader sharing needs authorization. Background capture and bystanders require explicit UX and permissions; never enable always-listening/wake-word capture merely by installing the plugin.

Resolve durable keys through Hermes's existing profile-scoped secret/auth mechanisms. Store opaque credential references, not new credential copies, keys in project YAML/JSON, browser storage, URLs, telemetry or model context. Use host relay or a tested provider bootstrap/ephemeral credential path by default. TTL/config constraints must be checked against the real API, not assumed to be single-use or unchangeable. Bootstrap must preserve host authentication, Origin/CSRF checks, rate/budget admission and target/profile binding.

Native trusted Desktop client-direct mode can expose actual long-lived keys to client memory, while GPT-Live's host SDP exchange and the `webapp` relay path differ [V5, V6]. Supporting that legacy mode requires explicit trusted-device selection and documented key lifetime/cleanup; it is not the default for a new mobile/browser adapter. Do not describe all browser-served Hermes surfaces as inherently key-free. Do not silently overwrite another profile's existing voice settings to enforce this plugin's preference.

Reviewed endpoint references allow local inference or online services, but are not arbitrary URL proxies. Enforce scheme/host policy, TLS verification, redirects and credential-to-origin binding; block metadata/loopback/private-network SSRF unless the local endpoint is explicitly configured and verified. Keep credentials off redirected origins. Protect WebRTC signaling/ICE/TURN data and temporary credentials; TURN/egress can carry separate cost and network privacy implications. No credentials or full SDP in routine logs.

A remote host cannot capture the phone's microphone by itself. Capture and playback permission/device selection belong to the actual client, with lease release on close/background/revocation as supported. Validate browser autoplay, headphones/Bluetooth, mobile suspension, network switching and proxy/WebSocket/WebRTC behavior. Do not promise background calling or handset support from a desktop-only test.

## 10. Cost, Telemetry and Quality Gates

Use a pre-admission budget per call and owner, covering ASR, TTS, realtime duration/audio tokens, native Hermes turns, auxiliary calls, worker calls and any relay/TURN charges. Preserve provider-native usage units and the price/config revision. Estimated, provider-reported and settled charges are separate fields; unknown usage is not zero. No static vendor price or model name in this design is a purchase commitment.

Set bounded call/utterance/output/idle durations, concurrency and rate limits. Reserve conservatively before paid bootstrap or generation, then reconcile actual usage. Exhausted or unverifiable required budget stops new paid admission and requests teardown; unavoidable in-flight usage remains visible. A retry, fallback or extra reviewer call consumes budget too. Closing the local socket does not prove the provider has stopped billing, particularly with direct credentials; disclose limits of hard-stop enforcement and use provider-side quotas where available.

Default telemetry is redacted metadata: adapter/protocol/model revision, host/device mode, negotiated format, stage timings, queue depth, dropped frames, VAD events, interrupt-to-local-silence, native admission and outcome refs, reconnect/discontinuity counts, fallback reasons and usage. Do not log audio, transcript content, speaker biometrics, keys, resume handles or full provider error bodies. Opt-in diagnostic capture has its own clear retention/access controls.

Measure p50/p95 separately for capture/end-of-speech → final ASR, native admission → first model output, synthesis → first audible playback, and interruption detection → local silence. Use monotonic clocks and explicit clock alignment across client/host; do not subtract unrelated wall clocks. Separate cold-start and warm latency, local hardware, network class, language and utterance length. An initial tuning objective is p95 local mute within 100 ms after detection and warm first audible response within a defined test budget; neither is a certified promise until measured.

Evaluate Chinese CER/WER as appropriate, names/numbers/timezones/recipient slot accuracy, correction success, silence hallucination, echo/false interruption, noisy-room and accent cases, and task outcomes. Transcript accuracy alone does not certify realtime-model intent interpretation. Compare each adapter on the same disclosed test set while retaining its actual feature differences. Do not market a file-based local engine as equivalent latency to native streaming, or a fast acknowledgement as a completed backend answer.

## 11. Errors and Acceptance Matrix

Normalize errors to `code`, `stage`, `scope`, `retryable`, `retry_after_ms?`, `provider_code?`, `outcome_known`, and a bounded redacted message. Codes include `voice_identity_unavailable`, `voice_capability_unavailable`, `voice_format_mismatch`, `voice_audio_gap`, `voice_budget_exceeded`, `voice_provider_unavailable`, `voice_cancel_unconfirmed`, `voice_resume_unsupported`, `voice_context_discontinuity`, `voice_epoch_conflict` and `voice_privacy_scope_required`. Native and remote failure details stay available in protected diagnostics without exposing secrets. Retryability never bypasses authorization or uncertain-effect reconciliation.

| Scenario | Required assertion |
|---|---|
| Local pipeline, online pipeline, realtime frontend | Same lifecycle/event contract; capabilities and unsupported operations remain truthful |
| Unknown provider, missing local model, strict local policy | No silent online fallback or unintended network transmission |
| Rate/channel/codec mismatch, odd bytes, oversized/gapped frames | Reject or actually convert as negotiated; bounded memory; no incomplete utterance admission |
| Local and provider VAD both fire; partial/final/revised transcript | One turn controller and one semantic submission per logical request |
| ASR and realtime delegation both see the same utterance | One stable native admission/receipt, not two executions |
| Barge-in during playback/generation/tool work | Immediate local mute; scoped cancellation; truthful external effect state; no unrelated-session interruption |
| Late audio, partial audio failure, unsupported truncation | Fence stale generations; no whole-answer replay; declared reconciliation/discontinuity |
| Blocking native finalize or synthesis ignores cancel | Delivery stops, resource/usage remains unconfirmed until settled; no false cancellation claim |
| Lost ACK, network switch, expired token, stale resume handle | Reauthorize; recover native receipts; no blind audio or tool replay |
| Browser close/end call while Hermes works | Media closes independently; native work remains queryable and correctly labelled |
| Two devices/tabs or primary Bot changes mid-call | Capture lease and binding epoch prevent wrong-profile input/output |
| Spoken amounts/recipient corrections, replayed/bystander approval | Exact current intent and trusted approval; no voiceprint or transcript-only authority |
| Online recipient/region change, fallback, data retention choice | Required sharing approval and budget precede transmission; no silent expansion |
| Host isolation, unsupported media route, missing owner provenance | Affected feature disabled, no private IPC/DB bypass or default owner |
| Rate limit, exhausted budget, lingering provider session | Stop new admission, bounded teardown/reconcile and accurate cost uncertainty |
| Phone suspension, Bluetooth echo, proxy/TURN, reconnect storm | Tested platform-specific degradation and resource cleanup; no unsupported universal claim |

Use fake transports/engines and synthetic audio first; record exact adapter/native SHA, protocol/API version, model, host/client/OS, device, language, network and tested modes. Real-provider probes can incur charges/share audio and require authorization. Physical-device and production certification are separate. Existing local-task, authorization, source-inspection or document checks do not complete these tests.

## 12. Work Packages and Enablement Order

| ID | Status and narrow dependencies | Deliverable |
|---|---|---|
| E0.8 Verify Voice Provider Contracts | M0; Backlog; E0.1/E0.2; use E0.4/E0.7 identity findings where applicable | Pinned ASR/TTS/native audio/live-protocol matrix, credential/cancel/stream probes, public adapter seams and unsupported modes |
| E7.5 Define Unified Voice Session Contract | M2 (M1 design prework); Backlog; E0.8, E1.1/E1.2/E1.4/E1.5; E0.6 only for optional HTTP facade | Versioned profiles/capabilities, audio/control schemas, leases, author/turn ownership, budget and privacy policy; synthetic reference adapters |
| E7.6 Implement Local and Online Voice Adapters | M3; Backlog; E7.5, E7.1/E7.2/E7.3; E1.3 and relevant E0.4 coverage for enabled actions | One local/mixed pipeline and one explicitly selected online realtime adapter, native integration and capability-specific controls; no broad provider equivalence |
| E7.7 Validate Duplex Recovery and Voice Quality | M3; Backlog; E7.6, E6.4, E8.1/E8.2 harness; E3.5/E4.4 for linked task/effect recovery | Device/latency/accuracy, barge-in, playback repair, reconnect, budgets and privacy tests; documented per-mode release gates |

Extend E7.1–E7.4 rather than replacing the working voice-message plan: unify their ASR/TTS configuration and safety semantics, keep voice-message MVP and live duplex separate, and retain optional realtime validation. E9 remains worker-model routing; voice providers do not silently select that backend. Bot-bound calls additionally need the applicable E0.7/E1.6/E3.6 gates, without making every voice message depend on optional Bot enrollment.

This design does not block the local task inbox or require a custom mobile app. All new packages remain Backlog. Start with a capability-negotiated pipeline, add one verified online realtime family, then expand adapters only with protocol/privacy/cost evidence. Complete the plan and document interfaces now; do not enable microphone capture, paid sessions, new grants or runtime features merely because the design is approved.

## 13. Evidence and Version Notes

- V1: [Native transcription provider and live-stream contract](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/transcription_provider.py#L19-L66) and [public registrars](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_registrars.py#L74-L84).
- V2: [Native TTS provider contract](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/tts_provider.py#L26-L106) and [streaming provider bridge](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/tts_streaming.py).
- V3: [Native audio HTTP/WebSocket routes](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/audio.py) and [streaming ASR wrapper](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/transcription_streaming.py).
- V4: [Local ASR](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/transcription_local.py), [TTS selection and fallback](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/tts_tool.py), and [native recorder/VAD](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/voice_mode.py).
- V5: [GPT-Live-specific bootstrap](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/voice_live.py) and [Desktop WebRTC/delegation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/lib/voice-live.ts).
- V6: [Client-direct credential configuration](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/voice_client_config.py), [native voice-config route](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/audio.py#L152-L180), and [serving-surface policy](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server_surface.py#L50-L72).
- V7: [Native stop/barge-in scope](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tui_gateway/methods_voice.py#L194-L323) and [gateway streaming delivery](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/streaming_tts_consumer.py).
- V8: [Voice turn model routing](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/voice_turn_route.py).
- V9: [OpenAI Realtime conversations and interruption](https://developers.openai.com/api/docs/guides/realtime-conversations), [WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=realtime), and [Gemini Live protocol](https://ai.google.dev/api/live).
- V10: [OpenAI client-secret contract](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create), [Gemini ephemeral tokens](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens), and [Gemini session management](https://ai.google.dev/gemini-api/docs/live-api/session-management).
- V11: [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data), [Gemini zero-data-retention limitations](https://ai.google.dev/gemini-api/docs/zdr), and [Gemini terms](https://ai.google.dev/gemini-api/terms).

Online documentation was checked on 2026-11-06. Some Gemini evidence came from indexed official excerpts where full-page retrieval was unavailable. It is documentation research, not a live compatibility test. Recheck current provider/API/account terms and adapter fixtures before deployment; do not copy old prices, token TTLs or model availability into permanent guarantees.
