# Native cron delivery receipt write-back

English | [简体中文](README-zh.md)

This review artifact repairs native delivery bookkeeping on Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The native queue owns the send. The candidate uses the queue's existing terminal receipt to settle the original execution and matching current job summary. See [manifest.json](manifest.json) for the staged tree and verification inputs, and [LICENSE.hermes-agent](LICENSE.hermes-agent) for the upstream license.

## Recovery behavior

If the gateway process exits after the queue commits a terminal receipt, the clean native drain skips that receipt on restart because it has already been sent, refused, suppressed or fenced as unknown. The execution can remain `queued` and the job can still display delivery in progress. The clean host also records an `unknown` queue receipt as `failed` in the execution ledger.

The candidate keeps the execution's `queued` marker until the exact job update finishes or the job's current summary has moved on. A later native drain looks up retained queued executions and their terminal receipts in bounded batches, including the queue's pruned tombstones. The native write-back validates the job and execution binding. It settles the exact execution by CAS, preserves any newer job summary and keeps `unknown` distinct from `failed`. A newer attempt may start before it publishes a summary. The last canonical completion still owns the queued summary until a newer summary is committed. Another process exit between the job update and the execution update leaves the marker available for the next drain. Reconciliation does not select a delivery for transport or enqueue a new row.

`hermes cron runs` displays the recorded outcome separately from execution status. `hermes cron list` uses the outcome saved with the current job summary, including while a newer attempt is still running. A newer completed run clears the previous outcome. Check the original destination before any retry of an unknown result. A native `delivered` queue receipt records a successful send callback and does not establish recipient delivery or read confirmation. This recovery requires a retained execution with a queued marker and a terminal queue receipt. It performs no retrospective migration of older collapsed failures or reconstruction of pruned executions.

## Verification

Two clean controls reproduced the lost write-back and the conflated unknown result. Eleven candidate cases and 89 native regressions passed on Python 3.14.9. Candidate tests use the real cron firer, durable queue and restart path. Child processes exit before and after synthetic transport acceptance, after the queue commit and after the job summary write. An independent append-only test receipt distinguishes zero and one simulated acceptance. The successor drains twice with zero replay sends. The tests also cover a pruned receipt, a newer completed run, delivered and unknown receipts while a newer attempt is still running, a wait timeout, an incorrect job ID, early queue settlement and the existing CLI display. All 15 upstream static checks and the import boundary check passed.

The artifact stays outside the runtime package and exercises only synthetic profiles. It leaves host adoption, production authority, actual notification delivery and the full E4 acceptance open.

## Reproduce

Set `PROJECT` to this project checkout, `COPY` to a clean disposable Hermes checkout and `PYTHON` to its prepared Python 3.14 test interpreter.

```bash
set -eu
ARTIFACT="$PROJECT/experiments/cron-delivery-writeback"
BASE=2281116525106e3c109993ccb5dc74d02bfc1427
test "$(git -C "$COPY" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$COPY" status --porcelain --untracked-files=all)"
printf '%s  %s\n' 877018e2bd1a41d25b6dbc9b528669271523c099033767bfbd94a74deac90053 "$ARTIFACT/cron-delivery-writeback.patch" | sha256sum -c
cd "$COPY"
CHECK_HOME="$(mktemp -d)"
export HOME="$CHECK_HOME"
export HERMES_PYTHON="$PYTHON"
umask 022
bash scripts/run_tests.sh "$ARTIFACT/test_writeback.py" --file-retries 0 -- -o "pythonpath=$COPY" -k clean_pin -q
git apply --check "$ARTIFACT/cron-delivery-writeback.patch"
git apply --index "$ARTIFACT/cron-delivery-writeback.patch"
test "$(git write-tree)" = fb0c17aaf12e3656400b3b96306770fd017e9a00
bash scripts/run_tests.sh "$ARTIFACT/test_writeback.py" --file-retries 0 -- -o "pythonpath=$COPY" -k candidate -q
bash scripts/run_tests.sh tests/cron/test_delivery_queue.py tests/cron/test_delivery_queue_retention_race.py \
  tests/cron/test_delivery_outcome_writeback.py tests/cron/test_queued_delivery_fencing.py \
  tests/cron/test_execution_ledger.py tests/cron/test_cron_cancel_bookkeeping.py \
  tests/gateway/test_cron_delivery_housekeeping.py tests/hermes_cli/test_cron.py --file-retries 0 -- -q
"$PYTHON" scripts/check --base "$BASE" --staged
"$PYTHON" scripts/boundary_lint.py --check
```
