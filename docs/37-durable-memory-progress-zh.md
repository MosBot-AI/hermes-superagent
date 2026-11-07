# 37. 持久化本地记忆进度

[English](37-durable-memory-progress.md) | 简体中文

状态：已实现有界事件元数据读取和持久化内部消费者游标，为后续本地投影与生命周期 worker 提供重启/重试基础。没有实现后台 worker、原生 MemoryProvider 桥接或成功的原生压缩前 checkpoint。后端仍将 `checkpoint` 声明为不支持。

实现更新：[39](39-local-memory-checkpoints-zh.md) 新增显式元数据检查点，验证事件与记录的关联并查询是否过时，仍不满足原生检查点。其 schema-v4 迁移接续本页记载的 v3 存储阶段。

## 1. 读取元数据变更流

启用现有[本地记忆配置](31-explicit-local-memory-zh.md)后，可信原生 LOCAL 会话可以读取：

```text
/personal-memory changes --after-sequence 0 --limit 20
/personal-memory changes --after-sequence 20 --through-sequence 42 --limit 20
```

应使用首次响应返回的真实序号，而不是照抄示例数字。命令仅返回已提交的事件序号、记录 ID、记录 revision 和操作（`remember`、`correct`、`forget`）。不返回历史或当前内容、主题、会话/来源标签、请求键或内容摘要。旧 `remember` 事件是历史元数据，不表示记录现在仍然有效。无法从此流重建已遗忘内容。ID 和操作元数据仍可能属于个人信息，并进入正常宿主命令历史。

`limit` 默认为 20，允许 1–50。`after_sequence` 默认零；`through_sequence` 默认当前已提交事件水位。即使其他写入继续发生，后续分页仍可沿用响应中的上界。`next_sequence` 是最后返回的序号，空页则保持原下界。`has_more` 只针对该上界。后续页的 `current_watermark` 可能更高。每页事件和水位在同一事务内读取；此流不会冻结内容正文快照。

负数、非整数、未来、反向或不存在的非零序号锚点都会明确失败。保留的事件流目前不清理，因此 `retention_floor` 为零。记录/事件配额不变。namespace/profile 归属由现有存储打开器绑定，不接受调用方选择的路径或模型参数。此操作未加入模型工具 schema。

## 2. 内部消费者游标契约

可信本地代码可通过 `MemoryService.execute("consumer_get", {"consumer_id": "projection"})` 查询进度。未知消费者返回 revision/序号零及 `registered: false`，不创建状态。ID 是有界小写 slug，不是人的身份、授权或原生会话名。没有游标写入 slash 命令、模型操作或注册的后台 hook。

内部推进请求示例：

```json
{"consumer_id":"projection","expected_revision":0,"through_sequence":42,"request_id":"projection-pass-1"}
```

只有消费者完成其打算确认的工作后，才应将其提交给 `consumer_advance`。revision 为零时创建游标；后续变更必须匹配当前 revision，并严格增加序号。序号必须为零或真实已提交的记录事件序号，不能处于未来。状态更新和纯元数据回执在同一个 `BEGIN IMMEDIATE` 事务内提交，沿用存储既有持久化设置。即使重放旧推进，也要求绑定操作员来源的后端；绑定模型来源的后端在查询回执前就被拒绝。

相同请求键和内容会返回原始历史回执。同一键换内容会冲突。重放旧回执不会倒退当前游标。消费者键与记忆记录变更键使用独立回执空间。结果不确定时，应使用相同键和 `consumer_get` 核实；仅有失败响应不能证明没有提交。不要盲目换新键或重置进度。

每个存储最多 32 个消费者和 10,000 条游标变更回执。配额耗尽后仍可精确重试。游标配额耗尽不会阻止遵循各自独立配额的权威记录纠正或终结遗忘。本切片不提供游标删除、清理或自动重置。

## 3. 游标不能证明什么

游标明确标注为 `caller_reported_local_record_progress_not_native_checkpoint`。存储只证明进度记录及回执已经持久化提交，不能证明调用方读完全部事件、成功发布文件、完成外部动作、保存原生对话、保留待审批事项或核实来源证据。

消费者不能跳过未处理工作。未来的投影发布器仍须针对当前记录 revision 和 tombstone 单独建立输出栅栏，再协调发布/恢复与进度确认。推进一个数值不能使过时输出变得安全。本切片没有与远程系统或生成文件共享的原子事务，也不能从游标恢复权限。

完整[记忆生命周期方案](30-pluggable-memory-contracts-zh.md)仍要求经过验证的来源覆盖、显式桥接选择、允许的运行模式、有界关闭和真实原生 checkpoint-v2 契约。严格压缩必须保持不可用，不能把这些游标当成该保证。现有原生 provider、配置和模型路由不变，不引入自动外传。

## 4. 存储升级与兼容性

精确自有记忆数据库升级至 schema v3，增加 `consumer_cursors` 和 `consumer_receipts`。v2 升级会原子增加这两张表；v1 升级先执行既有来源迁移，再在同一事务内增加两表。在写锁下重新检查 namespace/application/schema。未知、被修改或外来 schema 会失败关闭。创建任一进度表失败会回滚整次升级，包括 v1 记录表重建。

保留原有记录 ID、revision、最近来源标签、tombstone、顺序高水位、事件行及原始回执精确字节/digest。首次只读打开也可能执行升级。升级前备份私有插件数据，旧版本会拒绝 v3。没有降级或可移植恢复协议。不要用旧备份覆盖当前数据，导致已遗忘内容复活或已处理事件进度倒退。

可选描述符能力为 `metadata_changes` 和 `durable_consumer_cursor`。推进操作的服务准入还要求持久写入、CAS 和幂等能力；调用后端前校验普通分页限制。缺少能力会失败，不自动回退。描述符 API 仍为 v1，存储 schema 独立为 v3。这不是完整的公开适配器 SDK。

## 5. 验证与剩余工作

合成测试覆盖有界/固定上界分页、删除安全元数据、精确重试、过期/倒退/未来拒绝、独立消费者、配额、相同键和竞争键并发、事务回滚、不确定提交恢复、快照竞争及精确 v1/v2 迁移。原生契约验证真实 slash 分发器、owner 准入、provider 配置不变，并通过四个禁止网络连接的独立进程，验证纠正/遗忘及旧回执重放后游标进度持久保留。已激活模型工具拒绝新增内部操作。

未使用真实模型、外部账户、socket listener、定时任务或生产 profile。E2.7 增加本地持久化基础，原生生命周期 E2.8、checkpoint 证据覆盖、投影栅栏、完整导出/导入及 E2.9 恢复验收仍未完成。
