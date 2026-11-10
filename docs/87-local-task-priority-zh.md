# 87. 显式本地任务优先级

[English](87-local-task-priority.md) | 简体中文

## 用途与范围

任务优先级是显式规划数据：`high`、`normal` 或 `low`，帮助从已经具备执行条件的工作中选择。它不是权限、推断的紧急程度、预算、worker 派发或提醒。截止日期不会静默改变优先级。通常的任务状态、依赖、revision 和会话准入门禁仍然适用。

词汇与在 `b0f3a52c4ab2cf5258e65ea4b7974cd044782505` 核对的 DSH 领域优先级枚举一致。这是本地原生命令/任务工具能力，不是新增共享 REST 字段。权威共享 Task 投影及其固定契约保持不变；不宣称 HTTP 已可用或跨后端功能等价。

## 显式编辑

```text
/personal-tasks add "整理项目资料" --priority high --request-id priority-capture
/personal-tasks update TASK_ID --priority low --expected-revision 1 --request-id priority-edit
/personal-tasks show TASK_ID
```

本地 CLI 及已经启用并经会话激活的任务工具使用相同取值。Plan 和 breakdown 的 JSON 条目可以分别指定优先级。新任务省略时按 `normal` 存储；不会将默认值静默加入历史请求摘要。无效枚举值、null、布尔值及未知字段均拒绝。只改优先级也需要当前 revision，并产生通常的持久事件/回执。终态任务继续遵循已有修改规则。

优先级必须反映用户明确选择，而不是模型推断的权限或长期偏好。当前任务视图及聚焦任务上下文会显示它。已有狭窄授权的规划 worker 披露不会静默增加字段。

## 选择下一件工作

```text
/personal-tasks next --limit 5
/personal-tasks next --project "项目名称" --limit 5
/personal-tasks next --unassigned --limit 5
```

`next` 仅考虑活动 `captured` 任务，要求人工记录的 `work_status=ready`，且全部前置任务均为 `done`。前置任务取消、缺失或未满足，不会因为后续任务优先级高就被放行。排序依次为 `high`、`normal`、`low`；每个优先级内部按明确截止日期从早到晚，无日期排最后，再按捕获顺序排列。

默认 limit 为 5，上限 20。结果包含 `total`、`omitted`、`limit`、精确 `ordering`、资格 `scope` 及 `authority=planning_data_not_permission_or_dispatch`。这是新鲜的有界 top-N 视图，不是分页快照；不接受 `after` cursor。计数可能检查整个符合条件的元数据集合，因此输出上限不保证大型存储的 CPU/延迟。现有 `ready` 视图保留最早捕获优先的排序和 cursor 语义。两种查询都不改变 focus、任务状态或派发工作。

## 迁移与历史证据

Schema 7 增加 priority，同时保留任务 ID、revision、捕获序号、依赖、原生引用、事件和回执。旧任务变为 `normal`。只在事务内迁移精确识别的旧 schema，不采纳损坏的 schema。

现有回执文本和请求摘要保持不变。因此，重放历史请求时，回执可能不含 priority；它是历史证据，不是当前读取，也不表示后来的优先级修改消失。用 `show` 查看当前状态。显式默认值及省略字段的兼容性分别测试。

历史 schema-6 快照仍只读，其字节不被迁移。旧任务结构中缺少的 priority 展示为 `normal`；这不会改写历史产物或授予权限。快照检查/复制及私有存储安全门禁继续适用。现有选定文本的 `recover-copy` 操作仍创建 normal 优先级的新任务，不继承历史优先级或恢复执行权限。

## 验证及边界

测试覆盖 schema 迁移/回滚、省略字段重放、精确历史回执、严格取值、仅优先级修改的 CAS、依赖、过滤/同序、展示、原生命令及无模型调用的既有模型工具准入。手动官方安装包 Gateway 验收仍需针对精确候选版本单独验证真实创建/修改/选择及重启行为。离线测试本身不证明该真实运行结果。

该有界功能推进 [#5](https://github.com/MosBot-AI/hermes-superagent/issues/5) 下的 E3.4，交付由 [#109](https://github.com/MosBot-AI/hermes-superagent/issues/109) 跟踪。它不代表更广 E3、自然语言验收、远程 owner 权限、提醒或完整 Super Agent 已完成。
