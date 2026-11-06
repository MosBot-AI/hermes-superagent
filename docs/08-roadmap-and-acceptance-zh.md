# 08. 路线图、项目拆解与验收

[English](08-roadmap-and-acceptance.md) | 简体中文

## 1. 规划原则

这是实现计划，不是完成报告。未经过代码、测试、部署和用户验收的项不得标 Done。当前 E0.1/E0.2/E0.5 的基础切片进度见 [12](12-foundation-progress-zh.md)；这不等于 E0/M0 或整个 personal agent 完成。

优先完成一个安全可靠纵切，再增加连接器、入口和主动性。阶段按依赖与 gate 推进，不在未知团队规模和可用时间时编造工期。GitHub Projects 管研发交付，运行时 Hermes Projects/Kanban 管用户事务。

## 2. 里程碑

| Milestone | 交付结果 | 进入条件 | 退出门槛 |
|---|---|---|---|
| M0 设计与契约 | 固定基线、可运行的合成测试、最小公共 API 映射、写路径覆盖清单 | 本设计完成 | 缺口和适配路径清楚；没有依赖虚构 API；未覆盖写集合默认关闭 |
| M1 可靠纵切 | 单 owner、单项目、单手机文字入口、一个提醒、受控动作 | E0.1–E0.5 适用门禁、E1.1–E1.5 及恢复/对账基础完成 | 重启/重复/拒绝/撤权测试通过；没有已知绕过 action gate 的启用写路径 |
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

验收：每个复用点有一个行为测试或明确 blocker；首次 `requires_hermes` 范围来自测试，不用随意版本号。输出逐工具/逐路径 enforcement 清单；有未知或可绕过的写路径时不得启用该集合，不能用 prompt 约束替代。

当前 E0.4 进度：[合成失败契约与阻断写清单](13-enforcement-contracts-zh.md) 已实现。这只是部分证据，不代表路径全部覆盖，也不允许启用写操作。

E0.6 是独立的可选客户端契约路线，不阻塞 channel-first M0/M1 退出；除非明确列出 E0.6、E0.7 或 E0.8，现有一般 E0 依赖均指适用的 E0.1–E0.5 门禁。E0.7/E1.6/E3.6 是启用 Primary Bot 能力时的条件门槛，不会静默成为本地收件箱或未绑定 channel-first 基线的前置条件。

### E1. 建立身份授权审计（P0，M1）

依赖 E0.2/E0.4。

- E1.1：Owner 与 verified channel binding；群/第三方/转发/机器人身份分类。
- E1.2：ActionIntent、grant、approval schema 与 revision；批准绑定 payload/target/expiry。
- E1.3：领域 handler 操作级检查与原生 approval 适配；拒绝后禁止替代路径绕行。
- E1.4：soft pause、hard revoke、emergency stop，建立授权准入/撤权事务线性化点，取消未准入 effect，对已准入/已发出的在途请求保留真实状态和尽力取消语义。
- E1.5：脱敏审计、敏感数据分类与最小凭据暴露。
- E1.6：Bind Primary Bot（M1，Backlog）：依赖 E0.7、E1.1–E1.5、E2.1。实现 owner 确认的 enrollment/recovery、authority 内唯一 active binding、revision/epoch fence、审计及角色。仅绑定不会启用受控写。

验收：所有发布范围内写操作均被覆盖；伪造身份、旧批准、审批后改 payload、policy 故障均无未经授权副作用。撤权 race 测试覆盖“撤权先提交/准入先提交但未发送/远端已接受而本地未知/撤权后下一动作”，依据 admission 与 revoke 的事务顺序断言，不承诺撤回已获许可的远端请求。denied intent 不可复活，新指令须新建并重新授权。

当前准备性实现：[Owner 入口与只读授权基础](18-owner-entry-and-read-authorization-zh.md)提供纯内部评估器和始终拒绝访问的诊断。E0.7 原生 source/IPC 测试证实公开接收 Bot 身份缺失；不签发生产 verified context，不提供 owner 登记、grant/policy 持久化或私人读取。E0.7/E1 门禁尚未完成，不据此启用绑定。

[host 上下文实验](23-host-command-context-experiment-zh.md)为 E0.7 打包仅供审阅的原型。来源真实性、当前 owner/策略准入及受支持的公共 IPC 契约仍是独立门禁。历史九项环境受限测试不计为通过，也不启用主 Bot 或私人读取。

### E2. 建立个人领域与记忆（P0/P1，M1–M2）

依赖 E1.1/E1.5。

- E2.1：SQLite schema/migration、projects/commitments/facts/sources、revision 更新。
- E2.2：按 scope 检索，明确事实/推断/冲突，原生记忆只放有界摘要。
- E2.3：更正、过期、遗忘、导出与备份恢复 tombstone。
- E2.4：人物/项目消歧与任务来源关联，不把第三方转述当 owner 指令。
- E2.5：可选 memory provider 适配评估；兼容用户现有单 provider，不强制替换。

验收：长期事实都有 provenance 或 inference 标记；跨 profile/群聊不可读；纠错与删除后的检索测试通过。

当前 E2.1 前置切片：[显式本地 CLI 任务收件箱](16-local-task-inbox-zh.md) 已实现插件自有 SQLite、原子 receipt、revision 校验及明确本地完成/取消。它不是完整领域 Task/记忆存储、已验证 owner 身份或原生派发。向 agent、渠道或 HTTP 开放个人数据前，E1 依赖仍是必需条件；E2.1 和 M1 均未完成。

后续本地扩展已实现[截止日期与 agenda](17-local-task-agenda-zh.md)，包含原子 schema 升级及旧 receipt 兼容测试。它推进 E2.1/E8.3 的狭窄本地范围，不创建提醒，也不完成 E4 或 E1 门禁。

当前 E2.2 先导切片：[本地任务检索](22-local-task-search-zh.md)仅通过显式启用的本地 CLI 查询标题/详情字面匹配，保留当前 schema 与回执；它不是 Agent 记忆、语义检索或 owner 授权的渠道访问。E1 和完整 E2.2 门槛仍未满足。

另一个本地 E2.1/E2.2 先导增加[项目分组](24-local-project-groups-zh.md)：标签、精确筛选、计数及 schema-v3 兼容性。标签不是稳定的领域/原生项目 ID 或权限键。这不代表 E2 或 E3.1 完成，也不放宽其 E1 依赖。

### E3. 接通原生项目任务（P0/P1，M1–M2）

依赖 E0.3、E1.1–E1.5、E2.1。

- E3.1：领域 Project 对接原生 Project/board，保留业务与工作目录差异。
- E3.2：Task ↔ Kanban card/run 映射，acceptance contract、依赖、阻塞与 review。
- E3.3：临时子 agent 的公共 lifecycle API，最小上下文和工具集，父任务汇总。
- E3.4：owner follow-up 优先，线程到任务关联、context-only 和 handback。
- E3.5：重启对账、未知结果、完成证据与取消状态。
- E3.6：Reconcile Primary Bot Sessions（M1 门槛，M2 扩展；Backlog）：依赖 E1.6、E3.2/E3.5、E4.3/E4.4。通过已验证 adapter 解析 canonical root/tip，关联 worker handoff，完成交付与 native receipt 对账。不并行写同一 transcript，不自动跨宿主接管。

验收：一条输入去重为一个任务；多个项目不串上下文；短子任务退出不虚报整个任务完成；长期任务跨重启可查且不会重复派工。

### E4. 实现提醒与可靠交付（P0/P1，M1–M2）

依赖 E0.3、E1.1–E1.5、E2.1。

- E4.1：一次/周期提醒和 IANA timezone，明确 DST、错过窗口、停止条件。
- E4.2：复用 cron/heartbeat，记录 native job/run/occurrence 与领域目标。
- E4.3：插件自有 effect/outbox/receipt，明确原生 delivery 唯一责任方。
- E4.4：结果未知对账、去重、失效路由、dead letter 与恢复入口。
- E4.5：quiet hours、通知合并、变化检测、attention/compute 双预算。

验收：重复触发、进程中断、发送超时、重启与取消不会导致盲目重复外发；无变化可静默；accepted 不冒充 delivered。

### E5. 治理 MCP 与插件（P1，M2–M3）

依赖 E1/E4.3。

- E5.1：Connector capability registry：账号、读写操作、版本化输入/输出 schema、数据类别、成本、真实幂等保留期、receipt 级别、对账/取消能力及认证健康。
- E5.2：一个只读 connector 与一个受控写 connector 纵切，包含类型化 prepare/execute/reconcile/cancel 契约、服务端语义校验、逐 effect 准入、稳定 effect key 及部分成功/未知结果测试。若准备阶段有远端副作用，它本身也是受控操作。
- E5.3：最小工具集、MCP trust/filters/OAuth、断连/撤销处理。
- E5.4：插件来源、固定版本、依赖更新、扩权 consent 与供应链清单。
- E5.5：持久预算和 connector receipt，不以原生会话估算代替账单。

验收：伪 read-only、错误 scope、凭据撤销、恶意 tool result 不能产生越权；新连接器必须完成风险与恢复契约后才启用写操作。E5.1/E5.2 保持为现有 Epic 内的 checklist，不新建编号。契约设计可从 E0.6/E1.2 开始；启用写操作还须 E1.3/E1.4、E4.3/E4.4 及该连接器的 E0.4 路径覆盖。凭据仍由原生 OAuth 管理。具体连接器输入、输出与 receipt 见 [14](14-client-api-contracts-zh.md)。

### E6. 打通手机工作入口（P1，M1–M3）

依赖 E1.1/E3/E4。

- E6.1：一个主手机消息渠道，身份绑定、文字/附件、任务与提醒路由。
- E6.2：跨桌面/手机接续和短候选消歧，重复消息与审批按钮幂等。 选择 Primary Bot 时，E6.1/E6.2 还须核验接收 transport/runtime-profile binding，以及共享领域、分离 transcript 的连续性；共享 profile 不合并聊天，也不证明 bot 账号隔离。
- E6.3：personal overview，优先复用原生 dashboard/plugin UI；验证移动布局。
- E6.4：TLS/auth/session 撤销、附件访问、小屏和弱网测试。
- E6.5：Build Domain API and Change Feed（M2，可选，Backlog）：基于领域服务的版本化类型 REST、事务化去重/outbox/change feed、授权一致快照及轮询概览。依赖 E0.6、E1.1–E1.5、E2.1、E3.2/E3.5、E4.2–E4.4；仅启用逐项验证的 adapter。
- E6.6：Validate Client Recovery Flows（M3，可选，Backlog）：多设备、离线、重放、过期、ACL、隔离及取消场景。依赖 E6.5、E6.2/E6.4 与这些路径所需的 E8.1/E8.2 harness，不等待全部 E8/M4。附件还需 E0.6 文件契约证据。
- E6.7：Validate Native Mobile Sign-in（M3，可选，Blocked）：依赖 E0.6 认证发现、E1.1/E1.4/E1.5 和 E6.4。固定版本的原生流程仅接受 loopback callback，须先证实目标手机支持的 callback 及设备撤权契约，再做真机认证。不得另造插件认证服务。

验收：目标真实手机上完成“创建项目 → 提醒 → 查看/取消 → 批准受控动作”；旧设备与转发批准不能操作。M1 使用已有消息渠道，不依赖 E6.5–E6.7 或自建 App。可选浏览器/PWA 交付可先于原生手机认证。新增客户端工作仍未实现，详细契约与精确阻断见 [14](14-client-api-contracts-zh.md)。

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

### E9. 设计并验证 Worker 路由插件（P1，M0–M3）

详细设计：[Worker 模型与思考强度路由插件](11-worker-model-routing-zh.md)。复用 Hermes delegation backend，按任务在用户配置且允许的 provider/model/effort 集合中选择，不改变主 agent 模型，不强制部署网关。以下都是待实施工作包，当前为 Backlog。

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

E0.1–E0.5（含适用写路径覆盖与关闭未覆盖集合）→ E1.1–E1.5（身份、授权、执行检查、硬撤权、审计/数据分类）→ E2.1 → E3.1/E3.2/E3.5 + E4.1–E4.4（含任务恢复、结果未知与交付对账）→ E6.1 → E8.1/E8.2 对应的 crash/revoke/delivery 测试 → M1。

Bot-bound M1 还须通过 E0.7 → E1.6 → E3.6 及适用的恢复/交付门槛。显式 local_tasks 收件箱不会启用该绑定；自建客户端仍为可选路线。

E2.1 在 E1.5 的数据分类与审计约定明确后进入。M1 不能跳过 E1.4 再宣称 revoke 通过，也不能把 E3.5/E4.4 的恢复对账留到后面却宣称可靠纵切完成。随后才做更广泛自动主动性和更多 connectors。身份、安全、恢复不是“最后补一层”。

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
