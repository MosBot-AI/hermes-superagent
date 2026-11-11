# 103. Literal Slots in Automatic Recall

English | [简体中文](103-automatic-recall-slots-zh.md)

[Issue #147](https://github.com/MosBot-AI/hermes-superagent/issues/147) is a bounded production-code improvement to the opt-in [session recall](49-session-memory-recall.md) and optional [native provider](41-native-memory-recall.md). It does not activate either path, deploy a package, call a model, or complete #43/#45/#46.

## Behavior and boundaries

Before the historical Chinese character-boundary planner, a small recognizer checks whole single-clause questions with literal grammatical slots: a subject followed by a Chinese “who” marker and a predicate, a subject followed by a preference/want marker and a choice question, or an attribute question with a possessive marker or explicit current-time suffix. Optional leading request phrases, sentence-final punctuation and question particles are recognized only in their grammatical positions. This is not Chinese parsing in general. Every query term remains an unchanged, case-sensitive substring of the current original input.

Within recognized slots, Han names and attributes remain whole; Latin words and adjacent scripts retain bounded word boundaries. A self-reference consisting exactly of the Chinese first-person pronoun is omitted. For a recognized multi-term question, every term must match the same returned record's content or topic. Two words of a project name therefore cannot replace its missing requested attribute. This is literal co-occurrence, not entity identity, relation extraction or proof that the record answers the question. Negative statements are retained as evidence, not converted into affirmative facts.

Spaces alone do not establish grammatical roles. Coordinating/ambiguity markers the Chinese equivalents of “and”, “with”, “or”, the enumeration comma, “respectively” and “each” prevent the new interpretation. The check is deliberately conservative: an embedded name containing a marker may also fall back. Unsupported syntax and multiple clauses retain the previous planner and two-match heuristic unchanged. Fallback can still return unrelated facts, but this change adds no broader fallback or second query. Synonyms, traditional/simplified conversion, word-order identity and unrestricted Chinese segmentation remain unsupported. A record using a synonymous attribute may be missed.

The input limit is still 2,048 characters, with eight distinct terms of at most 128 characters. A recognized plan exceeding those term limits fails closed rather than dropping a late subject or attribute. The new filter runs after the existing single fresh read and bounded pack, without refill. Earlier ranking or budget omissions may hide a relevant record; an empty result does not prove absence. The session path still emits at most six whole records and 6,000 ASCII-escaped JSON characters. All activation, profile/session, read-only, revocation and model-disclosure gates remain unchanged. Explicit `search`, `search_terms`, `recall` and model-tool operations keep their existing literal semantics.

For multi-term recognized plans, `automatic_filter.required_query_indices` lists every required query index, `minimum_matched_terms` is its length, `filtered_returned_records` counts removals and `refilled` remains false. Legacy plans retain their existing metadata. Removed records increase `omitted_records`; `matched_records` still counts the backend's original literal-match snapshot. No canonical schema or public REST contract changes.

## Evaluation discipline

The historical [document-69 fixture](../tests/fixtures/chinese_recall_eval.json), [document-102 fixture](../tests/fixtures/longitudinal_memory_recall.json) and their checked-in reports are unchanged. An independent author froze [the first new fixture](../tests/fixtures/automatic_recall_holdout.json), 38 records and 60 questions, at local commit `cf335d1388ded1bfc1bad21c82b1dd23ddaeb9db`, SHA256 `00fd6c549e9846593b2b411b8aec096214b637f3de0901498297b1b64cf779ed`, before implementation.

The first candidate improved this fixture's returned-item precision from 52.00% to 67.57%, but reduced recall from 61.90% to 59.52%. It lost relevant results in two questions: an insufficiently structured multiword question and a coordinated attribute question. These observations informed the generic recognition narrowing above. The first fixture is therefore a development-validation set, **not an untouched final holdout**. No relevance label was changed. Independent code review separately found and fixed question-particle absorption and internal sentence punctuation handling.

The second [independent confirmation fixture](../tests/fixtures/automatic_recall_confirmation.json) contains 36 records and 60 questions. It was frozen at local commit `2a87bcef922983edbbdb1d1eaa7352ceda46752a` before the narrowing, SHA256 `eedd821fde419954fc08d63f651273d590f3e0b2288124708eac1a3993da5c15`. Its results did not inform any further production changes. Final measurements, exact source/fixture hashes and per-query changes are recorded in the [machine-readable comparison report](automatic-recall-slots-report.json). These are synthetic retrieval measurements, not population accuracy, model answer quality, production latency or live-user acceptance.

## Final observed results

Base production is `e85d207`; final locally evaluated code is `93b4cf7`, with identical production tree content published in the PR. The report records source hashes, rather than assuming a local commit ID is a published release. Returned-item precision divides relevant returned records by all returned records; micro recall divides them by labeled relevant query-record pairs.

| Frozen corpus | Base precision → candidate | Base recall → candidate |
| --- | --- | --- |
| Historical 48 questions | 24/24 (100%) → 26/26 (100%) | 24/37 (64.86%) → 26/37 (70.27%) |
| First development-validation 60 questions | 26/50 (52.00%) → 27/42 (64.29%) | 26/42 (61.90%) → 27/42 (64.29%) |
| Untouched confirmation 60 questions | 29/59 (49.15%) → 29/44 (65.91%) | 29/45 (64.44%) → 29/45 (64.44%) |
| Native longitudinal, 28 records | 16/16 (100%) → 18/18 (100%) | 16/32 (50.00%) → 18/32 (56.25%) |
| Native longitudinal, 250/1,000 records | 13/14 (92.86%) → 15/15 (100%) | 13/28 (46.43%) → 15/28 (53.57%) |

There are no lost relevant pairs on the historical, final development-validation or longitudinal corpus. The untouched confirmation has one per-query regression (`c25`) balanced by one gain (`c09`), not universal non-regression: a possessive question asking what the responsible person's name is retains a literal interrogative residue in its attribute and consequently abstains. The old plan returned both a relevant owner and an unrelated budget. The new gain is a short-name question with an explicit “who is responsible” structure. The final candidate adds no irrelevant ID on any tested query, but inherited fallback still returns unrelated data. Confirmation queries with irrelevant results fall from 14 to seven; negative-query false recalls fall from three to one. These results support a bounded precision improvement, not solved semantic recall.

All final native longitudinal hard invariants pass: complete envelopes, correction/forget/expiry exclusion, current-state equality, fresh restart, normal/interrupted repack and retained-source migration/recovery. The original reports remain immutable historical evidence. Earlier candidate summaries preserve their regressions and exact hashes in the new report; duplicated base native contexts are referenced by the original report's verified hash.

## Reproduction

Use the prepared Python 3.14 interpreter and exact clean Hermes pin `2281116525106e3c109993ccb5dc74d02bfc1427`. Run `scripts/evaluate_memory_recall.py --fixture PATH --repeats 5` on both base main and the candidate for each short fixture, and `scripts/evaluate_longitudinal_memory.py --hermes PATH` for the full native longitudinal scenario. Save results under the names consumed by `scripts/compare_automatic_recall.py --results-dir PATH --additional-fixture automatic_recall_confirmation`.

The short evaluator calls current automatic behavior `candidate_conservative` in both revisions; its older `baseline_1740a85` strategy is not the comparison base. The comparison utility checks fixture hashes and identical query labels, reports lost relevant pairs and newly irrelevant results, and retains complete native longitudinal evidence. Unit counterexamples validate the comparison and required-slot metadata. The full native runner independently verifies current correction/forget/expiry, one-read state, complete envelopes, fresh-process equality, normal/interrupted same-profile repack and retained-source suppression. These remain bounded synthetic checks, not historical restore, physical erasure or native long-chat compression certification.
