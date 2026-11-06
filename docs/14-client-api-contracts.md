# 14. Proposed Client API and Connector Contracts

English | [简体中文](14-client-api-contracts-zh.md)

**Status: design only. Every new domain endpoint, DTO, capability flag, policy scope, retention value and connector interface below is proposed and unimplemented.** Existing read-only foundation code does not expose this API, implement E1 authorization, or enable controlled writes. Source inspection of Hermes is not runtime certification. The verified source baseline is `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`; see [12](12-foundation-progress.md) and [13](13-enforcement-contracts.md) for actual implementation evidence.

This document makes [10's domain contracts](10-interface-contracts.md) concrete for optional clients. It does not replace [the authorization design](06-plugins-mcp-and-security.md), [mobile scope](07-mobile-and-voice.md), or [the roadmap](08-roadmap-and-acceptance.md).

## 1. Layers and Release Boundary

| Layer | Owns | Must not become |
|---|---|---|
| Native Hermes channel and session transport | Authenticated platform intake, session owner, agent loop, durable admission, tool execution, native approvals, streaming, scheduling and workers | A second personal-agent runtime |
| Personal domain service | Business projects, commitments, task acceptance, intents/grants, policy checks, effect/outbox/receipt records, authorized projections | A parallel transcript, scheduler, credential vault or generic tool executor |
| Proposed domain HTTP API | Typed commands and reads over the same domain services used by tools/channel handlers | A bypass around native or operation-level permission checks |
| Optional client | Rendering, safe local drafts, request IDs, reconnect and user decisions | An issuer of owner identity, grants or successful execution claims |

**M1 remains channel-first.** One existing Hermes messaging channel is the phone entry point. It does not depend on E6.5–E6.7, a PWA/native app, custom push, or another gateway deployment. Domain tools and authenticated channel handlers may use the same services before an HTTP facade exists. Optional M2/M3 clients use the native host and transport already deployed.

There are two different project identifiers: the plugin's opaque business `project_id` and verified `native_refs` such as a Hermes project/board reference. A GitHub Project issue/item is engineering planning metadata, never the runtime task identity. Clients cannot infer one ID from another or submit another owner's native reference to gain access.

## 2. Actual Hermes Hosting and Missing Seams

### 2.1 Dashboard plugin registration

The pinned Python plugin context has no `ctx.register_http_router`. The documented mount is a plugin dashboard manifest and a module-level FastAPI router [H1, H2]. The following is a **future file-layout example**, not files added by this design:

```text
hermes-personal-agent/
  plugin.yaml
  dashboard/
    manifest.json
    plugin_api.py
```

```json
{"name":"hermes-personal-agent","api":"plugin_api.py"}
```

```python
from fastapi import APIRouter

router = APIRouter(prefix="/v1")
# Future typed routes are declared on router after identity and policy gates exist.
```

Hermes mounts this router under `/api/plugins/hermes-personal-agent`. The proposed absolute base is therefore **`/api/plugins/hermes-personal-agent/v1`**, abbreviated `B` below. `B` is documentation shorthand, not a literal URL. Respect any verified deployment reverse-proxy base prefix. Do not claim these routes exist on the independent native API-server listener.

Normal HTTP authentication precedes plugin handlers. An unauthenticated request receives 401 before plugin existence is revealed; an authenticated request to a disabled/unknown plugin receives 404. User Python plugins need host enablement; project-local dashboard plugins do not auto-import Python. Profile home and secret scopes are bound by the host. Importing a module is not permission to perform an action.

### 2.2 Host-mode capability negotiation

| Verified host behavior | Consequence for the proposed API |
|---|---|
| In-process handlers share the host event loop | Use async I/O or worker threads for blocking work; bound concurrency and body size |
| `plugins.isolation: host` buffers forwarded HTTP | Bounded ordinary JSON polling is the correctness path; do not advertise plugin SSE |
| Hosted plugin WebSockets are unsupported; secondary-profile sockets may return 501 | `domain_websocket` remains false without an actual supported, tested route |
| Desktop plugin `ctx.socket` is a no-op on OAuth remotes | Never use socket availability as a prerequisite for state recovery |
| Plugin broadcasts are live, process-local and fire-and-forget | Use them only as refresh hints, not as durable action or delivery receipts |
| Host authentication has several credential/principal shapes | Prove a normalized trusted principal adapter for each mode, including host IPC |

Do not turn isolation off to make an optional UI work. No native general-purpose `ctx.current_http_principal()` contract was found. In particular, the isolated host's `with_hosted_admission` stamps only `hosted_http_authenticated: true`; that boolean is an admission decision, **not a verified owner/principal/profile/policy context** [H13]. A native request's `request.state.native_http_principal` is also not a general plugin-context API. E0.6 must prove a supported, normalized host boundary, or propose a **generic upstream principal seam with this concrete consumer**. Trusted identity propagation through isolated host IPC is an explicit unresolved blocker. The plugin must never decode cookies, accept a client-supplied identity, or trust arbitrary forwarded identity headers. If the verified principal/profile cannot be obtained, return 503 `host_identity_unavailable` for protected reads and writes; do not degrade to a default owner. An authenticated but unbound user gets 403 `owner_binding_required`.

## 3. Authentication Is Not Domain Authorization

### 3.1 Existing host authentication routes

These are existing host paths, **not new domain endpoints** [H3–H5]:

| Method/path | Existing purpose and limitation |
|---|---|
| `GET /api/auth/providers` | Discover available interactive host sign-in providers |
| `GET /auth/login`, `GET /auth/callback` | Host browser sign-in and callback |
| `POST /auth/logout` | Host logout behavior; not proof of revocation of all devices/credentials |
| `GET /api/auth/me` | Sanitized verified session or authenticated loopback identity |
| `POST /api/auth/ws-ticket` | Verified interactive session obtains a 30-second, single-use WebSocket ticket |
| `GET /auth/native/authorize` | Native system-browser sign-in with S256 PKCE and strict loopback callback |
| `POST /auth/native/token` | Exchange `{code, code_verifier}` for native bearer tokens |
| `POST /auth/native/refresh` | Refresh `{refresh_token, provider?}` through the host |

Dashboard cookies, native-app bearer credentials, enabled deployment/session-token modes and native same-user grants have different issuance and revocation rules. The private native grant header is not a remotely mintable mobile credential. The native API-server's `API_SERVER_KEY` is not automatically a credential for dashboard plugin routes. No plugin login database, token-signing service or refresh-token store is proposed.

Canonical local sessions intentionally allow verified operators of the **same profile** to attach across host authentication paths. This does not create per-human isolation inside a shared operator profile. The initial deployment is one trusted owner/profile; use separate Hermes profiles for separate owners unless an independently verified restricted-host policy exists. A plugin ACL cannot hide data already readable through the operator's native host APIs.

### 3.2 Proposed trusted request context

The adapter, not the JSON body, constructs:

```json
{
  "principal_id":"verified-host-subject",
  "issuer":"verified-host-issuer",
  "profile_id":"opaque-host-profile-ref",
  "owner_id":"own_example",
  "credential_class":"interactive_session",
  "auth_context_id":"server-owned-binding",
  "permission_revision":12,
  "policy_revision":31,
  "domain_scopes":["personal.read","personal.tasks.write"],
  "request_id":"req_example"
}
```

These are **proposed internal fields**, not a native Hermes payload. Store no bearer token in them. `domain_scopes` are plugin policy names, not new host token claims: `personal.read`, `personal.projects.write`, `personal.tasks.write`, `personal.commitments.write`, `personal.automations.write`, `personal.actions.prepare`, `personal.actions.execute`, `personal.approvals.decide`, `personal.connectors.sync`, `personal.artifacts.write`, `personal.control.revoke`. Having one does not override source ACLs, recipient/data limits, action-specific approval, current policy or native capabilities. Preparation scope never silently grants execution scope. Scoped tool/worker surfaces are selected at supported creation boundaries, not by cache-breaking mid-turn prompt mutation.

On every read and command, verify the current credential, owner binding, profile, object/source scope, policy revision and allowed transition. Denied identity is never repaired from a display name, model output, source URL, forwarded message, request body `owner_id`, or correlation ID. HTTP bodies cannot supply `approved`, `principal`, `grant`, `policy_revision`, raw credentials or arbitrary native routing fields. A native reference is accepted only through a server resolver that already checks access.

### 3.3 Browser, network and mobile sign-in gates

- Reuse Hermes Host/Origin checks, authenticated session expiry and cookie protections. All proposed unsafe browser methods additionally require a verified same-origin request or an explicitly allowed origin plus the host-approved anti-CSRF mechanism. If a host mode cannot supply this guarantee, disable cookie-authenticated mutation there. Bearer requests must not accidentally inherit a cookie fallback after an invalid bearer.
- CORS is an explicit origin allow-list, never wildcard with credentials. Use verified TLS/reverse proxies; do not advertise public wildcard binding as a secure deployment recipe. No GET performs a domain mutation or an external action. All sensitive responses use `Cache-Control: no-store`.
- The pinned native sign-in callback is only canonical `http://127.0.0.1[:port]/...` or `http://[::1][:port]/...`. It rejects `localhost`, app schemes and claimed HTTPS mobile callback URLs. PKCE support is not evidence that an iOS/Android client works.
- Existing browser sign-in is the first optional PWA path. E6.7 is Blocked until a supported callback path, target-device recovery, secure credential storage and device revocation are proven. If a generic callback/device-control extension is needed, it belongs at the existing host boundary, not in a parallel plugin auth service.
- Webapp sign-out and native-app credentials do not have identical lifetimes. A browser sign-out can invalidate its bound browser sockets while native-app sign-in survives. Never promise “logout revokes every device” without a verified host mechanism. Plugin hard revocation still prevents subsequent domain admissions under the revoked binding.

## 4. Proposed Wire Conventions and Limits

Everything in this section is a **project design value**, not an observed Hermes default.

| Contract | Proposed v1 value |
|---|---|
| Encoding/version | UTF-8 JSON; path major `/v1`; `schema_version: "personal.api.v1"` |
| IDs/time | Opaque case-sensitive IDs; RFC 3339 UTC instants; IANA timezone retained separately |
| JSON body limit | 256 KiB, except the separately gated binary upload route |
| Pagination | `limit` default 50, range 1–100; opaque cursor; no unbounded export through lists |
| Read timeout/polling | Client timeout 15 s; foreground poll every 5 s, idle 30 s; offline exponential backoff to 60 s with jitter |
| Idempotency key | UUIDv4 generated before submission; required for every proposed POST/PATCH command |
| Idempotency retention | Pending/unknown reservations retained until resolved; complete result retained 7 days after terminal settlement; key/digest tombstone retained another 90 days |
| Approval presentation | Fresh 256-bit random nonce; default expiry 5 minutes; single successful decision consumption |
| Changes retention | At most 7 days or latest 100,000 records per profile, whichever expires earlier |
| Snapshot | Immutable authorized projection at a committed watermark; 15-minute TTL; 100 rows/page; total cap 10,000 rows/10 MiB |
| Optional upload | 20 MiB/file, one file/request, 10 pending uploads/owner; completion TTL 1 hour |
| Optional artifact | Unreferenced staging expires after 24 hours; referenced retention explicit in metadata; no implied permanent retention |

The idempotency namespace is `(owner, profile, method, normalized route, key)`, stable across the same owner's verified cookie/native authentication paths. The original principal/auth context is retained for audit, not used to split deduplication. Digest the canonical validated command, resource revision and domain scope, not transport credentials. Use deterministic JSON canonicalization (RFC 8785) and SHA-256; reject non-finite numbers and ambiguous duplicate JSON keys. An exact retry returns the original receipt with `Idempotency-Replayed: true`, after checking the current caller's access; it never transfers the original caller's permissions. A changed digest returns 409 `idempotency_conflict`; an expired result with a retained tombstone returns 409 `idempotency_expired`, without execution. Keys must never be reused, including after tombstone expiry. The client reconciles before creating a new key; expiry is not permission to duplicate a side effect.

The database transaction reserves the command, updates domain state and writes changes/outbox together. Native dispatch and remote effects remain separate transactions: use a stable effect key and reconcile, not a claim of cross-system exactly-once execution. Pre-admission validation failures that create no reservation may be corrected with the same key; once reserved, any payload change needs a new key and applicable authorization.

Single-resource reads return `ETag: "<id>:<revision>"`. PATCH and state-changing commands against existing resources require exactly that strong `If-Match`; missing is 428, stale is 412. An exact idempotent retry is recognized before rejecting its now-old ETag, but only after current authentication/authorization. A write response is committed state, not proof that a native or remote effect finished.

```json
{
  "schema_version":"personal.api.v1",
  "request_id":"req_example",
  "data":{"id":"task_example","revision":3,"status":"ready"},
  "operation_id":null,
  "error":null
}
```

Lists put `{items, next_cursor, has_more}` in `data`; an ordinary list is not a cross-resource snapshot. Errors put `data: null` and `{code, message, retryable, field_errors?, recovery?}` in `error`. `message` is display text only; clients branch on codes. `recovery` contains an enum and authorized object references, not secrets or arbitrary navigation URLs. Log request/operation IDs with redacted metadata, never tokens, approval nonces, raw approval payloads or uploaded content.

| HTTP | Meaning/examples |
|---|---|
| 200 / 201 | Read or committed local change / created local object |
| 202 | Durable operation accepted; inspect its state; never “completed” or “delivered” |
| 400 / 422 | Malformed JSON/header / well-formed but invalid command fields |
| 401 / 403 | Authentication missing/expired / authenticated action forbidden |
| 404 | Missing or out-of-scope object; do not reveal foreign object existence |
| 409 | Idempotency conflict/expiry, already settled decision, invalid transition, unknown outcome requiring reconciliation |
| 410 | Expired snapshot/change cursor or approval presentation; fetch fresh authorized state |
| 412 / 428 | Revision mismatch / missing precondition |
| 413 / 415 | Size limit / unsupported media type |
| 429 | Rate/budget admission refused; honor `Retry-After`, do not switch credentials |
| 503 | Host identity, policy/storage, native adapter or draining state unavailable; fail closed |

## 5. Route Registry and Resource Shapes

Every route below is **proposed under B**. The host auth paths and canonical RPCs in other sections are not aliases for these routes. Reject unknown command fields. All reads require `personal.read` plus object/source permission; the table names additional mutation scope. No generic `tool_name + args` executor, arbitrary URL proxy, SQL endpoint or client-supplied filesystem path is exposed.

### 5.1 Discovery and read models

| Method/path | Request | `data` result |
|---|---|---|
| `GET /capabilities` | None; authenticated | Version, limits, transport/adapter flags and actual release gates |
| `GET /context` | None | Sanitized owner/profile refs, timezone, domain scopes, permission revision and current `policy:{id,revision,etag}` for authorized control callers; no host tokens |
| `GET /overview` | `date=YYYY-MM-DD`, `timezone=<IANA>` | `as_of`, task/reminder/approval/connection summaries, stale native projections |
| `GET /operations` | cursor, limit, status, optional object_ref | Authorized operation inventory, including pending/unknown connector syncs without a task |
| `GET /operations/{operation_id}` | None | Operation receipt described below |
| `GET /receipts/{receipt_id}` | None | Sanitized effect/delivery evidence described in section 10 |
| `GET /snapshot` | First page: none; later: `cursor` | Consistent snapshot page and final change cursor |
| `GET /changes` | `cursor`, optional `limit` | Durable changes and next cursor; required cursor comes from snapshot |

Illustrative **future** capability response; these true values describe a target deployment after its gates pass, not this repository today:

```json
{
  "schema_version":"personal.api.v1","request_id":"req_caps",
  "data":{
    "api_major":1,"plugin_id":"hermes-personal-agent",
    "contract_revision":"2026-11-06.design.1",
    "native_baseline":"90d6b98fd86d20981ee06ddd5b7d93e4320f26a4",
    "deployment_mode":"host_isolated","principal_adapter":"verified",
    "features":{
      "domain_reads":true,"domain_mutations":false,"controlled_writes":false,
      "change_polling":true,"domain_sse":false,"domain_websocket":false,
      "artifact_upload":false,"artifact_download":false,
      "canonical_session_attach":false,"native_mobile_sign_in":false
    },
    "limits":{"page_max":100,"json_body_bytes":262144,"upload_bytes":20971520},
    "release_gate":"blocked"
  },"operation_id":null,"error":null
}
```

`native_baseline` records compatibility evidence, not a claim that the running host matches; expose a separately verified runtime version when available. Flags are computed from tested host mode, configured authorization and adapter health. Clients must not infer enabled writes from successful authentication or endpoint discovery. No raw host home paths are exposed.

### 5.2 Domain objects and commands

| Method/path | Allowed command fields / query | Additional scope and result |
|---|---|---|
| `GET, POST /projects` | GET: cursor, limit, status. POST: `name, goal, context_scope, source_refs?` | POST `personal.projects.write`; 201 Project |
| `GET, PATCH /projects/{id}` | PATCH: `name?, goal?, status?` | PATCH same scope + If-Match; 200 Project |
| `GET, POST /tasks` | GET: cursor, limit, project_id, status. POST: `project_id, outcome, acceptance[], constraints, source_refs?, artifact_ids?` | POST `personal.tasks.write`; 201 Task in `captured`/`ready`, not automatic dispatch |
| `GET, PATCH /tasks/{id}` | PATCH: `outcome?, acceptance?, constraints?`; active material change invalidates affected intents | PATCH same scope + If-Match; 200 Task |
| `POST /tasks/{id}/start` | `reason?`; If-Match | Same scope, action admission checks; 202 Operation mapped to native worker/Kanban |
| `POST /tasks/{id}/cancel` | `reason?`; If-Match | Same scope; 202 Operation, task records `cancel_requested` separately from business status |
| `GET /tasks/{id}/attempts` | cursor, limit | Native refs, attempt state, result/receipt refs, known cancellation support |
| `GET, POST /commitments` | POST: `project_id?, content, promisor_ref, promisee_ref?, due_at?, timezone, source_refs[]` | POST `personal.commitments.write`; 201 Commitment |
| `GET, PATCH /commitments/{id}` | PATCH: `content?, due_at?, timezone?, status?, evidence_refs?` | Same scope + If-Match; 200; fulfillment needs evidence or owner instruction |
| `GET, POST /automations` | POST: `goal, trigger, timezone, destination_ref, stop_condition, source_refs?` | POST `personal.automations.write`; 202 Operation then Automation/native job mapping |
| `GET, PATCH /automations/{id}` | PATCH: `goal?, trigger?, timezone?, destination_ref?, stop_condition?` | Same scope + If-Match; 202 Operation; changed external authority re-evaluated |
| `POST /automations/{id}/pause`, `/resume`, `/cancel` | `reason?`; If-Match | Same scope; 202 Operation, native confirmation required before final state |
| `POST /action-intents` | Typed action described in section 6 | `personal.actions.prepare`; 201 Intent; prepares only |
| `GET /action-intents/{id}` | None | Authorized redacted intent, status, approval/operation references |
| `POST /action-intents/{id}/execute` | `intent_revision, payload_hash`; If-Match | `personal.actions.execute`; revalidate current exact grant/approval and policy; 202 new Operation or 200 existing execution receipt |
| `GET /approvals`, `GET /approvals/{id}` | List: cursor, limit, status | Current permitted approval projection; nonce only on authorized individual presentation |
| `POST /approvals/{id}/decision` | Decision described in section 6; If-Match | `personal.approvals.decide`; 200 Decision plus optional accepted operation ID |
| `POST /control/revoke` | `scope_type, target_ref, reason`; target-policy If-Match | `personal.control.revoke`; 200 revocation revision and affected operation refs |

Resource common fields: `id`, `schema_version`, `revision`, `created_at`, `updated_at`, authorized owner/profile references, and `source_refs`. Project adds `name, goal, context_scope, status, native_refs`. Task adds the command fields, business `status`, `execution_state`, `cancel_requested_at`, `native_refs`, `last_operation_id`, `acceptance_evidence_refs`. Commitment adds the command fields and `status`. Automation adds `status, native_refs, next_due_at, last_occurrence_ref, reconciliation_state`. Native refs are nullable and server-written; `stale_at` distinguishes a cached projection from a current read.

Reuse [04's business state machines](04-domain-data-and-memory.md). `cancel_requested` is an execution/control condition, not a fabricated successful business cancellation. Patch cannot assign `done`, `authorized`, `succeeded`, native run IDs or arbitrary acceptance evidence. Completing a task requires the acceptance service and evidence, not a worker's terminal message.

`constraints` is a typed object: `deadline_at?`, `data_scope_refs[]`, `allowed_connector_ids[]`, `max_attempts`, `budget_ref?`. Client values can narrow existing authority, never expand it. An automation `trigger` is a tagged union: `{kind:"once", at}` or `{kind:"cron", expression, dst_policy, misfire_policy}`. `destination_ref` resolves to an already verified route; no arbitrary email/phone/chat ID is accepted as a privileged destination. `stop_condition` is `{until_at?, max_occurrences?}` with at least one bound in v1. Schedule parsing/preview and native semantics are verified in E4, not reimplemented by HTTP.

### 5.3 Request, operation and concurrency examples

```http
POST /api/plugins/hermes-personal-agent/v1/tasks
Content-Type: application/json
Idempotency-Key: d10152d8-1a2f-4ea1-802f-9bdd97245899

{"project_id":"proj_example","outcome":"Prepare the weekly review","acceptance":["Include unresolved commitments and source links"],"constraints":{"data_scope_refs":["scope_project"],"allowed_connector_ids":[],"max_attempts":1},"source_refs":["src_owner_request"]}
```

```json
{
  "schema_version":"personal.api.v1","request_id":"req_create",
  "data":{"id":"task_example","revision":1,"status":"captured","execution_state":"not_started","native_refs":{},"last_operation_id":null},
  "operation_id":null,"error":null
}
```

This abbreviated response illustrates selected fields; the resource also contains the common fields and validated submitted fields. It is HTTP 201 with `ETag: "task_example:1"`. Starting it is a separate `POST /tasks/task_example/start`, new idempotency key, and `If-Match: "task_example:1"`:

```json
{
  "schema_version":"personal.api.v1","request_id":"req_start",
  "data":{
    "id":"op_example","revision":1,"kind":"task.start","object_ref":"task_example",
    "status":"accepted","phase":"awaiting_native_admission",
    "created_at":"2026-11-06T10:00:00Z","updated_at":"2026-11-06T10:00:00Z",
    "native_refs":{},"effect_refs":[],"receipt_refs":[],
    "cancel_requested_at":null,"error_code":null,"retryable":false
  },"operation_id":"op_example","error":null
}
```

HTTP 202 includes `Location: B/operations/op_example` expanded to the real base path. Operation status is `accepted | running | waiting_user | succeeded | failed | cancel_requested | cancelled | unknown_outcome`. Terminal means `succeeded`, `failed` or `cancelled`; `unknown_outcome` remains unresolved. A local intent/approval can succeed while its separate effect operation is only accepted. Re-read state after cancellation or loss of response. Retryability never overrides action policy or unknown-effect reconciliation.

For a concurrent edit, a stale ETag returns HTTP 412:

```json
{
  "schema_version":"personal.api.v1","request_id":"req_edit","data":null,"operation_id":null,
  "error":{"code":"revision_conflict","message":"The task changed. Reload it before editing.","retryable":false,"recovery":{"kind":"reload_resource","object_ref":"task_example"}}
}
```

## 6. Action Preparation, Human Decision and Revocation

### 6.1 Typed action and hash

`POST /action-intents` prepares a known action kind, never arbitrary connector arguments:

```json
{
  "kind":"message.send","connector_id":"conn_example","account_ref":"acct_example",
  "target_ref":"recipient_verified","payload":{"draft_ref":"draft_example","draft_revision":4,"attachment_ids":["artifact_example"]},
  "source_refs":["src_owner_request"],"task_id":"task_example"
}
```

The server resolves immutable recipient/account IDs, exact content, attachment bytes/hashes, data classes, delivery mode, visible costs/limits and authorization evidence. It computes an immutable `payload_hash` over a versioned canonical action including those facts and the native adapter operation, not just display text; mutable resource revision/status are not part of this action hash. Store the canonicalization version. An intent response includes `id, revision, kind, status, payload_hash, policy_revision, grant_ref?, expires_at, approval_ref?, operation_id?, redacted_preview`. Preparation does not send or silently create a standing grant. Kind-specific schemas are allow-listed; unknown kinds fail 422.

`GET /approvals/{id}` after access checks returns `id, revision, intent_id, intent_revision, payload_hash, policy_revision, expires_at, allowed_decisions, presentation_nonce, preview`. `preview` shows actual recipient/destination, exact material content or a reviewable artifact revision, data being shared, attachments, costs and relevant consequences. Lists/events never contain the nonce. The presentation nonce binds this verified principal/auth context, profile, approval, current intent/hash/policy and expiry; store only its hash. Multiple device presentations may exist, but the decision transaction settles the approval once and invalidates all its presentations.

### 6.2 Decision transaction

```http
POST /api/plugins/hermes-personal-agent/v1/approvals/appr_example/decision
Content-Type: application/json
Idempotency-Key: 23c3543c-3893-43d9-b324-445f6d703c44
If-Match: "appr_example:2"

{"decision":"approve_once","intent_id":"intent_example","intent_revision":3,"payload_hash":"sha256:<64-hex-digest>","presentation_nonce":"<one-use-secret-from-current-presentation>"}
```

Allowed decisions in v1 are `approve_once` and `deny`; no bulk approve, standing grant, `approved:true` or agent-generated approval. The nonce is not sufficient by itself: current host authentication and owner policy are required. A forwarded card, replayed button, bot reply or third-party statement cannot decide.

In one transaction: resolve current identity and policy; verify nonce/expiry/intent revision/hash; compare approval revision; record the immutable human decision; consume all presentations; update the intent and audit/change rows; enqueue only the authorized effect. A successful 200 response includes `{approval_id, decision_id, decision, intent_id, intent_status, operation_id}`. `approve_once` may return `intent_status:"authorized"` plus an accepted operation, never imply delivery. A repeated identical idempotency key returns that decision receipt without enqueuing again; a different key after settlement returns 409 `approval_already_settled`.

For an intent already covered by a valid grant, preparation still sends nothing. The explicit execution command is `POST B/action-intents/{id}/execute` with `personal.actions.execute`, Idempotency-Key, current intent If-Match and `{intent_revision, payload_hash}`. Revalidate the verified owner/profile, current exact grant or prior approval, expiry, target/data/cost restrictions, current policy and covered connector write path. Scope alone is not approval. An unresolved approval returns 409 `approval_required` and its authorized reference; denied/settled-incompatible intent returns 409, revoked authority 403 and unavailable policy/identity 503. The client cannot supply a grant or dispatch permit.

The approval decision's authorized enqueue and this execute route use the **same intent execution slot**, uniquely keyed by `(owner_id, profile_id, intent_id)`, in the shared admission service. The slot records the immutable action hash; resource `revision` is only an If-Match/CAS precondition, never part of slot identity. A state transition may increment revision but cannot allocate another slot. Material action changes require a new intent ID. A different HTTP command key or a race between the two paths cannot create a second logical effect. Authorized access to an already allocated slot returns its existing operation; provider dispatch retries retain that effect's stable key and reconcile uncertainty. Each effect still requires its current dispatch permit. Neither endpoint calls a raw tool as a shortcut.

`deny` makes the intent terminal `denied`; it creates no effect operation. A timeout/expired presentation is not denial and does not grant authority. Material recipient/content/attachment/cost changes create a new intent, invalidate the old approval, and require fresh evaluation. A denied intent cannot be revived by retries, another connector or a rewritten prompt. A new explicit owner instruction with relevant new authorization may support a new intent linked by `supersedes_intent_id`; third-party content cannot.

### 6.3 Revocation and in-flight truth

`POST /control/revoke` supports `scope_type: "grant" | "channel_binding" | "all_domain_writes"`, with a server-resolved `target_ref` and the current owner/profile policy ETag. Authorized callers obtain it from `GET B/context`, for example `policy:{id:"policy_example",revision:31,etag:"\"policy_example:31\""}`; they send that exact value in If-Match, never guess a revision. All three revoke scopes update that same governing policy resource and return its new ID/revision/ETag. The transaction atomically commits the new policy revision and stops new admissions. No endpoint here claims to revoke a host device token; that is an independently verified host operation.

Authorization admission and revocation serialize at a database transaction boundary, as in [06](06-plugins-mcp-and-security.md). Before outbound transmission the executor rechecks current policy and atomically claims an effect dispatch permit. If revocation commits first, no new dispatch permit is granted. If a permit commits first but nothing has been transmitted, cancellation is attempted and the state remains truthful. Already transmitted/accepted remote work may not be retractable: mark `cancel_requested` or `unknown_outcome`, reconcile, and report the remote receipt. Do not hold a database transaction across network I/O or promise a distributed atomic revoke/send boundary.

Read current persistent policy for every effect, including workers with frozen config and scheduled executions. If unavailable, refuse new effects with 503. No “fallback” raw MCP/shell/browser dispatch may bypass denial. Native approval presentation is adapted to this exact intent binding; if the host cannot correlate it safely, controlled writes remain blocked. The existing foundation's hooks/inventory are not this authorization system.

## 7. Native Conversation Transport, Not a New Chat Loop

### 7.1 Canonical WebSocket integration

For continuation of native CLI/TUI/Desktop/messaging-owned sessions, use the existing authenticated `/api/ws` and feature-detect the **canonical** `hermes-gateway-v1` protocol [H5, H6]. Use the host's documented credential/ticket flow for that listener. Do not copy private bootstrap tickets to remote clients or put long-lived credentials in generated URLs.

| Native canonical method | Relevant parameters and meaning |
|---|---|
| `runtime.describe` | `{}` → instance/profile/authority epoch, capabilities, supported session creation fields |
| `session.create` | `{request_id, source, ...supported_fields}` → durable stable session identity; repeat request ID reuses it for the same authenticated principal/profile |
| `session.resume` | `{session_id}` → authoritative snapshot and current control state |
| `prompt.submit` | `{session_id, submission_id, text}` → durable admission receipt, not finished inference |
| `prompt.receipt` | `{session_id, admission_id, include_result?}` → current admission and retained result |
| `prompt.cancel` | `{session_id, admission_id}` → retire queued input or interrupt started input |
| `session.interrupt` | `{session_id, execution_generation}` → generation-bound control |
| `session.steer` | `{session_id, execution_generation, text}` → correction receipt; queued is not consumed |
| `approval.respond` | `{session_id, execution_generation, prompt_id, choice}` → native pending approval only |
| `clarify.respond` | `{session_id, execution_generation, prompt_id, answer}` → native clarification, not another inference turn |
| `session.events.since` | `{session_id, last_sequence?, last_seen?, replay_epoch?}` → replay or snapshot-required indication |
| `prompt.resolve_unknown` | `{session_id, admission_id, execution_generation}` → acknowledge lost execution; never replay it |
| `session.mutate` | `{session_id, request_id, expected_revision, operation, payload, expected_generation?}` → native revision-fenced mutation |

Native admission status is `queued | started | unknown | terminal`, with `admission_id`, `ref:{profile_id,session_id}`, `sequence`, `outcome`, `authority_epoch`, `execution_generation`. It is not the domain operation enum. Keep their mapping explicit. Source/session-creation fields are policy choices, not identity proof. Attach only sessions the host authorizes; do not broaden messaging ownership merely because a task links them.

Canonical and legacy TUI-sidecar contracts have overlapping method names but different payloads. Generate/use the correct canonical types; do not assume all legacy RPCs or server requests are supported by the canonical listener. If using a legacy connection, negotiate `client.capabilities({server_requests:true})` before claiming to handle server requests, and answer unknown methods with JSON-RPC errors rather than silently approving. Native `approval.respond` is not interchangeable with a domain approval decision without the verified adapter binding.

Native replay events carry `type, session_id, payload, replay_epoch, seq` and optional `authority_epoch, execution_generation, admission_id`. Replay results include `events, latest_seq, last_sequence, epoch, replay_epoch, truncated, snapshot_required, count`, optionally `open_requests`. On epoch mismatch/truncation, recover a native snapshot and current pending controls. Viewers disconnecting does not mean a turn was cancelled. Never re-submit a lost acknowledged input with a new submission ID before checking its durable receipt.

### 7.2 Existing native HTTP API is a separate choice

The native API server already provides `POST /v1/chat/completions`, `POST /v1/responses`, `POST /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events`, `POST /v1/runs/{id}/stop`, `/steer`, `/approval`, `/clarify`, `/resolve-unknown`, and `GET /v1/capabilities` [H7]. It requires the routed profile's `API_SERVER_KEY`; authenticate and feature-detect there independently of dashboard plugin routes.

**API sessions are their own sessions.** These inference routes refuse a session owned by CLI/TUI/Desktop/ACP/messaging with HTTP 409 `permission_denied`. To continue such a conversation, attach through the canonical WebSocket instead. Do not build a mobile REST wrapper that starts a second agent over the same transcript.

Native runs support `Idempotency-Key` with their own contract: 1–255 visible ASCII characters; exact replay returns the original run with HTTP 202 and `Idempotency-Replayed: true`; changed payload gives 409; retention is 24 hours after the last status update. This is **different from proposed domain retention**. Native stop first reports `stopping`; only actual exit settles cancellation. Native run SSE is neither a domain change feed nor an artifact store.

## 8. Durable Domain Changes and Consistent Recovery

### 8.1 Snapshot protocol

Pollable JSON is the required correctness path. Domain state, its revision, an outbox entry where needed, and a monotonically ordered change row commit in the same plugin database transaction. This sequence is domain-owned; do not reuse a native token-stream sequence as a domain commit watermark.

`GET B/snapshot` materializes the authorized domain projection at one committed watermark `S`, with `snapshot_id`, `feed_generation`, `permission_revision` and an immutable pagination view. Use a transactional read/materialized snapshot, not independently paginated live tables. Each page has `rows:[{resource_type, resource}]`, `next_cursor`, `expires_at`; only the final page returns `changes_cursor` beginning strictly after `S`. Supported rows are projects, tasks, commitments, automations, pending approval summaries, authorized operations, connector summaries and artifact metadata. Include all unresolved operations, especially pending/unknown syncs not attached to a task, plus terminal operations updated within the last 7 days. `GET /operations` provides separately paginated authorized recovery history. Reinstallation or a second device discovers this state from the server, not from locally remembered operation IDs. Large source bodies/content remain separate authorized reads.

```json
{
  "schema_version":"personal.api.v1","request_id":"req_snapshot",
  "data":{
    "snapshot_id":"snap_example","feed_generation":"feed_example","watermark":817,
    "permission_revision":12,"expires_at":"2026-11-06T10:15:00Z",
    "rows":[{"resource_type":"task","resource":{"id":"task_example","revision":3,"status":"ready"}}],
    "next_cursor":null,"changes_cursor":"opaque-authenticated-cursor"
  },"operation_id":null,"error":null
}
```

Resource rows in examples abbreviate other mandatory fields. On first load, stage all pages locally, then atomically replace the cache; do not show a partially replaced snapshot as complete. If the snapshot exceeds its cap, return 413 `snapshot_too_large` and require an explicitly designed narrower projection, not silent truncation. An expired page returns 410 `snapshot_expired`; start over. A permission change invalidates every remaining page before its content is returned.

### 8.2 Change page and client algorithm

```json
{
  "schema_version":"personal.api.v1","request_id":"req_changes",
  "data":{
    "events":[{
      "schema_version":"personal.change.v1","event_id":"chg_example","sequence":818,
      "type":"task.updated","occurred_at":"2026-11-06T10:00:02Z",
      "resource":{"type":"task","id":"task_example","revision":4},
      "operation_id":"op_example","changed_fields":["execution_state"],"deleted":false
    }],
    "next_cursor":"opaque-next-cursor","has_more":false,"watermark":818,
    "permission_revision":12
  },"operation_id":null,"error":null
}
```

Events are **invalidation records**, not complete object payloads or inference deltas. Initial event vocabulary: `project.updated`, `task.updated`, `commitment.updated`, `automation.updated`, `approval.updated`, `operation.updated`, `connector.updated`, `artifact.updated`, `resource.deleted`. Optional hints use the same object refs; no approval nonces, messages, secret tokens or unrestricted connector payloads are broadcast.

1. Authenticate, check capability and permission revision, then obtain the full snapshot and its change cursor.
2. Poll changes from that cursor; drain bounded pages while `has_more` is true. Duplicate events are harmless by `event_id`/sequence; never roll back to a lower resource revision.
3. Commit received invalidations and the next cursor to local durable storage together. Refetch referenced resources under current access; keep an invalidation pending until a fresh object or tombstone is applied. A crash after advancing the cursor must not lose a required refetch.
4. A refetch can observe a newer revision than the event; accept it. A 404 removes the cached object without revealing whether it was deleted or became unauthorized. A transient failure leaves it visibly stale.
5. On 410 `cursor_expired`, `feed_generation_changed` or `snapshot_required`, clear/stage a replacement projection and restart snapshot. On 403 `permission_changed`, erase affected cached content immediately and recover only after fresh authorization. On 401 stop polling/mutations and clear sensitive in-memory state.

Cursors are server-authenticated opaque values bound to owner/profile, principal binding, permission revision, feed generation and last committed sequence. Clients cannot edit scope or lower the cursor to obtain unauthorized history. Deleted resources leave a minimal tombstone in the retained change window. A lagging client beyond that window must replace its snapshot. Restore/migration that changes feed lineage increments `feed_generation`; never reuse old cursor authority after restore.

Offline cache is device-local presentation data, not an authorization source. Default to memory-only for sensitive bodies/approvals; persistent cache requires platform protection and documented sign-out cleanup. Offline edits remain drafts. Do not queue approval decisions or automatic outbound sends for later submission. Reconnect first revalidates auth, policy, resource revisions and receipts; an unsent benign draft may then be submitted with its original stable request key.

### 8.3 Optional live accelerators

The internal `ctx.emit(event, payload)` bus publishes `<plugin-id>:<event>` and returns scheduled subscriber count. `broadcast_plugin_event(plugin_id, event, payload)` emits `plugin.<id>.<event>` over a live process-local client stream. Neither is a durable feed or delivery acknowledgment [H8, H9].

Only after separate tests may `GET B/events/stream` (SSE) or `B/events/ws` (WebSocket) be advertised. They carry sanitized “changes available” hints, not privileged command frames, and use the existing host auth/Origin boundary. They never replace `/changes`, require no new token issuer, and must not keep an unbounded buffer. In host-isolated mode, OAuth plugin-socket limitations, or failed principal/lifecycle tests, advertise them false and use polling. The host may lack a generic scoped live-delivery seam; document that as a blocker rather than importing private broadcast internals.

## 9. Artifacts and Real Native File Boundaries

### 9.1 Existing capabilities and limitations

Hermes's native API server supports inline images but **not uploaded document/file IDs**. The old `/v1/artifacts/*` browser-controller routes were removed. Neither is a generic artifact registry [H7].

The host Webapp's `POST /api/chat/file-upload` accepts multipart `file` and an optional profile selected through the host boundary. It stages a unique 0600 file under the resolved profile's uploads directory, returns `{ok, path, size, staged_upload?}`, and feeds the existing `file.attach` flow. The caller does not choose a server path; deleted profiles are not recreated. `POST /api/chat/image-upload` is a separate native image path. These routes are surface-gated; their availability on every listener is not assumed [H10].

Native `POST /api/files/ticket` produces route/resource-bound tickets for existing download/stream paths. At this pin, a download ticket lasts 60 seconds and permits up to three GET/HEAD requests; a stream ticket lasts one hour. They are process-local and have credential-specific sign-out semantics, not permanent file IDs or universal revocation guarantees [H11].

### 9.2 Proposed opaque artifact adapter

All artifact routes remain disabled until the native storage/attachment/read boundary is tested. A plugin artifact ID is **new plugin-owned metadata**, not an invented native `artifactfileID` capability. Proposed metadata:

```json
{
  "id":"artifact_example","schema_version":"personal.artifact.v1","revision":1,
  "filename":"weekly-review.pdf","mime_type":"application/pdf","size_bytes":14201,
  "sha256":"<64-hex-digest>","status":"ready","classification":"private",
  "task_id":"task_example","source_refs":["src_example"],
  "created_at":"2026-11-06T10:00:00Z","expires_at":"2026-12-06T10:00:00Z",
  "download_supported":true
}
```

The storage locator, profile home, staging descriptor and native path remain server-side. Client filenames are display labels, never paths. MIME is verified, size enforced while receiving, checksum verified at completion, and unknown active content is downloaded as attachment rather than rendered in the authenticated app origin. Block traversal/symlink escapes, cross-profile references, credential-file access, decompression bombs and deleted-profile resurrection. Retention cleanup honors task/reference policy and privacy deletion rather than pretending host staging is durable storage.

| Proposed route | Contract |
|---|---|
| `POST B/artifact-uploads` | `filename, mime_type, size_bytes, sha256, task_id?`; `personal.artifacts.write`; 201 `{upload_id, revision, expires_at}` |
| `PUT B/artifact-uploads/{id}/content` | Authenticated octet stream, declared length, upload ETag and same content digest; one whole file; bounded staging only; repeat identical content is idempotent |
| `POST B/artifact-uploads/{id}/complete` | Idempotency-Key + If-Match; validates bytes/hash and scope; 201 Artifact or 422; no partial file becomes ready |
| `GET B/artifacts/{id}` | Current authorized metadata only |
| `POST B/artifacts/{id}/download-ticket` | Idempotency-Key + If-Match; current read authorization; 200 `{url, expires_at, method:"GET"}` for a tested native resource ticket |

There is no resumable upload claim in v1. A failed/expired upload is reconciled, then restarted under a new upload identity. The content PUT is the exception to POST/PATCH idempotency keys: its identity is the server-issued upload ID plus immutable expected content hash; conflicting bytes get 409. Finalization must atomically claim the staged file for this owner/profile, preserve only a verified storage reference and create metadata/change rows. A scan or storage failure leaves a quarantined/failed upload, not an agent-readable artifact.

Returned download URLs must be a verified deployment/native route and short-lived resource ticket, never a long-lived session token or arbitrary remote URL. Ticket-response replay does not extend expiry; once expired the client requests a new ticket with a new key. If the native ticket route cannot serve a scoped artifact securely in that host mode, `artifact_download` remains false; do not create a broad filesystem proxy to fill the gap.

## 10. Connector and Plugin Contracts

### 10.1 Capability descriptor and native credentials

```json
{
  "schema_version":"personal.connector.v1","connector_id":"conn_example",
  "plugin_id":"reviewed-connector","plugin_version":"1.0.0","source_revision":"<reviewed-commit>",
  "account_ref":"acct_example","status":"read_only","auth_health":"connected",
  "operations":[{
    "kind":"message.send","input_schema":"personal.message-send.v1",
    "output_schema":"personal.effect-result.v1","mode":"write",
    "required_scopes":["provider.message.send"],"data_classes":["message_body","contact"],
    "destinations":["verified-provider-host"],"approval_policy":"exact_intent",
    "idempotency":{"mode":"native_key","retention_seconds":86400},
    "reconcile":{"supported":true,"by":"client_reference"},
    "cancel":{"supported":false,"phase":"none"},
    "receipt_level":"accepted","cost":{"currency":"USD","upper_bound":"0.00"}
  }],
  "sync":{"polling":true,"webhook":false,"cursor_schema":"provider-cursor.v1"},
  "limits":{"batch_max":1,"concurrency":1},"write_release_gate":"blocked"
}
```

Values above are illustrative, not claims about a real vendor. `status` is `disconnected | read_only | controlled_write | degraded`; `auth_health` is `connected | expired | revoked | unavailable | unknown`. Describe each operation separately; a read-capable account is not proof of write authority. `idempotency.mode` is `native_key | reconciliation_only | none`; record the actual provider retention, not the proposed domain retention. A source/tool declaring itself read-only is untrusted metadata until its semantics and alternate paths pass testing.

Use Hermes's existing MCP trust/tool filters, plugin enablement and native OAuth grants. Plugin OAuth declarations already support specified scopes/HTTPS hosts and host-owned token storage/refresh through `credentialed_provider_request`; declaration changes can require renewed sign-in. Do not add a vault, copy tokens into domain state, or start a secret refresh daemon [H12]. The pinned plugin OAuth CLI sign-in refuses gateway/cron/agent initiation, so mobile connection setup requires a supported host handoff rather than a fabricated OAuth URL route. Consent to connect and persistent access expansion still require applicable authorization.

### 10.2 Typed internal connector interface

The following is a **proposed plugin-internal protocol**, not native `ctx` methods and not a generic public RPC:

```text
describe(context) -> ConnectorDescriptor
health(context) -> ConnectorHealth
read(context, ReadCommand, cursor?) -> ReadPage
prepare(context, TypedAction, operation_id) -> PreparedEffect
execute(context, prepared_effect_id, dispatch_permit, effect_key) -> EffectResult
reconcile(context, effect_ref, last_receipt?) -> EffectResult
cancel(context, effect_ref, reason) -> CancelResult
```

`context` is server-owned: owner/profile/principal binding, account binding, current policy, data scope, deadline, budget admission, request/operation IDs. A dispatch permit is an opaque internal, single-effect authorization record, not a bearer token exposed to the client/model. The connector cannot expand its action, account, destination, data, cost limit or deadline.

`prepare` validates exact provider semantics and returns `prepared_effect_id, action_kind, canonical_payload_hash, resolved_target_refs, account_ref, required_scopes, cost_upper_bound, currency, expires_at, idempotency_capability, reconciliation_capability, cancellation_capability`. Preparation must be read-only externally. If a vendor's preparation itself writes/reserves/pays, model it as its own controlled effect before calling it. Persist no access token or gratuitous provider payload.

`execute` validates prepared hash/version and current permit, then sends at most one admitted effect attempt with the stable `effect_key`. Repeated uncertain calls must not generate a new provider idempotency key. If the provider has no safe key/reconciliation, mark `unknown_outcome` and wait for verified evidence or owner decision, never blind retry or connector substitution. Batch support is off initially (`batch_max:1`); later batches require per-item intent/permit/key/receipt and explicit partial-result semantics.

### 10.3 Result, reconciliation and cancellation

```json
{
  "schema_version":"personal.effect-result.v1","effect_id":"effect_example",
  "operation_id":"op_example","attempt_id":"attempt_example",
  "status":"accepted","provider_ref":"opaque-provider-message-ref",
  "receipt":{"id":"receipt_example","level":"accepted","observed_at":"2026-11-06T10:01:00Z","evidence_ref":"evidence_redacted"},
  "retryable":false,"reconcile_after":"2026-11-06T10:01:30Z",
  "cancel_supported":false,"error":null
}
```

`EffectResult.status` is `succeeded | accepted | denied | failed | unknown_outcome | cancel_requested | cancelled`. `receipt.level` is `submitted | accepted | delivered | read | reconciled`; these are evidence labels, not a mandatory progression. A provider accepting a send does not prove delivery/read. `succeeded` is allowed only when the operation-specific acceptance contract is met; provider/tool prose alone is not proof. `reconciled` records how uncertainty was settled and retains the actual outcome separately.

`CancelResult` includes `status: cancelled | requested | unsupported | already_terminal | unknown`, `effect_ref`, `observed_at`, `receipt_ref?`. `requested` never maps directly to domain `cancelled`. Reconciliation is read-only, scoped to the same account/target/effect; it cannot resend, switch account, widen search permissions or reopen a denied intent. If multiple remote matches are possible, preserve unknown/needs-review rather than guessing.

Proposed connector HTTP reads are `GET B/connectors`, `GET B/connectors/{id}` (the current authorized descriptor and ETag, also the refetch target for `connector.updated`) and `GET B/connectors/{id}/health`. `POST B/connectors/{id}/sync` takes `{scope_ref, cursor_ref?}`, requires `personal.connectors.sync`, Idempotency-Key and connector If-Match, and returns 202 Operation for a bounded read sync. These routes never accept credentials, provider URLs or arbitrary tool arguments. Webhook ingestion is out of the initial HTTP scope; a later adapter must verify provider signature/timestamp/replay identity, deduplicate before advancing cursor, and treat payloads as evidence, never owner authorization.

## 11. Offline, Fault and Security Acceptance Matrix

These are required future tests, **not tests run by this document change**. Use synthetic accounts and fake remote boundaries first; physical-phone/real-provider certification is a separate authorized step.

| Scenario | Required assertion |
|---|---|
| Lost create ACK, repeated tap, two devices, process crash | Same key/payload gives one domain command/effect; changed payload conflicts; receipt is queryable |
| Same owner retries through different cookie/native credentials | One owner/profile command reservation; current access checked, original actor audit retained, no duplicate effect |
| Valid prior grant, execute/approval race, approve → revision increment → execute with a new key | Prepare sends nothing; execution rechecks current grant; fixed owner/profile/intent slot returns the same operation/effect despite the new resource revision/key |
| Revocation after reading context policy ETag | Stale precondition refuses; fresh context supplies the authoritative ETag; no guessed policy revision |
| New device/reinstall, pending sync without task, connector change | Snapshot/operation list discovers unresolved work; connector item read restores descriptor |
| Crash between domain commit and native enqueue | Stable outbox/native correlation is reconciled; no second worker/job is blindly created |
| Crash after remote acceptance before local receipt | Unknown outcome persists; reconcile by exact effect key; no speculative resend |
| Domain/native idempotency window expired | Reconcile or explicit conflict; no claim of indefinite exactly-once semantics |
| Stale ETag and old approval nonce/hash | 412/410/409 or denial as applicable; no side effect |
| Forwarded approval, wrong owner/profile/issuer, bot or group participant | Identity/source cannot be promoted; foreign resources remain concealed |
| Approval accepted on device A while device B decides | One settled decision and effect; other presentation invalidated |
| Denied intent proposed through another tool/connector | Original denied terminal; alternate raw paths cannot execute the effect |
| Revoke commits before/after dispatch permit; remote already accepted | Verify transactional ordering and truthful cancellation/unknown state, not impossible remote rollback |
| Policy store unavailable; frozen worker config; safe worker skips plugin | Fail closed for controlled effects; no prompt-only enforcement fallback |
| Authenticated same-profile operator, separate profile, isolated host IPC | Document shared operator trust; prove profile separation and verified principal propagation |
| Invalid bearer plus valid cookie; CSRF/CORS/Host/Origin probes | No unintended fallback or cross-origin mutation; no credential leaks |
| Logout/device revocation, pending approval and socket | Apply actual host revocation semantics; domain admission remains denied; do not invent universal token revocation |
| Native mobile callback, app killed/backgrounded, network switch | Supported callback and secure credential handling demonstrated on each claimed device; otherwise E6.7 blocked |
| Snapshot concurrent writes, page expiry, ACL change, delete and restore | No mixed snapshot; cursor after watermark; revoked cache removed; generation reset requires replacement |
| Duplicate/out-of-order hint, missing events, cursor truncation, crash during refetch | Pending invalidations survive cursor advance; polling/snapshot recovers without executing commands |
| Hosted isolation and OAuth remote without sockets | Complete all read/change flows by bounded JSON polling; no SSE/WS requirement |
| Oversize/mismatched MIME/hash, symlink/traversal, secret path, deleted profile | No ready artifact or file leak; no client-controlled path opens |
| Expired file ticket, revoked access, interrupted upload/download | Reauthorize and obtain a new scoped ticket; no long-lived token in URL or broad proxy |
| Lying MCP read-only hint, scope expansion, rotated/revoked grant | Semantic operation gate and native consent remain authoritative |
| Native prompt replay, reconnect, stale generation, unknown admission | Same owner runtime, durable receipts and correct native snapshot; no parallel API-server turn |
| Stop voice playback / stop worker / cancel external send | Three distinct states; never infer external cancellation from stopped audio |

Release evidence records exact plugin/native SHA, host mode, credential mode, profile setup, transport, device/browser/OS, tested failure points and skipped cases. Unit/schema/static checks alone cannot certify deployment auth, network containment, remote receipts or phone behavior.

Supplementary baseline evidence: the existing upstream `test_dashboard_auth_native_flow.py` (20), `test_plugin_api_consent_gate.py` (7) and `test_plugin_host_route_auth.py` (4) passed 31/31 through the official per-file runner with a separate PM Python 3.14.9 environment and an isolated temporary HOME. These cover upstream stub-auth, consent and IPC regressions only. They do not implement/test this plugin's proposed API, verify a real identity provider or phone, establish trusted domain identity through IPC, or complete E0.6.

## 12. Work Packages and Exact Dependencies

| ID/title | Milestone/status | Narrow dependencies | Deliverable and release gate |
|---|---|---|---|
| E0.6 Verify Client Transport Contracts | M0; Backlog | E0.1/E0.2; use E0.4 findings without claiming all write paths complete | Pinned route/ctx/auth/RPC/isolation/file probes, host-principal adapter decision, generated contract fixture; no private/imaginary APIs |
| E6.5 Build Domain API and Change Feed | M2 optional; Backlog | E0.6; E1.1–E1.5; E2.1; E3.2/E3.5; E4.2–E4.4 | Typed REST/operation schemas, transactional command dedup/outbox/change feed, authorized consistent snapshot, polling plugin overview; enable only individually proven adapters |
| E6.6 Validate Client Recovery Flows | M3 optional; Backlog | E6.5; E6.2/E6.4; E8.1/E8.2 fault harness for these paths; artifact tests require E0.6 file evidence | Multi-device/offline/replay/expiry/ACL/isolation/cancellation suite; native session reuse; no required custom push or live sockets |
| E6.7 Validate Native Mobile Sign-in | M3 optional; Blocked | E0.6 auth findings; E1.1/E1.4/E1.5; E6.4; unblock callback and device-revocation host contracts before device certification | Prove supported native callback, PKCE, secure credential handling, actual revocation and physical-device recovery; otherwise keep native mobile feature false |

E0.6 is an independent optional-client lane whose planning milestone is M0; it does not block the channel-first M0/M1 slice, whose applicable E0 gates are E0.1–E0.5. E6.5 can implement and test read projections before a write adapter passes, but cannot enable controlled writes by declaring the API complete. E6.6 does not wait for all E8/M4; it requires only the named observability/fault harness. E6.7 discovery can run before E6.5 and must not gate browser/channel-first delivery. There is no dependency from M1 to any optional custom-client package.

Extend existing **E5.1** with operation descriptors, schema versions, actual idempotency/receipt/reconciliation/cancellation limits and health. Extend **E5.2** with typed prepare/execute/reconcile/cancel adapters, one read and one controlled-write synthetic vertical slice, per-effect admission and partial/unknown-outcome tests. Do not create new E5 IDs. The connector interface design can proceed with E0.6/E1.2; write enablement still requires E1.3/E1.4, E4.3/E4.4 and that connector's E0.4 path coverage. API implementation does not wait for every future connector.

Completing this bilingual design does not mark any implementation item Done. Implementation work is Backlog; E6.7 is Blocked for its explicit host/device gaps. Verify Project issue/item IDs before synchronizing these plans; documentation IDs are not proof that remote Project items exist.

## 13. Pinned Source References

- H1: [Dashboard plugin backend API documentation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/extending-the-dashboard.md).
- H2: [Plugin mount, runtime consent gate and hosted response behavior](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server_dashboard.py).
- H3: [Host auth routes, WS tickets and native callback validation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/dashboard_auth/routes.py).
- H4: [Dashboard middleware and host token boundary](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server.py).
- H5: [Canonical local sessions, operator sharing and sign-in lifetimes](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/gateway-local-sessions.md).
- H6: [Canonical session/replay models](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tui_gateway/contracts/canonical_sessions.py) and [admission/control models](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tui_gateway/contracts/canonical.py).
- H7: [Existing HTTP API, idempotency, session ownership and file limitations](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/api-server.md).
- H8: [Public PluginContext methods and internal event bus](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py) and [plugin broadcast helper](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_events.py).
- H9: [Desktop plugin REST/socket contract and limitations](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md).
- H10: [Webapp file upload](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/uploads.py) and [staged-upload ownership/layout](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/staged_uploads.py).
- H11: [Resource-bound file tickets and lifetime](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server_file_tickets.py).
- H12: [Plugin authoring and native OAuth grant contract](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md).
- H13: [Hosted HTTP admission carries an authentication boolean, not full domain identity](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_host_http_auth.py).
