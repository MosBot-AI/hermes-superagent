# 13. 执行边界契约与写路径清单

[English](13-enforcement-contracts.md) | 简体中文

此页记录较早的 E0 切片。当前新增的显式本地任务收件箱见 [16](16-local-task-inbox-zh.md)；它不启用这里列出的原生/外部受控写路径。

本次后续 P0 切片推进 E0.4，但不启用任何受控写能力。新增可复验的失败边界测试和机器可读发布清单。E0.4、E0/M0 与 E1 授权仍未完成。

## 1. 实现了什么

`personal_agent/enforcement.py` 返回独立、可 JSON 序列化的清单。每条已知写路径都为 `controlled_writes_enabled: false`、`release_gate: blocked`；未列出的路径也属于未验证、阻断的本项目受控写发布范围。状态工具只返回有界摘要。默认 in-process 插件模式下，`hermes personal-agent coverage` 输出完整清单。

这是**只读发布报告**，不是动作授权器、实时宿主检查或沙箱。它不关闭其他 Hermes 工具、不拦截直接 API 调用，也不会把操作员现有工具配置变成受控环境。基线 commit 是已测源码的证据，不代表当前宿主必然运行该 commit。固定宿主在 host-isolation 模式跳过插件 CLI 注册。

## 2. 固定基线的实际行为

新增测试通过真实 discovery 加载真实目录插件，其唯一 handler 只在内存中记录调用。没有替换 manager、context、manifest parser、registry 或 config loader。测试夹具控制 callback 行为；外层 dispatcher 测试显式注入一次逃逸的 dispatcher 异常。

| 边界 | 观察结果 | 含义 |
|---|---|---|
| `pre_tool_call` 显式 block | 不进入合成 handler | 常规拒绝在此已测调度路径有效 |
| 注册 callback 抛出 `RuntimeError` 或 `SystemExit` | inline 与 bounded 模式均产生 block directive | callback 异常 fail-closed，不等于 dispatcher 异常 |
| callback 超时及受抑制的重试 | 两次均阻断，不调用 handler | 超时 callback 仍可能存活，hook 不得执行副作用 |
| 相同调用标识的 callback 仍在运行 | 第二次投递在超时前阻断；释放后首次调用执行一次 | 正在执行的调用抑制与超时退避不同 |
| 执行 middleware 在 `next_call` 前抛异常 | 下游 handler 仍执行一次 | 此失败是 fail-open，不是授权拒绝 |
| middleware 在 `next_call` 后抛异常或调用两次 | 已测链路不重放已完成 handler | 不能据此推断远端传输幂等 |
| 异常逃逸出外层 hook dispatcher | `model_tools` 继续调用 handler | 被捕获的 callback 异常与 dispatcher 失败属于不同边界 |
| 直接 registry dispatch | 不调用 `pre_tool_call` hook 或执行 middleware | 底层调用不继承面向模型的调度链 |
| Troubleshooting safe worker | 跳过插件 discovery 与 hooks | 缺失的插件不能保护写操作或提供自己的降级诊断 |
| 普通 managed worker / config-only worker | 插件与 hooks 仍启用，config 保持冻结 | 后续 profile 修改不是即时撤权 |

Worker 探针在全新进程中运行，因为 bootstrap policy 必须在 runtime import 前一次绑定。测试验证修改返回的 config 或替换磁盘 config 不会改变冻结快照。子进程使用明确变量 allowlist、临时 home，并在进程内阻断 socket 连接。超时测试 hook 在 teardown 中通过 Event 释放并 join；宿主本身不保证杀死被放弃的 callback。

测试位于 [原生执行边界契约](../tests/contracts/test_enforcement_boundaries.py)。该夹具仅用于测试，不会作为插件运行时工具面安装。

## 3. 受控写发布清单

| 路径 | 本切片证据 | 发布状态 |
|---|---|---|
| `native_dispatch` | 合成 hook 与外层 dispatcher 失败契约 | 阻断；尚未接入操作级授权 |
| `direct_registry` | 合成跳过 hooks 契约 | 阻断；handler 需自行检查操作级权限 |
| `mcp` | 无端到端裸 MCP 写合同 | 阻断 |
| `shell` | 无 backend containment 或操作级写合同 | 阻断 |
| `browser` | 无身份绑定写入/结果合同 | 阻断 |
| `execute_code_rpc` | 无端到端嵌套调用权限合同 | 阻断 |
| `connector_batch` | 无逐项授权/部分结果/重试合同 | 阻断 |
| `short_worker` | 无被委派副作用/撤权合同 | 阻断 |
| `managed_worker` | 合成冻结 config 与 safe-mode 合同 | 阻断；未接入当前持久 policy 检查 |
| `scheduled_job` | 无授权/取消/交付/对账合同 | 阻断 |

“合成合同”不等于完整覆盖某类工具。内存探针通过，不能证明 shell、MCP、browser、外发或真实 worker 副作用受保护。清单内部不可变，返回独立快照；修改报告不能授予能力，也不能改变后续报告。

## 4. 启用写操作前的要求

1. 通过 E1 建立 verified owner 与有范围的 action intent/grant，依据可信来源，不使用模型传入的批准标志。
2. 每个领域动作 handler 自身执行授权检查，包括不经过面向模型 hook 链的调用。Policy store 失败不能变成许可。
3. 动作准入时读取当前持久 policy revision，冻结的 worker config 不是该权威。遵循 [撤权设计](06-plugins-mcp-and-security-zh.md#8-撤权审计与应急停止) 的事务顺序与在途动作边界。
4. 验证每条启用路径，并缩减暴露工具、凭据和执行环境，防止未受保护的替代路径执行同一受控动作。
5. 威胁需要 containment 时使用合适的 OS/进程隔离。进程内 hooks 和本清单不能替代隔离。

本切片没有可启用写操作的 mode 或配置开关。独立配置的 Hermes host 仍可能暴露自己的工具，本插件不宣称控制这些工具。

## 5. 证据与限制

- 基线：Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`、Linux、Python 3.14、隔离测试 home，无账号凭据。
- 检查脚本现在通过官方逐文件 Hermes runner 运行 `tests/contracts` 下全部文件，同时执行单元测试、Ruff、ty 和双语文档检查。
- 实测 dispatcher 失败仅覆盖 `model_tools` wrapper。其他 wrappers 与直接 MCP helper 仅做源码检查，没有运行端到端写操作。
- 无需生产账号、API key、在线模型调用、外发或真实 connector 写操作。未来在线测试需要独立、限定范围的测试配置与安全凭据交接；凭据不得进入聊天、日志或仓库。
- E0.3 公共 Project/Kanban/cron 合同及 E0.4 未测路径仍待完成。本切片通过不代表 M0 完成，也不允许依赖 E1 的写功能发布。

固定来源：

- [插件 dispatch 行为](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_dispatch.py)
- [面向模型的工具 dispatch](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py)
- [执行 middleware](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/middleware.py)
- [Managed/safe worker policy](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/safe_worker_policy.py)
- [上游安全模型](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/SECURITY.md)
