# 107. 托管本地记忆会话

[English](107-managed-memory-sessions.md) | 简体中文

## 已实现边界

Issue [#155](https://github.com/MosBot-AI/hermes-superagent/issues/155) 为显式审查过的本地 Python 工厂增加资源生命周期管理。`memory_sessions.FACTORY_VERSION = 1` 独立于 SDK/API/存储版本。`MemoryFactory.acquire(resources, binding, mode)` 接收不可变的 `LocalBinding` 和显式 `readonly` 或 `writable` 模式。获取资源前检查版本、绑定类型和模式。不会执行模块字符串、已安装入口点或配置值来选择工厂。

通过 `ResourceScope.register(cleanup)` 立即注册每个已获取的资源，然后才能执行下一个可能失败的步骤。后端初始化之前注册后端清理。每个注册回调按注册逆序恰好尝试一次，包括获取资源、描述符/导出准入、命名空间拒绝、正文或清理失败以及 `BaseException`。尝试回调不保证操作系统资源成功关闭。未披露的资源无法自动清理。工厂仍是可信的进程内代码，不是沙箱、认证机制或硬超时边界。

`LocalMemorySDK.session(factory, binding, mode=...)` 负责从资源获取到清理，并执行现有的有界描述符/导出/命名空间准入。显式 `sdk.close()` 清理托管资源；重复关闭和后续上下文退出不会重复清理。退出后 SDK 不可使用，即使清理失败也是如此。清理回调尝试与错误报告彼此独立：在异常处理块中显式关闭时暂缓清理错误，使真正向外传播的主要错误优先。如果托管上下文最终成功退出，则报告一次暂缓的 `cleanup_failed`。已经报告的清理错误不会再次报告。因此 `ResourceScope.close(primary=error); close()` 可以报告暂缓的错误，但不会重复回调。文件头和维护锁清理只捕获自身操作中的异常，不使用无关的外围已处理异常。现有 `LocalMemorySDK(backend, binding)` 构造器保留已打开后端契约：调用方负责获取/准入失败及宿主连接；其 `close()` 仅关闭后端。

只读托管 SDK 会话在分派给后端前拒绝所有 SDK 修改，即使工厂声明可写能力。现有操作员/模型来源及命名空间验证保持有效。绑定是可信路由声明，不证明所有者身份或任意 Python 代码的诚实性。

## 生产集成与错误优先级

现有 `open_memory_backend` 和 `open_existing_memory_reader` 都使用内置 `SQLiteMemoryFactory` 和共享托管资源作用域。签名和产出的后端接口不变。配置目录/路径检查、私有文件准入及完整维护锁生命周期保留在存储边界。工厂本身接收已准入的路径，不是替代路径验证或生产后端替换 API。SQLite 仍是维护、投影和来源操作唯一的权威存储。

在构造后端之前注册连接；在 PRAGMA/open 之前注册后端清理。后端关闭失败不能跳过连接或锁清理。只读原始文件头描述符仍在打开 SQLite 之前关闭，保留现有 POSIX 描述符/锁注意事项。只读仍仅访问现有存储，不创建/迁移，保留文件头/日志拒绝、`mode=ro` 和 `query_only`。原生生产读取器直接使用资源层，不增加 SDK 导出探测：仅元数据来源恢复和有界原生召回保留现有契约。

清理也失败时保留已有的获取/准入/正文错误，包括取消和 `outcome_unknown`。没有主要错误时，清理失败仅产生已脱敏的 `cleanup_failed`，禁用重试。清理无法撤销已提交修改，也不意味着回滚。保留不确定操作的原始请求身份，通过现有后端协议核对；不要自动发起另一次写入。

## 独立示例与一致性验证

仅使用全新、显式隔离的合成目录：

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from personal_agent.memory_conformance import run_managed_conformance
from personal_agent.memory_sdk import LocalBinding
from personal_agent.memory_sdk_example import SyntheticMemoryFactory

with TemporaryDirectory() as directory:
    report = run_managed_conformance(
        SyntheticMemoryFactory(Path(directory)),
        LocalBinding("synthetic-example", "synthetic-session"),
        isolated_synthetic=True,
    )
    print(report)
```

共享运行器验证持久 CRUD/重新打开/精确重放、显式重复关闭、逸出句柄失效和只读拒绝。内置 SQLite 工厂与独立实现的合成工厂都执行该套件。独立示例用于教学，不是生产存储安全或迁移认证。故障测试另行注入构造器/connect/PRAGMA/open、描述符/导出/绑定、正文及清理失败，包括取消和组合清理故障。现有 CRUD/进度/检查点/来源套件仍然必需；原生契约测试使用合成数据验证实际生产路径和新进程重放。

这些是离线本地观察，不是部署验收、断电保证、恶意代码隔离或完整 E2.6 完成。不会引入存储版本、召回语义、冻结题集/报告、宿主固定版本/补丁、公共 REST 契约、提供方选择、凭据、付费模型调用或部署变更。doc30 更广泛的替换/迁移及原生生命周期门槛仍未关闭。
