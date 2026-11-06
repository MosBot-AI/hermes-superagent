# Changelog

English | [简体中文](CHANGELOG-zh.md)

This file distinguishes design work, development changes, and released capabilities. There is no production release yet.

## Unreleased

### Added

- E0 native plugin foundation with a read-only readiness tool and an `in_process` CLI.
- Strict read-only configuration and argument validation. No personal-data or external-action tools.
- Pinned Hermes compatibility metadata, real discovery/dispatch/reload/unload/Doctor contracts, synthetic unit tests, and offline test guards.
- Reproducible check script and SHA-pinned GitHub Actions workflow.
- macOS and Windows system-file ignore rules, preserving existing Python rules, with Git behavior tests.
- Separate English originals and `-zh` Chinese README, changelog, and all design documents with language links.
- E0.4 synthetic failure-boundary contracts covering policy callbacks, dispatcher/middleware failures, direct registry dispatch, and managed/safe worker configuration.
- A read-only blocked-write inventory and `personal-agent coverage` CLI; no write authorization or host-wide enforcement is added.

- Detailed bilingual client/connector API design: plugin HTTP namespace, host authentication seams, canonical session transport, durable changes, approval/idempotency/recovery semantics, and explicit native-mobile blockers. No HTTP endpoints are implemented.
- E0.6 and E6.5–E6.7 work packages, with E5.1/E5.2 connector contract details.
- JSON-example syntax validation with regression tests; this does not validate API schemas or runtime behavior.

- Opt-in `local_tasks` CLI inbox with plugin-owned SQLite, stable request receipts, compare-and-set revisions, explicit completion/cancellation, bounded pages and terminal-state checks.
- Profile/mode gates, private POSIX main/sidecar files, unsafe-link/permission rejection and database ownership/schema checks; default diagnostics remain storage-free.
- Synthetic concurrency/rollback/storage tests, real-host CLI lifecycle tests and guarded top-level CLI subprocesses.
- Separate bilingual primary Bot binding design, including conditional E0.7/E1.6/E3.6 work packages; no binding code is enabled.

- Local date-only deadlines and bounded agenda, with explicit set/clear/view dates and existing idempotency/revision gates; no clock inference or reminder delivery.
- Atomic exact-schema v1→v2 upgrade preserving legacy digests/receipts, with rollback, concurrent-upgrade and old-request replay tests.

- Owner-entry diagnostics, an internal read-authorization evaluator and native context/IPC contracts; missing receiving-Bot provenance explicitly blocks private reads, with no production identity or grant issuance.

### Boundaries

- E0.3, full E0.4 coverage, E0.6, identity/authorization, full domain storage, reminders, connectors, mobile, voice, and E9 model routing remain unimplemented.
- Local task storage is a trusted-local-operator feature, not owner authentication, native task execution or an OS sandbox. Windows storage, encryption, export/forget and full retention policy remain unsupported.
- The plugin does not secure other Hermes tools. The status reports a blocked release gate.
- Full install transactions and isolated-host execution have not been validated. The host-isolated CLI is unsupported by the pinned host.

## Design baseline: 2026-11-06

- Documented the Hermes-native personal-agent architecture, DSH research, authorization/revocation semantics, reliable delivery, memory, mobile/voice, and E0–E8 roadmap in commit `c254c86a17c61e1bd13d74d00d5b44016abab13d`.
- Added the native worker model/effort routing design, shadow-first rollout, host constraint gaps, open-source comparisons, and E9.1–E9.6 work packages in commit `e4eb446c0d0c20d3ce83aa20f7b5139261d593f9`.
- Those commits delivered designs and plans, not running product features.
