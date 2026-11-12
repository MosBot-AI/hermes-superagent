# Hermes 兼容性证据矩阵

[English](hermes-compatibility-matrix.md) | 简体中文

## 当前 E0.1 目标

当前[兼容性记录](../compatibility.json)以 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 为目标，这是 2026-11-08 查询时上游 main 的最新提交。每次测试固定查询到的版本，不在运行中追逐移动的 `main`。仍强制要求准确且干净的 Git 身份；缺少 `.git` 的官方源码归档不能满足这些检查。不声明宽泛的版本范围。

此前 MacBook 对该版本的探测通过了全部三项官方真实 Gateway 生命周期测试，以及合成插件 ticket/WebSocket 任务、重启与去重流程。归档形式的契约测试通过 1,037 项，两项 Git 身份守卫失败，并非行为断言失败。这不等于官方安装或真实模型服务商验收，也没有修复云执行器的 socket 限制。Kanban 守卫使用的最新版源码哈希未变化。

仅供评审的宿主提案保留历史基线和隔离解释器，不静默变基，也不算作最新版宿主支持。新的干净检出结果记录在 [E0.1](https://github.com/MosBot-AI/hermes-superagent/issues/1) 关联 Issue/PR 中。

## E0.2–E0.3 原生生命周期范围（22811165）

[原生生命周期契约](75-native-lifecycle-contracts-zh.md)在可丢弃的合成 profile 中增加 Project/Kanban/cron 真实操作入口的创建、查询及归档/取消/历史探测。目标版本和插件运行时依赖不变。已导出的插件 API 包含 `cron.execution_identity`，不包含 Project/Kanban/cron CRUD SDK；仅测试导入原生入口不会把私有内部实现变成生产接口。

证据区分原生弱去重、Project 元数据归档、Kanban 归档副作用的测试限制、已保存但未注册的 cron 作业、取消请求确认及废弃尝试的 `unknown` 结果。实际一次性执行的常量输出 `no_agent` 脚本提供本地完成回执，投递受抑制。不涉及模型、线上 daemon、真实账号或外部投递。确切执行结果以 [Issue #11](https://github.com/MosBot-AI/hermes-superagent/issues/11) 及其关联 PR 为准，不更新下方历史计数。E3/E4 及线上验收仍独立进行。

## E0.4 RPC/MCP 边界范围（22811165）

[写路径证据](13-enforcement-contracts-zh.md)增加内存传输上的真实 RPC 服务端/default 嵌套调度，以及生成的持久客户端在响应丢失后的重试。真实 MCP discovery 和 SDK stdio 探针区分已注册插件否决与直接 registry 绕过，也区分原生不可信工具批准拒绝与虚假只读声明。唯一新增的批准替身是测试 UI 端点，不替换动作门禁。

这 21 个聚焦用例测试合成副作用，不是 shell/browser 沙箱、真实 socket 传输、connector batch、线上 worker 或生产账号。所有受控写发布门禁仍阻断。准确聚合结果以 [Issue #12](https://github.com/MosBot-AI/hermes-superagent/issues/12)及关联 PR 为准；不替换下方历史计数，也不代表 E0.4 完成。

## E0.4 真实生产包暴露面范围（22811165）

[生产暴露面契约](../tests/contracts/test_production_exposure.py)冷加载真实的安装形态包，检查暂存模块来源且不允许回退到仓库导入。测试验证默认/只读负向模型/registry 调度、真实普通 managed/config-only 冻结配置、安全启动省略、不支持 text-worker 时的拒绝，以及原生 blueprint 消费者。独立存储及端点调用判据配合加载/opt-in 正向对照；不调用真实模型服务商、定时作业或外部副作用。

[边界矩阵](13-enforcement-contracts-zh.md#27-真实生产包暴露面与降级)区分不可用的经验证 owner/受控副作用 adapter，与显式启用的本地功能及普通原生 planning-blueprint 调度。`read_only` 不覆盖 `planning_blueprint: true`，不限制其原生投递目标，也不停止既有作业。干净宿主上的 `llm.text_worker` 同意配置，不是获授能力或回退权限。并发/替代执行路径、完整生命周期及真实隔离仍需单独验收。确切聚合证据属于 [Issue #12](https://github.com/MosBot-AI/hermes-superagent/issues/12)，不更新下方历史计数。

## E0.5 合成 MCP 夹具范围（22811165）

[离线合成连接器测试框架](74-synthetic-connector-fixtures-zh.md)以当前准确宿主版本为目标，不修改 `compatibility.json`。其[原生契约](../tests/contracts/test_synthetic_connectors.py)使用真实 MCP 发现、注册表/模型工具分发和 SDK stdio 会话，连接持久假远端。测试覆盖提交后响应丢失、重启对账，以及依据声明重试故意谎报只读的工具。会话过期错误在真实 stdio RPC 之后注入，不是真实 HTTP 会话过期的证据。

测试文件同时检查宿主提交及宿主声明的 MCP SDK 固定版本。确切执行结果以 Issue #13 及其关联 PR 为准；本段不更新下方历史计数。不启用真实账号、服务商、OAuth 流程、网络监听器或生产连接器。该反例证明不能信任 `readOnlyHint`，不是 E0.4 执行控制或 E1/E5 完成的证明。

## E0.9 原生记忆范围（22811165）

[原生记忆契约矩阵](76-native-memory-contracts-zh.md) 区分提供方发现/准入、内置容量/重载、原生历史检索及生命周期/上下文接线，与现有召回及检查点边界。准确执行结果以 [Issue #42](https://github.com/MosBot-AI/hermes-superagent/issues/42) 及关联 PR 为准；此补充不替换下方历史计数。

不支持的隔离、跨配置档案授权及持久来源绑定检查点仍明确保留。项目提供方保持 API v1，必需检查点失败关闭。此仅测试核验不启用自动捕获、远程身份、第二个提供方槽位或生产部署。

## 历史 E0.1 证据（90d6b98）

此前的兼容性基线固定 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。已验证的环境为 Linux、Python 3.14.9，以及使用固定版本 Hermes 的 `dev` 和 `test` 组构建的 PM 环境。大多数插件契约测试在临时 profile 中使用原生 `in_process` 加载。取得带版本的兼容性证据之前，保持 `semver_support_range` 为 `null`，[清单](../plugin.yaml)继续省略 `requires_hermes`。以下历史证据对应的开发目标是该确切提交。

[插件提交 `eefa8845b1ed66b740d9e46de2b8aee77917db0a`](https://github.com/MosBot-AI/hermes-superagent/tree/eefa8845b1ed66b740d9e46de2b8aee77917db0a)的 [main 推送运行](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42377180370)通过了 2,534 项单元测试、1,039 项固定宿主契约测试，以及 lint、格式、类型和双语文档检查。应用纯文本 worker 提案的独立临时宿主检出通过了 357 项测试和两套生产入口测试。推送运行还构建、扫描并冷加载了[离线运行包](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42377180370/artifacts/13575019987)。这些 CI 结果对应确切提交。部署和真实模型服务商验收仍待完成。

## 复用点与边界

除非表中另列版本，宿主路径均相对于[历史固定版本的 Hermes 源码树](https://github.com/NousResearch/hermes-agent/tree/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4)。契约测试只为实际覆盖的行为和输入提供证据。链接中的记录列出了完整的反例、恢复检查和未完成的验收门槛。[上游研究](09-upstream-evidence-zh.md)提供更全面的源码引用。

| 复用点 | 固定宿主源码 | 已验证行为与未完成的验收 |
| --- | --- | --- |
| 插件发现、配置、CLI、注册表和存储 | `hermes_cli/plugins.py`、`tools/registry.py`、`plugins/plugin_storage.py` | [原生插件契约测试](../tests/contracts/test_native_plugin.py)覆盖真实加载、拒绝无效配置、注册表和 CLI 分发、profile 存储、重载和卸载。宿主隔离模式会跳过 CLI 注册。完整的宿主隔离工具执行和非 Linux 运行时验收仍待完成。 |
| 原生本地命令、会话权限与主轮次上下文 | `gateway/session_commands.py`、`gateway/session_authority.py`、`agent/turn_facade.py`、`agent/turn_context.py`、`model_tools.py` | [命令契约](../tests/contracts/test_local_conversation_tasks.py)、[会话工具契约](../tests/contracts/test_session_task_tools.py)和[任务聚焦契约](../tests/contracts/test_task_focus.py)覆盖已注册来源的准入、拒绝不支持的来源、限定范围的激活及即时有界上下文。部署后的 CLI/TUI 和真实模型服务商的自然语言验收仍待完成。 |
| Hook 和中间件执行控制 | `hermes_cli/plugins_dispatch.py`、`hermes_cli/middleware.py`、`model_tools.py`、`agent/safe_worker_policy.py` | [执行控制测试](../tests/contracts/test_enforcement_boundaries.py)验证回调拒绝和超时、外层分发器失败、直接注册表绕过、安全模式跳过 hook，以及 worker 配置冻结。[写路径清单](13-enforcement-contracts-zh.md)规定未覆盖的能力集保持禁用。 |
| Profile、渠道与接收 Bot 身份 | `gateway/profile_routing.py`、`gateway/session_identity.py`、`hermes_cli/plugin_host_http_auth.py` | [Owner 入口契约](../tests/contracts/test_owner_entry_contracts.py)验证公开上下文缺少接收适配器证明，以及对歧义身份的拒绝。[读取准入测试](../tests/contracts/test_read_admission_boundary.py)验证生产入口保持关闭。[命令上下文实验](23-host-command-context-experiment-zh.md)仅供评审。经验证的 owner 登记和 Primary Bot 绑定需要宿主提供受支持的证明。 |
| 原生 Projects、Kanban 与 goals | `hermes_cli/projects_db.py`、`tools/project_tools.py`、`hermes_cli/kanban_db.py`、`website/docs/user-guide/features/goals.md` | [Kanban 契约](../tests/contracts/test_native_kanban.py)覆盖向确切看板创建停放卡片、身份约束及结果未知。[结果审核契约](../tests/contracts/test_native_result_review.py)覆盖过期证据、依赖门槛及显式本地完成。后续[操作生命周期探测](75-native-lifecycle-contracts-zh.md)增加原生创建/查询/归档证据及副作用限制。原生 Project 映射、goal 驱动的派发和部署后的 Kanban 验收仍待完成。 |
| 调度、蓝图与投递 | `cron/blueprint_catalog.py`、`cron/jobs.py`、`cron/scheduler.py`、`cron/scheduler_delivery.py` | [蓝图契约](../tests/contracts/test_planning_blueprint.py)验证注册、表单校验，并以替身拦截创建调用来检查原生消费者传递的参数。后续[生命周期探测](75-native-lifecycle-contracts-zh.md)区分已保存作业、取消请求与执行历史。完整的每次触发/投递核对和 heartbeat 行为仍需单独验收。 |
| 子代理生命周期与纯文本规划 worker | `agent/subagent_lifecycle.py`、`tools/delegate_tool_toolsets.py` | [Worker 路由契约](../tests/contracts/test_worker_routing_contracts.py)证明公开 API 的空允许列表无法保证零工具。[生产入口测试](../experiments/text-worker/test_production_entrypoint.py)覆盖未打补丁宿主的拒绝行为和隔离的宿主提案。未打补丁的固定宿主缺少 `hermes.text-worker.v1`。线上 worker 验收和通用工具隔离仍待完成。 |
| 记忆提供方、轮次 hook 和对话记录生命周期 | `plugins/memory/__init__.py`、`agent/memory_manager.py`、`agent/turn_context.py`、`hermes_state_messages.py` | [提供方契约](../tests/contracts/test_native_memory_provider.py)和[候选契约](../tests/contracts/test_memory_candidates.py)覆盖分别选择的有界路径。[重启契约](../tests/contracts/test_memory_process_restart.py)覆盖已持久化的本地状态。[检查点测试](../tests/contracts/test_native_checkpoint_boundary.py)说明保留 UID 无法证明持久的来源覆盖或提交回执。严格检查点和完整恢复仍待完成。 |
| MCP、OAuth 与费用估算 | `website/docs/user-guide/features/mcp.md`、`website/docs/developer-guide/plugins/index.md`、`model_tools.py` | 源码审查确认原生连接器和凭据入口。按账号限定范围的连接器适配、按副作用逐项准入、持久费用记录及未知结果对账需要单独取证。`readOnlyHint` 不足以授权工具。 |
| 语音提供方注册、文件分发与流式传输 | `agent/transcription_provider.py`、`agent/tts_provider.py` 和 `hermes_cli/web_routers/audio.py`。当前固定版本的文件与流式消费者使用 `22811165` 的 `tools/transcription_tools.py`、`tools/tts_tool.py`、`tools/transcription_streaming.py` 和 `tools/tts_streaming.py`。 | [语音提供方契约](../tests/contracts/test_voice_provider_contracts.py)覆盖注册与合成故障。[文件分发](20-voice-contract-simulator-zh.md#当前固定版本的文件语音分发)覆盖选择、列表就绪检查和回退。[流式消费者](20-voice-contract-simulator-zh.md#当前固定版本的流式消费者)覆盖 PCM、ASR 本地取消及隔离模式下返回对象的失败。[语音 IPC 实验](21-native-voice-ipc-experiment-zh.md)单独开展。托管音频传输、设备及实时服务商验收仍待完成。 |
| 本地语音播放与打断 | `22811165` 的 `tools/tts_tool_speaker.py` 和 `tui_gateway/methods_voice.py`。 | [播放与打断](20-voice-contract-simulator-zh.md#当前固定版本的播放与打断)覆盖 WAV 内容和清理、本地停止后的迟到 PCM，以及进程范围的生成打断。设备播放回执和已确认的原生轮次取消仍待完成。 |
| 原生音频 WebSocket 准入 | `22811165` 的 `gateway/run_api.py`、`gateway/runtime_bootstrap.py` 和 `hermes_cli/web_routers/audio.py`。 | [音频 ASGI 契约](20-voice-contract-simulator-zh.md#当前固定版本的原生音频-websocket-准入)覆盖本地票据、限定于 profile 的 provider 调用，以及流式媒体或回退响应。真实监听器和凭据交付仍需取证。 |
| 原生 HTTP 语音配置与 SDP | `22811165` 的 `hermes_cli/web_routers/audio.py`、`tools/voice_client_config.py` 和 `tools/voice_live.py`。 | [HTTP 语音契约](20-voice-contract-simulator-zh.md#当前固定版本的原生-http-语音配置与-sdp)覆盖限定于 profile 的合成直连与 relay 响应、本地票据拒绝和模拟 GPT-Live 交换。部署环境中的凭据交付及真实 WebRTC 仍需取证。 |
| Dashboard、客户端 API 与移动端登录 | `hermes_cli/web_server_dashboard.py`、`hermes_cli/dashboard_auth/routes.py`、`tui_gateway/contracts/canonical_sessions.py` | [传输源码审查](14-client-api-contracts-zh.md)确认回环回调及授权主体和文件边界的缺口。领域 API 层、受支持的原生手机回调、撤销和部署后的传输验收仍待完成。 |
| 委派后端与模型、推理强度路由 | `agent/delegation_provider.py`、`tools/delegate_tool_routes.py`、`agent/reasoning_effort.py` | [路由契约](../tests/contracts/test_worker_routing_contracts.py)覆盖 schema、显式空回退列表和无效路由拒绝。[离线影子测试](../tests/unit/test_routing_shadow.py)覆盖合成约束。可信的线上路由上下文、服务商实际请求证据和持久预算准入仍待完成。 |

## 复现与源码声明

按[开发验证](../README-zh.md#开发验证)使用确切、干净的 Hermes 检出及其独立的 Python 3.14 解释器。[检查脚本](../scripts/check.py)记录宿主锁文件和已安装软件包的指纹。[CI 工作流](../.github/workflows/check.yml)在独立工作树中运行宿主提案补丁，并单独构建和检查离线包。[运行包分发](runtime-distribution-zh.md)记录运行包来源及安装被阻止的情况。

固定版本的 Hermes 使用 MIT 许可证。[第三方声明](../THIRD_PARTY_NOTICES-zh.md)记录上游许可证、测试依赖来源，以及为语音、命令上下文和纯文本 worker 补丁保留的声明。生产插件本身没有第三方 Python 运行时依赖。运行包和兼容性证据覆盖当前开发基线，E0 的其余验收和发布门槛仍待完成。
