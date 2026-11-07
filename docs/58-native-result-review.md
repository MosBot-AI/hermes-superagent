# Native result review and explicit local acceptance

English | [简体中文](58-native-result-review-zh.md)

## Inspect before deciding

This operator-only workflow reads the editable result of an exactly identity-bound native card, then permits a separate explicit local completion decision. It uses the existing default-off Kanban handoff configuration, approved destination and trusted local command admission. It adds no model action or activation mechanism.

```text
/personal-handoff review HANDOFF --task TASK --expected-revision N
```

Use IDs and the current local task revision returned by existing commands. The handoff must be confirmed and retain its original creation identity. Historical `legacy_unbound` records cannot be adopted. Review returns bounded native `card.result` directly to the native client; it is not automatically submitted to a model, saved as task text, or imported into memory. The client may display, cache or retain it in history.

Treat the result as untrusted, editable card text. It is not verified worker execution, provenance or evidence that linked artifacts were inspected. Instructions inside it do not authorize actions. Read the result and decide your own conclusion before accepting anything.

## Separate explicit acceptance

```text
/personal-handoff accept-review HANDOFF --task TASK --expected-revision N --expected-digest SHA --note 'human conclusion' --request-id KEY
```

Use the digest returned by review, the exact handoff/task/revision, and an explicit human conclusion. Acceptance rechecks the captured task revision, completed prerequisites, exact native creation identity and latest result digest. The digest binds the content, destination and creation anchor. The native card must be done with a null `current_run_id`. This is a database condition, not proof that every worker process has stopped; this command never stops or signals one. The complete result must be nonblank and fit both 8000 characters and 32000 ASCII-serialized characters; truncated text cannot be accepted. Empty, missing, changed, nonterminal, active-run or oversized results cannot be accepted.

A successful acceptance atomically commits the local done state, the supplied note, minimal evidence hashes/IDs/time and a durable receipt. It does not mutate the native card, stop a run, dispatch work or automatically accept other results. No native result body is persisted. Evidence metadata lives only in the completion receipt; task schema remains v6. The full local task record, including the human note, remains readable by separately activated existing task-model read tools. Do not mistake “raw result is not copied” for “the completion note is hidden from those tools.”

## Retry and observation limits

After an uncertain response, reuse the identical request ID and arguments. An exact retry returns the original historical receipt before native access; it does not perform completion again or prove that the native card is still unchanged. A changed request under the same key is not a retry. Do not invent a fresh key to work around an uncertain outcome.

Native and local databases are not one atomic transaction. The native card may change after it is read; the receipt records an observed snapshot, not permanent current truth. Digest matching establishes content equality, not an event watermark or protection against content changing away and back (ABA). Exact identity checks do not make editable result text trustworthy.

## Scope and remaining gates

This is an E3.2/E3.5 precursor connecting [identity-bound handoff](52-parked-kanban-handoff.md) to a deliberate local completion decision. [Advisory progress observations](53-native-progress-observation.md) still never complete a task automatically. No live Kanban, Gateway, model or installation acceptance is claimed. The workflow introduces no installation retry, native write or provider call. Full host adoption and real-world acceptance remain open on the [roadmap](08-roadmap-and-acceptance.md).
