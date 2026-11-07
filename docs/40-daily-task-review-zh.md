# 40. 有界每日任务回顾

[English](40-daily-task-review.md) | 简体中文

已实现：通过已有 CLI、原生 `/personal-tasks` 命令和已激活的 `personal_tasks_read` 工具，一次只读获取本地活动任务概览。精确数量与有界标题摘要帮助用户检查承诺，不必读取每项任务详情。它不是自动规划器、提醒、优先级模型或任务执行器。

## 1. 使用现有本地入口

沿用已有[本地任务配置](16-local-task-inbox-zh.md)，不新增设置或权限。下列日期为合成示例，使用时应明确提供目标日历日期。

```text
hermes personal-agent tasks review --on 2026-11-07
/personal-tasks review --on 2026-11-07 --project "Demo"
/personal-tasks review --on 2026-11-07 --unassigned --lookahead-days 14
/personal-tasks review --on 2026-11-07 --per-bucket-limit 3 --max-chars 8000
```

原生命令仍要求可信单用户 profile 中的 `mode: local_tasks` 和 `local_conversation: true`。模型读取还要求 `local_model_tools: true`，以及同一原生会话内有效的 `/personal-tools enable-read` 或 `enable-write` 激活。模型请求如下：

```json
{"action":"review","on":"2026-11-07","lookahead_days":7,"per_bucket_limit":5,"max_chars":16000,"project":"Demo"}
```

`project` 与 `unassigned` 可选且互斥。项目标签精确匹配，区分大小写，标点按字面值处理。`unassigned: true` 选择无标签任务，false 不过滤。不新增项目实体、原生 Kanban 映射或跨 profile 读取。Review 不接受 `limit`、`after`、`state`、写字段或调用者自报的身份/上下文。

## 2. 日期、数量与摘要顺序

`on` 必须是有效的 `YYYY-MM-DD` 日期，不推断系统时钟、地点或时区。`lookahead_days` 为 0 至 90 的整数，默认 7。响应中的 `through` 是 `on` 加上对应日历天数，近期分组包含该截止日。日期溢出会被拒绝，不会自动截断。

仅统计当前处于 `captured` 状态的任务。数量涵盖所有匹配的活动任务，包括未展示摘要的任务：

- `overdue`：截止日期早于 `on`。
- `due_today`：截止日期等于 `on`。
- `upcoming`：截止日期晚于 `on` 且不晚于 `through`。
- `later`：截止日期晚于 `through`，只提供数量，不抽样标题。
- `undated`：没有截止日期。
- `total_active`：以上五个互斥分组的数量之和。

四个摘要分组为 `overdue`、`due_today`、`upcoming` 和 `undated`，均包含 `total`、`items` 和 `omitted`。有日期的条目先按截止日期、再按最初录入顺序排列；无日期条目按最初录入顺序排列。这种确定性顺序不推断重要性、工作量、阻碍或执行意愿。已完成和已取消任务不计入。前瞻天数为零时，近期分组为空，所有未来有日期任务计入 later。

每条摘要仅含 `id`、`title`、`project`、`due_date` 和当前 `revision`。不会加载或返回详情、完成说明、receipt 或操作历史。标题和项目标签仍可能含有个人信息或不可信文本，读取器不会执行其中指令。决定修改前可用 `show` 查看当前完整详情，revision 仍受正常的比较交换检查约束。

## 3. 输出上限与快照语义

`per_bucket_limit` 默认为 5，允许 1 至 20 的整数。`max_chars` 默认为 16000，允许 2048 至 64000 的整数。布尔值、浮点数、字符串和 null 均不能代替整数。预算按 `len(json.dumps(data, ensure_ascii=True, sort_keys=True))` 衡量，包含日期、过滤、数量、分组元数据和完整摘要，不含外层 CLI/命令/工具响应包。它是 ASCII 序列化字符预算，不是 token 估计或 provider 总上下文上限。

摘要按逾期、今天、近期、无日期的分组顺序尝试加入。某分组的下一条完整摘要超出预算时，停止该分组；后续分组仍可能容纳较短摘要。标题、ID 和 revision 不会截断。`omitted = total - len(items)` 同时覆盖单组上限和共享预算造成的省略。总数大于零但 items 为空表示摘要被省略，并非没有任务。Review 不提供分页游标；要进一步检查，可用既有 `list`、`agenda`、`search` 和 `show` 读取器。`later` 有意只提供数量。

全部数量与摘要共享一个延迟 SQLite 读取事务，并发更改不会让单次结果混入更改前后两种状态。下一次回顾是新快照，可能不同。不承诺持久快照、完成证明或跨调用冻结游标。读取失败释放事务并保留任务、事件和 receipt。已有自有 v1/v2 存储沿用 schema-v3 升级，本功能不新增迁移。

## 4. 隐私、准入与验证

既有 profile、来源、会话、活动 turn、TTL、撤销和卸载门禁保持不变。默认只读模式不打开任务存储。模型结果进入所配置模型上下文和正常宿主留存，摘要预算不会让传输变成离线。本插件不保护其他 Hermes 工具。不要在暴露/共享网关上启用本地路线，也不要为开放此入口禁用隔离。

Review 不新增后台任务、原生 blueprint 任务访问、自动提示注入、通知、模型/provider 调用或外部行动。明确的原生命令只在既有存储打开器验证或升级后执行确定性的本地读取。它不完成真实 provider 自然语言验收或完整 M1 发布门禁。

合成测试覆盖日期/闰年边界、精确数量和过滤、完整摘要/Unicode 预算、稳定顺序、省略数量、终态排除、并发更改、读取失败回滚、旧版本迁移和重启。固定宿主契约覆盖 CLI 重载、原生命令/模型结果一致、当前读取激活、无效参数、错误会话/来源、缺少 turn 和禁用后的拒绝。全部测试使用临时 profile 和网络保护，不使用凭据或个人账号。
