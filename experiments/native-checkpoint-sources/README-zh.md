# 仅供评审的原生检查点来源回执

[English](README.md) | 简体中文

[Issue #125](https://github.com/MosBot-AI/hermes-superagent/issues/125) 为 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上显式请求的所有者原地压缩提出宿主持有的来源回执。此补丁尚未提交上游、安装或启用。交付的 provider 仍为 API v1，生产兼容性固定版本不变，E2.8 仍未完成。参见[设计与边界](../../docs/92-native-checkpoint-sources-zh.md)。

## 内部契约

提议的宿主模块 `hermes_state_checkpoint_sources` 暴露：

- `prepare_source_request(db, session_id, attempt_id, candidates, compacted_messages, *, lock_holder=None)`：针对所选原生会话进行显式只读准备。
- `commit_source_request(db, session_id, request, *, cancelled=None)`：重新验证来源覆盖和 revision，然后在同一原生压缩事务内归档并写入元数据回执。
- `source_receipt_status(db, session_id, attempt_id)`：只读快照检查；检查不会创建尚不存在的回执 schema。

候选使用 `[{role, content, uids: [primary, *absorbed]}]`；压缩输出必须恰好是一条摘要消息 `[{role: "assistant", content: ...}]`，不携带其他消息或额外选项。完整活动扫描最多准入 256 行及 65,536 个正文字符；选定覆盖必须连续。容量为 4,096 条回执及 1,048,576 条来源绑定，不进行淘汰。状态为 `committed_available`、`invalidated_or_unknown` 或 `absent`。提交重放仅报告历史 `committed`，不报告当前可用性。

候选覆盖有意限定为准确的活动普通用户/助手来源，以及受支持的有序用户合并。待持久化输入、未知谱系及不支持的覆盖均被拒绝，不进行猜测。回执不复制会话正文；保留的原文仅存在于原生已归档消息行。永久原生触发器会在除 `display_order` 外的任一来源列发生变化时使元数据回执失效，包括反应变化。同值无操作更新不会使其失效。旧代码的普通原生/SQL 修改仍会触发这些持久触发器；因无关元数据变化而保守报告不可用是可接受的。有限回执容量会拒绝新的准入，而不会淘汰既有历史。

已持久化的 `_compressed_summary` 行不能作为合格来源。调用方仅为单条助手摘要提供 `role` 和 `content`；宿主在新的输出副本上设置 `_compressed_summary=True`，使规范请求在重试之间保持不变。

读取后的准入还将每条原始行中字符串字符数与字节值长度的总和限制为 262,144，完整扫描中的总和限制为 2,097,152。序列化谱系最多为 `1024 * 36 + 2` 个字符；规范请求 JSON 最多为 1,500,000 个字符。这些是读取后的准入限制，不是分配安全保证。

准备不预留来源，也不授权执行。提交准入必须重新检查来源。可选取消谓词适用于提交准入之前，不承诺撤销已提交的事务。返回中断或结果不确定后，应检查同一会话/尝试的回执，不能将异常当作没有发生写入的证明。历史回执不是当前记忆覆盖、模型结果、送达证据或授权授予。

范围仅包含显式所有者原地压缩。不支持会话轮换、worker 压缩、app-server 严格检查点、自动摄取及 provider-v2 启用。这是可信进程内宿主 API，不能隔离恶意代码、直接篡改 schema、手动数据库替换或备份回滚。不会添加并行会话档案、记忆存储、调度器或运行时循环。

## 安全复现

使用独立预配的 Python 3.14 环境，以及准确基础版本的无凭据一次性宿主检出。先评审补丁，再显式应用并暂存：

```sh
git -C "$DISPOSABLE_HOST" apply --check "$ARTIFACT/native-checkpoint-sources.patch"
git -C "$DISPOSABLE_HOST" apply --index "$ARTIFACT/native-checkpoint-sources.patch"
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON" --check-only
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON"
```

运行器核验准确基础版本、已暂存补丁/树、制品源码哈希、未跟踪文件及隐藏索引标志。它不会下载、安装、应用补丁、启动监听器或改变生产固定版本。提案测试使用净化后的环境及临时合成 home。原生回归使用固定宿主的规范 `scripts/run_tests.sh` 及其逐文件进程隔离，并显式指定预配解释器。存在测试不代表测试通过；实际执行计数应记录于经过评审的 manifest。CI 使用独立的一次性宿主作业，不会在运行时包中启用此提案。

`consumer.py` 是显式测试/评审消费者，不是交付的 provider 注册或自动钩子。制品仅包含合成测试证据，没有真实模型调用、凭据、生产 profile 或外部送达检查。源自上游的补丁材料受[保留的许可证](LICENSE.hermes-agent)约束。尚未提交上游或发布。

## 中断的消费者记账

[Issue #127](https://github.com/MosBot-AI/hermes-superagent/issues/127)加入 `recovery.py` 和 `test_recovery.py`。宿主还公开 `source_request_identity(session_id, request)`，这个有界元数据标识辅助函数不访问数据库，也不执行来源准入。`RecoveryJournal(path, host_path, session_id, create=True)` 显式初始化私有日志；重新打开时省略 `create`。`stage` 先于宿主准入，`submit` 显式提交相同的绑定请求，`pending` 有界列出待处理尝试，`reconcile` 在本地历史记账前读取同一宿主回执。日志不保留完整请求、来源或摘要文本。

使用前请阅读[恢复协议与边界](../../docs/93-source-receipt-recovery-zh.md)。回执缺失需要显式重新提供相同请求，不会自动重试。来源可用性是重新读取的观察结果，不由记账保证。两个存储不是原子的，不写入规范记忆或游标。本切片仍是隔离的合成测试入口，不是生产启用。

## 回执绑定的原始来源读取

[Issue #129](https://github.com/MosBot-AI/hermes-superagent/issues/129) 新增显式宿主操作 `read_receipt_sources(db, session_id, attempt_id, expected_receipt_id)` 与只读消费者。回执有效性、精确成员关系及完整原始行共用一个有界 SQLite 读取快照。缺失、失效或不可用结果没有来源载荷；回执哈希不匹配时拒绝，不泄露文本。快照建立后仍可能发生删除，因此返回的历史观察不代表持续可用性或权限。参见[读取协议与上限](../../docs/94-receipt-source-reads-zh.md)。不新增日志载荷、自动读取器、记忆接受、游标或 provider-v2 能力。
