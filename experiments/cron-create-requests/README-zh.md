# 仅供审查的原生 cron 创建请求键

[English](README.md) | 简体中文

这个尚未提交上游的宿主补丁针对 `2281116525106e3c109993ccb5dc74d02bfc1427`。它未安装，不是公开插件 SDK、身份权威或提醒功能。生产兼容性固定版本和运行时包保持不变。E1 准入、通知交付及 Issue #19 仍未完成。本实验不运行模型、ticker、网络交付或生产 profile。

## 契约

现有内部 `cron.scheduler.create_job_with_scheduler_registration` 接受可选 `request_key`。省略时保留原有 job 形状返回值；提供时，将严格兼容 JSON 的完整创建参数（包括签名默认值）绑定到版本化 SHA-256 摘要。键在 profile 内唯一，允许 1–128 个 ASCII 字母、数字及 `_.:-`。不同但等价的拼写不会合并。任何参数变化都会冲突，包括目的地、脚本、模型/provider、涉及授权的工具集和时间策略。

结果区分 `creation`（`job_id`、不变摘要和生命周期 `state`）、`current_job` 与 `replayed`。`creation.state` 可推进到 `removed`，因此它不是不可变历史回执。重放读取当前状态，不还原后续编辑、暂停、完成或删除。相对时间仅在首次创建解析。摘要描述请求参数，不描述动态解析的默认值或当前 job 字节。它不是认证签名，也不授权调用者。

请求绑定和新原生 job 在同一个经过 fsync 的 JSON envelope 中原子替换。所有保存路径保留 ledger。删除（包括已完成一次性任务清扫）保留墓碑，重试绝不重建。每个 profile 最多保留 1,024 个永久键；达到上限后拒绝新键，已有重放仍可执行。参数限制为 64 KiB，存储限制为 16 MiB。没有自动 ledger 淘汰或重置命令。

只接受显式 builtin/默认 scheduler 配置，不调用通用 provider resolver。在持久化 job 前拒绝外部 provider，即使原生 provider 解析本会静默回退。Builtin 注册是空操作：持久存储仍是调度权威，重试取回原 ID 而不注册第二个触发器。不声称支持通用外部 provider 对账。`enabled` 仅表示当前 enabled，不表示已经执行或送达；`delivery_verified` 始终为 false。

## 有意改变的宿主行为及边界

- 所有 job 写入者（包括不带键的写入）都必须取得跨进程锁。超时或锁后端不可用时拒绝，不再降级为进程内锁。嵌套锁不能切换存储。这改变了原生可用性行为，需要上游审查。
- 畸形 JSON（包括 NaN/Infinity，旧存储也拒绝）、重复键、损坏或未知版本 ledger、超限存储均 fail closed。带键存储不得自动丢弃垃圾条目或重置计数。未实现修复流程，不得手动删除 ledger 来恢复。
- **采用前必须停止所有旧 runtime。** 旧代码会丢弃 ledger 并忽略这些规则。本提案无法可靠检测整个 ledger 被删除。并发旧进程、手动替换存储、从备份回滚和恶意进程内代码不在保证范围内。
- 原子 rename、文件/目录 fsync 及同键对账覆盖已测试的进程退出窗口，不是通用断电或文件系统保证。替换后异常可能表示已成功提交；`create_outcome_unknown` 必须使用同键对账，不得改用新键。锁失败发生在创建前。持续失败可能仍无法解决。
- 原生所有权、occurrence 执行、取消和交付保持不变。不增加调用者可控路径、额外服务、并行 scheduler、模型工具、CLI flag 或插件后台消费者。内部 API 不等于生产授权。

## 安全复现

使用已单独准备的 Python 3.14 环境及精确基线上的无凭据临时宿主 checkout。不要使用生产兼容性 checkout 或日常 profile。先审查补丁，再自行应用并暂存：

```sh
git -C "$DISPOSABLE_HOST" apply --check "$ARTIFACT/cron-create-requests.patch"
git -C "$DISPOSABLE_HOST" apply --index "$ARTIFACT/cron-create-requests.patch"
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON" --check-only
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON"
```

runner 不下载、安装、应用补丁、启动 gateway 或更改兼容性固定版本。它核验精确 base、暂存 diff/tree、源码哈希、未跟踪修改及索引隐藏标志。子进程使用清理后的环境，显式导入打补丁的宿主并拒绝联网。所有存储均为临时合成 profile。测试覆盖重放、参数冲突、并发、替换前后进程退出、暂停、删除、真实完成清扫、容量、损坏及不支持的 provider。这些是宿主存储契约，不是真实定时 occurrence 或用户通知。manifest 记录实际选定测试结果，不代表完整上游认证。

补丁中的上游源码受[保留的许可证](LICENSE.hermes-agent)覆盖。未向上游提交或发布任何内容。
