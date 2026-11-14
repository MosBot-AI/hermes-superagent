# Review-only SSH draft recovery proposal

English | [简体中文](README-zh.md)

The [patch](ssh-draft-recovery.patch) implements an opt-in review action in the original SSH chat for an uncertain ordinary text submission. It targets [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) at Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The [manifest](manifest.json) binds its exact patch and tree. Upstream-derived code retains the [Hermes MIT license](LICENSE.hermes-agent).

The renderer draft may disappear on abrupt Electron exit. The existing native journal already stores the original submission ID and intent before the legacy send. The proposal records a digest of the configured SSH destination with that entry before the legacy attempt. After explicitly reopening the original scoped chat, the user can review the original editor text under the same ID in an empty composer. Unchanged Send, Queue and Steer show the existing uncertainty warning. They keep the draft in the editor and issue no transport request. An edit creates a new draft under the existing composer rules. The reviewed unedited copy stays in the scoped journal and ephemeral composer. It is excluded from the ordinary stash, whose keys are only session IDs.

The review filters by the exact saved connection, Desktop profile, target profile and stored session. It rejects changed configured SSH coordinates, absent route evidence, ambiguous old-format entries, slash/queued/hidden sends and attachments. The action re-reads the journal and rechecks the current route and composer before painting text. The digest describes the configured route. It cannot attest a physical installation, host key or owner across a replacement that preserves those coordinates. The action requires the operator to reopen the original chat and deliberately select it. It grants no admission, synchronizes no draft to a peer, and does not send automatically.

## Reproduce

Use a disposable Hermes checkout at the pin, the pinned Node and Python, and a prepared locked Desktop workspace. Apply the patch and commit on that checkout only. Verify the tree against the manifest before building.

```sh
set -eu
artifact="$PWD/experiments/ssh-draft-recovery"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/ssh-draft-recovery.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/ssh-draft-recovery.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'fix(desktop): recover unconfirmed SSH drafts after process exit'
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
for case_name in bot-canonical-ssh-draft-crash bot-canonical-ssh-draft-crash-no-continue; do
  python -m acceptance.live.run_desktop_profile_routing \
    --case "$case_name" --review-proposal --hermes "$DISPOSABLE_HERMES" \
    --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE"
done
```

The runner requires the manifest digest, clean parent/tree, tracked files, exact patch identity and fresh build products. It uses a loopback-only Linux namespace and synthetic SSH credentials, transcript, and provider. Use the clean pin without `--review-proposal` for the [baseline](../../docs/15-primary-bot-binding.md#current-pin-openssh-abrupt-desktop-exit). The proposal remains unsubmitted and inactive. The supported pin and its distributed runtime use the clean Hermes revision.
