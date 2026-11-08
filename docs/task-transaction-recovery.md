# Task Transaction Process-Recovery Evidence

English | [简体中文](task-transaction-recovery-zh.md)

## Scope

This is a bounded offline subset of E8.1/E8.2 in Issue #21, not full M1 acceptance. The existing task store is exercised with synthetic SQLite databases in the cloud, without a Gateway, provider credentials, external writes or the user's MacBook. It complements, rather than replaces, the memory-candidate recovery tests in PR #52 and the existing breakdown commit-boundary checks.

## Failure matrix

`tests/unit/test_task_process_recovery.py` runs 88 cases across SQLite DELETE and WAL journal modes. Each case opens a real database in a separate Python process and calls the production `TaskStore.run` method. A connection subclass terminates that process with `os._exit` immediately after selected real SQL writes, or before/after COMMIT. This prevents Python exception handling and connection cleanup from supplying a rollback that a crashed process could not perform.

Eight operations are covered: capture, update, complete, cancel, progress, dependency replacement, batch plan capture and breakdown. Every operation is interrupted after its first task write, first event, receipt insertion, before commit and after commit. Additional interruptions cover the deletion of old dependency edges and the first newly inserted edge, before the remaining batch is written.

On reopening, every pre-commit crash must reproduce the complete prior logical database dump, not merely matching row counts. Every post-commit crash must retain its receipt. Retrying the exact request creates one result or replays the existing result; a further fresh connection must replay the same receipt without database changes. Reusing the request ID with a different payload must fail without mutation. Canonical task and parent snapshots must match the original successful result, and SQLite integrity must pass.

## Limits

These are process-termination tests, not power-loss, filesystem fault, disk corruption or backup/restore certification. The tests explicitly select two journal modes only in their temporary databases; production database configuration is unchanged. Offline store tests do not exercise host admission, revocation, real native transport, worker dispatch or remote delivery. They do not prove exactly-once external execution. No production behavior or schema is changed by this test slice. Full #21 remains open.

Run the focused matrix with the project's Python 3.14 test environment:

```sh
python -m pytest tests/unit/test_task_process_recovery.py -q
```

Run `python scripts/check.py` for all unit, lint, type and bilingual-documentation checks. Native compatibility requires the separately documented pinned-host invocation; a local-only run must not be reported as native compatibility acceptance.
