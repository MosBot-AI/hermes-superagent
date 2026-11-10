# Local multi-term memory search

English | [简体中文](66-local-memory-full-text-search-zh.md)

## Explicit search without a remote service

In an already admitted local memory session:

```text
/personal-memory search-terms "Shanghai" "Hermes" --limit 10
/personal-memory search-terms "project" "deadline" --include-expired
```

The separately activated `personal_memory_read` tool accepts `action: "search_terms"` and `terms: ["Shanghai", "Hermes"]`. Existing configuration, session, scope, unload, worker/cron and finalization gates remain unchanged. This does not enable automatic recall, ingestion, a new provider or a new remote recipient. As with other memory reads, returned text may enter the already configured model/session history.

Provide 1–8 distinct literal terms, each 1–128 characters. Every term must occur in the current content or topic; different terms may match different fields. Matching is case-sensitive, without stemming, normalization, pinyin, synonyms or identity inference. Existing `search` and `recall` retain their original literal semantics and ranking. FTS operators, quotes, punctuation and wildcard-looking characters are literal data, never an accepted query language.

Terms of at least three Unicode characters use SQLite FTS5's case-sensitive trigram index to select candidates, then all terms are rechecked against canonical records. One/two-character terms use canonical substring checks, including short Chinese names. With only short terms, this scans at most the existing 1,000-record store capacity. This is not a Chinese segmentation, semantic retrieval or person-disambiguation implementation. No latency or accuracy benchmark is claimed.

Results contain whole canonical records with IDs, revisions, source-route metadata, expiry and evaluation time. Source labels do not prove truth, original authorship or authorization. Results are newest-created first, default 20 and maximum 50 per page; use `next_cursor` as `after`. Pages are live, not a frozen multi-page snapshot. `has_more` exposes page truncation; the limit is records, not a token budget. Ordinary searches exclude expired records. `--include-expired` is explicit inspection, not renewed validity. A no-match result is not proof a fact is absent.

## Transaction and deletion guarantees

Schema v7 maintains the index in the same SQLite writer transaction as records, metadata events and idempotency receipts. Remember, correct, forget and reviewed candidate acceptance share this path. Failed index changes roll back the canonical mutation; exact retries return the original metadata receipt without reinserting historical content. Forgotten records are terminal. Search joins candidate row IDs to current canonical records and rechecks status, expiry and every term in one read snapshot.

There is no delayed index job, background publication or second writable authority in this slice. `index_stale: false` now requires logical document correspondence and complete current-query coverage inside the read snapshot. It is not a global forensic corruption detector or protection against hostile same-UID database tampering. A read already admitted before a concurrent forget may return its older snapshot; later fresh reads cannot retrieve the forgotten record. Prior model context, history, exports and backups cannot be retracted.

Both SQLite `PRAGMA secure_delete` and the separate FTS5 `secure-delete` setting are required. Correction/removal deletes obsolete indexed text rather than merely retaining FTS deletion markers. This remains logical local removal, not a physical-media, filesystem snapshot or backup erasure guarantee. Expired active records remain stored/indexed and are filtered at read time. The store is plaintext and is not a secret vault.

## Migration and compatibility

Opening an exact owned v1–v6 store for a permitted write atomically creates/fills the index and advances to v7 while preserving records, receipts and events. Read-only provider/recall opens never create or migrate: an old schema returns `readonly_schema_unavailable` until an explicit local writer upgrades it. No runtime downgrade is supported: older plugin versions reject v7. Preserve any backup under the existing privacy/retention policy before upgrading; restoring an older backup can restore previously forgotten payload and is not authorized by this feature.

SQLite must provide FTS5, the trigram tokenizer and FTS secure-delete (SQLite 3.42 or later). Unsupported builds fail closed, without downloading an extension or changing query semantics. The exact virtual/shadow schema and secure-delete configuration are checked. No permissive triggers or `trusted_schema` relaxation is used. The development interpreter tested here is Python 3.14.9 with SQLite 3.53.1; this is not a claim of compatibility with every SQLite build or OS.

## Acceptance scope

Synthetic unit and pinned-host contracts cover mixed Chinese/English terms, short strings, punctuation/query injection, paging, expiry, mutation and candidate rollback, restart/replay after forgetting, namespace rejection, non-migrating read-only access and existing native permission gates. They are not a live personal-data benchmark, user acceptance or production deployment. Markdown projection, adapter migration, automatic extraction and complete E2.7 remain separate work.

Current search freshness now fails closed with `index_stale` on logical document or current-query coverage drift, within one read transaction and before pagination. No partial results or automatic repair. See [acceptance evidence](81-local-memory-acceptance.md).
