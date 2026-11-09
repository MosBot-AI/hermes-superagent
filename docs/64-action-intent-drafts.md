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

## Bounded pending review snapshots

`review_pending(scope, limit=100)` recovers pending draft metadata after restart without needing to remember every request ID. Scope must contain exactly `owner_id` and `profile_id`; the output limit is 1–100. These identifiers do not establish identity, resource access or approval. This internal method has no CLI, model or network entry point and does not reconstruct action content from hashes.

Under one write transaction and one trusted clock sample, it validates all records and event chains in the selected namespace, reconciles elapsed expiry, and returns `observed_at`, `pending_count`, `truncated` and bounded `items`. Pending items are ordered by expiry instant, then request ID. Cancelled and expired records are omitted. Expiry beyond the displayed limit is also persisted, while other namespaces are untouched. Validation, audit or commit failure returns no partial result and rolls back expiry changes. The existing 1,000-record retention cap bounds review work; review does not prune records or free capacity.

This is a coherent observation, not a reservation or approval. A later cancellation or clock advance can make its contents stale immediately. Re-review or use the exact existing binding for any later internal operation; production execution still requires its separate current authority and payload checks. A truncated result is not a full inbox and this method supplies no pagination cursor. Like `inspect`, it is not a pure read because it can commit expiration events. No automatic scheduler, expiration sweep or external cancellation is installed.

## Atomic draft replacement

`replace(selected, specification)` replaces one exact live draft with a newly identified draft in the same owner/profile namespace. `selected` contains exactly the three request selectors and its previously observed `binding_digest`; the replacement uses the complete `prepare` specification with a different request ID. Changed content is never written into an existing request. Scope labels and digest possession are still not authentication or permission.

Under one transaction and clock sample the store validates the old binding, requires an unexpired draft, refuses an independently existing replacement, checks the normal lifetime/capacity limits, cancels the old draft, prepares the new metadata, and writes a minimal durable replacement link. Any validation, event, link or commit failure rolls back all changes. An already cancelled/expired old draft cannot be newly replaced; a draft whose time has elapsed is refused without an expiry mutation (normal inspect/review can reconcile it). Cancellation does not free capacity.

An exact retry validates the durable link and both records, then returns `previous` and `replacement` metadata in their current terminal-aware states. It may commit expiry of the new draft. A different replacement ID or changed bound field conflicts. A replacement subsequently cancelled, expired or itself replaced is not revived. Independently preparing a new record and cancelling the old record is not adopted as a completed replacement. This is not an approval transfer, execution retry, withdrawal of a sent operation or freshness guarantee after whole-database rollback.

Schema version 2 adds the metadata-only replacement link table. Explicit initialization upgrades only the exact owned version-1 schema in the same transaction; unknown schema additions are refused and failed commits leave v1 intact. Raw payload/target bytes remain absent, existing intent/event records stay unchanged, and the 1,000 retained-intent cap also bounds replacement links. There is no automatic production opener or downgrade support; older code refuses the v2 schema.

Synthetic tests cover exact replay across reopen, changed bindings, no adoption/resurrection, chain replacement, expiry/capacity, concurrency, migration rollback, and abrupt exits during writes and around COMMIT. These are local bookkeeping tests, not real approval or effect acceptance.

### Review time watermark

`review_pending` also returns `latest_event_at` (the latest persisted event for
validated intents in the selected scope, or null for an empty scope) and
`clock_behind_events`. The watermark includes terminal records and newly
reconciled expirations even outside the output limit. Other scopes do not affect
it. `observed_at` remains the sampled trusted wall clock; if it is earlier than
that watermark, the flag is true. Terminal retries remain stable during clock
correction and never revive records. All fields share the review transaction.
This is not a global monotonic clock, a freshness token, clone/rollback detection
or execution authority. No schema migration is required.
