# 102. Synthetic Longitudinal Memory Acceptance

English | [简体中文](102-longitudinal-memory-acceptance-zh.md)

## Scope and independent fixture

[Issue #145](https://github.com/MosBot-AI/hermes-superagent/issues/145) adds a bounded diagnostic toward #46, not production or live-model acceptance. The [fixture](../tests/fixtures/longitudinal_memory_recall.json) was authored independently and frozen before any production query evaluation: SHA256 `4e504fd7b2c84bcf2418a482f5769eecf845e84b2a56cd1c6237f7c2bc5ed2dd`. Neither its relevance labels nor production retrieval were tuned after seeing results. The historical 28-record evaluator and its document-69 evidence remain unchanged. The unavailable local knowledge base was not used to invent prior decisions; repository contracts are the evidence.

The cumulative synthetic store grows from 28 to 250 to 1,000 retained rows, including tombstones and expired rows. It adds mineral-catalog filler and eight independently chosen same-entity distractors. Thirty-seven fixed queries cover short and same-name entities, Chinese and mixed-script wording, dates/numbers, negative facts, injection-like stored data, correction, forgetting, expiry and unsupported cross-script matching. An unrelated attribute of the right person/project is not labeled relevant.

The stage clock advances across the explicit expiry boundary. Ordinary memory correction and forgetting, plus correction/forgetting of two explicitly retained receipt-backed synthetic source records, use current production APIs. Receipt labels are deterministically SHA256-encoded for the SDK's digest fields. These are trusted synthetic source fixtures, not genuine native receipt issuance, source authenticity or automatic ingestion. Expiry in this corpus applies to an ordinary record, not a retained-source record.

## Exercised runtime and safety oracle

The [runner](../acceptance/memory/runner.py) copies the current source into a private temporary plugin fixture and uses the existing pinned-host contract helpers. The real plugin loader registers the production pre-LLM hook; real LOCAL command dispatch activates memory reads and recall; the real Relay turn coordinator and native hook collector exercise `RecallingSessionMemoryTools`, current-profile admission, original-input query planning, SQLite read-only opening, conservative filtering and complete ASCII-escaped JSON assembly. No planner/recall implementation is substituted. The already-authenticated in-memory transport fixture is not authentication proof, official installation or a running Gateway. No listener, model, provider credential or external connection is started. Child processes use an allowlisted environment and deny network connections.

Each stage is read in three different processes: initial evaluation, unchanged-state restart, and after supported same-profile maintenance preview/prepare/commit. Process-local activation must be absent before explicit renewal. Logical envelopes, exact record fields and envelope sizes must match. Only the documented fresh `memory.evaluated_at` timestamp is eligible for normalization; the fixed expiry clock normally makes that identical too. No UUID, revision, provenance, source field, expiry, omission or budget field is normalized away. All database table rows are independently captured before/after reads, refused probes, historical retries and repack. This is current-store repack, not historical restore or transcript compaction.

Hard checks are separate from measured relevance:

- Every complete context is ASCII JSON, at most 6,000 characters and six whole records. IDs are unique, current payload/provenance/revision fields agree with canonical reads, and omission, item-size and filter metadata are internally consistent.
- Canonical content, topic, revision, expiry and stored status are also compared with an independent state derived from fixture additions and mutations. Forgotten payloads remain cleared tombstones; the expired record remains stored and inspectable. Fresh contexts exclude the stage's forbidden IDs and stale payload markers.
- At least one admitted context must exist per stage so an entirely broken hook cannot pass vacuously. This health condition is not a relevance threshold. Empty/slash inputs and recall-off return no context.
- Forgotten records reject correction. Exact source-identity reentry rejects with `source_identity_conflict`; a new identity with the same fingerprint rejects with `source_suppressed`. The 250-row probe establishes suppression independently of the full-store limit. Original accepted retries return historical metadata without changing current state. A 1,001st retained row refuses with `record_limit`, without eviction.
- Scoped exception tracing observes production exceptions even when the recall code catches them; hook failure logs are also fatal. A single-query swallowed-failure negative control prevents an exception from being mislabeled as a relevance miss. Negative-control tests prove that stale/truncated payload, full-envelope overflow, duplicate IDs, corrupted omission/filter/budget metadata, changed restart context/budget and an all-empty hook are detected. Relevance misses remain reportable results, not reasons to rewrite labels.

Deleting native original text is **not** treated as deleting independently retained canonical memory. This runner does not delete a native transcript. Source-loss and real packaged Gateway behavior remain the distinct [document-99 lane](99-packaged-memory-lifecycle.md).

## Retained-source migration and maintenance composition

The separate [retained helper](../acceptance/memory/retained.py) uses SDK/SQLite fixtures, not native hooks. It creates receipt-backed schema-12 accepted/corrected, accepted/forgotten, discarded and pending decisions, migrates through the ordinary writable opener to schema 13, then adds the equivalent observed-source cases. Legacy request digests and receipts must survive migration. Pending decision, completed cursor, status, lineage and suppression metadata must survive supported repack and fresh-process reopen, including exact historical retries and refused new admissions.

Two fresh profiles cover normal cutover and one controlled process exit after preserving the old database but before installing the staged database. Explicit recovery completes the same recorded intent. Eight decisions per profile and two fresh verification processes are checked. This composes existing mechanisms without another broad crash matrix, native transcript repack, authority transfer or claim of physical erasure. Preserved old files can retain historical plaintext.

## Observed relevance and limits

The [machine-readable report](longitudinal-memory-acceptance-report.json) includes every query's retrieved, missed and irrelevant fixture IDs, complete context, envelope size, visible omissions, scoped timing, process evidence, fixture/source/harness hashes and maintenance results. Source hashes identify the tested tree; a local worktree commit is not a published release. The test used Python 3.14.9, SQLite 3.53.1 and clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`.

| Retained rows | Relevant returned / all returned | Relevant returned / labeled pairs | Positive queries with no result | Maximum complete envelope |
| --- | --- | --- | --- | --- |
| 28 | 16/16 (100%) | 16/32 (50.00%) | 15 | 1,453 characters |
| 250 | 13/14 (92.86%) | 13/28 (46.43%) | 14 | 1,709 characters |
| 1,000 | 13/14 (92.86%) | 13/28 (46.43%) | 14 | 1,710 characters |

These are returned-item precision and micro recall, not six-slot precision or answer correctness. To avoid inflating usefulness with literal lifecycle controls, the report separately excludes `old_city_probe`, `empty` and `slash`: the initial recall becomes 15/31 (48.39%); later stages remain 13/28. All 6 initial and 10 later empty-ground-truth queries returned nothing. The added `aurora_logo` is irrelevant to `mixed_owner` but is returned at 250 and 1,000 rows. Fifteen initial and fourteen later queries miss relevant evidence, including same-name ambiguity, commute, negative-food/course wording, flight, budget, mixed database, long keys wording, movie, current city, injection sample and cross-script forms. The report preserves the exact per-query list.

Two omissions are visible in returned envelopes at each stage. For 21 initial and 24 later queries no envelope is returned, so omission metadata is **unknown**, not zero and not proof of absence. Maximum observed envelopes are well below the ceiling: this corpus does not saturate the 6,000-character budget. Separate overflow negative controls and existing production budget tests cover that bound; no claim of a stress benchmark at every budget edge is made. The predominantly unrelated bulk filler and this synthetic fixture do not establish population quality, semantic retrieval, long-chat answer quality, model savings or production latency.

## Reproduce and evidence

Use the prepared Python 3.14 interpreter and exact clean checkout; the runner verifies the compatibility pin and refuses a changed fixture digest. It owns and deletes its temporary synthetic profiles. Do not point it at a real profile.

```sh
/path/to/hermes-test-venv/bin/python scripts/evaluate_longitudinal_memory.py \
  --hermes /path/to/pinned-hermes > /tmp/longitudinal-memory.json
/path/to/hermes-test-venv/bin/python -m pytest -q \
  tests/unit/test_longitudinal_memory_acceptance.py \
  tests/unit/test_retained_source_repack_acceptance.py
/path/to/hermes-test-venv/bin/python scripts/check.py \
  --hermes /path/to/pinned-hermes \
  --hermes-python /path/to/hermes-test-venv/bin/python
git diff --check
```

Timing samples bracket native pre-LLM hook collection, including exception/log observation overhead, production admission, fresh read-only connection/schema validation, query/filter, full envelope and final gate. They exclude process/host startup, writes, repack, the oracle and all model latency. OS caches are not flushed. Each stage has 111 measurements across the three fresh processes; nearest-rank p50/p95 were 5.757/19.867 ms, 5.080/6.362 ms and 5.786/7.719 ms respectively. The environment and raw samples are in the report. These are shared-cloud observations, not service-level targets. The executed aggregate passed 4,457 unit tests, Ruff, ty, bilingual documentation checks and 1,440 pinned-host contracts; the 36 focused runner/retained-helper tests also passed. Code and passing tests do not close broader #46 or authorize deployment.
