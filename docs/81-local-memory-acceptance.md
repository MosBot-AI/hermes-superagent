# 81. Local Memory Backend Acceptance

English | [简体中文](81-local-memory-acceptance-zh.md)

Status: **original E2.7 local-backend scope accepted at main `15d690a` (2026-11-10)**. This maps the original #44 E2.7 Scope/Acceptance, not every capability in the wider memory design. The machine-readable [ledger](local-memory-acceptance-ledger.json) has exactly six scope entries and four acceptance entries, with exact test-file/function references. Its unit test checks references exist, not that a name proves behavior; execution, independent review and negative controls remain necessary.

## Original criterion mapping

| ID | Delivered local boundary and evidence family |
| --- | --- |
| S1 | SQLite canonical records, metadata events, receipts and terminal tombstones; explicit generated Markdown with revision/watermark. Projection lifecycle tests establish it is derived, not a second authority. |
| S2 | Canonical changes and projection invalidation/intent share transactions. Projection crash/retry tests establish dirty rebuild without reverting facts; filesystem deletion itself is not a cross-resource transaction. |
| S3 | Bounded explicit local CRUD under current profile/session/config admission; native lifecycle/admission/help tests establish no installation-time ingestion or new authority. |
| S4 | Fixed private edit.md is the constrained Markdown proposal import: revision/digest checks, strict file grammar, size/root/type/source controls and explicit apply. General arbitrary-folder import is not required or enabled. |
| S5 | Structured lookup and transactional FTS with short Chinese fallback, complete-query freshness checks, whole-record recall budgets, source-route/record references and omission metadata. Budget and Chinese corpus tests bound the supported behavior, not semantic recall quality. |
| S6 | Native MEMORY/USER and selected provider remain unchanged. Optional summary patches are not enabled, so their approval/capacity requirements are not bypassed or claimed implemented. |
| A1 | Real process crashes, storage faults, retries and concurrent mutation tests cover DB/projection/index recovery. A prepared projection cannot publish after forgetting; index rebuild holds the writer fence through publication. Exact-input candidate suppression prevents supported old-source re-proposal, not paraphrase recognition. |
| A2 | Local CRUD/FTS uses no paid model or remote fallback; native provider-preservation tests and the suite's socket guard retain the offline boundary. |
| A3 | Profile/namespace refusals, source-instruction data handling, bounded Chinese queries, correction/expiry/tombstone filtering are exercised through actual local/native paths. Source labels are provenance, not authenticated authorship. |
| A4 | Private POSIX storage, supported journal modes, redacted failures and explicit plaintext/backup retention limits. No encryption, WAL portability or hostile same-UID containment is claimed. |

## Truthful search freshness

Previously `search_terms` always returned `index_stale: false`, even when a missing FTS document caused silent omitted matches. The read path now checks, within the same transaction as returned records:

1. Canonical and indexed document sets each contain at most 1,000 rows.
2. Active canonical rows correspond exactly to stored FTS documents, including expired active rows; forgotten/extra rows and differing content/topic are refused without loading private text just for diagnosis.
3. The complete current query's canonical-only literal match IDs equal its FTS-plus-canonical-recheck IDs, with the same expiry filter **before** pagination or limit. This catches query-relevant missing postings even when stored documents match.

Drift returns redacted `index_stale`, no partial result and no automatic write. Use `index-status`, then deliberately `index-rebuild` with its current watermark; unknown corruption remains a failure, not a fabricated healthy result. Ordinary literal search and canonical recall do not depend on FTS and remain usable under logical drift. A healthy response labels its exact scope `logical_documents_and_complete_current_query_coverage`; it does not certify all inverted postings or replace the separate native integrity check. The additional canonical scan is explicitly bounded and is not a hidden repair or remote fallback.

## Budget and completion boundaries

Original doc30 §10 explicitly permits a conservative byte/character ceiling when a selected-model tokenizer is unavailable. Current recall budgets the full serialized ASCII JSON **items array**, including each record's source/provenance fields, quoting, escaped Unicode and list separators; whole records are omitted rather than truncated. It reports `items_json_chars`, `max_chars`, match/omission counts and skipped-for-budget counts. These are not provider token counts, not a universal chars-to-tokens conversion, and not a budget for the surrounding host prompt or conversation. Separately, activated session recall caps the complete recall-context JSON envelope (including warnings, metadata and records) at a fixed 6,000 ASCII characters; lifecycle prefetch defaults to 6,000 and is configurable from 2,048 to 12,000 ASCII characters. Whole oversized records are omitted, not truncated. The three whole-envelope tests are linked in S5 of the ledger. Provider-token budgeting stays conditional on such a tokenizer integration; the fixed fallback is the local acceptance target.

Two-connection contention evidence now opens the forget backend before the rebuild starts, waits for the actual forget `BEGIN IMMEDIATE` attempt, and proves it cannot finish before rebuild releases its fence. The reverse ordering waits for rebuild's actual BEGIN attempt while forget is before COMMIT, then requires watermark rejection. Existing projection prepare/forget/resume evidence covers the distinct stale-job case where forgetting commits before publication resumes.

The supported source suppression is namespace-local exact full-input fingerprinting for pending and newly linked accepted candidates. Legacy accepted digests cannot be reconstructed, changed input does not match, and already accepted siblings need separate forgetting. Snapshot browsing is explicit historical access, never current recall or restoration. These limits remain part of acceptance, not claims of global erasure.

The accepted original local backend package permits closing #44 after this reconciliation is merged and verified. It does not close #43's full adapter SDK/replacement contract, #45's native lifecycle/coverage work, #46's migration and recall validation, general portable backend migration or production/user-device acceptance. Runtime controlled-write gates remain blocked. Earlier comments describing these independent features as unfinished do not create circular new prerequisites for E2.7.

## Final acceptance checkpoint

PR #99 supplied the final freshness/fence corrections and criterion ledger; PRs #100–#102 did not change the memory implementation. Main `15d690adbbd860f145cbc1405399d854d6bb32c4` passed [CI 42813558369](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42813558369), including pinned native contracts, worker/runtime-package checks and artifact validation. An independent source-and-test audit of all ten original criteria found no blocker; 1,068 memory unit tests passed in that audit. The ledger records this exact accepted baseline rather than automatically certifying future revisions. CI remains necessary for subsequent changes.

This checkpoint reconciles already delivered behavior; it enables no feature, provider, remote access or deployment. The local boundary is a trusted single-user profile, not authenticated remote-owner isolation. Historical checkpoints in earlier documents describe their dates, not remaining dependencies added to this work package.
