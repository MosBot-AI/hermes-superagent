# 75. 原生插件与调度生命周期契约

[English](75-native-lifecycle-contracts.md) | 简体中文

## 范围与基线

此仅测试的 E0.2–E0.3 切片对应 [Issue #11](https://github.com/MosBot-AI/hermes-superagent/issues/11)。它与现有插件契约一起，覆盖 Project、Kanban 和 cron 的真实原生操作入口，并记录缺失的受支持插件接口。不新增生产导入、配置选项、存储迁移、执行权限或已安装的排程。GitHub Projects 跟踪工程交付；原生 Hermes Projects 和 Kanban 是运行时对象，不是该交付台账。

准确目标仍为 [Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`](https://github.com/NousResearch/hermes-agent/tree/2281116525106e3c109993ccb5dc74d02bfc1427)，记录在 [compatibility.json](../compatibility.json)，使用独立的 Python 3.14 测试环境。证据仅适用于该干净的固定检出，不代表宽泛的支持范围。下方场景矩阵标明测试断言，不声称某次运行已通过；确切版本、结果和 CI 链接记录于 Issue 及关联 PR。

## 操作入口不等于插件 CRUD SDK

| 入口 | 固定版本的原生入口 | 边界 |
| --- | --- | --- |
| 插件注册与上下文 | `hermes_cli/plugins.py`、`hermes_cli/plugins_context.py`、`plugins/plugin_storage.py` | 已有真实发现、配置拒绝、注册表/CLI 分发、重载/卸载及 profile 存储契约。`plugin_data_dir` 会创建目录，且不是 `ctx` 方法。 |
| Hook 与中间件 | `hermes_cli/plugins_dispatch.py`、`hermes_cli/middleware.py`、`model_tools.py` | 现有反例覆盖回调拒绝、超时、外层分发器故障和直接调用注册表绕过。这些不是通用写入执行控制。 |
| Project 操作 | `tools/project_tools.py`、`hermes_cli/projects_cmd.py` | 操作工具/CLI 通过原生存储完成操作。它们的存在不表示导出了稳定的插件 Project CRUD 接口，也不把本地项目标签映射为原生 Project。 |
| Kanban 操作 | `hermes_cli/kanban.py`、`hermes_cli/kanban_db.py` | 测试通过 CLI 入口及原生状态/事件/运行辅助函数覆盖创建、检查和归档。测试只使用无 worker 的合成停放任务；归档通常不能当作无害的元数据操作。 |
| Cron 操作 | `tools/cronjob_tools.py`、`hermes_cli/cron.py`、`cron/executions.py` | 测试通过工具入口执行作业操作，通过 `cron_runs` 获取操作者历史输出，并通过原生台账辅助函数作独立观察。作业、执行尝试和投递结果是不同对象。 |
| 已声明插件 API | `hermes_cli/data/plugin_api.json`、`hermes_cli/plugins_context.py` | 清单导出 `cron.execution_identity`，上下文可提供当前 cron 执行信息。它没有将 Project/Kanban CRUD 或 `cron.jobs`、`cron.executions`、调度器内部实现导出为受支持的插件 CRUD API。执行身份不是调度权限。 |

测试对原生操作实现与生命周期辅助函数的导入，是固定版本的探测，不是新增生产插件依赖。缺失的受支持接口保持明确；此切片不通过直接写宿主数据库来绕过缺口。已有默认关闭的[停放式 Kanban 交接](52-parked-kanban-handoff-zh.md)及其更严格的源码/身份守卫保留独立边界。

## Project 语义与限制

原生 Project 创建和列表返回宿主对象身份，不是 personal-agent 副作用回执。CLI 拒绝重复主路径；Project 工具则根据该路径复用已有 Project。这弱于将完整载荷绑定到确切请求键的契约：改名不会让路径查找变成事务性的内容绑定契约。无路径创建可以产生不同对象。查询和重新打开的证据必须识别实际返回的对象，不能从一句成功消息推断恰好创建一次。

Project 归档改变项目元数据和可见性，不证明关联会话、Kanban 任务、脚本或 cron 执行已经停止。原生 Project 存储按 profile 划分，但这不等于验证了 owner 身份，也不能防御可访问同一 profile 的任意代码。本地 TaskStore 的项目名仍是标签；没有新增自动原生 Project 映射。

## Kanban 语义与限制

生命周期测试使用显式临时看板和合成停放卡片。创建、查询、归档观察及原生事件历史，只为这些卡片提供证据，不代表已启动 worker、完成任务或外部副作用已被接受。按顺序使用同一原生幂等键创建时，即使标题/正文改变，也可能返回原卡片。归档后复用该键可以创建新卡片。这既不是精确载荷绑定，也不是永久去重；测试集不保证原生操作入口的并发行为。

原生归档还可能停止 worker 并推动依赖任务进入可运行状态。这里只覆盖无 worker 的合成路径；测试配置不得复制到生产看板，也不能当作通用取消验收。归档卡片不证明已经开始的外部副作用被撤销。已有[结果审核](58-native-result-review-zh.md)继续要求显式本地接受；原生终态不会自动完成本地任务。

Kanban 子进程测试包装在每一步后记录链接的 SQLite 版本和解释器这些运行时元数据，并通过独立的只读连接观察实际 `PRAGMA journal_mode`。对于 SQLite `3.46.1` 这类易受影响的运行时，只接受固定宿主的完整 WAL-reset 警告及观察到的 `DELETE` 回退；对于 `3.53.1` 这类已修复的运行时，这些隔离夹具要求无警告并使用 `WAL`。测试覆盖修复版本的回移边界、意外/缺失/重复诊断、版本/解释器/模式不一致，以及重启后的警告再次出现。固定宿主按进程和数据库标签去重，因此首次打开看板后，共用 `kanban.db (kanban.db)` 标签的其他看板不会再告警。测试不屏蔽警告，也不强制日志模式；无关的文件系统回退仍使这一限定契约失败，而不会被静默接受。

## Cron 定义、尝试与回执

- **创建不等于执行。** 操作入口的创建响应标识一个已保存的作业定义。没有运行中的调度器时，保存的作业不会触发。重复创建没有通用的原生请求键去重保证，可能产生另一个作业。
- **持久化与调度器注册可能分离。** 注册失败可以发生在作业保存之后。必须根据已保存的作业 ID 和部分结果进行核对；失败或丢失的响应不是再次创建的许可。
- **查询不一定纯读取。** 原生作业加载可以修复持久化的畸形或旧格式数据。名为 `list` 的工具或读取包装不会消除这些宿主副作用。仅仅看似观察性操作，不足以让它成为允许的生产个人数据读取入口。
- **取消是请求某次尝试停止。** 响应可以在尝试仍处于 claimed/running 时包含 `cancelled: true`。这确认的是针对该执行的取消请求，不是经验证的终态。它不会暂停排程，后续触发仍可运行。没有进行中的尝试时，取消是成功但无操作的结果。
- **暂停、移除和取消不同。** 暂停改变未来排程，移除删除作业定义。仅凭定义回执或定义消失，均不能证明进行中的副作用已停止，或历史投递已撤回。
- **历史可以保持未知。** 废弃尝试恢复时，无法确定副作用是否发生便记录为 `unknown`。不会仅因缺少回执而安排重试。持久化的尝试 ID 不是任务成功或投递成功的证明。

一次性 `no_agent=True` 测试执行临时脚本，唯一动作是打印固定合成字符串。真实 `cronjob` 运行入口先在暂停状态下拒绝执行，再经显式恢复后通过原生手动路径恰好运行脚本一次，并重新暂停作业。测试检查真实 `completed` 台账行、开始/结束时间、已保存的本地输出、`delivery_outcome: suppressed` 及重新打开后的持久性。它不导入 `run_agent`，也不创建 `state.db`。这是真实本地完成回执，不是排程触发回执（`scheduled_instant` 为 null）、外部投递、owner 通知、线上取消或真实模型验收。重新打开的历史还通过真实 `cron_runs` 入口核验。作业仅存在于可丢弃的测试 profile；不启动 ticker 或安装到用户环境的排程。

## 证据映射与测试隔离

生命周期测试集包括 [Project](../tests/contracts/test_native_project_lifecycle.py)、[Kanban](../tests/contracts/test_native_kanban_lifecycle.py) 和 [cron](../tests/contracts/test_native_cron_lifecycle.py)。它们补充而不替代下方已有测试。第一张矩阵使用这三个生命周期文件中的测试名。

| 场景 | 具体测试 | 证据边界 |
| --- | --- | --- |
| Project 操作生命周期 | `test_cli_create_list_show_archive_restore` | 真实 CLI parser/command 创建、列表、详情、归档和恢复；归档可见性不同于任务取消。 |
| Project 非法输入 | `test_empty_names_rejected_by_real_consumers`；`test_invalid_slug_and_unknown_project_return_errors` | CLI/工具拒绝后无新对象；非法 slug 和未知目标失败。 |
| Project 较弱的重试身份 | `test_cli_rejects_duplicate_primary_but_tool_reuses_existing`；`test_pathless_retry_creates_distinct_ids_without_operation_key` | CLI 路径冲突、工具在名称变化后仍按路径复用、无路径重试产生不同对象，且不存在持久操作键/回执表契约。 |
| Project 持久化与范围 | `test_restart_persistence_and_profile_isolation`；`test_archive_does_not_cancel_linked_native_task` | 新解释器读取和 profile 分离；Project 归档/恢复前后，关联的停放 Kanban 状态/事件不变，没有 worker。 |
| Kanban 创建与观察 | `test_native_consumer_create_show_list_and_real_receipts` | CLI 创建卡片、真实 created/blocked 事件及空运行历史；不伪造执行回执。 |
| Kanban 较弱的原生去重 | `test_native_same_key_changed_payload_returns_original_after_restart`；`test_native_archive_replay_missing_and_archived_key_reuse` | 改变载荷的重复请求返回原对象；重复/不存在目标的归档不改变事件；已归档键可创建不同替代卡片。 |
| Kanban 范围与归档历史 | `test_native_board_separation_and_explicit_scratch_override`；`test_native_consumer_archive_keeps_queryable_history` | 命名看板保持分离；显式 scratch 不继承 Project；CLI 归档保留可查询事件，无 worker 或工作区。 |
| Kanban SQLite 诊断 | `test_native_journal_diagnostic_is_once_per_process_and_returns_after_restart`；诊断校验器回归场景 | 完整安全回退警告或已修复运行时的无警告行为、实际只读日志模式观察、每进程一次的行为，并严格拒绝无关或不一致的诊断。 |
| Cron 定义生命周期 | `test_real_paused_cron_lifecycle_survives_restarts`；`test_cron_profiles_have_independent_jobs_and_receipts` | 真实创建/列表/恢复/暂停/移除、重新打开的定义、运行前空历史，以及临时 profile 间定义/合成 claim 历史的分离；无 ticker。 |
| Cron 不安全重放与校验 | `test_duplicate_creates_are_not_idempotent_and_names_can_be_ambiguous`；`test_missing_job_is_a_failure_without_new_jobs`；`test_invalid_create_has_no_persisted_effect` | 重复创建产生不同 ID；歧义名称、未知 ID 和非法创建输入失败，不增加副作用。 |
| 已保存但未注册的创建 | `test_registration_partial_failure_keeps_job_and_warns_against_recreate`；`test_actual_registration_exception_exposes_partial_commit_contract` | 注入注册 provider 故障，使用真实持久化和真实部分异常：`job_saved: true`、`scheduler_registered: false`、`retry_create: false`。不发起重复创建。 |
| 取消请求与终态的区别 | `test_cancel_without_attempt_is_noop_and_preserves_schedule`；`test_cancel_claim_fixture_is_request_not_terminal_cancellation` | 真实取消入口处理明确的合成 claim；标记保留首个原因，claim 仍非终态，已启用的排程及下次运行时间不变。 |
| 废弃尝试恢复 | `test_dead_process_claim_recovers_unknown_without_job_retry` | 真实子进程建立合成 claim 后退出；另一进程将其恢复为 unknown，不新增运行。定义移除后历史仍保留，真实 `cron_runs` 入口报告该未知尝试。 |
| 原生查询副作用 | `test_queries_repair_only_explicit_disposable_corruption_fixture` | 故意将临时 `jobs.json` 改写为裸列表，由原生 get/list 修复。该损坏夹具不是伪造的成功回执。 |
| 真实本地完成 | `test_real_constant_script_has_local_completion_receipt_not_delivery` | 一个被允许的常量输出脚本进程、已完成的原生台账行、已保存的本地输出及受抑制的投递；检查暂停时拒绝运行、重新打开后的持久性和 `cron_runs` 输出；不声称排程触发已被验证。 |
| 已声明 API 限制 | `test_project_crud_is_not_exported_plugin_api`；`test_exact_pin_public_plugin_api_does_not_offer_native_crud_sdk` | 读取实际插件 API 清单并检查准确宿主版本；缺失 CRUD 导出仍为已记录接口缺口。 |

| 已有证据 | 具体测试集 | 保留的范围 |
| --- | --- | --- |
| 注册、配置、限定范围的分发和数据路径 | [原生插件契约](../tests/contracts/test_native_plugin.py) | 真实 manager 加载/重载/卸载、拒绝非法配置、CLI/工具结果及按 profile 划分的存储辅助函数。 |
| Hook 与故障反例 | [执行控制边界](../tests/contracts/test_enforcement_boundaries.py) | 回调拒绝和超时不能证明外层分发器、直接注册表路径或所有 worker 上下文均会安全拒绝。 |
| 规划模板生命周期 | [规划蓝图契约](../tests/contracts/test_planning_blueprint.py) | 目录、表单、slash、dashboard 集成中使用了替代的 create 调用。仅凭这些旧测试，不能说明创建或执行过 cron 作业。 |
| 已有受守卫保护的停放交接 | [原生 Kanban 契约](../tests/contracts/test_native_kanban.py) | 确切看板、源码、身份约束，未知结果与不盲目重试；不同于原生操作 API 较弱的去重语义。 |
| 本地结果接受 | [原生结果审核](../tests/contracts/test_native_result_review.py) | 不可信的原生证据需要显式、重新核验的本地完成决定。 |

使用可丢弃的合成 home/profile，通过真实原生入口完成修改，不手写宿主数据库 SQL。内部台账辅助函数可建立明确标注的合成尝试，用于取消/恢复测试；这不表示这些尝试实际执行过。不需要真实账号、凭据、模型请求、网络监听器、运行中的 ticker、worker 派发或安装到用户环境的排程。cron 子进程除常量脚本外，还允许严格匹配的只读 `systemctl list-units` gateway 存活查询，不允许启动/停止服务或启动 worker/ticker。临时 `cache/scratch/.last_prune` 新鲜度标记避免触发无关的分离式 scratch 维护；它属于夹具配置，不是执行证据。Python socket 守卫是测试防护，不是恶意代码沙箱，也不证明子进程网络被完全限制。

## 复现与解释

按[开发验证](../README-zh.md#开发验证)使用确切、干净的宿主检出及准备好的解释器：

```bash
python scripts/check.py
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

第一条命令执行仓库单元、lint、类型和双语文档检查，并明确不运行 Hermes 契约。第二条增加完整的固定宿主契约测试。专项生命周期测试通过不等于完整汇总检查通过；收集测试、源码检查或干净 diff 都不是执行证据。失败、跳过、受阻和未运行必须分开记录。本文不新增任何运行计数声明。

## 仍需验收的门槛

有界的 E0.2–E0.3 契约工作不完成 E0/M0、E1 权限、E3 运行时编排、E4 受控提醒、E5 连接器或生产发布。它不实现受支持的插件调度适配器、持久跨系统准入/outbox、精确副作用级幂等、线上 worker 取消、真实账号投递核对或通用原生 owner 隔离。源码缺口可以满足“记录不可用接口”的要求，但不能重新标记为可用功能。

Issue 完成仍要求适用的测试证据、独立评审、变更已合并及合并后 main CI 已验证。更广的父工作及[线上验收](65-live-task-acceptance-zh.md)保留各自门槛。生产 readiness 报告、默认关闭的能力和授权边界不变。
