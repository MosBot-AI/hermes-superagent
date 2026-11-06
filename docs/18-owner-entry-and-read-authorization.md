# 18. Owner Entry and Read Authorization Foundation

English | [简体中文](18-owner-entry-and-read-authorization-zh.md)

**Implemented: a deterministic internal read evaluator and a non-personal access diagnostic. Not implemented: a production identity issuer, owner enrollment, live private reads, live grant/policy authority, Primary Bot binding or controlled writes.** This advances E0.7 and preparatory portions of E1.1/E1.2; it does not complete their release gates. The [Primary Bot design](15-primary-bot-binding.md) remains gated.

The baseline is Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. No API Key is needed to test this slice. Missing trustworthy host contracts cannot be repaired by supplying a model credential.

A separate [review-only host-context experiment](23-host-command-context-experiment.md) records a prototype transport-observation seam and unresolved integration gates. It is not applied to the compatibility checkout or installed with this plugin, and does not change the denied production behavior described here.

The follow-on [pending enrollment/policy core](26-pending-enrollment-policy.md) now persists prospective administrative records only. The live owner enrollment, current authenticated policy and grant issuance gaps described here remain open.

## 1. Why Channel Identity Is Not Yet Enough

The documented slash-command callback supplies `source`, `platform`, `session_id` and `session_key`. `source` is adapter-derived and has stable user/chat IDs; the host documentation explicitly says it is transport identity, not an authorization grant [I1]. This is a better candidate input than a name or command body, but it does not provide every required boundary.

The same runtime profile may receive traffic through multiple transport Bots. Public `SessionSource.profile` identifies runtime routing; the receiving adapter is held in a private, dynamically attached `_transport_adapter_ref` and resolved by private host code [I2]. The plugin does not import or use those internals. Hosted IPC serializes declared dataclass fields and drops that dynamic reference [I3]. Two callbacks with identical public actor/chat/profile fields can therefore have different receiving Bots.

Allowlisting only user/chat IDs would silently grant access through both routes. That is incompatible with [15's selected-Bot boundary](15-primary-bot-binding.md). Private task reads and binding remain denied until a supported receiving-transport/account contract is available. A profile label, local CLI operator, authenticated HTTP boolean or title matching `Bot Chat` does not fill the gap.

## 2. Runnable Diagnostic

The plugin registers only this new non-personal slash diagnostic:

```text
/personal-access
/personal-access status
```

The local CLI equivalent has no transport source:

```bash
hermes personal-agent access
```

It returns JSON with `schema_version: personal.access-diagnostic.v1`, `status: blocked`, `decision: deny`, a bounded reason code, an `actor_observation` containing only booleans/platform category, missing-contract names, and both `protected_reads_enabled` and `primary_binding_enabled` false. A successful diagnostic command is not successful authorization. The CLI can exit successfully because the diagnostic itself ran, while its payload remains blocked.

There are no private IDs, profile paths, account labels, task contents, tokens or raw command arguments in the output. It does not read configuration, task storage or personal data, create sessions, start a gateway, mint tickets, bind a Bot or send a separate message. The native host presents the ordinary command result; this is not a durable delivery receipt.

Only an empty argument or `status` is accepted, with a 32-character input bound. Claims such as `--owner`, `approved` or arbitrary JSON are invalid. Missing source returns `source_unavailable`. CLI/Desktop/local and untested platforms return an unavailable/unsupported result rather than a default owner.

For a recognizable Telegram DM candidate, the observer checks matching platform, exact boolean non-bot/non-relay/non-rejected-route signals, no thread/group scope, and matching positive decimal user/chat IDs. It handles public attribute projections, including hosted IPC Records, instead of requiring a concrete host class. This recognizes a shape, **not authenticity**. Even a perfectly shaped source returns `receiving_transport_unverified`; it never creates a verified context. Forwarded/internal provenance is not fully present in the callback, so the diagnostic cannot certify a direct owner instruction.

The only model tool remains `personal_agent_status`. Status now separates the implemented evaluator from the absent production context issuer and disabled private reads. No task tool, data-reading slash command, HTTP route or mutable policy command is added.

## 3. Pure Internal Read Evaluator

`personal_agent.authorization` defines frozen, slotted internal records:

| Record | Meaning |
|---|---|
| `VerifiedReadContext` | Already independently verified owner/profile, transport/receiver, principal/session, policy revision/epoch and owned task IDs |
| `ReadGrant` | Exact identity and read scope, resource IDs, trusted current revocation state and UTC validity interval |
| `ReadRequest` | One operation, target, resource-ID tuple and data scope |
| `ReadDecision` | Only `allowed` and a stable reason code |

These Python objects are **not authentication proof or a sandbox**. Arbitrary in-process code can construct or alter them. No production function in this slice issues VerifiedReadContext, imports one from JSON, enrolls an owner or supplies a live grant. The diagnostic does not call the evaluator with guessed identities. Allow results are demonstrated only with synthetic fully specified internal fixtures.

`evaluate_read` takes explicit current policy revision, current epoch and UTC time from its future trusted caller. It performs no I/O or clock lookup. Validation rejects malformed or missing fields, subclasses/uninitialized records, mutable ID containers, unknown operations, wildcards, invalid times and inconsistent scopes. Opaque IDs are 1–128 ASCII letters/digits or `._:-`; ID tuples are unique and bounded to 1,024 elements. Revisions/epochs are exact nonnegative integers through the signed 64-bit maximum, not booleans.

All six identity components must match the grant: owner, profile, transport, receiving transport account/Bot, principal and session. Both context and grant revisions/epochs must equal the current trusted values. Revoked grants deny. Times must be exact built-in UTC datetimes, with `not_before <= now < expires_at`; no timezone guessing or numeric-time coercion occurs.

Only two operations exist in this evaluator:

- `personal.tasks.read` with `tasks.summary`, targeting either an exact nonempty set of owned task IDs or the explicitly named `own_inbox` collection with no IDs. An exact request may be a subset of its exact grant, but every ID in the grant must independently belong to the context. Whole-inbox access is restricted to that exact owner/profile and is not a global SQL permission.
- `personal.primary_binding.inspect` with `primary_binding.metadata`, targeting that profile's binding metadata without resource IDs. It is not binding creation, confirmation, recovery or activation.

There is no implicit conversion between targets, no write scope, no delegated authority and no broad wildcard. A future adapter must apply the approved projection and owner/profile filtering to its resource query; the evaluator does not fetch or redact records itself. `tasks.summary` is intended for a minimal task projection, not full details, source bodies, secrets or arbitrary attachments.

## 4. Current Policy and Race Boundaries

The evaluator checks supplied snapshots; it does not persist or prove their freshness. It is not E1.4 hard revocation, a transaction admission record, a grant issuer or an execution engine. The future domain read must obtain current identity/policy/revocation and its authorized resource snapshot consistently. A caller cannot make a stale cached policy current merely by copying its revision into both inputs.

No permission decision is reused to authorize a later mutation or another scope. External execution still requires the separate authorization commit and effect/reconciliation protocol in [06](06-plugins-mcp-and-security.md). A returned internal allow is not proof that an action occurred, data was delivered, or all Hermes paths are protected.

The existing explicit local task CLI remains a separate trusted-local-operator feature. It does not acquire verified owner status through this evaluator, and the new diagnostic does not expose that inbox to a channel.

## 5. Minimum Generic Host Contract Needed Next

A supported command/HTTP adapter needs a **host-issued, server-derived context**, not another plugin login service. Exact API naming is an upstream design decision; no such universal accessor is claimed to exist at this pin. Its minimum evidence must distinguish:

1. Authenticated actor and issuer, actor kind, direct/forwarded/internal provenance, and current session/credential authority.
2. Receiving platform account/Bot and transport profile, separate from the executing runtime profile and verified host authority observation.
3. Provenance of routing/profile scope that cannot be overwritten by command text, request JSON, headers or a peer-supplied record.
4. Versioned propagation through in-process and isolated-host boundaries, preserving the same guarantees or explicitly marking missing evidence.
5. Current owner binding and plugin policy lookup by the adapter before each protected read. Host authentication alone is not that binding.

The plugin must fail closed on missing or unsupported context. No private adapter import, environment fallback, same-title match, first-message self-enrollment or local CLI credential minting is an acceptable workaround. Canonical discovery through the existing Desktop `host.profileRoutes()` / `host.requestProfile()` is a useful supported observation path [I6], but it does not itself supply domain owner grants.

## 6. Tests and Release Interpretation

Unit tests cover strict types/immutability, exact identity/scope/ownership, wrong receivers/sessions, policy/epoch changes, revoked/expired grants, malformed time, forbidden writes and redacted decisions. Source-observer tests include missing, malformed, group/thread, bot, relay and mismatched contexts.

Pinned-host contracts exercise real plugin registration/dispatch/reload/unload and serialization behavior. They show the lost receiving-adapter reference rather than pretending it survives. Injection tests exercise the native resolver and quick/plugin dispatch sink for `allow_gateway_control=False`; they do not exercise the full inbound pipeline. Direct callback fixtures alone are not proof of a secure ingress path. Hosted HTTP's admission boolean remains insufficient [I4]. No real personal account or production binding is tested.

Run the [full repository checker](../README.md#development-checks) at the tested commit. E0.7 remains partial, E1 owner enrollment/current authenticated-policy admission remains unimplemented, and Primary Bot/read/write release gates stay closed. Future connection setup and any persistent access must use the authorized native secure flow; do not ask the user to paste secrets into chat.

## 7. Pinned Evidence

- I1: [Public slash context and authorization caveat](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#L1796-L1816).
- I2: [Receiving adapter attachment](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/platforms/base.py#L4751-L4754) and [private transport/runtime resolution](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_identity.py#L109-L121).
- I3: [Host IPC serialization](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_host_wire.py#L132-L164).
- I4: [Hosted HTTP admission marker](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_host_http_auth.py#L17-L23).
- I5: [Native command dispatch](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/run_inbound_hooks.py#L262-L301) and [injection command-control flag](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/platforms/event.py#L176-L185).
- I6: [Desktop route-aware host APIs](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md#L1446-L1514).
