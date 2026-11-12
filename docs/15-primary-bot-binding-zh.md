# 15. 主 Bot 绑定与连续性

[English](15-primary-bot-binding.md) | 简体中文

**状态：可选后续设计，尚未实现，不是 profile-first 本地 MVP 的前置条件。** 若选择此能力，用户选择一个现有的 Hermes **Bot Mode Bot** 作为个人 super agent。这不会创建另一套 agent loop、改变 Hermes 的全局/默认 Bot，也不会授予新权限。下文所有绑定记录、服务方法、角色、事件和能力标志均属于这套拟议插件设计。当前 CLI 任务收件箱是一项独立的本地功能，不能证明 Bot 绑定或 owner 身份认证已经实现。

本设计的源码基线为 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。当前固定版本的兼容性验证涵盖[名册](#当前固定版本的原生-bot-chat-名册)、[Desktop 路由](#当前固定版本的-desktop-profile-路由)、[原生 profile 生命周期](#当前固定版本的原生-profile-生命周期)、[同一安装内 Bot 消息](#当前固定版本的同一安装内-bot-消息)和 [Bot Chat 延后投递](#当前固定版本的-bot-chat-延后投递)。请结合 [03](03-native-architecture-zh.md)、[06](06-plugins-mcp-and-security-zh.md)、[11](11-worker-model-routing-zh.md) 和 [14](14-client-api-contracts-zh.md) 阅读本合同。

准备性代码与契约证据见[文档 18](18-owner-entry-and-read-authorization-zh.md)：只读评估器已实现，但公开接收 Bot 身份缺失，该远程/Bot 路线的生产 owner context 和私人读取仍关闭。以下绑定流程仍为设计。

当前默认路线见 [08](08-roadmap-and-acceptance-zh.md) 的 E6.8/E6.9：可信单用户本地 gateway/profile 中的原生 LOCAL 会话，无需 Bot 登记。Profile 不是身份；LOCAL 不是物理本地性证明。宿主 SessionAuthority 的 owner/operator 读取、控制、精确已注册活动 source 及准入检查仍适用，所有已获宿主授权的控制者共享本地数据。本文的远程 owner/绑定门禁不因本地命令而视为通过；未接入的待登记/读取准入核心也不是显式本地命令的前置条件。

## 1. 决策与用户体验

在这条可选 Bot 绑定路线中，个人主 agent 是用户选择的原生 Bot：其 profile 持有个人领域状态，其**规范 Bot Chat（canonical Bot Chat）**是首选的协调会话。Hermes 仍负责推理、会话、压缩、worker 执行、cron、凭据和传输。插件提供个人领域上下文、任务、策略和证据。

预期设置流程为：选择现有 Bot 及其所在机器，审阅确切目标和数据范围，确认绑定，然后显示 **主 Bot：<显示标签> · <已验证的连接/profile>**，并单独显示能力/健康状态。绑定现有 Bot 会保留它的模型、SOUL、记忆 provider、凭据、普通会话和例行任务。不会自动复制、执行破坏性重置、更换模型或重命名其他会话。

这项主 Bot 指定属于插件职责，不是 Hermes 保留的 `@hermes` 别名，也不是桌面端的当前/默认 profile。打开另一个 Bot 不会切换个人主 Bot。其他 Bot 仍可用于各自的工作。

## 2. 原生事实与边界

| 在固定版本已核对的事实 | 对本设计的影响 |
|---|---|
| Bot Mode Bot 是一个带有名册元数据和规范 Bot Chat 的 profile [B1] | 绑定原生 profile 和规范会话注册表，而不是新建 persona 或平台 token |
| 插件管理器和持久化插件状态以 Hermes home/profile 为作用域 [B2] | 必须在选定的 profile 中启用后端；安装 UI 代码不会绑定所有 Bot |
| 桌面端提供 `host.profileRoutes()` 和支持路由的 `host.requestProfile()` [B3] | 使用完整、经过验证的路由描述符；绝不只按显示名称选择 |
| `profiles.list` 提供 `canonical_session.id` 及其压缩后的 `resolved_id` [B4] | 解析权威的规范会话，而不是 `last_session`、worker 会话或缓存的 UI 元数据 |
| 安装有一个不透明的 `install_id`；profile 名称/路径可能变化，这里没有暴露不可变的 profile 实例身份 [B5] | 安装 ID 和 slug 可用于定位，但不是身份认证，也不足以作为恢复证据 |
| `ctx.inject_message` 以 profile 为作用域、受能力关卡控制，且只返回表示宿主是否接纳的布尔值 [B6] | 它不是持久化的恰好一次投递 API，也不能证明 Bot 已回答 |
| 平台路由区分接收侧的 `bot_profile` 与执行侧的 `profile`；会话键包含平台/聊天/线程/用户 [B7] | 同一 profile 不自动等于同一会话或同一传输账号 |
| Hermes 在受管理安装中为已启用协议的 Bot Chat 会话提供 `message_agent` [B8] | 符合条件的 Bot 可通过原生路径协作。Owner grant 和 worker 路由各有独立关卡。 |
| Cron 可通过原生权限准入机制以 `bot-chat[:profile]` 为目标 [B9] | 复用原生回执和调度；绝不对同一个 Bot Chat 运行第二个写入者 |

这些是参考合同，不代表可以把私有模块导入作为受支持的插件 API。尤其是规范会话注册表实现、profile 重命名内部机制和 Bot 投递邮箱，它们都是**源码证据**，不是新增的 `ctx` 方法。E0.7 必须证明受支持的适配器可用，或报告通用的上游接口缺口。不得虚构 `ctx.bind_main_bot`、`ctx.current_owner` 或原生不可变的 `bot_uuid`。

### 当前固定版本的原生 Bot Chat 名册

名册夹具在干净的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上经由原生网关 `/api/ws` ASGI 边界调用 OpenRPC 方法 `profiles.list`。夹具使用合成本地票据和临时 profile 及会话存储，无需真实监听器、桌面客户端、模型或账户。连接协商 `hermes-gateway-v1`，并收到带 `session_authority: true` 的 `gateway.ready`。[名册契约测试](../tests/contracts/test_native_bot_roster_asgi.py) · [网关 OpenRPC](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/shared/src/gateway-contract.openrpc.json)

| 夹具场景 | 观察结果 |
| --- | --- |
| 宿主作用域的票据显式选择已提供服务的同级 profile | 两个 profile 使用相同的显示标签，返回不同的规范会话 ID。被选中的 profile 排在首位，其隐藏的精确 `Bot Chat` 提供 `canonical_session.id`。`resolved_id` 和预览来自压缩末端。`last_session` 和 `worker_session` 分别指向独立的编号会话和 worker。 |
| Profile 作用域的交互票据 | 票据所属 profile 返回自身的会话字段，包括存储的会话所有者与票据主体不同的规范会话。同级 profile 仅返回发现元数据，省略 `canonical_session`、`last_session` 和 `worker_session`。显式请求该同级 profile 返回 `profile_mismatch`。 |
| `worker-adoption` 票据 | `profiles.list` 返回 `permission_denied`。 |
| 同级 profile 开始退役后的宿主作用域名册 | 退役中的同级 profile 只返回元数据，仍提供服务的 profile 继续返回自己的规范会话。 |
| 未绑定的历史精确标题会话，或可恢复的自动归档精确标题会话 | 经授权的名册返回 `canonical_session: null`。编号会话仍为近期会话，未新建、收编或恢复记录。 |
| 两个隔离 ASGI 端点使用不同的运行时实例 ID，但使用相同的预置 `install_id`、profile slug 和显示标签 | 各端点用自己的票据返回自身的 profile 路径、规范会话根、压缩末端及预览。相同的安装观测值无法确定会话属于哪个端点。 |
| 安装 ID 不可读 | 夹具用目录模拟不可读的标记。名册返回空的 `install_id`，仍报告经授权的规范会话。 |

夹具隔离执行、套接字连接及监听和无关的网关后台活动。它在请求前后比较会话、消息、准入和状态元数据记录，并检查原生 authority 上没有遗留连接或已附加会话。预置的安装标记保持原样，也未出现新的安装锁文件。不可读标记仍为空目录。[名册契约测试](../tests/contracts/test_native_bot_roster_asgi.py)

原生准入路径为成功核销的本地 `interactive` 票据授予 operator 权限。票据的 `profile` 或 `host` 作用域独立决定请求能否到达同一进程中的其他 authority。此验证覆盖本地 operator 契约。人的 owner 身份、远程认证和公开插件调用方上下文各需独立证明。[原生网关准入](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/run_api.py#L452-L490) · [当前固定版本的 owner 证据边界](78-enrollment-ceremony-zh.md)

Authority 名册使用 `reopen=False` 读取现有会话存储。精确标题的 `session.list` 路径可能收编满足条件的历史记录，用于发现前需单独验证。名册的 `install_id` 来自提供服务的 Hermes 根目录。缺少 ID 或格式有误时，解析器可在可写根目录生成 ID。文件系统副本可以保留同一 ID，因此宿主连续性需要独立证据。[名册实现](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_group_controls.py#L389-L450) · [历史会话收编夹具](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/gateway/test_bot_roster_fleet.py#L94-L102) · [安装身份解析器](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/install_identity.py)

### 当前固定版本的 Desktop Profile 路由

五项 [Desktop 路由组合测试](../tests/desktop/test_profile_route_composition.mjs)在 Node.js `26.12.1` 上通过。测试使用合成输入以及替代的状态存储和传输边界，运行干净的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 中的名册、路由生成、SDK 请求和 Bot Mode 路由模块。组合测试未涉及 Electron IPC、渲染进程的网关连接池、后端连通性或 owner 连续性。

| 夹具场景 | 观察结果 |
| --- | --- |
| 两个连接暴露同名的 Desktop profile，各自映射到不同的后端 profile | 清单保留两条带来源的路由，且不暴露凭据。Bot Mode 按各自的 `connectionId` 和 Desktop `profile` 发送请求，并将 RPC 的 `profile` 参数改为对应的 `targetProfile`。直接调用 SDK 时保留传入的 RPC 参数。 |
| 已缓存的离线 SSH profile 和尚未拨号的 SSH 清单 | 缓存 profile 和初始 `default` 路由各发出一次请求，使用各自的连接和后端 profile。两个替代网关均拒绝。请求日志中只有这两次限定来源的尝试。 |
| 描述符不完整或单独提供的 profile 存在歧义 | SDK 在调用替代网关前拒绝。 |
| 已注册路由、替换目标和移除来源 | 精确注册检查接受字段相同的描述符，并拒绝 `targetProfile` 已变更及来源已移除的描述符。显式使用已移除的描述符请求 SDK 时，仅到达原来的替代网关并被拒绝。 |
| 安装标记缺失或被复制 | 两个来源均缺少安装标记时保留两条路由。同一 profile 具有相同的非空标记时，两条记录合并至配置的主连接。 |

固定版本的 Desktop preload 提供 `getProfileRoutes` 和限定连接范围的拨号桥接。主进程根据连接注册表和名册构建路由清单。SDK 首次发送显式请求时校验描述符的三个字段，并将调用转交网关状态模块。SDK 在显式路由的 hydration 重试前核对注册表中的三个字段，只重试一次。已保存的连接可以保留 ID 并更换端点，因此该比较无法单独证明后端连续性。[Preload 桥接](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/preload.ts#L53-L64) · [注册表路由清单](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14284-L14358) · [SDK 请求与注册检查](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/profile-request.ts) · [Hydration 重试](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/index.ts#L1098-L1116) · [连接编辑](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L8568-L8589)

渲染进程可以复用匹配的主连接，也可以为同一来源的其他 profile 复用共享的主后端。探测 profile 的服务范围失败时，远程主连接也可能继续为同一来源提供服务。清单可能包含缓存的本地 profile，或尚待拨号的 SSH 初始路由。复制的安装标记可能让不同端点在 Desktop 清单中合并，即使各端点在独立测试中会返回各自的规范会话。[主连接复用](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/store/gateway.ts#L348-L409) · [路由清单生成](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/main.ts#L14294-L14351) · [原生端点夹具](#当前固定版本的原生-bot-chat-名册)

可选的[渲染进程网关连接池测试](../tests/desktop/desktop_profile_route_pool.test.ts)在 Vitest 中通过一项用例。它运行固定版本的注册表、路由生成、Bot Mode 路由逻辑、SDK 请求函数和渲染进程网关状态模块。测试用 SDK 门面将请求转交实际的请求函数。Desktop 桥接和网关传输使用替身。两个同名的非主来源路由打开各自的连接池条目，使用替代桥接各自返回的新 WebSocket URL，并发送对应的后端 profile 参数。夹具从替代注册表中移除一个来源，并调用渲染进程的清理入口。该条目关闭。后续向该来源发出的请求在限定来源的连接解析阶段失败，早于 WebSocket URL 查找和 RPC 调用。另一个条目保持打开，主连接、当前活跃网关和旧版请求路径均未被调用。

复现此可选测试时，使用可丢弃的 Hermes 检出，确认提交与固定版本一致且跟踪文件无改动。设置隔离的 `HOME` 和 `HERMES_RUNTIME_DIR`，并使用 Node.js `26.12.1` 和 pnpm `12.15.0`。在 Hermes 根目录运行 `pnpm install --frozen-lockfile --ignore-scripts --filter . --filter '{./apps/desktop}...'`。将本仓库的 `tests/desktop/desktop_profile_route_pool.test.ts` 复制到 `apps/desktop/src/store/`，运行 `pnpm --dir apps/desktop run test:ui src/store/desktop_profile_route_pool.test.ts`，运行结束后移除复制的测试文件。CI 单独运行无需依赖的 Node 组合检查。

同一固定版本使用 Vitest `4.1.12`、Node.js `26.12.1` 和 pnpm `12.15.0` 通过 261 项不同的上游用例。UI 项目通过 157 项上游用例。Bot Mode 的四个测试文件 `routing.test.ts`、`data.identity.test.ts`、`data.roster.test.tsx` 和 `canonical-chat-registry.test.ts` 共 81 项。SDK 的 `profile-routing.test.ts` 和渲染进程的 `gateway-profile-request.test.ts` 分别为 49 项和 27 项，与本项目独立的连接池夹具一同运行。基于 Node 的 `electron` 项目在 `connection-registry.test.ts` 中通过 104 项。这些专项测试使用合成输入。实际 Electron IPC 和真实网关连接仍待验证。[Bot Mode 测试](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/plugins/hermes-bots) · [SDK 路由测试](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/sdk/profile-routing.test.ts) · [渲染进程请求测试](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/store/gateway-profile-request.test.ts) · [注册表测试](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/electron/connection-registry.test.ts)

### 当前固定版本的原生 Profile 生命周期

生命周期测试使用干净的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 和合成 profile。CLI 夹具在已停止的 home 中运行原生 profile 参数解析和分派，并替换服务管理、shell 别名及技能同步子进程。测试限制网络连接、监听器和 SDK 安装。独立的拒绝用例在控制调用边界替换运行中多路复用器的响应。[原生 profile 生命周期测试](../tests/contracts/test_native_profile_lifecycle.py) · [身份清理测试](../tests/contracts/test_native_profile_identity_settlement.py)

原生重命名先移动命名 profile 的 home，再按新名称迁移会话与路由身份。`previous_names` 是尽力写入的元数据。目录移动成功后，身份迁移仍可能未完成。原生命令 `profile migrate-identity <old> <new>` 可独立重试持久化迁移。重命名默认 profile 只更改显示名称。[原生 profile 生命周期](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profiles.py#L2213-L2310) · [Profile 身份迁移](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profile_identity.py#L29-L85)

删除会在移除命名 profile 的 home 前写入删除标记。身份清理单独处理以名称为键的路由、心跳与投递记录。若该名称重新成为有效 profile，清理会拒绝。同名重建可以复用安装内的定位信息。原生 `--clone-all` 可以复制展示元数据，同时排除会话历史、检查点及 cron 数据。[原生创建与删除](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profiles.py) · [身份清理](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/profile_identity.py#L55-L138)

| 停止状态 CLI 夹具场景 | 观察结果 |
| --- | --- |
| 重命名已有 Bot profile | 旧 slug 不再解析，活动 profile 随目录迁移。隐藏的精确 `Bot Chat` 保留根会话、压缩末端及消息。根会话和压缩末端两条记录的 `profile_name` 及共享路由使用新 slug，无关的共享路由保持原样。 |
| 用 `--clone-all` 克隆到旧 slug | 克隆与重命名后的 profile 有相同的显示标签和 `previous_names`，并复制合成插件数据标记。克隆排除源 `state.db` 及预置的 `cron/jobs.json`。两个 profile 各自在列表中出现。 |
| 删除含有已写入本地数据库的重命名 profile | CLI 以状态 `1` 退出并报告身份清理未完成，因为删除标记阻止清理流程打开命名 profile 的数据库。目录已经移除，活动 profile 重置为 `default`，共享路由已清理，无关路由仍保留。移除后执行 `profile purge-identity` 成功。 |
| 清理完成后重建同一 slug | 新 profile 使用相同路径和安装标记，并清除删除标记。其 `previous_names` 列表为空。合成插件数据标记及原规范根会话和末端均不存在。 |

替身多路复用器拒绝清理身份时，原生删除在移除已标记的 profile 后报告 `ProfileIdentitySettlementPending`。此时共享根目录中的路由、心跳和历史会话记录保持原样。停止状态下两次调用 `profile purge-identity`，以幂等方式清理确切的已删除名称，并保留名称相近的路由、心跳以及共享会话历史。重建同一 slug 并使其重新有效后，再次清理以状态 `1` 退出，并保留同一键下的新路由。[身份清理测试](../tests/contracts/test_native_profile_identity_settlement.py)

迁移后的数据库中存在目标路由键冲突时，重命名会留下部分完成的状态。目录已移动，共享根数据库已迁移，CLI 发出警告，迁移后的 profile 数据库保持原样。冲突存在时，显式重试 `profile migrate-identity` 以状态 `1` 退出。夹具移除合成的冲突记录后，同一原生命令迁移 profile 的会话字段与路由，保留规范会话谱系和消息。再次重试保持幂等。[身份清理测试](../tests/contracts/test_native_profile_identity_settlement.py)

停止状态安装复制夹具在复制合成根目录前关闭 authority 和会话数据库。原件与副本独立、依次启动，并使用新签发的本地票据。`profiles.list` 返回相同的安装标记、profile 标签和规范会话摘要，包括相同的根会话及压缩末端。夹具中经准入的 `runtime.describe` 调用返回不同的运行时实例 ID 和 profile 路径。名册读取前后，每次启动所记录的数据库快照保持一致。安装标记与规范会话谱系相同，仍无法确定应信任哪个 authority。[停止状态安装的名册夹具](../tests/contracts/test_native_bot_roster_asgi.py) · [身份识别限制](#33-必须明确展示身份识别的限制)

真实运行环境下的 Desktop 路由与 profile 生命周期转换、经权威证明的恢复连续性、受支持的调用方与 worker 来源证明及更广泛的投递回执对账，仍属 E0.7 的开放事项。可选 HTTP 入口仍依赖 E0.6。经 owner 授权的登记、激活绑定及对账仍是 E1.6 和 E3.6 的独立工作。[Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33)

## 3. 身份、存储与作用域

### 3.1 三种不同的身份

1. **人的权限身份：** 来自 E1 的已验证 owner/principal 及当前 grant/策略。本地 CLI 操作者、profile 名称、Bot 标签、`is_bot` 标志或客户端 JSON 都不是这种身份。
2. **原生目标：** 已认证的宿主路由、安装观测结果、后端 profile 和规范会话谱系。客户端的 `connectionId + profile` 用于定位注册表路由；`targetProfile` 可能不同。连接 ID 只在客户端本地有效，不是可跨客户端使用的服务端 ID [B3]。
3. **插件登记：** 插件自有的随机 `enrollment_id` 和 `binding_id`，存储在选定 profile 的插件数据库中。它们标识登记记录，不是宿主签发的身份、secret 或权限 token。

后端从已验证的宿主上下文派生自身的 profile 作用域。不得从请求中接受任意文件系统 home。`ctx.profile_name` 只是便于使用的标签，不足以认证身份；在该固定版本中，其出错时的回退值可能是 `default` [B2]。缺少可信身份/作用域时，必须阻止受保护的绑定操作。

### 3.2 拟议记录

```json
{
  "schema_version":"personal.primary_binding.v1",
  "binding_id":"bind_example",
  "enrollment_id":"enroll_example",
  "owner_id":"owner_verified",
  "authority_id":"authority_example",
  "binding_epoch":1,
  "revision":1,
  "state":"active",
  "target":{
    "observed_install_id":"opaque-host-install-id",
    "backend_profile":"personal",
    "canonical_root_id":"session_example",
    "resolved_session_id":"session_tip_example"
  },
  "continuity_mode":"shared_domain_separate_transcripts",
  "policy_revision":31,
  "confirmed_by":"verified-principal-ref",
  "confirmed_at":"2026-11-06T10:00:00Z"
}
```

这是未来处于 active 状态的记录示例，不代表目前已经就绪。`authority_id` 标识插件自有的这份策略/领域存储，不是第二套运行时或全局注册表。已认证的本地服务端将记录关联到自己的存储 home；客户端 DTO 不包含路径和凭据。客户端单独保存路由描述符，并在连接时重新解析。

在这份权威存储中，每个 owner 只允许一个 active 绑定，由数据库唯一性约束强制执行。绝不能基于 profile 本地数据库声称实现了整个安装范围或跨机器的单例约束。V1 支持一份明确指定的权威存储，不支持双活副本。在另一个 profile 启用该包，不会完成登记，也不会复制 grant。

其他拟议记录包括 `binding_proposals`、`binding_audit`、`session_roles`、`worker_handoffs` 和 `delivery_correlations`。引用包含绑定 epoch、策略修订号、原生会话/run ID 和不可变的操作 ID。复用 [04](04-domain-data-and-memory-zh.md) 和 [05](05-automation-and-delivery-zh.md) 中的领域/outbox/审计机制，不创建第二套完整会话记录存储或调度器。

### 3.3 必须明确展示身份识别的限制

安装 ID 文件或插件登记记录可能随备份一起被复制。两者都不能证明恢复/克隆后的宿主就是原宿主。`previous_names`、路径和相同标签都不能证明 profile 的连续性。使用旧名称的新 profile，绝不能仅凭名称继承登记。

自动恢复要求具备当前已认证的目标证据、可读取且符合预期的安装身份、预期登记、规范会话谱系，并且不存在冲突的权威方观测结果。profile 定位信息变化、登记丢失、安装不匹配、身份重复或无法解释的谱系，都需要 owner 审阅恢复。如果宿主无法区分克隆与原件，就报告 `identity_ambiguous`，不得虚构确定性。防范同一用户权限下的恶意代码或并发运行的克隆磁盘，需要外部 fencing 权威服务和操作系统隔离，不在 v1 范围内。

## 4. 登记与控制合同

### 4.1 初始绑定

1. 发现可访问的原生 Bot/profile 路由。显示友好标签、机器/连接、后端 profile、可用性，以及能否验证已有规范 Bot Chat。仅能发现元数据，不代表有权读取其历史记录。
2. 验证选定路由、当前 owner 授权，以及该 profile 中是否存在插件。缺少安装/同意时，必须作为明确的设置步骤处理。绝不默默在所有 profile 中启用插件，也不复制 provider 凭据。
3. 通过 E0.7 已证明可用的适配器解析已有规范 Bot Chat，优先使用经过验证的原生 canonical registry/roster 给出的根会话 ID 与谱系。原生通信路径也支持经过授权的 `session.list` 标题查询；精确匹配 `root_title == "Bot Chat"`（或在已验证的较旧数据结构中精确匹配 `title`）只是兼容性筛选，不是身份或 owner 授权证明。拒绝泛化匹配带编号的标题。分别记录根会话和当前谱系末端。若没有可信 registry/来源合同，该能力保持不可用；标题相同不能替代它。RPC 错误、缺少访问权限，或先前已有正面证据后返回空结果，都表示**未知**，不代表有权创建新聊天 [B10]。
4. 准备短期有效的绑定提案，其中包含确切目标、登记、预期修订号、数据/角色范围和证据。该步骤不向外发送消息，也不改变 active 绑定。
5. 向已验证的 owner 展示与 nonce 绑定的预览。确认在一个事务中完成：检查当前身份、有效期和修订号；消费提案；建立唯一绑定；按需递增绑定/策略栅栏；持久化审计/变更行。重复确认返回原始回执。
6. 只公布已分别通过独立关卡的能力。即使绑定为 active，受控写入、worker 启动和主动投递也仍可能禁用。仅完成选择绝不会启用这些能力。

V1 选择的是**现有 Bot 和规范聊天**。如果没有已验证的 Bot Chat，引导 owner 完成原生 Bot Mode 设置后重试。本插件不会默默创建/重命名会话，也不会写入 `ui_meta.hermes-bots` 来伪造成员资格。只有证明同样的原生身份/会话合同成立后，才支持无界面登记；仅配置 `bot_mode_protocol: true` 并不充分 [B8]。

### 4.2 拟议服务方法

这些是未来 CLI、原生 UI 和可选 HTTP 适配器共用的内部领域服务合同，**不是现有 Hermes RPC 名称**。UI 选择可以使用原生读取 API，但变更仍必须进入经过 owner 验证的绑定服务。当前本地任务 CLI 不提供这些方法。

| 拟议方法 | 输入与输出 |
|---|---|
| `primary_binding.inspect` | 返回当前有权访问的绑定、健康状态、发布关卡和 ETag；不包含 token 或 home 路径 |
| `primary_binding.propose` | 输入服务端解析的候选目标和请求范围；返回提案 ID、确切预览、到期时间和一次性展示凭据 |
| `primary_binding.confirm` | 输入提案 ID、展示 nonce、预期修订号和幂等键；返回绑定回执 |
| `primary_binding.pause` | 输入当前绑定的 If-Match 和原因；提交新栅栏，并停止新的依赖绑定的准入 |
| `primary_binding.resume` | 输入当前修订号，并在目标/策略检查后重新获得 owner 确认；不是 worker/模型命令 |
| `primary_binding.recover` | 输入针对同一登记准备的恢复提案；返回已确认的映射或明确阻塞项 |
| `primary_binding.retire` | 输入当前修订号和 owner 决定；留下持久化墓碑记录，使绑定 grant/展示凭据失效，并报告在途工作 |

准备提案要求当前 owner 访问权限和 `personal.primary_binding.manage`，但不要求事先确认这份尚未提交的提案。提交登记、恢复、暂停/恢复运行或退役时，既要求该 scope，**也要求已验证的 owner 对确切预览进行确认**。Scope 是必要条件，但不是充分条件。展示凭据复用 [14](14-client-api-contracts-zh.md) 中的 256 位 nonce、默认五分钟有效期、principal/payload/修订号绑定和单一决定规则。自动保护性暂停/设栅栏可以不等待确认就收回权限；绝不能授予权限或恢复绑定。模型/worker 不能生成自行确认的提案。服务端解析必须拒绝客户端提供的 principal、authority、epoch、grant 或文件系统路径字段。应用 [14](14-client-api-contracts-zh.md) 中的幂等、授权、ETag 和错误约定；内部绑定命令使用稳定的 owner/authority/method/key 命名空间，每个提案只允许一个决定，而 HTTP facade 保留 [14](14-client-api-contracts-zh.md) 中的 owner/profile/method/route/key 传输命名空间。绑定变更绝不会续期已经过期的批准。

可选 HTTP/UI facade 仍受 E0.6/E6.5 和可信 principal 传递机制约束。隔离托管 HTTP 的准入布尔值并不充分。原生渠道/CLI 绑定适配器仍需自行提供 E0.7/E1 身份证明；能够访问本地进程不能替代身份验证。

## 5. 生命周期、恢复与重新绑定

持久化绑定状态为 `unbound → active ↔ suspended → retired`；`active` 或 `suspended` 可以进入 `recovery_required`。提案是独立记录（`pending | confirmed | expired | cancelled`），因此打开选择器绝不会移除一个正常工作的绑定。对该绑定 ID 而言，`retired` 是终态。健康状态独立存在（`verified | offline | incompatible | identity_ambiguous | storage_unavailable`），且绝不授予权限。

身份与对账通过后，经 owner 确认的恢复将 `recovery_required → suspended`。仅当精确预览已明确包含恢复运行，且所有相关门禁此时均通过，才可在同一次决定中提交 `active`；否则需要之后再由 owner 确认 resume。退役先提交保护性栅栏，再进入绑定终态；尚未解决的在途 effect 保留在账本中，不会随绑定退役消失。

| 变更或故障 | 必须采取的行为 |
|---|---|
| 连接别名/URL 改变，但已认证宿主和 profile 相同 | 重新解析注册表路由并验证登记；只更新客户端路由；不因外观标签变化而递增权限版本 |
| Bot 显示标题/头像改变 | 只刷新显示；不重写权限，也不选择另一个 Bot |
| 压缩推进规范会话末端 | 沿着宿主证明的谱系，从同一规范根继续解析；保留绑定 ID/epoch 和逻辑操作 ID |
| Profile slug/路径重命名 | 进入恢复状态，直到宿主迁移、同一登记和 owner 审阅后的新映射均已验证；仅有别名并不充分 |
| 规范聊天被归档、删除、重命名或在 handoff 中被替换 | 停止向规范目标投递，保留领域工作；替换根会话须获得显式恢复确认；递增 epoch |
| Gateway 重启或连接断开 | 标记为 offline；保留回执；重新连接已验证的权威方，并在重新提交前对账 |
| Profile 被删除/重建、登记丢失、安装错误、克隆重复 | 进入 `recovery_required`；禁止按名称继承、自动创建或跨 profile 回退 |
| 插件被禁用/卸载，或 worker 跳过 hook | 禁止新的插件受控准入；缺少独立强制执行机制的写入路径继续禁用；不得声称其他宿主工具也已停止 |
| 较旧/不兼容的宿主失去必要能力 | 标记为 incompatible 并禁用受影响功能；绝不降级为直接编辑原始数据库或运行第二套 agent loop |

目标解析器必须在每次准入/投递前运行，而不只在登记时运行。出现不匹配时，以原子方式阻断新的插件自有准入。执行器在每次受控 effect 处检查当前绑定 epoch 和策略，包括启动配置已冻结的普通 worker。撤销/准入的顺序遵循 [06](06-plugins-mcp-and-security-zh.md)；已接纳的远端工作可能仍在进行，必须如实报告。

### 5.1 在同一 authority 内重新绑定

修复同一 profile 的规范聊天是一项经过审阅的恢复操作，而不是普通会话切换。暂停准入；检查待批准项、排队投递和 worker；验证替换后的规范根和来源证据；确认确切预览；以原子方式递增 epoch、使过时展示凭据失效并更新映射。旧结果仍可作为历史证据查询。待处理工作必须重新评估，绝不默默转发到新聊天。只有完成对账后才能恢复。

更换 profile 或宿主会改变存储/authority 边界。不得通过编辑活跃记录的 `backend_profile` 来实现。

### 5.2 更换 Bot 或迁移宿主

V1 **不支持自动跨 profile/跨宿主接管**。应使用 E8.3 下经过单独测试、由 owner 指定的导出/导入迁移流程：

1. 冻结源绑定并持久化其新栅栏。停止新的领域准入和定时投递映射；对 worker 和排队 effect 进行对账/取消。若不确定的 effect 无法安全核清，拒绝迁移。
2. 只导出明确选择的插件领域数据、不可变 ID 和回执，并附带版本化清单/校验和。不复制宿主凭据、owner grant、批准 nonce、会话记录数据库、插件登记或原生运行时归属。授权更换主 Bot 不等于全面授权复制所有私有数据。
3. 在目标端已验证的 owner 身份下，准备新的登记/authority。使用幂等迁移 ID 导入；保留历史对象/effect 身份和源 authority，未解析的原生引用在映射前保持禁用。导入的批准/grant 不能用于执行。
4. 验证源端退役/栅栏和目标端对账，然后取得明确的目标端激活确认。只有目标端变为 active；保留源端墓碑记录。若某一步失败，保持 suspended，并提供经过验证的回滚/恢复方案，绝不自动同时激活两端。

这是先停止、再启动的协议，不是原子分布式事务。如果源端无法访问或无法证明已退役，必须阻止接管，等待操作者恢复。恢复备份要求显式恢复流程，在启用写入前先隔离旧策略；恢复到旧 epoch 的数据库无法检测自身发生了回滚。没有外部 authority 时，不支持分叉后的并发恢复。这里不意味着提供广泛的宿主/worker 隔离。

## 6. 角色、委派与上下文

| 由服务端派生的角色 | 允许承担的职责 | 不代表 |
|---|---|---|
| `primary` | 已验证的规范 Bot Chat 协调领域工作并报告结果 | 可以批准自己的操作或绕过操作关卡 |
| `owner_entry` | 经过 owner 验证的普通/Desktop/移动端会话可以在 grant 范围内检查或提交，并关联领域任务 | 成为规范会话、继承全部会话记录或更改主绑定 |
| `worker` | 带有已记录任务交接、最少数据和明确结果合同的原生子会话/run | 拥有全部 owner 记忆、管理绑定或超出 grant 继续委派 |
| `specialist_bot` | 明确授权的独立 profile/连接接收有范围限制的协作请求 | 拥有 owner 身份、通用访问权限，或自动加入 E9 路由 |
| `observer` / `untrusted` | 只允许获准的公开/来源限定观察或证据摄取 | 可以变更个人领域、给予 owner 批准或访问私有上下文 |

角色来自已验证的运行时/会话/worker 来源信息与绑定记录，绝不能只来自 prompt、工具参数、聊天标题或 JSON 中的 `role:"primary"`。规范聊天中的消息仍可能由 bot 撰写、由计划任务生成或来自第三方。**会话角色与消息作者相互独立。** 每项操作都必须保留真实作者、来源、grant 和当前策略。

拟议的 handoff 携带 `binding_id`、`binding_epoch`、`task_id`、`attempt_id`、权威父级/原生引用、scope、预算/截止时间、预期结果和 grant 引用。Worker 结果是证据，不是用户指令，也不是任务验收。由主 Bot/领域验收服务进行验证。旧 epoch 的延迟结果可以保留用于对账，但不能重新打开授权，也不能自动送达新目标。

短期工作使用原生委派/生命周期，持久化工作使用 Kanban。持久化 specialist Bot 可在受支持且已授权时使用原生 `message_agent`。其响应按所用路由报告移交或准入，回合完成需等待后续结果。应用原生循环防护，以及插件预算和发送方/目标策略。E9 选择获准的 worker 模型/推理强度路由。Primary Bot 的选择和模型配置单独处理，worker 路由范围外的 Bot、cron 与 Kanban 路径也是如此。

加载插件可能影响 profile 中的所有会话。初始集成在受支持的创建/重建边界选择最少工具，并在领域 handler 中重新检查角色。失败时放行的 hook，或跳过插件 hook 的 worker，不能成为唯一的角色/授权边界。来源不明时，必须阻止受保护操作。E0.7 必须将任何缺失的规范化会话/作者/worker 上下文明确列为经过测试的适配器或上游缺口。

### 当前固定版本的同一安装内 Bot 消息

在 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`，注入工具前会检查 Bot Mode 协议设置、精确的 `Bot Chat` 标题和受管理安装标记。工具处理器会重新检查标题和标记。如果调用方有会话数据库，其 home 决定发送方 profile。Profile slug 决定结构化作者 ID `bot:<profile>`，名册提供消息前缀使用的 handle 和显示元数据。这些值来自宿主的调用上下文和名册。[工具资格检查](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L127-L168) · [发送方归属与本地路由](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L239-L364) · [调用 agent 上下文](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L1008-L1025)

接收方 authority 将 `bot_relay.deliver` 提供的作者规范化为归属信息，并独立从已认证的 RPC 调用主体派生邮箱的 `principal_id`。对于规范 LOCAL 接收方，目标 FIFO 使用 `automation:<session_key>` 作为生产者，在 `local_automation_v1.turn_author` 中保留作者。同一安装内的仅通知路径可在持久化准入后返回 authority 的排队状态，并清理临时载荷和投递意图，无需启动回复等待进程。[RPC 作者解析](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L805-L828) · [邮箱准入](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L955-L1000) · [自动化快照](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_automation.py#L549-L565) · [FIFO 准入](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_automation.py#L605-L636) · [仅通知结果](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_mode_dm.py#L762-L799)

夹具使用由真实会话数据库支撑的合成命名发送方，以及同一临时安装下独立的默认 profile Bot Chat。它经过工具注入、原生顺序路由选择器和内联执行器，再经过 `GatewayClient`、私有控制接口的票据签发、`/api/ws` 票据核销和接收方 authority。夹具提供端点发现结果和合成本地对端主体，并在内存中桥接控制请求和 WebSocket 流量。[仅通知契约测试](../tests/contracts/test_native_bot_notify_only.py) · [顺序路由选择器](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/tool_executor.py#L1674-L1685) · [原生内联执行器](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/inline_tool_executors.py#L296-L303)

| 夹具场景 | 观测结果 |
| --- | --- |
| 发送方 profile 中的普通会话 | 工具注入被拒绝。通过内联执行器直接调用会在端点发现、票据签发或准入前返回错误。 |
| 命名 Bot Chat 向 `@hermes` 发送 | 默认 profile 的规范 Bot Chat 收到一条排队中的准入记录。消息以 `Message from 🤖 Scout Fixture (@scout): [no reply needed]` 开头，结构化作者为 `bot:scout`，名称为 `scout`，`is_bot: true`。本地票据主体和 FIFO 生产者分别记录。 |
| 持久化回执与事件还原 | 工具返回 `queued` 和 `expects_reply: false`。投递 ID 与已固定的意图、邮箱回执及 FIFO 请求 `bot:<delivery_id>` 一致。原生还原函数从该排队条目返回相同的作者和内部事件标记。发送方临时载荷和意图已清理。参与比较的发送方数据库记录保持不变，接收方的会话消息记录仍为空，authority 记录一次调度请求。 |

夹具让接收方回合保持排队状态，并拦截回复等待进程。证据覆盖同一安装内的 Bot 作者归属和本地 operator 准入。已验证的人类 owner、受支持的插件调用方和 worker 来源证明、模型执行、回复送达、安装环境中的传输及跨机器消息均需单独验证。

## 7. 跨设备与平台连续性

默认模式：**共享领域，分离会话记录**。Desktop Bot Chat、Telegram 私信、Discord 线程和 CLI 临时会话可以引用相同的已授权任务/项目，而不复制各自的对话，也不假装共用一个 prompt。上下文从有界、按权限过滤的领域事实和明确任务链接重建。一个路由中的用户文本不会被默默作为新命令在另一个路由重放。

如果用户明确希望使用同一个原生会话，使用受支持的规范会话 attach/handoff 路径，并单独测试归属、排序和恢复。`gateway.profile_routes` 不提供目标规范会话 ID。不得通过合并会话记录、直接写入 SessionDB 或 API-server 影子会话来近似实现连续性。

对于消息入口，优先使用由所选 Bot 的 profile 持有的一份独有平台凭据。共享 bot 可以把指定聊天路由到另一个运行时 profile，但授权/回复仍依赖接收侧传输。在渠道绑定中同时保存已验证的传输引用和运行时引用。`SessionSource.is_bot` 描述的是**发送方**，不是接收消息的 Bot。如果两个 bot 被有意路由到相同运行时 profile，且会话键的其他组成部分完全相同，不得声称具备 bot 级隔离 [B7]。

群组/共享渠道默认绝不接收私有规范会话摘要。投递必须为该具体内容选择经过验证、已获授权的路由。在原始会话中向 owner 返回状态，与启动新的规范 Bot 回合是两件不同的事；不能仅为保持屏幕同步就把任一操作执行两次。

## 8. 消息、例行任务与回执

每次投递只设一个负责方。领域通知在准入前保存其预期绑定/epoch、目标、内容修订号、策略 scope 和稳定的 effect ID。派发时解析当前规范/传输目标，并重新检查权限。目标变化时，应暂停/审阅旧 effect，而不是默默改投新目标。原生 cron 投递与插件 outbox 不能同时发送同一结果。

原生 `bot-chat[:profile]` 投递仅限本机，并进入既有 Bot authority。owner 不可用时，调度器可将尚未准入的投递持久化并延后，在后续 tick 使用相同投递 ID 重试。如果准入响应丢失，即使 authority 已提交准入，调度器的待投递记录仍可保持 `queued`。保留原生投递和准入引用，区分移交、准入及排队、运行中、等待、完成、失败和未知等执行结果。已认领工作若结果不确定，须沿用现有标识对账 [B9]。跨机器 Bot 投递需要单独验证且已获授权的传输。禁止以针对同一会话记录的 CLI 写入者作为后备方案。[当前固定版本的回执证据](#当前固定版本的-bot-chat-延后投递)

`ctx.inject_message(..., session_key=...)` 返回布尔值，接口既不接受调用方指定的投递 ID，也不提供持久化回执查询。当前固定版本的上游网关调度器测试中，调度器返回 `True`，随后异步派发抛出错误。结果不确定的提交须通过提供稳定回执的适配器才能安全对账。缺少受支持的适配器时，持久化主动投递仍无法启用。[插件 API](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_context.py#L395-L402) · [上游调度器测试](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tests/gateway/test_plugin_message_injection.py#L341-L368)

计划任务和 specialist 的输出必须保留来源归属。例行任务不能把自己的内容标记为 owner 的直接请求来获取权限。对 owner 的提醒和第三方服务上的操作仍是不同的 effect，各自需要独立的 grant。Bot 绑定不自动授权主动联系、跨 Bot 共享、新增费用或外部写入。

### 当前固定版本的 Bot Chat 延后投递

在 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`，如果投递抛出错误，cron 排空流程会将待投递文件保持为 `queued`。收到成功响应后，它将记录标为 `transferred`，并把响应状态写入 `receipt_status`。authority 在返回该投递 ID 的既有回执前，会核对消息、提交主体、作者和通知类别。`transferred` 记录调度器的移交结果。回执记录 authority 的处置结果，回合执行和完成另有各自结果。[原生 cron 排空流程](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/cron/bot_chat_legacy.py#L64-L123) · [原生回执处理](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/session_bot.py#L795-L876)

契约测试夹具把合成 cron 结果投递给同一个本地 profile。它经过原生 cron 投递辅助函数和排空流程、`GatewayClient`、私有 `session-ticket` 处理器和 `/api/ws` 的票据核销，以及原生 authority 上的 `bot_relay.deliver`。夹具提供端点发现结果和本地对端主体，在内存中桥接控制请求和 WebSocket 流量，并通过带超时的测试驱动运行两个事件循环。[延后投递回执契约测试](../tests/contracts/test_native_bot_deferred_receipt.py) · [原生 authority 客户端](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/bot_live_delivery.py#L71-L119) · [私有控制处理器](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/gateway/control_socket.py#L333-L410)

| 夹具步骤 | 观测到的状态 |
| --- | --- |
| 端点报告已停止 | Cron 按执行与目标派生的投递 ID 持久化一条 `queued` 记录。authority 邮箱和规范会话准入队列均为空。 |
| 端点报告已就绪，随后首次成功响应被丢弃 | Gateway 发出 `queued` 回执，随后桥接层丢弃响应。邮箱与规范会话 FIFO 条目 `bot:<delivery_id>` 对应同一个准入 ID。客户端观测到断开，cron 记录逐字节保持不变，状态仍为 `queued`。 |
| 后续排空流程重放投递 | 客户端使用新的 `interactive` 票据发送相同的投递 ID、profile、规范会话和消息。authority 返回既有回执，cron 记录变为 `transferred`，并带有 `receipt_status: queued`。 |
| 再次运行排空流程 | 已移交的记录不再触发移交。夹具仍只有一个规范会话、一份回执、一条排队中的 FIFO 准入记录和一次调度请求。准入条目没有终态结果，规范会话的消息记录仍为空。 |

夹具让已准入的回合保持排队状态，覆盖合成本地 operator 准入及回执处理。安装环境中的 Gateway 与操作系统对端验证、模型执行及回合完成、外部投递、重启及更广泛的投递对账仍需单独验收。公开插件 API 提供上文所述的布尔值注入路径。

## 9. 事件、错误与客户端恢复

拟议的持久化失效通知包括 `primary_binding.changed`、`primary_binding.suspended`、`primary_binding.recovery_required`、`primary_binding.retired` 和 `primary_delivery.updated`。使用与 [14](14-client-api-contracts-zh.md) 相同的已提交领域序列/outbox；不创建平行事件总线作为权威来源。快照包含已授权的绑定摘要。可选实时提示仅请求重新获取数据。

Payload 携带 ID、修订号、epoch 和原因码，不包含会话记录、nonce、凭据值或文件系统路径。客户端收到 epoch 变更时，必须丢弃过时的绑定专属批准展示凭据，并重新读取当前 grant；事件不能提供 grant。离线选择只保留为草稿，绝不能成为排队等待执行的绑定确认。

| 代码 | 含义与恢复方式 |
|---|---|
| `primary_unbound` | 没有已确认的主 Bot；使用已授权的设置流程，不回退到默认 Bot |
| `primary_target_unavailable` | 已知目标离线；将上次验证状态标记为过时并对账 |
| `primary_identity_ambiguous` | 宿主/profile/登记证据相互冲突；需要 owner 恢复 |
| `primary_canonical_unverified` | 无法证明规范会话注册表/谱系；不允许后备创建 |
| `primary_epoch_conflict` | 命令/handoff 已过时；重新加载并评估，不复用旧批准 |
| `primary_role_forbidden` | 当前已验证角色/作者无权执行此操作 |
| `primary_capability_unavailable` | 缺少必要宿主适配器；功能保持禁用 |
| `primary_recovery_required` | 退役/重命名/恢复中断了连续性；执行经过审阅的恢复流程 |
| `primary_migration_blocked` | 源端栅栏、未知 effect 或目标身份尚未确定 |

根据情况，将缺少身份认证映射为 401、权限被拒绝映射为 403、隐藏的他人对象映射为 404、修订号/epoch 冲突映射为 409/412、缺少 If-Match 映射为 428、可信适配器/存储不可用映射为 503。本地 CLI 界面使用相同的稳定领域错误码，但不伪装成 HTTP。绝不能把暂时性网络故障理解为取消成功或 Bot 不存在。

## 10. 兼容性与发布测试

记录原生/插件 SHA、宿主模式、路由/连接类型、凭据类别、profile 设置、会话根/末端、worker 模式和每一项跳过的能力。现有单元/宿主基础测试**不能**认证这些新合同。静态文档/JSON 检查只能证明语法/结构。

| 必需的合成测试或已授权集成场景 | 断言 |
|---|---|
| 不同连接上有两个同名 Bot；路由别名改变 | 以明确目标身份为准；不回退到当前聊天/默认项/最近使用项 |
| 发现过程暴露元数据，但不提供会话访问权限 | 不越权读取或登记 |
| 初次确认双击、ACK 丢失、提交过程中崩溃 | 只有一个绑定/提案决定；查询回执可以恢复；不发生第二次登记 |
| 普通会话、伪造标题/JSON、bot 撰写的规范会话输入、本地 CLI 操作者 | 角色与 owner 证据保持独立；不允许自我批准 |
| 两个 profile 上并发进行 owner/bot/worker 工作 | 使用正确的 profile 策略/存储；上下文和权限不泄漏 |
| 压缩、重启、名册读取失败/返回空结果 | 遵循已证明的谱系；尚未查明的缺失不能生成另一个聊天 |
| Profile 重命名仅完成部分迁移；删除后按同名重建 | 在恢复验证完成前默认拒绝；不按别名继承 |
| 规范聊天归档/重命名/handoff 替换 | 停止旧投递；owner 确认新根；新 epoch 阻断过时工作 |
| 撤销与派发竞争；绑定变化后旧 worker 恢复运行 | 按已提交栅栏排序；拒绝旧 grant；如实报告已接纳的 effect |
| Bot 间消息、例行任务结果、转发的批准 | 作者身份得以保留；不冒充 owner，也不产生失控回复循环 |
| 移动端/Desktop 使用同一 profile；两个传输 bot 路由到该 profile | 只提供明确的任务连续性；不假定会话记录合并或 bot 账号隔离 |
| 投递 ACK 丢失；原生延迟；目标离线；cron 结果重复 | 稳定回执对账和单一投递负责方；没有竞争的会话写入者 |
| 快照恢复、克隆登记/安装 ID、旧备份恢复运行 | 按受支持的恢复流程要求恢复操作；不把不受支持的并发克隆称为安全 |
| 源端设栅栏与目标端导入前后迁移崩溃 | 在受支持协议中最多只有一个激活的 authority；无自动故障转移/双端恢复运行 |
| Safe worker、托管 HTTP 布尔值、缺少规范会话/profile API | 受保护能力禁用；不导入私有模块、不仅靠 prompt 防护，也不回退到默认 owner |

较旧宿主可能缺少路由描述符、规范会话字段或规范化来源信息。必须检测能力并测试受支持模式；不能默默回退到 `last_session`、未公开参数或只按 profile 的远端路由。Gateway 拓扑和离线 cron 行为的源码示例可能与旧版文字说明不一致：应使用固定版本实现和合同，并在升级时重新验证。仅安装较新的 Hermes 版本，不能证明该绑定仍然有效。

## 11. 实施工作包

| ID | 状态与依赖 | 交付物 |
|---|---|---|
| E0.7 Verify Primary Bot Contracts | M0，In Progress。依赖 E0.1/E0.2，并使用 E0.4 发现。 | 当前固定版本的[名册](#当前固定版本的原生-bot-chat-名册)、[Desktop 路由](#当前固定版本的-desktop-profile-路由)、[原生 profile 生命周期](#当前固定版本的原生-profile-生命周期)、[同一安装内 Bot 消息](#当前固定版本的同一安装内-bot-消息)和 [Bot Chat 延后投递](#当前固定版本的-bot-chat-延后投递)证据。真实传输与 profile 转换、受支持的作者、调用方与 worker 来源证明、其余回执模式和适配器清单仍待完成。可选 HTTP 还需要 E0.6。 |
| E1.6 Bind Primary Bot | 可选后续；Backlog；E0.7、E1.1–E1.5、E2.1 | Owner 确认的登记与恢复、唯一 active 绑定、修订号/epoch 栅栏、审计和角色策略；不无条件启用写入 |
| E3.6 Reconcile Primary Bot Sessions | 启用 Bot 绑定路径时为 M1 门禁，M2 继续扩展；Backlog；E1.6、E3.2/E3.5、E4.3/E4.4 | 规范会话解析、worker handoff 关联、投递/恢复和原生回执对账 |

扩展 E6.1/E6.2，加入所选 Bot 的已验证渠道绑定和分离会话记录的连续性。扩展 E8.2/E8.3，加入这份故障矩阵和经过审阅的迁移/恢复；E8.5 记录选择、暂停、恢复和限制。这些只是计划增补，不代表创建远端 Project 条目或将状态标为 Done。

**启用 Primary Bot 能力时**，E0.7/E1.6/E3.6 是发布关卡。它们不阻塞 profile-first 本地 MVP 或其明确限定为本地、无派发的任务命令。绑定 Bot 的 M1 必须让其启用路径通过这些关卡；自定义 HTTP/PWA/原生手机端的 E0.6/E6.5–E6.7 仍是独立的可选路线。从一个现有 Bot、一份权威 profile 和一个已验证 owner 开始；自动多宿主迁移和广泛的多 Bot 编排延后处理。

## 12. 固定版本证据

- B1：[Profile、agent 和 Bot](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/profiles.md#L19-L43) 与 [Bot Mode 生命周期](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/bot-mode.md#L8-L45)。
- B2：[插件上下文/状态/profile 与管理器作用域](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py)。
- B3：[桌面端 profile 路由描述符与连接身份](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md#L1446-L1514)。
- B4：[已授权的规范会话名册与压缩解析](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_group_controls.py#L330-L490)。
- B5：[安装 ID](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/install_identity.py)、[profile 元数据](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/profiles.py#L646-L678) 以及[重命名/删除时的身份迁移](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/profile_identity.py)。
- B6：[插件注入作用域、同意与布尔返回值](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_injection.py)。
- B7：[接收侧 bot 路由判别字段](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/profile_routing.py#L62-L108)、[会话键](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session.py#L691-L734) 以及[传输/运行时身份](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_identity.py#L43-L83)。
- B8：[message_agent 资格检查](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/bot_mode_dm.py#L127-L168) 与[受管理安装标记](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/bot_mode_probe.py#L131-L143)。
- B9：[Cron Bot Chat 投递实现](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/scheduler_delivery.py#L714-L805)、[延迟后的同 ID 准入](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/bot_chat_legacy.py#L24-L100) 以及[单一 authority 的 Bot 准入](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_bot.py)。
- B10：[经过授权的原生标题查询](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_controls.py#L567-L596)、[规范会话 UI 解析](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L88-L107) 以及[不确定缺失的处理](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/plugins/hermes-bots/canonical-chat.ts#L330-L339)。
