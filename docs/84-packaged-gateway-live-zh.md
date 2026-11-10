# 84. 安装包 Gateway 生命周期验收

[English](84-packaged-gateway-live.md) | 简体中文

## 范围与状态

Issue #50 跟踪 profile-first 本地 MVP 的真实传输前提；#40 已按其原始本地命令范围单独完成。原始单任务安装包生命周期已在精确 head `71fa6efa15a3058c98b09e9f0376a18575818b17` 的[手动运行 42821354726](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42821354726) 中通过。该历史检查点不认证以后每个主分支版本。下述扩展中文项目计划链在自身精确 head 运行通过前，仍是**仅手动运行的验收候选**。普通 PR/单元检查只验证准备工作，不代表真实验收或整个 MVP 完成。

工作流从当前已提交版本构建带来源清单的生产运行包，验证后将其准备成隔离的本地 Git 来源。固定版本的官方 Hermes 安装器在一次性私有 profile 中执行扫描、安装和启用。扫描拒绝或安装失败会让测试失败，不使用绕过标志。仅安装阶段可沿用 runner 现有代理/CA 路由下载官方 Python 依赖。不继承 provider 秘密，Gateway 接收更小的环境，不包含代理/provider 配置。

Host 固定为 `2281116525106e3c109993ccb5dc74d02bfc1427`，只复用其真实进程/control/WebSocket 辅助函数。原有上游生命周期测试使用回环假模型；**独立的安装包测试不复用该模型、它的 harness 或伪造 runner**。测试不调用 `prompt.submit`，不提供 provider 凭据。固定 host 即使恢复纯命令 session 策略也要求非空模型名称；隔离配置仅以 `deepseek-v4.1-flash` 作为元数据，不配置或调用 provider。

## 验收链

1. 启动未修改的 `gateway.run` 进程，要求真实就绪和发现结果。
2. 拒绝未认证的 WebSocket 连接；通过官方私有 control 签发 session ticket，并用原生协议连接。
3. 创建本地 session，通过 `slash.exec` 调用已安装的 `/personal-tasks --json` 命令。
4. 验证任务创建、同键重放不重复、更新至 revision 2、拒绝过期 revision，以及拒绝无效输入。
5. 执行以进程身份为目标的正常计划停止，要求进程退出、control 通道消失及 API 端口关闭。
6. 启动新的 Gateway 实例，取得新 ticket，显式恢复原 session，读回相同任务/revision/title 和重放回执。
7. 再次干净停止；以只读方式独立检查 host 数据库和精确的插件任务库，包括任务 ID/revision/title 以及没有重复行。

## 中文项目计划链

第二个隔离的官方安装测试，通过相同真实认证传输执行一个包含三项任务的中文项目计划。它验证原子计划捕获、依赖顺序、项目/ready/focus 读取、带 revision 检查的编辑、拒绝完成被依赖阻塞的任务，再按前置依赖顺序完成任务。正常停止/重启 Gateway 并显式恢复 session 后，必须保留完整依赖图和持久回执。独立只读数据库检查验证最终规范状态，不依赖模型叙述。

Session 工具激活/focus 命令可以作为确定性状态转换被检查。测试没有模型轮次消费它们：停用或重启后清空其元数据，**不证明**模型侧读写已被拒绝。真实自然语言验收仍是独立事项，需要执行环境中经过批准的 OpenCode Go `deepseek-v4.1-flash` 连接。此工作流不假定当前云端存在凭据，不从其他设备复制，也不存储凭据。

只使用合成任务文本。若正常停止失败，失败清理只终止测试自己的子进程；这是清理，不是成功的生命周期证据。只上传 JUnit 回执，不上传原始 profile、ticket、日志或数据库。

## 运行与限制

从已审查的分支/版本明确触发工作流，不在 push 或 PR 时运行。测试放在 `acceptance/live`，不受离线 `tests/conftest.py` 网络守卫影响，也不属于默认 `tests/unit` 收集范围，所需的 `HERMES_TEST_ROOT`、`HERMES_RUNTIME_PACKAGE` 和 `HERMES_SOURCE_COMMIT` 由工作流已验证的构建提供。

本地云端在构造 `AF_UNIX` 时仍遇到 `EPERM`，通过受支持的提权审核探测也相同。取得该结果后不尝试本地 Gateway 启动或策略绕过。GitHub 托管执行即使成功，也只证明该 runner 的限定验收，不修复本地云端限制或确定其内核策略原因。

这不证明自然语言/模型行为、纯 slash session 的裸 `--continue` 行为、崩溃恢复、TUI 界面验收、远程所有者权限、共享 REST API 完成或外部效果。此前 MacBook/Mac mini 的证据保持独立，此工作流不使用这些电脑。
