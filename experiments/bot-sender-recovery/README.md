# Review-only native Bot sender recovery

English | [简体中文](README-zh.md)

[Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) tracks this candidate for Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The [patch](bot-sender-recovery.patch) and [manifest](manifest.json) are for disposable review builds. The installed plugin and official compatibility pin use the clean host. Upstream-derived material retains the [Hermes MIT license](LICENSE.hermes-agent).

## Recovery path

An admitted, same-install Bot delivery already has an original delivery ID and a waiter that reads its recipient receipt. The candidate lets that existing waiter write to the native process output log when the POSIX sender is a bound local Gateway conversation with asynchronous delivery. It checkpoints the original process ID, start time, parent session and notification route after watcher setup. In a multiplexed Gateway, only the profile whose output directory owns the log can adopt the checkpoint entry.

A successor tails the same waiter output and collects its recorded exit. The existing Gateway watcher and session authority admit the original process completion. An unviewed local session stores the result as a completion note. The recipient keeps the original Bot admission and receipt. No additional Bot send, transcript writer or model tool is introduced.

A finished waiter keeps its notification route and disposition in the existing process result. On startup the owner rearms pending results under their originating profile and original process ID, start time and parent session. The existing session admission ledger resolves a replay after an admission was already committed. An explicit full output read records consumption on the same result, so startup skips it.

If a scoped result write fails, the native checkpoint keeps the original handoff while its profile-local output and recent exit record remain. The successor reads the same output, persists the result and retires the handoff. A full output read can mark the retained handoff consumed while the result path is unavailable. Already committed admissions are resolved by the same native completion identity.

At planned restart, the Gateway gives local receipt waiters up to one shared second after a successful drain to collect their already-admitted delivery results. The wait stays within the shutdown watchdog budget. The normal shutdown sweep still terminates any remaining waiter. Result and checkpoint writes use the profile captured when the waiter was spawned or adopted, including writes from the host-wide sweep.

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
for mode in --owner-loss --settled-loss --finished-loss --consumed-loss --admitted-loss \
    --planned-restart --held-waiter-restart --drained-waiter-restart \
    --result-write-failure --consumed-write-failure --admitted-write-failure; do
  sh acceptance/live/run_native_bot_poll_reply.sh \
    --hermes "$DISPOSABLE_HERMES" --hermes-python "$PINNED_PYTHON" \
    "$mode" --review-recovery
done
```

Run `--owner-loss`, `--settled-loss`, `--finished-loss`, `--planned-restart`, `--held-waiter-restart` and `--drained-waiter-restart` against the unmodified pin without `--review-recovery` for the controls.

## Evidence

On Linux with Python 3.14.9, the three abrupt-loss clean controls reproduced the missing sender completion. The reviewed tree passed both pre-exit live Gateway cases. The settled reply appears once in the original sender chat with its original delivery and process IDs and exit code zero. The interrupted case produces one ambiguous completion that tells the sender to retain the receipt and avoid resending, with exit code one. Both verify one original recipient model request, no sender inference during recovery, exact recipient receipt replay, a profile-scoped retained process result, and no duplicate completion after one additional clean Gateway restart. The focused upstream suite passed 219 tests with six skips. Its profile regression exercises the same checkpoint entry appearing in both the launch and sender profiles.

The finished-result control retains the original reply without presenting a sender completion. The patched host presents it once if the result is pending. A real log read before the fault prevents presentation, while a completion admitted before the fault stays a single record after recovery. All three patched cases retain the recipient reply and one original inference, and check again after an additional clean restart.

The planned restart case sends native `SIGUSR1` to the owned Gateway after the waiter finishes and before the sender completion enters the session queue. It verifies the planned restart marker, service-restart exit status and released endpoint before starting the successor. The clean host preserves the recipient reply but does not restore the sender note. The candidate restores one note without a new inference or a duplicate after another restart.

Three candidate-only cases inject `ENOSPC` before the atomic sender-result write while leaving the checkpoint, output log and exit record available. The previous candidate tree `0e9be5956551d182605e133ef2377443cf4e91b7` dropped the handoff in this window. The current tree keeps the original handoff and, after the same native planned restart with writes restored, reconstructs the result. It presents one pending notice, keeps an explicitly consumed result quiet, and deduplicates a notice already admitted with the same identity. All three cases preserve the original recipient receipt without resending and verify that a later restart does not duplicate admission. A focused test also verifies retirement after a matching result or after the native exit-record retention period.

With the waiter still active at the restart signal, the drain case releases the synthetic recipient only after the owner reports draining. Both hosts retain the original settled recipient reply. The candidate collects that reply in the original sender profile and presents one completion. In the forced-interrupt case the fixture holds the recipient response and pauses its owned waiter to ensure the shutdown sweep reaches it. The recipient retains one interrupted admission and a failed delivery receipt with a shutdown diagnostic. The candidate restores one sender process-exit notice from the correct profile. That notice does not include the recipient's delivery ID or a reply because the waiter was killed before it produced output. Exact retry on both hosts reconciles the original receipt without resending. Neither clean control restores a sender notification.

## Boundaries

The recovery contract covers a single abrupt owner loss before the waiter has finished, followed by a successor and one subsequent clean restart. The post-persistence cases separately cover an unadmitted result, a consumed result and an admitted completion whose local acknowledgement was lost. Simultaneous result and checkpoint write failure, failure to persist consumption after a saved result has already replaced its checkpoint, a killed waiter's automatic lookup of the recipient receipt, multiple failures during handoff, attached-viewer startup races, remote routes, Windows, installed adoption and real providers require separate evidence. This candidate is inactive and has not been submitted upstream.
