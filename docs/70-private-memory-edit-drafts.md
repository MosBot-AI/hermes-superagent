# Private Markdown memory edit drafts

English | [简体中文](70-private-memory-edit-drafts-zh.md)

## Purpose and explicit workflow

This local operator workflow lets an editor capture a new memory or change an existing memory's content and topic without putting a long body into a command line. SQLite remains the only authority. This is not arbitrary Markdown import, batch migration or a second writable memory store. The generated records.md projection, Hermes MEMORY.md and USER.md are not edited by this workflow.

    /personal-memory edit-new --keep --request-id capture-1
    /personal-memory edit-status
    /personal-memory edit-create RECORD_ID --expected-revision 3 --request-id edit-create-1
    /personal-memory edit-preview DRAFT_ID
    /personal-memory edit-apply DRAFT_ID --expected-digest SHA256 --request-id edit-apply-1
    /personal-memory edit-discard DRAFT_ID

For corrections, edit-create requires the current target revision and returns the draft identity and cleanup notice. There is at most one active draft per profile. Use edit-status to recover its ID and lifecycle state if the create response or file was lost; it does not create a draft or read its body. Unsafe file conditions appear as a redacted file_check_error while the registered draft ID remains available; status does not repair or delete the file. Replayed creation returns lifecycle state, not a promise that the file still exists. Save the draft ID and request ID; use the same request ID and identical arguments for an uncertain create/apply retry. Native commands can generate an ID when it is omitted, but a newly generated ID is not the original operation's retry.

The fixed file is memory/edit.md beside records.sqlite3 in the private profile plugin directory. The reserved .edit.md.pending path is managed staging, never a separate user document. No arbitrary input or output path is accepted. Explicit creation registers these fixed paths as the draft lifecycle's property: **apply or discard removes their contents, including manual edits; for correction drafts, target correction or forgetting also removes them.** Without an active registration, existing files are unknown and are not silently adopted, overwritten or deleted.

## First capture in an editor

Use `edit-new --keep` for explicit retention without a deadline, or `edit-new --expires-at 2030-01-01T00:00:00Z` for a fixed UTC deadline. There is no implicit retention default. This creates a blank managed draft, not a canonical record. Fill its content and optional topic in an editor, then run edit-preview and review the complete proposed text and retention before edit-apply with the returned SHA-256. An empty body cannot be previewed or saved. The new and correction workflows share one active slot; discard or finish it before starting another draft.

The file cannot change the chosen expiry or choose an existing record, namespace, source author or permission. To change the retention choice before first capture, discard the draft and start another. Apply creates exactly one new record through the ordinary remember path and commits its canonical event, FTS changes, retry receipt and draft terminal state together. It does not invoke a model or treat the text as instructions. The source identifies the explicit local operator route, not verified authorship or factual truth.

New-record preview must be understood as **creation**, not a correction or merge. Reusing the original create/apply identities returns lifecycle/historical metadata, even after the resulting record has been corrected or forgotten. It does not restore the file or recreate the record. A new independent draft requires fresh create and apply request IDs. An apply ID already used by another remember operation is rejected even if its text matches. New capture is a new explicit action: no semantic duplicate detection or general source-level suppression is promised. This is not a generic Markdown importer, folder scan, synchronization or migration workflow.

## Editing and reviewing

Keep the generated title and identity JSON line byte-for-byte unchanged. The Topic line contains one JSON string; edit its value while keeping valid JSON. The next blank line separates metadata from the editable multiline content. The body is literal text, including any Markdown syntax, not executable instructions. Content and topic retain canonical limits of 2,048 and 128 characters; preview/apply inputs are bounded to 32 KiB. Oversized but otherwise safely owned registered files can still be discarded or cleared by target forgetting without reading their payload. The generated identity, namespace, target revision (for corrections), source attribution and expiry cannot be supplied or changed by editing the file.

For corrections, preview reads the current file and target, returning the full before/proposed content and topic, SHA-256, baseline revision, unchanged expiry and cleanup notice. For new capture, it returns the complete proposed content/topic and chosen expiry without inventing an existing target. Review these values, not just a success flag. Preview does not change canonical memory. For corrections, apply re-reads the file, verifies the exact reviewed digest and checks the target revision before performing the normal canonical correction. A changed file or target is a conflict, not an invitation to silently rebase. There is no automatic acceptance or fallback to creating a new record.

For corrections, the existing expiry is preserved. Correcting an expired record does not renew it. A new capture uses the deadline selected when the draft was created; time spent editing does not extend it. An accepted correction updates the normal event/receipt and FTS paths and invalidates a managed projection. It does not make untrusted draft prose into authorization, verified source authorship or instructions. These commands remain operator-only; model tool schemas and session permissions are unchanged.

## Files, forgetting and recovery

Owned private POSIX directories and ordinary single-link files are required; unsafe modes, links and unsupported file types are rejected rather than repaired. Editors may replace the registered file atomically. Once registered, path lifecycle ownership, not an unchanged hash or inode, permits cleanup of manual edits. Same-user hostile filesystem modification remains outside the trusted local boundary.

Schema v10 distinguishes new and correction drafts and stores the fixed new-record expiry alongside bounded lifecycle metadata, not a copy of the draft body. Existing schema-v9 correction drafts and their identities/receipts are preserved during migration. Supported writable openers migrate; read-only access cannot migrate. Up to 1,000 total draft metadata rows are retained, including terminal identities needed for retry fencing. This limit affects new creation, not normal discard, forgetting or cleanup. There is no automatic expiry timer or background cleanup; a draft remains until explicitly discarded/applied or invalidated by a change to its target.

Creation uses a durable preparing intent followed by publication under the shared SQLite writer fence. Before writing the draft, the publisher rechecks the active intent and, for corrections, the target revision. A paused old publisher cannot resume across a committed target correction/forget and recreate old plaintext. Target mutations must remove registered draft/staging files and sync their directory before committing. A bare backend without the necessary file adapter cannot bypass this obligation. Other records' changes do not silently consume the active draft.

SQLite and files are **not one atomic resource**. A crash after file removal but before database commit can leave an active registration with no file. A ready draft is not silently rebuilt because that would discard the user's edits; preview reports the missing file and explicit discard can clear the registration. An interrupted preparing intent may be recovered only while its identity and, for corrections, target remain valid. Exact terminal retries return metadata receipts without recreating files or reapplying corrections. Unknown replacement files after terminal state are not part of an old retry's cleanup.

Forgetting does not retract previously opened file descriptors, editor buffers, host history, copies, backups or physical storage traces. The managed-file cleanup guarantee applies only to the registered local draft and staging under the supported deployment conditions. Do not use these plaintext files for secrets.

## Verification boundary

The slice requires new/correction create/edit/preview/apply/discard and restart tests, schema-v9 draft migration, fixed-retention and single-slot checks; stale digest/revision and forgotten-target refusals; publication/forget and apply/correct races; file and database failure windows; unknown-file and link/mode protection; terminal retry fencing; canonical FTS/projection consistency; schema migration and real pinned-host command admission. Final completed checks belong in the linked PR evidence.

This is a narrow editor-based capture and correction workflow within #44. General import, manual changes to generated records.md, portable migration and source re-extraction suppression remain separate work. No provider selection, real model call, installation or deployment is implied.
