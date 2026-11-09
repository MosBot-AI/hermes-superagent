# 真实原生任务会话验收

[English](65-live-task-acceptance.md) | 简体中文

## 精确范围

2026-11-09，合成数据的单用户任务会话通过真实 Hermes 原生 TUI 和 OpenCode Go `deepseek-v4.1-flash` 路线完成了验收。这补充了 [Issue #41](https://github.com/MosBot-AI/hermes-superagent/issues/41) 缺失的有限真实提供方证据，不代表完整个人助理 MVP 验收完成。

- 插件源码：`e01bd2cd405dd7f36b87896ede13fa70f7cfeace`，即本次文档变更前的 main。
- 宿主源码：`bf0203a794a07aac3ff764972ab9087baa4e4f4e`，位于获授权的 Linux 测试 laptop。
- 提供方：`opencode-go`；模型：`deepseek-v4.1-flash`；端点：`https://opencode.ai/zen/go/v1`。
- 使用全新独立 profile、合成任务数据及已获授权的现有凭据，未配置后备提供方。没有停止或重新配置日常 profile 及其运行中的 Gateway。
- 插件运行包由仓库构建器导出，再通过官方安装器扫描、安装和启用。没有覆盖扫描结果、绕过插件隔离或修改宿主。宿主提示可选 `llm.text_worker` 能力未知；`plan_worker` 保持关闭，不代表 worker 兼容性通过。

该宿主比 `compatibility.json` 中的确切离线开发目标更新。本结果只证明该宿主修订上的被测任务会话路径，不改变兼容基线，不宣称宽泛版本范围，也不代表 Kanban、调度、worker 或其他适配器通过验收。

## 实际观察到的闭环

测试者通过真实 TUI 提交普通自然语言请求，而不是直接调用插件处理函数。会话通过 `/personal-tools enable-write` 显式激活。验收检查了保存的原生工具结果和独立任务数据库，而非把模型叙述当成证据。

| 步骤 | 实际结果 |
| --- | --- |
| 在合成项目标签下创建一个合成任务 | 一条任务，`captured`，修订 1 |
| 查询该项目并更新任务详情 | 实际调用 `personal_tasks_read` 后更新；`captured`，修订 2 |
| 完成同一任务 | `done`，修订 3 |
| 执行 `/personal-tools disable` 后请求读取和包含新标记的写入 | 两个工具均返回 `status: error`、`data: null`、`error.code: session_tools_not_activated`、`retryable: false` |

停用后，被拒绝操作前后的 SQLite 逻辑转储完全一致：SHA256 为 `32ca3f17c4f79421986a03df3548fe0d9389ce00e64a53528c3c30a4f84965fb`。计数保持为一条任务、三条事件、三条回执。该摘要仅描述本次合成测试，不是其他运行应得到的固定摘要。会话路线元数据确认了上述提供方、模型和端点（12 次 API 调用、10 次工具调用）。SQLite 完整性为 `ok`。导出的来源证明文件 SHA256 为 `c291ff856ff9e193b26a00f776b73f500ab097c20b54a5e9b098da3a291b86db`。关闭后，本次测试 Gateway 进程已不存在。本地完成标记只是任务记录变更，不证明现实工作已经完成。

## 复现流程与隔离

1. 阅读仓库说明及受支持模式文档。检查实际宿主修订和现有进程，不暴露凭据。使用全新一次性 profile，不能复用日常 profile，也不能仅因为 Gateway 正在运行就停止它。
2. 使用严格环境变量白名单。实测启动器仅保留 `PATH`、`HOME`、`USER`、`LOGNAME`、`TERM`、`LANG`、`LC_ALL`，再加入独立的 `HERMES_HOME`、`PYTHONDONTWRITEBYTECODE=1` 和仅在内存中使用的现有 `OPENCODE_GO_API_KEY`。在运行任何 Hermes 命令前建立该环境；后续安装、配置、启用及聊天命令均须使用同一个白名单和独立 HERMES_HOME，而不只是 TUI。不得打印密钥、将其置于命令行参数、写入测试脚本，或复制整份日常环境/配置。
3. 用 `scripts/build_runtime_distribution.py` 导出确切插件源码。遵循官方安装器的本地源码要求，对原样导出的运行包执行 `hermes plugins install "file://$RUNTIME" --yes-deps --enable`。不得删除扫描发现或使用强制/扫描覆盖选项。新 profile 可能需要先通过宿主官方流程准备依赖，启动器才能运行。
4. 仅在独立 profile 的 `plugins.entries.hermes-personal-agent.settings` 中配置 `mode: local_tasks`、`local_conversation: true` 和 `local_model_tools: true`。明确设置上述提供方、模型、端点，并设置 `fallback_providers: []`。保持无关适配器关闭。
5. 通过真实 PTY 运行 `hermes chat --tui --provider opencode-go --model deepseek-v4.1-flash --toolsets personal_agent --max-turns 8 --run-budget 120 --ignore-rules`。这里的 `--ignore-rules` 会跳过宿主 AGENTS/SOUL、记忆和预加载技能的提示注入，以隔离合成测试（测试前已阅读仓库说明），不会关闭宿主授权、插件准入或扫描检查。显式激活测试会话，依次请求创建、项目查询/编辑和完成，每一步均检查真实工具结果和数据库状态。
6. 停用会话工具，获取数据库逻辑快照，再请求读取及包含新合成标记的写入。核实结构化拒绝和数据库没有变化。不能仅凭模型道歉或没有调用工具来推断拒绝生效。
7. 退出 TUI，核实准确进程身份后只停止本次独立 profile 启动的 Gateway。保持凭据和原始本地历史私密。记录摘要、路线、状态转换和脱敏结果，不发布原始终端录屏内容。

初次启动器继承了 `FEISHU`/`HERMES_*` 配置，导致宿主尝试使用已占用的飞书应用。官方冲突保护拒绝了该尝试。测试 TUI 随后停止，日常 Gateway 未停止。上述成功结果来自修正后的白名单启动。单独取一个新 profile 名字并不足以构成隔离。第一次缺少依赖的 profile 启动也正常失败，随后通过官方依赖准备解决。这两次失败启动都不计为通过的任务交互。

## 限制

本次运行仅覆盖一个确切宿主/提供方组合下的一次 TUI 会话和一个合成任务，不证明真实远程/多用户身份、托管插件或受管 worker 支持、移动端或语音验收、提醒或消息交付、重启恢复、worker 执行、完整项目编排、延迟/SLA 或广泛模型可靠性。此前重启与离线契约证据属于其他测试，不会被默认归到这个较新宿主上。除了实际 PTY 之外，没有进行独立实体 UI 观察。

云端对未修改的插件源码通过了 2,957 个单元测试、Ruff lint/格式检查、`ty 0.0.89` 和双语文档检查。这些检查与真实运行的范围不同。本文增加的是验收证据，不是新的运行时功能或生产版本。上层 E6/M1 目标仍未完成。
