# Hermes Superagent 设计文档

[English](README.md) | 简体中文

状态：**方案基线、E0 契约、本地任务存储及显式原生会话入口与任务模型工具；完整 personal-agent MVP 尚未实现**。核验日期：2026-11-06。目标仓库：`MosBot-AI/hermes-superagent`。当前代码与验证边界见 [第一开发切片](12-foundation-progress-zh.md)。

当前用户选择 profile-first 单用户本地 MVP；先通过已有原生会话管理任务和项目标签，不以主 Bot/远程登记作为前提。Profile 仍不是身份。主 Bot、远程/多用户、手机与语音安全门禁保留为对应模式的后续要求，见 [28](28-profile-first-local-conversations-zh.md) 与[路线图](08-roadmap-and-acceptance-zh.md)。

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
18. [Owner 入口与只读授权基础](18-owner-entry-and-read-authorization-zh.md)：内部评估器、原生身份缺口与不读取个人数据的诊断。
19. [统一语音会话与提供方契约](19-unified-voice-provider-contracts-zh.md)：本地/在线语音的可替换接口、能力、打断/恢复及安全门禁设计。
20. [离线语音契约模拟器](20-voice-contract-simulator-zh.md)：合成音频帧、队列与恢复自检，以及核实的原生 provider 局限。
21. [原生语音 IPC 实验](21-native-voice-ipc-experiment-zh.md)：可审阅宿主补丁、真实消费路径证据及尚未集成的发布限制。
22. [本地任务检索](22-local-task-search-zh.md)：标题/详情字面匹配、有界分页及不变的本地门禁。
23. [host 命令上下文实验](23-host-command-context-experiment-zh.md)：仅供审阅的命令专用身份观察补丁、受守卫证据及最小 owner 摘要集成路径。
24. [本地项目分组](24-local-project-groups-zh.md)：任务标签、精确筛选、进度计数及 schema-v3 迁移。
25. [原生计划 blueprint](25-native-planning-blueprint-zh.md)：显式启用的原生计划表单集成及明确 job 生命周期/费用边界。
26. [待确认身份登记与策略持久化](26-pending-enrollment-policy-zh.md)：未接入口的管理元数据、CAS/撤销、私有存储与剩余 owner 准入门禁。
27. [带栅栏的读取准入](27-fenced-read-admission-zh.md)：默认拒绝的确认/快照契约、实际策略事务排序及未实现的生产 adapter。
28. [Profile 优先的本地任务对话](28-profile-first-local-conversations-zh.md)：显式启用原生会话命令、任务/项目标签闭环和可信单用户部署边界。
29. [会话范围任务工具](29-session-scoped-task-tools-zh.md)：明确激活的原生进程内模型任务访问、隐私/撤销边界及待完成真实模型验收。
30. [可插拔记忆契约](30-pluggable-memory-contracts-zh.md)：拟议的可替换后端/SDK、SQLite 权威与 Markdown 投影、可选原生桥接、有界召回、删除与迁移。
31. [显式本地记忆](31-explicit-local-memory-zh.md)：用户控制的原生记住/搜索/更正/遗忘命令、有界记录与部分适配器边界；无自动召回或 provider 替换。
32. [会话范围记忆工具](32-session-scoped-memory-tools-zh.md)：独立30分钟读写激活、模型来源、v1→v2迁移与待完成的真实模型验收。
33. [记忆适配器准入](33-memory-adapter-admission-zh.md)：严格的显式记录描述、能力/上限检查、仅元数据审查及可复用离线一致性门禁；不加载第三方代码。
34. [本地任务操作历史](34-local-task-history-zh.md)：持久化版本元数据、有界分页及既有原生读取限制。
35. [离线 Worker 路由](35-offline-worker-routing-zh.md)：严格合成候选过滤、基线检查和部分原生路由契约；没有在线 backend。
36. [有界显式记忆召回](36-bounded-memory-recall-zh.md)：多关键词字面排序、完整记录的 JSON 预算、当前 revision 与同一读取快照；没有自动提示注入。
37. [持久化本地记忆进度](37-durable-memory-progress-zh.md)：元数据变更分页、内部 CAS/幂等消费者游标和原子 schema-v3 迁移；不等于原生压缩 checkpoint。
38. [已保存路由诊断](38-routing-readiness-inspection-zh.md)：原生本地声明诊断，不解析凭据/模型，也不启用路由。
39. [本地记忆元数据检查点](39-local-memory-checkpoints-zh.md)：显式原生命令创建持久元数据标记，验证事件与记录一致性，检查水位并查询是否过时；不备份正文，也不满足原生压缩检查点。
40. [每日任务回顾](40-daily-task-review-zh.md)：同一快照的活动数量、仅含标题的摘要、精确项目过滤和输出预算。
41. [可选原生记忆召回](41-native-memory-recall-zh.md): 显式选择真实 MemoryProvider 后，可为支持的原生主会话提供即时、有界的本地记录上下文；不摄取或改写规范记录，仍不支持严格原生检查点。
42. [本地任务进度](42-local-task-progress-zh.md)：明确的工作中/等待/阻碍说明、安全版本写入、活动过滤和原子 schema-v4 迁移。
43. [原生检查点证据边界](43-native-checkpoint-boundary-zh.md)新增有界、无 I/O 的候选准备和固定宿主契约测试。验证稳定 UID、待存尾部与 revision 的实际边界；未启用自动摄取或 checkpoint-v2。
44. [可读任务工作台](44-readable-task-workbench-zh.md)：原生文字视图、明确 JSON 兼容、安全分页和准确重试/错误提示。
45. [显式记忆到期](45-explicit-memory-expiry-zh.md): 增加明确 UTC 截止时间、默认到期过滤、主动检查和 schema-v5 迁移。到期影响新的召回资格，不改变存储状态或删除正文；原生只读召回永远不迁移存储。
46. [原生任务聚焦](46-native-task-focus-zh.md)：显式选择一条任务，为主对话轮次提供新的有界上下文，复用会话激活，保留整字段预算和已有历史边界。
47. [原子化项目计划](47-atomic-project-plans-zh.md)：多任务全部成功或回滚、持久共享回执、原生/模型/CLI 流程及已核验的 worker 派发限制。
48. [任务到 worker 的提案](48-task-worker-proposal-zh.md)：隔离的 opt-in 纯文本宿主补丁与具体任务消费者，尚未生产派发。
49. [架构决策记录](adr/README-zh.md)：为什么选择这些约束。

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

方案文档与项目规划已建立，E0 基础与显式本地任务收件箱已在临时测试 home 中运行。本地 CLI 持久化与显式启用的原生 LOCAL 会话命令已实现，另有明确激活的进程内模型任务工具；远程渠道/HTTP 个人数据访问尚未实现。没有生产部署、没有接入真实个人数据，也没有宣称权限、提醒或手机语音已经可用。GitHub Projects 是研发计划；Hermes 原生 Projects/Kanban 是未来产品运行时的工作对象，二者不能混淆。

E9 已选定原生 worker 路由设计，并实现离线约束验证器和部分原生契约测试；在线路由 backend 尚未实现。主 agent 保持原有职责；完整约束、宿主能力缺口、开源参考和验收见 [11](11-worker-model-routing-zh.md)。
