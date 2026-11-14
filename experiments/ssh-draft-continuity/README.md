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

Both native continuation settings passed after abrupt Electron and Gateway exit in the source build. The unchanged-route case preserves credentials, alias, install marker and chat ID while replacing the backend data. The new candidate keeps the replacement composer empty and hides review. The original journal entry survives. Switching back to the original state file restores review and guards two unchanged Enter presses. The backend tests also copy the actual database with its generation metadata intact and verify the copy has different continuity evidence.
