# 76. 原生记忆提供方契约

[English](76-native-memory-contracts.md) | 简体中文

## 范围与基线

此仅测试的 E0.9 切片对应 [Issue #42](https://github.com/MosBot-AI/hermes-superagent/issues/42)，核验原生记忆复用点并记录不支持的边界。它不实现自动摄取、项目持久 checkpoint-v2、来源解析器、远程身份或新记忆后端。安装和提供方选择仍须显式执行；不改变用户配置档案、账号或生产设置。

准确目标为 [Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427)，记录在 [compatibility.json](../compatibility.json)，使用独立 Python 3.14 环境。测试使用干净的固定源码及临时合成配置档案。这是固定版本证据，不是宽泛支持范围、已安装部署或真实模型验收。[30](30-pluggable-memory-contracts-zh.md) 和 [43](43-native-checkpoint-boundary-zh.md) 的历史证据保留原始固定版本；本矩阵另行补充当前目标的核验。

矩阵说明断言及其限制。执行结果必须对应 Issue/PR 的准确版本，不能仅因存在测试就推断已通过。E0.9 核验与 E2.8 持久生命周期实现是独立门槛；记录不支持的契约不代表启用它。

后续内部来源解析切片 [91](91-native-source-resolution-zh.md) 加入精确的调用方绑定只读核对及 revision 围栏。它不改变本仅测试切片的历史范围，也不启用缺失的持久检查点契约。

## 验收矩阵

| 契约 | 证据 | 边界 |
| --- | --- | --- |
| 提供方发现、选择及依赖准入 | `test_native_memory_admission.py` | 原生目录/入口点枚举与加载、激活及失败路径。须区分仅元数据的名称枚举与可能导入提供方代码的可用性探测。不授权运行时安装依赖。 |
| 单外部槽位 | `test_native_memory_provider.py::test_native_manager_refuses_second_external_provider` | 实际管理器拒绝第二个外部提供方。与 builtin 共存不允许项目适配器冒充 builtin 或静默串联提供方。 |
| 内置 MEMORY.md / USER.md | `test_native_memory_stores.py` | 原生容量与重载契约，不替换宿主存储，也不是无限事实档案。 |
| 原生历史检索 | `test_native_session_search.py` | 真实存储内容、有界结果形态、来源处理、显式跨配置档案读取及 FTS/CJK 行为。搜索可见性不是调用方授权边界。 |
| 提供方生命周期与上下文接线 | `test_native_memory_wiring.py`；现有 `test_native_memory_provider.py` | 宿主回调/上下文行为与产品拒绝是独立断言。Cron 与子代理并非普遍不使用记忆或只读。 |
| 配置档案、会话及即时撤权 | `test_native_memory_provider.py` | 所选 personal-records 召回拒绝旧会话、其他 home、非主/远程上下文、已停用配置及托管作用域变化。这不是远程所有者认证或相同 UID 进程隔离。 |
| 异步写入结果 | `test_native_checkpoint_boundary.py::test_async_turn_sync_failure_is_not_a_checkpoint_receipt` | 已排空队列可包含失败的 sync 回调；队列完成和助手口头确认都不是持久写回执。 |
| 检查点 v1/v2 与严格失败 | `test_native_checkpoint_boundary.py`；`test_native_memory_provider.py::test_actual_manager_preserves_required_checkpoint_failure` | 尽力而为的 v1 不支持严格检查点。原生 v2 接受正常回调返回而不验证持久回执；提供方错误通过必需门禁传播。项目提供方保持 v1，严格模式失败关闭。 |
| 来源身份与压缩 | `test_native_checkpoint_boundary.py` | 已有稳定 UID、合并沿袭和版本，但待持久化/无身份组成部分及未绑定回调输入使完整持久来源覆盖不能被假定。原生 app-server 的严格检查点限制仍明确保留。 |

上表测试路径均相对于 `tests/contracts/`。复用现有[提供方契约](../tests/contracts/test_native_memory_provider.py)与[检查点契约](../tests/contracts/test_native_checkpoint_boundary.py)，不重复实现。导入原生内部消费者只是固定版本测试接口，不是新增受支持的生产插件 API。

## 具体行为与反例

### 发现与激活

`test_metadata_listing_never_imports_but_availability_discovery_does` 区分公共的仅名称枚举与可用性发现，后者会执行合成提供方的导入。`test_directory_precedence_then_entry_point` 覆盖内置、用户、项目与裸模块入口点的优先级。非活动提供方测试证明检查既不改变所选提供方，也不注册非活动技能；它不宣称显式加载任意提供方代码没有副作用。

缺失依赖/导入失败测试不允许子进程安装或配置修改。已停用用户目录提供方在导入前被拒绝。**裸模块入口点不同：** 此固定版本的 `in_process` 模式下，`plugins.disabled` 不会停用它。Host-isolation 模式则在导入前拒绝该裸模块入口点。这是已记录的原生限制，不授权绕过所选隔离模式，也不能据此假定存在通用停用门禁。项目自身的召回配置检查仍独立存在。

`test_directory_provider_host_mode_runs_in_separate_process` 另行加载真实的 hosted 目录提供方代理。提供方报告不同的进程 ID，其模块未进入父解释器；随后停止临时宿主。这证明进程分离，不证明文件系统/网络沙箱或完整安全审计。

### 内置存储与刷新

`test_builtin_caps_boundary_and_overflow_preserve_disk` 检查 MEMORY.md / USER.md 默认 2,200 / 1,375 字符容量及配置后的上限。中文内容证明限制按字符而非 UTF-8 字节计数。恰好达到容量的内容可持久化；超限 add 和 replace 失败且文件不变，重开后保留已接受内容。

`test_actual_prompt_invalidation_reloads_external_store` 使用真实存储、提示词组装及失效函数，搭配惰性代理状态而非真实模型构造器。第二个存储修改两个文件；原提示词在失效处理重载记忆并清除缓存之前保持旧内容。刷新后的提示词包含两项修改。第二条参数化路径执行真实 `compress_context` → `_rebuild_system_prompt_at_boundary` → 失效处理 → 提示词重建，保留原生候选准入与边界后记账。其摘要阶段是合成的；模型/外部准备、租约获取/接纳、工具刷新和遥测被替换，此接线用例不包含持久会话数据库。独立的真实 SessionDB 压缩测试不会使这两个用例成为提交/提示词联合原子性的证明。两条路径都不证明模型压缩质量、逐 token 重载或直到新会话的永久冻结。

### 历史搜索、来源身份与输出预算

- `test_real_fts_english_chinese_and_supported_short_cjk_fallback` 观察真实英文 FTS5、中文 trigram 及短 CJK 规范存储 LIKE 扫描路由，再验证原生工具返回已存储的消息 ID 与来源。这是固定合成查询集，不是通用语言质量基准，也未测试全部缺失索引恢复模式。
- `test_discovery_browse_source_filters_are_not_acl` 展示 CLI 与 cron 结果，cron 排在交互内容之后。Kanban、子代理与 tool 会话在发现/浏览中隐藏，但按 ID 仍可直接读取。`test_tool_role_uses_supported_canonical_fallback` 验证显式 tool 角色搜索；默认发现不返回该工具正文。
- `test_read_scroll_discovery_bounds_and_attribution` 验证读取头 20/尾 10 条及 2,000 字符正文截断；发现消息和首尾节选分别限制为 4,000/1,200 字符。截断后附加省略号。**滚动只将两侧窗口各限制为 20，最多 41 条消息；单条滚动正文无上限。** 测试保留每条超过 6,000 字符的反例。未另行设限时，绝不能把原生滚动视为安全的总内容预算。
- `test_browse_and_discovery_limit_clamps` 检查结果数量被限制在 1–10。来源/会话/消息/模型归属依据真实合成行核验，而非生成摘要。
- `test_compaction_archives_are_discoverable_not_active_context` 区分归档原文与活动摘要上下文；发现和锚定滚动仍能检索旧证据。`test_archived_session_is_not_deleted_or_an_access_boundary` 另行证明会话归档既不是删除，也不是拒绝读取。
- `test_explicit_other_profile_reads_are_readonly_and_bare_id_does_not_fan_out` 验证显式 `profile=` 和 `profile/id` 读取、只读数据库访问及其他配置档案数据库字节不变。裸 ID 不扫描其他配置档案。这些是原生路由语义，不是读取其他配置档案的授权。

- `test_rewind_is_hidden_from_discovery_and_live_scroll_is_rejected` 区分回退与擦除：默认发现/活动消息隐藏已回退行，显式 inactive 搜索仍保留它。活动上下文滚动被拒绝，但不带当前沿袭保护的显式历史滚动仍能读取保留行。

### 生命周期与构造器接线

`test_public_manager_serializes_sync_end_switch_and_reverse_shutdown` 检查 FIFO 生命周期交付、逆序关闭与错误隔离；`test_public_session_switch_forwards_branch_rewind_and_ignores_empty_id` 检查切换参数。结合现有异步失败测试，区分回调交付与持久写入成功。

`test_actual_turn_sync_boundary_skips_interrupted_provider_writes_and_prefetch` 在最小状态上调用真实 `AIAgent._sync_external_memory_for_turn` 消费者，使用真实管理器/执行器及合成记录提供方。中断轮次既不提交 sync，也不提交排队预取；完成对照先提交 sync 再预取，并保留所传会话、对话记录及作者字段。这是消费者边界证据，不是完整代理/模型运行，也不认证这些作者字段。

Cron 与委派测试执行真实原生构造路径，在合成代理边界捕获构造参数。Cron 保留记忆但禁用后台 review。普通委派跳过记忆；必需检查点委派以 `memory_agent_context="subagent"` 加载记忆。这些测试不构建真实模型客户端、不执行已调度 occurrence，也不证明非主上下文中的提供方写入安全。现有产品提供方测试另行拒绝受支持主/本地范围以外的召回。

## 来源与授权限制

原生 `session_search` 可显式读取其他本地配置档案。此功能不授权个人代理扩大自身检索范围。原生会话 ID、来源标签、UID 或返回内容既不能证明已验证的远程所有者，也不能授权后续效果。项目召回继续执行更窄的配置档案/会话/配置边界。

宿主搜索索引与项目本地记录 FTS 索引是不同系统。本地记忆搜索测试通过不代表原生对话检索行为或通用中文语义召回已成立。容量限制和截断视图不能被描述为完整证据覆盖。

[43](43-native-checkpoint-boundary-zh.md) 的检查点证据仍是关键：来源引用需要精确对账，以及与压缩提交栅栏关联的宿主自有覆盖/保留机制。仅 v2 能力标记、成功回调字符串、有效 UID 或排空队列都不提供这些保证。本包不将项目提供方升级到 v2，也不在其他位置静默归档原始对话。

## 核验与后续门槛

全部场景使用合成内容与临时存储；不需要真实提供方请求、凭据、监听器、远程写入或已安装日程。新增测试及现有提供方/检查点契约须通过仓库固定宿主检查流程执行。Lint、类型、单元与双语文档检查仍是独立检查；准确计数随实际执行结果记录，不复制历史运行数据。

本地聚焦运行在 SQLite `3.53.1` 与 `3.46.1` 上各通过 37 项新增用例：12 项准入、10 项接线、6 项内置及 9 项搜索。两个环境均使用 Python `3.14.9` 及规范原生运行器。这些是聚焦结果，不是汇总单元/契约计数或 CI 验收。

只有在测试/不支持矩阵及准确固定版本结果经过审核后，才能将 E0.9 作为有界原生契约核验验收。E2.8 自动捕获、持久回执及来源绑定检查点集成仍待完成，远程身份、不支持的隔离模式及部署/提供方验收也仍独立存在。本切片不代表 E0 epic、M0 里程碑或生产发布完成。
