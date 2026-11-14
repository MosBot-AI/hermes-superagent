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

## Bundled Linux verification

Build an unsigned Linux x64 AppImage from the clean proposal commit using the Hermes builder and the [pinned icon-tool preload](../../docs/15-primary-bot-binding.md#current-pin-bot-mode-canonical-chat-refusal-and-retry). The build below uses the upstream driver behind `scripts/build-bundle.sh` and lets the operator select separate work and cache directories. Run from the Personal Agent repository root. Use absolute paths outside `/tmp` and complete the build before staging the acceptance fixture.

```sh
set -eu
commit=$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = 94260c86f63b93084d97acd2df76a2aa838bf608
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
CSC_IDENTITY_AUTO_DISCOVERY=false \
HERMES_E07_ICON_TOOL_DIR="$DISPOSABLE_HERMES/apps/desktop/build/prepared-packaging-tools/icons" \
NODE_OPTIONS="--import=$ABSOLUTE_PRELOAD_PATH" \
  "$PINNED_PYTHON" "$DISPOSABLE_HERMES/scripts/bundles/desktop.py" \
  --repo "$DISPOSABLE_HERMES" --commit "$commit" --variant bundled \
  --work "$BUNDLE_WORK" --cache "$BUNDLE_CACHE"
```

Add `--appimage /absolute/path/to/Hermes.AppImage` to both proposal cases. Run both clean controls with the clean pin and its matching image, omitting `--review-proposal`. For the negative control, supply the clean image to a proposal case. The expected failure is `AppImage commit must match the verified checkout`, before packaged Electron launches. The fixture launches the packaged renderer and verifies its install stamp, ASAR and executable bundled CLI. The fixture-owned Gateways run from the checked-out test source.

The [manifest](manifest.json) records the candidate and clean image digests. Both images passed with continuation enabled and disabled. The clean image reopened the original chat and left the composer empty. The candidate restored the text on explicit review, issued a fresh warning for each of two unchanged Enter presses, and made no repeat submission. A renderer reload offered the original journal entry again and left renderer draft storage empty. The native continuation count stayed at one when enabled and zero when disabled. The clean image failed the proposal stamp check before launch.

Run `--case bot-canonical-ssh-draft-endpoint-replacement` with the same runner to check a configured endpoint replacement with native continuation disabled. Use matching clean and proposal builds, with `--review-proposal` only for the proposal. After abrupt exit, the fixture edits the saved SSH connection to a different listener, client key and launcher. Both installations have the same named profile and stored chat ID, distinct install markers and different transcripts. The replacement displays its own transcript with an empty composer and no review action. The original journal entry survives, neither transcript changes during the visit, and there is no new submit, session creation or provider call. After restoring the original endpoint, the candidate again offers explicit review and guards two unchanged Enter presses. Both source-built clients and both locally built unsigned Linux x64 AppImages passed this case.

Run `--case bot-canonical-ssh-draft-unchanged-route` for the release gate that remains after an endpoint edit passes. The fixture preserves the saved registry, SSH credentials and launcher, then stops the original backend and serves another synthetic home with the same install marker and canonical chat ID. Both source-built clients and both locally built unsigned AppImages show the replacement's own transcript and leave the composer empty. The proposal offers review on that chat, while the clean control has no review action. The test deliberately leaves it unselected on the replacement. It verifies that the original journal entry survives and that neither transcript, the submission count nor the provider count changes during the visit. The original chat still offers review with the existing uncertainty guard after switching back.

This candidate needs a native continuity signal tied to the active backend before it can safely offer review across reconnection. Current configured SSH values and the install marker can remain equal across different homes. Owner verification, signed packages, other systems and upstream adoption remain separate gates.
