# 26. Pending Enrollment and Policy Persistence

English | [简体中文](26-pending-enrollment-policy-zh.md)

## 1. Delivered scope

This slice implements an **unwired administrative persistence core**, not an owner-enrollment product. It stores prospective actor/receiver mappings and exact proposed read scopes, with transactional versions, terminal revocation and minimal audit records. Its only states are `pending` and `revoked`. It has no activation, challenge, session binding, `VerifiedReadContext` issuer, `ReadGrant` issuer or protected-data reader.

`open_enrollment_store(bound_home, enabled=False)` rejects by default before host imports or filesystem work. The exact boolean `enabled=True` permits internal storage access only. No manifest setting, native CLI, slash command, model tool, HTTP route or callback invokes it. Loading the plugin, using `local_tasks`, or enabling the planning blueprint does not enable this store. Existing `/personal-access` diagnostics still deny access even when prospective records exist.

This advances preparatory E1.1/E1.2/E1.4/E1.5 persistence work. It does not complete E1, Primary Bot binding or M1. See [18](18-owner-entry-and-read-authorization.md) and the remaining [host admission gates](23-host-command-context-experiment.md).

The follow-on [fenced coordinator](27-fenced-read-admission.md) now provides the internal transaction/snapshot ordering seam. Its authority/resource adapters are still unavailable in production, and this pending store still cannot activate or authenticate a record.

## 2. Data and trust boundaries

The store uses a separate `enrollment.sqlite3`, under the native profile's `plugin-data/hermes-personal-agent` directory. It never reads, adopts or modifies `tasks.sqlite3`. Every record is addressed by the full `(owner_id, profile_id, enrollment_id)` tuple. These strings are **prospective administrative labels**, not authenticated identity. A profile directory, OS UID, database row, type annotation or caller-provided boolean cannot prove ownership.

Creation requires immutable `transport_id`, `transport_receiver_id` and `principal_id`. These are intended values awaiting a future trusted enrollment ceremony; no transport observation is verified by this code. Changing them requires a new prospective record. There is no active-binding uniqueness claim, automatic owner discovery or first-sender enrollment.

The initial schema has two tables:

- `enrollments`: exact identity labels, state, `enrollment_revision`, `policy_revision`, record-local `epoch`, and proposed scope.
- `events`: scoped record IDs, operation and resulting versions/epoch. It excludes actor/receiver IDs, scope content, task IDs, arbitrary text, credentials and raw exceptions. These routing labels are still private metadata, not anonymous audit data.

The file is not encrypted or tamper-evident. Record IDs are not secrets or bearer capabilities. The audit is a local transactional history, not an authenticated wall-clock log or an external freshness authority.

## 3. Internal contract

`EnrollmentStore(connection)` requires a dedicated standard SQLite connection. The caller owns the connection and access controls. `initialize()` creates only an empty database or verifies the exact owned schema. `run(operation, payload)` accepts only these operations and exact fields:

| Operation | Required fields | Result |
|---|---|---|
| `create` | Scoped record IDs, immutable intended identity fields, `scope` | New `pending` snapshot with enrollment/policy revisions `1` and epoch `0` |
| `get` | Scoped record IDs | Current administrative snapshot, including revoked state |
| `set_policy` | Scoped record IDs, `expected_revision`, `expected_enrollment_revision`, `scope` | Replace the proposed scope; increment policy revision and epoch |
| `revoke` | Scoped record IDs, both expected revisions | Terminal `revoked`; increment enrollment revision and epoch |

`expected_revision` means the **policy revision**, not the enrollment revision. Both must match. Even a successful no-op scope replacement increments the policy revision and epoch. Identity fields cannot be supplied to an update. Missing/unknown fields, booleans as revisions, unsupported scopes and integer overflow are refused. All IDs use the bounded opaque ASCII syntax of the internal authorization evaluator.

A scope has exactly `operation`, `target`, `resource_ids` and `data_scope`. Supported shapes reuse the pure read evaluator:

- `personal.tasks.read` / `own_inbox` / empty resource tuple / `tasks.summary`.
- `personal.tasks.read` / `exact_tasks` / nonempty unique resource tuple / `tasks.summary`.
- `personal.primary_binding.inspect` / `primary_binding` / empty resource tuple / `primary_binding.metadata`.

These are **proposed scopes**, not grants. An `exact_tasks` proposal does not establish ownership of its task IDs; an `own_inbox` proposal does not adopt local tasks. No conversion to a live grant exists. The future admission service must independently establish all identity, resource-ownership, session and freshness facts.

## 4. Transactions, retries and revocation

Every operation, including `get`, uses `BEGIN IMMEDIATE`, revalidates exact main/temp schema ownership, and commits a consistent result. A mutation and its audit event commit together. An audit insertion failure, interruption or rejected update rolls back the whole transaction. Independent connections serialize competing changes. Sharing one connection concurrently is unsupported; caller-owned transactions are refused without rolling them back.

The commit is the linearization point for **this administrative state change**, not authorization admission. With the secured persistent opener, a successful revoke commits before the method returns, subject to SQLite/filesystem durability guarantees; a caller-supplied in-memory connection is not durable storage. Another policy mutation with old revisions conflicts; using current revisions on a revoked record is also refused. There is no undo, deletion or reactivation API. A replacement proposal uses a new ID and remains pending.

Retries are CAS-only, with no replay receipts. The caller selects a stable enrollment ID before creation. If the outcome is uncertain, use the same owner/profile/ID to read current state and reconcile; do not blindly create a new ID or replay a stale edit. Duplicate creation returns `already_exists`, never the appearance of a new authority. A returned snapshot can become stale immediately after commit and is not reusable authorization.

Epochs are monotonic **within one record in this database history**. They are not a host-instance fence, profile incarnation, restore detector or distributed lease. Copying or restoring a database can copy old revisions. No restart, restore or clone may treat these records as authenticated active authority. Revocation here cancels a proposal only: no live request, issued grant, task read or remote effect exists to cancel.

## 5. Storage safeguards and limits

The internal opener uses the pinned host's public profile resolver and plugin-data helper, validating the bound absolute profile before and after directory resolution. It refuses profile changes, symlinked storage directories, directories writable by other users, unsupported platforms, and unsafe main or SQLite sidecar files. Existing files must be regular, singly linked, owned by the current UID and inaccessible to group/other users. New database files are created with mode `0600`. Existing permissions are never repaired automatically.

The database uses rollback journaling with `foreign_keys=ON`, `trusted_schema=OFF` and `synchronous=FULL`. An existing WAL database is refused rather than converted; this does not bypass Hermes's WAL compatibility gate. Exact application ID, schema version, table SQL and absence of temporary schema objects are checked. Foreign databases, task databases, unexpected tables/triggers or unsupported versions are refused rather than migrated or overwritten.

These checks reduce accidental exposure. They are not an OS sandbox, protection from malicious same-UID code, a race-free directory capability, encryption, secure deletion or a verified backup system. Existing ancestor/profile trust and a local trusted process are assumptions. The opener is currently POSIX-only; macOS/Windows ignore rules do not imply Windows storage support. No network, socket, provider credential or API key is needed for this slice.

## 6. Verification

Unit coverage exercises strict field/scope/type validation, persistence, owner/profile/ID isolation, immutable intended identities, CAS races on independent connections, exhausted counters, terminal revoke, foreign/malformed schema, caller transactions and rollback on audit failure/interruption. Default-gate tests assert no filesystem or host resolution occurs while disabled, and no enrollment/activation CLI exists.

Pinned Hermes contracts load the actual directory plugin and use its actual public profile/storage APIs in temporary synthetic homes. They verify persistence/reopen, separate profiles with equal prospective IDs, rejected stale profile paths, unsafe files/sidecars/directories, unchanged foreign task databases, closed connections and denial diagnostics after metadata is stored. This is native storage integration evidence, **not a real Bot identity or owner enrollment test**.

The slice passed 654 unit tests and 301 pinned-host contracts (955 total), including 81 new unit cases and 37 new host cases. Ruff, type checks and the bilingual documentation checker passed. This does not test crash/power-loss recovery or production enrollment.

Run the repository's aggregate `scripts/check.py` with the compatibility-pinned Hermes checkout and its PM-built interpreter. Tests use no real identities or keys. Historical blocked identity socket tests remain unresolved and are not retried by this slice. No upstream patch is applied.

## 7. Remaining route to an owner summary

Before exposing an enrollment ceremony or any private read:

1. Establish a real, current ingress observation with verified actor, receiving Bot, route, session and monotonic host fences; complete the supported host/IPC contracts in [23](23-host-command-context-experiment.md).
2. Design and approve the trusted bootstrap authority and explicit enrollment/challenge flow. Pending labels in this store alone do not authorize activation.
3. Define active binding, session expiry/replacement, current revocation/fencing and authenticated recovery. Canonical native Primary Bot selection remains separate from a transport receiver ID.
4. Explicitly preview/adopt a selected local task collection or migrate it to owner-scoped storage. No local task currently carries a verified owner by virtue of its profile.
5. Implement atomic host/policy/resource admission for a bounded deterministic `tasks.summary`, and test ordering with revocation. Calling the pure evaluator and then independently reading `TaskStore` is not sufficient.
6. Validate the real entry point in an authorized environment and securely connect the chosen Bot if needed. A deterministic summary need not use a model API key; credentials cannot fix missing identity contracts.

This foundation intentionally stops before those gates. The production status continues to report `identity_binding: false`, `protected_reads_enabled: false` and `release_gate: blocked`.

## Policy history inspection

`EnrollmentStore.policy_history(key, after_epoch=-1, limit=50)` is an internal administrative reader, not a CLI, model tool, remote route or authentication API. Exact owner/profile/enrollment selectors are caller-owned labels. It returns only operation, epoch and resulting enrollment/policy revisions, plus the current record state/revision/epoch watermark. It never returns intended actor/receiver IDs, scope content, resource IDs, credentials or arbitrary event text.

The initial cursor `-1` includes the epoch-zero creation event. Pages accept 1–100 items, return `next_after_epoch` and `has_more`, and remain readable after terminal revocation. A cursor beyond the current epoch is rejected. One transaction provides a coherent page and current watermark; separate calls are not a frozen snapshot and may observe later policy changes or revocation. A returned watermark is historical inspection, not an authorization fence or evidence that an external operation stopped.

The reader validates the exact schema, current record/counter relationship, current tail event and selected contiguous range including one lookahead item. Missing or inconsistent selected events fail closed, including failures during SELECT or COMMIT. It does not scan or certify all earlier history outside that page. Indexed scope/epoch queries fetch at most `limit + 1` page rows and one tail row; the API performs no mutation, retention cleanup or schema migration. The local database remains neither tamper-evident nor a restore/clone freshness authority. A caller transaction is rejected without being rolled back.
