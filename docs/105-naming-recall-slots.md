# 105. Literal Naming Slots in Automatic Recall

English | [简体中文](105-naming-recall-slots-zh.md)

[Issue #151](https://github.com/MosBot-AI/hermes-superagent/issues/151) extends the bounded [literal-slot recognizer](103-automatic-recall-slots.md) for opt-in [session recall](49-session-memory-recall.md) and the optional [native provider](41-native-memory-recall.md). This is a local development candidate, not deployment, model acceptance or completion of #43/#45/#46.

## Scope and behavior

A whole single-clause Chinese question with exactly one possessive marker can use the naming endings “what is called” or “what is the name”, optionally followed by the existing question particles and sentence-final punctuation (see the linked Chinese version for the literal syntax). Existing request prefixes remain supported. Both literal subject and attribute must be present. Names and attributes stay unchanged, including internal function-word characters; mixed scripts use existing word boundaries. The exact Chinese first-person self-reference is omitted after validating both slots. Terms are deduplicated in input order.

A literal internal naming verb, multiple possessives, coordination markers, multiple clauses and unsupported endings keep their previous interpretation. This narrow grammar does not remove filler words, resolve aliases, add synonyms, infer relationships or understand negation. A negative record matching every required term remains evidence. Legacy fallback can still return unrelated records. Empty results do not establish that a fact is absent.

Marker-only slots such as `___`, `---` or separated `- _` fail closed, including after self-reference; they cannot collapse into a broader one-slot lookup. Existing limits remain 2,048 input characters, eight distinct terms and 128 characters per term. Recognized over-limit plans fail closed without dropping late terms. Slash commands and malformed control-character inputs remain refused.

Recognized multi-term plans require every term in the same returned record's content or topic. Filtering follows one fresh bounded read without refill, retaining target and negative facts while excluding records missing the requested subject or attribute. Removed items increase `omitted_records`; `matched_records` still describes the original snapshot. `automatic_filter` retains all required indices and `refilled: false`. The session envelope remains at most six whole records and 6,000 ASCII-escaped JSON characters. Explicit search/recall, storage schema, activation, revocation, expiry, provider selection and deployment boundaries are unchanged. Correction and forgetting affect new reads, not previously supplied history.

## Recovery and evaluation discipline

The recovered production file is byte-identical to the reviewed implementation supplied for recovery: SHA256 `90b84265532729beb30294c3fc523e3de8f992d6031ae7f521bfddef45864d53`. Tests and this bilingual documentation were reconstructed; they are not claimed to restore missing original test/document bytes or an unavailable full commit.

The immutable naming confirmation fixture contains 32 records, 56 questions and 12 negative questions, SHA256 `ce9e1883d227581f455f8dfa8dbd2794706845a6f6ec656f0c815df4a103c274`, published in fixture-only commit `b8f3aef8103b9f323feaae3e589f20252817bf0d`. It was independently frozen before the original implementation and has previously been evaluated. It is immutable confirmation evidence, not a newly untouched holdout. Production reconstruction does not inspect its query contents or labels and does not tune production to its results. Independent evaluation subsequently runs the unchanged fixture to measure the frozen candidate. The previous `c25` case and known naming failures are development evidence only. Existing fixtures and historical reports remain unchanged.

## Validation boundaries

Reconstructed development tests cover request prefixes and endings, literal/mixed-script slots, self-reference, deduplication, exact prior fallback terms, limits, malformed and marker-only input, real backend all-term filtering, negative evidence, omission metadata and unchanged explicit retrieval. Lifecycle tests cover one-read freshness, missing-subject abstention and forgetting. Native contract tests use the actual entrypoint-loaded provider and registered hook for correction, revocation, forgetting, expiry, shutdown, unchanged database state and context budgets.

Run repository checks with Python 3.14 and native contracts against the unchanged `compatibility.json` pin `2281116525106e3c109993ccb5dc74d02bfc1427`, following the [development instructions](../README.md#development-checks). Fresh command results and independent comparative evaluation must be recorded separately before acceptance; historical passing counts are not recovery validation. No live model/API call, production install, provider switch, compatibility change or upstream submission is part of this slice. Synthetic retrieval evidence does not establish general answer quality or production acceptance.

## Fresh independent results

The [fresh comparison report](naming-recall-slots-report.json) records full per-query evidence, source and fixture hashes, commands and five timing repeats per short fixture. It compares main `6617f174e7a12a9b509bc88ca84e13d396a5ad64` with the fixed recovered production source above, using Python 3.14.9 and the clean native pin `2281116525106e3c109993ccb5dc74d02bfc1427`. Fixture bytes and labels remain unchanged. The report SHA256 is `2c06482ad7dac04f6d40e6847da85ad8dd7c79bff9e2c5de1c1b644aafd97b0b`.

Returned-item precision counts relevant returned records divided by all returned records; micro recall divides relevant returns by labeled relevant query-record pairs. All comparisons were freshly rerun:

| Corpus | Base precision → recovered | Base recall → recovered |
| --- | --- | --- |
| Historical | 26/26 → 26/26 | 26/37 → 26/37 |
| Development-validation | 27/42 → 27/42 | 27/42 → 27/42 |
| Previous confirmation | 29/44 → 30/45 | 29/45 → 30/45 |
| Previously evaluated frozen naming confirmation | 39/50 → 40/51 | 39/49 → 40/49 |

The previous confirmation improves the known development case `c25`. Naming confirmation has no lost relevant pair, but has regressions: per-query precision falls from 100% to 50% for `q01` and `q02`; `q23` exchanges one irrelevant ID with unchanged precision. Across that fixture there are three irrelevant additions and three removals. Negative-query false recalls remain 3/12. These results are not universal non-regression, a fresh untouched holdout, or evidence of general semantic answer quality.

Native longitudinal checks at 28, 250 and 1,000 records retain identical per-query outcomes; hard invariants and retained-source checks pass. Independent review additionally reports 225 focused unit tests, 48 native tests, 541 adversarial probes and 1,000 bounded long-input checks passing. Full aggregate validation is tracked separately; these focused counts do not claim that it has completed. No production code was changed in response to this evaluation.

For reproduction, use the exact baseline, fixed source hash and interpreter/native pin above. The linked report records the commands and complete fixture/source provenance; follow those commands together with the repository development-environment instructions. Keep the confirmation labels immutable and report per-query losses and irrelevant additions alongside aggregate metrics.
