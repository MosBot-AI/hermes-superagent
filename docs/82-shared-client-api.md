# Shared Client API Alignment

English | [简体中文](82-shared-client-api-zh.md)

## Goal and current evidence

The owner's 2026-11-10 direction is one REST contract for phone and desktop clients, with Hermes or DSH as a selectable backend. Clients select a backend base URL, not a different business protocol. Native runtimes remain authoritative; this work must not create a parallel agent loop, authentication issuer or authorization shortcut.

This first slice implements **versioned schemas, shared positive/negative fixtures and fail-closed Hermes metadata**, exposed inside existing local status diagnostics as `client_api`. It does **not** register an HTTP router, expose personal data, enable native-mobile sign-in, or make the two backends feature-complete. DSH implements discovery and task paging through its existing authenticated mobile boundary. DSH issue #23 tracks its implementation and acceptance. Its legacy snapshot, SSE and approval routes retain their existing contracts.

## Authority and versions

`contracts/personal-api/` in this repository is the single authority. `schema.json` uses JSON Schema 2020-12; `openapi.json` uses OpenAPI 3.1; `fixtures.json` is executable shared evidence; `manifest.json` records their SHA-256 digests and contract version `0.1.0`. JSON wire envelopes use `personal.api.v1`. These machine-readable artifacts need no translated duplicates.

DSH vendors the exact bytes and records an immutable source commit separately. Consumers verify every digest before tests and must not independently edit a copied contract. A change updates canonical artifacts, fixtures and manifest together, then explicitly upgrades consumers. During `0.x`, incompatible changes require a minor-version increment; compatible fixes require a patch increment. The eventual stable major version and release are not declared by this slice. The repository host does not make the protocol Hermes-specific.

## Client behavior and boundaries

- Resolve relative `/capabilities` and `/tasks` against the configured `/v1` mount. Backend metadata is diagnostic, never a client authorization or branching switch.
- Discovery distinguishes `supported`, `enabled` and `available`. Available implies supported and enabled; unavailable entries have a reason and may offer typed remediation. These describe **shared endpoints**, not native CLI features or similarly named legacy APIs.
- Capability identifiers are stable business operations. The initial registry includes task listing, approvals, changes, native conversation continuation and memory. Unknown future capabilities must not become permission to execute.
- Hermes reports all shared business operations unavailable. Its local operator permissions cannot be promoted into a trusted HTTP owner/profile. No raw forwarded header, client-supplied owner, private bootstrap credential or hosted authentication boolean satisfies that gap.
- OpenAPI declares the existing `__Host-dshpa-mobile` cookie as the first implemented HTTP authentication binding, not a shared token issuer or a Hermes cookie promise. The browser manages it; native-app bearer login is not supported by this slice.
- Authentication remains at the supported native boundary. A future authentication-discovery/handoff descriptor must preserve provider callbacks, revocation and credential lifetimes; an API facade cannot manufacture compatible phone sign-in.
- JSON polling is the baseline design. SSE may accelerate updates, but correctness must not require it. Discovery transport flags describe the implemented shared surface, not legacy transport availability.
- Proposed task pages are bounded to 64 and explicitly `consistency: live`, not immutable snapshots. No adapter may advertise `tasks.list` before authorized pagination and reset behavior are implemented and tested. Existing DSH's 64-item snapshot is not a complete list.
- IDs, revisions and cursors are opaque client values. They never establish authorization. A native cancelling operation cannot map to completed cancellation; reconciliation uncertainty remains `unknown`. Platform-specific reasons may explain an unavailable operation but cannot grant extra capabilities.
- Typed errors distinguish authentication, invalid cursor/input, forbidden access, unavailable capability and temporary internal failure. `retryable` never authorizes duplicating an effect. Future writes need their own idempotency, concurrency, receipt and unknown-outcome contracts before enablement.

## Gap matrix and sequence

| Area | Hermes observed | DSH observed | Required shared work |
|---|---|---|---|
| REST admission | Proposed domain API; no registered domain router | Cookie pairing and origin-checked mobile listener | Verified backend adapters; no parallel issuer |
| Task reads | Local CLI, model tools and an internal live page reader | Authenticated shared pages with scoped cursors plus the separate legacy snapshot | Trusted Hermes HTTP admission and scoped endpoint acceptance |
| Approval decisions | Domain HTTP gate not implemented | Existing exact device-bound response | Same immutable intent semantics and duplicate/race fixtures |
| Recovery | Proposed durable JSON change feed | Existing bounded SSE task replay | Pollable shared changes, reset/ACL/revocation tests |
| Conversation | Native runtime continuation only | Native DSH coordination | Adapter receipts; never spawn a second agent loop |
| Memory | Local opt-in native memory | Native personal-memory implementation | Authorized shared read/write contracts, not automatic exposure |

1. Establish this canonical contract and digest-checked consumer discovery. Keep this as partial evidence under Hermes #29 and DSH #23.
2. Add scoped task pagination/projection and shared read conformance on both adapters. Hermes must first prove trusted HTTP principal propagation for its host mode; independent read-projection work can continue without enabling HTTP.
3. Extend shared approval, operation receipt and JSON change/recovery contracts. Reuse existing authority and durable ledgers; implement one bounded vertical slice at a time under Hermes #30/#31 and DSH #23.
4. Add conversation, memory, artifacts and native-app authentication only with their explicit gates. Physical-phone, deployed-HTTPS and multi-device failure acceptance remain separate and visible.

## Verification limits

Unit tests validate both backends' shared fixture shapes, negative fixtures, artifact digests and fail-closed Hermes diagnostics even when local task tools are enabled. They establish neither a deployed HTTP endpoint nor production authentication, native-mobile callbacks or full functional parity. Existing client API design remains useful for future operation semantics; this shared wire baseline takes precedence only for the explicitly defined common discovery/error/task-page shapes.

## Local task projection foundation

`personal_agent.client_tasks.project_local_task` now provides a pure, unwired mapping from an already-admitted **current** `TaskStore` record into the canonical `Task` shape. It does not open a store, admit a caller, register a route, generate cursors or enable `tasks.list`. Successful projection is not proof of freshness, owner/profile scope or permission to disclose a title. Future adapters must obtain a fresh authorized read and preserve its revocation/consistency boundary through response publication. Legacy saved receipts lacking current fields are rejected; read the current task instead of filling defaults or presenting an old receipt as current state.

| Local lifecycle | Local progress | Shared state | Shared wait reason |
|---|---|---|---|
| `captured` | `ready` | `queued` | `null` |
| `captured` | `in_progress` | `running` | `null` |
| `captured` | `waiting` | `waiting` | `local_waiting` |
| `captured` | `blocked` | `waiting` | `local_blocked` |
| `done` | Any valid historical progress | `completed` | `null` |
| `cancelled` | Any valid historical progress | `cancelled` | `null` |

These states represent the **local task record**, not execution telemetry: `queued` does not mean dispatched, `running` does not prove a live worker, and local completion/cancellation does not establish external completion/cancellation. Native observations, notes, source text and client-provided authority cannot override lifecycle. An unsupported lifecycle/progress value is rejected, never guessed as success or cancellation. Terminal lifecycle wins over retained historical waiting/blocker labels.

Only `id`, `title`, decimal-string `revision`, `state` and fixed `wait_reason` are returned in a fresh mapping. Private details, progress/resolution notes, timestamps, project/source and native observations are not copied. Input must be a plain dictionary with a canonical UUID-v4 ID, a nonblank native title of at most 240 characters with the existing native prohibited control categories excluded, an exact integer revision in `1..2**63-1`, and recognized lifecycle/progress strings. Booleans, scalar/container subclasses, missing fields and malformed/oversized values fail with a fixed redacted error; values are not truncated or coerced. The wire schema remains version 0.1.0 with unchanged artifacts.

Tests exercise current records produced by the actual local store, all 12 lifecycle/progress combinations, terminal precedence, canonical schema conformance, invalid inputs, strict bounds and field minimization.

## Internal live task pagination

`SharedTaskPager(store).page(limit=32, cursor=None)` returns a `personal.api.v1` `TasksPage` from the supplied, initialized `TaskStore`. Trusted code selects the store and authorizes each read of its entire task collection before calling the pager. A future transport adapter must hold the appropriate ownership and revocation fences through response publication. Create a pager per authorized caller and store lifetime and discard it when that binding changes. The page parameters carry only the requested limit and continuation.

The page uses the same live keyset semantics as DSH. Each call reads at most `limit + 1` rows in immutable task ID order using a single SQLite statement. Only the five fields required by the task projection are selected. A later page reads current task states and revisions. A new task behind the anchor is visible on a fresh traversal. The local limit is 1–64 with a default of 32.

Continuations use an instance-local signing key. A changed token or one from another pager yields `cursor_invalid`. Start a new traversal without a cursor after a scope change or reader restart. Bad limits and empty or oversized cursors yield `invalid_request`. Store or projection failures yield `internal_unavailable` with no partial page. Only SQLite busy or locked cases mark the failure retryable.

Synthetic tests validate the shared response schema, the 64-row boundary, current revisions across pages, blocked cross-pager and tampered continuations, minimal SQLite column reads and redacted storage errors. DSH at `fa4add96455524b55e4a1ef3ad1dd7ae4a0525e6` pins the byte-identical v0.1.0 artifacts from Hermes `48a930a2c01b2add9e349cbc1f0d65278066cc1c`. The shared artifacts keep the same version and bytes. Trusted host-principal propagation, authorization of a task collection, HTTP registration and end-to-end Hermes client acceptance remain open under #29/#30.
