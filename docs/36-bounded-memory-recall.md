# 36. Bounded Explicit Memory Recall

English | [简体中文](36-bounded-memory-recall-zh.md)

Status: implemented on the existing local record store, as an explicit native command and separately activated model read action. This is a useful retrieval step toward [30](30-pluggable-memory-contracts.md), not automatic prompt injection, semantic search, source-bound extraction or the native MemoryProvider bridge. Existing providers and profile settings are unchanged.

## 1. Commands and Activation

With the existing [local memory opt-in](31-explicit-local-memory.md), use:

```text
/personal-memory recall "breakfast" "oat milk" --limit 6 --max-chars 6000
```

With [memory model tools](32-session-scoped-memory-tools.md) separately configured and `/personal-memory-tools enable-read` or `enable-write` active, the configured model can request:

```json
{"action":"recall","queries":["breakfast","oat milk"],"limit":6,"max_chars":6000}
```

The action belongs to `personal_memory_read`. Task-tool activation does not grant it. Missing/expired activation, wrong session/route/profile, missing live native turn, reload, unload and disabled configuration retain the existing denial behavior. No new permission, background callback, model call, schedule or provider selection is introduced. Direct commands rely on the same trusted single-user native LOCAL admission as other memory commands.

## 2. Deterministic Retrieval and Bounds

`queries` contains 1–8 distinct, nonblank literal strings, each at most 128 characters. Matching is case-sensitive substring matching against current content or topic. Chinese and short keywords work without a tokenizer; SQL wildcards and quotes remain literal. There is no stemming, translation, semantic similarity, inferred query expansion or external embedding service. Choose useful keywords instead of treating a whole natural-language question as semantic search.

Rank matching records by number of distinct matched queries, then number matching the topic, then newest record creation sequence. Correction does not make an old record newly created. A record appears once even when multiple queries match. `matched_queries` holds zero-based positions in the submitted query list; it is not a confidence score. `limit` defaults to 6 and accepts 1–20.

`max_chars` defaults to 6,000 and accepts 1,024–12,000. It bounds the exact ASCII JSON serialization of the returned `items` array, including metadata, escaped Unicode, quotes and separators: `json.dumps(items, ensure_ascii=True, sort_keys=True)`. `items_json_chars` reports that length. This is not a tokenizer budget and excludes the small response metadata and native tool/command envelope. Chinese characters use escaped JSON space, so fewer records may fit than with ASCII text.

Only complete records fit into the result; stored text is never cut or summarized. An oversized record is skipped and smaller lower-ranked matches can still fit. `matched_records` counts all matching active records. `omitted_records` counts matches not returned due to the record limit or size budget. `skipped_for_budget` counts records actually considered and rejected for size before the limit was reached, not every remaining match. If all matches are too large, `items` is empty while the match and omission counts remain nonzero. Use `show`, existing search/pagination, a narrower query or a larger permitted budget to inspect omitted data. An empty result is not proof that the user has no such preference or that a fact is false.

## 3. Snapshot, Corrections and Forgetting

Matching, record contents, ranking and the event `watermark` are read within one SQLite transaction. The bounded store has at most 1,000 retained records; recall rejects an excess rather than silently scanning an unbounded store. No persistent retrieval cache, extracted summary, derivative index, new schema or migration is added.

Each returned record includes its ID, current revision, content, topic, latest editing route, session reference and timestamps. `explicit_local_operator` and `activated_session_model` are route labels, not verified original authorship or source-message citations. Recalled text is data, not instructions, approvals or permissions. There is no automatic conflict resolution or factual certification.

A later recall sees committed corrections and excludes terminally forgotten records. Historical mutation-receipt replay does not restore forgotten payload. The response is an observation at one read snapshot and may be historical once that transaction ends; `watermark` is metadata, not a reusable snapshot token or authorization. Forget cannot retract an already returned response, existing model context, normal host history, backups or exports. No stronger concurrent-delivery or global-erasure guarantee is made.

## 4. Backend and Verification Boundaries

The local backend advertises the optional `bounded_recall` capability alongside `explicit_records` and `literal_search`. `MemoryService` requires all three before calling the backend, validates action-specific fields and enforces negotiated query/page limits. An older or reduced backend without this capability fails with `capability_unavailable`; it does not fall back to an unbounded list or assemble inconsistent multi-call results. The existing descriptor API and storage schema versions are unchanged.

Offline tests cover strict bounds/types, literal/Chinese matching, ranking/ties, whole-record omission, exact serialized budgets, source labels, reopen/correction/forget/replay, adapter capability denial and native admission. Native contracts exercise the real pinned slash dispatcher and model-tool registry, plus four fresh guarded processes for recall, correction and forgetting. These are deterministic synthetic-data tests without a live model or socket listener. They do not certify the configured model's keyword choices or end-to-end Gateway transport. E2.7 gains bounded explicit recall; automatic lifecycle integration and E2.8 remain unfinished.
