# 仅供审阅的任务规划 worker

[English](README.md) | 简体中文

## 状态

这是隔离环境中的宿主提案及具体实验任务消费者，**未安装、未启用、生产插件不会导入、未提交上游、未部署**。正式宿主基线仍为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。不要把补丁应用到已安装的宿主，也不要为了尝试它而降低插件隔离。

[清单](manifest.json)记录准确补丁、源文件哈希、选定验证和限制。[宿主补丁](text-worker-prototype.patch)保留上游 [MIT 许可证](LICENSE.hermes-agent)。在本项目功能分支分发不等于上游发布。

## 收窄后的实用流程

[实验消费者](consumer.py)把真实本地任务接到拟议的 `ctx.subagent_lifecycle.launch_text` API：

1. 已授权的原生 LOCAL 会话控制者执行 `/personal-plan-worker allow TASK_UUID REVISION REQUEST_ID`，批准把所选活动任务快照交给 OpenCode Go `deepseek-v4.1-flash` 做一次规划，有效期最长 120 秒，输出上限 1024 token，请求超时 30 秒。正常模型用量可能产生费用。命令本身不发起请求。
2. 在真实主会话轮次中，`personal_task_plan_preview` 可以消耗该准确授权。仅允许 `action`、`request_id` 两个字段。模型不能提供目标、任务、上下文、提供商、模型或权限。任务修订变化、授权过期/撤销、会话/路由/配置档不符或子代理轮次，都会在派发前拒绝。
3. 宿主准入一个有界、单请求的纯文本 worker，返回普通生命周期句柄。只有消费者保留该能力句柄。重复 launch 只检查同一句柄；异常留下结果不明的记录，绝不自动重试。
4. 结果返回**不可信的规划草稿**、快照/当前修订和过时标记。不会更新任务状态、创建提醒、派发可执行工作或发送消息。模型声称完成不构成任务状态变更。

`revoke REQUEST_ID` 阻止尚未开始的调用。已准入的调用可能完成。重新加载/卸载会失去消费者的进程内授权与结果，不能收回提供商已接收的数据或取消计费。尚无可跨重启恢复的持久执行回执。结果不明后重新授权可能重复调用，因此帮助文案明确提示不要这样操作。有界授权表保留终止记录，不会静默淘汰后允许再次执行。观察到配置撤销会永久撤销未启动的授权；未被观察到的关闭→恢复变化，需要宿主单调修订栅栏才能识别。

## 宿主约束，而非提示词承诺

现有不受此约束的 agent 启动保持不变。新文本路径默认关闭，按可信插件及准确的提供商/模型/base URL 单独配置，仅接受当前普通 OpenAI SDK chat-completions 路由。不查询已保存的 delegation 路由、回退链或凭据解析器。HTTPS 端点不得含 userinfo/query/fragment。拒绝 SDK provider 适配器、动态认证、query 覆盖、自动跟随重定向的 HTTP 客户端、HTTP 认证及 event hooks。

**普通 OpenAI SDK 默认跟随重定向，因此已有的默认 Hermes/OpenCode Go 客户端可能被直接拒绝。** 正式部署前需要受支持的专用 no-redirect 客户端。实验绝不修改父客户端或网络设置来让测试通过。提供商返回的模型标识不符时，会在响应后拒绝结果，不能撤回先前请求。

文本路径不构造或运行完整 `AIAgent` 子代理，使用真实宿主传输与中间件、不可变请求和单次受控调用回调，仅发送固定规划指令与所选任务快照。不会继承父历史、prefill、工具 schema、请求覆盖、MCP 权限、递归委派、工作区创建、记忆摄入、压缩或辅助模型工作。不派发模型返回的工具调用；任意中间件请求变化或额外尝试均被拒绝。

这不是 OS/Python 沙箱，不能防御恶意同进程插件、提供商实现或操作者。配置的插件信任不证明每次调用由真人亲自发起。原生 LOCAL 准入依赖宿主已有的注册来源/会话控制者检查，所有获授权控制者共享该会话权限。提供商内部行为以及实际计费/执行模型仍不能仅由客户端证明。超时/取消是协作式的，不能撤回已发送的请求。

## 重现选定离线证据

使用全新、可信、无凭据、位于准确基线的可丢弃源代码副本，已准备好的 Python 3.14 测试解释器，以及经过审阅的工件。暂存前先审阅补丁。以下是主动执行的实验步骤，不是生产安装程序：

```bash
set -eu
ARTIFACT="/path/to/hermes-superagent/experiments/text-worker"
COPY="/path/to/disposable-hermes"
PYTHON="/path/to/existing-test-venv/bin/python"
test "$(git -C "$COPY" rev-parse HEAD)" = 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
test -z "$(git -C "$COPY" status --porcelain)"
git -C "$COPY" apply --check "$ARTIFACT/text-worker-prototype.patch"
git -C "$COPY" apply --index "$ARTIFACT/text-worker-prototype.patch"
"$PYTHON" "$ARTIFACT/run_tests.py" --checkout "$COPY" --python "$PYTHON" --disposable-copy
```

[运行器](run_tests.py)先验证准确基线、已暂存补丁字节和消费者/测试哈希，再调用宿主标准测试运行器。不应用补丁、不安装包、不创建依赖环境、不配置个人配置档。`--check-only` 只检查上述条件，不执行宿主 Python。测试使用临时 home 与 HTTP mock transport，无监听器、真实模型/提供商请求或凭据。消费者测试运行真实原生命令授权、轮次准入、SQLite 任务存储、宿主生命周期、请求传输以及 OpenAI SDK 序列化。

普通项目检查器仅验证工件完整性，继续针对**未修改的干净宿主**进行契约测试。准确提交的项目 CI 不是该宿主提案的上游 CI，也不是真实模型验收。隔离实验是单独选定的测试范围，不是全量上游测试。没有重试曾被拒绝的 Gateway socket 测试。

## 剩余发布门槛

- 独立宿主 API 采纳/安全审阅和受支持版本，而不是向用户安装应用本地补丁。
- 通过获授权配置进行真实 OpenCode Go `deepseek-v4.1-flash` 验收，观察 wire/用量行为；不得换模型或静默回退。
- 在持续自主派发前，完成持久任务执行账本、重启恢复、结果不明的明确核对、并发限制和预算统计。
- 合理的取消/超时界面与可靠进度投递。短时轮询结束不能证明远端取消。
- 带工具 worker 仍需单独的可执行能力约束设计。纯文本预览不是代码执行、完整 worker 编排、Gateway 全链路验收、自动记忆或 MVP 完成。
