# 07. Mobile and Voice

English | [简体中文](07-mobile-and-voice-zh.md)

## 1. Entry-Point Strategy

The first phase prioritizes reusing Hermes’s official gateway messaging channels so users can start/continue tasks, check status, confirm controlled actions, receive reminders, and send voice messages from a phone. Desktop/CLI remain entry points for the same Hermes owner/profile; do not launch a separate personal agent for mobile.

Also reuse the native web dashboard/desktop pages for settings, sessions, Projects, Kanban, cron, and MCP. The new personal overview provides only an aggregate view of “today, projects, commitments, pending confirmations, reminders, and connection health.” Build an additional mobile PWA/native shell only when actual experience and permission models in existing entry points cannot meet requirements.

This does not claim that a complete official iOS/Android personal-agent app already exists. The current source has mobile messaging entry points, web/desktop, and multiple voice paths. Responsive layouts, notifications, background audio, authentication, and compatibility with target phones require real testing.

## 2. Channel Capability Matrix

| Capability | MVP approach | Required verification |
|---|---|---|
| Mobile text conversation | Deliver one officially supported channel first | Owner ID, thread routing, out-of-order/duplicate events, message length |
| Tasks and reminders | Native gateway delivery + domain references | Unknown delivery, offline recovery, cross-topic routing |
| Action approval | Available native approval UI, domain binding to the exact intent | Button replay, expiration, forwarding, identity mismatch |
| Voice messages | Native STT → Hermes turn → optional TTS | Chinese, recognition errors in names/times, file size, latency |
| Real-time voice | Later reuse supported Hermes voice paths | Device/browser compatibility, barge-in, recovery, cost |
| Mobile overview | Existing web entry point first; plugin UI if needed | Small screens/touch, keyboard occlusion, error/empty states, authorization |

Choose the primary channel based on services the user already uses and deployment conditions. Do not assume a particular region/account has access. New platforms use official platform adapter/plugin contracts and must not bypass service platform rules.

## 3. Continuity Model

`Owner → Verified Channel Binding → Hermes Profile → Session/Thread → Project/Task`.

The owner may designate an existing native Bot Mode Bot as the primary coordinator; its canonical Bot Chat is not automatically the mobile channel's conversation. Default continuity shares authorized domain tasks/facts, not transcripts or complete prompts. Selecting the same profile through `profile_routes` does not merge Telegram/Discord/Desktop sessions. Exact same-conversation attach/handoff needs a separately verified native path. The proposed binding and recovery contract is in [15](15-primary-bot-binding.md).

Switching channels does not automatically merge full transcripts. Continue through explicit task references and bounded handoff summaries; original and new sessions retain their own routes, participants, and permissions. Mentioning a private project name in a group must not load all personal data. If “that task” on mobile is ambiguous, return a short candidate list rather than guessing a sensitive target.

Messages include `client_message_id/platform_event_id` for request deduplication, and notifications carry stable task/automation references. Repeated taps on a weak connection must not create multiple tasks, approve repeatedly, or send duplicate messages. Once approval is processed, other devices promptly show it as handled and reject a second execution.

## 4. Voice Is an Interaction Layer, Not a Permission Shortcut

The native chained path is STT → Hermes turn → TTS. The source also describes a Desktop full-duplex voice front-end that delegates tool work to Hermes. A fast-response front-end may use an explicitly configured speech API, but must not hold independent authority or service credentials for executing personal actions or bypass the main agent's action gate.

The proposed [unified voice contract](19-unified-voice-provider-contracts.md) supports interchangeable local ASR/TTS/VAD, configured online pipeline APIs and explicitly adapted realtime speech-to-speech. A common session/audio/event interface negotiates real capabilities rather than pretending all backends have equal streaming, latency, cancellation or recovery. Voice API configuration does not change the selected primary Bot or silently select a new main/worker model.

Retain provenance and transcription confidence/correction information for each voice message, but do not retain raw audio long-term by default. If critical fields such as amounts, times, recipients, names, deletions, or outbound actions are misrecognized, display or read out structured confirmation. Ordinary queries do not require mechanical repeated confirmations; high-risk actions cannot expand scope merely because the voice model heard “mm-hmm.”

An explicit “stop the current work” during speech stops playback and requests cancellation of the bound native turn. Playback-only stop, barge-in, microphone mute and end-call have distinct semantics in [19](19-unified-voice-provider-contracts.md). **Stopping speech does not mean the external operation is cancelled.** The UI distinguishes cancel requested from cancelled, reports already-submitted actions truthfully, and must not interrupt unrelated sessions.

## 5. Credentials and Audio Paths

In this baseline, official Desktop remote can obtain STT/TTS settings and actual provider credentials from the gateway and call the provider directly. The native `webapp` surface forces relay; other serve/dashboard surfaces do not automatically share that restriction. GPT-Live's host-side SDP exchange is a separate key-handling path. These modes do not have identical security properties. [Native voice notes](09-upstream-evidence.md#h12-voice)

This project’s mobile web defaults to host relay or provider-supported short-lived, least-privilege session credentials rather than distributing long-lived provider keys to the browser. If adopting an existing client-direct path, explicitly define device trust, in-memory lifetime, transport protection, and user choice. Microphone access, recording, background playback, and third-party audio processing must comply with applicable permission and privacy requirements.

## 6. Securely Exposing the Web Entry Point

Use only Hermes’s existing authentication/session mechanisms, exposed through verified TLS/trusted reverse proxies. Do not simply bind the dashboard to `0.0.0.0` and make it public. Verify that the auth gate is actually enabled, along with CSRF/CORS, session expiration, logout/revocation, attachment access, and webhook authentication. Health checks must not leak configuration or personal content.

The MVP does not require custom push infrastructure. If the platform lacks reliable delivery, show the true status rather than promising guaranteed delivery within seconds. Mobile OS background limits, network switching, and browser autoplay are test concerns, not problems an agent prompt can solve.

## 7. Voice/Mobile Acceptance Scenarios

1. Create a project on desktop and check its progress on mobile: both read the same domain object.
2. A mobile voice request, “Remind me at nine tomorrow morning,” resolves the timezone correctly and can be confirmed/changed/cancelled.
3. Resending the same message after disconnection and repeatedly tapping confirmation produces only one action.
4. If a recipient or time is misrecognized, the user’s correction invalidates the old intent.
5. Interruption during playback, interruption during tool execution, and recovery after going offline never falsely report successful cancellation.
6. Forwarding the owner’s old approval into a group or another participant saying “continue” cannot trigger restricted actions.
7. Audio processing failure falls back to text without blocking existing tasks.
8. After logout or device revocation, old WebSockets/sessions and pending approvals cannot continue writing.

Complete acceptance testing on the user’s actual target devices and primary channel before promising wider compatibility. Scope the first-release mobile voice-message workflow and later real-time voice separately, rather than presenting “has STT” as “a telephone-style real-time assistant is complete.”
