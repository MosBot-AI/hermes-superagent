# 80. Exact Memory Source Suppression

English | [简体中文](80-exact-memory-source-suppression-zh.md)

## Local operator workflow

With the existing explicit local memory prerequisites, inspect a pending candidate and suppress its exact original input:

```text
/personal-memory candidate-show CANDIDATE_ID
/personal-memory candidate-suppress-source CANDIDATE_ID --expected-revision 1
```

This operator-only command derives the fingerprint from the stored pending candidate, not a supplied digest or model claim. It atomically records suppression and discards **all pending candidates with the same full-input SHA256** in the current profile namespace, clearing their content, quote, source digest and session fields. The selected candidate returns its terminal metadata receipt; exact retries return the same historical receipt, not a new deletion count. Stale revisions, expired or previously terminal candidates cannot establish a new suppression. There is no unsuppress command or silent eviction. Model tools cannot suppress, accept or remove these markers. Disabled, remote and unbound entry points retain their existing refusal gates.

Future new proposals and pending acceptances check suppression in the same SQLite writer transaction as their effects. A new native turn, nonce, request ID or session cannot bypass an identical input fingerprint. Identical old proposal requests can still replay their historical metadata; accepted candidate retries can return historical accepted metadata even after the linked record was corrected or forgotten. Neither retry creates a new candidate/record or establishes its current status. Changed replay arguments still conflict.

## Correction and forgetting

For candidates accepted after schema 11, a minimal candidate-to-record association retains the original input digest. `correct`, `forget`, edit-draft correction and reviewed `forget-expired` use the same canonical mutation path: suppression and pending-candidate cleanup commit or roll back with the canonical mutation, event and receipt. Expiry alone does not suppress a source. Ordinary explicit `remember` remains available as an intentional new record, without manufactured source lineage.

Suppression does **not** delete already accepted sibling records from the same input. If acceptance commits before suppression, that sibling remains and requires its own correction/forget action; if suppression commits first, a pending sibling cannot subsequently be accepted. Existing source-free explicit records and legacy accepted records cannot acquire guessed provenance. A correction suppresses the old input, not the newly supplied corrected text.

## Exact-match and privacy limits

This is whole-input matching, not semantic forgetting, source authorship or a durable native transcript identity. `source_turn` contains a nonce and is not used as the durable suppression key. Changing or appending text, changing Unicode normalization, paraphrasing or submitting the fact in a different input does not match. Conversely, suppressing one candidate blocks other proposed facts from the identical full input, including unrelated ones. Review this scope before acting.

SHA256 fingerprints are linkable and low-entropy input can be guessed by dictionary attacks; they are **not anonymization or encryption**. New lineage and suppression retain minimal identifiers and digests, not original input or quotes. Existing event/retry metadata remains. This does not erase native history, prior results, provider context, physical media or historical plaintext snapshots. A snapshot can still contain data later forgotten or suppressed; no restore/import path is enabled.

## Storage and migration

Schema 11 adds `memory_source_lineage` and `memory_source_suppressions` in the same owned SQLite database. Authorized writable opening upgrades known schemas 1–10 transactionally; unknown/foreign schemas remain refused. Previously accepted candidates have already lost their digest, so migration does **not** backfill lineage. Pending candidates remain eligible for the explicit command; subsequent acceptances establish lineage. Read-only recall does not migrate and requires current schema. Historical snapshot inspection explicitly retains exact schema-10/11 support without changing snapshot bytes or relaxing namespace/journal/schema checks.

Each lineage row is anchored to one retained candidate and one record; each suppression has a unique candidate anchor and unique digest. The existing never-evicted 1,000-candidate limit bounds each new table to 1,000 rows. There is no separate suppression quota that can newly refuse forgetting: every eligible new marker already has a candidate slot. Terminal markers are not silently evicted. `exact_source_suppression` is an explicit adapter capability; other adapters do not silently receive the new operation.

## Verification and remaining scope

Synthetic tests cover native operator commands and same-text new turns, model refusal, changed input, cross-session/new-nonce proposals, CAS/replay, exact schema migration with no invented lineage, legacy snapshot byte preservation, capacity-preserving forgetting, reviewed expiry cleanup, malformed metadata, rollback, two writer connections with bounded event barriers, and separate-process crashes before/after COMMIT. No model, network provider, credentials or real private data are used. These bounded contracts do not complete all #44 import/migration/live acceptance or #14 remote identity requirements, and do not enable any controlled-write release gate.
