# Review-Only Webapp Bot Chat Scope Proposal

English | [简体中文](README-zh.md)

The [candidate patch](bot-webapp-canonical.patch) proposes a Desktop routing correction for [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) at Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. It is unsubmitted and inactive. The official compatibility pin stays on the clean Hermes revision. Upstream-derived files retain the [Hermes MIT license](LICENSE.hermes-agent). The [manifest](manifest.json) binds the exact patch digest and proposal tree.

## Scope

The named Bot Mode chat uses an exact-title `session.list` with a backend `profile` operand. The fallback `session.info` probes the roster's canonical session ID when that list is empty. A saved Webapp token socket starts on the launch authority and can route an explicit request to another served profile. The proposal adds the backend `profile` operand for a source-qualified fallback and adds a focused alias test. A route-less fallback keeps its existing parameter shape. [Pinned source and acceptance boundary](../../docs/15-primary-bot-binding.md#current-pin-saved-webapp-bot-mode-routing)

## Reproduce

Use a separately prepared, disposable, credential-free Hermes checkout and a locked Desktop toolchain. From the Personal Agent repository root, set `DISPOSABLE_HERMES`, `PINNED_NODE` and `PINNED_PYTHON` to absolute paths outside `/tmp`. The [Electron runner](../../acceptance/live/run_desktop_profile_routing.py) uses private Linux namespaces, Xvfb and a loopback-only network. It validates the exact proposal as a clean direct child of the pinned commit, checks the build stamp and upstream Desktop and Webapp freshness, and applies no patch. The manual local commit below may have a different ID from the reviewed commit. Its source tree must match the manifest.

Put pinned pnpm `12.15.0` on `PATH` and prepare the locked Desktop dependencies and the Webapp build's separate dependency workspace. The Webapp builder's isolated mirror needs its own prepared dependencies or a populated pnpm content cache. The verified offline build used a private copy of that cache with `npm_config_offline=true`.

```sh
set -eu
ARTIFACT="$PWD/experiments/bot-webapp-canonical"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
printf '%s  %s\n' \
  e50e573140b1de21d9c8b5ddeb3a82ed0bd898e53b1fcdb345863fbe9cecbf80 \
  "$ARTIFACT/bot-webapp-canonical.patch" | sha256sum --check
git -C "$DISPOSABLE_HERMES" apply --check "$ARTIFACT/bot-webapp-canonical.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$ARTIFACT/bot-webapp-canonical.patch"
git -C "$DISPOSABLE_HERMES" commit -m "fix(desktop): scope Bot Chat fallback lookup"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = 49ff33f721dd356bc1ea853dde8a1623c460ac05
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  export npm_config_offline=true
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
python -m acceptance.live.run_desktop_profile_routing \
  --case bot-canonical-saved-token --review-proposal \
  --hermes "$DISPOSABLE_HERMES" \
  --hermes-python "$PINNED_PYTHON" \
  --node "$PINNED_NODE"
```

Run the clean baseline separately with `--case bot-canonical-saved-token` and a prepared clean checkout at the base revision. Leave `--review-proposal` out of that invocation.

For bundled Linux x64 acceptance, build a local AppImage from each checkout with upstream `scripts/build-bundle.sh` and the [pinned icon-tool workaround](../../docs/15-primary-bot-binding.md#current-pin-bot-mode-canonical-chat-refusal-and-retry). Wait for packaging to finish before staging the acceptance overlay in the checkout. Add `--appimage /absolute/path/to/Hermes.AppImage` to each invocation. The launcher verifies that the image stamp matches the exact clean or verified proposal commit used by the fixture. A rebuilt proposal commit can have a different ID if its parent, tree and patch match the manifest. Run the clean and proposal checks with their respective images.

## Evidence

The clean and proposal builds each passed one isolated Linux Electron case with two owned Gateway installations and the same one-shot empty result after a real named-profile lookup. [UI fixture](../../tests/desktop/desktop_bot_saved_token_refusal.spec.ts)

- Clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` sent an unscoped `session.info` probe to the remote `default` handler. After `4001 not_found`, the same click performed a second scoped lookup and opened the original chat.
- The candidate built from local commit `14c1a21fc4601de51000cba05d61894902773524` sent `profile: scout`. The named native handler confirmed the existing chat, and the UI kept prior focus and offered retry. A later explicit click opened that original chat.

Both runs recorded unchanged session, message and admission projections for the four fixture databases, no session creation or prompt submission, and zero model completions. The clean profile-routing and local Bot Mode cases also passed after the fixture refactor. The proposal source passed 52 selected upstream Vitest cases, including 15 canonical chat registry cases with the new alias case, 20 roster cases and 17 routing cases.

Authentication and grants remain governed by the native host. The patch remains a review artifact. Upstream adoption, supported packaging and other credential modes require separate evidence.
