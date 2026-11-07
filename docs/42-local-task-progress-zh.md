# 42. 持久化本地任务进度

[English](42-local-task-progress.md) | 简体中文

已实现：为已有活动本地任务明确记录工作中、等待和阻碍状态。CLI、原生 `/personal-tasks` 命令及已激活任务模型工具共享版本、持久回执和进度过滤。它推进本地任务恢复与回顾，不派发 worker、不验证原生执行、不建立依赖图，也不完成 E3.2/E3.5。

## 1. 记录进度更新

沿用已有[可信本地任务配置](28-profile-first-local-conversations-zh.md)，使用 `show`、`list` 或其他成功结果返回的真实任务 ID 和当前 revision。每次更新都要求工作状态和非空说明。

```text
hermes personal-agent tasks progress TASK_ID --expected-revision 1 --work-status in_progress --note "Started reviewing the draft" --request-id progress-1
/personal-tasks progress TASK_ID --expected-revision 2 --work-status blocked --note "Waiting for the missing attachment" --request-id progress-2
/personal-tasks progress TASK_ID --expected-revision 3 --work-status ready --note "Attachment received; ready for review" --request-id progress-3
/personal-tasks list --work-status blocked --project "Demo"
/personal-tasks review --on 2026-11-07 --work-status waiting
```

CLI 修改必须提供 `--request-id`。原生会话命令与其他既有写入一样，省略时可生成并返回新 key。结果不明确时，应使用完全相同的命令和 key 重试，新 key 不是安全重试。通过 `personal_tasks_write` 调用进度写入还要求既有模型写权限激活：

```json
{"action":"progress","task_id":"00000000-0000-4000-8000-000000000001","expected_revision":3,"request_id":"progress-3","work_status":"ready","note":"Attachment received; ready for review"}
```

UUID/日期为合成示例，不是实际任务引用。模型工具必须使用存储返回的 ID 和 revision，仅记录用户明确要求的本地进度。已激活模型活动不等于已验证的人类指令证据。不新增配置、注册、权限或模型调用。

## 2. 生命周期与工作进度分开

原有生命周期仍为 `captured`、`done` 或 `cancelled`。活动任务的 `state` 为 captured，记录进度不会完成、取消或重新打开任务。`work_status` 只能取：

- `ready`：未记录正在工作、等待或阻碍标签。这是初始值，不表示已经满足验收条件或执行授权。
- `in_progress`：明确记录本地工作已开展，不证明某个原生进程或 worker 当前存活。
- `waiting`：明确暂停，等待输入或其他事件。不创建监控、期限或自动恢复。
- `blocked`：明确存在阻碍，无法继续。不从说明中推断依赖或升级处理。

每个活动任务可以转为以上任意状态，也可保留相同状态并更新说明。每个新接受的请求只增加一次任务 revision，更新 `updated_at` 和 `progress_updated_at`，保存当前 `progress_note`，并追加一条 `progress` 元数据事件。`note` 接受 1–2000 个字符，必须含非空白文本，并遵守既有多行/控制字符校验。

任务 `update` 不能修改进度字段，会保留已有状态、说明和时间戳。明确更改必须使用 `progress`，包括用 ready 和说明解除阻碍。进度操作不修改截止日期、项目、标题或详情，活动记录的 `resolved_at` 和 `resolution_note` 保持未设置。完成/取消保留最后的进度值作为历史上下文，而生命周期进入终态。后续进度更新返回 `terminal_state`；已完成任务残留的 blocked 值不表示活动阻碍。

## 3. 查看进度与安全重试

完整任务读取返回 `work_status`、`progress_note` 和 `progress_updated_at`。`list`、标题/详情字面 `search`、`agenda` 和[每日回顾](40-daily-task-review-zh.md)支持可选的 work_status 精确过滤，可与既有项目/未分组过滤组合。list/search 使用工作状态过滤时，state 必须省略或为 captured。终态记录仍可通过普通 show 或不带进度过滤的状态读取查看。搜索有意不检索进度说明。

每日回顾返回所有匹配活动任务的 `progress_counts`，键为 ready、in_progress、waiting 和 blocked，其总和等于 `counts.total_active`。摘要条目包含 work_status，不包含进度说明和时间戳。既有共享输出预算与同一快照行为保持不变。总数覆盖全部匹配任务，即使部分摘要被省略；它不是 worker 健康指标。

历史只展示 revision、操作和时间戳，不展示进度说明或之前的工作状态。当前说明可替换，但旧写回执、普通宿主历史和备份可能保留之前的文本。它不是私密的追加工作日志或已验证作者审计，编辑说明也不等于擦除。

所有写入复用既有任务级比较交换和幂等契约。旧 revision 返回 `revision_conflict`，应先读取当前状态并核对，再做新的更改。同一 key 配不同参数返回 `idempotency_conflict`。成功请求的完全相同重试返回原始保存回执与 `replayed: true`，即使后续已经发生更新。该旧回执不是任务当前状态，需要当前状态时使用 show。结果不明确不会触发自动重试或额外工作。

## 4. 原子任务 Schema v4 升级

新任务库使用 schema v4。精确认识的自有 v1/v2/v3 数据库在既有单事务内升级：按需保留原有截止日期/项目升级，再添加 work_status、progress_note 和 progress_updated_at。已有记录获得 ready、空说明和 null 进度时间戳，不为活动或终态记录推断过往活动。

任务 ID、原字段、序列顺序、revision、事件行和回执字节保持不变。旧成功请求重试保留原响应形状，因此旧回执可能没有新字段。新 show/list 返回当前完整形状。新建与迁移后的库拥有相同的受检查 DDL。未知/修改后的 schema、额外索引/触发器/表及外部数据库仍会拒绝，不自动修复。任何迁移步骤失败都会回滚整个升级。

任务 schema v4 与独立记忆数据库版本无关。既有私有文件/profile 保护不变。旧插件会拒绝新任务 schema，本切片不提供自动降级、重建表或恢复流程。升级任何真实 profile 前保留受支持的备份，不要在宿主使用数据库时替换文件。测试只使用一次性合成 profile，本开发过程没有迁移生产数据。

## 5. 准入、隐私与证据

既有来源、profile、会话、turn、TTL 和卸载门禁适用于所有读写。enable-read 不能记录进度。缺少写激活、错误会话/来源、旧 revision、终态和无效字段都不会修改数据。进度文本是普通明文本地任务数据，不是秘密存储；完整任务结果按既有激活契约进入所配置模型上下文和宿主历史。插件不会验证每句话的作者，也不保护其他宿主工具。共享/暴露网关和不支持的隔离路径仍不在适用范围。

测试覆盖全部状态转换、说明替换、生命周期不变、终态拒绝、并发 CAS、后续编辑/重启后的重放、精确项目/状态过滤、同一快照回顾数量、回顾/历史不返回说明、失败回滚，以及独立构造的 v1/v2/v3 迁移和回执保留。固定 Hermes 契约覆盖 CLI 重载、原生命令至模型的连续性、读/写激活、错误会话/缺少 turn/禁用后的拒绝及脱敏校验失败。单元与原生契约均离线，不声称已完成真实 provider 自然语言验收、原生 worker 对账、提醒或外部行动。
