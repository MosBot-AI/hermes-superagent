# Hermes Personal Agent

[English](README.md) | 简体中文

Hermes 原生 personal-agent 插件，目标是让一个主 agent 管理项目、承诺、提醒和受控 worker。完整设计见 [docs 索引](docs/README-zh.md)。不运行第二套 agent loop，也不要求额外 API 网关。

## 当前进度

已实现的开发切片包括 **E0 原生兼容基础**和**显式启用的本地 CLI 任务收件箱**，尚不是完整 personal-agent MVP。

- `plugin.yaml` 与同步 `register(ctx)` 原生加载。
- 只读 `personal_agent_status` 工具，以及 `in_process` 插件模式下的 `hermes personal-agent status` CLI。
- 默认 `read_only` 不打开任务存储；显式 `local_tasks` 启用 profile 本地 CLI 收件箱，支持录入、检索、项目分组、列表/查看、编辑、完成和取消，以及显式截止日期与 agenda，以及持久重放 receipt 和 revision 校验。不注册个人数据模型工具、外发、调度或模型路由能力。
- 离线单元测试，以及固定 Hermes SHA 的真实 discovery、registry dispatch、配置和卸载契约测试。
- 后续 E0.4 失败边界契约及十条阻断写路径的只读清单。`hermes personal-agent coverage` 展示证据，不授权或关闭宿主工具。

本插件**不会禁用或保护其他 Hermes 工具**。E0.4 全部写路径覆盖及 E1 身份/授权尚未完成，不能据此开放模型驱动或外部写操作。本地任务编辑是单独的明确本地操作员命令。当前 status 输出明确给出 `release_gate: blocked`。详见 [第一切片记录](docs/12-foundation-progress-zh.md)、[执行边界契约](docs/13-enforcement-contracts-zh.md) 和 [更新记录](CHANGELOG-zh.md)。

详细的[客户端与连接器 API 契约](docs/14-client-api-contracts-zh.md) 仅为设计，本插件尚未注册 HTTP API。M1 使用已有手机消息渠道；自建原生手机 App 有独立的认证与恢复门槛。

[本地任务收件箱指南](docs/16-local-task-inbox-zh.md) 说明启用、命令、持久化与隐私限制。[截止日期与 agenda](docs/17-local-task-agenda-zh.md) 说明日期语义和最初的 v1→v2 存储升级；它不会投递提醒。[主 Bot 绑定方案](docs/15-primary-bot-binding-zh.md) 选择已有原生 Bot/canonical chat，但绑定与 owner 认证尚未实现。

[Owner 入口与读取权限基础](docs/18-owner-entry-and-read-authorization-zh.md)已实现内部纯评估器及 `/personal-access` / `hermes personal-agent access` 阻断诊断。公开 source 缺少可信接收 Bot 账号边界，生产身份签发与私人读取仍关闭；这不是已完成的 owner 授权。

[统一语音接口方案](docs/19-unified-voice-provider-contracts-zh.md)支持规划中的本地 ASR/TTS/VAD、用户配置的在线 API 与显式适配的实时语音前端，统一生命周期和恢复规则，但保留各后端实际能力差异。[离线语音模拟器](docs/20-voice-contract-simulator-zh.md)现可通过 `hermes personal-agent voice self-test` 验证窄范围合成契约，仅使用生成的静音，不接麦克风、语音模型、provider 或原生 turn。账户连接与真实语音仍未实现。

[本地检索指南](docs/22-local-task-search-zh.md)介绍标题/详情字面检索与有界分页。另有[原生语音 IPC 实验](docs/21-native-voice-ipc-experiment-zh.md)，包含可审阅的宿主补丁和验证记录；本插件不会应用或集成该补丁。

[本地项目分组](docs/24-local-project-groups-zh.md)增加显式任务标签、项目筛选和进度计数，并通过 schema-v3 升级保留旧回执。这些是本地分组，不是原生 Project 或权限范围。[host 命令上下文实验](docs/23-host-command-context-experiment-zh.md)另行打包未集成的身份观察补丁及剩余门禁，不启用 owner 授权。

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
