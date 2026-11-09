# 13. 执行边界契约与写路径清单

[English](13-enforcement-contracts.md) | 简体中文

此页记录较早的 E0 切片，以及针对 [Issue #12](https://github.com/MosBot-AI/hermes-superagent/issues/12) 的有界 RPC/MCP、终端/浏览器、本地批量及持久 worker 策略后续核验。当前新增的显式本地任务收件箱见 [16](16-local-task-inbox-zh.md)；它不启用这里列出的原生/外部受控写路径。

本次后续 P0 切片推进 E0.4，但不启用任何受控写能力。新增可复验的失败边界测试和机器可读发布清单。后续切片使用合成副作用核验固定宿主的真实 RPC 消费者/服务端调度、MCP 准入、终端/浏览器执行前守卫，主 agent 和被委派 agent 循环中的本地批量，以及受保护合成读 handler 中的当前持久策略检查；并未完成所有替代路径。E0.4、E0/M0 与 E1 授权仍未完成。

## 1. 实现了什么

`personal_agent/enforcement.py` 返回独立、可 JSON 序列化的清单。每条已知写路径都为 `controlled_writes_enabled: false`、`release_gate: blocked`；未列出的路径也属于未验证、阻断的本项目受控写发布范围。状态工具只返回有界摘要。默认 in-process 插件模式下，`hermes personal-agent coverage` 输出完整清单。

这是**只读发布报告**，不是动作授权器、实时宿主检查或沙箱。它不关闭其他 Hermes 工具、不拦截直接 API 调用，也不会把操作员现有工具配置变成受控环境。基线 commit 是已测源码的证据，不代表当前宿主必然运行该 commit。固定宿主在 host-isolation 模式跳过插件 CLI 注册。

## 2. 固定基线的实际行为

最初的执行边界测试通过真实 discovery 加载真实目录插件，其唯一 handler 只在内存中记录调用。没有替换 manager、context、manifest parser、registry 或 config loader。测试夹具控制 callback 行为；外层 dispatcher 测试显式注入一次逃逸的 dispatcher 异常。

| 边界 | 观察结果 | 含义 |
|---|---|---|
| `pre_tool_call` 显式 block | 不进入合成 handler | 常规拒绝在此已测调度路径有效 |
| 注册 callback 抛出 `RuntimeError` 或 `SystemExit` | inline 与 bounded 模式均产生 block directive | callback 异常 fail-closed，不等于 dispatcher 异常 |
| callback 超时及受抑制的重试 | 两次均阻断，不调用 handler | 超时 callback 仍可能存活，hook 不得执行副作用 |
| 相同调用标识的 callback 仍在运行 | 第二次投递在超时前阻断；释放后首次调用执行一次 | 正在执行的调用抑制与超时退避不同 |
| 执行 middleware 在 `next_call` 前抛异常 | 下游 handler 仍执行一次 | 此失败是 fail-open，不是授权拒绝 |
| middleware 在 `next_call` 后抛异常或调用两次 | 已测链路不重放已完成 handler | 不能据此推断远端传输幂等 |
| 异常逃逸出外层 hook dispatcher | `model_tools` 继续调用 handler | 被捕获的 callback 异常与 dispatcher 失败属于不同边界 |
| 直接 registry dispatch | 不调用 `pre_tool_call` hook 或执行 middleware | 底层调用不继承面向模型的调度链 |
| Troubleshooting safe worker | 跳过插件 discovery 与 hooks | 缺失的插件不能保护写操作或提供自己的降级诊断 |
| 普通 managed worker / config-only worker | 插件与 hooks 仍启用，config 保持冻结 | 后续 profile 修改不是即时撤权 |

Worker 探针在全新进程中运行，因为 bootstrap policy 必须在 runtime import 前一次绑定。测试验证修改返回的 config 或替换磁盘 config 不会改变冻结快照。子进程使用明确变量 allowlist、临时 home，并在进程内阻断 socket 连接。超时测试 hook 在 teardown 中通过 Event 释放并 join；宿主本身不保证杀死被放弃的 callback。

测试位于 [原生执行边界契约](../tests/contracts/test_enforcement_boundaries.py)。该夹具仅用于测试，不会作为插件运行时工具面安装。

### 2.1 嵌套 RPC 准入与响应丢失反例

[RPC 契约](../tests/contracts/test_nested_rpc_enforcement.py)调用真实 `_rpc_server_loop`，不传入其可选的 dispatch 替换参数。JSON 分帧、令牌比较、工具 allowlist、调用预算、`_default_dispatch`、`model_tools`、插件 hooks/middleware 和错误日志均保留原生实现。仅 socket 协议端点使用内存替身：不创建监听器、socket 连接、沙箱、shell 或模型调用。真实加载的夹具 handler 在内存中记录副作用。

- 空值/不匹配/非 ASCII 令牌、空服务端令牌、损坏 JSON、不可用工具和耗尽预算均在执行 handler 前拒绝。仅已派发尝试消耗预算；被 hook 拒绝的尝试仍计一次，并由 `tool_errors_since` 记录。
- 正常插件否决和 callback 失败会阻断嵌套调用。显式注入的外层 hook dispatcher 逃逸异常仍会进入 handler。经 RPC 嵌套不会修复已有失败边界。
- 两个完全相同且通过令牌验证的数据包会执行两次。令牌、工具 allowlist 和调用预算都不是 ActionIntent 或幂等键。
- 测试执行宿主生成的 `_UDS_TRANSPORT_HEADER` 客户端，仅替换连接建立。传输替身在真实服务端/default dispatch 完成**之后**丢弃第一次响应。一次性客户端抛出异常，独立观察到一次副作用；持久客户端重连、重复相同数据包，并在第二次副作用后返回。这是在内存传输上验证生成客户端重试的反例，不是真实 UDS/TCP 或完整 session-kernel 测试。Session kernel 自定义的当前 cell 权限重新绑定及远端文件系统轮询传输在此仍未验证。

### 2.2 MCP 准入与声明式只读行为

[MCP 执行边界契约](../tests/contracts/test_mcp_enforcement.py)复用 [74 的 SDK stdio 外观层](74-synthetic-connector-fixtures-zh.md)。测试使用真实 MCP discovery、registry 注册、原生 wrappers 和 stdio 会话。独立只读 SQLite 观察器统计尝试/副作用；返回文案不是判据。唯一的批准替身是返回拒绝、取消或异常的合成 UI 端点，不替换原生 trust gate。

- 真实注册的插件否决或 callback 异常，会在任何远端 execute 尝试之前阻断面向模型的 MCP 调度。在合成 `trust: full` 配置下，对相同参数直接 registry dispatch 会跳过该插件 callback，并产生一次夹具副作用。这**不表示**直接 registry 会跳过所有 MCP 门禁。
- 配置为 `trust: untrusted` 的写工具，在面向模型和直接 registry 两条路径都保留原生 trust gate。拒绝、取消及批准端点失败均在获取调用服务端之前拒绝，远端 execute 尝试/副作用为零。
- 不可信服务端上刻意虚报 `readOnlyHint: true` 的工具，在没有 trust 提示时产生副作用。该 annotation 是声明，不是副作用级授权或隔离。[74](74-synthetic-connector-fixtures-zh.md)另行记录注入会话过期错误之后由声明驱动的重放。

| 清单契约 ID | 可执行断言 |
| --- | --- |
| `rpc_token_allowlist_budget` | `test_rpc_invalid_tokens_never_reach_default_dispatch`、`test_rpc_empty_server_token_fails_closed`、`test_rpc_framing_allowlist_and_budget_refuse_before_dispatch` |
| `rpc_nested_hook_failure` | `test_rpc_default_dispatch_honors_plugin_denial_and_callback_failure` |
| `rpc_outer_dispatcher_failure` | `test_rpc_outer_dispatcher_failure_still_reaches_nested_handler` |
| `rpc_duplicate_request` | `test_rpc_identical_authenticated_requests_are_not_deduplicated` |
| `rpc_persistent_client_response_loss` | `test_generated_rpc_client_response_loss_can_replay_an_effect` |
| `mcp_plugin_veto_and_registry_bypass` | `test_registered_plugin_blocks_mcp_but_direct_registry_bypasses_plugin` |
| `mcp_native_trust_gate` | `test_native_untrusted_gate_stops_before_transport` |
| `mcp_dishonest_read_hint` | `test_untrusted_read_only_hint_is_not_effect_level_authorization` |

### 2.3 惰性执行端点前的终端与浏览器准入

[终端/浏览器契约](../tests/contracts/test_shell_browser_enforcement.py)保留原生模型/registry 调度、已加载插件、终端命令/workdir 守卫及浏览器 URL 预扫描。终端执行计划/获取、命令执行以及浏览器生命周期/进程端点使用不执行真实动作的测试替身。记录到端点调用**不表示**执行了 shell 命令、真实浏览器动作或证明 backend 隔离。夹具禁止创建进程、DNS 与 socket 连接。每个拒绝测试均包含能够到达同一端点的允许对照。

- Profile 本地的原生终端 deny 规则通过模型和直接 registry 调度均会拒绝。提交 `force: true` 无效：公开 registry handler 不转发内部 helper 的 `force` 参数，公开 schema 也不暴露它。
- 直接调用内部 `terminal_tool(..., force=True)`，即使存在该 deny 规则及插件否决，仍会进入合成 backend。同样的调用仍会在 backend 前拒绝不合法 workdir。这记录的是不同的 Python helper 权限面，并非模型可用的 force 字段。
- 正常插件否决会阻断终端与 `browser_exec` 模型调用。直接 registry 调用跳过该插件否决；直接 `browser_exec` helper 调用也如此。工具原生守卫是另一层，已测部分仍然适用。
- 云元数据 URL 字面量经模型和 registry 路径均会被真实 `browser_exec` 预扫描拒绝，包括设置 `browser.allow_private_urls: true` 时。动态拼接 URL 会通过此**字面量预扫描**并到达惰性端点。其代码从未被求值：真实 harness/CDP 的 URL 准入及导航仍未验证。没有把已移除的 `browser_tool` 兼容 stub 当成当前浏览器工具。

| 清单契约 ID | 可执行断言 |
| --- | --- |
| `shell_native_deny_and_force_surface` | `test_terminal_native_deny_survives_registry_and_model_force_argument` |
| `shell_internal_force_boundary` | `test_terminal_internal_force_skips_approval_but_not_workdir_guard` |
| `shell_plugin_registry_boundary` | `test_terminal_plugin_veto_does_not_cover_direct_registry` |
| `browser_metadata_literal_floor` | `test_browser_metadata_literal_is_blocked_before_backend` |
| `browser_plugin_helper_boundary` | `test_browser_plugin_veto_and_direct_helper_boundary` |
| `browser_dynamic_url_prescan_limit` | `test_browser_dynamic_url_is_not_evaluated_by_literal_prescan` |

### 2.4 本地桥接批量与构造出的被委派子 agent

[批量/worker 契约](../tests/contracts/test_batch_worker_enforcement.py)中的本地批量用例构造真实 `AIAgent`，执行其真实 `run_conversation` 循环。已加载的测试插件独立记录内存副作用，不以结果文案为判据。仅模型客户端/元数据端点使用替身；隔离夹具关闭 prompt caching、compression 和 trajectory 保存。本地 `tool_call` 展开、分段规划、逐项准入、插件 hooks、registry dispatch 及消息/结果配对均保留原生实现。

每个本地批量用例同时在主 agent 和真实 `_build_child_agent` 构造的子 agent 上运行。子 agent 请求父 agent 配置工具集之外的 `terminal`，但不会获得它。这证明已测构造器选择及子循环，不证明 `delegate_task` 调度、后台生命周期或任意被委派代码隔离。

- 三项本地批量执行获准的首项/末项，在 handler 之前拒绝中间项，并返回三个唯一配对的工具结果。部分拒绝不使整个批量原子化，也不撤销之前的副作用。
- 夹具 handler 记录副作用后抛异常，模拟副作用发生后结果丢失。新的**脚本化模型响应**再次发出同一项，造成第二次副作用；两次被拒项仍然被拒。这不是传输自动重试，也不宣称真实模型行为。逐项结果 ID 和批量展开不提供副作用级幂等。
- 内存夹具策略变更后，新的脚本化模型轮次重新进入当前 callback，并拒绝先前获准项。这仅证明 callback 重新检查，不证明当前持久策略读取、事务化撤权或 worker 取消。

| 清单契约 ID | 可执行断言 |
| --- | --- |
| `local_batch_item_veto` | `test_native_local_batch_veto_preserves_other_items_and_pairing` |
| `local_batch_uncertain_retry` | `test_native_local_batch_uncertain_item_retry_is_not_deduplicated` |
| `local_batch_policy_recheck` | `test_native_local_batch_retry_rechecks_changed_fixture_policy` |
| `delegated_child_toolset_and_batch_admission` | `delegated-child` 夹具下的同三个用例，包括构造器工具集断言 |

`local_tool_batch` 清单行与 `connector_batch` 分开：纯 connector 批量保留自己的原生 dispatcher，不能由本地桥接展开验证。这些本地用例不覆盖 RPC/code 批量或生产 connector 授权。

### 2.5 纯 connector 批量的部分结果与显式重试

同一文件的 `test_connector_only_batch_veto_partial_result_and_explicit_retry` 调用真实 `model_tools` `tool_call` 调度，进入原生纯 connector 批量调度及逐项模型调度。原生可用性检查、已加载插件准入/middleware、远端调用规划、文件暂存及结果拼接均保留。仅 gateway 客户端构造被替换为离线 schemas/execute 端点。隔离 profile 无凭据；核验默认访客发现可用性，但不签发访客凭据、不连接 gateway，也不测试身份认证。

获准项记录副作用，被拒项在获取客户端前被阻断，未知项记录副作用后，其合成客户端省略结果槽。原生输出保留带索引的成功/拒绝/`PROVIDER_ERROR` 结果。显式重复外层调用会再次记录成功项和未知项的副作用，而被拒项仍不获取客户端。每次尝试的客户端获取 ID 均恰好是外层调用 ID 加 `#0`/`#2`；它们不证明服务端幂等。这是**调用方发起的重试**，不是真实 `ToolGatewayClient` 的传输重试路径。

此测试为直接模型调度提供主会话上下文。它不运行子 agent connector 循环、并发批量执行器、真实 gateway 凭据/权限解析或生产操作级 grant。清单 ID `connector_batch_item_veto_partial_retry` 对应该断言。所有受控写门禁继续阻断。

### 2.6 冻结 worker 配置与当前持久读策略

[Worker 策略契约](../tests/contracts/test_worker_policy_enforcement.py)启动全新进程，在 runtime import 前调用真实 `agent.managed_worker.bind_worker_policy`，加载真实目录夹具插件，并在多次模型/直接 registry 调用之间持续存活。Handler 使用现有[加 fence 的读协调器](27-fenced-read-admission-zh.md)及[准备读审计](63-prepared-read-audit-zh.md)。不新增运行时授权器、生产 adapter、grant 状态或激活选项。

夹具通过私有测试控制管道明确提供独立的合成单次 host confirmation，以及合成所有权/resource snapshot。Pending 数据库行、模型参数中的 `approved: true` 和 draft 标签都不能提供这些 adapter 或 handle。读取内容仅为固定合成摘要。真实 owner adoption、`WorkerChannel`、提供方推理、完整 managed-worker 生命周期及生产写入权限不在测试范围内。

- 在另一连接撤权或替换策略前，同一 handler 经模型和直接 registry 调度均可成功。后续调用会再次进入 handler，但旧版本条件下不读取资源，也不提交新的审计。PID 不变，即使磁盘 config 已损坏，原生 config 仍返回冻结值。当前策略来自独立 SQLite 存储，而非 profile-config 刷新。
- 无内容变化的策略替换仍推进 policy revision/epoch。只有独立新签发、匹配新策略的合成 confirmation 才能再次读取；enrollment 仍为 pending。即使合成 confirmation 匹配已撤权行的当前版本，也仍会被拒绝：终态撤权不是激活 enrollment 的路径。
- 准入优先顺序在有界合成读取期间持有真实 SQLite 写锁。独立零超时竞争者观察到 `SQLITE_BUSY`；预先初始化的另一撤权者尝试自己的 `BEGIN IMMEDIATE`，仅在已准入读完成后提交。读审计保留准入时的 epoch。撤权优先顺序将撤权事务保持在 COMMIT 处，同时 worker 尝试准入；撤权提交后不发生资源读取或审计。这些测试不承诺收回已准入的数据。
- 缺少 authority/resource adapter 时，在访问资源前拒绝。已消耗的单次 handle 无法经另一调度路径重放。Dispatcher hook 不是该策略门禁：执行检查位于夹具 handler 对协调器的调用内部。
- SQLite authorizer 故障注入分别拒绝 enrollment 读取、审计插入或 COMMIT。所有情形均不返回摘要，也不提交 prepared-read 审计。审计/COMMIT 失败发生在合成摘要已被读取之后；测试不宣称撤销该次读取。移除故障后，新独立 confirmation 可恢复成功。
- Troubleshooting safe bootstrap 不加载该夹具插件/工具；真实 registry/模型尝试失败，且不增加读审计。这验证夹具能力缺失，不验证真实生产包 fallback 或宿主全局只读行为。仍需独立的生产暴露面测试。

子进程环境使用显式 allowlist 并拒绝 socket 连接。共享测试控制读取器强制绝对整帧截止时间、字节数上限及完整 JSON object 分帧，覆盖部分帧、EOF、连续帧和超限回归用例；teardown 关闭流、join 策略修改线程并回收子进程。它是夹具协议，不是原生 owner/worker IPC，也不是新公开 API。

| 清单契约 ID | 可执行断言 |
| --- | --- |
| `worker_current_policy_recheck` | `test_live_worker_rechecks_persistent_policy_on_both_dispatch_paths` |
| `worker_missing_authority` | `test_pending_record_and_model_claims_do_not_replace_adapters` |
| `worker_transaction_failure` | `test_handler_storage_failures_return_no_data_or_committed_audit` |
| `worker_safe_capability_absence` | `test_safe_worker_suppresses_fixture_plugin_and_registry` |
| `worker_admission_before_revoke` | `test_admission_holds_sqlite_lock_before_competing_revoke` |
| `worker_revoke_before_admission` | `test_revoke_commit_wins_while_worker_waits_for_sqlite` |
| `worker_one_shot_cross_path` | `test_confirmation_is_consumed_across_dispatch_paths` |

## 3. 受控写发布清单

| 路径 | 本切片证据 | 发布状态 |
|---|---|---|
| `native_dispatch` | 合成 hook 与外层 dispatcher 失败契约 | 阻断；尚未接入操作级授权 |
| `direct_registry` | 合成跳过 hooks 契约 | 阻断；handler 需自行检查操作级权限 |
| `mcp` | 真实 SDK stdio 的插件否决/直接 registry 及原生 trust gate 边界；虚假只读反例 | 阻断；没有生产逐动作授权或凭据/结果合同 |
| `shell` | 惰性 backend 上的原生 deny/workdir 与公开/内部 force 边界 | 阻断；没有真实 shell、隔离或操作级权限合同 |
| `browser` | 惰性端点前的原生云元数据 URL 字面量预扫描及插件/直接 helper 边界 | 阻断；没有真实导航、身份绑定写入或结果合同 |
| `execute_code_rpc` | 内存传输上的原生服务端/default 嵌套调度及生成客户端重试 | 阻断；存在重放反例，沙箱与当前 cell 权限仍未验证 |
| `local_tool_batch` | 真实主/子循环、逐项否决、结果配对及显式重试反例 | 阻断；没有持久副作用幂等或持久撤权 |
| `connector_batch` | 离线 gateway 客户端上的真实逐项模型调度、索引化部分结果及显式重试 | 阻断；生产 grant、凭据、传输重试及服务端幂等仍未验证 |
| `short_worker` | 真实子 agent 构造/工具集限制与本地批量循环 | 阻断；调度器、后台生命周期及生产权限仍未验证 |
| `managed_worker` | 真实 import 前 worker 绑定；合成读 handler 在两条调度路径内检查当前 SQLite 策略/撤权 | 阻断；没有生产 authority、write grant 或完整 worker 生命周期 |
| `scheduled_job` | 无授权/取消/交付/对账合同 | 阻断 |

`synthetic_contract` 和 `pinned_host_boundary_contract` 是有界证据标签，不等于完整覆盖某类工具。内存探针通过，不能证明 shell、MCP、browser、外发或真实 worker 副作用受保护。清单内部不可变，返回独立快照；修改报告不能授予能力，也不能改变后续报告。

## 4. 启用写操作前的要求

1. 通过 E1 建立 verified owner 与有范围的 action intent/grant，依据可信来源，不使用模型传入的批准标志。
2. 每个领域动作 handler 自身执行授权检查，包括不经过面向模型 hook 链的调用。Policy store 失败不能变成许可。
3. 动作准入时读取当前持久 policy revision，冻结的 worker config 不是该权威。遵循 [撤权设计](06-plugins-mcp-and-security-zh.md#8-撤权审计与应急停止) 的事务顺序与在途动作边界。
4. 验证每条启用路径，并缩减暴露工具、凭据和执行环境，防止未受保护的替代路径执行同一受控动作。
5. 威胁需要 containment 时使用合适的 OS/进程隔离。进程内 hooks 和本清单不能替代隔离。

本切片没有可启用写操作的 mode 或配置开关。独立配置的 Hermes host 仍可能暴露自己的工具，本插件不宣称控制这些工具。

## 5. 证据与限制

- 当前目标：[compatibility.json](../compatibility.json)记录的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`、Linux、Python 3.14、隔离测试 home，无账号凭据。最初切片使用 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`；历史结果与当前确切修订运行分开记录。
- 检查脚本现在通过官方逐文件 Hermes runner 运行 `tests/contracts` 下全部文件，同时执行单元测试、Ruff、ty 和双语文档检查。
- 实测 dispatcher 失败覆盖 `model_tools` wrapper，包括默认嵌套 RPC 调度。MCP 观察覆盖真实 stdio 夹具与原生 trust wrapper，不代表全部服务端传输或账号策略。终端/浏览器观察止于惰性执行端点。纯 connector 观察止于离线 gateway 客户端。本地批量及构造出的子循环不证明被委派调度或后台生命周期，且未执行并发批量执行器。现在已在原生 worker 绑定下的合成读 handler 内核验当前持久策略。真实隔离、身份绑定副作用、生产包 safe-mode fallback 及完整 managed-worker 生命周期仍是独立证据缺口。早期 config/safe-mode 探针本身并不建立这些保证。
- 无需生产账号、API key、在线模型调用、外发或真实 connector 写操作。未来在线测试需要独立、限定范围的测试配置与安全凭据交接；凭据不得进入聊天、日志或仓库。
- 后续 [E0.2–E0.3 生命周期契约](75-native-lifecycle-contracts-zh.md)增加有界的 Project/Kanban/cron 操作入口证据，并记录缺失的受支持插件 CRUD API；不启用任何生产能力。E0.4 未测路径、依赖 E1 的写入准入、E3 编排与 E4 受控调度仍需独立验收。本切片通过不代表 M0 完成，也不允许这些写功能发布。

使用绝对路径复现聚焦原生测试，因为官方 runner 会切换工作目录：

```bash
HERMES_PYTHON=/absolute/path/hermes-test-venv/bin/python \
bash /absolute/path/hermes-agent/scripts/run_tests.sh \
  /absolute/path/hermes-superagent/tests/contracts/test_nested_rpc_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_mcp_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_shell_browser_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_batch_worker_enforcement.py \
  /absolute/path/hermes-superagent/tests/contracts/test_worker_policy_enforcement.py \
  --file-retries 0 -- \
  -o "pythonpath=/absolute/path/hermes-agent /absolute/path/hermes-superagent" -q --tb=short
python scripts/check.py --hermes /absolute/path/hermes-agent \
  --hermes-python /absolute/path/hermes-test-venv/bin/python
```

聚合命令中的 `python` 应使用已准备的 Python 3.14 测试解释器。较早的 RPC/MCP 文件包含 21 个参数化用例；终端/浏览器、批量/worker 与持久 worker 策略文件新增各自有界用例。聚焦通过不能替代聚合验证或完整 E0.4 验收。准确执行结果以 Issue #12 及关联 PR 为准。本切片不引入宿主补丁或生产能力。

当前固定来源：

- [插件 dispatch 行为](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_dispatch.py)
- [面向模型的工具 dispatch](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/model_tools.py)
- [执行 middleware](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/middleware.py)
- [Managed/safe worker policy](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/safe_worker_policy.py)
- [上游安全模型](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/SECURITY.md)

- [Code RPC 服务端](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/code_execution_rpc.py)与[生成客户端](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/code_execution_tool.py)
- [MCP 原生准入与恢复](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/mcp_tool_handlers.py)

- [终端公开 handler 与执行守卫](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/terminal_tool.py)及[浏览器执行](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/browser_use_cli.py)
- [本地批量展开](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/tool_call_batches.py)及[被委派子 agent 构造](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/delegate_tool.py)
- [Connector 批量调度](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/connectors/dispatch.py)

## 6. E0.4 完成条件与后续能力启用

E0.4 验证边界、恢复限制，以及确实停用或只读的本项目受控能力面。E1 依赖 E0.4；不能将全部生产身份、批准与外部结果机制的实现反过来设为此验证包的循环前置条件。这些能力仍须在各自门禁通过前保持停用。

关闭 Issue #12 前，剩余的有限证据须证明：

1. Default/read-only、普通 managed、config-only 与 troubleshooting safe bootstrap 下真实生产包的暴露面及负向调度。仅报告用途的清单或测试夹具工具缺失并不足够。
2. 原生并发批量准入及其余委派/后台与 execute-code 替代路径：提供行为边界测试，或明确不支持的接缝并验证本项目受控模式不暴露它。惰性 shell/browser 端点不证明 backend 隔离。
3. 最终有限清单将每条路径映射到确切边界、拒绝/不暴露断言、副作用判据及已测修订。分开列出已验证的 E0.4 边界、技术上不可用模式，以及下游 E1/E3/E4/E5 启用工作。

本项目可以证明自身受控写 adapter 不可用，同时独立配置的 Hermes 宿主仍暴露原生工具；不能将此描述为宿主全局只读执行约束。未来任何隔离宿主或通用 worker 的主张，都需要相应工具、凭据及 OS/进程隔离证据。
