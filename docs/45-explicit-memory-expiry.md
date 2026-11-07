# 45. Explicit Memory Expiry

English | [简体中文](45-explicit-memory-expiry-zh.md)

Explicit expiry adds a time eligibility boundary to local memory records. It does not schedule deletion, infer a retention period or activate a provider. Existing [local-memory opt-in](31-explicit-local-memory.md), [model-tool activation](32-session-scoped-memory-tools.md) and [native-provider admission](41-native-memory-recall.md) still apply independently.

## 1. Save a Temporary Trip Plan

These synthetic examples use an explicit UTC deadline. Choose the actual deadline yourself; a phrase such as “until my trip ends” does not supply a timestamp. Use the returned record ID and latest revision, not the placeholders below.

```text
/personal-memory remember "Trip plan: take the airport train" --topic trip --expires-at 2026-12-01T18:00:00Z --request-id trip-plan-1
/personal-memory show RECORD_ID
/personal-memory correct RECORD_ID --expires-at 2026-12-02T18:00:00Z --expected-revision N --request-id trip-plan-2
/personal-memory list --include-expired
/personal-memory search "Trip plan" --include-expired
/personal-memory correct RECORD_ID --clear-expiry --expected-revision N --request-id trip-plan-3
/personal-memory forget RECORD_ID --expected-revision N --request-id trip-plan-4
```

Before the deadline, the trip note is eligible for ordinary search and recall. At the deadline it stops appearing in ordinary list/search and fresh recall. Inspect it with `show` or explicit `--include-expired`. If the trip is extended, correct its deadline. Clear expiry only if the note should again be eligible without a time limit. Use `forget` to remove its canonical payload rather than merely hide it from recall.

`--expires-at` accepts only a valid canonical UTC second, `YYYY-MM-DDTHH:MM:SSZ`. Date-only values, local times, numeric offsets, fractional seconds and relative durations are rejected. A past deadline is valid and makes the record immediately ineligible. There is no inferred TTL. `correct` accepts expiry alone or alongside text/topic changes; `--expires-at` and `--clear-expiry` are mutually exclusive. Omitting expiry preserves it on correction and means no expiry on remember.

## 2. Model Tools and Inspection

The separately activated memory write tool accepts optional `expires_at` on `remember` and `correct`: a canonical UTC string sets it; JSON `null` clears it. Omission preserves an existing correction target's expiry. Remember defaults to no expiry. This record deadline is separate from the tool session's activation TTL; neither extends the other. Models must not invent deadlines or silently clear them.

The read tool accepts `include_expired: true` only for explicit list/search inspection. Its default is false. Native commands use `--include-expired` for the same operations. `show` and `export` include expired records without that option; existing tombstone behavior is unchanged. There is no include-expired override for bounded recall or the native provider.

Record rows add `expires_at` (string or null) and computed `expired` (boolean). Record pages and recall results add `evaluated_at`, the operation's captured UTC wall-clock evaluation time. These are additive fields in the existing runtime v1 API and `personal.memory.record_page.v1` export contract. Export is still bounded, `restorable: false`, and not a portable backup. Mutation receipts remain metadata-only historical receipts, not current eligibility readbacks.

## 3. Time Is Not a Stored Status Transition

An active record is expired when `expires_at <= evaluated_at`. Each operation captures trusted UTC wall-clock time once, after actually acquiring its SQLite snapshot, so lock waits cannot leave it using a stale pre-wait time; a caller cannot supply its own evaluation time. Filtering and the computed flags use that time together with the operation's database snapshot. Ordinary list/search exclude expired records; explicit bounded recall and native-provider recall always exclude them before ranking and budgeting.

Stored status remains `active` or `forgotten`. Passing a deadline creates no revision, event, receipt, background job, scheduler or daemon. The payload remains stored. A wall-clock rollback can make a still-active record eligible again; expiry is not an irreversible deletion guarantee. Extending or clearing expiry is an explicit revision-checked write and can restore eligibility. A forgotten ID is terminal and cannot be revived by correction. Forgetting clears expiry as well as the canonical payload.

No expiry operation erases prior host transcripts, returned results, exports, backups or model-provider copies. A pack returned before expiry can remain in the model's context and host history after the deadline. Fresh recall exclusion is not a promise to retract earlier disclosures or to remove all future replay of old context.

## 4. Migration, Retries and Adapter Compatibility

The owned local SQLite store uses schema v5. A permitted store-opening command or already-activated model-tool operation atomically upgrades exact owned v1–v4 stores, preserving existing events, mutation receipts, consumer cursors and checkpoint receipts. For a deliberate operator upgrade, use `/personal-memory list`. Existing records start without expiry. Unsupported or malformed storage fails closed; migration is not a cross-profile import or a repair workflow.

The native read-only provider never creates or migrates a store. It refuses an old schema until a permitted store-opening command or activated model-tool operation upgrades it; fresh permitted recall can then resume. This feature does not install or select a provider, change configuration, switch models or change credentials.

Explicit new request fields require the optional `record_expiry` adapter capability, including an explicitly supplied null or false. Old adapters without this capability are not silently given new fields. Legacy requests that omit the new fields keep their old request digests and replay behavior. Reuse the same request ID and identical payload for an uncertain mutation; changed payload under an old key conflicts. Corrections and forgetting still require `expected_revision`; read current state after a conflict rather than retrying blindly.

## 5. Checkpoints and Acceptance Boundaries

[Local metadata checkpoints](39-local-memory-checkpoints.md) cover stored revisions, events and statuses, not time-valid recall eligibility. Time passage alone need not make a checkpoint stale. A checkpoint is not a certificate that every captured active record can still be recalled, nor a backup or native transcript-coverage guarantee.

Acceptance for expiry must cover exact deadline equality, future/past/null values, omitted-versus-cleared correction, explicit inspection, recall exclusion and budgets, forget terminality, clock rollback, legacy receipt replay, atomic migration and old-schema read-only refusal. Use synthetic profiles and controlled clocks, and report actual unit/native test results separately; this guide makes no final acceptance-count or live-provider claim.

Strict native checkpoint-v2, automatic ingestion, source reconciliation, native worker orchestration and real-provider natural-language acceptance remain absent or unverified. Expiry does not complete the full memory roadmap or relax any existing privacy/admission gates.
