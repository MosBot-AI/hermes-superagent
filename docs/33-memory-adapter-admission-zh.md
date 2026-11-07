# 33. 显式记忆适配器准入

[English](33-memory-adapter-admission.md) | 简体中文

状态：已实现面向[显式本地切片](31-explicit-local-memory-zh.md)的内部契约层，并增加**仅供审查的已安装包元数据发现**。这不是完整 SDK、provider 加载器、新配置项或原生 MemoryProvider 桥接。[完整记忆方案](30-pluggable-memory-contracts-zh.md)仍规定未来生命周期、迁移和远程存储的约束。

## 1. 运行时协商

`MemoryService` 现在会先验证完整 API-v1 描述，再准入已经选定的后端。API/schema 版本和数值限制必须是实际整数，不能用布尔值或可转换的字符串。缺少或未知字段、不支持的主版本、重复或未知能力、互相矛盾的能力声明，以及不兼容的语义，均以脱敏的 `unsupported_backend` 失败。

本版本仅准入 `trusted_profile_local` 显式记录，不声明外部数据接收方，使用区分大小写的字面子串搜索、清除载荷的终止性墓碑，以及现有不可恢复的记录分页导出格式。描述只是已审查代码的声明，不证明代码诚实、持久，或无法访问网络。不宣称能隔离恶意 Python。

服务保存协商后能力和限制的不可变副本。每个请求仍先通过常规载荷校验，再在**调用后端之前**检查操作能力和大小。记住操作要求持久写入及幂等；更正和遗忘还要求 CAS。搜索和导出要求各自对应的能力。只读或能力受限的适配器不会悄悄收到不支持的写入。声明的请求上限更小时，返回 `backend_limit_exceeded`，不静默截断数据或扩大限制。声明的总存储上限仍由后端执行，不是服务独立计数的配额。

现有 SQLite 后端无需修改即可满足契约。其存储 schema、直接命令、会话激活规则、原生 provider 选择和已存数据保持不变。协商不会打开存储、认证真人、证明事实正确，也不承诺自动召回。

## 2. 只读元数据发现和选择

`discover_adapter_candidates()` 显式读取拟议项目组 `hermes_personal_agent.memory_backends` 的已安装 entry-point 元数据。它不调用 entry point 的 `load()`，不导入目标、不执行工厂、不安装依赖，也不访问凭据。普通插件初始化不会调用发现函数。原生 Hermes 组 `hermes_agent.memory_providers` 与之独立，不在检查范围内。

每个不可变的 `AdapterCandidate` 包含适配器 ID、规范化发行包名称、精确版本，以及精确的模块/工厂目标。最多发现 128 个条目；格式错误、ID 重复，或占用 `local_sqlite`、`builtin`、`default`、`none` 保留 ID 都会失败关闭。不会随意选取重复项，也不会回退至其他后端。

`select_reviewed_candidate(candidate)` 重新读取元数据，要求精确的已审查候选项仍被安装。发行包、版本或目标改变时返回 `adapter_review_changed`；缺失时返回 `adapter_not_installed`。这只是审查辅助，**不是授权、激活、可执行句柄或产物签名**。相同版本的包仍可能改变字节。未来加载器在执行第三方代码前，仍需已审查的产物/安装流程、检查与使用之间的变更策略、通用打开/资源 ABI、作用域绑定、数据共享准入及受支持的隔离。[30](30-pluggable-memory-contracts-zh.md) 中拟议的 `create_backend(host, config)` 工厂仍未实现。

## 3. 可复用行为门禁

`tests/unit/test_memory_adapter_conformance.py` 提供 `ExplicitRecordConformance` 测试集。适配器可提供 `open_adapter` fixture 来复用：它返回上下文管理器，每次重新打开同一个新建、隔离、合成数据的持久存储。fixture 负责资源创建、绑定和清理。内置 SQLite 适配器分别通过操作员与已激活模型来源模式运行这组测试。

共享门禁覆盖持久重开及精确回执重放、载荷变化冲突、拒绝过期版本且不修改数据、终止性遗忘、墓碑导出、旧回执重放不复活内容、中文短词/字面通配符搜索、大小写语义和有界分页。修改回执不包含载荷文本。独立准入测试覆盖描述格式错误、执行前拒绝不支持的能力或超限请求、元数据变化、重复/保留包名，以及不导入代码的发现。仓库的 socket 防护继续生效。

这些测试不认证远程确认、恶意代码、加密存储、快照、回滚/切换、来源归属、原生生命周期或生产召回质量。现有 SQLite 事务、迁移、竞争和私有存储测试仍需与这个可复用子集一起通过。

## 4. 验证及剩余门禁

运行常规聚合检查；若具备固定宿主 checkout/interpreter，也运行对应契约：

```bash
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

不安装或选择新包，不修改生产配置档案，也不需要付费 provider 调用。E2.6 新增严格的显式记录契约及元数据审查先导，仍未完成。公共加载器/SDK、替换激活/迁移、绑定来源的提取、原生桥接、checkpoint 持久性、投影和外部存储仍待实现。测试通过不构成启用这些能力的授权。
