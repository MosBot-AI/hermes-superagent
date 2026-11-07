# 51. 项目任务依赖与可推进工作

[English](51-project-task-dependencies.md) | 简体中文

本地任务流程现在能在命名项目中执行明确的先后约束：记录前置任务、查看当前可推进的工作，并拒绝过早开始或完成下游任务。沿用受支持的原生命令、CLI 和已激活任务工具，不派发 worker、不创建原生 Kanban 卡、不调度提醒，也不从任务文字推断授权。

## 1. 实际项目流程

沿用现有 `local_tasks` 和原生会话显式配置。照常捕获计划，再使用返回的任务 ID：

```text
/personal-tasks plan --project "Launch" --task "Draft" --task "Review" --request-id launch-1
/personal-tasks dependencies REVIEW_ID --needs DRAFT_ID --expected-revision 1 --request-id review-needs-draft
/personal-tasks show REVIEW_ID
/personal-tasks ready --project "Launch"
```

上述 ID 是真实规范 UUID 的占位符。`dependencies` 替换**整个**前置集合，不是追加一条边。多个前置任务重复 `--needs`；删除全部前置需明确 `--clear`。当前修订和稳定 request ID 必填，这条命令不会自动生成重试键。每任务最多 20 个唯一前置 ID，拒绝重复、缺失、自引用或环。

所有关联任务必须具有完全相同、非空的项目标签。未分组任务应先分组。标签仍是大小写敏感的本地分组，不是原生 Project ID、所有权、身份或安全边界。不会根据标题或跨项目猜测关联。

明确完成草稿，再查看新可推进的审核任务：

```text
/personal-tasks done DRAFT_ID --expected-revision 1 --note "Draft checked" --request-id draft-done
/personal-tasks ready --project "Launch"
/personal-tools enable-read
/personal-tools focus REVIEW_ID
```

使用真实当前修订；建立依赖会增加下游任务修订。focus 只选上下文，不启动工作。标记进度或完成前查看当前任务，再用现有命令；依赖门控会在写事务内重新验证。CLI 对应前缀为 `hermes personal-agent tasks`。原生默认可读文本，前置 `--json` 可用结构化结果；CLI 默认 JSON，支持 `--format text`。

## 2. 约束与明确进度

仅记录为 `done` 的前置任务满足依赖。活跃或已取消前置都会阻塞，取消不等于成功。过时要求应明确移除依赖，不能因取消而自动清除。

存在未满足前置时，拒绝 `progress --work-status in_progress` 和 `done`。给已经进行中的任务增加未满足前置也会拒绝；确实需要增加时，先明确调整该任务进度。下游任务始终可以取消。依赖修改、开始/完成检查、修订、元数据事件和重试回执共用一个 `BEGIN IMMEDIATE` 事务，避免并发修改穿过过时检查。

人工 `work_status` 保持独立。前置状态变化不会静默更改 ready、进行中、等待或阻塞备注。`ready` 只返回活跃、人工状态为 `ready` 且所有前置均完成的任务，按最早捕获顺序排列，不推断重要性、截止优先级或模型优先级。这是建议工作列表，不是执行许可、worker 启动、真实可用性或现实完成证据。

任务有任意入边或出边时禁止改变项目，包括终态边。不静默移动关联任务，也不自动删除边。依赖编辑仍仅允许活跃任务，因此已取消下游保留的边仍可能阻止活跃前置任务移到其他项目。这是明确保守限制，不是批量项目重命名或终态历史编辑流程。

## 3. 读取快照、聚焦与重试

新鲜任务记录包含 `dependencies`（有界前置 ID、修订与状态）、`dependencies_satisfied` 和 `unsatisfied_dependency_count`，不复制前置标题、详情或指令。存储引用缺失或不一致会拒绝，不会误判满足。日常 review 为过滤后的活跃任务增加依赖满足/阻塞计数。有界展示继续报告省略数量，不把样本当成完整结果。

show、list、search、agenda、ready、review 和聚焦上下文的关联数据来自同一 SQLite 读取快照。不同调用/分页仍是实时结果。ready 支持 `--limit`、`--after`，以及精确 `--project` 或 `--unassigned`；翻页保持过滤条件一致。`total_eligible` 覆盖当前匹配队列，不仅是当前页。并发变更可能改变之后的页面。ready/review 内部可能扫描所有匹配任务的元数据；输出有界不等于 CPU 时间或大型 store 延迟保证。

任务修订覆盖自己的字段和依赖边，**不是全局冻结的依赖快照**。完成前置会改变下游派生可推进性，但不会增加下游修订。focus 每轮刷新这些字段并说明范围，已传给模型/历史的旧上下文不会改写或擦除。

完全相同的重试保留原有回执优先行为：即便后来状态变化或进程重启，也只返回历史成功回执，不重做修改。当前状态应重新读取。旧键搭配变更参数会冲突。前置 ID 在计算摘要前排序，所以仅改变顺序仍是相同请求；重复 ID 仍无效。不确定写入应使用相同键和参数重试，而非换新键。

Schema v5 新增依赖关系，原子升级精确自有 v1–v4 schema，保留现有字段、修订、元数据事件、回执及其序列化字节。历史回执可能缺少依赖字段，界面显示未知而非满足。history 仍仅有操作、修订和时间戳，不重建旧依赖集合。与现有任务命令一样，逻辑读取打开 store 也可能初始化或迁移；旧插件无法读取升级后的 schema。

## 4. 模型工具与原生集成边界

现有显式读取激活后，`personal_tasks_read` 可使用 `ready`。写入激活后，`personal_tasks_write` 可使用 `set_dependencies`，传入 `task_id`、`expected_revision`、`dependency_ids` 和 `request_id`。模型必须使用返回 ID 记录明确要求的关系，不从描述推断执行许可。原有活跃轮次/profile/路由、撤销、子代理/cron 和不支持模式检查保持不变，不调用额外模型。计划捕获现在支持明确的一基批次 `depends_on` 位置，参见[原子计划依赖](56-atomic-plan-dependencies-zh.md)。不支持嵌套任务定义或推断顺序。

本切片是通过受支持原生入口推进 E3.2 依赖/可推进部分的 profile-first E2/E6 先导，不等于任务到 Kanban 映射或 E3.3 worker 编排。固定宿主公开 `kanban_list` 会执行 `recompute_ready`，普通 Kanban/Project 读取可能初始化或迁移存储，所以没有把它们暗中用作无副作用查看。模型侧 `kanban_create` 默认 running 且要求 assignee，还可能订阅通知、继承项目工作区上下文。

官方 CLI 可以明确创建 blocked、无 assignee 的 scratch 卡，但安全跨 store 交接仍需持久不确定结果与归档/重试核对。这是单独下一步，不是本次已实现能力。见[原生源码](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/kanban_tools.py)。

## 5. 验证

离线合成测试覆盖环与并发反向边、开始/关联竞态、两端项目修改、取消、回滚、回执重放、迁移和一致读取快照。真实固定宿主契约覆盖捕获计划、依赖、拒绝过早开始/完成、完成前置、ready 选择、focus、进程重启和既有准入拒绝。不使用安装器、真实 provider、Gateway listener、原生派发或生产个人数据；先前安装/网络限制保持。
