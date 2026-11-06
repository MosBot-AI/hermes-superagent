# 04. 领域数据与记忆

## 1. 原则

“记忆”不能承担所有状态。项目任务需要确定性状态机，个人事实需要来源和纠错，授权需要可撤销的严格作用域，聊天记录需要原样保留。它们可以互相引用，但不能压缩成一份由模型任意覆盖的长文本。

所有表默认包含 `id`、`owner_id`、`profile_id`、`created_at`、`updated_at`、`revision`。时间点用 UTC 保存，面向人的期限另外保存 IANA timezone 和原始表述。结构化数据存于 `$HERMES_HOME/plugin-data/<plugin-id>/`，不提交 Git；大附件保存受控引用与哈希，不复制进所有数据库行。

## 2. 最小数据模型（拟议）

| 对象/表 | 主要字段 | 约束 |
|---|---|---|
| `owners` | 主体 id、状态、默认时区 | 不用显示名作为身份主键 |
| `channel_bindings` | 平台、tenant/account、external user id、验证方式、撤销时间 | 聊天/群/线程定位不等于 owner 身份 |
| `projects` | 名称、目标、范围、状态、原生 project/board 引用 | 原生已有项目只关联，不重建 |
| `commitments` | 谁承诺给谁、内容、due、timezone、状态、source ids | 区分事实与推断；他人承诺不能冒充用户承诺 |
| `tasks` | outcome、acceptance、constraints、dependency、Kanban/run 引用 | 执行状态读原生，业务验收单独记录 |
| `facts` | subject、predicate、value、scope、confidence、valid_from/to、status | inferred 与 explicit 分开，可更正/遗忘 |
| `sources` | 服务/账号、外部 id/url、作者、发生/抓取时间、内容 hash、权限标签 | URL 可失效；证据保留最少必要摘录 |
| `automations` | 用户目标、触发种类、native job id、stop condition、budget、destination | 调度实例由 Hermes 负责 |
| `action_intents` | action kind、target、payload hash、scope、expected revision、status | 审批绑定准确动作，变化后失效 |
| `grants` | 主体、允许操作/数据/接收者、期限、限额、policy version、撤销 | 外部内容不能创建 grant |
| `approvals` | intent id、approved hash、渠道/确认人、时间、expiry | 单次批准不可被旧消息重放 |
| `effects` | intent id、idempotency key、attempt、remote receipt、status | unknown 必须对账；不盲重试 |
| `deliveries` | artifact/summary、route、dedupe key、receipt、状态 | accepted 与 delivered 分开 |
| `audit_events` | 关联 id、动作、原因码、前后 revision、摘要 | 默认脱敏，不能记录 token/密码 |

## 3. 核心状态机

**Commitment**：`proposed → open → waiting_external / blocked → fulfilled / cancelled / superseded`。仅发现相似邮件不能自动标 fulfilled；应有交付或用户确认的证据。

**Task 业务状态**：`captured → clarified → ready → active → waiting_user / waiting_external / blocked → review → done / cancelled`。原生 worker 的 succeeded 只代表一次执行结束；验收未满足则保留 review/blocked，不能虚报 done。

**ActionIntent**：主路径为 `prepared → awaiting_approval → authorized → executing → succeeded / failed / unknown`；尚未提交的动作可进入 `cancelled`。用户拒绝进入明确终态 `denied`。授权过期可进入待确认；关键内容变化须创建新 intent 并使旧 intent 失效；撤权取消未获执行准入的动作，在途动作按 [授权提交线性化点](06-plugins-mcp-and-security.md#8-撤权审计与应急停止)处理。

`denied` 不复活、不自动更换工具/渠道重试，也不把过往拒绝当作下一轮可覆盖的临时错误。只有用户新的明确指令或相关的新授权允许重新提出时，才创建新 intent，保存 `supersedes_intent_id`、新内容 hash 与新的授权证据，重新走完整检查；第三方消息和模型自我改写不满足这一条件。

**Fact**：`candidate → confirmed / inferred → superseded / retracted / expired`。允许多个事实互相冲突，但检索必须显示当前有效与冲突原因，不简单“最后写入胜出”。

所有修改用 revision/compare-and-set 防止手机、桌面和后台同时覆盖。状态变更与 outbox 在同一插件数据库事务中落盘。原生状态同步使用事件和定期只读对账，断连时标注 stale。

## 4. 记忆分层

1. **原始会话**：Hermes SessionDB/session_search，不另存完整聊天副本。
2. **小型稳定记忆**：Hermes MEMORY.md / USER.md，保留高价值偏好和“如何查到详细信息”的索引，不塞大量流水。
3. **结构化个人资料**：本插件 facts、people/relationships、commitments 和 provenance，用领域工具检索。
4. **项目知识**：任务相关材料、决策、成果引用；没有权限时不可被召回。
5. **可选外部 memory provider**：只有一个可激活外部 provider，用户已有 provider 时保留它。高级语义检索属于后续选择，不是第一版前置条件。

默认基于 SQLite 索引/全文检索，按需再做向量索引；事实库是权威，向量只是可重建索引。检索后先做权限、scope、过期与来源过滤，再进入模型上下文，不能仅靠提示词要求模型忽略越权结果。

## 5. 写记忆流程

```text
可信输入或工具结果
  → 识别候选事实/承诺（模型可提议）
  → 验证来源、作者、范围、是否敏感、是否重复
  → 与现有事实做冲突检查
  → 确定性服务写入新 revision
  → 更新有界原生摘要或索引（适用时）
  → 可见审计，提供更正/删除入口
```

明确用户指令可以直接成为相应范围内的 confirmed 偏好；一次性任务选择只保存在该任务。模型推断必须标记 inferred，不升级成长期授权。第三方的转述保留作者信息，不写成“用户亲口说过”。

Hermes cron 在本基线中设置 `skip_memory=True`，不能假设后台 cron 会自然触发外部 MemoryProvider 的 sync/prefetch。后台整理如果需要写领域资料，应使用显式、受限的领域工具或生成候选待主 agent 合并。不绕过上游边界自动改个人核心记忆。

## 6. 更正、遗忘与导出

- 更正生成新 revision，旧事实标 superseded；有来源的审计保留最少记录，用户可看到更正结果。
- 遗忘先撤回检索可见性并删除派生索引，随后按用户选择删除源副本/附件。外部服务原件是否删除是另一个明确动作。
- 删除不等于备份立即消失：保留政策说明备份过期、恢复时 tombstone 重放和向量清理；不承诺技术上做不到的瞬时全网遗忘。
- 导出 JSON/Markdown 和附件清单，包含数据字典与来源；凭据、授权 token 不导出。
- 用户数据静态加密使用已验证的系统/存储机制与受控密钥；SQLite 本身不等于已加密。

## 7. 合成例子

“以后给我的项目周报用中文”写成 `subject=owner`、`predicate=report_language`、`value=zh-CN`、`scope=project_weekly_report`、`status=confirmed`、source=该条本人消息；不能扩展成所有外发邮件都用中文。收到“张某说你下周可以签约”的邮件，只形成第三方信息，不生成签约授权或已确认的个人承诺。

## 8. 数据质量门槛

每条长期事实可追溯到 source 或明确标注推断；没有 source 的历史导入不得伪造来源。测试覆盖冲突、误合并人名、撤回、时区变化、跨 profile 泄露、旧索引残留、并发覆盖和备份恢复后的遗忘重放。
