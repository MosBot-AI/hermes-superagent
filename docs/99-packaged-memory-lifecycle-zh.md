# 99. 安装包记忆生命周期验收

[English](99-packaged-memory-lifecycle.md) | 简体中文

## 范围与证据

[Issue #139](https://github.com/MosBot-AI/hermes-superagent/issues/139) 为实际生产运行包中的[观察来源保留命令](98-observed-source-retention-zh.md)增加需要显式运行的验收通道。它使用未经修改的 Hermes 固定版本 `2281116525106e3c109993ccb5dc74d02bfc1427`、官方安装器，以及全新合成配置档中的已认证原生 Gateway 传输。不涉及提供方凭据、模型回合、真实个人数据或宿主补丁。

测试实现本身不等于一次成功运行。Issue 及关联 PR 记录准确来源提交、安装包验证、已执行测试、独立审查与实时工作流结果。对工作流的单元检查通过只是静态证据；即使所有契约和安装包检查通过，实时失败仍是失败。本切片不关闭 [E2.6](https://github.com/MosBot-AI/hermes-superagent/issues/43)、[E2.8](https://github.com/MosBot-AI/hermes-superagent/issues/45)，也不证明模型实用性、自动摄取或生产部署。

## 真实进程与来源生命周期

[安装包记忆测试](../acceptance/live/test_packaged_gateway_memory.py)复用现有官方安装夹具与真实 Gateway 子进程辅助函数。会话创建、恢复和记忆命令通过原生已认证 WebSocket RPC 执行。每次重启都停止旧进程，并验证使用不同的进程/实例；进程内重置插件管理器不算重启。

合成原始行在 Gateway 停止时通过公开的 `SessionDB.append_message` 写入。随后通过 `source-list`、`source-show`、`source-preview` 和 `source-retain` 审阅及保留原生来源，使用准确的已审阅快照、显式保留选择和已保存的请求键/摘要。测试检查完整内容、原始角色、观察来源标记、精确重试和一次已完成游标推进。不会要求模型制造会话记录。

完全停止后，公开的 `SessionDB.clear_messages` 删除测试会话的原始行。原生数据库及会话仍保留，以便新 Gateway 真正恢复该会话。新进程必须看不到原始行，但 `source-status`、`source-cursor` 和规范记录读取仍应恢复已经授权的独立快照。这证明的是**原始文本丢失**，不是原生数据库丢失、断电或提交时原生来源仍有效的保证。现有白盒契约另行检查元数据操作不打开原生存储或载入记录载荷；只检查输出不能证明这些内部事实。

规范更正与遗忘使用现有原生命令。新读取必须显示当前 revision/status，已保存的接受决定则仍是历史记录。再次重启后，新接种的原始行若包含完全相同的文本，即使换了消息 UID、请求键和消费者，也必须以 `source_suppressed` 拒绝。只读数据库判定检查完整性、记录/事件/决定数量和被遗忘载荷的移除，不写入验收状态。

## 待决设置是独立 SDK 夹具

生产原生 `source-retain` 命令同步执行暂存与接受，并不存在仅暂存的原生命令。为了确定性地检查待决恢复，一个独立的新 Python 进程通过真实宿主加载器载入**已安装包**，使用此前审阅过的预览载荷调用 API-v1 `LocalMemorySDK` 的 `source_stage` 操作。只读加载器检查用于识别已加载包并验证模块路径，不是新增公开宿主 API，也不修改宿主准入。这是可信、明确绑定的合成 SDK 设置，不是伪造回执、直接 SQL 写入或模型授权导入。

Gateway 停止时，测试清除原始行。随后新 Gateway 检查待决决定和未改变的已完成游标，拒绝错误摘要，显式丢弃准确保存的键/摘要，并确认终态重试不会再次推进游标或创建记录。新的完全相同内容仍被抑制。

这证明受支持的 SDK 暂存决定可以通过真实安装包原生命令恢复，**不**证明在暂存与接受两次提交之间杀死 Gateway 的情形。现有底层进程故障测试覆盖各自事务边界，不能把任一通道改称为另一种证据。不会用依赖时序竞态的杀进程、生产猴子补丁或自动重试未知结果来填补这一证据缺口。

## 在隔离环境复现

仅手动触发的 [Native Gateway 工作流](../.github/workflows/native-gateway.yml)准备准确的宿主/解释器，构建并验证已提交运行包，将其暂存为本地 Git 来源，然后通过未经修改的官方安装/扫描路径运行任务和记忆验收。扫描或安装拒绝会停止运行。不得安装此前被拒绝的完整仓库，不得修改扫描器，也不得削弱既有隔离策略。

若自行准备本地运行，应先遵循[运行包验证与暂存指南](runtime-distribution-zh.md#先验证再暂存为本地-git-源)，使用本次测试的准确来源提交，不要替换成较早的仅任务检查点。提供干净的固定宿主、已验证且已 Git 暂存的运行包及准备好的 Python 3.14.9 解释器的绝对路径：

```sh
export HERMES_TEST_ROOT="/absolute/path/to/pinned-hermes"
export HERMES_RUNTIME_PACKAGE="/absolute/path/to/verified-staged-runtime"
export HERMES_SOURCE_COMMIT="FULL_40_CHARACTER_TESTED_SOURCE_COMMIT"
"/absolute/path/to/hermes-test-venv/bin/python" -m pytest -q \
  acceptance/live/test_packaged_gateway_memory.py
```

这些是需要显式执行的实时测试，不在默认单元测试套件内。仅使用可丢弃配置档。若环境拒绝原生套接字或安装步骤，应保留准确错误并将实时验收报告为受阻，不得绕过限制。JUnit 产物包含合成测试证据，不是提供方日志或个人数据库。

2026-11-11 的本地准备运行验证了基线 main `48dfc8662226cb668e21b0fc434af4943c324470` 的未修改运行包，并通过官方安装与扫描。首个 Gateway 因私有控制监听器返回 `[Errno 1] Operation not permitted`，在创建会话前退出。本地未执行任何记忆命令或恢复阶段，也未绕过或重试套接字限制。独立的 GitHub-hosted 工作流必须提供准确来源的实时证据，安装成功不能替代它。

## 对操作者的意义

- 保留前保存预览 query。遇到不确定结果或来源丢失时，检查原始键/摘要，不要发明新键或重放不可用文本。
- 原生来源保留与规范保留相互独立。删除来源文本不会撤销另行授权的规范快照。
- 待决丢弃解决待决来源决定并抑制其精确文本，不会遗忘已接受的记录；后者应使用规范遗忘。
- 更正、到期和遗忘影响新读取，不撤回此前模型/客户端上下文、会话记录、备份或导出；精确文本抑制不是语义擦除。
- 结果是有界的确定性安装包/Gateway 证据，不是广泛生命周期覆盖、checkpoint-v2、真实模型验收、远程所有者授权，也不是部署到日常配置档的许可。
