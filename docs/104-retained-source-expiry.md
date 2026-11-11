# 104. Retained-source expiry and cleanup recovery

English | [简体中文](104-retained-source-expiry-zh.md)

## Purpose and scope

[Issue #149](https://github.com/MosBot-AI/hermes-superagent/issues/149) adds a deterministic acceptance lane for an independently retained source reaching its original retention deadline, followed by explicit reviewed cleanup and local maintenance. Earlier evidence covered an observed source captured already expired ([99](99-packaged-memory-lifecycle.md)), ordinary-record deadline transitions and retained-source migration/repack separately ([102](102-longitudinal-memory-acceptance.md)). This lane composes those mechanisms; it does not introduce automatic deletion or another retrieval heuristic.

The synthetic [fixture](../tests/fixtures/retained_source_expiry.json) contains receipt-backed legacy and observed-source records with a future deadline, plus a permanent recall control. It uses one UTC second before, exactly at and one second after the original deadline. Only the expiry evaluation clock is controlled; the production expiry comparison, storage, query planner, recall filter and cleanup implementation are not replaced. The frozen relevance corpora and their labels remain unchanged. This is a lifecycle test, not a recall-quality score or model-answer evaluation.

## Exercised paths

The [runner](../acceptance/memory/expiry.py) uses isolated temporary profiles and the exact clean Hermes compatibility pin. It reuses the registered production pre-LLM hook and native LOCAL read/recall activation through the [longitudinal runner](../acceptance/memory/runner.py). Each observation uses fresh processes, and restart must not inherit activation. Complete ASCII-JSON envelopes, whole-record budgets, the positive permanent control and expected returned IDs are checked. Swallowed production recall exceptions are failures, not successful empty results.

Receipt-backed seed metadata is converted to the historical schema-12 fixture layout before the ordinary supported writable opener migrates it to schema 13. Observed-source records are then accepted with their separate provenance tag. This fixture construction does not issue a genuine native receipt or authenticate original authorship. Source acceptance and cleanup use production local APIs with trusted synthetic caller metadata; the recall lane uses the real registered hook. No native transcript is imported or deleted by this test.

The expected lifecycle keeps three states distinct:

- Before the deadline, both retained records must appear in fresh recall alongside the permanent control.
- At equality and afterward, their stored status and revision remain active and unchanged, but fresh recall excludes them. Expiry neither forgets payload nor advances source progress.
- After the explicit reviewed `forget-expired` batch, the current records are cleared terminal tombstones. Original accepted receipts remain historical active/revision-1 outcomes; they are not current-state evidence.

The oracle compares fixed fixture expectations, canonical SQL rows and current native results. Full logical database snapshots include schema, canonical tables, derived FTS rows, events, receipts and retained-source decisions. Reads, refused operations and exact historical retries must not change them. The reviewed cleanup preview is deliberately made stale by an unrelated canonical mutation; stale apply must refuse without mutation before a newly reviewed batch is applied. Retry evidence must distinguish replaying that batch from forgetting another eligible record.

## Restart, suppression and maintenance

The resulting state is checked after restart, normal supported repack and one controlled interruption after the old database is preserved but before the staged database is installed. The existing explicit recovery API completes the recorded maintenance intent. This is a bounded composition test, not another exhaustive crash matrix, historical backup restore or native transcript compaction.

Historical accepted and cleanup receipts, current forgotten metadata and completed source cursors must remain consistent. Reusing the source identity is refused, as is changing request, consumer, identity and provenance route while preserving a suppressed fingerprint. Current-input candidate admission must also honor the same suppression. Exact historical acceptance retries cannot restore forgotten text or advance a cursor again. Negative controls deliberately damage evidence or behavior to verify that these checks can fail.

## Reproduce and evidence

Use the prepared Python 3.14 interpreter and exact clean Hermes checkout. The runner creates and removes its own synthetic profiles; do not point it at a real user profile.

```sh
/path/to/hermes-test-venv/bin/python scripts/evaluate_retained_source_expiry.py \
  --hermes /path/to/pinned-hermes > /tmp/retained-source-expiry.json
/path/to/hermes-test-venv/bin/python scripts/check.py \
  --hermes /path/to/pinned-hermes \
  --hermes-python /path/to/hermes-test-venv/bin/python
git diff --check
```

The [machine-readable report](retained-source-expiry-report.json) passed all six stages: before, deadline, after, cleanup, normal repack and interrupted repack. It records twelve fresh native recall observations and three separate terminal-state verification processes. The original two targets are recalled before expiry and excluded at equality; cleanup leaves historical accepted receipts at active/revision 1 and current tombstones at forgotten/revision 2. Source cursors remain at completed sequence 1. A later eligible record stays active through cleanup retries. No production defect or production-code change resulted from this run.

The report identifies code commit `7270601631d95ce2eb05392d6aafed141dfde02a`, fixture SHA256 `19c6ea92425430fdcfbda394f0788ba0e75ed8d3c136d7c9d36687afdc64e7f8`, complete harness/production hashes and Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. It ran with Python 3.14.9 and SQLite 3.53.1. Generated UUIDs, process IDs and observation timings may differ on rerun; they are not normalized away to compare different executions. Exact same-profile restart/repack comparisons retain the complete logical state.

The focused execution passed 65 unit/oracle tests and the new pinned native contract. The pinned contract suite executes this acceptance lane, rather than relying only on a checked-in report. Full aggregate checks, independent final review, exact-head/main CI and downloaded-package evidence are recorded on the issue and PR; the report's local code commit is not a deployment or published release identifier.

The first official-runner aggregate exposed a fixture bug: its temporary path alias resolved differently from the bound profile, so the existing storage guard refused admission. The harness now resolves its synthetic home and uses the host's public profile-override context with restoration. A contract forces an aliased temporary root and an inherited override. A separate existing lost-response test compared fresh status across a UTC-second boundary; only that test's clock is fixed, preserving its complete status assertion. The official runner then passed all 17 tests in the two affected files without retry. No production guard was relaxed.

## Limits

No model, provider credential, external connection, installation, running Gateway, personal data or desktop computer is used. The native transport fixture is not live authentication or delivery acceptance. Production storage remains plaintext; logical forgetting and repack do not promise physical-media erasure, and preserved old files, native history, backups, exports or previously returned context can retain text. Suppression is exact-match protection, not semantic erasure of paraphrases. This evidence does not complete #46, general semantic recall, remote adapter migration, configured-model usefulness or production deployment.
