# 85. 版本化本地记忆 SDK

[English](85-local-memory-sdk.md) | 简体中文

## 范围

项目拥有的本地 SDK 是面向**已经审查并打开**的适配器的显式外观层。它为适配器作者提供 API-v1 显式记录子集的可复用请求/结果边界和行为合规运行器。它不是 [30](30-pluggable-memory-contracts-zh.md) 中完整的 E2.6 设计、公共 REST API、第三方加载器，也不替换 Hermes 原生记忆 provider。

支持范围为 `trusted_profile_local`。可信打开方负责存储选择、资源生命周期和配置档案绑定。SDK 准入需要有界 export 读取，先核对其 namespace 与绑定一致，再允许操作；不具备 export 能力的适配器不会准入。这能发现普通路由误绑定，不能发现谎报 namespace 的不诚实适配器。传入 Python 绑定对象不证明真人身份、租户授权，也不能隔离恶意代码。请求载荷不能选择 owner、namespace、任意文件路径、URL 或 SQL 语句。经过审查的进程内 Python 仍是可信代码。

普通插件现有的 `MemoryService` 和 SQLite 存储保持不变。不会切换已配置 provider，合规测试不会打开生产配置档案，也不引入凭据、网络接收方或付费模型调用。

## 契约及失败语义

本地外观层支持 `remember`、`correct`、`forget`、`get`、`list`、`search` 和 `export`。它协商现有严格描述，并在执行前验证请求。它在返回调用者前验证实际结果，包括有界记录字段、revision、不含载荷的修改回执、终止性墓碑和分页。不支持的操作会显式拒绝，不以模拟行为替代。

后端异常及无效结果不得泄露任意异常字符串或后端载荷。有限白名单中的领域拒绝（包括 CAS 冲突及记录缺失/已遗忘）仅在适配器契约保证这些异常代表未提交新修改的前提下被信任。保留其错误代码，但禁用重试；未知代码和任意错误消息不会透传。不诚实适配器若先提交再报告白名单拒绝，属于违反契约，Python 结果验证无法检测。确认丢失或无效时，写入可能已经提交：`outcome_unknown` **不代表**没有写入。外观层不会自动重试。应保留原始 request ID，依据经过审查的后端持久回执语义进行对账；不要仅因确认被拒绝就创建一次新修改。读侧失败也不是数据不存在的证据。

显式上下文组装使用经过验证的搜索结果，预算按紧凑 `ensure_ascii=False` JSON `items` 数组的字符数计量。它不包括外层 envelope，也不是字节、token 或完整上下文预算。它保留完整记录，不静默截断单条文本值。它不是自动召回、语义搜索、事实验证或完整的原生上下文预算集成。

## 行为合规

标准库运行器接受调用方拥有的工厂，要求使用新建、明确隔离的合成数据存储。它跨多次重新打开操作同一个存储。切勿指向生产配置档案：测试会有意写入、更正和遗忘合成记录。隔离声明是调用方的责任，不是能够约束恶意工厂的沙箱。

内置 SQLite 适配器和独立合成示例覆盖持久重开、精确请求重放、请求变化冲突、拒绝过期 CAS、终止性遗忘、不含载荷的历史回执、中文的字面搜索和有界结果/上下文行为。示例用于教学，不是生产适配器或存储安全认证。

通过这些门禁仅对实际执行的后端和夹具提供有界证据。它不认证断电持久性、恶意 Python 隔离、加密存储、远程确认、来源真实性、迁移、快照或生产召回质量。仍需运行现有 SQLite 事务、竞争、迁移及私有存储测试。

## 运行独立示例

在仓库根目录，或已安装的运行时包位于导入路径时，运行这个仅依赖标准库的示例。每次运行会创建并清理专用合成目录。真实适配器作者需提供单独审查的打开方，不得将临时路径替换为生产存储。

```python
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from personal_agent.memory_conformance import run_conformance
from personal_agent.memory_sdk import LocalBinding, LocalMemorySDK
from personal_agent.memory_sdk_example import SyntheticMemoryAdapter

with TemporaryDirectory() as directory:
    @contextmanager
    def open_synthetic():
        backend = SyntheticMemoryAdapter(Path(directory))
        sdk = LocalMemorySDK(
            backend, LocalBinding("synthetic-example", "synthetic-session")
        )
        try:
            yield sdk
        finally:
            sdk.close()

    print(run_conformance(open_synthetic, isolated_synthetic=True))
```

## 可选持久进度扩展

新增的 API-v1 SDK 操作 `changes`、`consumer_get` 和 `consumer_advance` 复用已有的 [37](37-durable-memory-progress-zh.md) 后端契约。仅支持 CRUD 的适配器仍可准入，现有 `run_conformance` 运行器不变。缺少声明能力时在分发前失败，不提供回退。推进需要 `metadata_changes`、`durable_consumer_cursor`、持久写入、CAS 和幂等性。SDK 还会在后端分发前拒绝模型来源绑定，包括回执重放。可信打开方仍须正确绑定实际后端；这不是身份认证。

变更页只包含序列、记录 ID、revision 和操作，不包含历史载荷、来源标签、请求键或摘要。严格验证检查精确字段、整数类型、递增序列、请求边界、水位关系、分页及固定为零的保留下界。同一页中重复记录 ID 的 revision 必须递增，记录终止性遗忘后不得再有该记录的事件。不引入连续序列要求或跨调用历史缓存。消费者读取及回执验证精确标识符、注册状态与 revision 一致性、作用域及请求的推进值。成功推进的回执是历史元数据，不一定代表当前游标。游标或经过验证的响应均不能证明原生检查点完成、外部发布、来源覆盖或恶意适配器的诚实性。

推进属于写入：意外异常或无效确认会产生 `outcome_unknown`，不会自动重试。保留原始 request ID，通过精确重放和 `consumer_get` 对账；重放旧回执不得倒退当前进度。可信的“未提交新修改”拒绝白名单包含序列/未来水位、游标未推进、消费者配额及操作者作用域失败。任意后端消息仍不会透传。

适配器作者可以在**另一个全新的合成存储**上，单独运行 `personal_agent.memory_conformance` 中的 `run_progress_conformance(factory, isolated_synthetic=True)`。该可选套件检查贯穿更正与遗忘的有界/固定上界分页、重开后游标持久保留、精确重试、同键变更载荷冲突、过期 CAS、倒退/未来拒绝、独立消费者及不倒退进度的旧回执重放。它要求这些可选能力，不会静默跳过不支持的适配器。独立 CRUD 示例不声称支持进度。基于 SQLite 的测试还注入无效元数据/回执和确认丢失。这些属于离线观察，不是生产、断电或原生生命周期验收。

## 可选本地元数据检查点扩展

新增的 API-v1 操作 `checkpoint_create`（`expected_watermark`、`request_id`）和 `checkpoint_status`（`checkpoint_id`）通过 SDK 暴露已有的 [39](39-local-memory-checkpoints-zh.md) 本地元数据契约。两者均要求 `local_metadata_checkpoint`；创建还要求 `durable_write`、`cas` 和 `idempotency`。缺少能力时在分发前失败，不通过模拟提供替代。创建要求 SDK 绑定具有 `explicit_local_operator` 来源，并在任何后端分发前检查，包括精确回执重放。可信打开方仍须正确绑定实际存储；绑定不是身份认证。仅支持 CRUD 的适配器、现有 CRUD/进度操作及运行器均保持不变。

请求和响应使用精确键集合。验证拒绝额外字段、无效标识符和类型、超出边界的计数或水位、不一致的计数关系、格式错误的元数据哈希及请求/回执不匹配。回执只包含有界记录/事件元数据，不包含记录文本、内容哈希、来源/session 标签或任意后端字段。其固定作用域为 `local_record_metadata_not_native_conversation`，并具有 `restorable: false` 和 `native_checkpoint: false`。状态验证嵌套回执及请求的检查点 ID、`is_current`、`current_watermark` 和固定作用域 `metadata_comparison_at_this_read_snapshot_not_restore_or_authority`。有效元数据不能证明不诚实适配器的完整性、载荷正确性或原生来源覆盖。

创建以观察到的水位作为围栏。空存储可捕获水位零；后续更正或遗忘会使较早的检查点过时。精确重放返回原始历史回执，不创建新快照，也不表示该检查点仍为当前状态。使用 `checkpoint_status` 检查该读取快照时刻的新鲜度；即使结果为当前，也可能立即过时。两种操作都不会恢复记录或已遗忘内容。既有的有界存储扫描和回执配额仍适用；本 SDK 扩展不增加模式迁移、裁剪、自动调度或保留机制。

创建属于写入。未知后端失败或无效确认会产生经过脱敏的 `outcome_unknown`，并禁用自动重试，因为检查点可能已经提交。保留原始 `request_id` 和不变的 `expected_watermark`：显式重放完全相同的键和载荷进行对账，再通过 `checkpoint_status` 检查返回的检查点。不要仅因确认丢失就使用新键，也不要将状态读取失败视为不存在。已知领域拒绝仅在经过审查的适配器保证未提交新修改的契约下保留；不会返回任意后端消息。

适配器作者可以在**另一个全新的合成存储**上单独运行 `personal_agent.memory_conformance` 中的 `run_checkpoint_conformance(factory, isolated_synthetic=True)`，不得使用生产配置档案或 CRUD/进度套件已经使用过的存储。该可选运行器覆盖空/当前/过时检查点、更正和终止性遗忘、重开后的持久性、精确历史重放、请求变更冲突及过期水位围栏。不支持检查点的适配器会显式失败，而非静默跳过套件。上方独立 CRUD 示例不声称支持检查点。这是隔离的本地离线合规验证，不是生产验收或原生 checkpoint-v2 支持。不改变原生 provider、网络操作、共享 REST 契约或宿主生命周期行为。

## 可选规范修改结果检查

可选的 `mutation_receipt_status` 操作使用事先保留的规范化请求身份，检查 `remember`、`correct` 和 `forget`。它从同一读取快照返回历史回执及单独的当前元数据，或明确表示该快照中不存在。它不重放修改，也不需要原文。摘要契约、只读恢复、严格验证、隐私边界及仍然独立的来源接受/游标协议见 [95](95-canonical-mutation-status-zh.md)。现有进度与检查点恢复语义不变。

## 剩余 E2.6 工作

更广的 [#43](https://github.com/MosBot-AI/hermes-superagent/issues/43) 保持开放：本地外观层并未交付完整的版本化来源/事件及多类型契约、远程对账、替换激活/迁移、经过审查的加载/资源 ABI 或原生生命周期集成。[82](82-shared-client-api-zh.md) 中共享客户端契约不变；Python SDK 不证明已提供认证 HTTP 或跨后端功能等价。

## 可选的保留来源接受

[96](96-retained-source-acceptance-zh.md) 新增可选的 `retained_source_acceptance` 操作族：`source_stage`、`source_accept`、`source_discard`、`source_status` 和 `source_cursor`。仅含元数据的待处理槽在实际规范写入前绑定明确授权的独立保留；接受、独立来源游标及抑制检查在同一个事务内提交。来源信息与现有编辑路径字段分开，通过决定/状态查看，而不附加到普通记录 `get` 或召回中。可选的 `run_retained_source_conformance` 入口使用单独的空合成存储。Schema-12 迁移和隔离原生消费端不启用自动生命周期、checkpoint-v2、提供方切换或生产摄取。
