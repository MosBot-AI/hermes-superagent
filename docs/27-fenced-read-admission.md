# 27. Fenced Read Admission

English | [简体中文](27-fenced-read-admission-zh.md)

## 1. Scope and current availability

This slice implements a default-denied **internal read coordinator** and a real SQLite policy/revocation transaction guard. Offline fixtures supply independent confirmations and resource snapshots to test that coordination. The repository does **not** supply a production identity authority, confirmation issuer, resource reader or enrollment activation flow. It does not authenticate the fixtures as real users.

No production command, tool, HTTP route, manifest setting or plugin callback constructs this service. Even an internal `enabled=True` is insufficient without both trusted adapters. Production status and `/personal-access` remain blocked. Pending records remain pending, the enrollment schema is now v2 with explicit exact-v1 migration, and `tasks.sqlite3` is neither opened nor adopted.

This advances the E1.3/E1.4 read-admission foundation, not the whole E1 or M1 gate. [26](26-pending-enrollment-policy.md) describes the prospective policy store; [23](23-host-command-context-experiment.md) records the still-unresolved host identity path. Python objects and types are not authentication or isolation against malicious code in the same interpreter.

## 2. Internal API

`ReadAdmissionService(store, host_authority=None, resource_source=None, enabled=False)` accepts internal trusted dependencies only. `read(key, request, live_handle=...)` returns an immutable tuple of `TaskSummary` or raises a redacted `ReadAdmissionError`. It never returns an authorization token, cursor, generator or a cached allow decision.

- `key` must contain exactly `owner_id`, `profile_id` and `enrollment_id`. These are selectors, not proof.
- `request` is the exact internal `ReadRequest` type. Only `personal.tasks.read` / `exact_tasks` / `tasks.summary` is supported, for 1–32 unique opaque IDs. `own_inbox`, binding inspection, details and writes are refused.
- `live_handle` is passed unchanged to the trusted authority. The coordinator does not parse JSON, a username, profile path or `approved=True` into authority.
- `enabled` must be exactly `True` to proceed. Missing adapters or any other value fail before touching the store, authority or resource source. There is no user-facing enable option.

`EnrollmentStore.with_current_record(...)` is a trusted-code-only primitive: exact scoped key, expected policy/enrollment revisions and epoch, plus a synchronous callback. It validates current schema/state inside `BEGIN IMMEDIATE`, refuses revoked/stale records, commits, then returns the callback result. It is not accepted by the data-driven `run()` dispatcher and does not itself establish authority. The coordinator restricts its returned data to validated immutable summaries; arbitrary trusted callbacks must not be exposed to external input.

## 3. What a trusted confirmation must mean

`HostAuthority.hold_admission(live_handle)` must consume a separately approved, one-shot confirmation and acquire a **real live invalidation fence**. Failed attempts stay consumed; a retry requires a fresh confirmation rather than reusing an old allow. The only implementation in this slice is explicitly synthetic test code.

Its `ReadConfirmation` binds:

- Exact enrollment ID and enrollment revision.
- Host incarnation, matching the held guard's current incarnation.
- Independently established `VerifiedReadContext` and `ReadGrant`, including owner/profile, transport, receiving account, actor, session, policy revision and epoch.
- The exact request, including resource tuple and ordering. A broader grant cannot be reused for a smaller request in this slice; a new exact confirmation is needed.

The persisted prospective identity must match that independent context. Its proposed scope may contain the requested IDs, but must itself be an `exact_tasks` summary scope of at most 32 IDs. This conservative limit can reject a smaller request under a larger stored proposal. Neither the row nor the request supplies proof that the task IDs belong to the owner.

`AdmissionGuard.validate_and_now()` must revalidate current one-shot/session/route/connection/host constraints and return a trusted builtin UTC time. It runs before storage access, again after SQLite acquisition, after resource acquisition and after reading. The adapter must actually serialize invalidation, not compare a stale snapshot twice or rely on equality that misses ABA transitions. It must not use a caller-supplied clock. The coordinator validates the grant's exact validity interval through the existing pure evaluator.

## 4. Resource ownership and minimal projection

`ResourceSource.open_snapshot(owner_id, profile_id, request)` acquires a stable resource/ownership snapshot. Its entry must independently establish ownership **before any private summary fields are read**. Entry can wait for a lock, but must not fetch private contents. Only the later `read_summaries()` call may return data, after the coordinator rechecks authority inside all fences.

The immutable `TaskSummary` fields are exactly:

| Field | Bound |
|---|---|
| `task_id` | One of the exact requested opaque IDs |
| `title` | 1–240 characters, not blank; no Unicode control/format/surrogate/line/paragraph separators |
| `state` | `captured`, `done` or `cancelled` |
| `due_date` | `None` or a valid canonical `YYYY-MM-DD` date; no timezone inference |

The result must be an exact tuple of exact `TaskSummary` instances, covering every requested ID once. Missing, duplicate, foreign, excessive, mutable or lazy results are rejected. The coordinator returns request order deterministically. Full details, source bodies, attachments, profile paths and secrets are not part of the projection; fetching them and then redacting is not an acceptable adapter implementation.

No resource adapter is shipped. In particular, `TaskStore.run("list", ...)` is not an adapter: it has no verified owner column, returns full task fields and does not establish the required combined ownership/resource snapshot. An explicit adoption/migration design remains necessary before connecting real local tasks.

## 5. Ordering, linearization and failure

Every participant must use the same lock order:

1. Hold the current host authority/invalidation guard and consume the confirmation.
2. Begin the enrollment SQLite transaction and verify exact current versions, non-revoked state, identity and proposed scope.
3. Acquire the owner-scoped resource snapshot without reading private fields.
4. Revalidate authority and trusted time after all waits. This successful check is the **read-admission point** while every fence is held.
5. Materialize only the bounded summary projection. Recheck authority/time and validate the entire result; a failure discards it.
6. Close the resource snapshot, revalidate authority/time, persist a minimal prepared-snapshot audit, commit the SQLite transaction, exit the host guard, then return the detached summary.

The policy lock excludes revocation/policy edits throughout the read and until commit. A revoke committed first denies before resource access. An admitted read can finish before a waiting revoke commits. A revoke may commit after that read's transaction, even before the caller receives the detached result: this is already-admitted data, not a promise to retract it. The same applies to a host invalidation after the guard is released. No transport reply is sent here.

A no-op policy replacement still changes its revision/epoch and invalidates an older confirmation. Trusted time is resampled after actual lock waits; an expired confirmation cannot read merely because it was valid when waiting began. The post-read check is an additional conservative discard rule, not a guarantee of continuous future validity.

Snapshot errors, denied post-read checks, malformed results, commit failures or host-exit failures return no data. An explicit completion check also prevents a broken snapshot context manager from suppressing a denied post-read exception and returning a summary. Interruption releases transaction and context-manager guards. A caller-owned transaction is refused without rolling it back.

No prompt, network request, worker dispatch, transport send or long-running work belongs inside these locks. Resource adapters must not reenter the enrollment store in reverse lock order. Python cannot enforce the correctness of arbitrary adapter code; only independently reviewed adapters may eventually be wired.

## 6. Audit, persistence and recovery limitations

The [durable prepared-read audit](63-prepared-read-audit.md) now records minimal `snapshot_prepared` metadata in the same policy transaction. Audit failure prevents data return. A committed record may remain after host-exit failure or post-commit crash; it is not proof of return or delivery. There is no replay cache, reusable approval, or full denied-attempt log. Capacity is bounded without silent eviction; exact-v1 initialization upgrades to v2. Production authority/resource adapters remain absent.

SQLite coordinates this database's current policy, not host identity, distributed ownership or restore/clone fencing. The source adapter guarantees only its own stable snapshot; after that snapshot closes, resources may change while the detached result remains a valid earlier snapshot. Restored copies of the database cannot prove freshness. Genuine cross-process/host invalidation, authenticated recovery and actual ingress are unimplemented.

## 7. Verification boundaries

Tests combine actual SQLite transactions and independent connections with clearly synthetic host/resource fixtures. They cover disabled/missing adapters, fake selectors/handles, one-shot replay denial, exact confirmation/scope/version checks, receiver/session mismatch, bounded projections, late expiry/invalidation, malformed clock, exception suppression, interruption and commit/exit failure.

Deterministic contention tests exercise summary-first versus revoke/policy-edit ordering, subsequent stale-confirmation denial, and expiry while `BEGIN IMMEDIATE` really waits. They prove the implemented database ordering and coordinator behavior. They do not prove that an actual Hermes/Telegram host supplies authenticated context or genuinely blocks invalidation.

Native contracts import the actual namespaced directory plugin under the pinned Hermes checkout, exercise default/no-adapter refusal and confirm all normal modes retain denial diagnostics without creating storage. They are package/registration boundary tests, not live summary retrieval or end-to-end Bot authorization. Run the repository aggregate checker; historical environment-blocked socket tests are not retried or reclassified.

Additional [worker-policy contracts](13-enforcement-contracts.md#26-frozen-worker-configuration-with-current-durable-read-policy) now run this same coordinator inside a genuine discovered fixture handler after native pre-import worker-policy binding. A separate connection changes durable policy while that process retains frozen config. Model-facing/direct-registry denial, both real SQLite lock orderings, one-shot replay and storage/audit/COMMIT failure recovery are verified with synthetic independent adapters. This adds no production route or authority; actual production-package safe-mode fallback and full managed-worker lifecycle remain separate gates.

This slice passed 754 unit tests and 304 pinned-host contracts (1,058 total), including 100 new unit cases and three new native boundary cases. Ruff, type checks and bilingual documentation checks passed.

## 8. Next production gates

Before a useful owner summary can be exposed, the project still needs a trusted bootstrap/enrollment decision, supported live host/IPC provenance and invalidation fences, real one-shot approval issuance/consumption, owner-scoped resource adoption, full audit/retention operations, restore/clone handling and authorized real-ingress acceptance. The receiving transport Bot and native canonical Primary Bot remain separate concepts.

No API key or user decision is needed to test this internal coordinator. A real activation path will require explicit selection of the trust/bootstrap mechanism and exact account/Bot/profile/data scope, secure credential connection when applicable, and a permitted test environment. Supplying a model key does not solve the identity or environment gates.
