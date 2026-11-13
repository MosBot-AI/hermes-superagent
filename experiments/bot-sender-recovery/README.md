# Review-only native Bot sender recovery

English | [简体中文](README-zh.md)

[Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) tracks this candidate for Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The [patch](bot-sender-recovery.patch) and [manifest](manifest.json) are for disposable review builds. The installed plugin and official compatibility pin use the clean host. Upstream-derived material retains the [Hermes MIT license](LICENSE.hermes-agent).

## Recovery path

An admitted, same-install Bot delivery already has an original delivery ID and a waiter that reads its recipient receipt. The candidate lets that existing waiter write to the native process output log when the POSIX sender is a bound local Gateway conversation with asynchronous delivery. It checkpoints the original process ID, start time, parent session and notification route after watcher setup. In a multiplexed Gateway, only the profile whose output directory owns the log can adopt the checkpoint entry.

A successor tails the same waiter output and collects its recorded exit. The existing Gateway watcher and session authority admit the original process completion. An unviewed local session stores the result as a completion note. The recipient keeps the original Bot admission and receipt. No additional Bot send, transcript writer or model tool is introduced.

A finished waiter keeps its notification route and disposition in the existing process result. On startup the owner rearms pending results under their originating profile and original process ID, start time and parent session. The existing session admission ledger resolves a replay after an admission was already committed. An explicit full output read records consumption on the same result, so startup skips it.

If a scoped result write fails, the native checkpoint keeps the original handoff while its profile-local output and recent exit record remain. The successor reads the same output, persists the result and retires the handoff. A full output read can mark the retained handoff consumed while the result path is unavailable. Already committed admissions are resolved by the same native completion identity.

At planned restart, the Gateway gives local receipt waiters up to one shared second after a successful drain to collect their already-admitted delivery results. The wait stays within the shutdown watchdog budget. The normal shutdown sweep still terminates any remaining waiter. Result and checkpoint writes use the profile captured when the waiter was spawned or adopted, including writes from the host-wide sweep.

The sender checkpoint and process result retain the exact target profile, target session, admission and delivery IDs, profile directory identities, and a digest of the original message and author. If the waiter is terminated before it emits output, the native sender watcher can read the exact receipt and verify it against the target profile's terminal local admission and retained result. The watcher uses the original process completion identity. A missing receipt or an identity-matching nonterminal receipt gets up to three more reads at one-second intervals in the same watcher. If the receipt is still unavailable, the watcher uses the process-exit notice. A mismatched or unsupported receipt goes directly to that fallback. The lookup reads local files and native admission state without dialing the recipient or replaying delivery.

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
    --result-write-failure --consumed-write-failure --admitted-write-failure \
    --killed-settled-receipt --mismatched-waiter-receipt \
    --delayed-waiter-receipt --missing-waiter-receipt --combined-write-failure; do
  sh acceptance/live/run_native_bot_poll_reply.sh \
    --hermes "$DISPOSABLE_HERMES" --hermes-python "$PINNED_PYTHON" \
    "$mode" --review-recovery
done
```

Run `--owner-loss`, `--settled-loss`, `--finished-loss`, `--planned-restart`, `--held-waiter-restart` and `--drained-waiter-restart` against the unmodified pin without `--review-recovery` for the controls.

## Evidence

On Linux with Python 3.14.9, the three abrupt-loss clean controls reproduced the missing sender completion. The reviewed tree passed both pre-exit live Gateway cases. The settled reply appears once in the original sender chat with its original delivery and process IDs and exit code zero. The interrupted case produces one ambiguous completion that tells the sender to retain the receipt and avoid resending, with exit code one. Both verify one original recipient model request, no sender inference during recovery, exact recipient receipt replay, a profile-scoped retained process result, and no duplicate completion after one additional clean Gateway restart. The focused upstream suite passed 255 tests with five skips. Its profile regression exercises the same checkpoint entry appearing in both the launch and sender profiles.

The finished-result control retains the original reply without presenting a sender completion. The patched host presents it once if the result is pending. A real log read before the fault prevents presentation, while a completion admitted before the fault stays a single record after recovery. All three patched cases retain the recipient reply and one original inference, and check again after an additional clean restart.

The planned restart case sends native `SIGUSR1` to the owned Gateway after the waiter finishes and before the sender completion enters the session queue. It verifies the planned restart marker, service-restart exit status and released endpoint before starting the successor. The clean host preserves the recipient reply but does not restore the sender note. The candidate restores one note without a new inference or a duplicate after another restart.

Three candidate-only cases inject `ENOSPC` before the atomic sender-result write while leaving the checkpoint, output log and exit record available. The previous candidate tree `0e9be5956551d182605e133ef2377443cf4e91b7` dropped the handoff in this window. The current tree keeps the original handoff and, after the same native planned restart with writes restored, reconstructs the result. It presents one pending notice, keeps an explicitly consumed result quiet, and deduplicates a notice already admitted with the same identity. All three cases preserve the original recipient receipt without resending and verify that a later restart does not duplicate admission. A focused test also verifies retirement after a matching result or after the native exit-record retention period.

With the waiter still active at the restart signal, the drain case releases the synthetic recipient only after the owner reports draining. Both hosts retain the original settled recipient reply. The candidate collects that reply in the original sender profile and presents one completion. In the forced-interrupt case the fixture holds the recipient response and pauses its owned waiter to ensure the shutdown sweep reaches it. The recipient retains one interrupted admission and a failed delivery receipt with a shutdown diagnostic. The candidate restores one sender process-exit notice from the correct profile with the original delivery ID and the verified failure diagnostic. In a separate case the recipient drains successfully but the paused waiter is killed before it reads the settled reply. The candidate restores that reply in the same completion. If the stored target session is replaced with a mismatched ID in the fixture, the watcher emits only the process-exit notice. Exact retry on both hosts reconciles the original receipt without resending. Neither clean control restores a sender notification.

Two additional cases make the receipt file appear absent on the successor's first read. Releasing the read fault before the next attempt restores the verified shutdown diagnostic in one sender completion. Holding the fault for all four reads produces one exit-only notice, even after the fixture releases the fault and starts another Gateway. Both preserve the original recipient admission and avoid a resend or duplicate completion. A separate case fails both the sender-result and checkpoint writes before either replacement. The existing checkpoint survives byte for byte, and the successor uses the retained log and exit record to rebuild and admit one result after writes return.

## Upstream review snapshot

A [separate patch](upstream/bot-sender-recovery.patch) and [manifest](upstream/manifest.json) adapt the candidate to upstream Hermes `547739e46692b2db7b4c9cdd57e8f795573846a4` (candidate tree `d93d217d67e2b7f5b0893a32f78d7e1e21f3e5b1`). The port preserves first-observer process exit results, sandbox-scoped process visibility and legacy in-memory adoption. Hosted activity cannot use local reply recovery to read or mutate host checkpoints or results.

On this revision ordinary unattended background completions can resume their parent as a model turn. Bot reply waiters persist one completion note when there is no viewer, including after Gateway loss. An attached sender can still receive the usual follow-up. Bot waiter completions are batched separately so an unrelated process retains its upstream wake behavior.

For this snapshot, use the `upstream` artifact directory and the manifest's `hermes_base` in the reconstruction commands above. Pass `--upstream-recovery-base --review-recovery` for the candidate, and `--upstream-recovery-base` for the six clean controls. Prepare the Python environment from this snapshot's lockfiles. With Python 3.14.9 on Linux, the 16 candidate cases, six clean controls and 341 focused upstream tests passed. The focused run skipped five platform cases. The supported compatibility pin and installed package still use the original clean host.

## Boundaries

The recovery contract covers a single abrupt owner loss before the waiter has finished, followed by a successor and one subsequent clean restart. The post-persistence cases separately cover an unadmitted result, a consumed result and an admitted completion whose local acknowledgement was lost. Loss of both writes without an existing checkpoint and retained output, failure to persist consumption after a saved result has already replaced its checkpoint, republished receipts with a retry admission, receipts that become available only after the exit notice has been admitted, multiple failures during handoff, attached-viewer startup races, remote routes, Windows, installed adoption and real providers require separate evidence. This candidate is inactive and has not been submitted upstream.
