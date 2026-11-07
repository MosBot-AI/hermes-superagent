# Hermes Personal Agent

[English](README.md) | 简体中文

Hermes 原生 personal-agent 插件，目标是让一个主 agent 管理项目、承诺、提醒和受控 worker。完整设计见 [docs 索引](docs/README-zh.md)。不运行第二套 agent loop，也不要求额外 API 网关。

## 当前进度

当前优先交付 **profile-first 单用户本地 MVP**，不要求先绑定主 Bot。已实现 E0 基础、本地任务存储及显式启用的原生会话 `/personal-tasks` 命令，并已新增会话范围任务模型工具；尚未完成真实模型自然语言验收。

- `plugin.yaml` 与同步 `register(ctx)` 原生加载。
- 只读 `personal_agent_status` 工具，以及 `in_process` 插件模式下的 `hermes personal-agent status` CLI。
- 默认 `read_only` 不打开任务存储；显式 `local_tasks` 启用 profile 本地 CLI 收件箱，支持录入、检索、项目分组、列表/查看、编辑、完成和取消，以及显式截止日期与 agenda，以及持久重放 receipt 和 revision 校验。默认不注册个人数据模型工具；单独启用 `local_model_tools` 才注册，并要求会话激活。未实现模型路由，插件加载不创建调度或外发。
- 离线单元测试，以及固定 Hermes SHA 的真实 discovery、registry dispatch、配置和卸载契约测试。
- 后续 E0.4 失败边界契约及十条阻断写路径的只读清单。`hermes personal-agent coverage` 展示证据，不授权或关闭宿主工具。

本插件**不会禁用或保护其他 Hermes 工具**。E0.4 全部写路径覆盖及 E1 身份/授权尚未完成，不能据此开放远程或外部写操作。单独启用的任务模型工具只在明确激活的可信本地会话内访问本地任务。本地任务编辑是单独的明确本地操作员命令。当前 status 输出明确给出 `release_gate: blocked`。详见 [第一切片记录](docs/12-foundation-progress-zh.md)、[执行边界契约](docs/13-enforcement-contracts-zh.md) 和 [更新记录](CHANGELOG-zh.md)。

详细的[客户端与连接器 API 契约](docs/14-client-api-contracts-zh.md) 仅为设计，本插件尚未注册 HTTP API。M1 优先已有原生本地会话；手机渠道、自建 App 和指定主 Bot 是有独立认证/恢复门槛的后续可选路线。

[本地任务收件箱指南](docs/16-local-task-inbox-zh.md) 说明启用、命令、持久化与隐私限制。[截止日期与 agenda](docs/17-local-task-agenda-zh.md) 说明日期语义和最初的 v1→v2 存储升级；它不会投递提醒。[主 Bot 绑定方案](docs/15-primary-bot-binding-zh.md) 选择已有原生 Bot/canonical chat，但绑定与 owner 认证尚未实现。

[Owner 入口与读取权限基础](docs/18-owner-entry-and-read-authorization-zh.md)已实现内部纯评估器及 `/personal-access` / `hermes personal-agent access` 阻断诊断。公开 source 缺少可信接收 Bot 账号边界，生产身份签发与该受保护读取路线仍关闭；这不是已完成的 owner 授权。另行明确启用的单用户本地命令不依赖此未来远程协议。

[统一语音接口方案](docs/19-unified-voice-provider-contracts-zh.md)支持规划中的本地 ASR/TTS/VAD、用户配置的在线 API 与显式适配的实时语音前端，统一生命周期和恢复规则，但保留各后端实际能力差异。[离线语音模拟器](docs/20-voice-contract-simulator-zh.md)现可通过 `hermes personal-agent voice self-test` 验证窄范围合成契约，仅使用生成的静音，不接麦克风、语音模型、provider 或原生 turn。账户连接与真实语音仍未实现。

[本地检索指南](docs/22-local-task-search-zh.md)介绍标题/详情字面检索与有界分页。另有[原生语音 IPC 实验](docs/21-native-voice-ipc-experiment-zh.md)，包含可审阅的宿主补丁和验证记录；本插件不会应用或集成该补丁。

[本地项目分组](docs/24-local-project-groups-zh.md)增加显式任务标签、项目筛选和进度计数，并通过 schema-v3 升级保留旧回执。这些是本地分组，不是原生 Project 或权限范围。[host 命令上下文实验](docs/23-host-command-context-experiment-zh.md)另行打包未集成的身份观察补丁及剩余门禁，不启用 owner 授权。仅命令调用修复另有 87 项受守卫测试验证，历史九项 socket 初始化失败仍未解决。

显式启用的[原生计划 blueprint](docs/25-native-planning-blueprint-zh.md)可通过 Hermes 已有 Blueprint/Cron 界面使用。加载只注册模板，不创建 job。原生排程可能产生模型费用，已有 job 在移除插件后仍会运行。默认投递为本地，不是工具或隐私沙箱。

[待确认身份登记与策略核心](docs/26-pending-enrollment-policy-zh.md)现可持久化拟议映射和范围，包含事务版本、终止性撤销及审计。内部 opener 默认禁用，没有注册运行入口。这些记录不认证 owner、不签发 grant，也不接管本地任务。

[带栅栏的读取准入核心](docs/27-fenced-read-admission-zh.md)增加当前策略事务排序和有界不可变摘要协调。只有合成测试提供可信确认/资源；不启用生产 adapter、运行入口或任务接管。


[原生本地任务对话](docs/28-profile-first-local-conversations-zh.md)将已有任务存储接入 Hermes 会话。在可信单用户安装中显式设置 `mode: local_tasks` 和 `local_conversation: true`，即可使用 `/personal-tasks add "准备演示" --project "个人助手"`、`list`、`projects`、`update` 和 `done`。命令依赖宿主原生会话授权；已获授权的 owner/operator 控制端共享访问，`LOCAL` 不证明物理本地性。不要在对外暴露/共享网关启用。确定性命令不调用模型、不新增远程入口，项目仍是任务标签。


[会话范围任务工具](docs/29-session-scoped-task-tools-zh.md)进一步支持 `personal_tasks_read` / `personal_tasks_write`。单独启用 `local_model_tools: true` 后，在原生会话中使用 `/personal-tools enable-read` 或 `enable-write` 激活30分钟。任务结果进入已配置模型上下文；所有该会话模型活动共享访问，并非逐条用户意图验证。仅支持正常原生进程内模式，不支持 managed worker/hosted plugin，不能为此关闭隔离。真实模型验收尚未运行。

[可插拔记忆方案](docs/30-pluggable-memory-contracts-zh.md)定义可替换的项目后端与用户自写适配器 SDK，默认采用 SQLite 记录/事件/FTS 加 Markdown 投影，并可选桥接实际 Hermes MemoryProvider。获准替换前保留现有原生 provider。当前任务工具**尚未实现**记忆摄取、生命周期集成、检索与迁移。

首个[显式本地记忆切片](docs/31-explicit-local-memory-zh.md)现支持在已有可信原生会话中使用 `/personal-memory remember`、`search`、`show`、`correct`、`forget` 和有界 `export`，需另行显式设置 `local_memory: true`。它通过小型内部后端接口使用独立 SQLite 存储，保留原生 provider，不自动召回/提取。命令/结果可能进入正常宿主历史；遗忘不会擦除该历史或备份。

[会话范围记忆工具](docs/32-session-scoped-memory-tools-zh.md)现通过独立 `memory_model_tools: true` 选项及 `/personal-memory-tools enable-read` 或 `enable-write` 激活，增加有界模型记住/查询/更正/遗忘。任务工具激活不授予记忆权限；模型编辑标记为 `activated_session_model`，不是经验证的人工指令，原生 provider 不变。已有记忆 DB 原子升级到 schema v2；真实 provider 自然语言验收仍待完成。

## 开发验证

基线为 `compatibility.json` 内的 Hermes commit；当前实际运行目标是 Python 3.14。没有根据单一 SHA 宣称宽泛的 `requires_hermes` 版本范围。

先在独立目录准备官方 Hermes checkout 和测试环境。不要使用用户的生产 `HERMES_HOME`，不要复制账号密钥：

```bash
git clone https://github.com/NousResearch/hermes-agent.git ../hermes-agent
git -C ../hermes-agent checkout --detach 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
cd ../hermes-agent
export HERMES_HOME="$(mktemp -d)"
export HERMES_RUNTIME_DIR="$(mktemp -d)"
python -m pm.build_env --source . --out ../hermes-test-venv --group dev --group test
cd ../hermes-superagent
../hermes-test-venv/bin/python scripts/check.py \
  --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

准备环境需要从官方源下载依赖；测试使用合成输入、临时 home 和 Python socket 网络禁用，不访问真实个人账号。检查脚本核对上游 HEAD 与 tracked 文件清洁状态，记录 Python 版本、lock/package 指纹，再调用 Hermes 官方 `scripts/run_tests.sh`。缺少 checkout 或依赖会失败，不会跳过后冒称兼容。已安装包的指纹是所用解释器的观察证据，不证明任意传入环境必定与 lock 完全一致。

检查器通过 pytest 配置传递宿主和插件源码目录，使导入路径在宿主清空环境变量后仍然有效，也支持含空格的目录。这不会向测试环境传递凭据，无需再手动设置 `PYTHONPATH`。

只运行 `python scripts/check.py` 会做本仓库单元测试、Ruff、ty 和双语文档结构/链接及 JSON 示例语法检查，并明确打印 Hermes compatibility **NOT RUN**。测试工具版本随固定 Hermes dev group，不是插件运行依赖。

## 在隔离 Hermes 中试用

这不是生产安装建议。使用固定、已测试的 Hermes checkout 和临时 profile，按该版本 `hermes plugins install --help` 安装经审阅的**完整 40 字符 commit SHA**；`--ref` 不接受分支名，GitHub tree 分支 URL 也不能替代 pin。然后显式启用插件，插件标识为 `hermes-personal-agent`。

当前实际合同测试覆盖默认 `plugins.isolation: in_process`。在 `plugins.isolation: host` 下，宿主会跳过 `ctx.register_cli_command`，因此这里的 CLI 不可用；隔离 host 模式的完整工具调用尚未运行验证，不要为了显示 CLI 而关闭已配置的隔离。

配置位于宿主 `config.yaml`：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: read_only
```

合并到你已有配置时保留其他条目，不要覆盖整个 `plugins`。启用不修改 `delegation.backend`、主模型、凭据、tool override 或其他权限。`personal_agent_status` 是否出现在模型工具面还取决于宿主会话的工具集选择；CLI 状态检查不需要 LLM 调用。

试用收件箱时，仅将本插件 mode 显式改为 `local_tasks`，按[命令示例](docs/16-local-task-inbox-zh.md#2-启用与使用)操作。它使用 POSIX 私有文件检查，在 Linux 上测试；Windows 任务存储不支持。它不会绑定 Bot、派发原生工作，也不需要 API Key。任务文本是明文本地数据，不是秘密存储。

## License

[MIT](LICENSE)。仅供审阅的语音与命令上下文实验包含部分上游衍生补丁及其许可；未打包整个 Hermes 宿主，插件安装也不会修改它。出处与许可说明见 [THIRD_PARTY_NOTICES-zh.md](THIRD_PARTY_NOTICES-zh.md)。
