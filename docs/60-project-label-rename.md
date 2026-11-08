# 60. Atomic Local Project-label Rename

English | [简体中文](60-project-label-rename-zh.md)

This explicit local command renames a whole task label group, including its done
and cancelled tasks, without breaking same-project dependencies. It is an E2.1
local-domain slice, not a native Project identity, worker operation or completed
E2 package. No reminder, board, directory, external resource or model is contacted.

## Preview and explicitly apply

```text
/personal-tasks project-rename-preview --project "Old name" --new-project "New name"
/personal-tasks rename-project --project "Old name" --new-project "New name" --expected-snapshot HASH --request-id rename-1
```

Use the actual `snapshot` hash returned by the first command. Preview reports the
exact old/new labels, total count and captured/done/cancelled counts, but no task
text. Inspect task lists separately if needed. The equivalent CLI prefix is
`hermes personal-agent tasks`; native output defaults to readable text and accepts
leading `--json`. CLI defaults to JSON and accepts `--format text`.

Both labels use existing exact case-sensitive validation (1–80 characters, no
leading/trailing whitespace or control characters). They must differ. The source
must exist and contain at most 1,000 tasks. The destination must have **no tasks**,
even terminal ones; this never merges groups or includes unassigned tasks.

The snapshot binds both labels and the sorted source task IDs/revisions/states.
Any captured task, removal from the group, or revision change invalidates it.
Destination occupancy is checked again when applying. A snapshot is a concurrency
check, not an authorization token or a lock held between commands. Existing local
profile/operator admission still applies; a copied hash grants no new access.

## Transaction and recovery

Apply takes one `BEGIN IMMEDIATE` writer transaction, validates the current group
and all dependency references, compares the snapshot, then changes every label.
Every affected task gets one new revision and timestamp plus a `rename_project`
metadata history event. Dependency edges, task state, due date, working/progress
notes, resolution evidence and existing native observations are preserved. Terminal
tasks remain terminal: this is a narrowly explicit label change, not reopening or
editing their completion evidence. No partial rename is committed if any step fails.

Revisions invalidate stale task edits and revision-bound grants/snapshots. Existing
native cards, handoff ledgers and saved progress are not renamed or refreshed;
renaming local labels is not synchronization with them. Review their existing
revision/identity checks before using a stale handoff. Stored histories and old
retry receipts remain historical; already supplied model context is not rewritten.

The stable explicit request ID is mandatory. Exact retries return the original
metadata-only receipt, even after a later rename or restart. They do not relabel
new tasks that subsequently reuse the old name. Changed arguments with the same
key conflict. For an uncertain outcome, retry the same key and arguments; do not
silently mint a new key. A stale preview requires explicit fresh review.

No schema migration is introduced. Like existing task reads, opening the store
may initialize/migrate supported older task schemas even for a logical preview.
The output is bounded; the database scan cost is not a large-store latency promise.
There is no automated rename, new model-tool action, remote API or broad terminal
mutation permission.

## Verification boundary

Synthetic unit coverage exercises connected active/terminal tasks, retained
resolution/progress fields, concurrent identical requests, stale previews,
destination collisions, exact labels, bounded groups, corrupt edges, storage
rollback and restart replay. Native command parsing/presentation is exercised
without a model or Gateway. Full live Gateway/user acceptance is not claimed by
these offline tests. This change does not establish power-loss durability,
backup/restore or external exactly-once delivery.
