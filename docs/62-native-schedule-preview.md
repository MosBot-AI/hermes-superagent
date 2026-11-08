# Native schedule preview

English | [简体中文](62-native-schedule-preview-zh.md)

## Explicit local planning, not a reminder

`hermes personal-agent schedule-preview --schedule '0 9 * * *' --timezone Asia/Shanghai --after '2027-01-01T08:00:00+08:00' --count 3`

The operator-only native CLI reuses the pinned Hermes `parse_schedule` and `compute_next_run` functions. It shows up to 20 nominal candidate instants from an explicit offset-aware reference and IANA timezone. It is available in read-only mode and is not registered as a model tool, slash command or remote API. It neither reads personal job records nor creates, repairs, runs, cancels or sends a job. `scheduled` and `delivery_verified` are always false. Changing the selected profile, managed-worker execution, a non-file configuration backend or invoking a retained handler after plugin unload fails closed.

Supported forms are native recurring intervals (`30m`, `every 2h`), cron expressions and native weekday phrases, and absolute offset-aware ISO one-shots. Bare durations are recurring, not one-shots. Relative `in 30m` and offset-less one-shots are rejected: their native parsing would use the current profile clock rather than the supplied reference. An absolute one-shot is compared with the reference directly, without claiming native missed-window/grace eligibility.

Each candidate includes native time, UTC, local time, `fold` and `wall_time_valid`. Intervals preserve elapsed time across DST. Cron candidates follow the actual host algorithm; a nonexistent spring-forward wall time is surfaced with `dst_gap_requires_review`, and preview stops instead of silently changing the intended time. A repeated autumn hour carries its explicit offset/fold. This is **not** a simulation of the live ticker, missed-run catch-up, repeated-hour delivery, outages, paused state or external receipts. A successful preview does not mean the schedule is active or that a notification will arrive.

## Why there is no read-only job inspector yet

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, `get_job`/`list_jobs` invoke `load_jobs`, which creates directories and can repair malformed records by writing `jobs.json`. This slice deliberately does not call them or bypass the public interface with an alternate native-store reader. Creation still lacks a caller idempotency key, cancelling a running execution does not stop future occurrences, and local delivery saves output rather than notifying the owner. E4's admission, reconciliation and delivery gates remain open.

## Evidence and limits

Unit and pinned-host contracts cover explicit reference/timezone, invalid bounded inputs, recurring versus absolute semantics, DST gap/fold handling, unload/profile isolation and unchanged cron files. Native loading may initialize ordinary host directories before the command runs; preview itself is checked against the post-load snapshot. Tests use temporary profiles and synthetic schedules; they do not launch a Gateway, ticker or external model and are not reminder delivery acceptance.

Cron forms need the host croniter dependency. Its initial platform probe may invoke the system `file` utility. Environments denying that probe return `native_preview_unavailable`; no restriction is bypassed. The no-subprocess cold-package test covers interval preview; cron/DST behavior is covered separately in the standard pinned-host contracts.
