# 10. 拟议接口与端到端契约

[English](10-interface-contracts.md) | 简体中文

本页全部是本项目的**拟议契约**，不是宣称 Hermes 已提供同名 API。具体命名在 E0 后冻结。领域服务应与 UI/模型解耦；无论由 agent tool、手机按钮还是后台调度进入，必须走相同状态和权限检查。

具体客户端 HTTP 路由、宿主认证、canonical 会话传输、持久变更流及连接器 schema 见 [14](14-client-api-contracts-zh.md)。该设计同样尚未实现；本页定义共同的领域层。

## 1. EventEnvelope

```json
{
  "schema_version": "personal.event.v1",
  "event_id": "opaque-source-event-id",
  "source_instance_id": "verified-connector-instance",
  "source_type": "message",
  "actor": {
    "external_id": "source-authenticated-id",
    "is_bot": false,
    "owner_binding_id": "binding-id-or-null"
  },
  "thread_ref": "source-native-thread-id",
  "occurred_at": "2026-11-06T09:00:00Z",
  "received_at": "2026-11-06T09:00:02Z",
  "body_ref": "permission-scoped-content-reference",
  "content_hash": "sha256-of-normalized-content",
  "correlations": [],
  "trust_class": "untrusted_content"
}
```

actor/auth metadata 由 connector/平台可信通道给出，body 中自称的姓名不覆盖它。owner_binding_id 由本机身份服务解析，不接受远端任意填入。关联只帮助检索，不继承授权。

去重以 source_instance_id + event_id 为基础。对支持编辑的源，另存 revision/content_hash；同一事件被编辑需要更新证据，但不会直接重复执行旧动作。cursor/watermark 只能在该批事件已经可靠落盘后推进，轮询与 webhook overlap 必须去重。

## 2. 最小领域工具面

不把所有数据库 CRUD 暴露给模型。初始工具可分为以下小集合，在受支持的 session/worker 创建边界，或宿主明确支持的下一回合重建点，选择最小允许集合。固定版本的宿主会冻结 session/worker 的工具与 prompt 表面以保持缓存行为，不能假设可以在回合中任意修改工具 schema。每次受控动作之前仍须检查当前策略：

| 拟议工具 | 输入重点 | 输出/副作用 |
|---|---|---|
| `personal_context` | query、project/task ref、scope、limit | 有界事实与来源，无权限的条目不返回 |
| `personal_project` | action、project ref、expected_revision | 建立/更新业务项目，必要时通过原生 adapter 关联 |
| `personal_commitment` | action、content、due、timezone、source refs | 承诺状态修改，返回 revision 和审计引用 |
| `personal_task` | action、outcome、acceptance、constraints、task ref | 映射原生 Kanban/worker，不直接创建平行 executor |
| `personal_fact` | propose/correct/forget、fact ref、scope、sources | 明确事实/推断；敏感/冲突路径可要求确认 |
| `personal_automation` | create/inspect/pause/resume/cancel、trigger、destination | 由原生 cron/heartbeat 执行，返回 native ref 和计划预览 |
| `personal_action` | prepare/inspect/cancel、action kind、target、payload | 生成准确 intent；批准不是模型可自行传 true 的参数 |

执行受控动作的能力不暴露成 `approved: true` 或“忽略策略”参数。Approval receipt 来自受验证的人机交互与宿主审批路径，服务端按 principal、hash、expiry 和 policy revision 重新验证。受控 connector 若可以被另一裸工具绕开，必须缩减当前工具集/凭据 scope，或者标为未达到发布门槛。

## 3. 通用结果结构

```json
{
  "status": "awaiting_approval",
  "object_ref": "intent-id",
  "revision": 3,
  "summary": "需要你确认接收者和要发送的内容。",
  "evidence_refs": ["source-id"],
  "native_refs": {},
  "next_action": {
    "kind": "human_approval",
    "request_ref": "approval-request-id"
  },
  "error": null
}
```

`status` 使用结构化枚举：ok、awaiting_approval、denied、blocked、conflict、not_found、retryable_failure、unknown_outcome、cancel_requested、cancelled。denied 是当前 intent 的终态，不按 retryable_failure 处理。`summary` 只是用户可读文字，不能靠解析它判断业务状态。错误包含稳定 code、是否可重试和必要的补救，不泄露 token/原始敏感 payload。

## 4. NativeAdapter 契约

领域服务通过适配器对接 Hermes；E0 测试决定调用官方 ctx/tool dispatch/CLI/API 中哪条受支持路径。

| Adapter | 所需行为 | 不能假设的能力 |
|---|---|---|
| ProjectAdapter | list/resolve/create/link，返回稳定 native id | 手机天然拥有 desktop_project 工具 |
| TaskAdapter | create with idempotency、get state/attempt、request cancel、read result | 任意私有 DB import 稳定；succeeded 等于业务 done |
| ScheduleAdapter | create/update/pause/cancel/read next-run/read execution | 可直接改 jobs.json；cron 自动运行 MemoryProvider |
| DeliveryAdapter | resolve verified route、submit、get receipt/reconcile | 每个平台都能证明已送达/已读 |
| ShortWorkerAdapter | launch/status/cancel/result，受限 toolsets | lifecycle handle 能跨进程存活；所有 request 字段都可用 |
| ConnectorAdapter | read/write capability、auth health、idempotency/reconcile | read-only annotation 保证服务端语义 |

所有 adapter 返回稳定 external refs 和 capability flags。缺少幂等或 receipt 的服务须明确报告，而不是构造假的成功保证。原生 API 更改通过 adapter compatibility test 发现，领域 schema 不随内部模块重构频繁变动。

## 5. 三条验收路径

### A. 创建提醒

owner 发请求 → Event 去重/身份验证 → 解析时间与 timezone → 领域 automation prepared → 原生 scheduler 建 job → 保存 native ref/对账 key → 给 owner 展示计划 → occurrence 到达 → 检查仍有效 → 唯一 delivery owner 发送 → 保存 receipt。若 native job 已创建但领域写回失败，重试先按 idempotency/关联读取，而非新建第二个 job。

### B. 准备并发送内容

owner 请求 → 获取已授权源 → 形成草稿/artifact → 准确 action intent → 判断现有 grant 是否覆盖 → 如需则展示接收者/内容/附件/影响 → 验证 approval → 执行前重读 revision → 连接器发送 → 记录 receipt → 对外确认实际结果。发送超时走 unknown/reconcile，审批后修改正文关键内容或收件人使旧 approval 失效。

### C. 项目 worker 被打断

主 agent 建 task 与验收 → 原生 Kanban 派工/短 worker → owner 新消息抢占前台 → 解释/修改原任务 → 更新 scope/revision → worker 下一副作用前验证 → cancel_requested 或继续窄 scope → 根据原生结果与验收进入 review/done。worker 结束不能复用已过期 grant；后续第三方事件只提供证据，不自动恢复任务。

## 6. 协议演进

schema_version 按对象契约独立管理；新增字段可选，改变语义需 migration。opaque ids 不让客户端解析字符串结构。对象引用、来源权限、状态枚举和错误代码通过契约测试冻结。迁移前可备份和 dry-run，失败保持旧可用状态，不让半升级开始外发动作。
