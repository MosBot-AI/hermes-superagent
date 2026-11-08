# Durable prepared-read audit

English | [简体中文](63-prepared-read-audit-zh.md)

## Scope

The internal [fenced read coordinator](27-fenced-read-admission.md) now commits a minimal `snapshot_prepared` event before allowing a detached result to leave its SQLite transaction. This fills one E1.4/E1.5 audit gap; it is not production identity, enrollment activation, resource adoption, a transport, or complete M1 acceptance. All normal plugin entry points remain default-denied for this coordinator. Synthetic fixtures are the only current authority/resource adapters.

A record means that the coordinator validated and materialized a bounded snapshot, closed the resource snapshot successfully, and passed its final authority/time check while holding the host and policy fences. It does **not** prove that the caller received the result, that a transport sent it, that a user saw it, or that an adapter really authenticated a person. The internal API remains trusted code, not a security boundary against malicious Python.

## Ordering and failures

`EnrollmentStore.with_audited_read(...)` wraps `with_current_record(...)`. It validates the current policy/revisions under `BEGIN IMMEDIATE`, checks audit capacity before calling the resource operation, validates the returned `PreparedRead`, inserts the audit, then commits. The coordinator takes its final trusted UTC sample from `AdmissionGuard.validate_and_now()` **after** successful resource-snapshot exit, not from request input. A snapshot exit that invalidates the authority or consumes the remaining validity interval prevents the audit and return.

Insertion or COMMIT failure rolls back and returns no data. A crash before COMMIT leaves no committed event. A crash after COMMIT, or an exception leaving the host guard, may leave the event even though no value was returned. This is why the outcome is only `snapshot_prepared`. Denied or failed attempts are not recorded by this slice; it is not a complete access-attempt log. Administrative revoke/policy events remain separate and unchanged.

The existing lock order remains host guard → policy transaction → resource snapshot. Revoke committed first prevents the read; an already admitted read can commit its event before a waiting revoke. A later revoke does not erase history or retract a detached result. The event is not a reusable approval, a replay permit, or an authorization token. Retrying requires a fresh one-shot confirmation and produces a separate event if successful; the old result is not cached.

## Stored metadata and bounded inspection

The new `read_admissions` table retains only a store-local sequence, owner/profile/enrollment selectors, enrollment/policy revisions, epoch, trusted UTC preparation time, resource count (1–32), and the fixed outcome. It stores no task IDs, title/details, result hashes, transport receiver, principal, session, host incarnation, grant ID, credential or raw error. Selectors are ordinary plaintext administrative metadata, not proof of ownership or encrypted secrets.

The internal `read_admission_history(key, after_sequence=0, limit=50)` method returns exact-scope metadata pages in sequence order, at most 100 rows per call, plus `has_more` and `next_after_sequence`. Pages are fresh queries, not one multi-page frozen snapshot. Malformed persisted metadata is refused. It can inspect a revoked record's history but cannot reactivate it. There is no command, model tool, HTTP route or JSON `run()` operation exposing this method; external callers cannot pass an audit row as authority.

There is a hard limit of **10,000 events per database**. Capacity or sequence exhaustion refuses a new read before acquiring/reading the resource snapshot. No silent eviction, timestamp rewriting or automatic cleanup is performed. The one-shot host confirmation may already have been consumed by then. Administrative policy/revoke operations remain available. This precursor has no supported pruning, export, restore or capacity-recovery workflow; do not delete or replace authority storage to bypass the limit. Retention/operations handling is a remaining production gate, and offline copies may keep this metadata indefinitely.

## Schema compatibility

Explicit internal store initialization atomically upgrades **only the exact owned v1 schema** to v2 by adding the audit table. Existing enrollment rows, administrative events, revisions and terminal revoked state are preserved without reinterpreting them as active authority. No historical read events are fabricated. Fresh v2 and upgraded v2 have identical checked DDL. Unknown versions, extra objects, changed DDL and temporary shadow objects are refused. Failure during table creation, version change or COMMIT leaves v1 intact and the store uninitialized.

The plugin does not initialize this store on normal load/status. Calling the already explicit internal opener now performs the v2 upgrade. Old code that only understands v1 will refuse v2; there is no automatic downgrade. Schema checks occur before each operation, and snapshot data from another database is not adopted.

## Verification

Offline tests cover frozen v1 migration and rollback, metadata minimization, paging/scope isolation, revoked-history inspection, final clock samples, malformed callbacks/records, audit insertion and commit failures, capacity/sequence refusal, host-exit failure, and actual process exit before/after COMMIT. Existing real SQLite contention tests verify a committed audit remains at the admitted revisions before a waiting policy mutation. These are process-crash tests, not proof of power-loss durability or malicious same-UID resistance.

Pinned-host contracts check package status stays blocked, explicit private-profile persistence, and that a persisted audit cannot activate a missing authority adapter. They do not run a real owner/Bot read, a provider request, Gateway listener or external transmission. Production identity, trusted adapters, resource ownership/adoption, restore/clone fencing, full denied-attempt auditing and genuine ingress acceptance remain open.
