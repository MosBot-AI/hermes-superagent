# 04. 领域数据与记忆

[English](04-domain-data-and-memory.md) | 简体中文

完整的拟议可替换记忆设计见 [30](30-pluggable-memory-contracts-zh.md)：项目自有的 MemoryService/MemoryBackend 合同、本地 SQLite 加 Markdown 默认实现、可选的实际 Hermes MemoryProvider 桥接、生命周期/checkpoint、有界检索与迁移。本文保留领域模型；记忆记录 namespace 和后端特定的提交语义遵循文档 30。当前本地任务实现并不是完整的个人事实/记忆库。

## 1. 原则

“记忆”不能承担所有状态。项目任务需要确定性状态机，个人事实需要来源和纠错，授权需要可撤销的严格作用域，聊天记录需要原样保留。它们可以互相引用，但不能压缩成一份由模型任意覆盖的长文本。

所有表默认包含 `id`、`owner_id`、`profile_id`、`created_at`、`updated_at`、`revision`。时间点用 UTC 保存，面向人的期限另外保存 IANA timezone 和原始表述。结构化数据存于 `$HERMES_HOME/plugin-data/<plugin-id>/`，不提交 Git；大附件保存受控引用与哈希，不复制进所有数据库行。

在记忆路径中，可信 profile namespace 不会伪造经过认证的 owner_id。未来 verified-owner namespace 有独立的真实身份与数据采用门禁。任务、授权和原生运行时对象仍是各自状态的权威来源；记忆摘要不能隐式修改它们。

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

**ActionIntent**：主路径为 `prepared → awaiting_approval → authorized → executing → succeeded / failed / unknown`；尚未提交的动作可进入 `cancelled`。用户拒绝进入明确终态 `denied`。授权过期可进入待确认；关键内容变化须创建新 intent 并使旧 intent 失效；撤权取消未获执行准入的动作，在途动作按 [授权提交线性化点](06-plugins-mcp-and-security-zh.md#8-撤权审计与应急停止)处理。

`denied` 不复活、不自动更换工具/渠道重试，也不把过往拒绝当作下一轮可覆盖的临时错误。只有用户新的明确指令或相关的新授权允许重新提出时，才创建新 intent，保存 `supersedes_intent_id`、新内容 hash 与新的授权证据，重新走完整检查；第三方消息和模型自我改写不满足这一条件。

**Fact**：`candidate → confirmed / inferred → superseded / retracted / expired`。允许多个事实互相冲突，但检索必须显示当前有效与冲突原因，不简单“最后写入胜出”。

所有修改用 revision/compare-and-set 防止手机、桌面和后台同时覆盖。状态变更与 outbox 在同一插件数据库事务中落盘。原生状态同步使用事件和定期只读对账，断连时标注 stale。

## 4. 记忆分层

1. **原始会话**：Hermes SessionDB/session_search，不另存完整聊天副本。
2. **小型稳定记忆**：Hermes MEMORY.md / USER.md，保留高价值偏好和“如何查到详细信息”的索引，不塞大量流水。
3. **结构化个人资料**：本插件 facts、people/relationships、commitments 和 provenance，用领域工具检索。
4. **项目知识**：任务相关材料、决策、成果引用；没有权限时不可被召回。
5. **可选外部 memory provider**：只有一个可激活外部 provider，用户已有 provider 时保留它。高级语义检索属于后续选择，不是第一版前置条件。

默认后端使用 SQLite 权威记录/事件、全文索引，以及生成的人类可读 Markdown 投影。Markdown 编辑成为显式、基于版本的变更提案，不构成第二个并发权威来源。向量索引是可选且可重建的。在任何外部查询或私有载荷读取之前，先确定获准 namespace、数据类别与范围；返回有界模型上下文前再检查当前权限、删除标记、有效性和来源。仅提示模型忽略未授权结果并不足够。原生 session_search 可显式读取另一个本地 profile，所以默认 profile 选择并不是通用隐私屏障。适配器、token 预算和迁移合同见 [30](30-pluggable-memory-contracts-zh.md)。

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

Hermes 本基线的 [cron/scheduler.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/scheduler.py#L2502-L2514)实际设置 `skip_memory=False`、`skip_background_review=True`，并通过初始化向 provider 传入 `agent_context="cron"`。Cron 写入限制是 provider 必须遵守的契约，不是宿主统一禁用 memory；不能据此假定任何外部 MemoryProvider 都正确拒写。后台领域写入仍应走明确受限工具或生成候选供主 agent 合并，不自动修改核心记忆。另 [system_prompt.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/system_prompt.py#L814-L837)会在压缩后失效重建时从磁盘重新加载 memory，不能泛称快照在整个会话内永不变化。

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
