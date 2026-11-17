# Native memory context trust proposal

English | [简体中文](README-zh.md)

Review-only host patch against Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. The stock host tells the model to treat prefetched recall as authoritative reference data. The optional personal-records provider labels its JSON as untrusted evidence. Both labels reached the same request in the isolated installed-wheel acceptance. [PR #249](https://github.com/MosBot-AI/hermes-superagent/pull/249)

## Request behavior

The proposal frames fresh native recall as untrusted background data. The wrapper directs the model to check claims and ignore instructions and claimed permissions. The native fence and provider payload remain in the user message. The same host rendering is used for text and multimodal turns. The wrapper label carries no verified identity or authorization.

The ordinary request and iteration-summary builders replace the exact old host label in user `api_content` and in legacy multimodal text parts that start with the old frame. They preserve the body of the recall, any subsequent plugin context, other roles and the original text prefix when the sidecar still contains it. Plain user text without a sidecar is untouched. The new label may change the first post-upgrade prompt-cache prefix for a legacy session. Preflight and tail budget calculations use the same projected content. Existing stored sidecars and canonical records stay byte-for-byte intact.

Loaded native multimodal rows can already drop the memory fence when Hermes flattens and sanitizes the transcript. The proposal does not add data back to these rows. The ordinary-request test supplies a retained typed multimodal part to exercise the replay path where the part is available.

## Verification

Use an exact disposable Hermes checkout and its existing Python 3.14 test environment. Review the patch and apply it explicitly to the disposable checkout.

```sh
git -C "$DISPOSABLE_HOST" apply --check "$ARTIFACT/native-memory-context-trust.patch"
git -C "$DISPOSABLE_HOST" apply --index "$ARTIFACT/native-memory-context-trust.patch"
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON" --check-only
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON"
```

The runner checks the exact base, staged diff and tree, rejects tracked worktree drift and untracked non-ignored files, and uses private temporary homes. The HTTP fixture sends synthetic exchanges over loopback through the actual native request builder. The tests check a legacy SQLite sidecar on a fresh agent, fresh provider recall on the same request, a retained multimodal frame, summary projection, budget parity and preservation of quoted user text. The manifest records the selected suite and outcome.

A separate local run used the installed-wheel fixture from PR #249 with the verified standalone runtime built from main. The stock Gateway wrote revision 1 into a real session and stopped. A new candidate Gateway resumed the identical session after a correction. Its one request carried revision 1 as history and revision 2 as fresh recall, both with the untrusted label. The previous stored sidecar and the canonical SQLite database were unchanged by replay. This one-off cross-process check is recorded separately from the repeatable regression suite.

This proposal is unsubmitted and inactive. The supported Hermes revision and distributed runtime keep their previous behavior. Recall text already stored, transmitted or incorporated into a summary can persist. Provider rollout, live-model behavior, opaque server-side checkpoints and strict checkpoint-v2 remain outside the tested scope. [Issue #45](https://github.com/MosBot-AI/hermes-superagent/issues/45)

Upstream code in the patch is covered by [the retained license](LICENSE.hermes-agent).
