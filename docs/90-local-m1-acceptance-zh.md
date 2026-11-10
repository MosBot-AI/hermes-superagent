# 90. 原始本地 M1 验收

[English](90-local-m1-acceptance.md) | 简体中文

## 结论与固定检查点

状态：在下述固定检查点上**接受原始本地 M1 范围**。本验收记录发布前仍需完成最终独立审查及合并。[#115](https://github.com/MosBot-AI/hermes-superagent/issues/115) 对齐原始 profile-first 确定性本地 M1 范围，并不完成 Hermes Super Agent 总目标。

- 源码：`ed6bcdc15d883dc429f2dbb0559a62204965ab04`。
- 源码树：`24bae909c2caf97e11620a1d9a660cba22272670`。
- Hermes：`2281116525106e3c109993ccb5dc74d02bfc1427`。
- 精确源码 [Foundation 运行 42859787656](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656)：已成功完成。覆盖离线检查、固定 host 契约和生产运行包验证，不是 live 传输。
- 精确源码[手动 Gateway 运行 42862192600](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42862192600)：已成功完成。运行 API 确认精确源码 SHA 和结果；job 日志确认 3 项 upstream 生命周期测试和 5 项生产包插件测试通过。两次硬杀位于同一项生产包测试内，不是额外两项测试。

验收源码固定为这个检查点，不是未指定的未来 main，也不是本次文档提交。机器可读 [ledger](local-m1-acceptance-ledger.json) 记录源码、host、证据链接和精确测试函数。其静态[测试](../tests/unit/test_local_m1_acceptance.py) 仅检查结构和引用；通过不代表重跑场景或核实 GitHub 结果。

## 原始标准，不增加要求

依据是[产品范围 §5](01-product-and-scope-zh.md) 和 [M1 里程碑](08-roadmap-and-acceptance-zh.md)。它们要求受信单用户 LOCAL 命令、持久任务/项目标签、重启/重复/修订/非法输入/host 准入检查、明确限制，以及不新启用远端/出站能力。E6.9 位于此确定性切片之后。实现不会把 profile 或 LOCAL 标签变成已验证的人类身份。

| Ledger 标准 | 证据映射 |
|---|---|
| M1-1：无需 Bot 的显式启用原生 LOCAL 入口 | 原生 owner 命令生命周期、默认关闭注册、生产包 Gateway 安装/分发 |
| M1-2：add/list/search/projects/show/update/done/cancel/agenda | 对话工作流、原生取消/重载、中文项目计划链 |
| M1-3：持久收据、重复/CAS/输入拒绝与重启 | 冲突/非法输入测试、原生 manager 重放、真实 Gateway 重启读回 |
| M1-4：私有访问前的现有 host 准入 | 原生权限/source 拒绝、非 LOCAL 拒绝、producer event 拒绝及已准入 owner/operator 范围 |
| M1-5：配置与 profile 边界 | 未启用、重载/卸载、当前配置与双 profile 隔离 |
| M1-6：私有存储与真实失败语义 | 不安全文件/sidecar 和外来数据库拒绝；不确定结果保留重试键且不自动重试 |
| M1-7：有限本地范围 | 已支持 source 契约、非 LOCAL 拒绝及现有原生认证传输，不是新增插件 listener |

Ledger 为每行提供精确可执行引用及对应证据运行。原生进程内权限测试不是实际登录测试；真实 Gateway 测试也不能替代全部不利原生上下文测试。它们在同一源码检查点上提供不同观察结果。

## 适用的进入前提

路线图还要求适用的 E0.1/E0.2/E0.4/E0.5 证据。Ledger 的 `entry_prerequisites` 将它们分别映射到精确测试及同一 Foundation 运行：

- **E0.1：**精确 host 导入，以及 runtime pin、兼容性记录和 workflow 的一致性。不由此推导宽泛版本范围。
- **E0.2：**本地任务所用的真实插件发现/分发、启用/禁用、非法配置、卸载/重载和 profile 范围存储 helper 契约。不假设虚构 host API。
- **E0.4：**[有限 enforcement ledger](enforcement-evidence-ledger.json) 和生产 exposure 测试覆盖默认配置、冻结配置、安全 bootstrap、不支持的 worker 及 blueprint 消费者。它们证明适用的项目不暴露/默认拒绝边界，**不是 host 全局只读行为**。显式本地任务启用仍受自身准入约束。独立配置的 host 工具不在此保证之内。可选 planning blueprint 即使在 `read_only` 模式也能安排普通 host 送达并产生 provider 成本；本地 M1 验收不会启用它，也不认证通用受控写入。
- **E0.5：**合成连接器测试覆盖有界来源/账号隔离夹具、拒绝将来源文字或夹具绑定当作权限，以及从 runtime 排除夹具代码。这些不需要真实账号，也不证明实际连接器认证或送达。

这些是本地里程碑适用的前提，不是对所有 E0/E1 工作的一揽子接受或关闭。独立 ledger 行防止任务生命周期成功被默默当作这些前提的替代品。

## 三种不同的恢复结论

1. **正常 Gateway 重启：**计划关机、新实例和 ticket、显式 session resume、规范 SQLite 读回。生产包任务、中文计划、优先级及跟进链覆盖此行为。优先级/跟进工作台是有用的附加场景，不是事后新增的原始退出条件。
2. **TaskStore 进程崩溃：**`test_task_process_recovery.py` 的 88 个参数化案例在 SQL/commit 边界终止真实子进程，并在临时 DELETE/WAL 数据库中验证回滚或持久收据重放。这既不是 Gateway 崩溃，也不是断电证据。
3. **附加 live Gateway 崩溃（#113）：**生产包未观察回复的创建/更新场景两次硬杀自己的 Gateway，重启后核对持久状态及精确请求键。客户端没有消费回复，不证明服务器何时发出了回复。这项附加 E8.2 证据不改写原始 M1 条件，也不证明外部 exactly-once 送达。

精确检查点的手动 live 运行现已成功。上述场景边界不变：成功不会把正常重启变成崩溃证据，也不会把本地恢复变成外部送达。单元 mock 或静态 ledger 检查不能替代这次 live 运行。

## 独立待办与诚实交付

E6.9 真实自然语言验收需要获授权的 OpenCode Go `deepseek-v4.1-flash` 连接，仍为独立后续。完整 [#21](https://github.com/MosBot-AI/hermes-superagent/issues/21) 身份/撤权/外部送达矩阵及 [#19](https://github.com/MosBot-AI/hermes-superagent/issues/19) 提醒/送达仍开放。共享认证 REST、远端 owner/移动/Bot 准入、通用 worker 执行及更广泛的记忆适配器/生命周期/迁移目标均不在本次接受范围。跟进日期不会发送通知；本地任务完成不会执行外部任务。

这些是**本地验收范围之外或独立待完成项**，绝不是“不适用即通过”。完成本 ledger 不得自动关闭那些 issue、启用 provider 或出站操作、宣称 TUI/模型/设备认证，或声称整个个人助理已完成。最终接受需要精确源码证据及独立范围审查；交付物是有限本地 MVP，并向用户明确以上限制。

## 获取并试用这个精确本地检查点

[已验证运行包](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656/artifacts/13785725174)名为 `hermes-personal-agent-runtime-ed6bcdc15d883dc429f2dbb0559a62204965ab04`，到期时间为 **2026-12-10 17:04:08 UTC**。这是 CI 开发产物，不是 release 或永久下载渠道。独立只读核对确认 ZIP 摘要、内部校验和、全部 83 个分发源文件，以及精确 source/tree 来源证明一致。扫描报告为 safe，保留六项中等发现；应保留并阅读完整报告，不假设后续包结果相同。Foundation 验证本身明确没有安装或调用模型。

实际顺序见[固定检查点操作者指南](runtime-distribution-zh.md#固定检查点操作者入口)：**先**按该源码验证下载字节，**再**加入 `.git`、创建本地暂存 Git 提交，然后在全新隔离可信 profile 中使用未修改的官方 `file://` 安装器安装该提交。暂存提交不是原始源码 SHA；纯解压目录不是安装器要求的 Git 源。保留全部扫描/catalog/同意门槛，遇拒绝即停止。不要安装此前被拒绝的完整仓库目录，也不要降低现有隔离策略。

固定宿主与准备好的解释器是前提，不包含在插件归档内。确定性 CLI 和获准的 LOCAL slash 命令不需要 provider 凭据，宿主 UI 的前提仍需单独满足。此有限入口仅启用 `mode: local_tasks` 与 `local_conversation: true`。跟进日期不会送达提醒；该包不提供共享认证 REST、自然语言验收结果或整个 Super Agent 完成结论。是否可宣称接受该精确检查点，应以上方证据状态为准。
