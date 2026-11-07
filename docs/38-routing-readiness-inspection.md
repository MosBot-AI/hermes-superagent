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

The command still reads a local configuration document that may contain secrets. It minimizes its output; it is not a replacement for host secret storage, filesystem permissions, log redaction or trusted code review. The registration binds the current resolved profile and checks it before and after reading. Unload closes the retained inspector. No audit file or persistent snapshot is written.

## Verification and Limits

Unit tests cover malformed declarations, literal route shapes, environment references, requested/effective effort distinctions, fallback states, ignored-tier/timeout warnings, closed error codes and output minimization. Native contracts exercise real registration and top-level CLI dispatch, fresh saved-config reads without cache mutation, malformed documents, unload/profile changes, non-file-backend refusal, unknown backend failure, frozen/safe-worker refusal and the pinned default backend's service-tier behavior. Tests use synthetic temporary homes and a network guard; no real account, provider request or socket bypass is used.

Run the aggregate checker described in the [README](../README.md#development-checks), using the pinned Python 3.14 environment. Actual worker execution, hosted-plugin IPC, live backend health, provider encoding, permissions, budgets and production configuration acceptance are not tested by this command. Do not use its successful exit code as admission to enable routing. Continue through the [routing design](11-worker-model-routing.md) and [roadmap](08-roadmap-and-acceptance.md) gates.
