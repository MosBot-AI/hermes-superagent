# 97. Native source review workbench

English | [简体中文](97-native-source-workbench-zh.md)

## Implemented boundary

The follow-on [explicit observed-source retention](98-observed-source-retention.md) now connects canonical acceptance through separate preview/retain commands, with actual host UUID, observed provenance and explicit retention authority. This document’s read-only and unconnected-acceptance statements apply only to `source-list`/`source-show`; those operations still do not write canonical memory, create receipts or advance cursors.

[Issue #135](https://github.com/MosBot-AI/hermes-superagent/issues/135) adds `source-list` and `source-show` to the production plugin's `/personal-memory` command. They review original transcript rows through the published `hermes_state.SessionDB` read API, without a host patch. The compatibility target remains Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. Production-package code is not evidence of installation, production deployment or live personal-data acceptance.

The existing explicit local-memory configuration and origin gates remain required: `mode: local_tasks`, `local_conversation: true`, `local_memory: true`, the admitted current profile and the exact current Gateway-backed LOCAL session binding. The reader opens only that profile's existing fixed `state.db` with `read_only=True`. Requests cannot choose a path, profile or session, search other stores, or include ancestors, inactive or compacted rows. Missing, unsafe or malformed stores are refused rather than created, migrated, repaired or chmodded. Profile selection is not verified user identity, and trusted in-process Python is not a security sandbox.

## List, select and show

Use the native command in the admitted local conversation:

```text
/personal-memory source-list
/personal-memory source-list --limit 20
/personal-memory source-list --limit 10 --after UID --expected-snapshot HASH
/personal-memory source-show UID --expected-snapshot HASH
```

Replace `UID` with a returned `message_uid` and `HASH` with that list's `snapshot`. A UID is 32 lowercase hexadecimal characters; the snapshot is 64. The default page size is 10, with a maximum of 20. The first page may optionally include `--expected-snapshot HASH`. Every continuation using `--after` and every show require the expected snapshot. Use the returned `next_after` for the next page; null means there is no next page. This is observation-bound pagination, not a durable processing cursor.

List returns metadata only: UID, original role, character and UTF-8 byte counts, exact content SHA-256 and absorbed-UID count. It does not return excerpts. Show returns one selected complete original `user` or `assistant` row and its absorbed UIDs, without truncating or summarizing the content. Both report the snapshot, eligible/excluded/scanned counts and read consistency. The existing `--json` prefix is available, for example `/personal-memory --json source-list`.

Only eligible original rows can be selected. Tool-related rows, display rows, blank content and conservatively recognized compaction summaries are excluded. Quoting a recognized summary marker may also exclude a row; this classifier does not establish authorship or authority. Excluded rows still participate in validation and observation identity. Ambiguous or malformed row identities/lineage fail the whole observation rather than silently dropping evidence. A well-formed UID absent from the eligible set is not selectable.

## Bounded observation and freshness

Each page and show reads and validates the whole bounded active current-session observation, not just the requested page. Limits are 256 scanned rows, 16,384 characters per row and 65,536 characters in total, with the existing source-lineage limits. Over-limit observations fail rather than returning a partial scan. The host decoder can allocate stored rows before plugin payload validation; these limits are not a pre-allocation byte or memory guarantee.

The digest binds the profile's transient filesystem identity, native session revision, and the complete validated observation's row IDs, UIDs, content and lineage, including excluded rows. The reader uses the public transcript snapshot and verifies its generation; it rechecks the fixed file binding before returning. `read_consistency` distinguishes `pinned` from `generation_validated`. This detects supported observation changes, not arbitrary tampering, a durable store identity, or replacement with an old backup that evades those observations.

A changed digest fails with `source_snapshot_changed`; a detected in-flight generation or binding change fails with `source_generation_changed`. Run a fresh list, review it again and select from that new snapshot. Do not substitute a fresh hash blindly. Invalid arguments, unsupported origins, unavailable storage and incomplete/unsupported reads also fail closed. A successful read does not lock future publication or promise the source remains available afterward.

Native slash-command dispatch does not itself append these requests/replies to the transcript. The verification target includes an actual list-to-show dispatch sequence with unchanged native revision, rather than assuming every command necessarily invalidates its own snapshot. Other conversation activity or transcript changes can still invalidate it.

## Privacy and unfinished acceptance

The operations do not write native transcripts or canonical memory, retain a plugin-side source receipt, advance cursors, ingest automatically, expose a model tool, change HTTP contracts, install providers or activate checkpoint-v2. The returned observation is not a durable checkpoint, native source receipt, stable store identity or authorization. A content fingerprint is exact matching metadata, not anonymization, factual verification or permission. Source text remains untrusted evidence.

Showing content can disclose private transcript text into the user's client or history. Later native deletion cannot retract copies already displayed or retained there. Metadata and fingerprints also require private handling. The read-only plugin boundary does not guarantee that the client forgets responses.

The [retained-source acceptance](96-retained-source-acceptance.md) SDK path has a separate receipt-backed provenance and retention contract. This workbench does not invoke it. Connecting observed sources to canonical acceptance still requires an honest tagged provenance/stable-identity design and explicit retention authority. Do not fabricate a `receipt_id` or relabel an observation hash as a receipt from the #134 acceptance implementation. Native source lifetimes, canonical retention and client copies remain separate.

## Verification

Run `python scripts/check.py` for repository unit, static and bilingual documentation checks. Run the [pinned native development checks](../README.md#development-checks) with the separate Hermes checkout and interpreter to establish host compatibility. Use isolated temporary homes and synthetic transcripts only.

Review parser bounds, metadata-only pagination, exact full-row selection, snapshot mismatch/relisting, excluded/ambiguous rows, malformed or unsafe stores, row/content limits, read-only behavior and current-profile/session gates. Native checks should exercise the real public SessionDB API and actual command list-to-show dispatch without transcript revision changes. Record actual executed results, exact revisions and independent review in the PR; this document does not claim test counts or passing production acceptance. The broader source lifecycle, canonical acceptance integration and full memory roadmap remain open.
