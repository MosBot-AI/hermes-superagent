# 86. 带停写栅栏的本地记忆重整

[English](86-local-memory-maintenance.md) | 简体中文

## 功能范围

这个仅供操作员使用的流程会压缩**当前**内置 SQLite 记忆库的一致副本，验证其逻辑内容完全相同，再保留原文件并切换。持久 journal 支持中断后的显式恢复。它是同一配置档案的存储维护，不是历史快照恢复、灾难恢复、跨配置档案迁移、schema 转换或通用适配器迁移。

[已有快照命令](79-local-memory-snapshots-zh.md)仍为历史查看，保持 `restorable: false`。维护不接受快照名称、任意源/目标路径或外部数据。当前源缺失或损坏时，不能用旧快照重建。此限制防止旧备份复活后续已更正或遗忘的记录。

## 部署前提

**安装这个支持协调锁的版本之前，必须停止旧版 runtime。** 旧版闲置 SQLite 句柄不认识新协调文件，rename 后仍可能写入旧 inode。SQLite 事务和这段 Python 代码都不能证明这些句柄已经消失。保证仅覆盖更新后的受控插件入口，不包括旧二进制、任意 SQL 客户端或恶意同 UID 代码。这不是身份认证或沙箱。

更新后的写入和只读 opener 在完整连接生命周期内持有共享锁，包括跨多个事务的投影/编辑操作。索引维护及实时快照创建也参与协调。重整获取独占锁，等待有界。固定私有锁 inode 永久保留：切勿通过删除或替换它来解除竞争。现有存储的只读 opener 可以创建该协调文件，但不会创建或迁移数据库。

## 操作流程

使用现有可信本地会话及通常的 `local_tasks`、`local_conversation`、`local_memory` 开关。这些命令不是模型工具或远端 owner 访问。配置和会话准入先于存储操作。

```text
/personal-memory maintenance-preview
/personal-memory maintenance-prepare repack-1 --expected-watermark 42
/personal-memory maintenance-status repack-1
/personal-memory maintenance-commit repack-1
```

应使用 preview 实际返回的 watermark，而不是示例中的 `42`。Prepare 在独占访问下再次检查它。Watermark 改变时会拒绝，不会静默选择更新的源。名称由 1–64 个 ASCII 字母/数字/下划线/连字符组成，以字母或数字开头。

Prepare 创建固定私有暂存数据库，复制当前一致源并运行 SQLite `VACUUM`。精确 schema 及全部表值必须一致，包括规范记录、事件、持久回执、终止性墓碑、待审候选和来源抑制。重整不会改写事实、重置容量、擦除墓碑或使旧 request ID 变成新操作。文件大小不保证缩小。

存在待处理 journal 后，普通受控记忆读取/写入、实时快照及索引维护均拒绝。此状态跨进程重启保留。Status 只显示元数据。历史快照查看仍可用，并保留原有历史内容警告。

Commit 重新验证源/暂存文件身份及摘要。它将源保留在固定私有 `maintenance/NAME.old.sqlite3`，再将已验证暂存库设为实时存储。先记录完成，再清除 pending 防护。这是特定受控切换，不是通用覆盖/导入操作。它不会恢复或重新填充外部 Markdown/编辑器文件、切换 provider、复制凭据或改变 owner 权限。

## 中断及恢复

```text
/personal-memory maintenance-status repack-1
/personal-memory maintenance-recover repack-1
```

复用同一名称。恢复会完成已记录的意图；没有 rollback 命令。`preparing` journal 仅能从未变化的源重建它已记录的非权威暂存 inode。`prepared`/`switching` journal 只接受精确预期的源/暂存/保留旧库布局。字节、身份、namespace、sidecar 或 journal 字段异常时会拒绝，不根据时间戳或哪个文件看起来更新来猜测。

完成状态记录且普通访问恢复后，新库可能发生后续更正/遗忘。重复 commit/recover 只返回历史操作元数据，不替换或回滚这些新写入。不要把该回执当作当前存储的新检查结果。

`maintenance_outcome_unknown` 表示效果可能已经存在。应查看同一操作，不要自动换一个名称重试。首次 journal 发布前崩溃可能留下未归属的私有暂存文件。系统不会据此推测归属或自动删除；名称冲突会拒绝，需要单独核实后的离线清理。原子 journal 发布同样可能留下私有孤立临时文件；后续操作不会采纳它。损坏或无法解释的 pending 状态也会继续阻断。

## 隐私及限制

原数据库以明文保留。以后在新实时存储中遗忘，不会擦除保留旧文件、历史快照、导出或已交付数据。重整不保证物理擦除，也不自动清理、上传或共享。名称/元数据及命令可能进入宿主历史。

要求私有所有权、严格权限、无符号链接、单链接普通文件及独立 DELETE-journal 格式。沿用 128 MiB 和协作式 30 秒界限；fsync 等内核文件系统调用不能被强制中断。检查时原始 hash 描述符保持打开直至 SQLite 关闭，避免提前释放 POSIX 记录锁。获取协调锁另有有限等待。

## 证据及剩余范围

测试在合成配置档案上覆盖进程竞争、中断窗口、持久 pending 防护、精确恢复、相同请求回执、终止性遗忘、危险路径，以及原生准入/模型工具拒绝。进程退出测试及目录 fsync 顺序检查不模拟物理断电，也不认证所有文件系统。不使用实际用户存储、付费模型或外部数据接收方。测试通过不是部署证据。

最终合并验证后，仅可据此完成有界维护包 [#106](https://github.com/MosBot-AI/hermes-superagent/issues/106)。更广的 [#43](https://github.com/MosBot-AI/hermes-superagent/issues/43) 和 [#46](https://github.com/MosBot-AI/hermes-superagent/issues/46) 仍保留历史恢复、远程/多类型契约、适配器切换及原生生命周期门禁。共享客户端 REST 契约不变。
