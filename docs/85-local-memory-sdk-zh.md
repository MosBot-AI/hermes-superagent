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

## 剩余 E2.6 工作

更广的 [#43](https://github.com/MosBot-AI/hermes-superagent/issues/43) 保持开放：本地外观层并未交付完整的版本化来源/事件及多类型契约、远程对账、替换激活/迁移、经过审查的加载/资源 ABI 或原生生命周期集成。[82](82-shared-client-api-zh.md) 中共享客户端契约不变；Python SDK 不证明已提供认证 HTTP 或跨后端功能等价。
