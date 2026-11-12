# 15. Primary Bot Binding and Continuity

English | [简体中文](15-primary-bot-binding-zh.md)

**Status: optional future design, not implemented; not a prerequisite for the profile-first local MVP.** If this capability is chosen, the user selects an existing Hermes **Bot Mode Bot** to act as the personal super agent. This does not create another agent loop, change Hermes's global/default Bot, or grant new permissions. All binding records, service methods, roles, events and capability flags below belong to this proposed plugin design. The current CLI task inbox is a separate local feature, not proof of Bot binding or owner authentication.

The design source baseline is Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. Compatibility checks cover the [roster](#current-pin-canonical-bot-chat-roster), [Desktop routing](#current-pin-desktop-profile-routing), [native profile lifecycle](#current-pin-native-profile-lifecycle), [same-install Bot messaging](#current-pin-same-install-bot-messaging) and [deferred Bot Chat delivery](#current-pin-deferred-bot-chat-delivery) at the current pin. Read [03](03-native-architecture.md), [06](06-plugins-mcp-and-security.md), [11](11-worker-model-routing.md) and [14](14-client-api-contracts.md) alongside this contract.

Preparatory code and contract evidence are in [18](18-owner-entry-and-read-authorization.md): the read evaluator exists, but missing public receiving-Bot identity keeps production owner contexts and private reads in this remote/Bot lane disabled. The binding flows below remain a design.

The current default route is E6.8/E6.9 in [08](08-roadmap-and-acceptance.md): native LOCAL sessions in a trusted single-user local gateway/profile, without Bot enrollment. A profile is not identity; LOCAL is not proof of physical locality. Host SessionAuthority owner/operator read/control, exact registered live-source and admission checks still apply, and all already host-authorized controllers share local data. Local commands do not pass the remote-owner/binding gates in this document; the unwired pending-enrollment/read-admission cores are not prerequisites for explicit local commands.

## 1. Decision and User Experience

In this optional Bot-bound lane, the personal main agent is the user's selected native Bot: its profile owns personal domain state, and its **canonical Bot Chat** is the preferred coordination conversation. Hermes still owns inference, sessions, compression, worker execution, cron, credentials and transport. The plugin contributes personal-domain context, tasks, policy and evidence.

The intended setup is: select an existing Bot and its machine, review the exact target and data scope, confirm the binding, then see **Primary Bot: <display label> · <verified connection/profile>** with a separate capability/health indicator. Binding an existing Bot preserves its model, SOUL, memory provider, credentials, ordinary conversations and routines. No automatic copying, destructive reset, model change, or retitling of another conversation occurs.

The designation is a plugin responsibility, not Hermes's reserved `@hermes` alias or the desktop's active/default profile. Opening another Bot does not switch the personal primary. Other Bots remain available for their own work.

## 2. Native Facts and Boundaries

| Verified at the pin | Consequence for this design |
|---|---|
| A Bot Mode Bot is a profile with roster metadata and a canonical Bot Chat [B1] | Bind the native profile and canonical registry, not a new persona or platform token |
| Plugin managers and durable plugin state are scoped to Hermes home/profile [B2] | Enable the backend in the selected profile; installing UI code does not bind every Bot |
| Desktop exposes `host.profileRoutes()` and route-aware `host.requestProfile()` [B3] | Use the complete verified route descriptor; never choose by display name alone |
| `profiles.list` supplies `canonical_session.id` and its compression `resolved_id` [B4] | Resolve the authoritative canonical conversation, not `last_session`, a worker, or cached UI metadata |
| The install has an opaque `install_id`; profile names/paths can change and no immutable profile incarnation is exposed here [B5] | Install ID and slug are useful locators, not authentication or sufficient recovery proof |
| `ctx.inject_message` is profile-scoped, capability-gated and returns only a boolean host acceptance [B6] | It is not a durable exactly-once delivery API or proof that a Bot answered |
| Platform routes distinguish receiving `bot_profile` from executing `profile`; session keys include platform/chat/thread/user [B7] | Same profile is not automatically the same conversation or transport account |
| Hermes exposes `message_agent` in protocol-enabled Bot Chat sessions on managed installs [B8] | Eligible Bots can collaborate through a native route. Owner grants and worker routing have independent gates. |
| Cron can target `bot-chat[:profile]` through native authority admission [B9] | Reuse native receipts and scheduling; never run a second writer against a Bot Chat |

These are reference contracts, not permission to import private modules as a supported plugin API. In particular, the canonical registry implementation, profile-rename internals and Bot delivery mailbox are **source evidence**, not new `ctx` methods. E0.7 must prove supported adapters or report a generic upstream seam. Do not manufacture `ctx.bind_main_bot`, `ctx.current_owner`, or a native immutable `bot_uuid`.

### Current-Pin Canonical Bot Chat Roster

The roster fixture drives the native gateway `/api/ws` ASGI boundary and the OpenRPC `profiles.list` method at clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. It uses synthetic local tickets and temporary profile and session stores without a real listener, Desktop client, model or account. The exchange negotiates `hermes-gateway-v1` and receives `gateway.ready` with `session_authority: true`. [Roster contract tests](../tests/contracts/test_native_bot_roster_asgi.py) · [Gateway OpenRPC](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/shared/src/gateway-contract.openrpc.json)

| Fixture case | Observed result |
| --- | --- |
| Host-scoped ticket explicitly selects a served sibling | Both profiles share a display label and return distinct canonical IDs. The selected profile appears first. Its hidden exact `Bot Chat` supplies `canonical_session.id`. `resolved_id` and preview come from the compression tip. `last_session` and `worker_session` refer to the separate numbered chat and worker. |
| Profile-scoped interactive ticket | The ticket profile exposes its session fields, including a canonical chat whose stored owner differs from the ticket subject. The sibling exposes discovery metadata without `canonical_session`, `last_session` or `worker_session`. An explicit request for that sibling returns `profile_mismatch`. |
| `worker-adoption` ticket | `profiles.list` returns `permission_denied`. |
| Host-scoped roster after a sibling begins retiring | The retiring sibling becomes metadata-only. The serving profile still returns its canonical chat. |
| Unbound legacy or recoverably auto-archived exact-title chat | The authorized roster returns `canonical_session: null`. The numbered chat remains recent and no row is created, adopted or restored. |
| Two isolated ASGI endpoints with distinct runtime instance IDs and the same seeded `install_id`, profile slug and display label | Each endpoint's own ticket returns its own profile path, canonical root, compression tip and preview. The repeated install observation does not identify which endpoint owns a session. |
| Unreadable install ID | The fixture supplies an unreadable marker as a directory. The roster returns an empty `install_id` and still reports the authorized canonical chat. |

The fixture fences execution, socket connections and listeners, and unrelated gateway background activity. It compares session, message, admission and state metadata rows before and after requests and checks that the native authority has no remaining connections or attached sessions. The preseeded install marker is unchanged and no new install lock file appears. The unreadable marker remains an empty directory. [Roster contract tests](../tests/contracts/test_native_bot_roster_asgi.py)

The native admission path grants operator access to a redeemed local `interactive` ticket. The ticket's `profile` or `host` scope independently determines whether a request can reach sibling authorities. This verifies the local operator contract only. Verified human ownership, remote authentication and public plugin caller context require their own proof. [Native gateway admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/run_api.py#L452-L490) · [Current-pin owner evidence limits](78-enrollment-ceremony.md)

The authority roster reads the existing session stores with `reopen=False`. The exact-title `session.list` path can adopt an eligible legacy row and needs separate verification before use as discovery. The roster's `install_id` is an observation from the serving Hermes root. The resolver can mint it on a writable root when it is absent or malformed. An ID can survive a filesystem copy, so host continuity requires separate evidence. [Roster implementation](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_group_controls.py#L389-L450) · [Legacy adoption fixture](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/gateway/test_bot_roster_fleet.py#L94-L102) · [Install identity resolver](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/install_identity.py)

### Current-Pin Desktop Profile Routing

Five [Desktop route composition tests](../tests/desktop/test_profile_route_composition.mjs) passed with Node.js `26.12.1`. They ran the roster, route projection, SDK request and Bot Mode routing modules from clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` with synthetic inputs and substitute store and transport boundaries. The composition tests leave Electron IPC, the renderer gateway pool, backend reachability and owner continuity unexercised.

| Fixture case | Observed result |
| --- | --- |
| Two connections expose the same Desktop profile name and different backend profiles | The inventory keeps both source-qualified routes without exposing credentials. Bot Mode sends each request through its own `connectionId` and Desktop `profile`, with the RPC's `profile` operand rewritten to the corresponding `targetProfile`. A direct SDK request preserves its supplied RPC parameters. |
| Remembered offline SSH profile and cold SSH inventory | The cached profile and cold `default` route each produce one request for their own connection and backend profile. Both substitute gateways reject. The request log contains only those two scoped attempts. |
| Incomplete descriptor or ambiguous bare profile | The SDK refuses before calling the substitute gateway. |
| Registered route, replacement target and removed source | The exact registration helper accepts the unchanged descriptor and rejects both the changed `targetProfile` and removal. An explicit SDK request using the removed descriptor reaches only the original substitute gateway, which rejects it. |
| Missing or copied install marker | Two missing install observations leave two route rows. A shared nonempty marker for the same profile collapses the rows to the configured primary connection. |

The pinned Desktop preload exposes `getProfileRoutes` and the scoped dial bridge. Its main process builds the inventory from the connection registry and roster. The SDK's initial explicit request validates the three descriptor fields and sends the call to the gateway store. The SDK checks the exact registered triple before its one explicit-route hydration retry. A saved connection can be repointed under the same ID, so that comparison alone cannot establish backend continuity. [Preload bridge](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/preload.ts#L53-L64) · [Registry inventory](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14284-L14358) · [SDK request and registration check](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/profile-request.ts) · [Hydration retry](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/index.ts#L1098-L1116) · [Connection edits](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L8568-L8589)

The renderer can reuse the exact primary connection or a shared primary backend for another profile on the same source. A failed scope probe can also keep a remote primary on that same source. Inventory can include cached local profiles or an SSH seed awaiting a dial. The copied-marker result means the Desktop inventory can conceal distinct endpoints, even when each endpoint answers for its own canonical chat in a separate test. [Primary sharing](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/store/gateway.ts#L348-L409) · [Inventory projection](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14294-L14351) · [Native endpoint fixture](#current-pin-canonical-bot-chat-roster)

The optional [renderer gateway pool test](../tests/desktop/desktop_profile_route_pool.test.ts) passed its single Vitest case. It runs the pinned registry, route projection, Bot Mode route logic, SDK request helper and renderer store. A test SDK facade forwards to the real request helper. The Desktop bridge and gateway transport are substitutes. Two same-name non-primary routes open distinct pooled entries, use their respective fresh WebSocket URLs from the substitute bridge and send the corresponding backend profile operands. The fixture removes one source from the substitute registry and invokes the renderer's disposal entry point. That entry closes. A later request for it fails at scoped connection resolution, before the WebSocket URL lookup or RPC. The other entry stays open, and the primary, ambient and legacy request paths remain unused.

To reproduce this optional test, use a disposable checkout at the exact Hermes pin with clean tracked files. Set an isolated `HOME` and `HERMES_RUNTIME_DIR` and use Node.js `26.12.1` and pnpm `12.15.0`. From the Hermes root, run `pnpm install --frozen-lockfile --ignore-scripts --filter . --filter '{./apps/desktop}...'`. Copy this repository's `tests/desktop/desktop_profile_route_pool.test.ts` into `apps/desktop/src/store/`, run `pnpm --dir apps/desktop run test:ui src/store/desktop_profile_route_pool.test.ts`, and remove the copied test file after the run. The dependency-free Node composition check runs separately in CI.

The same pin passed 261 distinct upstream cases under Vitest `4.1.12` with Node.js `26.12.1` and pnpm `12.15.0`. The UI project passed 157 upstream cases. The four Bot Mode suites `routing.test.ts`, `data.identity.test.ts`, `data.roster.test.tsx` and `canonical-chat-registry.test.ts` accounted for 81. The SDK `profile-routing.test.ts` and renderer `gateway-profile-request.test.ts` accounted for 49 and 27, respectively, and ran alongside this project's separate pool fixture. The Node-based `electron` project passed 104 cases in `connection-registry.test.ts`. These focused runs used synthetic inputs. Actual Electron IPC and live gateway connections remain unverified. [Bot Mode suites](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots) · [SDK routing suite](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/profile-routing.test.ts) · [Renderer request suite](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/store/gateway-profile-request.test.ts) · [Registry suite](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/connection-registry.test.ts)

### Current-Pin Native Profile Lifecycle

The lifecycle tests use clean Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` and synthetic profiles. The CLI fixtures run the native profile parser and dispatcher against stopped homes, with service management, shell aliases and skill-sync subprocesses substituted. Network connections, listeners and SDK installation are fenced. The separate refusal case substitutes a live multiplexer response at the control-call boundary. [Native profile lifecycle tests](../tests/contracts/test_native_profile_lifecycle.py) · [Identity settlement test](../tests/contracts/test_native_profile_identity_settlement.py)

For a named profile, native rename moves the home and then rekeys session and routing identity. It records `previous_names` as best-effort metadata. The move can succeed while rekeying remains incomplete. The native `profile migrate-identity <old> <new>` command retries the durable migration independently. The default profile's rename changes only its display name. [Native profile lifecycle](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profiles.py#L2213-L2310) · [Profile identity migration](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profile_identity.py#L29-L85)

Deletion tombstones the named home before removal. Identity purge is a separate operation over name-keyed routing, heartbeats and delivery bookkeeping. It refuses a name that is live again. Creating a new profile under the same name can reuse its locator within the installation. Native `--clone-all` can copy presentation metadata while excluding session history, checkpoints and cron data. [Native creation and deletion](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profiles.py) · [Identity purge](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profile_identity.py#L55-L138)

| Stopped CLI fixture case | Observed result |
| --- | --- |
| Rename an existing Bot profile | The old slug stops resolving and the active profile follows the move. The hidden exact `Bot Chat` keeps its root, compression tip and message. Both session rows' `profile_name` values and the shared route use the new slug. An unrelated shared route stays intact. |
| `--clone-all` into the old slug | The clone shares the renamed profile's display label and `previous_names` and copies a synthetic plugin-data marker. It excludes the source `state.db` and its seeded `cron/jobs.json`. Both profiles are separately listed. |
| Delete the renamed profile with its populated local database | The CLI exits `1` and reports pending settlement because the tombstone prevents the purge from opening the named database. The directory is removed, the active profile resets to `default`, and the shared route has already been purged while the unrelated route remains. `profile purge-identity` succeeds after removal. |
| Recreate that slug after settlement | The new profile uses the same path and install marker and clears the tombstone. Its `previous_names` list is empty. The synthetic plugin-data marker and original canonical root and tip are absent. |

When the substituted live multiplexer declines identity purge, the native delete reports `ProfileIdentitySettlementPending` after removing the tombstoned profile. The shared root's routing, heartbeat and historical session rows remain intact at that point. Two stopped `profile purge-identity` calls settle the exact deleted name idempotently and preserve a similarly named route and heartbeat and the shared session history. A later purge of the now-live recreated slug exits `1` and preserves the new route under the same key. [Identity settlement tests](../tests/contracts/test_native_profile_identity_settlement.py)

A destination routing-key collision in the moved database demonstrates partial rename settlement. The directory moves and the shared root database rekeys, while the CLI warns and leaves the moved database unchanged. An explicit `profile migrate-identity` retry exits `1` while the collision remains. After the fixture removes the synthetic conflicting row, the same native command rekeys the profile's session fields and route, preserves the canonical lineage and message, and is idempotent on another retry. [Identity settlement tests](../tests/contracts/test_native_profile_identity_settlement.py)

The stopped-install fixture closes its authority and session databases before copying the synthetic root. The original and the copy run independently and sequentially with fresh local tickets. `profiles.list` returns matching install markers, profile labels and canonical summaries, including the same root and compression tip. The fixture's authorized `runtime.describe` calls return different runtime instance IDs and profile paths. The roster reads preserve the database snapshots taken after each start. A match on install marker and canonical lineage still leaves the choice of authority unresolved. [Stopped-install roster fixture](../tests/contracts/test_native_bot_roster_asgi.py) · [Identity limits](#33-identity-limits-must-remain-visible)

Live Desktop route and profile transitions, authoritative restore continuity, supported caller and worker provenance, and broader delivery receipt reconciliation remain open under E0.7. Optional HTTP still depends on E0.6. Owner-authorized enrollment, active binding and reconciliation remain separate work under E1.6 and E3.6. [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33)

## 3. Identity, Storage and Scope

### 3.1 Three distinct identities

1. **Human authority:** the verified owner/principal and current grant/policy from E1. A local CLI operator, profile name, Bot label, `is_bot` flag or client JSON is not this identity.
2. **Native target:** an authenticated host route, install observation, backend profile and canonical session lineage. Client-side `connectionId + profile` addresses a registry route; `targetProfile` may differ. Connection IDs are client-local, not portable server IDs [B3].
3. **Plugin enrollment:** a random plugin-owned `enrollment_id` and `binding_id`, stored in the selected profile's plugin database. These identify the enrollment, not a host-issued identity, secret or permission token.

The backend derives its profile scope from verified host context. It must not accept an arbitrary filesystem home from a request. `ctx.profile_name` is a convenience label, not sufficient authentication; in this pin its error fallback can be `default` [B2]. Missing trusted identity/scope blocks protected binding work.

### 3.2 Proposed records

```json
{
  "schema_version":"personal.primary_binding.v1",
  "binding_id":"bind_example",
  "enrollment_id":"enroll_example",
  "owner_id":"owner_verified",
  "authority_id":"authority_example",
  "binding_epoch":1,
  "revision":1,
  "state":"active",
  "target":{
    "observed_install_id":"opaque-host-install-id",
    "backend_profile":"personal",
    "canonical_root_id":"session_example",
    "resolved_session_id":"session_tip_example"
  },
  "continuity_mode":"shared_domain_separate_transcripts",
  "policy_revision":31,
  "confirmed_by":"verified-principal-ref",
  "confirmed_at":"2026-11-06T10:00:00Z"
}
```

This illustrates a future active record, not current readiness. `authority_id` identifies this plugin-owned policy/domain store, not a second runtime or global registry. The authenticated local server associates the record with its own storage home; paths and credentials are absent from client DTOs. A client stores its route descriptor separately and resolves it again when connecting.

Use one active binding per owner in this authoritative store, enforced by a database uniqueness constraint. Never claim installation-wide or cross-machine singleton enforcement from a profile-local database. V1 supports one explicitly designated authoritative store, not active-active copies. Enabling the package in another profile does not enroll it or copy grants.

Additional proposed records are `binding_proposals`, `binding_audit`, `session_roles`, `worker_handoffs` and `delivery_correlations`. References include binding epoch, policy revision, native session/run IDs and immutable operation IDs. Reuse the domain/outbox/audit mechanisms in [04](04-domain-data-and-memory.md) and [05](05-automation-and-delivery.md), not a second transcript store or scheduler.

### 3.3 Identity limits must remain visible

An install ID file or plugin enrollment can be copied with a backup. Neither proves that a restored/cloned host is the original. `previous_names`, paths and matching labels cannot prove profile continuity. A fresh profile with an old name must not inherit an enrollment merely by name.

Automatic recovery requires current authenticated target evidence, a readable expected install identity, the expected enrollment, canonical lineage and no conflicting authority observation. A changed profile locator, lost enrollment, install mismatch, duplicate identity or unexplained lineage requires owner-reviewed recovery. If the host cannot distinguish a clone from the original, report `identity_ambiguous`; do not invent certainty. Protecting against malicious same-user code or concurrently running cloned disks needs an external fencing authority and OS isolation, outside v1.

## 4. Enrollment and Control Contracts

### 4.1 Initial binding

1. Discover accessible native Bot/profile routes. Show friendly label, machine/connection, backend profile, availability and whether an existing canonical Bot Chat can be verified. Metadata-only discovery is not permission to read its history.
2. Verify the selected route, current owner authorization and plugin presence in that profile. Missing installation/consent is an explicit setup step. Never silently enable a plugin across all profiles or copy provider credentials.
3. Resolve the existing canonical Bot Chat through an adapter proven at E0.7, preferring the verified native canonical registry/roster's root ID and lineage. The native wire path also supports authorized `session.list` title lookup; exact `root_title == "Bot Chat"` (or exact `title` on a verified older shape) is a compatibility filter, not an identity or owner-authorization proof. Reject generic numbered-title matches. Record root and current lineage tip separately. If trustworthy registry/provenance is unavailable, keep the capability unavailable; a matching title cannot replace it. An RPC error, missing access, or an empty result following prior positive evidence is **unknown**, not permission to create a new chat [B10].
4. Prepare a short-lived binding proposal with exact target, enrollment, expected revisions, data/role scope and evidence. It performs no external send and does not change the active binding.
5. Show the verified owner a nonce-bound preview. Confirmation is one transaction: check current identity, expiry and revisions; consume the proposal; establish the unique binding; increment the binding/policy fence as appropriate; persist audit/change rows. Duplicate confirmation returns its original receipt.
6. Advertise only capabilities whose independent gates pass. An active binding may still have controlled writes, worker launch and proactive delivery disabled. Selection alone never enables them.

V1 selects an **existing Bot and canonical chat**. If no verified Bot Chat exists, direct the owner to native Bot Mode setup and retry. This plugin does not silently create/retitle a session or write `ui_meta.hermes-bots` to fake membership. Headless enrollment is supported only after the same native identity/session contracts are proven; a configured `bot_mode_protocol: true` alone is insufficient [B8].

### 4.2 Proposed service methods

These are internal domain-service contracts shared by future CLI, native UI and optional HTTP adapters, **not existing Hermes RPC names**. UI selection may use native read APIs, but mutation still enters the owner-verified binding service. The current local task CLI does not expose these methods.

| Proposed method | Input and output |
|---|---|
| `primary_binding.inspect` | Authorized current binding, health, release gates and ETag; no tokens or home paths |
| `primary_binding.propose` | Server-resolved target candidate and requested scope; returns proposal ID, exact preview, expiry and one-use presentation |
| `primary_binding.confirm` | Proposal ID, presentation nonce, expected revision and idempotency key; returns binding receipt |
| `primary_binding.pause` | Current binding If-Match and reason; commits a new fence and stops new binding-dependent admissions |
| `primary_binding.resume` | Current revision plus fresh owner confirmation after target/policy checks; not a worker/model command |
| `primary_binding.recover` | A prepared recovery proposal for the same enrollment; returns confirmed mapping or an explicit blocker |
| `primary_binding.retire` | Current revision and owner decision; leaves a durable tombstone, invalidates binding grants/presentations and reports in-flight work |

Preparing a proposal requires current owner access and `personal.primary_binding.manage`, but no prior confirmation of that still-uncommitted proposal. Committing enrollment, recovery, pause/resume or retirement requires that scope **and verified owner confirmation** of the exact preview. Scope is necessary, not sufficient. Presentations reuse [14](14-client-api-contracts.md)'s 256-bit nonce, five-minute default expiry, principal/payload/revision binding and single-decision rules. Automatic protective suspension/fencing may remove authority without waiting for confirmation; it may never grant authority or resume a binding. Models/workers cannot mint proposals that confirm themselves. Server-side resolution rejects client-supplied principal, authority, epoch, grant or filesystem path fields. Apply [14](14-client-api-contracts.md)'s idempotency, authorization, ETag and error conventions; internal binding commands use a stable owner/authority/method/key namespace with one decision per proposal, while an HTTP facade retains [14](14-client-api-contracts.md)'s owner/profile/method/route/key transport namespace. Binding changes never renew an expired approval.

An optional HTTP/UI facade remains gated by E0.6/E6.5 and trusted principal propagation. The isolated hosted HTTP admission boolean is not enough. A native channel/CLI binding adapter still needs its own E0.7/E1 identity proof; local process access is not a substitute.

## 5. Lifecycle, Recovery and Rebinding

The persisted binding states are `unbound → active ↔ suspended → retired`; `active` or `suspended` may enter `recovery_required`. Proposals are separate records (`pending | confirmed | expired | cancelled`), so opening a picker never removes a working binding. `retired` is terminal for that binding ID. Health is separate (`verified | offline | incompatible | identity_ambiguous | storage_unavailable`) and never grants authority.

Owner-confirmed recovery returns `recovery_required → suspended` after identity and reconciliation pass. It may commit `active` in the same decision only when the exact preview explicitly included resumption and every relevant gate now passes; otherwise a later owner-confirmed resume is required. Retirement first commits the protective fence, then the terminal binding state; unresolved in-flight effects remain in the ledger rather than disappearing with the binding.

| Change or failure | Required behavior |
|---|---|
| Connection alias/URL changes, same authenticated host and profile | Re-resolve the registry route and verify enrollment; update client routing only; do not increment authority for a cosmetic label |
| Bot display title/avatar changes | Display refresh only; do not rewrite permissions or select a different Bot |
| Compression advances the canonical tip | Follow host-proven lineage from the same canonical root; keep binding ID/epoch and logical operation IDs |
| Profile slug/path rename | Enter recovery until host migration, same enrollment and owner-reviewed new mapping are verified; aliases alone are insufficient |
| Canonical chat archived, deleted, renamed or displaced by handoff | Stop canonical-target delivery, retain domain work; require explicit recovery confirmation for the replacement root; increment epoch |
| Gateway restarts or connection drops | Mark offline; preserve receipts; reconnect to the verified authority and reconcile before resubmission |
| Profile deleted/recreated, enrollment lost, wrong install, duplicate clone | `recovery_required`; no name-based inheritance, auto-create or cross-profile fallback |
| Plugin disabled/unloaded or worker skips hooks | No new plugin-controlled admission; write paths without independent enforcement remain disabled; do not claim other host tools stopped |
| Older/incompatible host loses a required capability | Mark incompatible and disable the affected feature; never downgrade into raw DB edits or a second agent loop |

The target resolver runs before each admission/delivery, not only at enrollment. On a mismatch it atomically fences new plugin-owned admissions. Executors check current binding epoch and policy at each controlled effect, including ordinary workers with frozen startup config. Revocation/admission ordering follows [06](06-plugins-mcp-and-security.md); already admitted remote work may remain in flight and must be reported truthfully.

### 5.1 Rebinding within the same authority

Repairing the same profile's canonical chat is a reviewed recovery operation, not an ordinary session switch. Pause admissions; inspect pending approvals, queued deliveries and workers; verify the replacement canonical root and source evidence; confirm the exact preview; atomically increment epoch, invalidate stale presentations and update mapping. Old results remain queryable as historical evidence. Pending work is re-evaluated, never silently forwarded to the new chat. Resume only after reconciliation.

Changing the profile or host changes the storage/authority boundary. It must not be implemented as editing `backend_profile` on a live record.

### 5.2 Replacing the Bot or migrating hosts

V1 has **no automatic cross-profile/cross-host takeover**. Use a separately tested, owner-directed export/import migration under E8.3:

1. Freeze the source binding and persist its new fence. Stop new domain admissions and scheduled delivery mappings; reconcile/cancel workers and queued effects. Refuse migration while uncertain effects cannot be safely accounted for.
2. Export only explicitly selected plugin-domain data, immutable IDs and receipts with a versioned manifest/checksum. Do not copy host credentials, owner grants, approval nonces, transcript DBs, plugin enrollment or native runtime ownership. Authorization to change the primary Bot is not blanket permission to copy all private data.
3. Prepare the destination under its verified owner and fresh enrollment/authority. Import with an idempotent migration ID; preserve historical object/effect identity and source authority, while unresolved native references remain disabled until mapped. Imported approvals/grants cannot execute.
4. Verify source retirement/fencing and destination reconciliation, then obtain explicit destination activation confirmation. Only the destination becomes active; preserve the source tombstone. If a step fails, remain suspended and offer a verified rollback/recovery plan, never automatically activate both.

This is a stop-before-start protocol, not an atomic distributed transaction. If the source is unreachable or retirement cannot be proved, takeover is blocked pending operator recovery. Restoring a backup requires an explicit recovery procedure that fences old policies before enabling writes; a database restored with its old epoch cannot detect its own rollback. Forked concurrent restores are unsupported without an external authority. No broad host/worker isolation is implied.

## 6. Roles, Delegation and Context

| Server-derived role | Allowed responsibility | Not implied |
|---|---|---|
| `primary` | Verified canonical Bot Chat coordinates domain work and reports results | Permission to approve itself or bypass action gates |
| `owner_entry` | An owner-verified ordinary/Desktop/mobile session may inspect or submit within its grants and link domain tasks | Becoming canonical, inheriting all transcripts, or changing the primary binding |
| `worker` | Native child/run with a recorded task handoff, minimal data and a specific result contract | Full owner memory, binding management or delegation beyond its grant |
| `specialist_bot` | Explicitly authorized separate profile/connection receives a scoped collaboration request | Owner identity, universal access, or automatic membership in E9 routing |
| `observer` / `untrusted` | Only permitted public/source-scoped observation or evidence ingestion | Personal-domain mutation, owner approval or private context |

Roles come from verified runtime/session/worker provenance plus the binding record, never a prompt, tool argument, chat title alone or `role:"primary"` in JSON. A message in the canonical chat may still be bot-authored, scheduled or third-party. **Conversation role and message author are independent.** Each action must retain the true author, source, grant and current policy.

The proposed handoff carries `binding_id`, `binding_epoch`, `task_id`, `attempt_id`, authoritative parent/native refs, scope, budget/deadline, expected result and grant references. A worker result is evidence, not a user instruction or task acceptance. The primary/domain acceptance service verifies it. Delayed results from old epochs may be retained for reconciliation but cannot reopen authorization or automatically reach a new target.

Use native delegation/lifecycle for short work and Kanban for durable work. Persistent specialist Bots can use native `message_agent` when supported and authorized. Its response reports handoff or admission for the route used. Turn completion requires a later outcome. Apply native loop guards plus plugin budgets and sender/destination policy. E9 chooses permitted worker model/effort routes. Primary Bot selection and model configuration remain separate, as do Bot, cron and Kanban paths outside the worker routes.

Plugin loading can affect every session in a profile. The initial integration chooses minimal tools at supported creation/rebuild boundaries and rechecks roles in domain handlers. Hooks that fail open or workers that skip plugin hooks cannot be the sole role/authorization boundary. Unknown provenance blocks protected operations. E0.7 must expose any missing normalized session/author/worker context as a tested adapter or upstream gap.

### Current-Pin Same-Install Bot Messaging

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, tool injection checks the Bot Mode protocol setting, the exact `Bot Chat` title and the managed-install marker. The tool handler rechecks the title and marker. When the caller has a session database, its home supplies the sender profile. The profile slug determines the structured author ID `bot:<profile>`, and the roster supplies the handle and display metadata used in the message prefix. These values come from the host's calling context and roster. [Tool eligibility](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L127-L168) · [Sender attribution and local routing](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L239-L364) · [Calling agent context](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L1008-L1025)

The receiving authority normalizes the author supplied in `bot_relay.deliver` as attribution. It derives the mailbox `principal_id` independently from the authenticated RPC caller. For a canonical LOCAL recipient, the target FIFO uses an `automation:<session_key>` producer and carries the author under `local_automation_v1.turn_author`. For a same-install notify-only send, the tool can return the authority's queued status after durable admission and remove its temporary payload and intent without starting a reply waiter. [RPC author parsing](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L805-L828) · [Mailbox admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L955-L1000) · [Automation snapshot](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_automation.py#L549-L565) · [FIFO admission](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_automation.py#L605-L636) · [Notify-only result](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L762-L799)

The fixture uses a synthetic named sender backed by a real session database and a separate default-profile Bot Chat on the same temporary installation. It exercises tool injection and the native sequential route selector and inline executor, then `GatewayClient`, private control ticket issuance, `/api/ws` redemption and the receiving authority. The fixture supplies endpoint discovery and a synthetic local peer subject and bridges control and WebSocket traffic in memory. [Notify-only contract test](../tests/contracts/test_native_bot_notify_only.py) · [Sequential route selector](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/tool_executor.py#L1674-L1685) · [Native inline executor](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/inline_tool_executors.py#L296-L303)

| Fixture case | Observed result |
| --- | --- |
| Ordinary session in the sender profile | Tool injection is refused. Direct invocation through the inline executor returns an error before endpoint discovery, ticket issuance or admission. |
| Named Bot Chat sends to `@hermes` | The default profile's canonical Bot Chat receives one queued admission. The message starts with `Message from 🤖 Scout Fixture (@scout): [no reply needed]` and its structured author is `bot:scout`, name `scout`, `is_bot: true`. The local ticket subject and FIFO producer remain separately recorded. |
| Durable receipt and event reconstruction | The tool reports `queued` and `expects_reply: false`. Its delivery ID matches the pinned intent, mailbox receipt and FIFO request `bot:<delivery_id>`. The native reconstruction helper returns the same author and internal event marker from that queued row. The sender's temporary payload and intent are removed. The compared sender database rows stay unchanged, the recipient transcript stays empty and the authority records one scheduling request. |

The fixture holds the recipient turn queued and fences reply waiters. The evidence covers same-install Bot attribution and local operator admission. Verified human ownership, supported plugin caller and worker provenance, model execution, reply delivery, installed transport and cross-machine messaging require separate verification.

## 7. Cross-Device and Platform Continuity

Default: **shared domain, separate transcripts**. Desktop Bot Chat, Telegram DM, Discord thread and CLI scratch sessions can refer to the same authorized tasks/projects without copying their conversations or pretending they share a prompt. Context is rebuilt from bounded, permission-filtered domain facts and explicit task links. User text from one route is not silently replayed as a fresh command on another.

If the user explicitly wants the same native conversation, use a supported canonical attach/handoff path and test ownership, ordering and recovery separately. `gateway.profile_routes` does not provide a target canonical session ID. Do not implement transcript merging, direct SessionDB writes or an API-server shadow conversation to approximate continuity.

For a messaging entry, prefer one unique platform credential owned by the selected Bot's profile. A shared bot can route selected chats to another runtime profile, but authorization/replies still depend on the receiving transport. Store both verified transport and runtime references in channel bindings. `SessionSource.is_bot` describes the **sender**, not which Bot received it. Do not claim bot-level separation when two bots are deliberately routed to the same runtime profile and otherwise identical session key [B7].

Group/shared channels never receive private canonical summaries by default. Delivery selects a verified authorized route for that specific content. Returning a status to the owner in the originating session is distinct from starting a new canonical Bot turn; neither happens twice merely to keep screens synchronized.

## 8. Messages, Routines and Receipts

Use one owner for each delivery. A domain notification stores its intended binding/epoch, destination, content revision, policy scope and stable effect ID before admission. At dispatch, resolve the current canonical/transport target and recheck permission. Target changes pause/review the old effect rather than retargeting it silently. Native cron's delivery and the plugin outbox must not both send the same result.

Native `bot-chat[:profile]` delivery is machine-local and enters the existing Bot authority. The scheduler can durably defer a delivery that has yet to be admitted when the owner is unavailable, then retry with the same delivery ID on a later tick. If an admission response is lost, the scheduler's pending record can still be `queued` after the authority has committed admission. Preserve both native references and distinguish transfer and admission from queued, running, waiting, completed, failed and unknown execution outcomes. Reconcile uncertain claimed work under its existing identity [B9]. Cross-machine Bot delivery requires a separately verified authorized transport. A fallback CLI writer against the same transcript is forbidden. [Current-pin receipt evidence](#current-pin-deferred-bot-chat-delivery)

`ctx.inject_message(..., session_key=...)` returns a boolean and exposes neither a caller-supplied delivery ID nor a durable receipt lookup. At the current pin, the upstream gateway scheduler test returns `True` before its asynchronous dispatch raises. An uncertain submission needs a stable receipt-bearing adapter before it can be reconciled safely. Durable proactive activation remains blocked without that supported adapter. [Plugin API](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_context.py#L395-L402) · [Upstream scheduler test](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/gateway/test_plugin_message_injection.py#L341-L368)

Scheduled and specialist output keeps source attribution. A routine cannot label its own content as a direct owner request to obtain authority. Reminders to the owner and actions on third-party services remain separate effects with separate grants. A Bot binding does not automatically authorize proactive contact, cross-Bot sharing, new costs or external writes.

### Current-Pin Deferred Bot Chat Delivery

At Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`, the cron drain leaves a pending file `queued` when delivery raises an error. On a successful response it records `transferred` and copies the returned status to `receipt_status`. Before returning an existing receipt for that delivery ID, the authority checks the message, submitting principal, author and notification category. `transferred` records the scheduler's handoff. The receipt carries the authority's disposition, and turn execution and completion have their own outcomes. [Native cron drain](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/cron/bot_chat_legacy.py#L64-L123) · [Native receipt handling](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L795-L876)

The contract fixture sends a synthetic cron result to the same local profile. It exercises the native cron delivery helper and drain, `GatewayClient`, the private `session-ticket` handler and ticket redemption at `/api/ws`, and `bot_relay.deliver` on the native authority. The fixture supplies endpoint discovery and the local peer subject, bridges the control and WebSocket traffic in memory, and runs both event loops with the bounded test driver. [Deferred receipt contract test](../tests/contracts/test_native_bot_deferred_receipt.py) · [Native authority client](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_live_delivery.py#L71-L119) · [Private control handler](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/control_socket.py#L333-L410)

| Fixture step | Observed state |
| --- | --- |
| Endpoint reported stopped | Cron persists one `queued` record under the delivery ID derived from the execution and target. The authority mailbox and canonical admission queue are empty. |
| Endpoint reported ready, then first successful response dropped | The gateway emits a `queued` receipt before the bridge drops the response. The mailbox and canonical FIFO row `bot:<delivery_id>` agree on one admission ID. The client observes a disconnect and the cron record remains byte-for-byte unchanged at `queued`. |
| Later drain replays the delivery | With a fresh `interactive` ticket, the client sends the same delivery ID, profile, canonical session and message. The authority returns the existing receipt and the cron record becomes `transferred` with `receipt_status: queued`. |
| Drain runs again | The transferred record triggers no further handoff. The fixture still has one canonical session, one receipt, one queued FIFO admission and one scheduling request. The admission has no terminal outcome, and the transcript stays empty. |

The fixture holds the admitted turn queued and exercises synthetic local operator admission and receipt handling. Installed gateway and OS peer verification, model execution and turn completion, external delivery, restart and broader delivery reconciliation remain separate acceptance checks. The public plugin API exposes the boolean injection path described above.

## 9. Events, Errors and Client Recovery

Proposed durable invalidations are `primary_binding.changed`, `primary_binding.suspended`, `primary_binding.recovery_required`, `primary_binding.retired` and `primary_delivery.updated`. Use the same committed domain sequence/outbox as [14](14-client-api-contracts.md); do not create a parallel event bus as the authority. The snapshot includes the authorized binding summary. Optional live hints only request a refetch.

Payloads carry IDs, revision, epoch and reason codes, not transcripts, nonces, credential values or filesystem paths. A client receiving an epoch change discards stale binding-specific approval presentations and re-reads current grants; an event cannot supply a grant. Offline selection remains a draft, never a queued binding confirmation.

| Code | Meaning and recovery |
|---|---|
| `primary_unbound` | No confirmed primary; use authorized setup, not the default Bot |
| `primary_target_unavailable` | Known target offline; show last verified state as stale and reconcile |
| `primary_identity_ambiguous` | Conflicting host/profile/enrollment evidence; require owner recovery |
| `primary_canonical_unverified` | Canonical registry/lineage cannot be proved; no fallback creation |
| `primary_epoch_conflict` | Stale command/handoff; reload and re-evaluate, do not reuse old approval |
| `primary_role_forbidden` | Current verified role/author lacks this operation |
| `primary_capability_unavailable` | Required host adapter missing; keep the feature disabled |
| `primary_recovery_required` | Retirement/rename/restore interrupted continuity; run reviewed recovery |
| `primary_migration_blocked` | Source fencing, unknown effects or destination identity not settled |

Map missing authentication to 401, denied authority to 403, hidden foreign objects to 404, revision/epoch conflicts to 409/412, missing If-Match to 428 and unavailable trusted adapters/storage to 503 as appropriate. Local CLI surfaces use the same stable domain codes without pretending to be HTTP. Never interpret a transient network failure as successful cancellation or absence of a Bot.

## 10. Compatibility and Release Tests

Record native/plugin SHA, host mode, route/connection type, credential class, profile setup, session root/tip, worker mode and every skipped capability. The existing unit/host foundation tests do **not** certify these new contracts. Static document/JSON checks prove only syntax/structure.

| Required synthetic or authorized integration scenario | Assertion |
|---|---|
| Two same-named Bots on different connections; changed route alias | Explicit target identity wins; no active-chat/default/recency fallback |
| Discovery exposes metadata but no session access | Do not read or enroll beyond permission |
| Initial confirm double click, lost ACK, crash during commit | One binding/proposal decision; receipt query recovers; no second enrollment |
| Ordinary session, spoofed title/JSON, bot-authored canonical input, local CLI operator | Role and owner evidence remain independent; no self-approval |
| Concurrent owner/bot/worker work across two profiles | Correct profile policy/storage; no context or permission leakage |
| Compression, restart, failed/empty roster read | Follow proven lineage; unresolved absence cannot mint another chat |
| Profile rename partially migrates; delete/recreate same name | Fail closed until verified recovery; no alias-based inheritance |
| Canonical archive/rename/handoff replacement | Old delivery stops; owner confirms new root; new epoch fences stale work |
| Revocation races dispatch; old worker resumes after binding change | Order by committed fence; old grants denied; report already admitted effects truthfully |
| Bot-to-Bot messages, routine result, forwarded approval | Authorship survives; no owner impersonation or uncontrolled reply loops |
| Same profile across mobile/Desktop; two transport bots routed to it | Explicit task continuity only; no assumed transcript merge or bot-account isolation |
| Lost delivery ACK; native defer; target offline; duplicated cron result | Stable receipt reconciliation and one delivery owner; no competing session writer |
| Snapshot restore, cloned enrollment/install ID, old backup resumes | Recovery required under supported restore procedure; unsupported concurrent clone is not called safe |
| Migration crash before/after source fence and destination import | At most one activated authority in the supported protocol; no automatic failover/dual resume |
| Safe worker, hosted HTTP boolean, missing canonical/profile API | Protected capability disabled; no private import, prompt-only guard or default-owner fallback |

Older hosts may lack route descriptors, canonical fields or normalized provenance. Feature-detect and test supported modes; do not silently fall back to `last_session`, undocumented params or profile-only remote routing. Source examples of gateway topology and offline cron behavior can disagree with older prose: use the pinned implementation and contracts, then revalidate on upgrade. Merely installing a newer Hermes version is not evidence that this binding still works.

## 11. Implementation Work Packages

| ID | Status and dependencies | Deliverable |
|---|---|---|
| E0.7 Verify Primary Bot Contracts | M0, In Progress. Depends on E0.1/E0.2 and uses E0.4 findings. | Current-pin evidence for the [roster](#current-pin-canonical-bot-chat-roster), [Desktop routing](#current-pin-desktop-profile-routing), [native profile lifecycle](#current-pin-native-profile-lifecycle), [same-install Bot messaging](#current-pin-same-install-bot-messaging) and [deferred Bot Chat delivery](#current-pin-deferred-bot-chat-delivery). Live transport and profile transitions, supported author, caller and worker provenance, remaining receipt modes and the adapter map remain open. Optional HTTP also needs E0.6. |
| E1.6 Bind Primary Bot | Optional future; Backlog; E0.7, E1.1–E1.5, E2.1 | Owner-confirmed enrollment and recovery, unique active binding, revision/epoch fence, audit and role policy; no unconditional write enablement |
| E3.6 Reconcile Primary Bot Sessions | M1 gate for enabled Bot-bound paths, extended in M2; Backlog; E1.6, E3.2/E3.5, E4.3/E4.4 | Canonical resolution, worker handoff correlation, delivery/recovery and native receipt reconciliation |

Extend E6.1/E6.2 with the selected Bot's verified channel bindings and separate-transcript continuity. Extend E8.2/E8.3 with this failure matrix and reviewed migration/restore; E8.5 documents selection, pause, recovery and limitations. These are additions to the plan, not remote Project item creation or Done status.

E0.7/E1.6/E3.6 are release gates **when Primary Bot capability is enabled**. They do not block the profile-first local MVP or its explicit, no-dispatch task commands. A Bot-bound M1 must pass them for its enabled paths; custom HTTP/PWA/native-phone E0.6/E6.5–E6.7 remain separate optional lanes. Start with one existing Bot, one authoritative profile and one verified owner; defer automatic multi-host migration and broad multi-Bot orchestration.

## 12. Pinned Evidence

- B1: [Profiles, agents and Bots](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/profiles.md#L19-L43) and [Bot Mode lifecycle](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/bot-mode.md#L8-L45).
- B2: [Plugin context/state/profile and manager scoping](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py).
- B3: [Desktop profile route descriptors and connection identity](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md#L1446-L1514).
- B4: [Authorized canonical roster and compression resolution](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_group_controls.py#L330-L490).
- B5: [Install ID](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/install_identity.py), [profile metadata](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/profiles.py#L646-L678), and [rename/delete identity migration](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/profile_identity.py).
- B6: [Plugin injection scope, consent and boolean return](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_injection.py).
- B7: [Receiving-bot route discriminator](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/profile_routing.py#L62-L108), [session keys](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session.py#L691-L734), and [transport/runtime identity](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_identity.py#L43-L83).
- B8: [message_agent eligibility](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/bot_mode_dm.py#L127-L168) and [managed-install marker](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/bot_mode_probe.py#L131-L143).
- B9: [Cron Bot Chat delivery implementation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/scheduler_delivery.py#L714-L805), [deferred same-ID admission](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/bot_chat_legacy.py#L24-L100), and [single-authority Bot admission](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_bot.py).
- B10: [Authorized native title lookup](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_controls.py#L567-L596), [canonical UI resolution](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L88-L107), and [uncertain absence handling](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L330-L339).
