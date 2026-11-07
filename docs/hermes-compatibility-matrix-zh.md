# Hermes 兼容性证据矩阵

[English](hermes-compatibility-matrix.md) | 简体中文

## E0.1 基线

[兼容性记录](../compatibility.json)固定 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。已验证的环境为 Linux、Python 3.14.9，以及使用固定版本 Hermes 的 `dev` 和 `test` 组构建的 PM 环境。大多数插件契约测试在临时 profile 中使用原生 `in_process` 加载。取得带版本的兼容性证据之前，保持 `semver_support_range` 为 `null`，[清单](../plugin.yaml)继续省略 `requires_hermes`。开发目标以这个确切提交为准。

[插件提交 `eefa8845b1ed66b740d9e46de2b8aee77917db0a`](https://github.com/MosBot-AI/hermes-superagent/tree/eefa8845b1ed66b740d9e46de2b8aee77917db0a)的 [main 推送运行](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42377180370)通过了 2,534 项单元测试、1,039 项固定宿主契约测试，以及 lint、格式、类型和双语文档检查。应用纯文本 worker 提案的独立临时宿主检出通过了 357 项测试和两套生产入口测试。推送运行还构建、扫描并冷加载了[离线运行包](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42377180370/artifacts/13575019987)。这些 CI 结果对应确切提交。部署和真实模型服务商验收仍待完成。

## 复用点与边界

宿主路径相对于[固定版本的 Hermes 源码树](https://github.com/NousResearch/hermes-agent/tree/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4)。契约测试只为实际覆盖的行为和输入提供证据。链接中的记录列出了完整的反例、恢复检查和未完成的验收门槛。[上游研究](09-upstream-evidence-zh.md)提供更全面的源码引用。

| 复用点 | 固定宿主源码 | 已验证行为与未完成的验收 |
| --- | --- | --- |
| 插件发现、配置、CLI、注册表和存储 | `hermes_cli/plugins.py`、`tools/registry.py`、`plugins/plugin_storage.py` | [原生插件契约测试](../tests/contracts/test_native_plugin.py)覆盖真实加载、拒绝无效配置、注册表和 CLI 分发、profile 存储、重载和卸载。宿主隔离模式会跳过 CLI 注册。完整的宿主隔离工具执行和非 Linux 运行时验收仍待完成。 |
| 原生本地命令、会话权限与主轮次上下文 | `gateway/session_commands.py`、`gateway/session_authority.py`、`agent/turn_facade.py`、`agent/turn_context.py`、`model_tools.py` | [命令契约](../tests/contracts/test_local_conversation_tasks.py)、[会话工具契约](../tests/contracts/test_session_task_tools.py)和[任务聚焦契约](../tests/contracts/test_task_focus.py)覆盖已注册来源的准入、拒绝不支持的来源、限定范围的激活及即时有界上下文。部署后的 CLI/TUI 和真实模型服务商的自然语言验收仍待完成。 |
| Hook 和中间件执行控制 | `hermes_cli/plugins_dispatch.py`、`hermes_cli/middleware.py`、`model_tools.py`、`agent/safe_worker_policy.py` | [执行控制测试](../tests/contracts/test_enforcement_boundaries.py)验证回调拒绝和超时、外层分发器失败、直接注册表绕过、安全模式跳过 hook，以及 worker 配置冻结。[写路径清单](13-enforcement-contracts-zh.md)规定未覆盖的能力集保持禁用。 |
| Profile、渠道与接收 Bot 身份 | `gateway/profile_routing.py`、`gateway/session_identity.py`、`hermes_cli/plugin_host_http_auth.py` | [Owner 入口契约](../tests/contracts/test_owner_entry_contracts.py)验证公开上下文缺少接收适配器证明，以及对歧义身份的拒绝。[读取准入测试](../tests/contracts/test_read_admission_boundary.py)验证生产入口保持关闭。[命令上下文实验](23-host-command-context-experiment-zh.md)仅供评审。经验证的 owner 登记和 Primary Bot 绑定需要宿主提供受支持的证明。 |
| 原生 Projects、Kanban 与 goals | `hermes_cli/projects_db.py`、`tools/project_tools.py`、`hermes_cli/kanban_db.py`、`website/docs/user-guide/features/goals.md` | [Kanban 契约](../tests/contracts/test_native_kanban.py)覆盖向确切看板创建停放卡片、身份约束及结果未知。[结果审核契约](../tests/contracts/test_native_result_review.py)覆盖过期证据、依赖门槛及显式本地完成。原生 Project 映射、goal 驱动的派发和部署后的 Kanban 验收仍待完成。 |
| 调度、蓝图与投递 | `cron/blueprint_catalog.py`、`cron/jobs.py`、`cron/scheduler.py`、`cron/scheduler_delivery.py` | [蓝图契约](../tests/contracts/test_planning_blueprint.py)验证注册、表单校验，并以替身拦截创建调用来检查原生消费者传递的参数。作业、运行及每次触发的回执、投递对账和 heartbeat 行为仍需单独验收。 |
| 子代理生命周期与纯文本规划 worker | `agent/subagent_lifecycle.py`、`tools/delegate_tool_toolsets.py` | [Worker 路由契约](../tests/contracts/test_worker_routing_contracts.py)证明公开 API 的空允许列表无法保证零工具。[生产入口测试](../experiments/text-worker/test_production_entrypoint.py)覆盖未打补丁宿主的拒绝行为和隔离的宿主提案。未打补丁的固定宿主缺少 `hermes.text-worker.v1`。线上 worker 验收和通用工具隔离仍待完成。 |
| 记忆提供方、轮次 hook 和对话记录生命周期 | `plugins/memory/__init__.py`、`agent/memory_manager.py`、`agent/turn_context.py`、`hermes_state_messages.py` | [提供方契约](../tests/contracts/test_native_memory_provider.py)和[候选契约](../tests/contracts/test_memory_candidates.py)覆盖分别选择的有界路径。[重启契约](../tests/contracts/test_memory_process_restart.py)覆盖已持久化的本地状态。[检查点测试](../tests/contracts/test_native_checkpoint_boundary.py)说明保留 UID 无法证明持久的来源覆盖或提交回执。严格检查点和完整恢复仍待完成。 |
| MCP、OAuth 与费用估算 | `website/docs/user-guide/features/mcp.md`、`website/docs/developer-guide/plugins/index.md`、`model_tools.py` | 源码审查确认原生连接器和凭据入口。按账号限定范围的连接器适配、按副作用逐项准入、持久费用记录及未知结果对账需要单独取证。`readOnlyHint` 不足以授权工具。 |
| 语音提供方注册与音频传输 | `agent/transcription_provider.py`、`agent/tts_provider.py`、`hermes_cli/web_routers/audio.py` | [语音提供方契约](../tests/contracts/test_voice_provider_contracts.py)覆盖注册、流式处理默认行为及合成故障。[语音 IPC 实验](21-native-voice-ipc-experiment-zh.md)单独开展。设备、麦克风及实时服务商验收仍待完成。 |
| Dashboard、客户端 API 与移动端登录 | `hermes_cli/web_server_dashboard.py`、`hermes_cli/dashboard_auth/routes.py`、`tui_gateway/contracts/canonical_sessions.py` | [传输源码审查](14-client-api-contracts-zh.md)确认回环回调及授权主体和文件边界的缺口。领域 API 层、受支持的原生手机回调、撤销和部署后的传输验收仍待完成。 |
| 委派后端与模型、推理强度路由 | `agent/delegation_provider.py`、`tools/delegate_tool_routes.py`、`agent/reasoning_effort.py` | [路由契约](../tests/contracts/test_worker_routing_contracts.py)覆盖 schema、显式空回退列表和无效路由拒绝。[离线影子测试](../tests/unit/test_routing_shadow.py)覆盖合成约束。可信的线上路由上下文、服务商实际请求证据和持久预算准入仍待完成。 |

## 复现与源码声明

按[开发验证](../README-zh.md#开发验证)使用确切、干净的 Hermes 检出及其独立的 Python 3.14 解释器。[检查脚本](../scripts/check.py)记录宿主锁文件和已安装软件包的指纹。[CI 工作流](../.github/workflows/check.yml)在独立工作树中运行宿主提案补丁，并单独构建和检查离线包。[运行包分发](runtime-distribution-zh.md)记录运行包来源及安装被阻止的情况。

固定版本的 Hermes 使用 MIT 许可证。[第三方声明](../THIRD_PARTY_NOTICES-zh.md)记录上游许可证、测试依赖来源，以及为语音、命令上下文和纯文本 worker 补丁保留的声明。生产插件本身没有第三方 Python 运行时依赖。运行包和兼容性证据覆盖当前开发基线，E0 的其余验收和发布门槛仍待完成。
