# Review-only LOCAL receipt preservation on profile rename

English | [简体中文](README-zh.md)

The [review patch](local-receipt-rename.patch) for [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) adds `hermes profile rename OLD NEW --preserve-local-sessions` to a separate Hermes build. The [manifest](manifest.json) records the exact base, candidate tree and patch digest. Upstream material retains the [Hermes MIT license](LICENSE.hermes-agent).

The Linux candidate requires the native maintenance reservations of the installation and the original named profile. It physically moves the home with an exclusive destination check. In the moved store, the existing native SQLite rekey transaction validates the LOCAL creation identity, exact routed entry, stored transcript lineage and idle state before changing the receipt's route and origin profile. Creator ID, minting path, principal, creation request, policy, transcript and durable admissions retain their original identities. On a validation refusal, the transaction rolls back and the private home returns to the old name. The standalone `profile migrate-identity` command has no receipt-migration authority.

The scope is an idle same-installation Linux named-profile rename on a filesystem supporting `renameat2` with `RENAME_NOREPLACE`. The review flag excludes `default` and the special `main` namespace, live Gateway ownership and legacy-adopted LOCAL receipts. Process death and filesystem or SQLite I/O failure during directory publication, incoming profile-local paths and credentials, untitled creation retries across renamed homes, and authenticated owner recovery require separate verification. Use the fixture only with disposable stores. The supported pin and runtime archive exclude this patch.

## Reproduce

Prepare a disposable checkout of Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` and a compatible Hermes test interpreter. From the Personal Agent repository root, apply the patch and commit the candidate before the fixture verifies its exact tree and diff.

```sh
set -eu
artifact="$PWD/experiments/local-receipt-rename"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/local-receipt-rename.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/local-receipt-rename.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'feat(profile): preserve local receipts during explicit offline rename'
scratch="$(mktemp -d /var/tmp/lr.XXXXXX)"
mkdir "$scratch/home" "$scratch/tmp"
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$scratch/home" TMPDIR="$scratch/tmp" \
  HERMES_TEST_ROOT="$DISPOSABLE_HERMES" HERMES_REVIEW_LOCAL_RECEIPT_RENAME=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PINNED_PYTHON" -m pytest -q -p no:cacheprovider --show-capture=no \
  --basetemp="$scratch/pytest" acceptance/live/test_native_local_receipt_rename.py
```

The fixture starts real Gateway processes with fixture-owned homes, authenticates a host-scoped client and runs the native CLI from a private export of the verified candidate. It creates an original Bot Chat through the Gateway and uses native storage operations to prepare a synthetic compression child and admission without model calls. The existing [clean-pin rename fixture](../../docs/15-primary-bot-binding.md#current-pin-native-profile-rename) covers the supported runtime.

The candidate fixture checks that live ownership, an occupied destination, a destination pointing to a copy and a pending admission all refuse. After the pending input is cancelled, the same physical state database moves. A fresh native ticket can read and resume the original Bot Chat under the new name. The roster preserves the original root and compression tip, the compressed message is visible, and a repeat titled lookup returns the original session. The cancelled admission and the measured transcript rows remain unchanged. The standalone identity retry also leaves the migrated receipt unchanged.
