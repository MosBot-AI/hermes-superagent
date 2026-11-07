# 34. 本地任务操作历史

[English](34-local-task-history.md) | 简体中文

已实现：通过 CLI、原生 `/personal-tasks` 命令和单独激活的 `personal_tasks_read` 工具，分页查询已有本地任务的操作历史。这只是 E2.1/E3.5 中一小部分恢复辅助能力，不是原生 worker 对账、任务执行、提醒或新的授权入口。

## 1. 查询已保存的进度

沿用受信任的单用户 profile 和既有[本地任务启用方式](16-local-task-inbox-zh.md)。把下面的 TASK_ID 换成 `list`、`search` 或 `show` 返回的任务 ID：

```text
hermes personal-agent tasks history TASK_ID --limit 20
hermes personal-agent tasks history TASK_ID --after-revision 20 --limit 20
/personal-tasks history TASK_ID --limit 20
/personal-tasks history TASK_ID --after-revision 20 --limit 20
```

原生 slash 命令仍要求 `local_conversation: true` 和宿主会话准入。模型调用仍要求已有的 `local_model_tools: true`，以及当前 `/personal-tools enable-read` 或 `enable-write` 激活。本功能不增加设置项或激活入口。读取工具支持：

```json
{"action":"history","task_id":"00000000-0000-4000-8000-000000000001","limit":20,"after_revision":0}
```

示例 UUID 是合成值。实际请求应使用真实返回的 ID，不要直接复制示例。写入结果不确定时，模型可以查看历史，但仍应通过 `show` 读取当前内容并核对原始请求。历史不返回 request ID，不证明某个重试键已经提交，也不能替代使用原稳定键和完全相同参数重试。

## 2. 有界结果与游标约定

历史在各入口现有的 `data` 响应中返回 `task_id`、`current_revision`、`current_state`、`items`、`has_more` 和 `next_cursor`。每条记录仅包含 `revision`、`operation` 和原始 UTC `timestamp`。操作值为 `capture`、`update`、`progress`、`complete` 或 `cancel`，按任务版本递增排列。不返回任务标题、详情、项目标签、旧字段值、完成说明或回执正文。

`limit` 默认为 20，接受 1 至 100 的整数。`after_revision` 默认为 0，表示从头开始。非末页需要继续时，将整数 `next_cursor` 传入 `after_revision`，并保持**同一个任务 ID**。它与其他读取操作使用的字符串 `after` 字段不同。正数游标必须对应该任务已有的事件；未来或缺失的版本返回 `invalid_cursor`。未知任务 ID 返回 `not_found`。类型错误、无关字段、缺失 ID 和越界参数返回既有的脱敏 `invalid_request` 错误。

每页的当前元数据与事件共享一个 SQLite 读取快照。分页是实时视图，不是冻结导出：如果另一操作已经提交，后续页面的当前版本可能增大。即使系统时间相同或发生回拨，版本号仍提供顺序。成功请求重放，或因旧版本、幂等冲突被拒绝，都不会添加事件。末页返回 `has_more: false` 和 `next_cursor: null`；从当前版本之后读取会得到空列表。如需检查之后新增的事件，请保留最后一条事件的版本，而不是空游标。

## 3. 持久化、隐私与边界

历史复用既有 `events` 表，本身不新增迁移、自动摄取或后台工作。[任务进度后续切片](42-local-task-progress-zh.md)将任务库升级为 schema v4 并新增 progress 操作，同时保留旧事件。元数据在插件重载与进程重启后仍可查询。操作本身使用延迟读取事务；既有存储入口仍进行标准 schema 校验或受支持的旧版本升级。

这是操作元数据，不是已验证作者的审计或对话记录。它不区分 CLI、slash、模型作者，不记录具体字段变化，不重建任务旧内容，也不能证明现实中的工作已完成。`complete` 仅表示本地记录被标为完成。本功能不解决完整任务保留、恢复、删除策略或原生 Kanban/worker 对账要求。

元数据仍可能属于个人信息。模型工具结果会进入当前模型上下文及正常宿主历史，与其他[任务工具](29-session-scoped-task-tools-zh.md) 共享隐私、费用和保留边界。每次读取仍检查 profile、会话、路由、turn 和 TTL。插件只读模式、不支持的来源、未激活、disable 和 unload 等限制不会被 `history` 绕过。不新增远程接口、第二次模型调用、调度任务或外部操作。

## 4. 验证

合成单测覆盖活动与终态任务、有序分页与上限、私密正文不返回、成功重试去重、失败写入行为、任务隔离、并发追加时单页读取一致性、持久化、旧版本迁移、参数校验，以及注入故障后的事务清理。固定宿主契约覆盖真实 CLI 重载、原生 slash 派发、激活后的模型工具派发、只读激活、不同会话/无 turn/disable 拒绝及游标错误处理。

测试使用临时 profile，不使用凭据、真实模型或网络调用。原有真实 provider 自然语言验收仍未完成；确定性历史契约通过不代表 E3.5 或 M1 的端到端验收完成。
