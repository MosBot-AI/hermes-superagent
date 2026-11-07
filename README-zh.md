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

[可插拔记忆方案](docs/30-pluggable-memory-contracts-zh.md)定义可替换的项目后端与用户自写适配器 SDK，默认采用 SQLite 记录/事件/FTS 加 Markdown 投影，并可选桥接实际 Hermes MemoryProvider。获准替换前保留现有原生 provider。下述显式本地记录及可选原生只读召回切片已实现该设计的有限部分；自动摄取、持久会话检查点及迁移仍待实现。

首个[显式本地记忆切片](docs/31-explicit-local-memory-zh.md)现支持在已有可信原生会话中使用 `/personal-memory remember`、`search`、`show`、`correct`、`forget` 和有界 `export`，需另行显式设置 `local_memory: true`。它通过小型内部后端接口使用独立 SQLite 存储，保留原生 provider，不自动召回/提取。命令/结果可能进入正常宿主历史；遗忘不会擦除该历史或备份。

[会话范围记忆工具](docs/32-session-scoped-memory-tools-zh.md)现通过独立 `memory_model_tools: true` 选项及 `/personal-memory-tools enable-read` 或 `enable-write` 激活，增加有界模型记住/查询/更正/遗忘。任务工具激活不授予记忆权限；模型编辑标记为 `activated_session_model`，不是经验证的人工指令，原生 provider 不变。已有记忆 DB 现原子升级到 schema v3，见下方持久化进度指南；真实 provider 自然语言验收仍待完成。

[本地任务操作历史](docs/34-local-task-history-zh.md)通过 CLI、`/personal-tasks history` 和已激活的任务读取工具返回按版本排列的元数据。重启后仍可查询，不返回任务旧正文；不验证作者、执行工作或对账原生 worker。

[离线 Worker 路由前置切片](docs/35-offline-worker-routing-zh.md)验证合成候选约束和合格基线，并覆盖部分固定版本原生契约。不调用 provider，不注册路由 backend，不启用在线 shadow 或自动切换。

[有界召回指南](docs/36-bounded-memory-recall-zh.md)新增原生记忆命令和独立激活读取工具的显式多关键词字面检索，返回完整记录、当前 revision，并限制序列化结果大小。不启用自动提示注入或原生 provider 替换。

原生 [`personal-agent routing inspect`](docs/38-routing-readiness-inspection-zh.md) 命令检查已保存本地 delegation 声明，不输出路由标识符或密钥。它提示继承/fallback/effort 的限制，不认证实际 session 路由，不调用模型或切换 backend。

[持久化进度指南](docs/37-durable-memory-progress-zh.md)新增纯元数据记忆变更分页和可跨重启保留的内部消费者游标。v1/v2→v3 迁移保留原始记录回执，不宣称支持原生压缩 checkpoint。

[每日任务回顾](docs/40-daily-task-review-zh.md)通过已有本地入口，一次提供逾期/今天/近期/无日期的精确数量与有预算的标题摘要。沿用当前读取准入，不新增调度或自动优先级决策。

[本地记忆元数据检查点](docs/39-local-memory-checkpoints-zh.md)：显式原生命令创建持久元数据标记，验证事件与记录一致性，检查水位并查询是否过时；不备份正文，也不满足原生压缩检查点。

[可选原生记忆召回](docs/41-native-memory-recall-zh.md): 显式选择真实 MemoryProvider 后，可为支持的原生主会话提供即时、有界的本地记录上下文；不摄取或改写规范记录，仍不支持严格原生检查点。

[本地任务进度指南](docs/42-local-task-progress-zh.md)新增明确的工作中/等待/阻碍说明、安全版本写入和过滤回顾。任务 schema v4 原子升级自有旧库并保留历史回执，已记录进度不等于原生执行证据。

[原生检查点证据边界](docs/43-native-checkpoint-boundary-zh.md)新增有界、无 I/O 的候选准备和固定宿主契约测试。验证稳定 UID、待存尾部与 revision 的实际边界；未启用自动摄取或 checkpoint-v2。

[可读任务工作台](docs/44-readable-task-workbench-zh.md)将已有原生任务命令展示为简洁文字，保留准确 ID、版本/重试说明和有界翻页。结构化原生输出使用 /personal-tasks --json ...，CLI 与模型工具 JSON 不变。

[显式记忆到期](docs/45-explicit-memory-expiry-zh.md) 增加明确 UTC 截止时间、默认到期过滤、主动检查和 schema-v5 迁移。到期影响新的召回资格，不改变存储状态或删除正文；原生只读召回永远不迁移存储。

[原生任务聚焦](docs/46-native-task-focus-zh.md)把一条明确选定的任务接入后续主代理对话轮次。任务工具激活后，`/personal-tools focus <task-id>` 每轮提供新的有界快照；`clear-focus`、禁用、到期和重启停止未来快照。不派发任务，也不清除此前模型/历史上下文。

[原子化项目计划](docs/47-atomic-project-plans-zh.md)通过一笔全部成功或全部回滚的事务和持久重试键，保存同一标签下明确要求的 1–20 条任务。原生命令、CLI 和已激活模型工具共享回执；这些任务可继续用于项目回顾、进度和聚焦。不派发 worker。

[会话自动记忆召回](docs/49-session-memory-recall-zh.md)现可在独立 `/personal-memory-tools recall-on` 授权后，把相关新鲜记录带入受支持主会话轮次。保留已有原生 provider，不新增模型请求或记忆写入，随激活过期/重载停止；不会擦除历史模型上下文。

[经审核的记忆候选](docs/50-reviewed-memory-candidates-zh.md)新增独立启用的当前原生输入草稿、精确引文和明确保留期限的原生接受流程。接受前不参与召回；到期清理是延迟执行，不新增额外模型请求或自动正式写入。

[项目任务依赖](docs/51-project-task-dependencies-zh.md)现可在开始/完成前执行明确的同项目先后约束，并在 ready 队列、review 和 focus 中提供新鲜依赖快照。取消前置仍会阻塞，不启动 worker 或修改原生 Kanban。

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

成功的推送构建现附带[经过校验的离线运行包](docs/runtime-distribution-zh.md#下载推送构建的运行包)：确定性归档、完整官方静态扫描发现，以及冷进程实际运行包的 CLI/重载验收。这是可下载的开发产物，不是正式发行或重试安装的许可。

## 在隔离 Hermes 中试用

最近一次官方完整仓库安装被未修改的安全扫描器阻断（CAUTION，50 条发现），插件未安装或启用。不要覆盖该拒绝。[离线运行时分发构建器](docs/runtime-distribution-zh.md)生成保留原始字节及来源证明的包，但不会扫描、安装或授权再次尝试。下文是后续单独审阅后的安装说明，不代表验收通过。

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

[任务到 worker 的提案](docs/48-task-worker-proposal-zh.md)新增仅供审阅的宿主补丁与具体实验消费者，为明确授权的单任务生成规划草稿。隔离提案现包含专用 no-redirect 客户端、保守的持久草稿/重试回执及可读的原生请求工作台（列表、状态、保存草稿、提交前停止）。未启用生产派发、工具执行、提供商结果不明的自动恢复或真实模型验收。

## 停放式原生 Kanban 交接

[明确预览/提交交接](docs/52-parked-kanban-handoff-zh.md)可将本地任务停放到明确指定的共享原生看板。默认关闭，不设置受派者或派发工作，不重试不明结果。注册和状态不探测原生存储；操作时的兼容检查与真实验收仍是独立门槛。

[建议性原生进度同步](docs/53-native-progress-observation-zh.md)明确观察身份已绑定的停放卡片，并写入本地任务。原生 done 不等于本地完成，不自动同步或派发。

新增[已存原生观察关注复盘](docs/54-saved-native-attention-zh.md)：只读本地快照，重叠分类不重复计数，不读取实时看板或改变完成状态。

[受门控的任务规划 worker](docs/55-gated-plan-worker-zh.md): 生产包接线默认关闭，要求准确已审阅宿主约定及当前同意，不代表安装或真实验收。

[原子计划明确依赖](docs/56-atomic-plan-dependencies-zh.md): 显式一基批次引用，同事务保存任务与边，不自动执行。

[明确任务拆解](docs/57-task-breakdown-zh.md): 原子记录步骤、继承前置，并让父任务依赖全部新步骤；不自动执行或完成。

[原生结果审阅与明确本地接受](docs/58-native-result-review-zh.md): 直接审阅不可信卡片结果，再凭重新核对的摘要及人工说明完成本地任务；不自动完成或修改原生卡片。
