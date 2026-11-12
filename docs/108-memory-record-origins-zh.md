# 108. 检查记忆记录来源

[English](108-memory-record-origins.md) | 简体中文

## 已实现边界

[Issue #157](https://github.com/MosBot-AI/hermes-superagent/issues/157) 新增显式 LOCAL `origin RECORD_ID` 检查与可选 API-v1 `record_origin` 能力。这是有界的本地操作者契约，不是共享公共 REST API 的扩展、自动摄取、远程访问、模型工具，也不代表完整 E2.6/E2.8 验收。合成检查不等于部署或真实个人数据验收。

```text
/personal-memory origin RECORD_ID
/personal-memory --json origin RECORD_ID
```

使用现有记录操作返回的规范 UUID 记录 ID。现有本地记忆配置、获准配置目录、当前 Gateway 支持的 LOCAL 会话和维护隔离仍然适用。禁用、外部会话、远程及模型路径仍被拒绝。原生命令使用托管的仅现有存储只读打开器，不创建、迁移或执行 SDK 导出准入。缺失存储返回 `memory_store_missing`；缺失记录返回 `not_found`。查询字段或 ID 无效时返回 `invalid_request`。

## 精确元数据契约

SDK 请求仅包含 `{record_id}`。结果为 `{data, replayed: false}`。data 恰好包含以下字段：

- `namespace_id`、请求的 `record_id` 与规范 UTC 秒级 `evaluated_at` 绑定本次观察。
- `current` 包含 `record_id`、`revision`、`status`、`expires_at` 和 `expired`。到期状态按同一评估秒计算；活动记录恰好到达期限时已到期。已遗忘记录的到期时间为 null，且 `expired: false`。
- 活动记录的 `current_editing_route` 为 `explicit_local_operator` 或 `activated_session_model`；已遗忘记录为 null。这表示最近编辑路径，不是原始作者身份。
- `origin` 恰好采用下列一种变体。
- 固定 `scope` 为 `historical_acceptance_and_current_metadata_at_read_snapshot`；固定 `notice` 解释下述限制。这些值会被校验，不是适配器自行声明的主张。

| 来源类型 | 附加字段 | 证据限制 |
| --- | --- | --- |
| `observed_native_snapshot` | `role`、`consumer_id`、`source_sequence`、`acceptance`、`suppressed` | 显式接受的观察快照中保存的 user/assistant 角色。 |
| `retained_native_snapshot` | 同上 | 有回执支持的保留快照中保存的 user/assistant 角色；不重新查询原生回执。 |
| `reviewed_candidate` | `candidate_id`、`acceptance`、`suppressed` | 仅历史审阅接受信息；不会重建已擦除的引用、来源和会话字段。 |
| `unavailable` | `reason: no_durable_lineage` | 没有持久谱系链接的现有记录，包括直接记录和缺少此链接的历史候选。 |

`acceptance` 仅包含 `record_id`、`revision: 1`、`status: active` 和 `event_sequence`。更正、到期或遗忘后，它仍是历史信息。消费者 ID 与来源序号是有界的本地决策引用，不是权限。不会根据当前编辑路径推断原始来源。存储的角色标签与基于哈希的关联不能证明作者身份、真实性、认可或许可。

抑制表示阻止完全相同来源再次进入，并不一定表示这条记录已被遗忘：更正也会抑制再次进入，共享同一来源的另一条已接受记录仍可能保持活动。查询不会打开原始来源或断言其可用性。来源删除不会抹去独立保留的历史接受信息、重建已遗忘载荷或授权重试写入。

结果限制为紧凑 JSON data 的 4,096 个 UTF-8 字节。它排除规范/来源内容、主题、引用、路径、会话标签/引用、来源/请求指纹、轮次哈希和原始来源身份对象。原生回执及观察 ID 被有意省略。记录和候选标识符仍属于应私密处理的关联元数据。

## 完整性与快照规则

延迟开启的规范只读事务先建立 SQLite 快照，再采样到期评估时间。命名空间/模式、规范记录/事件/回执关系、保留决策和现有候选谱系/抑制锚点在同一快照内一致校验。有界 SQL 投影在 JSON 解析前拒绝超大值；重复 JSON 键和格式错误的历史回执均失败关闭。候选接受必须匹配规范 `candidate.accept.<candidate_id>` 回执及当前记录关系。待处理或已丢弃候选不能支持已接受来源。

此操作从不调用面向载荷的 `memory_sources.validate`、候选修改/清理分发、原生来源打开器或游标推进。它只读取有界元数据（含历史回执），不执行规范写入。无关待处理候选的载荷不会被加载。现有模式和其他操作校验器保持不变。

悬空、冲突或双重谱系，格式错误/超大/重复键回执以及无法验证的关系会产生后端 `storage_corrupt`，不会任意优选某个来源或成功返回 `unavailable`。缺少谱系不自动等于损坏：较早的已接受候选可能合法地没有持久谱系链接。缺失字段不会被重建。事务结束后读取结果可能立即过时。

## 可选 SDK 与一致性检查

`record_origin` 要求可选 `record_origin` 加 `explicit_records`。仅支持 CRUD 的现有适配器仍兼容，并在分发前收到 `capability_unavailable`。即使声明该能力，激活模型的 SDK 绑定也会在后端分发前以 `source_scope_required` 拒绝。严格结果校验覆盖精确字段、命名空间/请求绑定、变体互斥、当前到期/状态/路径、历史接受及输出界限。无效回复返回 `invalid_result`；非预期后端失败返回已脱敏 `backend_failure`，不表示缺失。原生存储损坏保留明确错误。

SDK 构造/导出准入可能读取载荷。仅元数据保证适用于此操作与原生只读路径，**不适用于整个 SDK 生命周期**。经审阅的适配器仍是受信任 Python 代码；校验不是沙箱，也不能证明诚实只读实现。没有动态加载、工厂替换、后端切换、恢复或模式变更。

`memory_conformance.run_record_origin_conformance(factory, isolated_synthetic=True)` 使用调用方拥有的一个全新合成存储。它有意创建、更正并遗忘一条直接记录，重新打开存储，验证不可用谱系及不会复活载荷的历史重试。来源家族的溯源/损坏需适配器专用夹具；通用检查器不要求可选来源摄取。内置存储和独立测试元数据适配器均运行该检查器。不要将这个会写入的一致性检查器指向真实配置目录。

## 验证与剩余门槛

聚焦单元套件覆盖 user/assistant 观察、保留回执、已审阅候选、直接/旧记录缺少谱系、两种路径编辑、精确到期、遗忘、历史重试、并发修改快照、SQL 载荷/写入拒绝、损坏及错误 SDK 回复。新进程测试在正常/中断规范压实前后检查来源。原生契约针对 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 覆盖人类/JSON 输出、准入、来源不可用、重启及托管不创建/不迁移读取器。

运行时文件声明和经审阅的检查点来源实验绑定包含新模块，不修改宿主补丁或削弱哈希守卫。精确提交的完整单元/原生/提案/运行时检查、独立审阅与合并后主分支 CI 证据由 PR 记录。不新增模型调用、部署、公共 REST 变更、召回语义变更或冻结召回夹具/报告修改。父任务 #43/#45/#46 的验收仍未完成。
