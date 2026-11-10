# 79. 显式一致的本地记忆快照

[English](79-local-memory-snapshots.md) | 简体中文

## 操作者工作流

```text
/personal-memory snapshot-create before-change
/personal-memory snapshot-inspect before-change
/personal-memory --json snapshot-inspect before-change
```

这些显式原生本地命令需要已有 `mode: local_tasks`、`local_conversation: true`、`local_memory: true` 配置及当前可信 profile/session 准入。它们不是模型工具、自动导出、remote-owner 访问或新 provider。停用/外部来源在快照存储前拒绝。加载/help 不创建数据库。本 #44 切片不完成一般导入/迁移或来源级抑制。

名称为 1–64 个 ASCII 字母/数字/下划线/连字符，以字母/数字开头。唯一目标是当前 profile 私密 plugin-data 目录下的 `memory/snapshots/NAME.sqlite3`。不提供任意路径、覆盖、上传、列出/删除命令或自动清理。同名已存在则拒绝；创建结果不确定后应检查该名称，不要以为新名称等同于同一次重试。

Create 返回 schema version、namespace、事件水位、record/active/tombstone 计数、字节长度及 SHA-256。`active_records` 统计 status-active 行，包括已过期但尚未遗忘的记录；不等于当前可召回数量。Inspect 从指定历史文件返回同样的元数据，不返回私密记录正文。它可在 live records.sqlite3 缺失时工作，从不创建/迁移该存储，并拒绝不同 profile namespace 的快照。

## 一致性与隐私

支持的记忆存储使用当前精确 schema 和 DELETE journal。创建在 SQLite 读事务内验证，然后从同一快照使用 SQLite backup API。并发纠正或遗忘可以随后完成；副本保留较早一致的 record/tombstone/receipt/event 状态，而不是多个独立实时页混合。源读锁可能推迟并发 writer。原有 `export` 命令仍是有界实时页面，不是此一致性产物。

**快照是明文，并保留私密历史内容。** 它包括 canonical records、待审核模型候选、source/session 元数据、receipts 和维护元数据。后续纠正、遗忘或过期记录清理不会擦除此副本、以前的导出、已打开描述符或文件系统备份。显式命令只授权此本地副本，不授权分享。它不改变到期时间，也不安装/选择 memory.provider。

只复制 SQLite 数据库。不复制 `records.md`、`edit.md`、原生 MEMORY.md/USER.md、凭据或其他 profile 文件。已存 projection/draft 元数据是历史状态，不表示这些外部文件存在于快照中。`restorable: false` 是有意设置：没有 restore/import/copy-back 路径、authority 转移或自动重新激活。不要用此产物替换运行中的 live 数据库。

## 文件系统与失败契约

已有目录和文件须满足原生 POSIX 所有权/隐私检查，不允许 symlink，且文件是单链接 regular file；snapshots 目录私密，新文件权限为 `0600`。拒绝源及已发布快照 sidecar。对 live 源的检查不会打开/关闭 raw descriptor，因为那可能丢弃其他同进程 SQLite 连接的 POSIX 锁。不支持的 WAL 源通过 SQLite 验证拒绝；打开被外部修改的此类文件可能在拒绝前创建 WAL/SHM sidecar。这不是 VFS 或恶意同 UID 文件系统沙箱。

副本上限为 128 MiB，采用协作式 30 秒 deadline：完整性扫描前检查源大小，backup/hash 期间检查进度/时间。该 deadline 不会强制中断 fsync 等阻塞文件系统调用。Inspect 在打开已发布快照前拒绝非独立 SQLite header。Hash descriptor 从 SQLite 事务前保持打开，直至 SQLite 关闭后才关闭，避免 hash 丢弃读锁。Inode/size 检查可发现普通替换；恶意同 UID 竞争不在保证范围内。Digest 标识字节，不是认证作者或安全恢复证明。

发布使用私密随机 staging 文件，验证/hash 已复制数据库并 fsync，然后通过不可覆盖的 hardlink 创建最终名称，删除 staging 名称并 fsync 目录。已发布文件/后期目录同步失败返回 `snapshot_outcome_uncertain`；目标可能存在，清理不宣称将其回滚。清理失败为尽力而为，不以文件系统细节覆盖脱敏结果。

真实进程在 link 前崩溃可留下孤立 staging 文件且没有目标。在 link 后、staging unlink 前崩溃可留下两个 hardlink。Inspect 拒绝此不安全状态，不自动删除或修复。操作者须先验证匹配且归属正确的 inode，再单独离线清理，不能绕过 hardlink 门禁。之后的 create 不复用或采用未知 staging 文件。

## 证据

测试覆盖元数据/canonical 一致性、遗忘后的历史保留、namespace/schema/config/source 拒绝、路径和权限故障、大小/时间上限、发布后失败、持久 hardlink alias、link 前后真实进程退出、并发遗忘，以及 inspect hash 期间不能提交的独立进程 writer。原生契约在记录的兼容性 pin 上执行真实可信本地命令、停用/外部/远程拒绝及模型工具排除。不使用真实模型、凭据、live provider、用户 profile 或外部传输。这是合成验证，不是部署或用户验收。
