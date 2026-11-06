# 架构决策记录

状态：设计采纳，等待实现验证。日期：2026-11-06。

## ADR-001：Hermes 原生插件，不建平行 agent runtime

**选择**：以 `plugin.yaml + register(ctx)`、原生工具/skills/公共 ctx 与 ABC 扩展 Hermes，复用 agent loop、gateway、SessionDB、cron、Kanban、MCP 和语音。

**原因**：用户需要 Hermes 自身成为 personal agent。复制执行/会话/调度系统会产生双状态、升级成本和权限裂缝。DSH/Cordis 只作为设计参考。

**代价**：受官方扩展面约束；先做契约 spike，缺能力时提出最小通用上游扩展，不直接修改 core 或私写宿主数据库。见 [03](../03-native-architecture.md)。

## ADR-002：一个主身份，任务与 session 分离

**选择**：默认一个主 profile/owner，项目是上下文，worker 是临时或 Kanban 管理的执行资源。业务 Task 关联原生 card/run，不等于聊天 session。

**原因**：任务应跨会话、设备和重启存在，session idle/结束不证明任务完成。多 persona 会增加用户协调负担。

**代价**：需要任务引用、验收和状态对账；只在数据/身份隔离必要时增加主 profile。见 [01](../01-product-and-scope.md)、[04](../04-domain-data-and-memory.md)。

## ADR-003：准入与操作授权两道门

**选择**：IntakeGate 决定候选工作；ActionGate 在每次副作用提交前检查 owner、grant、scope、payload、recipient、限额和最新 policy revision。

**原因**：DSH Mandate 的任务级边界有价值，但不能替代个人敏感数据场景下的动作级 enforcement。提示词和自动摘要不能授予权限。

**代价**：连接器需实现细分动作语义与审批；部分动作必须由人完成。pre_tool_call callback fail-closed 与 middleware fail-open 精确区分，handler 再检查。见 [06](../06-plugins-mcp-and-security.md)。

## ADR-004：领域事务加 outbox，不承诺端到端 exactly-once

**选择**：插件自有状态与自有 effects 同 SQLite 事务；原生调度/交付仍以 Hermes 为权威；外部 action 采用 idempotency、receipt 和 unknown/reconcile。

**原因**：跨数据库与外部服务没有共同事务；“请求超时”不证明没执行。不能把 LLM 恢复提示当可靠性保证。

**代价**：需要对账和人工处理少量 unknown；不能重复接管原生 delivery queue。见 [05](../05-automation-and-delivery.md)。

## ADR-005：记忆是带来源的数据，不是授权数据库

**选择**：原生会话/稳定摘要 + 结构化事实/承诺 + 按需项目知识；默认保留用户已有 memory provider。

**原因**：事实会过期、冲突和被撤回；长期权限不能靠模型摘要恢复。Hermes 仅一个外部 provider，cron 默认 skip_memory。

**代价**：需要纠错、遗忘、索引清理和 scope 检索；不在 MVP 自建庞大知识图谱。见 [04](../04-domain-data-and-memory.md)。

## ADR-006：Observe-first，硬撤权独立于 soft pause

**选择**：主动功能先只读观察/提案，再按场景和风险启用。暂停停止新工作；撤权与动作准入以同一权威存储的事务提交顺序为线性化依据，阻止后续新准入并使旧 approval 失效。先前已准入的在途请求尽力取消，不承诺撤回远端已接受动作。

**原因**：减轻注意力负担不能靠扩大无限自主权实现；通知运行中 worker“权限变了”不等于执行层已撤权。

**代价**：需要持久 budget、dedupe、policy revision 和撤权 race 测试。见 [05](../05-automation-and-delivery.md)、[06](../06-plugins-mcp-and-security.md)。

## ADR-007：手机先复用消息入口，语音与执行解耦

**选择**：先官方 gateway 手机文字/语音消息，再验证原生 web/mobile 和实时语音。语音前端无独立副作用授权通道。

**原因**：原生已有多种入口；自建移动聊天/通话栈会分散可靠闭环工作。停止播放与取消外部动作必须区分。

**代价**：目标渠道和设备逐个验证，不宣称全平台即时可用。见 [07](../07-mobile-and-voice.md)。

## ADR-008：先做单机可靠性，再做多执行环境

**选择**：一个持续在线 Hermes host 为默认；用原生可用执行后端，在需求明确后引入远端 lease/fencing/reconnect 契约。

**原因**：单机锁和 SQLite 不等于分布式一致性；文章里的未来架构不能直接当 MVP 已实现。

**代价**：单 host 故障时暂不可用，需要清楚服务健康、备份和恢复目标。见 [08](../08-roadmap-and-acceptance.md)。
