# 26. 待确认身份登记与策略持久化

[English](26-pending-enrollment-policy.md) | 简体中文

## 1. 已交付范围

本切片实现的是**未接入运行入口的管理记录持久化核心**，不是可用的 owner 登记产品。它保存拟议的 actor/receiver 映射和精确的拟议读取范围，提供事务版本、终止性撤销和最小审计记录。状态仅有 `pending` 和 `revoked`。没有激活、挑战验证、会话绑定、`VerifiedReadContext` 签发、`ReadGrant` 签发或受保护数据读取器。

`open_enrollment_store(bound_home, enabled=False)` 默认在导入宿主或访问文件系统之前拒绝。只有精确布尔值 `enabled=True` 才允许内部存储访问。没有 manifest 设置、原生 CLI、斜杠命令、模型工具、HTTP 路由或回调调用它。加载插件、使用 `local_tasks` 或启用规划蓝图都不会启用此存储。即使已有拟议记录，现有 `/personal-access` 诊断仍拒绝访问。

这推进了 E1.1/E1.2/E1.4/E1.5 的持久化前置工作，不表示 E1、主 Bot 绑定或 M1 完成。见 [18](18-owner-entry-and-read-authorization-zh.md) 和剩余的[宿主准入门禁](23-host-command-context-experiment-zh.md)。

后续[带栅栏协调器](27-fenced-read-admission-zh.md)现已提供内部事务/快照排序契约。其 authority/资源 adapter 在生产中仍不可用，本待确认存储仍不能激活或认证记录。

## 2. 数据与信任边界

存储使用原生 profile 的 `plugin-data/hermes-personal-agent` 目录下独立的 `enrollment.sqlite3`。它不读取、接管或修改 `tasks.sqlite3`。每条记录均以完整的 `(owner_id, profile_id, enrollment_id)` 元组定位。这些字符串是**拟议的管理标签**，不是经过认证的身份。profile 目录、OS UID、数据库行、类型注解或调用者提供的布尔值均不能证明所有权。

创建要求不可变的 `transport_id`、`transport_receiver_id` 和 `principal_id`。这些只是等待未来可信登记流程验证的预期值；此代码不会核验传输来源。修改它们必须创建新的拟议记录。这里不声称保证 active binding 唯一性，也没有自动发现 owner 或首个发送者自动登记。

初始 schema 包含两张表：

- `enrollments`：精确身份标签、状态、`enrollment_revision`、`policy_revision`、记录内 `epoch` 和拟议范围。
- `events`：带范围的记录 ID、操作及结果版本/epoch。不包含 actor/receiver ID、范围正文、任务 ID、任意文本、凭据或原始异常。这些路由标签仍是私人元数据，不是匿名审计数据。

文件没有加密或防篡改能力。记录 ID 不是秘密或 bearer capability。审计是本地事务历史，不是经过认证的墙钟日志或外部新鲜度权威。

## 3. 内部契约

`EnrollmentStore(connection)` 要求专用的标准 SQLite 连接。调用者负责连接和访问控制。`initialize()` 只创建空数据库或验证精确的自有 schema。`run(operation, payload)` 仅接受以下操作及精确字段：

| 操作 | 必需字段 | 结果 |
|---|---|---|
| `create` | 带范围的记录 ID、不可变的预期身份字段、`scope` | 新的 `pending` 快照，登记/策略版本为 `1`，epoch 为 `0` |
| `get` | 带范围的记录 ID | 当前管理快照，包含撤销状态 |
| `set_policy` | 带范围的记录 ID、`expected_revision`、`expected_enrollment_revision`、`scope` | 替换拟议范围；递增策略版本和 epoch |
| `revoke` | 带范围的记录 ID、两个预期版本 | 终止性 `revoked`；递增登记版本和 epoch |

`expected_revision` 指**策略版本**，不是登记版本。两个版本都必须匹配。即使成功替换为相同范围，也递增策略版本和 epoch。更新不能提供身份字段。缺失/未知字段、作为版本的布尔值、不支持的范围和整数溢出都会被拒绝。所有 ID 使用内部授权求值器限定长度的不透明 ASCII 语法。

范围恰好包含 `operation`、`target`、`resource_ids` 和 `data_scope`。支持的形状复用纯读取求值器：

- `personal.tasks.read` / `own_inbox` / 空资源元组 / `tasks.summary`。
- `personal.tasks.read` / `exact_tasks` / 非空且唯一的资源元组 / `tasks.summary`。
- `personal.primary_binding.inspect` / `primary_binding` / 空资源元组 / `primary_binding.metadata`。

这些是**拟议范围**，不是 grant。`exact_tasks` 提议不证明任务 ID 的所有权；`own_inbox` 提议不接管本地任务。没有转为实际 grant 的功能。未来准入服务必须独立确立所有身份、资源所有权、会话和新鲜度事实。

## 4. 事务、重试与撤销

每个操作，包括 `get`，均使用 `BEGIN IMMEDIATE`，重新验证 main/temp schema 的精确归属，并提交一致结果。变更及其审计事件一同提交。审计插入失败、中断或被拒更新会回滚整个事务。独立连接上的竞争修改串行化。不支持并发共享一个连接；调用者已开启的事务会被拒绝，但不会被本模块回滚。

提交是**本管理状态变更**的线性化点，不是授权准入。通过受保护的持久存储 opener，成功撤销在方法返回前提交，持久性受 SQLite/文件系统保证约束；调用者传入的内存连接不是持久存储。另一次使用旧版本的策略变更会冲突；对已撤销记录使用当前版本也会被拒绝。没有撤销撤销、删除或重新激活 API。替代提议使用新 ID，仍为 pending。

重试仅依赖 CAS，没有重放回执。调用者在创建前选择稳定的 enrollment ID。结果不确定时，使用相同 owner/profile/ID 读取当前状态并对账；不要盲目创建新 ID 或重放过时修改。重复创建返回 `already_exists`，不会表现为产生了新的权限。返回快照在提交后可能立即过时，不能重复用作授权。

epoch 仅在**同一数据库历史中的一条记录内**单调增长。它不是宿主实例栅栏、profile 世代、恢复检测器或分布式租约。复制或恢复数据库会复制旧版本。重启、恢复或克隆均不能将这些记录视为经过认证的 active authority。这里的撤销仅取消提议：没有实际请求、已签发 grant、任务读取或远端 effect 可供取消。

## 5. 存储防护与限制

内部 opener 使用固定宿主的公开 profile resolver 和 plugin-data helper，在目录解析前后验证绑定的绝对 profile。它拒绝 profile 变化、符号链接存储目录、其他用户可写的目录、不支持的平台，以及不安全的主数据库或 SQLite sidecar 文件。已有文件必须是普通文件、单一硬链接、归当前 UID 所有，且 group/other 无访问权限。新数据库文件以 `0600` 创建。不自动修复已有权限。

数据库使用回滚日志，并设置 `foreign_keys=ON`、`trusted_schema=OFF` 和 `synchronous=FULL`。已有 WAL 数据库被拒绝而非转换，不绕过 Hermes 的 WAL 兼容门禁。检查精确 application ID、schema 版本、表 SQL，以及不存在临时 schema 对象。外来数据库、任务数据库、意外表/触发器或不支持的版本会被拒绝，不迁移或覆盖。

这些检查降低意外暴露风险。它们不是 OS 沙箱，不能防御恶意同 UID 代码，也不是无竞态目录能力、加密、安全删除或已验证备份系统。既有祖先目录/profile 的可信性及可信本地进程是前提。opener 当前仅支持 POSIX；macOS/Windows 忽略规则不代表支持 Windows 存储。本切片不需要网络、套接字、provider 凭据或 API key。

## 6. 验证

单元覆盖严格字段/范围/类型校验、持久化、owner/profile/ID 隔离、不可变预期身份、独立连接上的 CAS 竞争、计数器耗尽、终止性撤销、外来/异常 schema、调用者事务，以及审计失败/中断回滚。默认门禁测试断言禁用时没有文件系统或宿主解析操作，也没有登记/激活 CLI。

固定 Hermes 契约在临时合成 home 中加载真实目录插件，使用实际公开 profile/storage API，验证持久化重开、不同 profile 中相同拟议 ID 的隔离、过期 profile 路径拒绝、不安全文件/sidecar/目录、外来任务数据库不变、连接关闭，以及保存元数据后诊断仍拒绝。这是原生存储集成证据，**不是实际 Bot 身份或 owner 登记测试**。

本切片通过 654 项单元测试和 301 项固定宿主契约（共 955 项），其中新增 81 项单元用例及 37 项宿主用例。Ruff、类型检查和双语文档检查均通过。这不验证崩溃/掉电恢复或生产登记。

使用兼容性固定的 Hermes checkout 及其 PM 创建的解释器，运行仓库统一 `scripts/check.py`。测试不使用真实身份或密钥。历史受限的身份套接字测试仍未解决，本切片不会重试。没有应用上游补丁。

## 7. 到 owner 摘要的剩余路径

暴露登记流程或任何私人读取之前：

1. 建立实际、当前的入口观察，验证 actor、接收 Bot、路由、会话和单调宿主栅栏；完成 [23](23-host-command-context-experiment-zh.md) 的受支持宿主/IPC 契约。
2. 设计并批准可信 bootstrap authority 和显式登记/挑战流程。本存储中的 pending 标签不能单独授权激活。
3. 定义 active binding、会话过期/替换、当前撤权/栅栏和经过认证的恢复。原生 canonical Primary Bot 选择仍与 transport receiver ID 分离。
4. 显式预览/接管选定的本地任务集合，或迁移到 owner 范围存储。本地任务不会因为位于某 profile 就带有已验证 owner。
5. 为有界、确定性的 `tasks.summary` 实现原子宿主/策略/资源准入，并测试与撤权的排序。调用纯求值器后再独立读取 `TaskStore` 并不足够。
6. 在获得授权的环境验证真实入口，需要时安全连接选定 Bot。确定性摘要不必使用模型 API key；凭据不能弥补缺失的身份契约。

此基础明确停在这些门禁之前。生产状态仍报告 `identity_binding: false`、`protected_reads_enabled: false` 和 `release_gate: blocked`。

## 策略历史检查

`EnrollmentStore.policy_history(key, after_epoch=-1, limit=50)` 是内部管理读取接口，不是 CLI、模型工具、远程路由或认证 API。精确的 owner/profile/enrollment 选择条件仍是调用者负责的标签。接口仅返回操作、epoch、变更后的 enrollment/policy revision，以及当前记录的状态、revision、epoch 水位。它不返回拟定的 actor/receiver ID、scope 内容、资源 ID、凭据或任意事件文本。

初始游标 `-1` 包含 epoch 为零的创建事件。每页允许 1–100 项，返回 `next_after_epoch` 和 `has_more`；终态撤销后仍可读取。超过当前 epoch 的游标会被拒绝。单次事务提供一致的页面和当前水位；分次调用不是冻结快照，可能观察到后续策略变更或撤销。返回的水位仅用于历史检查，不是授权屏障，也不证明外部操作已经停止。

读取器验证精确 schema、当前记录与计数器的关系、当前尾事件，以及包含一条前瞻记录的所选连续区间。所选事件缺失或不一致时失败关闭，SELECT 或 COMMIT 失败也不会返回页面。它不会扫描或认证页面之前的全部历史。通过作用域和 epoch 索引，查询最多获取 `limit + 1` 条页面记录及一条尾记录；接口不执行变更、保留清理或 schema 迁移。本地数据库仍不防篡改，也不能作为恢复或克隆后的新鲜度权威。调用者已有事务会被拒绝，但不会被回滚。

参见 [78. 带栅栏的登记确认流程证据](78-enrollment-ceremony-zh.md)，了解未接线的一次性确认基础和当前 pin 身份边界；生产 owner authority 仍不可用。
