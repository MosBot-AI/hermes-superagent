# 78. 带栅栏的登记确认流程证据

[English](78-enrollment-ceremony.md) | 简体中文

## 已实现范围

`personal_agent.enrollment_ceremony` 新增未接线、默认拒绝的协调器及独立 SQLite challenge 存储。这是 E1.1 准备工作，不是生产 owner 签发器。现有 `EnrollmentStore` schema 和 pending/revoked 状态不变。没有 CLI、slash command、模型工具、HTTP 路由、生产存储打开器或 host adapter 调用此模块。不启用 ReadGrant、私密读取、canonical Bot 绑定或受控写入；Issue #14 保持开放。

仅 `enabled=True` 不足以启用：缺少独立 authority 时，在检查任一 store 或导入 host 之前拒绝。成功测试只使用合成可信 adapter。冻结 Python record 和构造函数不构成认证，也不防御同进程恶意代码。

## 一个有界确认流程

部署操作者已有的 pending enrollment 固定拟定 owner/profile/enrollment、actor、transport/接收账户和精确拟定读取 scope。这不是自登记，也不会采用已有本地任务。

1. 独立 authority 消耗不透明、一次性的 live observation handle，并持有 host 失效栅栏。它提供精确 `ChannelObservation` 字段：actor/receiver/profile、session、host incarnation、route/device revision、直接人类 DM 来源以及当前设备撤销状态。缺失、群组、bot、转发、内部或已撤销观察均拒绝。
2. 在 host 栅栏内，现有 enrollment 事务验证当前 enrollment/policy revision 与 epoch，并排除并发撤销。独立 challenge 事务在锁等待之后采样可信时间，存储精确绑定及五分钟有效区间，并记录 issued 事件。随机 challenge ID 只是定位符，不是 bearer authority。
3. 确认需要新鲜独立 handle，证明明确确认该精确 challenge。在相同锁序下，将全部已存 observation 和 enrollment/scope 字段与当前值比较。等待 challenge 锁后重新采样可信 UTC。仅在左闭右开有效区间内精确匹配才记录 `confirmed`；进入此阶段的拒绝尝试记录 `consumed` 和 denied 事件。
4. 两种终态都拒绝再次尝试，即使有新 handle。历史检查只报告 ID/状态及 `authority: false`。Confirmed 证据从不激活 enrollment 或授权后续操作。任何未来操作仍须当前独立 host 和 enrollment authority。

审计事件包含 challenge ID 和结果，不含 principal/receiver ID、scope、原始参数或 adapter 异常。Challenge 行本身包含私密身份及拟定 scope 元数据；调用方拥有的 SQLite 访问必须私密。本切片不提供生产打开器、加密、清理策略或认证审计日志。容量限于 10,000 行，不自动淘汰。拒绝外部/修改过/临时 schema 及调用方已有事务。


对其他 challenge ID 或 owner/profile/enrollment key 的确认，在修改该 challenge 前拒绝。Host handle 可以已消费，但不能烧掉其他 enrollment 的 pending challenge。只有获准进入自身精确 challenge 的尝试才能持久化 denied/consumed 结果。

## 失败与并发语义

锁序为 **host 失效栅栏 → enrollment `BEGIN IMMEDIATE` → 独立 challenge `BEGIN IMMEDIATE`**。持锁时不得询问用户、调用模型、联系 transport 或派发 worker。独立 challenge 连接串行化竞争确认。当前策略/撤销在现有 enrollment 锁内检查，不从缓存 pending 行推断。

两个数据库之间**没有原子提交**。内部 challenge 提交可能在稍后的 enrollment 提交或 host guard 退出失败后仍保留。协调器报告 `outcome_uncertain`，不返回成功结果，也绝不通过删除证据或复活已消费 challenge 来补偿。检查此时可能报告 `confirmed`，但这是历史证据，不证明调用方收到成功或当前有授权。

Challenge 审计/提交失败会回滚该数据库事务。独立消费的 host handle 仍保持已消费，因此重试需要新的可信观察/确认。当前策略准入前失败可使数据库 challenge 保持 pending；API 不虚称 challenge 已持久消费。未知异常经过脱敏。数据库回滚及恢复副本不证明 live host 新鲜度，证据绝不能作为可复用许可。

## 当前 host 边界与验证

当前兼容性 pin：Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`。不同于 [18](18-owner-entry-and-read-authorization-zh.md)/[23](23-host-command-context-experiment-zh.md) 的历史来源，此 host 已有 `gateway.session_identity.RoutingIdentity`，含 transport/runtime profile 和 live adapter weakref。它仍是 wire-invisible 动态来源观察。公开插件 command context 不提供本流程所需的独立一次性确认、当前 device/session/route 栅栏或 owner 签发器。插件不导入私有 routing identity helper，也不把序列化 source 变为 authority。

原生测试执行真实 source 序列化及公开 command 调用，展示动态 identity 丢失及命令提供的批准声明被拒绝。单元测试以合成可信 guard 执行真实 challenge/enrollment 事务，覆盖精确不匹配、到期、一次性结果、schema 故障和两个跨库失败窗口。应运行完整仓库 checker 及固定 host 原生契约；focused 合成成功不证明安全真实 ingress 或生产登记确认流程。
