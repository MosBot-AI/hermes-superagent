# 38. Saved Routing Readiness Inspection

English | [简体中文](38-routing-readiness-inspection-zh.md)

Status: **Implemented read-only native CLI diagnostic.** This extends the [offline routing precursor](35-offline-worker-routing.md) with inspection of saved local delegation declarations. It does not implement a routing backend or qualify a live shadow baseline.

## Entry and Scope

In an ordinary in-process Hermes installation with this plugin enabled, run:

```bash
hermes personal-agent routing inspect
```

The existing `personal-agent` CLI registers this subcommand in both `read_only` and `local_tasks` modes. There is no new slash command, model tool, HTTP endpoint, backend registration or activation setting. No arguments can select another profile, model, endpoint or configuration file. Generic status advertises the diagnostic without reading configuration.

The inspector uses the host-selected local `FileBackend` to read the active registration's saved user-layer document. It does not merge defaults or managed overlays, expand environment references, resolve model aliases or credentials, load the selected delegation backend, inspect another profile, launch workers, or call any model. It does not modify configuration, task/memory storage or the routing selection. Ordinary Hermes startup remains host-owned, including its existing config/bootstrap behavior; the inspector does not claim to suppress all host startup logs or side effects.

A selected remote/custom configuration backend is refused before reading its document. The inspector does not open a local shadow file as a workaround. Managed workers, including ordinary frozen-config workers and safe workers, are refused before reading the profile. A changed profile, unloaded callback, unavailable host API, malformed document or read failure returns a bounded failure. Missing/empty local user configuration is reported as undeclared settings, never a usable fixed baseline.

## What the Report Means

`scope` is always `saved_user_config_only`. `status: ok` and exit code 0 mean that saved declarations were inspected, **not that execution is ready**. A blocked diagnostic exits 1. Syntax/argument errors follow the host CLI parser. Every report keeps `execution_authorized`, `shadow_ready`, `automatic_routing_ready`, and `plugin_live_routing_enabled` false. The last field describes this plugin, not whether another installed backend might already route workers.

Reported route shapes distinguish explicit provider/model or endpoint/model declarations from parent-dependent, profile-dependent, backend-defined, and unspecified/unresolved forms. These are literal configuration shapes, not predictions of which credential resolver branch or actual route the host will use. Provider/model/endpoint identity and capability validation remain unperformed.

Warnings highlight useful pinned-host distinctions:

- A saved main-agent model alone does not prove a worker pin. Parent routes and existing session backend pins are not observed.
- Empty `fallback_providers: []` is distinguished from missing/null, populated and malformed declarations. No effective fallback chain is certified. Profile/custom backends can replace these fields.
- A recognized requested reasoning effort is shown separately from unknown effective wire effort. Bespoke mappings remain uninspected; a declared disabled value does not prove the provider can disable thinking.
- The pinned default backend drops `delegation.service_tier`; the diagnostic does not present it as a real speed or pricing setting. Custom backend semantics remain unknown.
- `child_timeout_seconds` is an inactivity timeout, not a total task deadline.
- Request overrides and inline credential fields are flagged by presence only. Their values are never copied or evaluated.

The report lists remaining unknowns: current session/backend state, credential validity, actual endpoint/recipient scope, capabilities, effort encoding, service tier, fallbacks, usage/cost, authorization and budget/cancellation enforcement. The target Hermes commit is reported, but the running host commit is not verified. E9.1 remains partial; trusted context and E9.2–E9.6 runtime gates remain open.

## Privacy and Lifetime

Output is constructed from fixed classifications, reason codes and recognized effort enums. It does not include caller-supplied provider/model/backend/profile names, URLs, API modes, paths, secret values, hashes, arbitrary field names or exception details. Unknown nested settings and fallback entries are not recursively inspected. Unlike the offline fixture report's caller-supplied opaque IDs, this diagnostic emits no raw identity references.

The command still reads a local configuration document that may contain secrets. It minimizes its output; it is not a replacement for host secret storage, filesystem permissions, log redaction or trusted code review. The registration binds the resolved profile. Both commands check that profile and the registration before reading, after reading and after evaluating the report. They discard the result if the profile changes or the plugin unloads during the operation. No audit file or persistent snapshot is written.

## Saved Capability Registry

Use `hermes personal-agent routing inventory` to validate the saved registry and see its route count. Supply `--route synthetic-text` to show the capability observations for one exact, case-sensitive route ID. This diagnostic shares the saved-user-layer, profile and unload checks above. It uses the canonical `settings` location shown below.

```yaml
plugins:
  entries:
    hermes-personal-agent:
      settings:
        routing_inventory:
          schema_version: personal.routing.registry.v1
          routes:
            synthetic-text:
              binding:
                provider: synthetic-provider
                model: synthetic/text-v1
                account_ref: synthetic-account
                api_mode: synthetic-mode
                transport: https
                endpoint_ref: synthetic-endpoint
                recipient_scope_ref: synthetic-recipient
                data_scope_ref: synthetic-scope
              evidence:
                synthetic-observation:
                  source: native_contract_test
                  observed_at: "2026-11-16T12:00:00Z"
                  valid_until: "2026-11-17T12:00:00Z"
              capabilities:
                text: {state: supported, evidence: synthetic-observation}
                image_input: {state: unsupported, evidence: synthetic-observation}
                context_tokens: {state: supported, evidence: synthetic-observation, value: 8192}
                health: {state: unknown}
```

Each route declares its complete binding. Keep account, endpoint, recipient scope and data scope as opaque references. Route IDs, evidence references and binding labels use 1–96 ASCII letters, digits, periods, underscores or hyphens and start with a letter or digit. Model identifiers can also contain slash or colon separators and have a 128-character limit. Transport is one of `in_process`, `local_process`, `local_http` or `https`. Use Hermes credential storage for keys. The inventory cannot verify the referenced identities, entitlements or privacy scope.

The registry holds up to 64 routes and up to 64 evidence records per route. Evidence belongs to its route and declares a source category (`provider_documentation`, `account_configuration`, `native_contract_test` or `operator_observation`) and a quoted UTC observation/expiry pair at second precision. Each `supported` or `unsupported` fact refers to one evidence record. The observation time is inclusive and expiry is exclusive. Expired or future observations project to `unknown`, with a freshness reason. Omitted facts and explicit `unknown` are equivalent.

Presence facts are `text`, `image_input`, `audio_input`, `tool_calling`, `structured_output`, `reasoning_effort`, `reasoning_token_budget`, `reasoning_toggle`, `reasoning_disable`, `service_tiers`, `cache_metering`, `usage_metering` and `pricing`. Pricing records evidence provenance. A supported `context_tokens` or `output_tokens` fact supplies a positive integer up to one billion. A supported `health` fact supplies the last observed `available`, `degraded` or `unavailable` value.

The `personal.routing.inventory.v1` report returns the declared registry version and route count. Exact lookup also returns fixed capability names, evidence categories, freshness states and recognized current values. The report omits route IDs, binding values, evidence references and timestamps. Missing inventory reports `not_configured`. An invalid record blocks the entire registry with a fixed reason code. Exact lookup of a missing route also exits 1. The readiness and execution flags stay false even with current evidence. Registry entries are local operator declarations.

## Verification and Limits

Registry tests exercise capability states, observation/expiry boundaries, route-local evidence and redacted failures. Offline integration on Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` exercises registered CLI dispatch against the real local configuration backend and refuses use after unload or with a non-file backend. The [native routing contract tests](../tests/contracts/test_worker_routing_contracts.py) exercise the pin's delegation provider registry, route resolution and session schema behavior.

Unit tests cover malformed declarations, literal route shapes, environment references, requested/effective effort distinctions, fallback states, ignored-tier/timeout warnings, closed error codes and output minimization. Native contracts exercise real registration and top-level CLI dispatch, fresh saved-config reads without cache mutation, malformed documents, unload and profile changes during both reading and evaluation, non-file-backend refusal, unknown backend failure, frozen/safe-worker refusal and the pinned default backend's service-tier behavior. Tests use synthetic temporary homes and a network guard; no real account, provider request or socket bypass is used.

Run the aggregate checker described in the [README](../README.md#development-checks), using the pinned Python 3.14 environment. Actual worker execution, hosted-plugin IPC, live backend health, provider encoding, permissions, budgets and production configuration acceptance are not tested by this command. Do not use its successful exit code as admission to enable routing. Continue through the [routing design](11-worker-model-routing.md) and [roadmap](08-roadmap-and-acceptance.md) gates.
