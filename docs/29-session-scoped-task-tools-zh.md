# 会话范围的本地任务工具

[English](29-session-scoped-task-tools.md) | 简体中文

状态：针对固定 Hermes SHA 中普通原生进程内会话的显式启用 E6.9 实现。在[确定性对话命令](28-profile-first-local-conversations-zh.md)之外增加面向模型的任务工具。尚未进行真实 provider 的自然语言验收。安装不会配置凭据或账号。

## 1. 支持的部署与显式激活

支持此前批准的可信单用户本地 profile 部署，不是新的远程身份服务。宿主继续授权原生 LOCAL 会话控制端。所有获准 owner/operator 控制端及**已激活会话内的所有模型活动**共享所选访问能力，包括由非新鲜人工消息的材料引起的 turn。激活不能证明每一项模型提出的变更都由用户明确要求。不可信内容和其他已启用 Hermes 工具不在本插件的沙箱保证内。

在临时 profile 中使用已测试 Hermes pin 和经审阅插件 commit，保留其他配置条目并明确添加：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
        local_model_tools: true
```

`local_model_tools` 默认 `false`，只接受布尔值，并要求另外两项设置。加载该配置会在已有 `personal_agent` 工具集中注册两个工具 schema，但不打开任务存储、不激活任何会话。通过宿主正常工具选择控件选择该工具集，并按宿主要求启动/重载会话。Schema 保持 profile 范围且稳定；出现 schema 不等于允许执行。

在已有原生本地会话中使用以下命令之一：

```text
/personal-tools enable-read
/personal-tools enable-write
/personal-tools status
/personal-tools disable
```

`enable-read` 允许有界任务读取，`enable-write` 同时允许读取和本地编辑。两者均从明确命令发出时起授权 **30 分钟**，每个已加载插件最多 64 个活动会话。Status 不续期。激活保存在内存中，以注册的 profile、精确原生 session ID 和 route key 为键；插件重载/卸载或进程重启会清除。新/轮换会话需要重新激活。写权限之后启用只读会降为只读。

**隐私与费用：**返回的标题/详情/note 会进入已激活会话配置的模型上下文，因此可能发送给该模型 provider，并进入正常宿主历史/日志。只有允许该已配置模型接收数据时才激活。这不是新增 provider 连接。普通模型使用可能按用户已有配置收费；这些工具不额外调用第二个 LLM，也不切换 provider。

可选[任务聚焦](46-native-task-focus-zh.md)在激活后通过 `/personal-tools focus <task-id>` 为后续每个原生轮次提供一条新的任务快照。`clear-focus` 停止未来快照，不撤销工具。默认不选任务，也不更改模型/提供器。

## 2. 自然语言流程与工具契约

`enable-write` 后，可以对已有主模型说“在 Personal Agent 项目中添加准备演示的任务”“查看该项目的任务”“将演示任务标记为完成”。模型必须调用注册工具并使用返回 ID/revision，而非只承诺记住任务。自然语言理解和工具选择取决于已配置模型，仍需真实验收。

- `personal_tasks_read`：`list`、`show`、字面 `search`、通过 `projects` 查看项目标签计数、显式日期 `agenda`，以及仅含元数据、使用整数 `after_revision` 游标的任务 `history`。参见[操作历史](34-local-task-history-zh.md)。
- `personal_tasks_write`：`capture`、`update`、`complete`、`cancel` 和明确的 `progress`。[任务进度](42-local-task-progress-zh.md)说明状态、说明和过滤契约。所有修改要求稳定 `request_id`；编辑、进度和终态变更还要求之前读取的 `task_id` 与 `expected_revision`。完成/取消/进度要求 note。
- 由同一 TaskStore 校验器拒绝未知、不相关、身份/批准字段及错误类型。`show` 映射为存储的 `get`；没有其他隐含动作别名。
- 日期必须明确。项目名仍是标签，不是原生 Project、worker 派发或权限范围。完成记录不等于实际执行对应现实任务。不发送提醒或外部副作用。
- 读取结果继续遵守已有页/详情上限。只返回所请求操作的数据，不自动将整个 profile 当记忆加载。

合成工具调用示例：

```json
{
  "action": "capture",
  "title": "Prepare demo",
  "project": "Personal Agent",
  "request_id": "demo-capture-1"
}
```

结果使用 `personal.session-task-tools.v1`，包含 `scope: activated_trusted_local_session`、`status`、`data`、`error`、`request_id` 和 `replayed`。任务存储现为 schema v4，包括历史 `source: local_cli`；该字段标识明确本地操作功能系列，不是可信 session/Bot 来源。稳定回执、冲突 key 拒绝和 revision 规则与确定性命令相同。结果不确定时重试同 payload/key 或先查看任务；换新 key 可能重复录入。插件绝不自动重试。

## 3. 准入与撤销边界

激活通过真实注册 slash 命令，沿用现有原生会话准入。只接受支持的 LOCAL source 结构及精确上下文 `bound_session_key()` 匹配，不回退环境变量。仅复制 source/session 字符串不能通过普通工具参数激活。

每个工具 handler，包括直接 registry dispatch，都要求固定版本的 `agent.relay_runtime.active_turn(dispatcher_session_id)` adapter。它校验当前、未关闭/释放、profile/session 匹配的 turn，匹配 task ID，支持的 lease platform（`cli`、`tui`、`desktop`），无 parent/delegated 或 cron 上下文，无回退 route 绑定，当前 profile/配置，以及未过期且符合所需读写级别的激活。工具参数不能提供 owner、profile、session、批准或 lease。无上下文的 registry 调用即使复制 session ID，也会在任务存储前失败。

Adapter 在准入并完成有界存储操作期间持有真实 turn 的 finalization lock 和插件 activation lock。若 disable 先取得 activation lock，下一操作被拒；若操作已准入，disable 等待其完成。过期阻断未来准入，不撤回已准入事务。这不是取消已经提交的编辑。回调观察到禁用/非法配置时清除激活；重载运行进程以一致应用配置。卸载除了清除激活，也永久关闭保留的 handler。

这是**固定版本的进程内路由约束**，不是官方通用 owner 认证 API，也不是逐指令意图验证器。实时 turn adapter 依赖经过测试的宿主实现细节，包括 finalization lock。宿主升级必须先通过兼容测试才能启用。同进程/同 UID 中任意恶意代码可以修改运行对象，不在可信本地契约内。其他 Hermes 工具仍能按自身权限访问资源。

## 4. 不支持的模式保持关闭

该 pin 中普通原生 LOCAL 会话和 Python 插件默认在进程内运行。Managed execution 是另一模式：safe/config-only 和 Kanban 会话使用 worker，普通会话也可按宿主限制显式启用 managed worker。这些 worker 使用新的插件模块，不继承内存激活。Hosted Python 插件同样看不到父进程中导入的当前 turn 上下文。

因此不支持 managed worker、hosted-plugin、ACP、消息渠道、委派 child、cron、缺少匹配上下文 ID 的嵌套 `execute_code` RPC，以及缺失/未知 turn 上下文。Slash 激活响应不证明独立配置的 worker 能使用工具。**不要为了启用本功能而关闭已有 isolation/managed-worker 策略。**可以在其独立支持范围内继续使用 `/personal-tasks`，或等待经过审查的跨进程激活/撤销 adapter；这里没有实现后者。

## 5. 验证与后续验收

自动测试使用合成数据和临时 profile，覆盖实际固定插件加载、获准原生 slash 分发、原生 conversation/turn 生命周期、`model_tools.handle_function_call`，以及生命周期、范围、TTL、重放、CAS、撤销/卸载和拒绝用例。原生运行提供其真实上下文对象；仅单元 fixture 不能证明真实性。未使用 provider API、凭据、监听器、麦克风或真实模型请求，历史被拒绝的身份 socket 用例未触碰。

仍需：在符合条件的测试会话中安装经审阅 pin，选择工具集/模型，验收自然语言录入 → 项目查询 → 编辑/完成、禁用后拒绝以及有用错误提示。若已获授权，可用已有配置的 provider。需要新 key 时，先说明具体 provider/用途并请求安全配置；不要把 key 放入聊天、commit 或 fixture。进程内测试不认证完整 GUI/传输、多进程隔离或生产部署。

## 6. 固定宿主证据

Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`：

- [插件注册](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py)：profile 范围工具、命令及卸载生命周期。
- [原生 turn façade](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_facade.py) 与[turn/lease runtime](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/relay_runtime.py)：真实上下文 turn、profile/session 绑定及 finalization。
- [模型工具分发](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/model_tools.py) 与[会话上下文](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_context.py)：dispatcher ID 和不回退环境变量的 route getter。
- [Managed execution 选择](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_managed_worker.py)：普通默认值与显式/safe/worker 模式。

写工具还通过 `capture_plan` 支持[原子化项目计划](47-atomic-project-plans-zh.md)：同一标签下 1–20 条任务，共用一个必需重试键，不会部分录入。复用已有写激活，不执行任务，也不启动第二个模型。
