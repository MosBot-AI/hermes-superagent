# Durable internal ActionIntent drafts

English | [简体中文](64-action-intent-drafts-zh.md)

## Scope and authority boundary

This E1.2 precursor implements internal `ActionIntentStore.prepare`, `inspect` and `cancel` on a dedicated, caller-secured SQLite connection. It provides durable request identity and exact metadata binding for future approval integration. It does not approve, authorize, send, execute, enroll a person, infer resource ownership or adapt a host approval. No CLI, model tool, hook, HTTP route or automatic storage opener exposes this store. E1.1 and complete E0.4 coverage remain prerequisites for production controlled effects; #15 remains incomplete.

Owner/profile/request identifiers and the operation name are bounded opaque administrative selectors, not verified identities or permissions. The caller must independently establish the connection, scope, policy/resource versions and trusted clock. Arbitrary in-process Python and direct database modification are outside this precursor's trust boundary. A restored or cloned database is not evidence of current authority. There is no `approved: true`, grant issuance, effect callback, execution state or retry engine.

## Exact binding and minimization

Preparation accepts exact owner/profile/request selectors, operation, policy revision, epoch, resource revision, UTC expiry, and nonempty target/payload **bytes**. The target is limited to 4,096 bytes and the payload to 65,536 bytes. The adapter must define exact serialization before calling; this module does not normalize whitespace, JSON key order, recipient aliases, URLs, currency or Unicode. Semantically equivalent but different bytes conflict on the same request ID.

Raw target and payload are hashed in memory with distinct versioned domains, then omitted from storage and returned metadata. A separate versioned binding digest covers these digests and every proposed selector/version/expiry field, including the request ID. The store retains selectors, operation, versions, digests, timestamps, state and revision. Events retain only the selectors, revision, fixed outcome and timestamp. No credentials, message body, target text or raw error text are intentionally persisted. Callers must not put secrets in selectors or operation names; syntactic validation is not sensitive-data classification.

Hashes are neither encryption nor anonymization: low-entropy values can be guessed offline, and equality can disclose correlation. Temporary input bytes remain subject to the caller's memory/lifecycle behavior. This is not a secret vault. Inspecting a digest does not reconstruct a human-reviewable action and cannot replace showing the exact action through a future trusted approval interface.

## State, time and retries

The only transitions are `draft` revision 1 to `cancelled` or `expired` revision 2. There is no update, renewal, reactivation, denial override or deletion. A new draft expires strictly after the trusted preparation clock sample and at most 24 hours later. UTC must be an exact builtin datetime with the UTC singleton and no fold. The trusted clock is sampled **after** acquiring the database transaction lock, never supplied as a request parameter. A time before creation is refused. Once observed and committed, expiry remains terminal even if the clock later moves backward; this is not protection against a malicious clock or rollback of the whole database.

An exact preparation retry returns the current metadata, including terminal state. Changing any bound field on the same owner/profile/request key conflicts, including after cancellation or expiry. Different namespaces may use the same request ID without claiming shared authority. Retries do not add duplicate audit events. A new request ID is not permission to resubmit any externally uncertain action; this module has never sent one.

`inspect` is **not a pure read**: it may atomically persist expiration. `cancel(..., expected_revision=1)` cancels only an unexpired draft. An exact cancellation retry returns the same cancellation. If expiry won, it returns `expired`, not a false cancellation claim. It cannot stop a host worker, pause a scheduler or retract delivery. Other expected revisions are rejected.

## Transactions, integrity and limits

Every operation uses `BEGIN IMMEDIATE`, verifies exact owned DDL/application/schema versions and rejects temporary shadow objects or unknown schema additions. A new empty dedicated database is initialized explicitly; no existing domain store is migrated or adopted. Intent mutation and metadata event commit together. Event chains, binding digests and persisted metadata are validated before returning a record. Unknown outcomes at COMMIT require inspecting or exactly retrying the same request, not creating another ID.

There are at most **1,000 retained intents per database**, with at most two events per intent. Capacity refuses new drafts without evicting old or cancelled records; exact retries, inspection and cancellation remain available. No supported prune, export, recovery or restore workflow is provided. Expiry is a state cutoff, not a deletion deadline; metadata may remain indefinitely. A crash before COMMIT rolls back both record and event; a crash after COMMIT may leave a durable record even when the caller did not receive a response. These semantics do not prove power-loss durability for arbitrary caller database settings or storage hardware.

Errors contain fixed codes, not action contents, hashes, selectors or SQLite/clock exception text. Audit is draft bookkeeping, not proof of authentication, approval, actual effects, delivery or a complete denied-attempt log.

## Verification and remaining work

Synthetic tests cover exact-byte binding, scoped retry identity, terminal cancellation/expiry, time validation, capacity refusal, corrupted metadata/event chains, strict schema, event/COMMIT failures, concurrent real SQLite preparation and process exit on both sides of COMMIT. Native package tests verify the internal module stays unexposed and cannot activate production permissions. No network, provider, actual account, Gateway or real action was used for this slice.

Remaining gates include verified owner/receiving-channel context, trusted human approval receipts, a reviewed payload/target schema for each action kind, current policy/revocation admission, resource ownership, atomic execution/outbox reconciliation, truthful in-flight cancellation, privacy/retention operations and full alternative-path enforcement. A passing draft ledger does not complete E1 or enable controlled external actions.

## Explicit atomic batch cancellation

`cancel_many(requests)` cancels between 1 and 100 explicitly selected existing drafts in one transaction. Every item contains exactly `owner_id`, `profile_id`, `request_id` and the previously inspected `binding_digest`. All items must have the same owner/profile, unique request IDs and valid exact digests. There is no wildcard, discovery, implicit inclusion of newly prepared drafts, or cross-profile cancellation. Scope labels and possession of a digest still provide no authentication or authorization.

The store validates every selected record, event chain and binding under one write lock before changing any state. A missing, corrupted or mismatched member refuses the entire batch. One trusted clock sample applies to the batch: expired drafts become `expired`, live drafts become `cancelled`, and prior terminal states remain unchanged. Results retain input order and truthfully report mixed terminal outcomes. Exact retries after a lost response or process restart do not append duplicate events. Reordering/subsetting an explicit retry does not authorize any new item. Concurrent overlapping batches serialize; newly prepared unselected drafts are untouched.

All state and audit changes commit together. An error during a later item or COMMIT rolls back earlier changes. A process exit after COMMIT can leave the whole batch committed even when no response was received; callers inspect or exactly retry the same bindings. This is not a durable batch receipt, global policy revocation, approval cancellation or interruption of running external actions. No new storage schema, entry point or production capability is enabled. The 1,000-intent retention limit remains unchanged; cancellation does not free capacity.

Synthetic verification includes invalid selections, mixed scopes, digest changes, expiry, terminal retries, event/commit failures, concurrent overlapping transactions, and abrupt process exit after an intermediate event and before/after COMMIT. The pinned-host package contract checks the same internal-only behavior and unchanged production denial. These checks do not prove hardware power-loss durability or external cancellation.
