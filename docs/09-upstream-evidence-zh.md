# 09. 上游证据与核验边界

[English](09-upstream-evidence.md) | 简体中文

核验日期：2026-11-06 UTC。Hermes 固定基线：`90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。本次读取源文件与官方文档，没有安装或运行该版本；“存在”只说明源码可见，不承诺部署已通过。实施前必须运行 E0 契约测试。

## H1. 原生架构

[architecture.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/architecture.md)说明 agent loop、SessionDB、gateway、tools、plugin 和 cron。产品方案因此不新增平行 runtime。[README](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/README.md)列出原生消息渠道、记忆、调度、委派和执行后端。

## H2. 插件扩展和兼容

[插件开发指南](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md)说明 `register(ctx)`、tools/hooks/commands/skills、config_schema、能力 consent、OAuth 和 manifest。兼容承诺主要是文档化行为，不是把所有内部 import 或某一个 manifest 版本当作整体安全/兼容保证。该长文部分 manifest 描述与总兼容叙述存在需要以实际 loader 核验的细节；本项目不凭文档猜测可用字段。

[plugins/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/plugins/AGENTS.md)要求插件不修改 core；缺能力时扩展通用 seam，第三方插件应独立发布，官方 catalog 固定 SHA。原生插件是独立仓库分发，但运行在 Hermes 扩展机制中，与“外部独立 agent”不同。

## H3. 持久插件数据

[Store durable state](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#store-durable-state)提供 `plugins.plugin_storage.plugin_data_dir/plugin_db`，数据位于 profile-scoped plugin-data；安装目录可能被更新/删除，不可用于保存用户状态。此路径不是 secret store。

## H4. Hook 安全边界

[plugins_dispatch.py L59–67](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py#L59-L67)将 `pre_tool_call` 列为 fail-closed；[L295–326](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py#L295-L326)对 callback 异常、timeout/still-running 生成 block。[model_tools.py L779–814](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py#L779-L814)仍有外层 dispatcher/import 异常捕获后继续的路径。

[observer-hooks.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/observer-hooks.md)是事件/关联 ID 参考，其泛称 callback fail-open 不能覆盖源码对 pre_tool_call 的特殊处理。本文采用更具体源码，不泛化所有 hook 同一失败语义。

[plugins_dispatch.py L275–293](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py#L275-L293)在 safe_worker_enabled 时跳过 hooks。[safe_worker_policy.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/safe_worker_policy.py)说明这是 troubleshooting safe-mode bypass，不是普通 managed worker 的默认行为，也不是 sandbox；普通 worker 仍加载 hooks，但配置是不可变 session snapshot。即时撤权必须读当前持久 policy，而非等待 profile 配置传播。

## H5. Middleware

[middleware.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/middleware.md)说明 tool_request 在 guard/approval 前、tool_execution 包装调用，middleware 故障可继续下游。[model_tools.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py#L766-L777)显示 tool_request fail-open。它们可做路由/观测/请求变换，不做唯一安全闸。

## H6. 原生 Projects

[projects_db.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/projects_db.py)定义 profile-scoped Projects、folders、board_slug/primary_path。[project_tools.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/project_tools.py)说明 `desktop_project` 属于 GUI 工具集，create/switch 可能改变 session workspace。插件不直接写该 DB；手机/CLI 适配属于 E0 的实际验证项。

## H7. Kanban 与 goal

[Kanban](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/kanban.md)提供 durable board、worker attempts、dependencies、idempotent create、原生工具和 gateway 内 dispatcher。[cron/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/AGENTS.md)给出 ownership、board 隔离、stale claim 和通知 profile 约束。

[Goals](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/goals.md)明确 `/goal` 是单 session 继续循环，不自动创建 Kanban 卡片；goal-mode card 才是在卡片 worker 内使用该循环。不能用“goal 已停”推断 board task 已完成。

## H8. 临时子 agent

[Public Subagent Lifecycle API](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/subagent-lifecycle-api.md)公开 launch/status/wait/cancel/steer/result/reconnect；仅在活动父 turn 内启动，句柄有所有权校验。实现结果在进程内保存有限时间，重启返回 `RECONNECT_UNAVAILABLE`；请求中的 per-tool blocks、cwd override、per-launch timeout 等当前明确拒绝，不能因为 schema 列出就声称支持。

## H9. Cron 与 heartbeat

[cron/AGENTS.md](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/AGENTS.md)记录 timezone、grace、occurrence ledger、tick lock、headless refusal、profile scope 及 background delegation 的 process-local 限制。其 `skip_memory=True` 描述与本 pin 的 [scheduler 实现](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/scheduler.py#L2502-L2514)不一致：实际是 `skip_memory=False`、`skip_background_review=True`。[MemoryManager](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py#L261-L266)仅对 subagent 统一抑制相关 turn hooks；cron 写入行为须 provider 遵守 `agent_context="cron"` 契约，不能当成宿主强制只读。

[Heartbeat](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/heartbeat.md)是当前 session 的空闲轮次提示，missed ticks 合并、用户优先，gateway 可恢复，但 reset/switch 等边界清理；存活 owner process 是执行前提。

## H10. 记忆

[Persistent Memory](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/memory.md)描述 MEMORY/USER、session search、后台 review 和写入控制。[MemoryProvider](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_provider.py)及[provider 指南](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/memory-provider-plugin.md)给出生命周期、profile isolation，且同一时刻仅一个外部 provider。

注意 general plugin `on_session_end` 与 MemoryProvider 同名方法的生命周期语义不能混用，应按对应文档和调用路径测试。

## H11. MCP 与费用

[MCP](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/mcp.md)包含 stdio/HTTP、OAuth、筛选、动态发现、sampling、elicitation 和实验性 events。`tool_costs/spend_limit` 是会话内估算，重启会重置，不能当作持久月账本。`readOnlyHint`/trust 声明不证明服务端实际无副作用；新工具需要语义审核。

## H12. 语音

[Voice Mode](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/voice-mode.md)描述 chained STT/TTS、手机语音消息、Desktop client-direct/relay、full-duplex voice front-end、barge-in。provider/价格/设备支持均可能变化，本文不锁定供应商价格为预算承诺。手机实时通话级体验需另行验证。

## H13. Web/移动基础

[Web Dashboard](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/web-dashboard.md)有 chat、sessions、cron、MCP、profiles、认证和远端连接。不得因存在 REST API 就假定它可公开无认证使用；新 UI 优先走官方扩展和认证体系。

## H14. Worker provider/model/effort 路由

[DelegationProvider ABC](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/delegation_provider.py)与[官方插件说明](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/delegation-provider-plugin.md)提供 route_task 原生 seam，核心保留生命周期。[delegate_tool_routes.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_routes.py)显示 payload 只有 goal/context/index 与声明参数，未包含完整可信 RouteContext；非 profile route 可继承 fallback，profile route 忽略其他路由参数，managed worker 的 frozen config 限制跨 profile。

[reasoning_effort.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/reasoning_effort.py)给出内部梯级、provider/model 的映射和厂商特例；unknown 支持集合不构成服务端能力证明。[child timeout](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_config.py#L192-L201)为 inactivity，不是总 deadline。公共 lifecycle 和 /review 等路径不自动使用 delegation.backend。详细设计、固定 Switchyard/LiteLLM/vLLM 来源与未实测边界见 [11](11-worker-model-routing-zh.md)。

## 待验证清单

1. 精确支持的 release 与插件 install/validate/config schema 行为。
2. 插件到 Project/Kanban/cron/delivery 的公开 mutation/read/receipt contract，以及哪些需要通用 upstream seam。
3. 所有实际外部写操作经过 action guard 的路径，包括代码执行 RPC、批量工具与 worker。
4. 目标手机渠道 approval、附件、时区、送达和 identity 的行为。
5. 常驻服务、备份/restore、停止/重启、取消和权限撤销的真实集成测试。
6. 语音设备/网络/provider 兼容和费用计量。
7. E9 路由可信上下文、预算原子准入、完整请求路径、effort wire 审计、schema/backend 切换及所有 fallback 隐私/费用约束。

本次只做文档静态校验；没有把上述待验证事项标为通过。DSH 的固定证据和新闻阅读限制见 [02](02-dsh-research-and-decisions-zh.md)。
