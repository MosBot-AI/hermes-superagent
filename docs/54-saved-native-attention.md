# Saved native attention review

English | [简体中文](54-saved-native-attention-zh.md)

## Read saved observations, not the live board

`/personal-tasks native-review --on YYYY-MM-DD` reads only saved local task `native_progress` snapshots. It does not open the native board or handoff ledger, call a provider, refresh observations, or dispatch work. The explicit date determines a UTC cutoff; it does not create background monitoring.

Optional filters are `--project LABEL` or `--unassigned`. `--stale-after-days` defaults to 7 (1–365), `--per-bucket-limit` to 5 (1–20), and `--max-chars` to 16000 (2048–32000). Only captured local tasks are considered. Summaries are bounded and ordered by oldest observation, then stable task sequence.

Four buckets overlap:

- `awaiting_review`: saved current status is review.
- `board_closed`: saved current status is done or archived.
- `identity_issue`: the saved observation has an identity/missing/duplicate failure outcome.
- `stale`: observation time is strictly before UTC midnight on the supplied date minus the selected number of days.

The unique attention count does not double-count tasks appearing in multiple buckets. Tasks without an observation are unobserved, not proof that no linked card exists. Every result needs manual verification: a saved status is not current live state, local completion, or permission to unblock, complete or dispatch anything. No automatic refresh or mutation is suggested.

## Scope and privacy

This is one local read workflow over the metadata already stored by [explicit native sync](53-native-progress-observation.md). Bounded summaries include task ID/title/revision/project/due date/work status and the saved observation, not source details or native output. The read query can be available through separately configured and session-activated task model tools under their existing read scope; it introduces no model write action or provider call of its own.

Status describes implementation/configuration only and does not probe a live board. This local-only slice is not installed or live-verified and does not complete [native orchestration acceptance](08-roadmap-and-acceptance.md).
