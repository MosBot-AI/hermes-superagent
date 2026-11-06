# Hermes Superagent 设计文档

[English](README.md) | 简体中文

状态：**方案基线、E0 契约及显式启用的本地 CLI 任务收件箱；完整 personal-agent MVP 尚未实现**。核验日期：2026-11-06。目标仓库：`MosBot-AI/hermes-superagent`。当前代码与验证边界见 [第一开发切片](12-foundation-progress-zh.md)。

## 一句话定位

把 Hermes 扩展成一个长期服务于单个用户的 personal agent：一个主 agent 统一理解项目、事务、个人资料、提醒与沟通，必要时调用少量受限 worker；使用 Hermes 原生运行时、插件、记忆、任务、调度、MCP、消息和语音能力，不再构建一个外部独立代理。

## 阅读顺序

1. [产品目标与范围](01-product-and-scope-zh.md)：服务谁，做什么，哪些明确不做。
2. [DSH 研究与取舍](02-dsh-research-and-decisions-zh.md)：从代码和报道中借鉴什么、修正什么。
3. [Hermes 原生架构](03-native-architecture-zh.md)：宿主、插件、领域状态和执行之间的边界。
4. [领域数据与记忆](04-domain-data-and-memory-zh.md)：项目、承诺、资料、来源、纠错与遗忘。
5. [主动工作、调度与交付](05-automation-and-delivery-zh.md)：可靠提醒、重启恢复、幂等与消息交付。
6. [插件、MCP 与安全](06-plugins-mcp-and-security-zh.md)：开放扩展、动作授权、身份和撤权。
7. [手机与语音](07-mobile-and-voice-zh.md)：优先复用现有入口，保证同一个 agent 的连续性。
8. [路线图与验收](08-roadmap-and-acceptance-zh.md)：按依赖排序的 epics、任务和可测试验收。
9. [上游证据与核验边界](09-upstream-evidence-zh.md)：固定源码版本、链接和需要再验证的契约。
10. [接口与端到端契约](10-interface-contracts-zh.md)：拟议事件、工具、适配器和关键纵向流程。
11. [Worker 模型路由插件](11-worker-model-routing-zh.md)：按任务需求选择已许可 provider/model/effort，先 shadow 再启用。
12. [第一开发切片](12-foundation-progress-zh.md)：原生只读插件、实际合同测试与剩余门槛。
13. [执行边界契约与写路径清单](13-enforcement-contracts-zh.md)：实测失败边界与仍被阻断的写路径。
14. [客户端、授权与连接器 API 契约](14-client-api-contracts-zh.md)：拟议 HTTP 路由、canonical 会话传输、恢复和明确的原生手机阻断。
15. [主 Bot 绑定与连续性](15-primary-bot-binding-zh.md)：选择既有原生 Bot、验证角色、恢复与 fencing 的拟议方案。
16. [显式启用的本地任务收件箱](16-local-task-inbox-zh.md)：已实现的本地 CLI 持久化、重放/revision 校验及明确限制。
17. [本地截止日期与 agenda](17-local-task-agenda-zh.md)：日期语义、有界查询与事务式 schema 升级。
18. [架构决策记录](adr/README-zh.md)：为什么选择这些约束。

## 三类陈述必须分开

- **已核验的上游能力**：在固定 Hermes/DSH 源码或官方文档中发现；不等于本仓库已具备。
- **本项目设计**：待实现的领域模型、策略、界面和适配。文中的工具名、数据表和事件名是拟议接口。
- **待验证事项**：需用最小原型和集成测试确认，不用想象补齐上游 API。

研究基线为 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`，DSH Superagent `8c32a9dc5d72c033816c6a8110b37f40cf94fba4`。`main` 持续变化；实施时先选择通过兼容测试的发布版本，再记录其精确 SHA。本文不是“最新版全部行为”的长期保证。

## 设计的硬约束

1. 一个主身份和一个授权主体，项目/会话不各自变成独立人格。
2. 不复制 Hermes agent loop、session store、cron scheduler、Kanban dispatcher 或 OAuth 栈。
3. 外部资料是证据，不是授权；消息来自用户账号不等于消息内引用的指令是用户命令。
4. 不能用提示词、Mandate、MCP 的 read-only hint 或 Python 插件加载方式代替安全隔离。
5. 任何外发、修改、消费等动作都先构造可核验的 intent，执行前重新验证授权；重试不能扩大权限。
6. 用户请求优先于后台工作。主动功能可解释、可暂停、有预算、有静默和去重规则。
7. 运行状态、个人数据、凭据不进入本公开仓库；仓库只收方案、合成样例和未来代码。

## 当前交付范围

方案文档与项目规划已建立，E0 基础与显式本地任务收件箱已在临时测试 home 中运行。本地 CLI 持久化已实现，更广泛的 agent/渠道/HTTP 个人数据访问尚未实现。没有生产部署、没有接入真实个人数据，也没有宣称权限、提醒或手机语音已经可用。GitHub Projects 是研发计划；Hermes 原生 Projects/Kanban 是未来产品运行时的工作对象，二者不能混淆。

新增 E9 为原生 worker 模型路由插件设计：用户已审阅并选择插件方向，仍未实现。主 agent 保持原有职责；完整约束、宿主能力缺口、开源参考和验收见 [11](11-worker-model-routing-zh.md)。
