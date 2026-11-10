# 08. 路线图、项目拆解与验收

[English](08-roadmap-and-acceptance.md) | 简体中文

当前 E2.7 检查点：[本地后端验收候选](81-local-memory-acceptance-zh.md)取代下文历史性“仅先导切片”状态。SQLite/FTS/投影/编辑提案/精确来源抑制已经实现；原始 #44 验收等待审查、合并及 main CI。E2.6/E2.8/E2.9 与部署仍独立。

## 1. 规划原则

这是实现计划，不是完成报告。未经过代码、测试、部署和用户验收的项不得标 Done。当前 E0.1/E0.2/E0.5 的基础切片进度见 [12](12-foundation-progress-zh.md)；这不等于 E0/M0 或整个 personal agent 完成。

优先完成一个安全可靠纵切，再增加连接器、入口和主动性。阶段按依赖与 gate 推进，不在未知团队规模和可用时间时编造工期。GitHub Projects 管研发交付，运行时 Hermes Projects/Kanban 管用户事务。

## 2. 里程碑

| Milestone | 交付结果 | 进入条件 | 退出门槛 |
|---|---|---|---|
| M0 设计与契约 | 固定基线、可运行的合成测试、最小公共 API 映射、写路径覆盖清单 | 本设计完成 | 缺口和适配路径清楚；没有依赖虚构 API；未覆盖写集合默认关闭 |
| M1 Profile-first 本地 MVP | 可信单用户本地 gateway/profile；持久任务、项目标签和原生对话入口，无需 Bot | 适用的 E0.1/E0.2/E0.4/E0.5、本地 E2.1/E2.2 切片、E6.8；E6.9 作为下一步 | 本地重启、重复、revision、非法输入及宿主准入测试通过；披露未验证范围；无远程/外发能力启用 |
| M2 个人事务 | 事实/承诺、原生多任务、主动观察与可靠通知；可选 E9 路由 shadow | M1；E9 shadow 另需可信约束基线 | 真实场景闭环，资料纠错和遗忘有效；shadow 不改变实际模型 |
| M3 连接与语音 | 最小读写 MCP 集合、手机语音消息、可选实时语音验证及 E9 有界模型路由 | M2 + connector 风险评审；路由另需 E9.5/E9.6 gate | 语音关键字段确认、身份与费用可控；路由质量/隐私/预算门槛通过 |
| M4 发布硬化 | 恢复、备份、升级、回滚、安全评测和文档 | 核心场景完成 | 发布门禁全部满足，没有未处理 P0 |

## 3. Epics 与工作包

### E0. 核验上游兼容契约（P0，M0）

- E0.1：固定 Hermes 支持版本/SHA，建立源码能力矩阵与 license/notice 记录。
- E0.2：最小原生插件注册、config_schema、plugin_data_dir、工具/hook/ctx 契约测试。
- E0.3：验证 Project/Kanban/cron 创建、查询、取消与 receipt 的公共操作路径；缺口记录为 upstream seam，不直接写宿主 DB。
- E0.4：测试 pre_tool_call callback 与 dispatcher 异常、middleware fallback；覆盖原生工具、裸 MCP、shell/browser、execute_code/RPC、批量调用和 worker，未受 action gate 保护的写集合默认关闭或只读降级。专项验证 troubleshooting safe mode 跳过 hooks 时只读降级，以及普通 managed worker 的 frozen config 不影响读取当前持久 policy revision。
- E0.5：建立离线合成 source/connector fixtures，测试不依赖真实个人账号。
- E0.6：在固定宿主上核验客户端传输契约：dashboard API 注册、可信 principal/profile 透传、canonical session RPC、认证/隔离/文件边界及明确不支持模式。依赖 E0.1/E0.2 并采用 E0.4 发现，不代表完整写路径覆盖已完成。见 [14](14-client-api-contracts-zh.md)。

- E0.7：Verify Primary Bot Contracts（M0，Backlog）：依赖 E0.1/E0.2，采用 E0.4 发现。核验原生 profile/route/canonical registry 与 lineage、author/worker provenance 和 receipt；HTTP 模式另需 E0.6。见 [15](15-primary-bot-binding-zh.md)。

- E0.8：Verify Voice Provider Contracts（M0，In progress，仅离线子集）：依赖 E0.1/E0.2，适用时采用 E0.4/E0.7 身份发现。核验固定 ASR/TTS、原生音频/live 协议、凭据、取消和流式契约，列明公开 adapter seam 与不支持模式。见 [19](19-unified-voice-provider-contracts-zh.md)。

- E0.9：Verify Memory Provider Contracts（M0，Done；有界原生契约核验）：依赖 E0.1/E0.2/E0.5。核验真实原生加载/生命周期/单外部 provider、profile/cron/worker 上下文、压缩 checkpoint 与来源引用契约，包括不支持的隔离模式。此门禁仅适用于启用个人记忆，不阻塞已有本地任务闭环。见 [30](30-pluggable-memory-contracts-zh.md)。

验收：每个复用点有一个行为测试或明确 blocker；首次 `requires_hermes` 范围来自测试，不用随意版本号。输出逐工具/逐路径 enforcement 清单；有未知或可绕过的写路径时不得启用该集合，不能用 prompt 约束替代。

当前 E0.4 进度：[有限边界账本](13-enforcement-contracts-zh.md#31-有限验收账本) 将全部 11 条发布路径及 52 个唯一契约映射到精确固定原生入口、可执行断言、独立副作用判据和明确限制。生产包暴露面、并发/替代执行及委派边界构成验收候选，以独立审查、最终账本合并及 Issue #12 记录的 main CI 验证为条件。此范围明确的验证不代表 E0/M0 或 E1 授权完成，不启用受控写入，也不证明宿主全局只读。所有运行时发布门禁仍阻断；生产授权、持久编排和外部效果结果仍属下游工作。

E0.6 是独立的可选客户端契约路线，不阻塞 profile-first local M0/M1 退出；除非明确列出 E0.6、E0.7、E0.8 或 E0.9，现有一般 E0 依赖均指适用的 E0.1–E0.5 门禁。E0.7/E1.6/E3.6 是启用 Primary Bot 能力时的条件门槛，不会静默成为本地收件箱或未绑定本地基线的前置条件。

### E1. 建立身份授权审计（P0，M1）

依赖 E0.2/E0.4。

- E1.1：Owner 与 verified channel binding；群/第三方/转发/机器人身份分类。
- E1.2：ActionIntent、grant、approval schema 与 revision；批准绑定 payload/target/expiry。
- E1.3：领域 handler 操作级检查与原生 approval 适配；拒绝后禁止替代路径绕行。
- E1.4：soft pause、hard revoke、emergency stop，建立授权准入/撤权事务线性化点，取消未准入 effect，对已准入/已发出的在途请求保留真实状态和尽力取消语义。
- E1.5：脱敏审计、敏感数据分类与最小凭据暴露。
- E1.6：Bind Primary Bot（可选后续，Backlog）：依赖 E0.7、E1.1–E1.5、E2.1。实现 owner 确认的 enrollment/recovery、authority 内唯一 active binding、revision/epoch fence、审计及角色。仅绑定不会启用受控写。

验收：所有发布范围内写操作均被覆盖；伪造身份、旧批准、审批后改 payload、policy 故障均无未经授权副作用。撤权 race 测试覆盖“撤权先提交/准入先提交但未发送/远端已接受而本地未知/撤权后下一动作”，依据 admission 与 revoke 的事务顺序断言，不承诺撤回已获许可的远端请求。denied intent 不可复活，新指令须新建并重新授权。

当前准备性实现：[Owner 入口与只读授权基础](18-owner-entry-and-read-authorization-zh.md)提供纯内部评估器和始终拒绝访问的诊断。E0.7 原生 source/IPC 测试证实公开接收 Bot 身份缺失；不签发生产 verified context，不提供 owner 登记、实际 grant/policy authority 或已验证远程 owner 的私人读取。E0.7/E1 门禁尚未完成，不据此启用绑定。

[host 上下文实验](23-host-command-context-experiment-zh.md)为 E0.7 打包仅供审阅的原型。来源真实性、当前 owner/策略准入及受支持的公共 IPC 契约仍是独立门禁。本地仅命令调用修复通过 87 项受守卫测试，但历史九项环境受限测试仍未解决；该实验不启用主 Bot 或已验证远程 owner 的私人读取。

[待确认身份登记/策略核心](26-pending-enrollment-policy-zh.md)已提供拟议映射及读取范围的 CAS、终止性撤销和事务审计持久化，但未接运行入口、不能激活，不构成实际 grant/policy authority 或 owner 认证。

[带栅栏的读取准入核心](27-fenced-read-admission-zh.md)增加内部默认拒绝协调器和实际策略/撤权事务守卫，采用合成 authority/资源 fixture。这只是 E1.3/E1.4 的部分准备，不是生产身份、激活、任务接管或完整读取审计。

### E2. 建立个人领域与记忆（P0/P1，M1–M3）

依赖按信任模式确定。显式可信 profile 本地记忆复用 profile-first 部署契约及 E1.5 的本地审计/数据分类/secret 引用规则，不伪造 owner 身份。已验证远程 owner 开放另需适用的 E1.1–E1.4 和明确资源采用。HTTP、Primary Bot 与语音门禁仅适用于选中的对应模式。

- E2.1：SQLite schema/migration、projects/commitments/facts/sources、revision 更新。 记忆 record/event/receipt 区分 trusted-profile 与 verified-owner namespace；原生任务与会话保留各自权威。
- E2.2：按 scope 检索，明确事实/推断/冲突，原生记忆只放有界摘要。 外部查询前授权，组装有界上下文前验证当前 revision/删除/来源，并评估 token 限额与中文检索。
- E2.3：更正、过期、遗忘、导出与备份恢复 tombstone。 删除优先于重新提取；要求投影/索引/provider purge receipt、符合保留规则的事件载荷及恢复抑制。
- E2.4：人物/项目消歧与任务来源关联，不把第三方转述当 owner 指令。 区分 semantic/episodic/procedural/task 引用、时间冲突及中文姓名/别名；相似度不证明身份。
- E2.5：可选 memory provider 适配评估；兼容用户现有单 provider，不强制替换。 分别评估可替换项目 MemoryBackend 适配器与可选原生 MemoryProvider 桥接；用户可提供合规适配器，并显式选择/迁移。
- E2.6：Define Pluggable Memory Contracts（M1，In Progress；狭窄本地先导）：依赖 E0.9、E1.5 本地审计/数据分类/secret 引用合同及适用本地 E2.1/E2.2 合同。定义版本化 service/backend SDK、record/event/receipt、删除语义与符合性 fixture。
- E2.7：Build Local Memory Backend（M2，In Progress；显式记录先导）：依赖 E2.6、本地 E2.1/E2.2 及适用 E8.1/E8.2 harness。实现权威 SQLite record/event/FTS、生成 Markdown、有界检索、纠错/遗忘与显式本地命令。
- E2.8：Integrate Native Memory Lifecycle（M2，In Progress：召回与审核候选）：依赖 E0.9/E2.6/E2.7 及适用 E6.8/E6.9 入口合同。增加可选单槽桥接、经同意的来源绑定候选/召回，以及带预算的持久生命周期/checkpoint 处理。显式本地记忆工具不要求启用桥接。
- E2.9：Validate Memory Migration and Recall（M3，Backlog）：依赖 E2.7/E2.8 及 E8.1/E8.2/E8.3 harness。验证适配器符合性、带栅栏的导出/切换/恢复/删除竞态及中文/长期召回。

[43](43-native-checkpoint-boundary-zh.md) 增加固定宿主证据门禁与未接入运行时的候选准备；完整检查点仍需与原生提交绑定的来源覆盖交接，不能仅靠 UID 或返回成功。

E0.9 已 Done，证据为 [Issue #42 完成记录](https://github.com/MosBot-AI/hermes-superagent/issues/42#issuecomment-6752608209)、已合并 PR #83、成功的 [main CI](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42705321028)及 [76](76-native-memory-contracts-zh.md) 的固定原生契约矩阵；E2.9 保持 Backlog。这仅完成该核验门禁，不代表 E0、E2.8 或生产部署完成。E2.8 现有 [41](41-native-memory-recall-zh.md) 的可选只读原生召回切片；摄取和持久会话检查点仍待实现。E2.6/E2.7 仅因下述狭窄显式记录先导切片设为 In Progress。[30](30-pluggable-memory-contracts-zh.md) 是完整方案，不是实现报告。现有 E2.1–E2.5 保留其清单 ID 和本地任务证据，不重复创建工作包。

验收：长期事实都有 provenance 或 inference 标记；跨 profile/群聊不可读；纠错与删除后的检索测试通过。

当前 E2.1 前置切片：[显式本地 CLI 任务收件箱](16-local-task-inbox-zh.md) 已实现插件自有 SQLite、原子 receipt、revision 校验及明确本地完成/取消。它不是完整领域 Task/记忆存储、已验证 owner 身份或原生派发。向远程/Bot/HTTP 开放个人数据仍须满足适用的 E1 门禁。E6.8 仅在可信单用户部署契约内允许显式本地命令，不代表 E1 或完整 E2.1 完成。

后续本地扩展已实现[截止日期与 agenda](17-local-task-agenda-zh.md)，包含原子 schema 升级及旧 receipt 兼容测试。它推进 E2.1/E8.3 的狭窄本地范围，不创建提醒，也不完成 E4 或 E1 门禁。

当前 E2.2 先导切片：[本地任务检索](22-local-task-search-zh.md)通过显式启用的本地 CLI 查询，并由 E6.8 本地对话命令复用，支持标题/详情字面匹配，保留当前 schema 与回执；它不是 Agent 记忆、语义检索或 owner 授权的渠道访问。E1 和完整 E2.2 门槛仍未满足。

另一个本地 E2.1/E2.2 先导增加[项目分组](24-local-project-groups-zh.md)：标签、精确筛选、计数及 schema-v3 兼容性。标签不是稳定的领域/原生项目 ID 或权限键。这不代表 E2 或 E3.1 完成，也不放宽其 E1 依赖。

当前本地记忆先导：[31](31-explicit-local-memory-zh.md)实现显式开启的原生操作员命令，以及内部接口后的有界 SQLite 后端。它复用已验证的 E6.8 命令入口与本地存储契约，不启用仍受 E0.9 门禁约束的 provider 模式。自动检索/摄取、完整 SDK、FTS/Markdown 投影、一致迁移和原生桥接均未实现；现有任务模型工具不获得记忆访问权。另行启用的[记忆模型工具扩展](32-session-scoped-memory-tools-zh.md)增加独立会话激活与模型来源标记，真实provider自然语言验收仍未完成。这些推进E2.6/E2.7，不代表它们或完整记忆门禁完成。

[本地任务进度后续切片](42-local-task-progress-zh.md)新增明确记录的工作中/等待/阻碍状态、说明、安全版本重试和活动回顾过滤。任务 schema v4 通过原子升级保留旧回执/事件。这只是本地状态，不是原生 worker 存活证明，也不完成 E3.2/E3.5。

[会话级自动召回](49-session-memory-recall-zh.md)现已在生产独立插件中，通过另行会话选择接入受支持原生轮次 hook。它执行新鲜有界只读检索，不替换原生 provider 或增加模型请求。这推进了 E2.8 的读取部分；自动提取、真实模型实用性和持久会话 checkpoint 仍待完成。

### E3. 接通原生项目任务（P0/P1，M1–M2）

依赖 E0.3、E1.1–E1.5、E2.1。

- E3.1：领域 Project 对接原生 Project/board，保留业务与工作目录差异。
- E3.2：Task ↔ Kanban card/run 映射，acceptance contract、依赖、阻塞与 review。
- E3.3：临时子 agent 的公共 lifecycle API，最小上下文和工具集，父任务汇总。
- E3.4：owner follow-up 优先，线程到任务关联、context-only 和 handback。
- E3.5：重启对账、未知结果、完成证据与取消状态。
- E3.6：Reconcile Primary Bot Sessions（Bot 绑定条件门槛，M2 扩展；Backlog）：依赖 E1.6、E3.2/E3.5、E4.3/E4.4。通过已验证 adapter 解析 canonical root/tip，关联 worker handoff，完成交付与 native receipt 对账。不并行写同一 transcript，不自动跨宿主接管。

验收：一条输入去重为一个任务；多个项目不串上下文；短子任务退出不虚报整个任务完成；长期任务跨重启可查且不会重复派工。

[项目任务依赖](51-project-task-dependencies-zh.md)为 E3.2 的依赖/审核部分增加 profile-first E2/E6 先导：明确同项目边、原子开始/完成门控、ready 队列和一致 focus/review 快照。它不等于原生 Project/Kanban 映射、worker 派发或 E3.5 跨 store 核对；这些仍待完成，可选原生停放卡交接仍需独立持久不确定结果处理。

### E4. 实现提醒与可靠交付（P0/P1，M1–M2）

依赖 E0.3、E1.1–E1.5、E2.1。

- E4.1：一次/周期提醒和 IANA timezone，明确 DST、错过窗口、停止条件。
- E4.2：复用 cron/heartbeat，记录 native job/run/occurrence 与领域目标。
- E4.3：插件自有 effect/outbox/receipt，明确原生 delivery 唯一责任方。
- E4.4：结果未知对账、去重、失效路由、dead letter 与恢复入口。
- E4.5：quiet hours、通知合并、变化检测、attention/compute 双预算。

验收：重复触发、进程中断、发送超时、重启与取消不会导致盲目重复外发；无变化可静默；accepted 不冒充 delivered。

原生 E0.3/E4.2 先导：[计划 blueprint](25-native-planning-blueprint-zh.md)在 Hermes 现有目录中注册可选模板。它不创建或管理 job、不读取本地收件箱，也不实现领域授权/outbox/对账。用户创建的原生 job 在移除插件后仍存在；E4 与 M1 尚未完成。

### E5. 治理 MCP 与插件（P1，M2–M3）

依赖 E1/E4.3。

- E5.1：Connector capability registry：账号、读写操作、版本化输入/输出 schema、数据类别、成本、真实幂等保留期、receipt 级别、对账/取消能力及认证健康。
- E5.2：一个只读 connector 与一个受控写 connector 纵切，包含类型化 prepare/execute/reconcile/cancel 契约、服务端语义校验、逐 effect 准入、稳定 effect key 及部分成功/未知结果测试。若准备阶段有远端副作用，它本身也是受控操作。
- E5.3：最小工具集、MCP trust/filters/OAuth、断连/撤销处理。
- E5.4：插件来源、固定版本、依赖更新、扩权 consent 与供应链清单。
- E5.5：持久预算和 connector receipt，不以原生会话估算代替账单。

验收：伪 read-only、错误 scope、凭据撤销、恶意 tool result 不能产生越权；新连接器必须完成风险与恢复契约后才启用写操作。E5.1/E5.2 保持为现有 Epic 内的 checklist，不新建编号。契约设计可从 E0.6/E1.2 开始；启用写操作还须 E1.3/E1.4、E4.3/E4.4 及该连接器的 E0.4 路径覆盖。凭据仍由原生 OAuth 管理。具体连接器输入、输出与 receipt 见 [14](14-client-api-contracts-zh.md)。

### E6. 打通本地与可选手机工作入口（P1，M1–M3）

E6.1–E6.7 保留适用的 E1.1/E3/E4 远程/手机依赖。E6.8/E6.9 是下述独立本地路线。

- E6.1：一个主手机消息渠道，身份绑定、文字/附件、任务与提醒路由。
- E6.2：跨桌面/手机接续和短候选消歧，重复消息与审批按钮幂等。 选择 Primary Bot 时，E6.1/E6.2 还须核验接收 transport/runtime-profile binding，以及共享领域、分离 transcript 的连续性；共享 profile 不合并聊天，也不证明 bot 账号隔离。
- E6.3：personal overview，优先复用原生 dashboard/plugin UI；验证移动布局。
- E6.4：TLS/auth/session 撤销、附件访问、小屏和弱网测试。
- E6.5：Build Domain API and Change Feed（M2，可选，Backlog）：基于领域服务的版本化类型 REST、事务化去重/outbox/change feed、授权一致快照及轮询概览。依赖 E0.6、E1.1–E1.5、E2.1、E3.2/E3.5、E4.2–E4.4；仅启用逐项验证的 adapter。
- E6.6：Validate Client Recovery Flows（M3，可选，Backlog）：多设备、离线、重放、过期、ACL、隔离及取消场景。依赖 E6.5、E6.2/E6.4 与这些路径所需的 E8.1/E8.2 harness，不等待全部 E8/M4。附件还需 E0.6 文件契约证据。
- E6.7：Validate Native Mobile Sign-in（M3，可选，Blocked）：依赖 E0.6 认证发现、E1.1/E1.4/E1.5 和 E6.4。固定版本的原生流程仅接受 loopback callback，须先证实目标手机支持的 callback 及设备撤权契约，再做真机认证。不得另造插件认证服务。
- E6.8：Enable Local Task Conversations（M1，In progress）：依赖 E0.1/E0.2、适用的 E0.4/E0.5、本地 E2.1/E2.2 schema-v3 TaskStore 切片。显式启用确定性 `/personal-tasks` add/list/search/projects/show/update/done/cancel/agenda，复用校验、revision 和回执；项目仅为标签，不是原生 Project。
- E6.9：Add Session-scoped Task Tools（M1，In progress）：依赖 E6.8 及经测试的宿主 session-scoped 工具上下文、准入与权限边界。添加有界模型任务工具前，验证来源/会话绑定、非法参数、重放及不支持路径；不自动开启，不宣称生产 owner 身份已验证。显式启用的原生进程内工具切片已实现；真实 provider 自然语言验收与跨进程支持仍未完成，见 [29](29-session-scoped-task-tools-zh.md)。

验收：目标真实手机上完成“创建项目 → 提醒 → 查看/取消 → 批准受控动作”；旧设备与转发批准不能操作。这是可选手机路线，不是本地 M1 退出门槛，也不依赖自建 App。可选浏览器/PWA 交付可先于原生手机认证。新增客户端工作仍未实现，详细契约与精确阻断见 [14](14-client-api-contracts-zh.md)。

本地 E6.8/E6.9 仅支持可信单用户本地 gateway/profile 部署。原生 CLI/TUI 的普通会话由 gateway 支持并使用 LOCAL source；宿主 SessionAuthority 检查 owner/operator 会话读取、控制、精确已注册活动 source 与准入。所有已获宿主授权的 owner/operator 控制者共享本地数据访问。Profile 是存储/配置分区，不是人的身份；LOCAL 不证明物理本地性。不新增监听器、认证服务或远程连接器；不支持暴露式、多用户或远程消息部署。待登记和 fenced read-admission 核心仍未接入，保留给未来已验证远程 owner 路线，不是显式本地命令的前置条件。

### E7. 保持语音任务连续性（P1/P2，M2–M3）

生产模式依赖适用的原生/客户端身份契约、E1.3 及 E6.4 安全/设备测试；只有启用可选 HTTP 或原生手机客户端模式时才要求相应 E0.6/E6.5/E6.7。合成 adapter 契约与设计可先行，不把整套可选手机 API 变成所有语音工作的前置条件。

- E7.1：复用 STT/TTS 完成手机语音消息，支持中文、时间/姓名纠正。
- E7.2：语音 action intent 与可见确认，barge-in/停止播放/取消执行分离。
- E7.3：音频隐私与保留、host relay/短时凭据、provider 费用可见。
- E7.4：实时语音路径可行性验证，只有设备和费用达标才扩大发布。
- E7.5：Define Unified Voice Session Contract（M2，M1 可先做设计；In progress，仅合成先导切片）：依赖 E0.8、E1.1/E1.2/E1.4/E1.5；可选 HTTP facade 另需 E0.6。定义 profile/capability、音频/control schema、lease、turn/author 归属、预算隐私与合成参考 adapter。
- E7.6：Implement Local and Online Voice Adapters（M3，Backlog）：依赖 E7.5、E7.1–E7.3；启用动作另需 E1.3 及相关 E0.4 覆盖。实现一条本地/混合 pipeline 与一个明确选定的在线 realtime adapter，不泛化协议兼容。
- E7.7：Validate Duplex Recovery and Voice Quality（M3，Backlog）：依赖 E7.6、E6.4、E8.1/E8.2 harness；关联任务/effect 的恢复另需 E3.5/E4.4。验证设备、延迟、准确率、barge-in、播放对账、重连、预算和隐私。

[文档 19](19-unified-voice-provider-contracts-zh.md)统一 E7.1–E7.4 的配置与安全语义，同时保留语音消息 MVP 和实时双工的独立门禁。[离线模拟器](20-voice-contract-simulator-zh.md)已实现窄范围合成先导切片及公开 ASR/TTS 契约探测。E0.8/E7.5 仍未完成，生产接口、在线传输与主 Bot 权限均未启用。

验收：误识别不造成高影响外发；同任务可在文字/语音切换；断网或停止语音不会伪报外部动作已取消。实时语音是单独 gate，不阻塞已完成的语音消息 MVP。

[原生语音 IPC 实验](21-native-voice-ipc-experiment-zh.md)以审阅工件保留独立测试的宿主适配。项目不会安装它，不改变正式固定版本，不完成 E0.8/E7.5，也不启用 E7.6/E7.7。

### E8. 完成运维评测发布（P0/P1，横贯 M0–M4）

依赖随各能力逐步接入，发布前覆盖全部。

- E8.1：correlation ids、脱敏日志、健康/预算/未知结果面板。
- E8.2：崩溃注入、并发、provider/MCP/channel 故障矩阵。
- E8.3：backup/restore、migration、升级兼容、回滚与数据保留。
- E8.4：固定场景集、observe-mode 评估、误报和成本报告。
- E8.5：安装、配置、停用、权限、隐私与故障排查文档。

发布 Primary Bot 时，E8.2 增加身份/epoch/receipt、clone/restore 故障用例；E8.3 增加 source 先 fence 的 owner-directed 迁移；E8.5 增加选择/暂停/恢复流程。缺少外部 fence 的并发克隆 authority 仍不支持，不能标为恢复通过。

验收：以同一发布 SHA 运行全套 gate；披露跳过/失败项，不把静态检查当运行验证。

启用记忆时，为 E8.1 扩充脱敏来源覆盖、延迟、token/费用及待定提交/清除指标；为 E8.2 增加 checkpoint、未知提交、遗忘后延迟发布的竞态；为 E8.3 增加来源栅栏迁移、非活动导入、保留 tombstone 的回滚与旧 generation 失效；为 E8.5 增加适配器编写、选择、信任/保留及恢复指南。这些只是扩充现有 Epic 清单，不新增 ID 或宣称完成。

### E9. 设计并验证 Worker 路由插件（P1，M0–M3）

详细设计：[Worker 模型与思考强度路由插件](11-worker-model-routing-zh.md)。复用 Hermes delegation backend，按任务在用户配置且允许的 provider/model/effort 集合中选择，不改变主 agent 模型，不强制部署网关。E9.1 已进入 In progress，具备部分原生契约证据与[离线约束样例前置切片](35-offline-worker-routing-zh.md)。[已保存配置 CLI 诊断](38-routing-readiness-inspection-zh.md)新增不输出原始标识符的原生检查，不认证实际 route。E9.2–E9.6 的运行工作仍为 Backlog；未启用在线 shadow 或自动 backend。

| ID | 英文工作包标题 | 主里程碑 | 交付与依赖 |
|---|---|---|---|
| E9.1 | Verify Hermes Routing Contracts | M0 | 依赖 E0；插件注册/route_task/schema pin、模型能力清单、未覆盖路径与兼容测试 |
| E9.2 | Define Trusted Route Context and Constraints | M1 | 依赖 E9.1、E1.1/E1.2/E1.4/E1.5 的身份/grant/撤权/数据 scope 契约，以及 E3.2 的 task/attempt 标识契约；不等待整个 E3 |
| E9.3 | Build Shadow Routing and Audit | M2 | 依赖 E9.1/E9.2；不改变实际 route 的建议选择、脱敏审计与基线评测 |
| E9.4 | Enable Bounded Worker Routing | M3 | 依赖 E9.3、E9.5/E9.6 的启用 gate；有限任务、尝试/截止时间/费用上限、可控回退 |
| E9.5 | Validate Effort and Fallback Policies | M2 | 依赖 E9.1/E9.2；provider wire 映射、未知能力拒绝、fallback 隐私/权限、取消和不重复副作用；M3 重测 |
| E9.6 | Integrate Budget Admission and Release Gates | M3 | 依赖 E9.2、E1.3/E1.4 的准入/撤权、E3.2/E3.5 的 attempt/对账契约、E8.1 审计计量与 E8.2 故障 fixture；完成预算与路由发布 gate，不等待整个 E8/M4 |

验收：只选已许可候选；精确用户 pin 不被覆盖；classifier/reviewer/fallback 同样受隐私与预算约束；requested 与有效 wire effort 可区分，未知明确标注。缺可信上下文/预算 enforcement 时保持 shadow 或拒绝相应自动路由。Shadow 结果不能冒充新模型实际成功率，启用须独立回放/任务验证证据。安全与费用限制未通过不能以“成本优化”理由发布。

## 4. 首次可用纵切顺序

本地优先路线：适用 E0.1/E0.2/E0.4/E0.5 → 本地 E2.1/E2.2 TaskStore 切片 → E6.8 确定性对话命令 → E8.1/E8.2/E8.3/E8.5 的本地持久化、准入、失败、恢复与配置验收 → M1 本地 MVP。随后通过 E6.9 增加 session-scoped 模型任务工具；在单独验证前不能把命令入口称为自然语言任务管理。

可选远程/手机路线仍须 E1.1–E1.5 → 完整 E2.1 → E3.1/E3.2/E3.5 + E4.1–E4.4 → E6.1 及相应 crash/revoke/delivery 验收。启用 Bot 绑定还须 E0.7 → E1.6 → E3.6。自建客户端保持独立可选门禁；本地命令不激活上述能力。

完整 E2.1 的数据分类与审计约定仍需 E1.5。不得把本地 MVP 完成视为广泛 E1、远程撤权、派发或 E3.5/E4.4 对账已完成；这些能力启用前必须通过各自门禁。保留既有研究与阻断记录，不通过重定义本地范围把它们标为 Done。

E9 是可选增强，不把第一版固定模型委派变成依赖新网关的系统。其独立顺序为 E9.1 → E9.2 → E9.3 shadow；E9.5/E9.6 可并行验证，全部 gate 通过后才启用 E9.4，不能先上线自动切换再补可信 scope 和费用控制。

## 5. GitHub Projects 配置建议

- 主 Project：Hermes Personal Agent，描述目标、设计基线和未实现状态。
- Status：Backlog、Ready、In Progress、Blocked、In Review、Done。Blocked 必须有原因与下一步，不把等待确认写成 In Progress。
- 字段：Epic（E0–E9）、Milestone（M0–M4）、Priority（P0/P1/P2）、Area、Risk、Effort、Dependencies、Acceptance evidence。E9 的 Epic/工作包标题采用英文，docs 正文继续中文。
- Views：Roadmap（Milestone）、Execution（Status board）、Security/Blockers、Mobile/Voice、Ready next。
- 先建 epics 和能独立验收的工作包，不用数百条碎任务淹没计划。
- Issue 模板包含 outcome、scope/non-goals、依赖、设计链接、验收、测试/安全、完成证据。父 epic 只有所有必要工作包及验收完成才关闭。

Project 链接、Issue 号与最终字段以实际创建结果为准。若 API/权限限制导致只建 Issues 而没建 Project，应明确记录差异，不把 docs 内的规划表冒充 GitHub Project 已配置。

## 6. 建议 SLO 与测试门禁

这些是待测目标，不是已经达到的承诺。用固定设备、网络和 provider 分别报告，不用供应商异常掩盖本地排队问题。

| 指标 | 初始目标/门槛 | 测法 |
|---|---|---|
| 未授权副作用 | 发布测试集为 0，任一失败阻断发布 | adversarial/故障注入 |
| 重复输入 | 相同幂等键不重复创建任务/已知外发 | 重放、并发、重启 |
| 用户新消息排队 | 主机正常时不被后台无限阻塞；初始 p95 < 2s 进入处理 | 测量 intake 到 turn admission，不含模型答复 |
| 提醒触发 | 主机/渠道健康时初始 p95 ≤ 60s 调度迟到 | 记录 due、admitted、delivered，分段测量 |
| 记忆质量 | source 覆盖 100%；测试集跨 scope 泄露为 0 | 合成冲突/删除/隔离用例 |
| 恢复 | 所有 crash 点有终态或可见 unknown，不能静默丢失 | 每个事务/远端边界注入退出 |
| 语音 | 测首个可听音频、转写和取消延迟；设设备基线后定数值 | 中文/噪声/弱网/打断集 |
| 费用 | 每任务与每天可查；到上限不再自动新增收费动作 | provider/mcp 模拟与账单抽样 |

## 7. Definition of Done

代码审阅 + 对应设计/ADR 更新 + 单元/契约/集成测试 + 安全反例 + 恢复测试 + 用户可见失败路径 + 兼容版本记录 + 真实验收证据。涉及外部系统时保留可脱敏的 receipt/读回，不以模型文字作为证明。任何未执行测试写明原因和风险。

[有界召回扩展](36-bounded-memory-recall-zh.md)新增同一当前读取快照内的显式多关键词字面排序和完整记录预算。E2.7 保持 In Progress；FTS 和 Markdown 投影仍未实现。[41](41-native-memory-recall-zh.md) 后续增加有限的 E2.8 只读原生召回桥接。

[37](37-durable-memory-progress-zh.md)新增本地事件元数据变更分页和持久化消费者进度，并进行原子 v3 迁移。E2.7 保持 In Progress；游标不等于原生对话 checkpoint 覆盖，也不代表完成 E2.8。

[显式到期](45-explicit-memory-expiry-zh.md)增加按 UTC 判断的新召回资格及 schema-v5 迁移，不是删除或自动摄取。E2.7 仍为 In Progress；严格原生 checkpoint-v2、来源对账和原生 worker 编排仍未完成。仅时间流逝不会改变 revision/事件，也不证明检查点的召回有效性。

[原生任务聚焦](46-native-task-focus-zh.md)为 E6.9 增加显式会话选择、轮次开始时的新有界上下文以及真实宿主钩子/API 消息契约。E6.9 保持 In Progress：本切片未完成真实模型自然语言验收、worker 派发或完整 MVP/发布门禁。

[原子化项目计划录入](47-atomic-project-plans-zh.md)推进本地 E2.1/E6.9 流程，把一个计划批次接入持久任务、项目回顾和单任务聚焦。固定生命周期/工具集契约解释了插件仍不声称具备受控 worker 派发的原因。E3.3/E3.5 和真实模型验收仍未完成。

[任务到 worker 的提案](48-task-worker-proposal-zh.md)通过仅供审阅的无工具规划路径及真实宿主/消费者离线集成推进 E3.3 可行性。专用 no-redirect 客户端、持久单次领取/草稿回执及范围内原生操作者工作台推进了可行性，但未完成真实提供商验收、结果不明核对、预算控制或一般工具约束，E3.3/E3.5 仍未完成。

[候选审核流程](50-reviewed-memory-candidates-zh.md)现已通过受支持 hook 实现 E2.8 的当前输入→草稿→操作员审核路径。仅明确接受才创建正式记忆；真实模型实用性、持久会话覆盖与 checkpoint-v2 仍待完成。Schema-v6 迁移和延迟执行的七天候选到期不意味着后台删除。

[停放式 Kanban 交接](52-parked-kanban-handoff-zh.md)增加面向共享原生看板的明确预览、单次提交及有界核对，不完成 worker 派发、通用任务映射或真实 Kanban 验收；这些门槛仍保持未完成。

[原生进度观察](53-native-progress-observation-zh.md)补齐身份绑定停放卡片的明确元数据回读流程，不完成 worker 执行、通用任务映射或真实宿主验收门槛。

新增[已存原生观察关注复盘](54-saved-native-attention-zh.md)：只读本地快照，重叠分类不重复计数，不读取实时看板或改变完成状态。

[受门控的任务规划 worker](55-gated-plan-worker-zh.md): 生产包接线默认关闭，要求准确已审阅宿主约定及当前同意，不代表安装或真实验收。

[原子计划明确依赖](56-atomic-plan-dependencies-zh.md): 显式一基批次引用，同事务保存任务与边，不自动执行。

[明确任务拆解](57-task-breakdown-zh.md): 原子记录步骤、继承前置，并让父任务依赖全部新步骤；不自动执行或完成。

[原生结果审阅与明确本地接受](58-native-result-review-zh.md): 直接审阅不可信卡片结果，再凭重新核对的摘要及人工说明完成本地任务；不自动完成或修改原生卡片。
