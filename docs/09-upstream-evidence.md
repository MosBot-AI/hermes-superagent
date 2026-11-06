# 09. Upstream Evidence and Verification Boundaries

English | [简体中文](09-upstream-evidence-zh.md)

Verification date: 2026-11-06 UTC. Pinned Hermes baseline: `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`. This review read source files and official documentation; it did not install or run that version. “Exists” means visible in source, not proven in deployment. E0 contract tests must run before implementation.

## H1. Native Architecture

[architecture.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/architecture.md) describes the agent loop, SessionDB, gateway, tools, plugins, and cron. The product design therefore does not introduce a parallel runtime. [README](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/README.md) lists native messaging channels, memory, scheduling, delegation, and execution backends.

## H2. Plugin Extensions and Compatibility

[Plugin Development Guide](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md) describes `register(ctx)`, tools/hooks/commands/skills, config_schema, capability consent, OAuth, and manifests. Compatibility commitments primarily cover documented behavior; neither arbitrary internal imports nor a particular manifest version guarantees overall safety or compatibility. Some manifest descriptions in this long document and its overall compatibility narrative contain details that require verification against the actual loader; this project does not guess available fields from documentation.

[plugins/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/plugins/AGENTS.md) requires plugins not to modify core; missing capabilities should be addressed through general-purpose seams, third-party plugins should be distributed independently, and the official catalog pins SHAs. Native plugins are distributed in separate repositories but run within the Hermes extension mechanism, unlike “external independent agents.”

## H3. Persistent Plugin Data

[Store durable state](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#store-durable-state) provides `plugins.plugin_storage.plugin_data_dir/plugin_db`, storing data under profile-scoped plugin-data. Installation directories may be updated/deleted and must not hold user state. This path is not a secret store.

## H4. Hook Security Boundaries

[plugins_dispatch.py L59–67](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py#L59-L67) lists `pre_tool_call` as fail-closed; [L295–326](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py#L295-L326) produces a block for callback exceptions and timeout/still-running outcomes. [model_tools.py L779–814](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py#L779-L814) still has a path that catches outer dispatcher/import exceptions and continues.

[observer-hooks.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/observer-hooks.md) is a reference for events/correlation IDs. Its general description of callbacks as fail-open does not override the source code’s special handling of pre_tool_call. This document follows the more specific source code rather than generalizing one failure semantics to every hook.

[plugins_dispatch.py L275–293](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py#L275-L293) skips hooks when safe_worker_enabled is set. [safe_worker_policy.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/safe_worker_policy.py) explains that this is a troubleshooting safe-mode bypass, not the default behavior of ordinary managed workers, and not a sandbox. Ordinary workers still load hooks, but their configuration is an immutable session snapshot. Immediate revocation must read the current persistent policy rather than wait for profile configuration to propagate.

## H5. Middleware

[middleware.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/middleware.md) explains that tool_request precedes guard/approval and tool_execution wraps the call; middleware failures may continue downstream. [model_tools.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py#L766-L777) shows tool_request failing open. These mechanisms can support routing/observation/request transformation, but must not be the sole security gate.

## H6. Native Projects

[projects_db.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/projects_db.py) defines profile-scoped Projects, folders, and board_slug/primary_path. [project_tools.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/project_tools.py) explains that `desktop_project` belongs to the GUI toolset and create/switch may change the session workspace. The plugin does not write directly to this DB; mobile/CLI adaptation requires actual verification in E0.

## H7. Kanban and Goals

[Kanban](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/kanban.md) provides durable boards, worker attempts, dependencies, idempotent creation, native tools, and an in-gateway dispatcher. [cron/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/AGENTS.md) specifies ownership, board isolation, stale claims, and notification profile constraints.

[Goals](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/goals.md) explicitly states that `/goal` is a continuation loop in a single session and does not automatically create Kanban cards; a goal-mode card uses that loop within its card worker. “The goal has stopped” does not imply the board task is complete.

## H8. Temporary Subagents

[Public Subagent Lifecycle API](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/subagent-lifecycle-api.md) exposes launch/status/wait/cancel/steer/result/reconnect; launches are permitted only within an active parent turn and handles enforce ownership checks. Results are retained in-process for a limited time, and reconnect after restart returns `RECONNECT_UNAVAILABLE`. Request features such as per-tool blocks, cwd override, and per-launch timeout are currently explicitly rejected; their presence in a schema does not justify claiming support.

## H9. Cron and Heartbeat

[cron/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/AGENTS.md) records timezone, grace, occurrence ledger, tick lock, headless refusal, profile scope, and `skip_memory=True`, and notes that background delegation is process-local.

[Heartbeat](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/heartbeat.md) provides idle-turn prompts for the current session, coalesces missed ticks, and prioritizes the user. It can be restored by the gateway but is cleared at boundaries such as reset/switch; a live owner process is a prerequisite for execution.

## H10. Memory

[Persistent Memory](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/memory.md) describes MEMORY/USER, session search, background review, and write controls. [MemoryProvider](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_provider.py) and the [provider guide](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/memory-provider-plugin.md) specify lifecycle and profile isolation, with only one external provider active at a time.

Note that the lifecycle semantics of a general plugin’s `on_session_end` and the identically named MemoryProvider method must not be conflated. Test each against its own documentation and call path.

## H11. MCP and Costs

[MCP](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/mcp.md) includes stdio/HTTP, OAuth, filtering, dynamic discovery, sampling, elicitation, and experimental events. `tool_costs/spend_limit` are in-session estimates that reset on restart, not a persistent monthly ledger. `readOnlyHint`/trust declarations do not prove that the server actually has no side effects; new tools require semantic review.

## H12. Voice

[Voice Mode](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/voice-mode.md) describes chained STT/TTS, mobile voice messages, Desktop client-direct/relay, a full-duplex voice front-end, and barge-in. Providers, pricing, and device support may change; this document does not lock vendor prices into budget commitments. A mobile real-time calling experience requires separate validation.

## H13. Web and Mobile Foundations

[Web Dashboard](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/web-dashboard.md) includes chat, sessions, cron, MCP, profiles, authentication, and remote connections. The existence of a REST API does not imply it can be exposed publicly without authentication; new UI should prioritize official extensions and authentication mechanisms.

## H14. Worker Provider/Model/Effort Routing

[DelegationProvider ABC](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/delegation_provider.py) and the [official plugin documentation](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/delegation-provider-plugin.md) provide the native route_task seam while core retains lifecycle ownership. [delegate_tool_routes.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_routes.py) shows that the payload contains only goal/context/index and declared parameters, not a complete trusted RouteContext. Non-profile routes can inherit fallback; profile routes ignore other routing parameters, and managed workers’ frozen config restricts cross-profile use.

[reasoning_effort.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/reasoning_effort.py) specifies internal levels, provider/model mappings, and vendor-specific cases; an unknown support set is not proof of server capability. [child timeout](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_config.py#L192-L201) is an inactivity timeout, not a total deadline. Paths such as the public lifecycle and /review do not automatically use delegation.backend. See [11](11-worker-model-routing.md) for detailed design, pinned Switchyard/LiteLLM/vLLM sources, and untested boundaries.

## Verification Checklist

1. Precisely supported releases and plugin install/validate/config schema behavior.
2. Public mutation/read/receipt contracts from the plugin to Project/Kanban/cron/delivery, and which require general-purpose upstream seams.
3. Paths through which all actual external writes pass the action guard, including code-execution RPC, batch tools, and workers.
4. Approval, attachment, timezone, delivery, and identity behavior on the target mobile channel.
5. Real integration tests for persistent services, backup/restore, stop/restart, cancellation, and permission revocation.
6. Voice device/network/provider compatibility and cost metering.
7. E9 routing trusted context, atomic budget admission, complete request paths, effort wire audit, schema/backend switching, and privacy/cost constraints on every fallback.

This review performed only static documentation checks; none of the above pending validations was marked passed. See [02](02-dsh-research-and-decisions.md) for pinned DSH evidence and news-reading limitations.
