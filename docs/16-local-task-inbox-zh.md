# 16. 显式启用的本地任务收件箱

[English](16-local-task-inbox.md) | 简体中文

**已实现的开发切片，不是完整 personal agent。** 受信任的本地操作员可以通过真实 Hermes CLI 录入、查看、编辑、完成和取消插件自有任务，记录跨进程重启保留。本切片不启用模型、HTTP、个人数据会话斜杠命令、Bot 绑定、调度器、原生 Kanban 或外发动作入口。

测试基线仍为 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`、Python 3.14.9。这是 E2.1 的有限本地前置切片，不代表 E1、E2 或 M1 完成。[完整路线](08-roadmap-and-acceptance-zh.md)与受控写发布门槛仍然有效。

仅含日期的截止日期与 agenda 已作为兼容扩展提供；命令、迁移及旧 receipt 语义见[文档 17](17-local-task-agenda-zh.md)。

标题/详情字面检索通过相同本地门禁提供；匹配与分页语义见 [22](22-local-task-search-zh.md)。

[本地项目分组](24-local-project-groups-zh.md)增加标签、筛选和进度计数。当前任务视图包含可空 `project`，当前 schema 为 v3，旧回执保持原样。

## 1. 范围与信任边界

- 默认 `mode: read_only` 仍在打开插件存储之前拒绝任务命令。两种模式下 status 和 coverage 都不打开任务存储。
- 显式 `mode: local_tasks` 只启用本地 CLI 对本插件收件箱的操作，不改变 delegation、凭据、工具权限或原生项目/任务/调度状态。
- 注册的模型工具仍只有 `personal_agent_status`，只报告能力/配置，不读取任务记录。没有任务数据工具、HTTP 路由、个人数据会话斜杠命令或从消息自动录入的入口。独立的访问诊断不读取此收件箱。
- 这里信任本地 OS 账号和选定的 Hermes profile。CLI 命令不是人类 owner 的密码学证明；profile 标签、任务 ID 和 `source: local_cli` 也不是授权凭据。
- 它不隔离 shell/Python 工具、其他插件、同 UID 进程或任意文件系统替换竞态，不能代替 E1 身份/动作授权。不要通过不可信远程执行器暴露该 CLI。
- 个人任务内容以明文保存在本地并输出到命令行；命令参数可能出现在 shell 历史和进程列表。不要将凭据或秘密写入任务字段。本切片没有实现加密、安全输入 UI、导出/遗忘/备份策略或远程身份。

首个支持的存储平台是具备 `O_NOFOLLOW` 的 POSIX。Linux 已测试，macOS 尚未真机认证，Windows 存储被明确拒绝，但诊断仍可用。支持 Windows 忽略文件不等于支持其运行时存储。

## 2. 启用与使用

先按[设置说明](../README-zh.md)使用隔离且通过兼容验证的 Hermes profile。添加下面的显式启用配置时，保留全部已有插件设置：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
```

CLI 仍要求固定宿主的 `in_process` 插件模式。Host isolation 不支持 `register_cli_command`，不要只为此功能关闭已有隔离设置。修改 `mode` 不等于安装插件，也不代表其他宿主版本兼容。

```bash
hermes personal-agent tasks capture \
  --title "准备每周回顾" \
  --details "检查未完成承诺并附上来源。" \
  --request-id review-capture-001
hermes personal-agent tasks list --state captured --limit 20
```

复制返回的 UUID 和当前 revision。下面示例使用 shell 占位值，运行前须替换成真实任务 ID/revision：

```bash
TASK_ID="capture 返回的 UUID"
hermes personal-agent tasks show "$TASK_ID"
hermes personal-agent tasks update "$TASK_ID" \
  --expected-revision 1 --title "准备并核验每周回顾" \
  --request-id review-edit-001
hermes personal-agent tasks complete "$TASK_ID" \
  --expected-revision 2 --note "本地操作员已手动检查。" \
  --request-id review-complete-001
hermes personal-agent tasks list --state done
```

`cancel` 与 `complete` 使用相同的 revision、request-ID 和 note 参数。`update` 可修改 title、details 或两者；显式空 details 字符串会清空详情。这些命令不启动 worker 或发送提醒。完成仅记录本地操作员的声明，不是外部动作或原生 worker 成功的证据。

## 3. 命令契约

| 命令 | 必需输入 | 结果 |
|---|---|---|
| `tasks capture` | title、request-id；可选 details | 新 UUID 任务，状态 captured，revision 1 |
| `tasks list` | 可选 state、limit、after | 最新优先的有界分页，含 next_cursor/has_more |
| `tasks show` | Task UUID | 当前任务，包括终态 |
| `tasks update` | UUID、expected-revision、request-id、title 和/或 details | 编辑 captured 任务并增加 revision |
| `tasks complete` | UUID、expected-revision、request-id、note | 明确本地命令将任务标为 done |
| `tasks cancel` | UUID、expected-revision、request-id、note | 明确本地命令将任务标为 cancelled |

在打开存储之前完成校验。未知操作/字段、不规范的 UUID4 ID、布尔 revision、空更新、不安全控制字符和越界值均被拒绝。Title 为单行 1–240 字符，details 最多 5,000 字符，结束说明为 1–2,000 字符。Details/note 允许换行和 tab，但拒绝其他控制/格式字符。Request ID 为 1–128 个 ASCII 字母、数字、点、下划线或连字符。

List 状态支持 captured（默认）、done、cancelled、all；limit 默认 20，范围 1–100。将返回的 next_cursor UUID 传给 `--after`。这是本地 keyset 分页，不是持久变更流或跨页面一致快照。其他 profile 的任务不是本数据库中的有效 cursor。

成功结果均包含 `schema_version: personal.local-tasks.v1`、`status: ok`、`scope: trusted_local_cli_only`、data、replayed 和 `error: null`。List 的 data 包含 items、next_cursor、has_more。任务包含 id、title、details、state、revision、created_at、updated_at、resolved_at、resolution_note、source，当前视图另含可为 null 的 due_date。事件时间为 UTC；due_date 是不推断时区的日历日期。历史 receipt 可能缺少 due_date，见[文档 17](17-local-task-agenda-zh.md)。

```json
{
  "schema_version":"personal.local-tasks.v1",
  "status":"error",
  "scope":"trusted_local_cli_only",
  "data":null,
  "replayed":false,
  "error":{"code":"revision_conflict","retryable":false}
}
```

CLI 成功退出码为 0，已处理操作失败为 1，argparse 用法错误为 2。错误结果不回显任务文本、SQL 或私人路径。稳定错误码包括 local_tasks_disabled、profile_context_changed、invalid_request、not_found、invalid_cursor、revision_conflict、terminal_state、idempotency_conflict、unsafe_storage_file、unsafe_storage_path、foreign_database、unsupported_schema。意外宿主/文件系统失败统一为 local_tasks_unavailable，不静默重置或切换存储。

## 4. 事务、重放与生命周期

收件箱是本地展示记录，生命周期为 `captured → done / cancelled`；终态任务不能编辑或重新打开。它不是完整领域 Task 状态机或原生 Kanban 执行生命周期。未来接入须明确映射/迁移，不能假设这些记录已经是派发任务。

每次变更都要求稳定 request ID。数据库在同一个 `BEGIN IMMEDIATE` 事务中记录操作与校验后 payload 的摘要、结果 receipt、任务和最小事件。先检查 receipt 重放，再判断现已过期的资源 revision。同一 request ID 换内容/操作会返回 idempotency_conflict。两个并发相同请求只产生一个任务/转换。

**重放返回原始 receipt，不一定是当前任务。** 结果标记 `replayed: true`；当前状态请使用 `tasks show`。例如完成任务后重放 capture，仍返回 revision-1 的录入 receipt，而 show 返回 done 任务。不要把重放 receipt 当成最新读取。

变更在同一事务中比较 expected_revision，仅增加一次 revision。竞争更新返回 revision_conflict。事务失败时任务、事件和 receipt 一起回滚。CLI 响应丢失可用相同 request ID/payload 重试；换新 key 表示新操作，不是恢复方法。本切片没有远端 effect，因此不声称分布式 exactly-once。

首个 schema 在本地保留 receipt，不自动过期；没有新增删除、自动清理、备份恢复或遗忘命令。Schema 升级另见[文档 17](17-local-task-agenda-zh.md)。这是开发限制，不是完整个人数据保留策略。

## 5. 存储与 Profile 安全

使用文档公开的 `plugins.plugin_storage.plugin_data_dir()` 解析当前 profile 的插件数据目录 [S1、S2]，随后用 Python SQLite 只打开本插件的 tasks.sqlite3。运行数据不写入安装目录或宿主 Projects/Kanban/cron 数据库。Local_tasks 模式首次使用（包括 list）会初始化此自有存储；默认诊断和 read_only 模式不会。

Handler 注册时记录解析后的 profile，任务访问前再次检查，并且在调用宿主配置读取器**之前**确认 profile 仍存在，因为该读取器可能重建已删除的 profile。每条任务命令重新读取 mode。Profile 改变、配置无效或切回 read_only 后，下一命令被拒绝。此命令 gate 不是针对任意并发 OS 活动的事务式硬撤权服务。

主文件以 0600 创建。已有主文件/journal/WAL/SHM 必须是当前 UID 所有、单硬链接、私有权限的普通文件。已有 profile/plugin-data/插件目录必须由当前 UID 所有，且不能允许 group/world 写入。不安全链接或权限被拒绝，不 chmod、unlink、截断或修复。这些检查防止已测试的预置文件风险，不承诺防竞态的文件系统隔离。

SQLite 使用默认 rollback journal、synchronous=FULL、foreign keys，并关闭 trusted_schema。插件不绕过宿主兼容控制独立启用 WAL。事务式核验应用所有权 marker 与受支持 schema，精确 v1/v2 存储现按[文档 24](24-local-project-groups-zh.md)升级到 v3，承接[文档 17](17-local-task-agenda-zh.md)中的原始日期扩展；外来、修改、损坏或更新版本的 schema 均 fail closed，不静默替换原数据库。手动恢复前先保留原文件并调查原因。

原生存储约定下，插件数据在安装更新/卸载后仍保留 [S1]。停用或删除插件不等于删除数据，不能把 uninstall 当作遗忘。

## 6. 为什么没有加入原生只读概览

源码核验和合成探针表明，在此固定版本上不能提供误导性的“原生只读概览”：

| 原生操作 | 观察到的限制 |
|---|---|
| Project list | 打开存储会初始化/迁移表 [S3] |
| Kanban list | 调用 recompute_ready，可能改变任务状态；板库跨 profile 共享 [S4、S5] |
| Cron list | 创建目录，可能修复/重写旧 job 存储，列表无界 [S6] |

把这些操作包进只读工具，不会消除其副作用或建立 owner 隔离。本切片不调用它们、不私读其数据库 schema、不启动 gateway，也不把原生数据不可用说成零任务。收件箱映射到原生工作之前，E0.3 仍须核验受支持的原生契约。

## 7. 验证与剩余门槛

源码与真实宿主测试覆盖校验、重放/重启、并发同 key 录入/更新、revision 竞争、事务回滚、外来/新版/损坏 schema 拒绝、有界分页、模式变更、profile 切换/删除、默认存储惰性及错误脱敏。存储回归覆盖主文件和三类 SQLite sidecar、硬链接/符号链接、宽权限文件及可写目录。真实顶层 CLI 子进程使用干净环境和 socket-connect guard。

验证使用合成临时 profile，不涉及个人账号、手机、真实 Bot 绑定或生产数据，不需要模型/provider 调用或 API Key。使用[完整仓库检查器](../README-zh.md#开发验证)运行单元、lint/type、双语文档及固定宿主契约检查。准确数量与 CI 属于测试过的 commit，不是后续编辑必定通过的承诺。

开放 agent/渠道/HTTP 访问之前，须完成 E1 验证身份、源 scope、动作策略与审计，完成相关 E0.4 路径，设计 E2 迁移/保留边界，并单独验证原生 adapter。可选主 Bot 和客户端方案不会因本地收件箱可用而自动启用，受控写发布门槛仍保持阻断。

## 8. 固定来源

- S1：[官方插件持久存储说明](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#store-durable-state)。
- S2：[按 profile 解析的插件存储 helper](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/plugins/plugin_storage.py)。
- S3：[Project 存储打开/初始化行为](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/projects_db.py)。
- S4：[Kanban list 与 readiness 重算](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/kanban_tools.py)。
- S5：[共享 Kanban 板存储](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/kanban_db.py)。
- S6：[Cron 存储加载、修复和列表](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/jobs.py)。
