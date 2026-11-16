# Review-only SSH draft continuity

English | [简体中文](README-zh.md)

This [patch](ssh-draft-continuity.patch) extends the [original SSH draft proposal](../ssh-draft-recovery/README.md) for [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33). It is a separate commit on Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The [manifest](manifest.json) identifies the exact tree and patch. Upstream-derived material retains the [Hermes MIT license](LICENSE.hermes-agent).

The legacy Gateway derives an opaque digest for the exact attached stored session from the current backend instantiation, physical database file identity, SQLite generation and row creation time. The client records the digest before its legacy attempt. The legacy submit handler checks the same digest before starting the attempt. The Desktop checks current evidence on the existing scoped socket before showing the review action and again before revealing text. Missing or different evidence leaves the journal entry private. Earlier route-only entries stay in the journal and are ineligible. A supported original session can still offer deliberate review after the Gateway and Desktop restart during the same backend instantiation. An unchanged reviewed draft retains the no-resubmit guard.

The scope is a Linux backend with a readable boot identity, intact state database and exact stored session row. A backend reboot, database restore or replacement, missing contract, unavailable store or unresolved route can make review unavailable. This digest covers local draft disclosure. Authenticated personal owner binding and broader restore policy still need separate evidence.

## Reproduce

Prepare a disposable checkout with the pinned Node, Python and locked Desktop dependencies. Apply the full patch directly to the clean Hermes base. Run the fixture from the Personal Agent repository.

```sh
set -eu
artifact="$PWD/experiments/ssh-draft-continuity"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/ssh-draft-continuity.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/ssh-draft-continuity.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'fix(desktop): bind SSH draft review to the active session store'
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
for case_name in bot-canonical-ssh-draft-crash bot-canonical-ssh-draft-crash-no-continue bot-canonical-ssh-draft-unchanged-route; do
  python -m acceptance.live.run_desktop_profile_routing --case "$case_name" \
    --review-draft-continuity --hermes "$DISPOSABLE_HERMES" \
    --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE"
done
```

The runner verifies the complete patch and source tree before launching an isolated Desktop and OpenSSH fixture. Use the clean pin without a review flag for the baseline. Use `--review-proposal` and the separate original proposal checkout for the historical negative comparison.

Both native continuation settings passed after abrupt Electron and Gateway exit in the source build. The unchanged-route case preserves credentials, alias and install marker while replacing the backend data with a physical SQLite copy. The copy preserves its stored chat ID, timestamp and database generation. The new candidate keeps the replacement composer empty and hides review. The original journal entry survives. Switching back to the original state file restores review and guards two unchanged Enter presses. The backend tests also copy the actual database with its generation metadata intact and verify the copy has different continuity evidence.

## Bundled Linux verification

Build the bundled variant from the committed candidate checkout with Hermes' desktop provider. Use a fresh preparation directory, a local dependency cache and the Linux build prerequisites. Set `ICON_PRELOAD` to the absolute path of the [CommonJS icon-tool preload](../../docs/15-primary-bot-binding.md#current-pin-bot-mode-canonical-chat-refusal-and-retry). Calculate the completed image's SHA-256 before running the fixture from the Personal Agent repository root.

```sh
set -eu
commit=$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = d7c0cb003cfe40b8e7bf0b21603a8cdd55125d3c
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
CSC_IDENTITY_AUTO_DISCOVERY=false \
HERMES_E07_ICON_TOOL_DIR="$DISPOSABLE_HERMES/apps/desktop/build/prepared-packaging-tools/icons" \
NODE_OPTIONS="--import=$ICON_PRELOAD" \
  "$PINNED_PYTHON" "$DISPOSABLE_HERMES/scripts/bundles/desktop.py" \
    --repo "$DISPOSABLE_HERMES" --commit "$commit" --variant bundled \
    --work "$BUILD_WORK" --cache "$BUILD_CACHE"
appimage="$DISPOSABLE_HERMES/apps/desktop/release/HermesBundled-0.0.0-linux-x86_64.AppImage"
sha256sum "$appimage"
for case_name in bot-canonical-ssh-draft-crash bot-canonical-ssh-draft-crash-no-continue bot-canonical-ssh-draft-unchanged-route bot-canonical-ssh-draft-endpoint-replacement; do
  python -m acceptance.live.run_desktop_profile_routing --case "$case_name" \
    --review-draft-continuity --hermes "$DISPOSABLE_HERMES" \
    --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE" --appimage "$appimage"
done
```

The fixture verifies the image's clean commit stamp, bundled CLI, packaged Electron executable and ASAR. It runs the isolated OpenSSH Gateway from the verified source checkout. For a negative control, substitute a clean-pin image or an image from the earlier recovery proposal. The install-stamp assertion should fail before packaged Electron launches. On refusal, the runner prints a private diagnostics directory, and the exact `AppImage commit must match the verified checkout` assertion appears in its `playwright.json`.

The [manifest](manifest.json) records the unsigned Linux x64 build's exact commit, tree, tool versions and image digest. This host supplied a CommonJS package boundary for the generated icon tool, X11 headers and libraries, and cached registry wheels from the earlier build with the same `uv.lock`. The provider rebuilt native dependencies and the payload from the candidate checkout.

The packaged renderer passed on the original store with native continuation enabled and disabled. On the unchanged SSH route serving the copied SQLite store, it showed the replacement's transcript and an empty composer without offering review. The separate configured endpoint edit also kept the draft private. In both cases the original journal entry survived, and reopening the original store allowed explicit guarded review. Each unchanged Enter press left the submit, transcript and provider counts unchanged. Both mismatched images failed the install stamp before Electron launched. Signed distribution, other systems and authenticated personal owner continuity are still open.
