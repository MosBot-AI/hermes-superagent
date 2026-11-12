# 106. 保留来源恢复发现

[English](106-retained-source-discovery.md) | 简体中文

## 已实现边界

[Issue #153](https://github.com/MosBot-AI/hermes-superagent/issues/153) 新增面向操作者的有界持久保留来源决策发现功能。操作者不再需要记住请求键、摘要或消费者，便能找到中断的尝试。原生 LOCAL 工作台和可选 API-v1 SDK 操作仅使用规范元数据。这是经过合成检查的生产包代码，不代表部署、真实个人数据验收、原生 checkpoint-v2 或完整 E2.6/E2.8 验收。

仍适用现有 `mode: local_tasks`、`local_conversation: true`、`local_memory: true`、获准配置档案，以及精确当前 Gateway 支持的 LOCAL 会话门控。其他档案、远程和模型入口仍被拒绝。没有自动捕获、重放、丢弃、提供者切换、REST 变更、来源查询或通用规范记录来源追溯扩展。

## 发现、检查，然后明确操作

```text
/personal-memory source-discover
/personal-memory --json source-discover --state all --limit 20
/personal-memory source-discover --state accepted --consumer-id reviewed
```

默认筛选为 `pending`。显式 `--state` 值为 `pending`、`accepted`、`discarded` 和 `all`；`--consumer-id` 是可选的精确筛选。消费者格式不变：以小写字母开头，后续为小写字母、数字、`_`、`.` 或 `-`，最多 64 个字符。规范存储缺失时返回 `memory_store_missing`，而非成功的空结果。仅现有存储的只读打开会拒绝旧模式，不迁移，也绝不打开原生文本。

每个条目包含 `query.request_id` 和规范化的 `query.expected_digest`、消费者 ID、来源序号、历史决策状态、历史已接受记录回执或 null、独立的当前记录 ID/修订/状态/过期元数据或 null，以及抑制状态。不包含规范或来源文本、主题、会话标签、来源身份、指纹或原生来源信息。这些请求身份和记录标识仍需私密处理。

使用返回的查询调用现有精确键命令：

```text
/personal-memory source-status --expected-digest=DIGEST -- REQUEST_KEY
/personal-memory source-discard --expected-digest=DIGEST -- REQUEST_KEY
```

人类可读输出为每个条目提供安全引用的精确状态命令，包括以 `-` 开头的键。发现不会发出自动丢弃操作，也不会重复写入。明确丢弃未解决的待处理槽位前，应先检查当前决策。丢弃不能撤销已接受记录；规范遗忘仍是该用途的操作。精确键操作在自身执行时重新检查身份和状态，不把发现令牌当作授权。

终态决策是历史信息。已接受回执仍可能描述修订 1 和 `active`，而当前元数据已经报告更正、过期或终态遗忘。待处理决策不会自动过期。来源丢失不会删除决策、恢复规范载荷或放松抑制。[96](96-retained-source-acceptance-zh.md)、[98](98-observed-source-retention-zh.md) 和 [104](104-retained-source-expiry-zh.md) 中现有来源生命周期、来源游标、抑制、过期、重打包和重试语义保持不变。

## 有界快照防护分页

默认页大小为 20，`limit` 范围为 1 至 50。现有存储上限仍为 1,000 个决策和 64 个消费者。按 `(consumer_id, source_sequence)` 升序排列，由 `order: consumer_id_source_sequence` 标识。页面公开 `total`、`offset`、`next_offset`、`snapshot`、`evaluated_at`、命名空间和规范化筛选。紧凑 JSON 数据预算为 65,536 个字符；字段和条目边界独立适用。这不是模型 token 预算。

首个请求使用偏移零。继续时保留筛选和页大小，使用返回的 `next_offset` 与 `snapshot`：

```text
/personal-memory source-discover --state all --limit 20 --offset 20 --expected-snapshot HASH
```

将 `20` 和 `HASH` 替换为实际返回的下一偏移与令牌；人类可读输出会打印精确下一页命令。偏移必须为页大小的非负整数倍，不大于 1,000，非零偏移必须位于当前结果集内。非零偏移需要有效的预期快照。耗尽页面的 `next_offset` 为 null；空的首页有效。没有静默重启、回退或游标推进。

摘要绑定命名空间、筛选、排序、页大小，以及**所有**保留决策的有界摘要，包括当前修订/状态/过期和抑制。即使在选定筛选之外，同一命名空间保留决策的其他变化也可能保守地使后续分页失效。暂存、接受、丢弃、规范更正/遗忘及相关过期变化会使旧页面以 `source_discovery_changed` 失效。评估的墙上时钟时间不参与摘要，因此仅经过数秒不会使页面失效。保持逻辑元数据的重打包会保持令牌；换到另一命名空间则不会。

令牌仅用于比较读取快照。它不是授权、预留、跨存储事务、来源可用性证明或针对未来写入的屏障。发现和缺失仅描述检查时的快照：尚未观察到的写入者仍可能稍后提交。不要仅因未发现某次不确定尝试，就替换其请求键。发现变化时，应从偏移零重新开始，并在操作前检查新结果。

## SDK 与只读契约

`source_discover` 要求新的可选 `retained_source_discovery` 能力及 `explicit_records`。不会假定现有适配器已实现发现功能，现有适配器仍兼容。SDK 请求使用带下划线的命令字段名，默认值为 `{state: pending, consumer_id: null, limit: 20, offset: 0, expected_snapshot: null}`。未知字段、无效类型、不安全边界和缺失的续页令牌在派发前被拒绝。即使已声明该能力，已激活会话模型绑定也会在派发前被拒绝。

严格结果验证检查精确字段、命名空间绑定、筛选、分页算术、条目顺序和唯一性、历史回执关系、当前元数据、抑制一致性及输出边界。畸形回复产生 `invalid_result`；意外读取失败被脱敏为 `backend_failure`，不是缺失的证据。`source_discovery_changed` 和 `invalid_cursor` 保持为显式拒绝代码。经过审查的 Python 适配器是受信任代码；验证不是沙箱，也不能证明不诚实的适配器没有写入。

SQLite 操作使用一个读取事务、现有有界规范/保留元数据完整性检查，以及有界 SQL 字符串投影。不进行创建、迁移、载荷验证读取、来源/原生存储打开、规范变更或游标推进。原生路径使用仅现有存储的只读打开器。SDK 构造保留现有有界 `export` 绑定准入，它可能读取规范载荷：仅元数据保证适用于发现操作，**而非整个 SDK 生命周期**。未引入替代 SDK 初始化方式或模式变更。

## 验证与限制

合成测试覆盖直至 1,000 决策上限的精确分页边界、筛选和令牌篡改、命名空间绑定、独立连接变化、跨越过期边界、畸形/超大元数据和 SDK 回复、旧模式拒绝、缺失存储、安全命令引用，以及拒绝载荷读取和写入的 SQL 授权器。新进程测试在正常/中断重打包前后发现未知身份，然后检查并明确丢弃待处理决策，验证精确来源不会复活。

原生契约针对 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 运行，使用合成档案，不调用模型或提供者。覆盖禁用/其他档案/远程准入、真实来源丢失和重新加载恢复、明确丢弃待处理决策，以及人类可读/JSON 入口。固定版本主机设置见[开发检查](../README-zh.md#开发验证)。聚焦套件包括 `test_retained_source_discovery.py`、`test_source_discovery_recovery.py`、`test_source_discovery_commands.py` 和 `tests/contracts/test_source_discovery.py`。精确源码的已执行检查、独立审查和打包证据归属 PR；仅有测试实现不代表生产验收。冻结的召回夹具及语义保持不变。
