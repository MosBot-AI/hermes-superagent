# 69. Bounded Chinese Automatic Recall

English | [简体中文](69-chinese-automatic-recall-zh.md)

Implemented local development slice of #45, with synthetic evaluation toward #46. It improves unspaced Chinese questions in the existing [session recall](49-session-memory-recall.md) and optional [native provider](41-native-memory-recall.md). It does not select a provider, deploy the plugin or complete either work package.

For the current syntax-aware literal-slot extension and its separate evaluation, see [document 103](103-automatic-recall-slots.md). The behavior and fixed comparison below describe this original slice; its historical evidence is unchanged.

## Query and selection behavior

Only the current original plain-text input is used. Existing admission, profile/session scope, configuration, activation and revocation gates remain unchanged. No history, sender claims or tool output becomes a query. No model request, network access, vector model, recalled-payload cache, automatic write, extraction or schema migration is added.

`memory_query.automatic_recall_terms` uses a finite list of Chinese question/function-word boundaries, not a general tokenizer or semantic model. For example, an unspaced question about breakfast yields the literal breakfast term; a person's birthday question yields the name and birthday attribute. Han and adjacent non-Han runs are separated; Latin words/numbers retain internal connectors, but isolated boundary `-`/`_` fragments cannot become queries. Every term is an unchanged case-sensitive substring of the input. There is no synonym expansion, traditional/simplified conversion, name resolution or inference from negation. Boundaries can cut a name or leave an unfamiliar compound intact.

The existing limits remain: at most 2,048 input characters, eight distinct terms and 128 characters per term. Invalid inputs and slash commands produce no lookup; existing host trivial-prompt handling remains in its existing routes. Terms are selected in input order, so long questions can lose later detail.

Both automatic consumers perform one existing bounded `recall` read and call the same `filter_automatic_recall` helper. Only when Han input produces a changed plan relative to the old deduplicated first-eight literal chunks, and there are at least two terms, returned records must match at least two terms. Single-term and unchanged plans retain existing behavior. This is a conservative relevance heuristic, not a claim of matching the correct person or answering the question.

Filtering occurs **after** the original bounded pack, without another read, refill or expanded budget. Ranking remains matched-query count, topic-match count, then newest creation. The session route still returns at most six whole records within its entire 6,000-character escaped JSON context. The optional provider retains its configured limits. An empty filtered result supplies no memory context. Explicit `search`, `search_terms` and `recall`, including model-tool actions, retain their existing literal semantics.

When the filter applies, `automatic_filter` reports `minimum_matched_terms: 2`, `filtered_returned_records` and `refilled: false`. `matched_records` remains the original snapshot's literal-match count; removed results increase `omitted_records`, and `items_json_chars` is recomputed. Existing budget omissions remain omissions, not proof that a fact is absent. Corrections, forgetting and expiry affect the next fresh read; already supplied context/history is not retracted. Stored records remain untrusted data, never permission or instructions.

## Fixed offline comparison

The independently authored [fixture](../tests/fixtures/chinese_recall_eval.json) was locked before evaluation: 28 synthetic records, 48 queries (36 positive, 12 negative), SHA256 `2cb38dd1d3cad885d1aa4bfb5b142a9c23f13cd489f2ba5b03685fda1bb86725`. It includes short/same-name Chinese entities, mixed scripts, dates/numbers, negative facts, correction/forget/expiry, unrelated queries, injection-like text and an unsupported cross-script stress case. Relevant labels identify records needed for a question; a shared person's unrelated attribute is not relevant. No labels were changed to improve results.

The [evaluation script](../scripts/evaluate_memory_recall.py) compares the frozen `1740a85` literal planner, the unfiltered splitting experiment, and the actual shared conservative filter on the same database and 4,976-character record budget. No model is called. Reproduce from the repository with its Python 3.14 environment:

```sh
python scripts/evaluate_memory_recall.py --repeats 5 > /tmp/chinese-recall-evaluation.json
```

The report includes source hashes, fixture hash, per-query retrieved/missed/irrelevant IDs and metrics at 1/3/6. The measured development worktree was based on `1740a85e34bf066cae047347a11f1e15a8dd136b`, not an already released revision; source hashes distinguish its changed implementation. The compatible native pin is `2281116525106e3c109993ccb5dc74d02bfc1427`; this standalone retrieval benchmark does not exercise native admission or a real model.

| Strategy | Returned-item precision @6 | Micro recall @6 | Empty positive queries /36 | Negative queries with results /12 |
| --- | ---: | ---: | ---: | ---: |
| Old literal chunks | 100% | 35.1% | 24 | 0 |
| Split, no conservative filter | 85.7% | 81.1% | 7 | 3 |
| Shipped conservative selection | 100% | 64.9% | 13 | 0 |

Precision here divides relevant returned records by all returned records, **not** a fixed six-slot denominator. The script separately reports fixed-k precision. Recall uses 37 relevant query-record pairs. The conservative choice prioritizes avoiding unrelated private facts in automatic context, at the cost of relevant records matching only one strong term. It still misses 13 positive queries, including compound/short-name wording and traditional/simplified differences. **100% precision on this small synthetic corpus is not a population or production guarantee.** A retrieved negative fact is relevant evidence, not proof of a correct answer or negation understanding. FTS/vector/reranker comparison and long-chat/compaction certification remain unperformed.

## Timing and verification boundary

Observed cloud environment: Linux 6.18.57 x86_64, AMD EPYC 9V74 (9 CPUs visible), Python 3.14.9, SQLite 3.53.1. Five repeats give 240 observations per strategy/mode. Nearest-rank milliseconds:

| Strategy | Fresh connection p50 / p95 | Reused connection p50 / p95 |
| --- | --- | --- |
| Old literal chunks | 0.392 / 0.627 | 0.123 / 0.225 |
| Split, unfiltered | 0.420 / 0.592 | 0.138 / 0.265 |
| Conservative | 0.431 / 0.633 | 0.144 / 0.254 |

“Cold” means fresh read-only connection, schema validation, planning, recall and close; the OS page cache was **not** flushed. “Warm” means planning and recall on a retained connection. These exclude model latency, lifecycle admission and full context-envelope construction. The tiny corpus and shared cloud hardware do not establish production latency, general Chinese quality or cost savings.

Unit and pinned-native contracts cover shared routing, bounded terms, connector fragments, unchanged explicit operations, fresh correction/forget/expiry, filtering/counts, whole-record budgets and existing access gates. Real-device Chinese conversations and live-model answer quality remain separate acceptance work; no installation, provider selection, credential use or deployment is claimed.
