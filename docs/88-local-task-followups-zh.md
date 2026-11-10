# 88. 等待事项的显式跟进日期

[English](88-local-task-followups.md) | 简体中文

## 范围

等待或阻塞中的任务可以设置显式 `follow_up_on` 日历日期，独立于截止日期（`due_date`）。用户主动打开跟进视图，决定重新处理哪些事项。这是计划数据，**不是自动提醒**、后台唤醒、送达承诺、权限或派发。它不会联系任何人，也不会把等待任务自动变成 ready。

此能力属于受信任 profile 的原生命令行和已经激活的 session 任务工具。共享 REST Task 制品和客户端投影保持不变；这不证明共享 API 功能对齐或经过认证的 HTTP 可用。#19 的提醒调度与送达仍是独立事项。

## 记录和修改日期

```text
/personal-tasks progress TASK_ID --work-status waiting --note "等待回复" --follow-up-on 2030-01-10 --expected-revision 1 --request-id waiting-date
/personal-tasks update TASK_ID --follow-up-on 2030-01-12 --expected-revision 2 --request-id postpone-followup
/personal-tasks update TASK_ID --clear-follow-up-on --expected-revision 3 --request-id clear-followup
```

非空日期只能用于操作后状态为 `waiting` 或 `blocked` 的活跃任务。日期严格使用 `YYYY-MM-DD`；不附加时区、时刻、推断出的今天或自动紧急程度。update 和 progress 命令要求当前 revision。工具边界使用 null 显式清除。继续保持 waiting/blocked 时，省略字段会保留当前日期。改为 ready/in-progress，或完成/取消时，会在同一事务中清除日期。截止日期不会移动。

capture、plan、breakdown 和选定文本恢复不接受跟进日期：新任务没有日期。这能防止恢复历史任务时静默恢复调度元数据。普通依赖与准入规则继续适用。

## 打开到期跟进工作台

```text
/personal-tasks followups --on 2030-01-10
/personal-tasks followups --on 2030-01-10 --project "项目名称" --limit 20
/personal-tasks followups --on 2030-01-10 --unassigned
```

必须提供查询日期。视图只包含跟进日期不晚于该日期的活跃 waiting/blocked 任务。排序依次为跟进日期、high/normal/low 优先级、捕获顺序。未来日期、未设置日期、ready/in-progress 和终态任务不包含在内。它不推断依赖已满足或行动已获得授权。

默认上限 20，最大 100。结果包含 `items`、`total`、`omitted`、`limit`、`on`、精确 `ordering` 和 `scope`，以及 `authority=planning_data_not_reminder_or_dispatch`。这是新鲜的有界前 N 项视图，不是游标分页。输出上限不是大库 CPU 或延迟保证。读取不修改日期、状态或激活情况。现有 agenda、ready 和 next 的语义不变。

## 迁移与历史记录

Schema 8 增加可空字段。精确识别的 schema 1–7 在事务中迁移，保留任务身份、revision、事件、依赖和原生引用；旧任务为 null。原始回执字节和省略字段的请求摘要不变。历史回执可能没有字段，也可能显示以前的日期：使用 `show` 读取当前状态，对结果不确定的写入重试应复用完全相同的原始 request ID。

Schema 6/7 快照保持不可变、只读；缺少存储的跟进日期会显示为 null，不改变制品字节。选定文本恢复创建的新任务没有跟进调度元数据。已有私有存储、快照和恢复安全门继续适用。

## 验证边界

需要测试迁移/回滚、重放/CAS、严格输入与状态规则、终态清理、排序/过滤、当前展示和原生准入。手动官方安装包真实 Gateway 测试单独检查设置等待日期、显式到期查询、改期/拒绝过期 revision、重启持久化和完成后移除，使用合成记录及只读数据库检查。离线测试本身不证明真实验收。

交付由 [#111](https://github.com/MosBot-AI/hermes-superagent/issues/111) 跟踪，推进 #5 与 #4 的本地任务流程。不宣称模型调用、自然语言验收、自动通知、远程 owner 权限、共享 REST 扩展或整个 MVP 完成。
