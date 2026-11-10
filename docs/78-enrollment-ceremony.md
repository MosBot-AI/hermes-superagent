# 78. Fenced Enrollment Ceremony Evidence

English | [简体中文](78-enrollment-ceremony-zh.md)

## Implemented scope

`personal_agent.enrollment_ceremony` adds an unwired, default-denied coordinator and a separate SQLite challenge store. It is preparatory E1.1 work, not a production owner issuer. Existing `EnrollmentStore` schema and pending/revoked states are unchanged. No CLI, slash command, model tool, HTTP route, production storage opener or host adapter invokes this module. No ReadGrant, private read, canonical Bot binding or controlled write is enabled; Issue #14 remains open.

`enabled=True` alone is insufficient: a missing independent authority denies before inspecting either store or importing a host. The only successful tests use a synthetic trusted adapter. Frozen Python records and their constructors are not authentication or protection against malicious same-process code.

## One bounded ceremony

The deployment operator's existing pending enrollment fixes the prospective owner/profile/enrollment, actor, transport/receiving account and exact proposed read scope. It is not self-enrollment and does not adopt existing local tasks.

1. An independent authority consumes an opaque, one-shot live observation handle and holds host invalidation fences. It supplies exact `ChannelObservation` fields: actor/receiver/profile, session, host incarnation, route/device revision, direct-human DM provenance and current device-revocation state. Missing, group, bot, forwarded, internal or revoked observations refuse.
2. Under that host fence, the existing enrollment transaction verifies current enrollment/policy revision and epoch and excludes concurrent revoke. A separate challenge transaction samples trusted time after its lock wait, stores the exact binding and a five-minute validity interval, and records an issued event. The random challenge ID is a locator, not bearer authority.
3. Confirmation requires a fresh independent handle proving explicit confirmation of that exact challenge. Under the same lock order, compare every stored observation and enrollment/scope field with current values. Re-sample trusted UTC after waiting for the challenge lock. Only an exact match in the half-open validity interval records `confirmed`; a rejected attempt reaching this stage records `consumed` and a denied event.
4. Either terminal state rejects another attempt, even with a new handle. Historical inspection reports only ID/state and `authority: false`. Confirmed evidence never activates an enrollment or authorizes a subsequent operation. Any future operation still requires current independent host and enrollment authority.

Audit events contain challenge ID and outcome, not principal/receiver IDs, scope, raw arguments or adapter exceptions. The challenge row itself contains private identity and proposed-scope metadata; caller-owned SQLite access must be private. This slice supplies no production opener, encryption, cleanup policy or authenticated audit log. Capacity is bounded at 10,000 rows with no automatic eviction. Foreign/modified/temp schemas and caller-owned transactions are refused.


A confirmation for another challenge ID or owner/profile/enrollment key is refused before changing that challenge. The host handle may be consumed, but another enrollment's pending challenge must not be burned. Only an attempt admitted to its own exact challenge can persist a denied/consumed outcome.

## Failure and concurrency semantics

Lock order is **host invalidation guard → enrollment `BEGIN IMMEDIATE` → separate challenge `BEGIN IMMEDIATE`**. Do not prompt, call a model, contact a transport or dispatch workers while holding these locks. Independent challenge connections serialize competing confirmations. Current policy/revoke is checked under the existing enrollment lock, not inferred from a cached pending row.

There is **no atomic commit across the two databases**. The inner challenge commit may survive a later enrollment commit or host-guard exit failure. The coordinator reports `outcome_uncertain`, returns no successful result and never compensates by deleting evidence or reviving a consumed challenge. Inspection may then report `confirmed`, but that is historical evidence, not proof that the caller received success or current authorization.

A challenge audit/commit failure rolls back that database transaction. The independently consumed host handle stays consumed, so retry requires a fresh trusted observation/confirmation. A failure before current-policy admission can leave the database challenge pending; the API does not falsely claim durable challenge consumption. Unknown exceptions are redacted. Database rollback and restored copies do not establish live host freshness, and evidence must never be used as a reusable permit.

## Current host boundary and verification

Current compatibility pin: Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`. Unlike the historical sources in [18](18-owner-entry-and-read-authorization.md)/[23](23-host-command-context-experiment.md), this host has `gateway.session_identity.RoutingIdentity` with transport/runtime profiles and a live adapter weakref. It remains a wire-invisible dynamic source observation. The public plugin command context does not provide the independent one-shot confirmation, current device/session/route fences or owner issuer required here. The plugin does not import private routing identity helpers or turn a serialized source into authority.

Native tests exercise actual source serialization and public command invocation, demonstrating loss of the dynamic identity and refusal of command-supplied approval claims. Unit tests exercise real challenge/enrollment transactions with synthetic trusted guards, exact mismatches, expiry, one-shot outcomes, schema faults and both cross-store failure windows. Run the full repository checker and pinned native contracts; focused synthetic success does not establish secure real ingress or a production enrollment ceremony.
