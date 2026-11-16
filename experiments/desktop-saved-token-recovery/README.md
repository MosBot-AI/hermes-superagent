# Review-Only Desktop Saved Token Recovery

English | [简体中文](README-zh.md)

The [candidate patch](desktop-saved-token-recovery.patch) addresses the saved-token reconnect failure observed in [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) at Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The [manifest](manifest.json) binds the patch digest and exact derived tree. The upstream-derived patch follows the [Hermes MIT license](LICENSE.hermes-agent).

The Desktop connection editor persists a replacement token and refreshes the connection's pooled descriptors. The running primary also holds a process-wide descriptor. When the effective primary takes its token from the edited registry entry at the same URL, the candidate retires that descriptor after the save. The main window uses the existing connection-apply signal to reconnect if it is still on that source. The patch uses the existing route precedence, registry save and native authorization paths.

## Reproduce

Prepare a disposable, credential-free Linux checkout at the exact base. Use the locked Desktop toolchain and the [pinned build instructions](../../docs/15-primary-bot-binding.md#current-pin-electron-profile-routing). Define `DISPOSABLE_HERMES`, `PINNED_NODE` and `PINNED_PYTHON` as absolute paths outside `/tmp`. Run the following from the Personal Agent repository root.

```sh
set -eu
ARTIFACT="$PWD/experiments/desktop-saved-token-recovery"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
printf '%s  %s\n' \
  cbeb4455ae2dbe2ea17afead6b8b63fb6e5d717dc110ebba2f64ff87fe9151f8 \
  "$ARTIFACT/desktop-saved-token-recovery.patch" | sha256sum --check
git -C "$DISPOSABLE_HERMES" apply --check "$ARTIFACT/desktop-saved-token-recovery.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$ARTIFACT/desktop-saved-token-recovery.patch"
git -C "$DISPOSABLE_HERMES" commit -m "fix(desktop): reconnect the primary after a saved token edit"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = b9c556f7f33fcf5e777eaff57ff4a6d85773f8cf
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
"$PINNED_PYTHON" -m acceptance.live.run_desktop_profile_routing \
  --case desktop-saved-token-sign-out --review-proposal \
  --hermes "$DISPOSABLE_HERMES" --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE"
```

The runner checks the full patch, tree, clean direct-parent ancestry, and source build stamps before it launches the isolated fixture. Repeat the command with a separately prepared clean pin and omit `--review-proposal` for the control. To test a locally bundled unsigned Linux x64 AppImage, build the matching checkout with `scripts/build-bundle.sh` and the [documented icon-tool workaround](../../docs/15-primary-bot-binding.md#current-pin-bot-mode-canonical-chat-refusal-and-retry). Add `--appimage /path/to/Hermes.AppImage`. The runner checks the packaged installation stamp before Electron launch.

## Evidence

The clean source control closes the old Desktop socket, rejects the old token with HTTP `401`, and refuses the scoped SDK read after the registry edit. The full Desktop restart reopens the original `scout` Bot Chat. The candidate reconnects after the explicit registry edit with the original Electron process and renderer document still running. An explicit Bot Mode click sends the open request over the new scoped socket and focuses the original chat. The independent native-ticket route can read its own same-named chat after the rotation and after recovery. The case measures route availability and both Gateway identities. Desktop may recreate the peer's renderer socket during its connection apply.

Both source cases compare the same four SQLite session, message and admission projections before and after the case. The fixture sees no session creation, prompt submission or model completion. The candidate's Electron type check and 138 focused route, registry and backend state tests passed. Reviewed cases cover an explicit same-URL saved token edit for the active registry-sourced primary. Signed builds, other credential modes, cross-installation recovery and authenticated owner continuity require their own evidence. The candidate is unsubmitted and inactive.

The locally bundled unsigned Linux x64 AppImages reproduced the clean and candidate outcomes. The candidate image built from `a2f9c951bddfa31e275ca0508cddb8d53ed93320` has SHA-256 `a4fa2154b79fb95cebb5960d6e3371594addbdab8b4453957b7822b6f01d8e16`. The clean image is rejected before Electron launch when supplied in proposal mode. The local candidate build used Clang `19.1.7` and the icon-tool workaround. The optional X11 modifier monitor was omitted by the builder because the XInput2 headers were unavailable.
