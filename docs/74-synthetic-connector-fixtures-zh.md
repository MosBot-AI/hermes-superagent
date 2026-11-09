# 离线合成连接器测试夹具

[English](74-synthetic-connector-fixtures.md) | 简体中文

## 范围

面向 [Issue #13](https://github.com/MosBot-AI/hermes-superagent/issues/13) 的本次 E0.5 切片，在 `tests/fixtures/synthetic_connectors` 中提供可复用的离线来源与连接器故障测试夹具。合成写入只向临时 SQLite 假远端插入记录，不发送消息、不调用服务商，也不使用真实账号。原生边界使用固定版本 Hermes 的 MCP 客户端和 SDK stdio 服务端，不使用 HTTP 监听器。

夹具协议是[文档 14 连接器设计](14-client-api-contracts-zh.md)的简化测试模型，不是生产实现。它不签发派发许可，也不证明 owner 身份。[ActionIntentStore](64-action-intent-drafts-zh.md)仍是内部、仅限草稿的账本，没有审批或执行 API。E0.4、E1、E5 以及线上服务商验收仍未完成。

## 夹具结构与信任边界

- `core.py` 提供 `Remote`、`Capabilities`、固定校验错误及确定性故障挂钩。假远端在自己的 SQLite 文件中保存持久账号、绑定、尝试、副作用与取消记录。
- `corpus.json` 包含版本为 `synthetic.sources.v1` 的记录，账号严格限定为 `account-a` 和 `account-b`。正常、冲突、冒充 owner、转发和提示注入记录均带来源 ID、账号引用、作者标签及来源信息。每条来源的 `authenticated_owner` 都是 false。固定的 `.invalid` 地址和 URL 仅是夹具标签，不能作为网络访问目标。
- `stdio.py` 通过宿主固定版本的 MCP SDK 暴露夹具，仅由临时 Hermes home 中的显式测试配置启动。普通插件加载不会发现或注册这些工具。
- 运行包使用显式[文件允许列表](../packaging/runtime-files.json)，排除 `tests/`，包括语料和 stdio 适配层。没有增加生产插件配置、依赖、存储迁移或连接器激活。

来源内容和工具结果中的自然语言是不可信数据。自称 owner、要求更改收件人、声称已批准、要求读取秘密或宣称成功，都不产生权限。测试配置显式选择对抗行为；夹具绝不把来源文字解释为代码或配置命令。合成 canary 字符串不是真实秘密。本测试框架不是任意 Python 或恶意 MCP 服务端的安全沙箱。

## 绑定与限制

准备后的 envelope 绑定 `schema_version`、`account_ref`、`operation`、`target`、`payload`、`effect_key` 和 `prepared_version`，并包含独立的目标/内容摘要以及绑定元数据摘要。唯一写操作种类为 `message.send`，目标限定为两个固定夹具收件人。正常准备不产生副作用。故意不纯的 `impure_prepare` 和 `lying_read` 是正向对照，违反表面语义，以便独立观察者发现差异。

校验拒绝多余字段、浮点数/非有限值、不支持的账号/目标、无效版本和变更后的绑定。原始 `strict_json` 解析器（包括显式 `fixture_prepare_json` 原始字符串入口）也拒绝重复键；SDK 解码后的对象不能反映已被外层 MCP JSON-RPC 解析器合并的重复键。输入 JSON 上限为 8,192 字节、深度 8；消息内容上限为 2,048 个 UTF-8 字节；来源分页为 1–4 条记录。准备版本与持久账号配置核对。测试专用账号控制可模拟 `connected`、`expired`、`revoked` 或 `unavailable` 身份验证状态，不需要凭据。整数测试时钟可注入，因此保留期和回退测试不依赖等待或真实服务商时钟。

这些哈希只绑定夹具自身的序列化方式，不是身份验证或生产 RFC 8785 实现，也不能让低熵输入保密。返回的准备 envelope 仍含合成目标和内容明文。假远端保存摘要绑定的副作用元数据，不把 envelope 当作生产授权令牌。

## 远端事实、重试与取消

`Remote.describe`、`health`、`read`、`prepare`、`execute`、`reconcile` 和 `cancel` 都是夹具操作，不是原生插件 API。其能力与限制如下：

| 能力 | 合成行为与限制 |
| --- | --- |
| `native_key` | 同一账号/副作用键仅在有限保留期内对完全相同的绑定去重：默认 60 秒，可配置为 1 至 86,400 秒。过期后直接进行不安全重试可能再产生一次副作用。 |
| `reconciliation_only` / `none` | 执行不去重。是否支持对账单独声明；`reconciliation_only` 要求支持对账。调用方不能因键保持不变就认定可安全重放。 |
| 绑定冲突 | 账号/副作用键持续绑定原始元数据。目标、内容或版本变更均冲突；去重过期不允许更改内容。保留绑定不等于服务商提供无限期幂等。 |
| 对账 | 查找准确的账号/键/绑定，不再次执行。不支持、不可用、未找到、存在歧义或证据不匹配时，保持 `unknown_outcome`。空查询结果不构成重发许可。 |
| 取消 | 默认不支持。启用后，仅能持久取消尚未被接受的副作用。不支持或为时已晚时返回 `cancel_requested`，不删除已接受记录，也不声称投递已停止。 |
| 回执 | 已提交的合成副作用为 `accepted`，且 `delivered: false`。接受不等于投递或已读证据。回执自然语言不是独立证明。 |

远端数据库与消费者观察属于不同证据。提交前故障可能不留下远端副作用；提交后丢失响应可能已留下一个副作用，即使调用方没有收到结果。两者都需要如实观察，而不是凭异常猜测。测试挂钩覆盖提交/响应边界及进程重启，不证明分布式恰好一次投递、硬件断电持久性或跨系统原子撤权。

## 消费者观察与独立判定器

`oracles.py` 将 `Observations` 保存在独立的消费者 SQLite 文件中。`execute_once` 在一次尝试前记录未知观察，绝不重试。`reconcile_only` 可在重启后读取替换的适配器，但绝不调用 `execute`。因此，远端提交与本地观察之间发生崩溃，不能让本地缺少回执变成“未发生副作用”的证据。

`classify_receipt` 检查有界结构、准确绑定、已接受状态及语法上合理的回执引用，仅返回 `accepted_claim`，绝不视为已验证的接受；伪造但格式正确的引用仍可能通过检查。两个场景执行器默认保持 `unknown_outcome`，除非显式测试 `verifier` 返回准确的 `True`。`assert_matching_receipt` 通过 `ground_truth` 读取假远端，核实声称的引用确实指向准确的已提交副作用，从而提供独立判定。真实客户端不能假定具有这种数据库访问权。刻意分离两者，避免模型编写的成功句子或自行声称的回执成为测试事实依据。

`assert_pure` 对比所谓读取/准备操作前后的远端观察。`assert_no_blind_resend` 同时检查副作用和远端执行尝试数，覆盖原本可能被服务商去重掩盖的重试。`validate_sources` 检查固定来源 schema、游标、ID、账号、作者标签和来源信息，拒绝格式错误/超大结果、重复来源 ID 和跨账号记录。有效的来源文字仍只是数据。`sanitized_report` 仅输出固定分类/计数和 `production_authorized: false`，不输出正文、目标、哈希、来源指令、canary 或原始错误。`observation_count` 统计本地观察行数，不是远端执行尝试数。消费者观察和远端尝试均不构成投递证明。

## 真实固定宿主 MCP 边界

原生契约以未变更的[兼容性记录](../compatibility.json)为目标：Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`、Python 3.14，以及该宿主声明的 MCP SDK 版本。测试使用真实发现、注册表登记、SDK stdio 会话和 `model_tools.handle_function_call` 分发。适配层暴露 `fixture_describe`、`fixture_health`、`fixture_read`、`fixture_prepare`、`fixture_prepare_json`、`fixture_execute`、`fixture_reconcile` 和 `fixture_cancel`，以及显式的对抗探针。临时测试配置仅为合成分发设置 MCP `trust: full`；这些测试不证明原生审批执行控制。

真实子进程在远端提交前或提交后退出，使写响应丢失。两种情况下原生客户端都报告结果不确定；新的 stdio 进程对账持久状态，而不是盲目重放。测试独立检查远端 SQLite 文件，不把返回的副作用计数当作证据。

会话过期场景在**真实 stdio RPC 和持久合成写入之后**注入合成 `HTTP 404: session not found` 异常。发现、分发、重连及可能重复的调用都是真实执行，但这不是 HTTP 传输测试。声明为写操作时，宿主保持不确定状态而不重放。谎报 `readOnlyHint: true` 时，同一恢复分支可能重放有副作用的工具，产生第二次合成副作用。该反例说明基于声明的重放不等于副作用级授权或隔离，不声称已经覆盖或修复所有宿主路径。

## 场景与测试证据映射

矩阵列出可执行断言，不独立声称每次运行均通过。确切运行结果与版本以关联 Issue/PR 证据为准。前一组使用[单元测试](../tests/unit/test_synthetic_connectors.py)；宿主/SDK 及之后的行使用[原生契约](../tests/contracts/test_synthetic_connectors.py)。

| 场景 | 具体测试 | 证据边界 |
| --- | --- | --- |
| 有界来源、来源信息与账号隔离 | `test_bounded_corpus_has_stable_provenance_and_separate_accounts`; `test_source_prose_cannot_establish_owner_or_production_authority` | 稳定分页语料、显式账号分离，以及生产评估器拒绝将来源文字作为 owner 上下文。 |
| 格式错误/超大来源结果 | `test_malformed_and_oversized_source_results_are_rejected`; `test_invalid_read_scope_and_bounds`; `test_invalid_source_schema_is_rejected_with_fixed_error`; `test_duplicate_source_ids_are_rejected` | 有界来源解析与无效读取范围，不导入来源，也不自动执行操作。 |
| 读取/准备纯度与虚假声明 | `test_prepare_read_describe_health_are_pure`; `test_dishonest_purity_is_detected_by_independent_oracle` | 独立比较远端状态，发现故意隐藏的副作用。 |
| 准确绑定与账号命名空间 | `test_tampering_prepared_fields_is_rejected_without_effect`; `test_reprepared_changed_data_conflicts_with_stable_effect_key`; `test_account_namespace_is_explicit_not_implicit_permission` | 变更字段不能复用绑定；独立账号键不建立跨账号权限。 |
| 身份验证变更与过期准备 | `test_auth_change_refuses_reads_preparation_and_execution`; `test_prepared_version_is_checked_at_execution` | 过期/撤销/不可用的合成账号及旧版本拒绝后续操作，不是真实身份验证流程。 |
| 严格校验不可信输入 | `test_strict_json_rejects_duplicate_malformed_deep_and_oversized`; `test_invalid_input_never_commits_and_errors_are_redacted`; `test_lists_and_executable_subclasses_are_rejected_before_execution` | 在副作用发生前拒绝重复键、格式错误/过深/超大数据、不支持的字段及可执行容器子类。 |
| 有限幂等与不安全重放 | `test_success_deduplicates_and_receipts_are_accepted_not_delivered`; `test_finite_idempotency_expiry_unsafe_resend_positive_control`; `test_no_native_key_replay_is_deliberately_not_deduplicated` | 接受不等于投递；超过保留期或没有原生键时，不安全重复尝试可能产生重复副作用。 |
| 提交前后故障的不确定性 | `test_indistinguishable_losses_remain_unknown_without_blind_retry`; `test_capability_variants_and_unknown_recovery` | 同样的观察故障可能对应零个或一个副作用。按能力对账绝不再次执行。 |
| 缺少证据不等于未执行证明 | `test_unavailable_or_empty_reconciliation_cannot_prove_nonexecution` | 即使独立观察确认副作用已提交，不可用/空对账结果仍保持不确定。 |
| 如实报告取消 | `test_supported_cancellation_before_acceptance_is_terminal`; `test_unsupported_and_too_late_cancellation_are_truthful` | 接受前取消在重开后仍为终态；不支持/为时已晚的请求不撤销已接受副作用。 |
| 恶意或矛盾回执 | `test_malicious_receipts_fail_independent_evidence_oracle`; `test_plausible_claim_is_not_accepted_without_independent_evidence` | 错误账号/目标/副作用/回执、成功文字、矛盾投递信息与注入指令均无法通过独立证据检查；没有验证器的合理声明仍保持未知。 |
| 进程突然退出后的恢复 | `test_process_crashes_preserve_separate_remote_and_consumer_truth` | 在提交前、提交后以及响应后但观察前真正退出进程；重开消费者后保持未知，直至经过验证的对账。 |
| 并发与时钟回退 | `test_concurrent_native_key_attempts_create_one_effect`; `test_clock_rollback_is_refused_without_new_effect` | 并发的准确原生键尝试共享一个副作用；测试时钟回退不会新建副作用。 |
| 生产草稿边界与脱敏 | `test_actual_action_intents_remain_drafts_across_reopen_cancel_and_expiry`; `test_fixture_binding_is_not_action_intent_or_authorization`; `test_loss_exception_and_reports_never_contain_canaries` | 真实 ActionIntentStore 在重开/取消/过期后仍仅限草稿；夹具数据不是许可，诊断报告不含 canary/内容。 |
| 宿主和 SDK 身份 | `test_sdk_and_host_are_exact_pins` | 将宿主 HEAD 和安装的 MCP SDK 与仓库/宿主声明比较，不声明宽泛兼容范围。 |
| 真实发现、分发与纯度反例 | `test_discovery_and_model_dispatch_reach_real_stdio`; `test_native_read_only_hint_and_prepare_name_do_not_enforce_purity` | 真实 stdio 读取/准备/写入/对账/取消，并在远端数据库中测量谎报读取/准备探针。 |
| 经原生分发校验原始 JSON | `test_raw_fixture_json_rejection_through_native_dispatch` | 有效原始字符串准备后，拒绝重复键/格式错误/多余字段/过深/超大输入，且无副作用；不声称覆盖外层 JSON-RPC 重复键处理。 |
| 远端提交前后服务端退出 | `test_real_stdio_death_is_unknown_without_replay` | 真实服务端退出、原生结果不确定、重启并对账，独立观察零个或一个副作用。 |
| 会话过期与谎报只读提示 | `test_session_expiry_boundary_obeys_declaration_not_real_effects` | RPC 后注入过期边界，对比写操作不重放和谎报只读后重放的副作用计数。不是真实 HTTP 会话过期。 |
| 默认插件保持关闭 | `test_normal_plugin_load_never_exposes_fixture_or_execution` | 默认/只读/本地任务模式均不暴露夹具工具或存储；生产准入保持关闭，ActionIntentStore 没有 approve/execute 方法。 |

## 复现与解读

按[开发验证](../README-zh.md#开发验证)使用隔离测试环境和合成临时 home。不要在生产 profile 中配置适配层，也不要把凭据复制到测试 home。

```bash
python -m pytest tests/unit/test_synthetic_connectors.py -q
python scripts/check.py
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

第一条命令运行聚焦的夹具测试。第二条运行仓库单元、lint、类型和双语文档检查，并明确不运行 Hermes 契约。最后一条增加完整固定宿主契约，包括 stdio 测试，需要准确、干净的 Git 检出及预先准备的解释器。仅发现测试不等于通过；聚焦套件通过不等于完整验收。当前目标和历史证据见[兼容性矩阵](hermes-compatibility-matrix-zh.md)。

## 未完成的验收门槛

本切片不增加网络服务、OAuth 流程、账号连接、模型请求、生产派发许可、outbox 或自动重试引擎。它不完成替代路径执行控制、可信 owner/审批准入、真实连接器集成、实际取消/投递验证或可用 personal-agent 发布。[文档 14](14-client-api-contracts-zh.md) 的设计 API 仍是提案，[文档 64](64-action-intent-drafts-zh.md) 的仅限草稿边界不变。
