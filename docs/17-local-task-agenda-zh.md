# 17. 本地截止日期、Agenda 与 Schema 升级

[English](17-local-task-agenda.md) | 简体中文

**已实现的本地 CLI 扩展，不是提醒投递。** 显式启用的[本地收件箱](16-local-task-inbox-zh.md)现支持仅含日期的截止日期，并提供指定日期的待办概览。仍沿用本地操作者与 profile 边界，不启用模型、渠道、HTTP、worker、调度器、主 Bot 绑定或对外动作。

本切片推进 E2.1 本地存储先导功能及 E8.3 schema 兼容测试，不代表 E1、E2、E4 或 M1 已完成。Hermes 仍固定在 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`，无需新的宿主 API 或 provider 凭据。

**当前 schema 提示：** 第 4 节记录最初的 v1→v2 日期扩展。当前插件为[项目分组](24-local-project-groups-zh.md)创建 schema v3，或将精确匹配的 v1/v2 存储升级至 v3；新增可空 `project` 列不改变日期语义或旧回执。

## 1. 日期就是日历日期

`due_date` 是可选的公历日期，严格采用 `YYYY-MM-DD` 格式，不是时间戳或提醒 occurrence。截止日期为 2028-02-29 的任务不会被推断出小时、偏移量、时区或投递期限。日期必须真实存在，闰日也会校验。空白、其他格式、自然语言、时间戳及错误类型会在打开任务存储前被拒绝。

Agenda 必须提供 `--on`，不会暗中使用电脑日期或推测用户所在地。由操作者选择比较的日历日期。`due_date < on` 表示已过期，`due_date == on` 表示当天到期。无日期、未来日期、已完成及已取消的任务均不纳入结果。

具体时刻、IANA 时区、夏令时、重复周期、安静时段及真实投递仍需实现 E4 契约。不要把仅含日期的值转成午夜，也不要承诺会收到通知。

## 2. 命令

按照[文档 16](16-local-task-inbox-zh.md)，先在隔离且经过测试的 profile 中启用 `mode: local_tasks`。原有命令保持兼容。

```bash
hermes personal-agent tasks capture \
  --title "Prepare the weekly review" \
  --due-date 2028-02-29 --request-id dated-capture-001
hermes personal-agent tasks agenda --on 2028-02-29 --limit 20
```

使用 capture 或 show 返回的真实 UUID 与当前 revision：

```bash
TASK_ID="UUID returned by capture"
hermes personal-agent tasks update "$TASK_ID" \
  --expected-revision 1 --due-date 2028-03-01 --request-id dated-edit-001
hermes personal-agent tasks update "$TASK_ID" \
  --expected-revision 2 --clear-due --request-id dated-clear-001
```

update 的 `--due-date` 与 `--clear-due` 互斥。清除对应显式 `due_date: null`；两者都省略时保留当前值。capture 接受可选日期字符串，不接受清除标志。更新可以只修改日期，也可同时修改标题或详情，原有 revision、终态与 request-ID 规则仍适用。

| 操作 | 日期契约 | 结果 |
|---|---|---|
| `capture` | 可选 `due_date` 字符串 | 当前任务包含日期或 null |
| `update` | 可选日期字符串或显式 null | 设置或清除日期，revision 递增一次 |
| `show` / `list` | 无新增必填输入 | 当前任务包含可为 null 的 `due_date` |
| `agenda` | 必填 `on`，可选 limit 与 after | 截至 on 到期的有效任务，最早到期者优先 |

响应 envelope 仍为 `personal.local-tasks.v1`。当前任务视图新增 `due_date`。Agenda 的 data 包含 `on`、`items`、`next_cursor` 与 `has_more`。limit 默认 20，范围 1–100。保持相同 `--on` 日期，把返回的 UUID 作为 `--after` 获取下一页。

## 3. Agenda 排序与并发变更

按 `due_date` 升序排序，同一天按创建 sequence 升序排序。查询最多读取 limit 加一行，因此命令输出与结果集都有上限。这是实时 keyset 分页，不是跨页一致快照或 change feed。

cursor 在当前 profile 自有存储中解析。cursor 不存在、没有日期或晚于 on 时返回 `invalid_cursor`。两页之间已完成但仍有日期的任务可以继续作为下一页锚点，尽管它已不在 agenda 中。两页之间修改日期可能移动锚点或改变集合，造成遗漏或重复；需要新概览时从第一页重新查询。更换 on 日期后复用 cursor 会改变查询，不再是原视图的连续读取。

完成或取消任务会将其排除在后续 agenda 查询之外，但不会删除任务、日期或原 receipt。修改或清除日期是普通原子更新，不是创建或取消调度任务。

## 4. v1 到 v2 的事务式 Schema 迁移

插件只拥有本 profile 的 `tasks.sqlite3`。打开之前仍执行原有 profile、文件及 sidecar 检查。显式 local_tasks 模式下，首个有效任务命令会初始化全新 v2 存储，或升级严格识别出的 v1 存储。这也包括 list、show 与 agenda：逻辑读取可能进行插件自有存储的初始化或迁移。status、coverage 及 read_only 拒绝不会打开或迁移任务存储。

迁移在 `BEGIN IMMEDIATE` 中检查应用所有权标记及精确支持的 v1 schema，新增可为 null 的 `due_date`，更新 schema version 后原子提交。既有任务 ID、revision、创建/更新时间、事件及 receipt 字节均保持不变。旧任务没有截止日期。全新 v2 与升级后的 v2 必须通过相同 schema 校验。

提交前发生失败，会同时回滚 schema 与版本变更；解决原因后可在原存储上重试。并发初始化被串行化。外来、更新版本或被修改的 schema 会被拒绝，不会修复、替换或部分接管。SQLite 损坏与繁忙错误仍采用原有脱敏方式。

这是单向支持的升级。只认识 v1 的旧插件代码必须拒绝 v2，不提供自动降级。升级真实 profile 前，应采用另行验证的一致性备份流程。本功能不新增备份/恢复命令、自动备份、保留策略或跨宿主迁移。未包含事务状态地复制正在打开的数据库，不是受支持的备份方式。

## 5. Receipt 兼容

对于原先省略日期字段的命令，新增日期能力不会改变其规范化 payload。迁移后，旧 v1 capture/update 使用相同 operation、request ID 与 payload 重试，仍须匹配原摘要。迁移不会重写 receipt。

重放精确返回历史原始结果，因此 v1 receipt 可能**缺少** `due_date` 字段。这不同于当前读取中的 `due_date: null`。重放后应使用 show 获取当前状态。不要用当前任务数据补写旧 receipt，因为 revision 或日期可能已改变。

在已使用的 key 下提交新的显式日期或清除操作属于不同 payload，会返回 `idempotency_conflict`。新编辑应使用新 request ID，并保留当前 expected revision。迁移本身不产生用户更新、不递增任务 revision，也不虚构完成事件。

## 6. 验证与剩余范围

测试覆盖严格日期、闰日及类型校验，设置/清除/重放/CAS，排除终态、无日期及未来任务，同日排序、有界分页与重启持久化。迁移 fixture 覆盖真实 v1 schema、数据及摘要，旧 receipt 重放，中断与并发升级，外来/更新/修改 schema 拒绝以及回滚。固定宿主契约覆盖注册后的 CLI，以及带 socket-connect guard 的干净顶层 CLI 子进程。

只使用合成的本地 profile，不涉及 API Key、真实账号、provider 请求、原生 cron job、手机身份或对外发送。采用兼容性结论前，应对精确 commit 运行[全仓检查器](../README-zh.md#开发验证)。独立审查和 CI 不会让本地功能变成已验证的 owner 授权或提醒投递。

数据仍为明文，受本地 OS 账号及[文档 16](16-local-task-inbox-zh.md)中的隐私与保留限制约束。后续 agent、渠道或 HTTP 集成仍需 E1 及适用的执行管控和恢复门禁，本地 agenda 不绕过这些要求。
