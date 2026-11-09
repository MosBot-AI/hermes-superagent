# 27. 带栅栏的读取准入

[English](27-fenced-read-admission.md) | 简体中文

## 1. 范围与当前可用性

本切片实现默认拒绝的**内部读取协调器**和实际 SQLite 策略/撤权事务守卫。离线 fixture 提供独立确认与资源快照来测试协调过程。仓库**没有**生产身份权威、确认签发器、资源读取器或登记激活流程，也没有把 fixture 认证为真实用户。

没有生产命令、工具、HTTP 路由、manifest 设置或插件回调创建此服务。即使内部使用 `enabled=True`，缺少两个可信 adapter 也不能运行。生产状态及 `/personal-access` 仍保持阻断。pending 记录保持 pending，登记 schema 现为 v2；仅显式初始化会原子迁移精确匹配的 v1，不打开或接管 `tasks.sqlite3`。

这推进 E1.3/E1.4 的读取准入基础，不代表整个 E1 或 M1 门禁完成。[26](26-pending-enrollment-policy-zh.md)介绍拟议策略存储；[23](23-host-command-context-experiment-zh.md)记录尚未解决的宿主身份路径。Python 对象和类型不是身份认证，也不能隔离同一解释器中的恶意代码。

## 2. 内部 API

`ReadAdmissionService(store, host_authority=None, resource_source=None, enabled=False)` 只接受内部可信依赖。`read(key, request, live_handle=...)` 返回不可变的 `TaskSummary` 元组，或抛出脱敏的 `ReadAdmissionError`。不返回授权 token、cursor、generator 或缓存的 allow 决定。

- `key` 必须恰好包含 `owner_id`、`profile_id` 和 `enrollment_id`。它们是选择器，不是证明。
- `request` 为精确的内部 `ReadRequest` 类型。只支持 `personal.tasks.read` / `exact_tasks` / `tasks.summary`，包含 1–32 个唯一不透明 ID。拒绝 `own_inbox`、绑定检查、详情和写入。
- `live_handle` 原样交给可信 authority。协调器不会把 JSON、用户名、profile 路径或 `approved=True` 解析为权限。
- `enabled` 必须精确为 `True` 才会继续。缺少 adapter 或其他取值均在接触存储、authority 或资源源之前失败。没有面向用户的启用选项。

`EnrollmentStore.with_current_record(...)` 是仅面向可信代码的原语：精确范围 key、预期策略/登记版本和 epoch，以及同步回调。它在 `BEGIN IMMEDIATE` 内验证当前 schema/状态，拒绝撤销/过时记录，提交后返回回调结果。数据驱动的 `run()` dispatcher 不接受此操作；原语本身不确立权限。协调器把返回值限定为经过验证的不可变摘要；任意可信回调都不得暴露给外部输入。

## 3. 可信确认必须意味着什么

`HostAuthority.hold_admission(live_handle)` 必须消耗单独批准的一次性确认，并获得**实际有效的失效栅栏**。失败尝试仍被消耗；重试需要新确认，不能复用旧 allow。本切片唯一的实现是明确标记为合成的测试代码。

其 `ReadConfirmation` 绑定：

- 精确 enrollment ID 及 enrollment revision。
- 与所持 guard 当前 incarnation 相符的宿主 incarnation。
- 独立确立的 `VerifiedReadContext` 和 `ReadGrant`，包含 owner/profile、transport、接收账号、actor、session、policy revision 和 epoch。
- 精确请求，包括资源元组及顺序。本切片不能把更宽的 grant 复用于更小请求；需要新的精确确认。

持久化的拟议身份必须与该独立 context 一致。拟议 scope 可以包含请求 ID，但本身必须是最多 32 个 ID 的 `exact_tasks` 摘要范围。这一保守限制会拒绝较大已存提议下的较小请求。记录和请求都不证明任务 ID 属于 owner。

`AdmissionGuard.validate_and_now()` 必须重新验证当前一次性确认/session/route/connection/host 约束，并返回可信的内置 UTC 时间。它在访问存储前、取得 SQLite 锁后、取得资源快照后及读取后运行。adapter 必须实际串行化失效，不能只比较两次旧快照，或依赖会遗漏 ABA 变化的相等检查；不得采用调用者时间。协调器通过现有纯评估器验证 grant 的精确有效区间。

## 4. 资源所有权与最小投影

`ResourceSource.open_snapshot(owner_id, profile_id, request)` 获取稳定的资源/所有权快照。进入时必须在**读取任何私人摘要字段之前**独立确立所有权。进入可以等待锁，但不能获取私人内容。只有后续 `read_summaries()` 调用，在协调器于所有栅栏内重新检查权限之后，才可返回数据。

不可变 `TaskSummary` 精确包含：

| 字段 | 限制 |
|---|---|
| `task_id` | 精确请求的不透明 ID 之一 |
| `title` | 1–240 字符，不能空白；不得包含 Unicode control/format/surrogate/line/paragraph separator |
| `state` | `captured`、`done` 或 `cancelled` |
| `due_date` | `None` 或合法且规范的 `YYYY-MM-DD` 日期；不推断时区 |

结果必须是精确 `TaskSummary` 实例组成的精确元组，每个请求 ID 恰好出现一次。缺失、重复、外来、超量、可变或惰性结果均被拒绝。协调器按请求顺序确定性返回。完整详情、来源正文、附件、profile 路径及秘密不属于投影；先获取再脱敏不是合格的 adapter 实现。

本切片没有资源 adapter。尤其 `TaskStore.run("list", ...)` 不是 adapter：它没有已验证 owner 列，返回完整任务字段，也不建立所需的组合所有权/资源快照。接入实际本地任务之前，仍需要明确的接管/迁移设计。

## 5. 顺序、线性化与失败

所有参与者必须采用相同锁顺序：

1. 持有当前宿主 authority/失效 guard，并消耗确认。
2. 开启登记 SQLite 事务，验证精确当前版本、非撤销状态、身份和拟议 scope。
3. 获取 owner 范围资源快照，不读取私人字段。
4. 在全部等待结束后重新验证权限和可信时间。此成功检查是所有栅栏均持有时的**读取准入点**。
5. 仅物化有界摘要投影。再次检查权限/时间并验证完整结果；失败则丢弃。
6. 关闭资源快照，再次验证当前权限和可信时钟，持久记录最小快照准备审计，提交 SQLite 事务，退出宿主 guard，然后返回脱离存储的摘要。

策略锁在整个读取过程及提交之前排除撤权/策略修改。撤权先提交时，在资源访问前拒绝。已准入的读取可以先完成，等待中的撤权随后提交。撤权可能在该读取事务之后、甚至在调用者收到结果之前提交：这是已准入的数据，不承诺将其收回。宿主 guard 释放后的失效也遵循同一边界。这里不发送任何传输回复。

即使策略替换内容不变，也会改变 revision/epoch，使旧确认失效。实际等待锁后重新采样可信时间；确认不能仅凭开始等待时有效，就在到期后继续读取。读取后的检查是额外的保守丢弃规则，不保证未来持续有效。

快照错误、读取后拒绝、异常结果、提交失败或宿主退出失败均不返回数据。显式完成检查还防止异常的快照 context manager 吞掉读取后拒绝异常并返回摘要。中断释放事务和 context-manager guard。调用者已开启的事务被拒绝，但不会被回滚。

锁内不得进行提示、网络请求、worker 派发、传输发送或长任务。资源 adapter 不得反向重入登记存储。Python 不能强制任意 adapter 代码正确；最终只能接入经过独立审查的 adapter。

## 6. 审计、持久化与恢复限制

[持久快照准备审计](63-prepared-read-audit-zh.md) 现已在同一策略事务内记录最小 `snapshot_prepared` 元数据。审计失败时不返回数据。宿主退出失败或提交后崩溃仍可能留下已提交记录；它不是返回成功或送达证明。没有重放缓存、可复用批准或完整拒绝尝试日志。容量有界且不静默淘汰；精确 v1 在初始化时升级为 v2。生产权限与资源 adapter 仍未实现。

SQLite 协调此数据库的当前策略，不认证宿主身份、分布式所有权或恢复/克隆栅栏。资源 adapter 仅保证自己的稳定快照；快照关闭后资源可能变化，脱离存储的结果仍是此前的有效快照。恢复的数据库副本无法证明新鲜度。真实跨进程/宿主失效、经过认证的恢复及实际入口尚未实现。

## 7. 验证边界

测试结合实际 SQLite 事务及独立连接，配合明确合成的宿主/资源 fixture，覆盖禁用/缺少 adapter、伪造选择器/handle、一次性重放拒绝、精确确认/scope/版本、receiver/session 不符、有界投影、延迟到期/失效、异常时钟、异常吞掉、中断和提交/退出失败。

确定性竞争测试验证摘要先行与撤权/策略修改的排序、后续过时确认拒绝，以及 `BEGIN IMMEDIATE` 实际等待时到期。它们证明已实现的数据库排序和协调器行为，不证明实际 Hermes/Telegram 宿主提供经过认证的 context 或真正阻止失效。

原生契约在固定 Hermes checkout 下导入实际带命名空间的目录插件，验证默认/缺少 adapter 拒绝，并确认普通模式仍保留拒绝诊断、不创建存储。这是包/注册边界测试，不是实际摘要检索或端到端 Bot 授权。运行仓库统一检查器；历史环境受限 socket 测试不会被重试或重新归类。

新增[worker 策略契约](13-enforcement-contracts-zh.md#26-冻结-worker-配置与当前持久读策略)在原生 import 前 worker-policy 绑定后，将同一协调器运行于真实 discovery 加载的夹具 handler 内。另一连接修改持久策略，而原进程保持冻结 config。使用独立合成 adapter 验证模型/直接 registry 拒绝、两种真实 SQLite 锁顺序、单次重放，以及存储/审计/COMMIT 失败恢复。不新增生产路径或权限；真实生产包 safe-mode fallback 与完整 managed-worker 生命周期仍是独立门禁。

本切片通过 754 项单元测试和 304 项固定宿主契约（共 1,058 项），其中新增 100 项单元用例和 3 项原生边界用例。Ruff、类型检查和双语文档检查通过。

## 8. 下一步生产门禁

在暴露可用 owner 摘要前，仍需可信 bootstrap/enrollment 决策、受支持的实际宿主/IPC 来源及失效栅栏、真实一次性批准签发/消费、owner 范围资源接管、完整审计/保留运维、恢复/克隆处理，以及获准的实际入口验收。接收传输 Bot 和原生 canonical Primary Bot 仍是不同概念。

测试此内部协调器不需要 API key 或用户决定。实际激活路径将需要明确选择信任/bootstrap 机制和精确账号/Bot/profile/数据范围，需要时安全连接凭据，并具备获准的测试环境。提供模型 key 不能解决身份或环境门禁。
