# Review-only native Bot sender recovery

English | [简体中文](README-zh.md)

[Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) tracks this candidate for Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The [patch](bot-sender-recovery.patch) and [manifest](manifest.json) are for disposable review builds. The installed plugin and official compatibility pin use the clean host. Upstream-derived material retains the [Hermes MIT license](LICENSE.hermes-agent).

## Recovery path

An admitted, same-install Bot delivery already has an original delivery ID and a waiter that reads its recipient receipt. The candidate lets that existing waiter write to the native process output log when the POSIX sender is a bound local Gateway conversation with asynchronous delivery. It checkpoints the original process ID, start time, parent session and notification route after watcher setup. In a multiplexed Gateway, only the profile whose output directory owns the log can adopt the checkpoint entry.

A successor tails the same waiter output and collects its recorded exit. The existing Gateway watcher and session authority admit the original process completion. An unviewed local session stores the result as a completion note. The recipient keeps the original Bot admission and receipt. No additional Bot send, transcript writer or model tool is introduced.

A finished waiter keeps its notification route and disposition in the existing process result. On startup the owner rearms pending results under their originating profile and original process ID, start time and parent session. The existing session admission ledger resolves a replay after an admission was already committed. An explicit full output read records consumption on the same result, so startup skips it.

## Reproduce

Prepare a disposable, clean Hermes checkout at the manifest base and a Python 3.14 environment with the pinned host's test dependencies. Use Linux with user, network, mount and PID namespaces and PID descriptor support. The launcher checks the candidate parent, committed tree, patch digest and checkout cleanliness before starting any Gateway. The published package excludes the experiment.

```sh
set -eu
artifact="$PWD/experiments/bot-sender-recovery"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/bot-sender-recovery.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/bot-sender-recovery.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'fix(bot): recover local reply completions across gateway loss'
for mode in --owner-loss --settled-loss --finished-loss --consumed-loss --admitted-loss; do
  sh acceptance/live/run_native_bot_poll_reply.sh \
    --hermes "$DISPOSABLE_HERMES" --hermes-python "$PINNED_PYTHON" \
    "$mode" --review-recovery
done
```

Run `--owner-loss`, `--settled-loss` and `--finished-loss` against the unmodified pin without `--review-recovery` for the controls.

## Evidence

On Linux with Python 3.14.9, the three clean controls reproduced the missing sender completion. The reviewed tree passed both pre-exit live Gateway cases. The settled reply appears once in the original sender chat with its original delivery and process IDs and exit code zero. The interrupted case produces one ambiguous completion that tells the sender to retain the receipt and avoid resending, with exit code one. Both verify one original recipient model request, no sender inference during recovery, exact recipient receipt replay, a profile-scoped retained process result, and no duplicate completion after one additional clean Gateway restart. The focused upstream suite passed 167 tests with one Windows-only shell test skipped. Its profile regression exercises the same checkpoint entry appearing in both the launch and sender profiles.

The finished-result control retains the original reply without presenting a sender completion. The patched host presents it once if the result is pending. A real log read before the fault prevents presentation, while a completion admitted before the fault stays a single record after recovery. All three patched cases retain the recipient reply and one original inference, and check again after an additional clean restart.

## Boundaries

The recovery contract covers a single abrupt owner loss before the waiter has finished, followed by a successor and one subsequent clean restart. The post-persistence cases separately cover an unadmitted result, a consumed result and an admitted completion whose local acknowledgement was lost. A failed checkpoint write, planned restart, multiple failures during handoff, attached-viewer startup races, remote routes, Windows, installed adoption and real providers require separate evidence. This candidate is inactive and has not been submitted upstream.
