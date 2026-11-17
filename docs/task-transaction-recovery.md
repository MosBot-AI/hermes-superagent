# Task Transaction Process-Recovery Evidence

English | [简体中文](task-transaction-recovery-zh.md)

## Scope

These E8.1/E8.2 checks in Issue #21 cover two boundaries. The offline matrix uses synthetic SQLite databases and dedicated child processes. The installed-package cases use the native Gateway and authenticated local transport in isolated profiles. Both use synthetic task data and require no model or provider credentials. The [original local M1 acceptance](90-local-m1-acceptance.md) retains its fixed evidence checkpoint.

## Failure matrix

`tests/unit/test_task_process_recovery.py` runs 88 cases across SQLite DELETE and WAL journal modes. Each case opens a real database in a separate Python process and calls the production `TaskStore.run` method. A connection subclass terminates that process with `os._exit` immediately after selected real SQL writes, or before/after COMMIT. This prevents Python exception handling and connection cleanup from supplying a rollback that a crashed process could not perform.

Eight operations are covered: capture, update, complete, cancel, progress, dependency replacement, batch plan capture and breakdown. Every operation is interrupted after its first task write, first event, receipt insertion, before commit and after commit. Additional interruptions cover the deletion of old dependency edges and the first newly inserted edge, before the remaining batch is written.

On reopening, every pre-commit crash must reproduce the complete prior logical database dump, not merely matching row counts. Every post-commit crash must retain its receipt. Retrying the exact request creates one result or replays the existing result; a further fresh connection must replay the same receipt without database changes. Reusing the request ID with a different payload must fail without mutation. Canonical task and parent snapshots must match the original successful result, and SQLite integrity must pass.

## Installed-package Gateway commit boundary

On Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, the manual native Gateway suite installs the verified runtime package through the official scanner. A ticket-authenticated WebSocket submits a synthetic three-task plan with three dependency edges. A test-only entrypoint instruments the transaction for that request key in the fixture's task database. It terminates the fixture-owned Gateway immediately before or after the real SQLite `COMMIT`, before the slash-command handler can return. The client reads until the connection closes and checks that the target RPC did not reply. Both Gateway processes run with the fixture's socket restrictions.

After a pre-commit crash, read-only queries compare the full task, event, edge and receipt state with the baseline. The fresh Gateway resumes the original session and the exact retry creates the plan once. After a post-commit crash, the plan is already visible, and the exact retry returns the committed receipt and task IDs. Both cases verify canonical tasks and revisions, exact dependency edges, event rows, the saved receipt and ready-task readback. A second exact retry and a changed payload with the same key leave the database unchanged. SQLite integrity and referential checks run before and after recovery.

Run these cases by dispatching the repository's [manual native Gateway workflow](../.github/workflows/native-gateway.yml) for the revision under test. For a local focused run, use the prepared pinned Hermes interpreter and set `HERMES_TEST_ROOT`, `HERMES_RUNTIME_PACKAGE` and `HERMES_SOURCE_COMMIT` as in that workflow. The fixture uses the verified package staged in a local Git directory for official installation.

```sh
python -m pytest -q acceptance/live/test_packaged_gateway_tasks.py -k plan_reconciles_at_gateway_commit_boundary
```

## Limits

The interruption is process termination. Power-loss durability, filesystem faults, disk corruption and backup restoration remain outside this evidence. The two journal modes apply to the offline matrix. The Gateway cases exercise the installed package and its ordinary task-store configuration. Broader identity, revocation, worker dispatch and external delivery acceptance remain open under #21.

Run the focused matrix with the project's Python 3.14 test environment:

```sh
python -m pytest tests/unit/test_task_process_recovery.py -q
```

Run `python scripts/check.py` for all unit, lint, type and bilingual-documentation checks. Native compatibility requires the separately documented pinned-host invocation; a local-only run must not be reported as native compatibility acceptance.
