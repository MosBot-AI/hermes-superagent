# 11. Worker Model and Reasoning-Effort Routing Plugin

English | [简体中文](11-worker-model-routing-zh.md)

Status: **The design direction is selected. An offline fixture evaluator and partial native routing contracts are implemented; the live backend and runtime validation remain pending.** This page is based on Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. The user wants the main agent to select an already configured provider, model, and reasoning effort automatically according to task difficulty when delegating work, and has reviewed and selected the native-plugin approach. The [offline precursor](35-offline-worker-routing.md) does not install or run a routing service.

## 1. Decision and Scope

Use an independently distributed **native worker-routing plugin** loaded by Hermes. It returns an execution route for each worker through `DelegationProvider.route_task`. The main agent still understands the user, breaks down tasks, obtains authorization, checks acceptance, and reports results. Hermes still creates and stops workers and owns tool isolation, sessions, credential resolution, concurrency, and results. The routing plugin answers only: “Which permitted route should this task use?”

This is task-level model routing and does not require a new API gateway. An existing LiteLLM, OpenRouter, or other compatible endpoint may serve as a user-configured provider, but it must not silently change the downstream model, data recipient, or budget and become a second decision-making center. The first phase does not change the main agent's model or switch models back and forth on every reasoning turn within a worker.

The preferred sequence is **deterministic rules and a static capability inventory → shadow selection → bounded activation → evaluate classifiers or learned policies only after gathering evidence**. Complexity affects candidate ranking, not authorization. A “stronger model” neither replaces approval for outbound actions nor grants permission to transmit sensitive data.

Installing or enabling the plugin only makes it discoverable; it does not automatically change `delegation.backend`. After the owner explicitly selects this backend, it defaults to shadow mode; actual automatic selection is a separate explicit setting. Shadow mode must refer to an existing, still-authorized static delegation baseline and verify its provider, model, effort, and data scope. Without a qualified baseline, configure and verify one first. Do not use an empty route to inherit an arbitrary parent model or claim that shadow mode has started.

## 2. What Hermes Currently Supports

### 2.1 Existing Native Integration Points

- A plugin registers through `ctx.register_delegation_provider()`. `delegation.backend` selects the active backend, whose configuration lives under `delegation.backends.<backend>`.
- `route_task(task, config)` can return route fields such as provider/model, reasoning_effort, service_tier, fallback_providers, and label. The host resolver resolves credentials.
- `task_parameters(config)` can declare bounded enums such as `work_class` and `effort_hint`. The core rejects reserved fields and undeclared parameters. The schema and description must be deterministic for a given configuration, rather than changing dynamically on each turn according to the network or time.
- If the selected backend is missing or unavailable, the host fails closed rather than automatically switching to default. Rejecting one task's route need not cancel other valid tasks in the same batch.
- Hermes retains ownership of lifecycle features such as spawn, roles, depth, concurrency, stop fan-out, output_schema, and progress. The plugin does not reimplement them.

Evidence: [DelegationProvider ABC](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/delegation_provider.py), [official plugin guide](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/delegation-provider-plugin.md), and [route resolver](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_routes.py).

### 2.2 Capabilities That Must Not Be Assumed to Exist

The current payload received by `route_task` contains only `goal`, `context`, `index`, and model-supplied plugin parameters. It does not contain a complete, trusted owner/task identity, modality, remaining budget, authorization, cancellation state, or tool requirements. Putting these values into model parameters does not make them trusted. The current interface also lacks a complete host contract for atomic budget reservation.

| Path | Boundary in this baseline | Design treatment |
|---|---|---|
| Native `delegate_task` | Invokes the delegation backend, including supported background delegation | First integration surface; test each path |
| `ctx.subagent_lifecycle` | Its documentation explicitly says it does not consult `delegation.backend`; the request has no separate effort field | Do not claim automatic coverage; an explicit bridge or minimal host extension point is required |
| Initial Kanban worker / cron | Each uses its own profile/job/model routing; enabling the backend does not automatically take over all routing | Unchanged in the MVP; future integration needs separate validation |
| Internal calls such as `/review` | `route_for_config` explicitly bypasses the provider and uses its own route | Account for review and auxiliary calls separately in cost and permissions; do not assume plugin control |
| Cross-profile route | The profile determines model, credentials, reasoning, and related settings; other route keys are ignored. Frozen snapshots for ordinary managed workers restrict cross-profile routes | The MVP must not switch profiles to silently change models or identity |

The public lifecycle still does not support request fields such as per-launch timeout, cwd override, or per-tool blocking. `delegation.child_timeout_seconds` is an **inactivity/no-progress timeout, not a total wall-clock deadline**. If total task deadlines, total cost, and cancellation propagation require hard guarantees, the host execution paths must supply them; an invented route field cannot. See [public lifecycle](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/subagent-lifecycle-api.md) and [timeout implementation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_config.py#L192-L201).

## 3. Candidate Routes and Capability Inventory

Candidates must be routes that the user has configured and explicitly permitted for the relevant work and data scope. Record `route_id`, provider identity, model, api_mode/endpoint identity, capabilities, effort support, pricing/metering source, health, privacy scope, and evidence version. Keep only host references to keys; do not put keys into task prompts, audit text, or a separate plugin-owned secret store.

Capability entries must cover at least tool calling, structured output, image/audio input, context/output limits, the form of reasoning controls, whether reasoning can be disabled, service tiers, cache/usage metering, and data recipients and their verifiable scope. Being configured as available does not mean all capabilities have been verified. Unknowns remain unknown; do not infer them from model names.

Present candidates using user-defined aliases such as fast-text, balanced-code, and deep-review, rather than requiring a purchase or a particular brand. An alias only maps to a configured route; it does not bypass an exact model pin. When the user explicitly specifies a model or effort, honor a valid pin rather than silently replacing it with a “cheaper” route.

## 4. From Constraints to Selection

```text
Host-verified task context + current policy
    → Filter routes that are not permitted, unavailable, or fail hard constraints
    → Evaluate task requirements and uncertainty
    → Compare feasible candidates on task-completion quality, total cost, and latency
    → Produce an auditable RouteDecision
    → Host revalidates, admits the budget, and constructs the worker
    → Record actual route/usage/outcome; retry or escalate within bounds if needed
```

**Filter first, rank second.** Data-recipient, regional, and local-only restrictions; user pins; modality; context; tools/output schema; budget; deadline; effort; and service tier are hard constraints. Quality, estimated total cost, latency, cache behavior, and historical success rate rank only the remaining candidates. If none is feasible, refuse or wait for input. Do not automatically cross privacy boundaries, raise limits, or buy an upgrade.

Initial complexity assessment can use structured signals: task type, number of steps/dependencies, conflicting evidence, verifiability, scope of code changes, modality, input length, and prior failures. Model-assigned difficulty and `work_class` are hints only. A short task may be difficult, while long text may need only reformatting. Classify risk separately from difficulty: “simply sending an email” does not remove confirmation requirements.

Example policies are starting points for evaluation: favor low-cost candidates for deterministic extraction/reformatting; balanced candidates for local code changes with clear tests; and deeper candidates for cross-file diagnosis, conflicting evidence, and demanding review. Surface keywords are not accuracy measures, and not every task should automatically start with a run on the cheapest model.

## 5. Normalize Reasoning Effort per Route

### 5.1 Record Three Distinct Concepts

1. `requested_effort`: the level requested by the user or policy.
2. `effective_effort` and `wire_shape`: the parameters actually encoded by the host for the provider/model/api_mode, or provider-default/omitted.
3. `usage/outcome`: the returned token/cost/result evidence. Sending high on the wire does not prove that the model used a fixed amount of internal computation.

Hermes uses the internal effort ladder none/minimal/low/medium/high/xhigh/max/ultra, but this is not a uniform unit of compute across providers. `clamp_effort` usually maps to the nearest supported weaker level, or the provider's lowest level if necessary, with vendor-specific exceptions. If the supported set is unknown, the function may return the input unchanged; **that does not prove server-side support for the value**. See [reasoning_effort.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/reasoning_effort.py).

### 5.2 Mapping Examples in the Pinned Source

| Route family | Differences in the baseline | Plugin requirement |
|---|---|---|
| OpenAI/Codex Responses | Supported sets differ by model generation; some lack none/minimal. ultra is not a universal wire value, and Codex app-server has separate harness semantics | Reuse the relevant resolver/encoder; do not send ultra to every compatible endpoint |
| xAI | Older and newer models support different sets; xhigh cannot be assumed for every route | Verify model/api_mode capabilities before selecting a level |
| Kimi K3 | Supports low/high/max; the baseline has special mappings medium→high and xhigh→max | Mapping can increase effort; recheck cost and user constraints, and do not claim clamping always goes downward |
| DeepSeek V4 | Supports low/medium/high/max, with xhigh→max; special combinations apply to thinking toggles and wire fields | Let the host's provider encoder handle it; do not manually combine generic parameters |
| Gemini native | Newer generations use thinkingLevel; older forms may use thinkingBudget. Output-token encoding may also be adjusted for thinking | Estimate budgets from the final effective request; the original max_tokens is not a hard cost guarantee |
| Other/custom endpoint | May expose only a toggle, token budget, provider default, or no reasoning control at all | Do not send guessed fields without capability validation; exclude the route when a hard requirement cannot be met |

This table gives examples of behavior in the pinned Hermes source. It is not independent certification of current model availability for purchase, account eligibility, or live API support. See [thinking encoding](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/reasoning_effort.py) and [Gemini native requests](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/gemini_native_adapter.py).

If an exact effort pin is unsupported, report a mismatch rather than silently lowering it. Automatic policies may normalize only within permitted bounds and must record why the value changed. If the user explicitly disables thinking but the model cannot, do not pretend none took effect. `reasoning_effort`, output-token limits, total budget, and `service_tier` are different controls. fast/ultrafast may affect service eligibility and fees; do not automatically upgrade them by default.

The native result route can report the child's actual provider/model/effort and fallback markers, but does not guarantee visibility into every transmission encoding or server-internal behavior. Mark effective wire behavior unknown where observations are insufficient. Add a general extension point for redacted request metadata, rather than reading or displaying hidden reasoning. See the [result-route contract](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/delegation-provider-plugin.md#result-route).

## 6. Trusted RouteContext and Minimal Host Extensions

The following are **proposed extensions, not existing APIs**:

- `RouteContext`: host-bound owner/profile, task/attempt, source/authorization refs, parent/child role, required tools/modality/context, user pins, data_scope, policy revision, budget reservation scope, and deadline/cancel token. The model may propose task hints, but cannot forge these authoritative fields.
- `RouteDecision`: candidate set, selected route, effort requirements, constraint checks, bounded fallback plan, policy/capability snapshot IDs, and reason codes. The decision carries no plaintext key and does not start a worker itself.
- `BudgetAdmission`: the host atomically reserves task/owner/provider budget across concurrent work, bound to attempt/route/final effective request upper bounds; it fills in actual usage, releases failed reservations or marks them unknown, and reconciles after restart.
- `RouteEnforcement`: before worker construction and each chargeable request or route change, verify current authorization, cancellation, and budget; emit redacted final provider/effort/limit metadata. Do not rely solely on middleware that can fail open.

Small extensions should be general, testable host capabilities: add trusted read-only context and admission receipts, rather than inserting personal-agent-specific branches into the Hermes loop. Preserve compatibility with existing plugins and test both in-process and plugin-host execution. Call limits hard only after runtime validation covers delegation, fallback, auxiliary calls, and API request paths.

Keep the internal RouteDecision record separate from the current route_task return value. Project only supported ROUTE_KEYS into the value returned to the host. The current resolver drops unknown keys; adding a budget token, deadline, or policy receipt to a route dict does not make it enforced by the execution layer.

Until these capabilities exist, the plugin may only make local shadow selections/reports, or run narrow experiments with synthetic or approved redacted fixtures whose data and budget boundaries the host can verify. A model's assertion that “there is no sensitive information” is insufficient. **A prompt saying “budget: 1 yuan/local only” cannot enable automatic routing of sensitive data.** If a mandatory condition cannot be verified, refuse automatic selection. Ordinary managed workers currently use frozen configuration snapshots; revocation must read the current durable policy rather than wait for a configuration hot reload. See [existing security boundaries](06-plugins-mcp-and-security.md).

## 7. Privacy, Cost, and Cancellation

### Privacy

Changing provider may change the data recipient. A configured account does not authorize it to receive all personal information. Apply hard filters before any network-based classification call. Classifiers, embeddings, reviewers, fallbacks, and logging platforms are also data recipients; constraints cannot apply only to the final worker. Default local rules make no additional outbound transmissions. A remote classifier needs explicitly permitted data scope and should receive only the minimum necessary excerpts, not the full personal profile.

### Budget

Compare **the total cost of completing a task**, including classification, multiple worker turns, retries, escalation, review, cache writes/reads, tools, voice, and other related calls, rather than only the token price of a single request. The ledger distinguishes estimates, reservations, known actual costs, and unknown charges. Do not record unknown prices or usage as zero.

Concurrent workers must not each read the same remaining balance and spend it simultaneously. Reservations must be atomic in a shared authoritative store. Fallbacks and reviewers consume the same task budget. Validate the final provider adapter's output/thinking caps, additional chargeable fields, and automatic cap increases. If the provider cannot supply an enforceable upper bound, label the budget soft, refuse hard-limit scenarios, or use an explicitly approved alternative. Do not promise that the provider's bill can never exceed the limit.

### Cancellation and In-Flight Calls

Distinguish the total deadline from the inactivity timeout. Cancellation first blocks admission of the next chargeable call and propagates a stop request to running workers. Already-submitted model/API requests may continue to incur charges; cancellation is not a refund. Follow the [admission linearization in 06 §8](06-plugins-mcp-and-security.md#8-revocation-audit-and-emergency-stop): admit each new call and fallback separately rather than reusing an indefinite permission.

## 8. Bounded Fallback and Escalation

The MVP selects a route when creating the worker and keeps route affinity throughout the attempt where possible. This avoids cache loss, model oscillation, and context-compatibility issues from reclassifying each turn. Later changes require clear events: temporary provider unavailability, unsupported capabilities, verifiable task failure, or changed user requirements.

- Distinguish transport retries, same-level failure fallbacks, and capability escalation. One 429 or timeout does not automatically mean “the task is too difficult.” Do not switch providers to bypass an authorization denial.
- Each task has a maximum attempt count, total deadline, model-call limit, and cost limit. Set exact values in tests/user configuration; do not allow an unbounded “cheap model→expensive model→reviewer” chain.
- Every fallback candidate must pass privacy, model-pin, capability, effort, and budget gates again. Hermes non-profile routes inherit delegation.fallback_providers, so the plugin must supply an explicitly reviewed list. The MVP can return `[]` to disable unreviewed inherited chains.
- Establish the outcome of tool side effects before switching. Do not replay a task that has already sent a message or created an object merely to change models. Reconcile first if execution is uncertain. Hand off only minimum necessary artifacts/evidence to the new attempt, rather than blindly forwarding private reasoning blocks of an unknown format.
- Escalation relies on tests, schema validation, fact-checking, or bounded human review, not solely on a model saying “I am not confident.” Reviewers are also subject to permissions and budgets.

## 9. Shadow Mode and Auditing

Shadow mode retains the existing authorized fixed delegation route, computes a “suggested route,” and records the comparison. It does not change the worker's actual provider/effort or rerun a complete task merely to validate the suggestion. Do not promise zero cost. Default local rules make no extra LLM requests, but any later classifier or replay benchmark needs separate accounting and authorization.

At minimum, audit task/attempt/parent, policy/capability versions, candidates and exclusion reasons, user pins, requested/effective effort, actual provider/model/api_mode, pricing source, budget reservations, fallback/retry reasons, call count, usage, latency, validation results, and final state. Record decisions as brief reason codes/evidence summaries, not hidden reasoning or complete sensitive prompts.

Explicitly mark unknown wire effort, usage, or recipients. Shadow logs establish differences in recommendations, not whether the new model would complete the task. Validate quality/cost benefits with approved redacted or synthetic replays, verifiable outputs, and a test set not used for tuning.

## 10. Comparison with Related GitHub Implementations

These comparisons are based on source/documentation review only. **No implementation was installed, load-tested, or verified for actual Hermes compatibility.** This project does not claim to implement the internal mechanisms of dots or Grokbot; the user's observations describe the desired experience only.

| Reference implementation | Verified content | Lessons and limitations |
|---|---|---|
| NVIDIA NeMo Switchyard | Parent and sub-agent can use independent routing; selection is maintained through trusted child/session identity; libsy is embeddable and has Python binding guidance | Closest reference for delegation-level routing. libsy is Beta, runner/client are earlier-stage, and the standalone server is positioned as a demo; do not directly deploy it as a second production brain |
| LiteLLM complexity_router | Local heuristics plus optional LLM/capability classification; tiers can attach request parameters such as reasoning_effort; session/cache-related policies | Suitable for users with an existing unified provider gateway, not a mandatory dependency here. Complexity classification is not an accuracy guarantee, and the default heuristic's offline nature does not apply to every mode. Some tuning capabilities have license/entitlement quotas; verify required features before adoption |
| vLLM Semantic Router | Complexity signals use differences between hard/easy prototypes or a remote scorer, producing easy/medium/hard; explicit unknown/failure behavior is supported | Suitable for existing inference-routing deployments; adds services/models/configuration for a single-user plugin. Score margin is not correctness, and remote embeddings/scorers also transmit data |

Pinned sources:
- Switchyard `c365efe832822541024704aadf6a0d5c81cc0528`: [sub-agent routing](https://github.com/NVIDIA-NeMo/Switchyard/blob/c365efe832822541024704aadf6a0d5c81cc0528/docs/routing_algorithms/subagent_routing.md), [architecture and stability levels](https://github.com/NVIDIA-NeMo/Switchyard/blob/c365efe832822541024704aadf6a0d5c81cc0528/README.md). Child routing requires the harness to supply child identity; parent/child identity cannot be guessed from a prompt.
- LiteLLM `b1d8ee719186bd7ed62e40ddf0c04035257c1943`: [complexity_router](https://github.com/BerriAI/litellm/blob/b1d8ee719186bd7ed62e40ddf0c04035257c1943/litellm/router_strategy/complexity_router/README.md). For example, heuristic-v1 custom dimensions/tuning limit the number of configurations without entitlement. Do not characterize the entire algorithm suite as wholly free or wholly paid.
- vLLM Semantic Router `abf9778f2cb754f015f519e3fb066ec1c5054a22`: [complexity signal](https://github.com/vllm-project/semantic-router/blob/abf9778f2cb754f015f519e3fb066ec1c5054a22/website/docs/tutorials/signal/learned/complexity.md).

Decision: implement the minimal native-plugin contract and local policy first. Switchyard may later supply an embedded algorithm; LiteLLM is an optional host for users with an existing gateway; vLLM SR is not a dependency for now. Any downstream router must expose and constrain the final model/data recipient. Without that, it cannot enter automatic mode for sensitive data or hard budgets.

## 11. Phased Roadmap and Acceptance

This feature uses the new **E9** epic and does not renumber E0–E8. E9.1 is in progress with partial offline contract evidence; the remaining runtime work packages stay in Backlog. The offline fixture slice does not complete any runtime activation gate.

| ID | Work package | Milestone | Dependencies and deliverables |
|---|---|---|---|
| E9.1 | Verify Hermes Routing Contracts | M0 | Depends on E0; pin plugin discovery/route_task/result/schema-switching contracts and list uncovered paths and capabilities |
| E9.2 | Define Trusted Route Context and Constraints | M1 | Depends on E9.1, identity/grant/revocation/data-scope contracts from E1.1/E1.2/E1.4/E1.5, and task/attempt identity contracts from E3.2; does not wait for all of E3 |
| E9.3 | Build Shadow Routing and Audit | M2 | Depends on E9.1/E9.2; local selection suggestions, unchanged actual routes, redacted audits, and baseline data |
| E9.4 | Enable Bounded Worker Routing | M3 | Depends on quality evidence from E9.3 and safety gates from E9.5/E9.6; enable only for permitted narrow tasks and preserve user control |
| E9.5 | Validate Effort and Fallback Policies | M2 (retest at M3) | Depends on E9.1/E9.2; test effective effort per provider, inheritance chains, failure/quality escalation, cancellation, and prevention of side-effect replay |
| E9.6 | Integrate Budget Admission and Release Gates | M3 | Depends on E9.2, execution admission/revocation from E1.3/E1.4, attempt/reconciliation contracts from E3.2/E3.5, E8.1 audit/metering, and E8.2 fault fixtures; budget reservation/reconciliation and routing release gates, without waiting for the entire E8/M4 release |

Main sequence: E9.1 → E9.2 → E9.3 shadow. E9.5/E9.6 may be validated in parallel, but E9.4 starts only after every activation gate passes. Do not skip trusted context or hard-budget gaps merely to demonstrate automatic switching early.

### Required Test Scenarios

1. Never select a provider/model outside the user's configured and permitted set. Automatic optimization must not override user pins.
2. Produce a definite outcome when modality, tools, schema, context, or effort is unsupported or unknown. Without a valid candidate, do not silently inherit an arbitrary parent route.
3. Cover Chinese and English, short difficult tasks, long simple tasks, misleading difficulty hints, and tool-output injection. The classifier is not an authorization source.
4. Distinguish requested/effective/wire effort. Cover unsupported none, vendor-specific upward mappings, unknown endpoints, service-tier eligibility, and final output caps.
5. Do not falsely claim hard-budget guarantees when concurrent workers share a remaining balance, a process crashes after reservation, usage arrives late, prices are unknown, or canceled calls still incur charges.
6. Subject classifiers/reviewers/embeddings/fallbacks to the same privacy scope and budget constraints as the main worker. Shadow logs or remote scorers must not leak additional sensitive data.
7. Fail closed according to the native contract when the selected backend is missing/unavailable, route_task raises, or the network fails. Verify the boundary between rejecting one task and other tasks in the batch. An unloaded plugin cannot provide shadow behavior or automatically revert to default. Relevant delegation resumes only when the owner explicitly switches back to an approved static configuration. Shadow applies only where the plugin has loaded successfully and the user has selected shadow mode. In safe mode or without trusted context, do not enable automatic selection; retain supported read-only diagnostics or simulate only if a qualified shadow path already exists.
8. Handle 429s, authentication failures, unknown tool side effects, and quality-test failures separately. Prohibit unbounded escalation, duplicate outbound actions, and model changes that bypass a denial.
9. Installing/enabling the plugin does not automatically switch backends. Explicit owner selection defaults to shadow and runs only with a valid static baseline; without one, do not arbitrarily inherit the parent route. Ordinary configuration saves, new sessions, `/delegation <backend> --now`, and resume/compression must preserve schema/backend-pin consistency. Switching back to default is explicit, and behavior for old/new sessions and in-flight tasks must be explainable. Do not claim that saving configuration immediately switches all tasks.
10. Compare task success, total cost per successful task, p95 completion latency, routing overhead, incorrect downgrades, fallback count, and human intervention using a fixed model pool, tools, and dataset. Benefits must include classifier/reviewer/retry costs. Expand gradually only with zero safety failures and the predeclared quality threshold met.

List unknown, failed, and unrun tests separately. A release establishes only the validated scenarios, not a promise that routing is always cheaper or more correct. The plugin can be disabled or reverted to an approved static configuration, but revocation and budget safety gates must not be bypassed during rollback.
