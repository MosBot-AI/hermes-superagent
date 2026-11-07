# 35. Offline Worker Routing Fixtures

English | [简体中文](35-offline-worker-routing-zh.md)

Status: **Implemented offline precursor, not a live routing backend.** This advances E9.1 contract evidence and prepares constraint fixtures for E9.2/E9.3. It does not complete trusted context, enable automatic selection, or start live shadow mode.

## Scope and Reproduction

`personal_agent.routing_shadow.evaluate_shadow_fixture` filters a caller-supplied synthetic route inventory, then ranks the remaining candidates by an explicit preference order. No task text or model classifier is accepted. It performs no config read/write, credential resolution, provider call, worker launch, audit persistence, registration or backend switch.

Using the same Python 3.14 interpreter as the repository checker, run the included synthetic example from the repository root:

```bash
python scripts/check_routing_fixture.py experiments/routing/synthetic-shadow.json
```

Exit codes are 0 for an advisory comparison, 1 for an unqualified baseline, and 2 for invalid input. Input is strict UTF-8 JSON, at most 64 KiB, with duplicate object keys rejected. Errors do not echo the input path or body. This script is a development utility, not a new installed Hermes command.

The fixture schema is intentionally closed and versioned. The example gives all required fields. It allows at most 32 candidates; route IDs must be unique; preference order must name every candidate exactly once. Unknown fields, secret/route override fields, malformed booleans, invalid token bounds and unknown effort/capability names fail validation.

## Constraints and Baseline

Each candidate asserts its configured/available state, provider/model/endpoint/API identities, evidence reference, recipients, data scopes, region/locality, capabilities, context/output limits, requested effort and service-tier support. These are **fixture assertions, not verified facts**. A route ID is not a cryptographic identity or an authorization receipt. Provider endpoint binding, current capability evidence, policy revision and exact inventory identity must be supplied and revalidated by future trusted host integration; this evaluator does not certify them.

Filtering precedes ranking:

- The route must be in the permitted ID set, configured and available.
- All recipients must be allowed and the data scope must be declared. Unknown recipients or scopes fail closed. Remote execution cannot claim an empty recipient set; local-only requirements also reject declared outbound recipients.
- Required modality, tools and structured-output capabilities, region, context capacity including reserved output, and output limits must be satisfied. Required unknowns exclude the route.
- Provider/model/route/effort pins are exact. Unsupported effort is rejected, never clamped or replaced; `provider_default` is distinct from `none`.
- Requested service tier must match and be declared supported. No automatic paid upgrade is proposed.
- Hard budget or total-deadline requirements reject every candidate because this slice implements neither reservation nor execution enforcement.

The explicit baseline is checked against the same constraints. If absent or excluded, the report is blocked and returns no suggestion, even when another candidate is feasible. This prevents a recommendation being presented as a qualified shadow run after an invalid baseline. No empty native route is emitted and no arbitrary parent route is inherited. There is no fallback execution or escalation plan.

## Report and Trust Boundary

The report contains policy/capability references, baseline/suggested route IDs, the suggested requested-effort enum, and stable exclusion reason codes. Provider/model/endpoint details, exact pins, task text, credentials and free-form explanations are omitted. IDs must be caller-supplied **non-sensitive opaque references**: syntax validation is not automatic redaction, and must not be used to sanitize private identifiers or URLs. The script prints the report only; it does not save an audit trail.

Every result explicitly has `execution_authorized: false`, `live_routing_enabled: false`, and `quality_validated: false`. Actual route, effective wire effort, usage and cost are null, never inferred from capability claims or counted as zero. `advisory` means only that the synthetic baseline passed the fixture checks. It does not establish approval, runtime safety, live availability, quality, success rate, savings or provider compatibility.

## Pinned Native Contracts

`tests/contracts/test_worker_routing_contracts.py` uses the exact Hermes commit in `compatibility.json`. A temporary test-only plugin is loaded through the real native plugin manager. Schema, registration, provider dispatch and route resolution are real; the credential resolver is replaced by an in-memory recorder before any credential reads. No child or model request runs.

Covered boundaries include deterministic schema snapshots, registration/unload, reserved fields omitted from the provider payload, undeclared/invalid parameters refused before dispatch, unknown route keys dropped, per-task refusal/exception without canceling a valid sibling, selected unavailable/missing backend refusal, unknown effort rejection, session backend pin precedence, internal caller bypass, and explicit `fallback_providers: []` versus inherited chains. Recorded route fields are not final wire metadata or proof a fallback was executed.

Not covered: hosted-plugin IPC, actual worker construction/background delegation, cron/Kanban/public lifecycle routes, cross-profile behavior, full save/new-session/resume schema transitions, effective provider encoders, live usage/cost, cancellations, budget races or trusted owner/authorization context. No provider capability or quality benchmark is claimed. E9.1 remains partial and E9.2–E9.6 runtime gates remain open. See [the routing design](11-worker-model-routing.md) and [roadmap](08-roadmap-and-acceptance.md).

## Verification

Run the normal repository checker with the pinned Hermes checkout and its test interpreter, as documented in the [README](../README.md#development-checks). The aggregate includes the new unit and native contract files, Ruff, formatting, ty and bilingual document checks. Synthetic negative fixtures cover hard constraints, exact pins, invalid baselines, malformed input, audit minimization and unsupported runtime guarantees. Tests are network-guarded and use no actual provider/model.
