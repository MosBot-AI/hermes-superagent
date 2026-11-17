# Native schedule preview

English | [简体中文](62-native-schedule-preview-zh.md)

## Explicit local planning, not a reminder

`hermes personal-agent schedule-preview --schedule '0 9 * * *' --timezone Asia/Shanghai --after '2027-01-01T08:00:00+08:00' --count 3`

The operator-only native CLI reuses the pinned Hermes `parse_schedule`, `parse_duration` and `compute_next_run` functions. It shows up to 20 nominal candidate instants from an explicit offset-aware reference and IANA timezone. It is available in read-only mode and is not registered as a model tool, slash command or remote API. It neither reads personal job records nor creates, repairs, runs, cancels or sends a job. `scheduled` and `delivery_verified` are always false. Changing the selected profile, managed-worker execution, a non-file configuration backend or invoking a retained handler after plugin unload fails closed.

Supported forms are native recurring intervals (`30m`, `every 2h`), cron expressions and native weekday phrases, absolute offset-aware ISO one-shots, and relative one-shots such as `in 30m`. A bare duration is recurring. For `in 30m`, preview parses the native duration and adds that elapsed time to `--after` in UTC. It then passes the resolved offset-aware time in `--timezone` to the native schedule parser. This yields at most one candidate after the reference. Offset-less absolute inputs are rejected. One-shot previews leave missed-window and grace eligibility to the live scheduler.

```sh
hermes personal-agent schedule-preview --schedule 'in 30m' --timezone America/New_York \
  --after '2027-11-07T01:45:00-04:00'
```

Thirty minutes later is `2027-11-07T01:15:00-05:00` (`fold: 1`), or `2027-11-07T06:15:00+00:00` in UTC.

Each candidate includes native time, UTC, local time, `fold` and `wall_time_valid`. Intervals preserve elapsed time across DST. Cron candidates follow the actual host algorithm; a nonexistent spring-forward wall time is surfaced with `dst_gap_requires_review`, and preview stops instead of silently changing the intended time. A repeated autumn hour carries its explicit offset/fold. This is **not** a simulation of the live ticker, missed-run catch-up, repeated-hour delivery, outages, paused state or external receipts. A successful preview does not mean the schedule is active or that a notification will arrive.

## Why there is no read-only job inspector yet

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, `get_job`/`list_jobs` invoke `load_jobs`, which creates directories and can repair malformed records by writing `jobs.json`. This slice deliberately does not call them or bypass the public interface with an alternate native-store reader. Creation still lacks a caller idempotency key, cancelling a running execution does not stop future occurrences, and local delivery saves output rather than notifying the owner. E4's admission, reconciliation and delivery gates remain open.

## Evidence and limits

Unit and pinned-host contracts cover explicit reference/timezone, bounded invalid inputs, recurring and one-shot semantics, DST gap/fold handling, unload/profile isolation and unchanged cron files. The relative preview is tested with the host clock disabled. Separate paused native test jobs created at those reference instants store the same UTC times across both DST transitions. Native loading may initialize ordinary host directories before the command runs, so preview is checked against the post-load snapshot. Tests use temporary profiles and synthetic schedules, with no Gateway, ticker, model or delivery.

Cron forms need the host croniter dependency. Its initial platform probe may invoke the system `file` utility. Environments denying that probe return `native_preview_unavailable`; no restriction is bypassed. The no-subprocess cold-package test covers interval and relative one-shot previews. Cron/DST behavior is covered in the standard pinned-host contracts.
