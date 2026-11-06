# Profile 优先的本地任务对话

[English](28-profile-first-local-conversations.md) | 简体中文

状态：已实现显式启用的确定性命令切片，尚不是完整的对话式个人助手。这是用户同意的首条产品路径。主 Bot 选择、可信远程 owner 登记、手机 API 和语音仍是独立的后续能力。

后续实现见[会话范围任务工具](29-session-scoped-task-tools-zh.md)。本篇仍记录确定性命令路径；模型工具另需配置和会话激活，不能把本篇默认配置视作已经启用模型读取。

## 1. 产品决策与信任边界

在已有 Hermes 原生本地会话中管理所选 profile 的本地任务，无须先选择 Bot、发现 canonical Bot Chat 或激活尚未完成的远程 owner 协议。仍由一个 Hermes 主 agent 负责；本插件不新增 agent loop、网关、登录、监听器或第二套排程器。

部署契约是**一个可信用户控制本地 Hermes 安装及所选 profile**。`mode: local_tasks` 加 `local_conversation: true` 明确启用通过注册命令访问该 profile 的插件任务库。Profile 是配置/存储分区，**不是经过认证的人**。待确认登记与带栅栏读取准入核心仍未接线，用于未来可信 owner 路线；这些命令不伪造登记、不签发 grant，也不声称那些门禁已通过。

固定版本宿主中，正常 CLI/TUI/原生会话命令通过已有网关的原生 `LOCAL` 会话 authority 执行。分发给插件前，宿主检查 session read/control 权限、owner 或 operator 访问、已注册的实时本地 source 以及开放的 admission。插件随后筛选支持的 source 结构，并检查绑定的 profile/配置。公开 `platform`、`user_id`、`session_id` 和 profile 字符串是路由信息，不是凭据。

**`LOCAL` 不证明物理本地性。** 已获宿主授权的会话 owner/operator 控制端共享此访问能力，包括宿主通过既有传输完成认证的控制端。公开插件回调无法独立将其与原生终端区分。不要在对外暴露、共享或多用户网关启用此功能，也不要认为它能阻断所有已授权自动化/控制端。本功能不创建或扩大宿主的远程认证面。非 LOCAL 消息回调、bot、relay、thread 及含糊的 source 结构会被拒绝。恶意同进程/同 UID 代码不在此信任边界内。

## 2. 启用已有会话入口

使用[开发环境说明](../README-zh.md#开发验证)中的固定已测试 Hermes checkout、临时 profile 和经审阅的完整插件 commit pin。保留所有已有配置条目。新增的插件设置如下：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
```

两项设置缺一不可；新增标志默认 `false`，只接受精确布尔值，与 `read_only` 同用视为非法。以该 profile 加载/重载插件，再打开已有 Hermes 原生本地 CLI/TUI 会话。命令本身不需要 Bot 绑定或 API Key。若宿主启动正常 UI 另需配置模型，该前置条件不由插件提供，也不构成命令调用模型的证据。

在会话中输入 `/personal-tasks help`。注册命令直接返回一份 JSON，不启动 agent turn，也不自动将任务内容附加到模型上下文。向命令参数或结果放入敏感文本前，请阅读宿主 UI 自身的历史/日志规则；本插件无法保证外围界面绝不记录显示内容。

当前运行验证针对 `plugins.isolation: in_process`。进程内测试不构成 hosted-plugin/桌面传输端到端执行认证。不要为了试用而关闭已有隔离设置或对外暴露服务器。旧式直接 CLI 回调仅作为兼容回退支持，不是固定版本正常 CLI/TUI 的路径。

## 3. 有用的任务与项目闭环

在所选 profile 的原生本地对话中执行：

```text
/personal-tasks add "Prepare demo" --project "Personal Agent" --due-date 2026-11-10 --request-id demo-add-1
/personal-tasks list --project "Personal Agent"
/personal-tasks projects
/personal-tasks search "demo"
/personal-tasks agenda --on 2026-11-10
```

新增/列表响应包含 `id` 和 `revision`。用实际返回值替换下方占位符：

```text
/personal-tasks show TASK_ID
/personal-tasks update TASK_ID --expected-revision 1 --details "Use the local conversation demo" --request-id demo-edit-1
/personal-tasks done TASK_ID --expected-revision 2 --note "Demo prepared" --request-id demo-done-1
/personal-tasks projects
/personal-tasks list --state all --project "Personal Agent"
```

`add` 是 `capture` 别名，`done` 是 `complete` 别名。`cancel` 与完成操作使用同样的 ID/revision/note 结构。项目名是大小写敏感、精确匹配的**任务标签**，不是原生 Hermes Project 实体或权限范围。沿用已有[项目分组](24-local-project-groups-zh.md)、[检索](22-local-task-search-zh.md)、[agenda](17-local-task-agenda-zh.md) 和[任务存储](16-local-task-inbox-zh.md)语义。日期是显式纯日期值，不从自然语言或时钟推断。

所有支持平台的参数均使用 POSIX 风格引号。以短横线开头的标题可用 `capture --title=-draft`。`help` 列出完整选项。输入上限为 32,768 字符和 256 token；读取页保持原有大小限制。JSON 转义终端控制字符和非 ASCII 字符；客户端可解码这些转义后显示。

## 4. 修改、重试和配置语义

所有修改复用已有 schema-v3 任务事务、请求 digest 和 receipt。编辑及终态变更要求 `--expected-revision`；完成/取消还要求明确 note。旧 revision 会失败，不静默覆盖另一条命令的结果。已完成/已取消任务不可编辑。

写入支持 `--request-id`。省略时生成新 key，并以 `request_id` 返回；解析成功后即使存储失败，也返回该 key。同 key 同 payload 返回已保存回执，变更 payload 会冲突。新 key 可能创建重复任务。结果不确定时，使用返回 key 和完全相同的命令手动重试，不要换新 key；不会自动重试。若响应丢失，尚未看到自动生成 key，应先查看任务列表再决定是否重提；显式 key 可避免这种含糊。

打开任务存储前，命令重新检查当前可见的 mode/flag 和绑定 profile home。回调观察到禁用配置后，会拒绝后续调用。这不是跨进程即时撤权协议：原生 worker 可能保留配置快照，已准入事务也可能完成。应重载/重启相关运行进程，使设置一致生效。禁用/卸载插件会移除注册，不删除任务或回执。

复用 schema-v3 后，任务的历史 `source: local_cli` 标签保持不变；它表示显式本地操作路径，不是经过认证的会话/Bot 来源审计。没有新增来源授权字段。

存储仍位于原有 profile 本地插件数据目录，使用 POSIX 私有文件检查。加载、status 和 help 不创建任务数据库。Windows 存储、加密、原生 Project 同步、提醒投递和保留/遗忘流程仍不可用。这些命令不会限制其他 Hermes 工具。

## 5. API 与失败契约

成功与失败均使用 `personal.local-conversation-tasks.v1`，包含 `scope: trusted_local_conversation`、`request_id`、`status`、`data`、`replayed` 和 `error`。这是 slash-command 结果 schema，**不是新 HTTP API**。

```json
{
  "schema_version": "personal.local-conversation-tasks.v1",
  "scope": "trusted_local_conversation",
  "request_id": null,
  "status": "error",
  "data": null,
  "replayed": false,
  "error": {"code": "unsupported_origin", "retryable": false}
}
```

在读取配置、解析或存储之前检查不支持的来源。通过来源检查的调用仍可能返回 `profile_context_changed`、`invalid_configuration`、`local_conversation_disabled`、正常任务校验/冲突错误或经过脱敏的 `local_tasks_unavailable`。异常不回显私人参数、数据库路径或堆栈。命令拒绝不等于写入成功，也不等于 owner 认证事件。

## 6. 验证与剩余门禁

实现使用临时 profile 中的合成任务测试：解析、命令生命周期、项目计数、持久重放/冲突、revision 拒绝、profile/配置变化、默认关闭注册、不支持来源及有界/脱敏错误。真实固定宿主契约在进程内验证实际插件加载器、原生命令分发组件、已授权 operator 访问及相反环境作用域下的双 profile 隔离，不等于 socket/TUI/桌面实机验收、可信远程 owner 签发或完整 hosted-plugin 集成。历史被拒绝的身份 socket 用例仍未解决，本切片不会重试它们。

未使用真实账号、API 凭据、麦克风、模型 provider 或外部投递。保留正常已有宿主分发与授权契约，不在生产中用伪造 source 替代。全仓检查另行记录精确测试数量；源码审查或合成用例通过不构成已部署服务的认证。

下一步：完成 E6.8 的原生命令验收，再评估 E6.9 会话范围自然语言任务工具，要求明确启用、真实宿主会话来源且无外部副作用。不得仅凭调用方传入 profile 全局注册私人数据工具，也不能静默将所有任务附加到模型上下文。远程/多用户 authority 和主 Bot 绑定仍是有条件的后续路线，见[路线图](08-roadmap-and-acceptance-zh.md)。

## 7. 固定宿主证据

以下引用全部固定于 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`：

- [原生 CLI 网关命令路由](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/gateway_plugin_commands.py)：正常 CLI 路径，而非旧式直接回调。
- [原生命令准入](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_commands.py)：read/control 检查、实时 source 准入和 profile 范围分发。
- [会话 authority](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_authority.py) 与[本地 source 注册](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_local.py)：owner/operator 权限与实时 source 身份检查；LOCAL 也用于经认证的原生传输会话。
- [插件 handler 调用](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/run_inbound_hooks.py)：公开 source/session 字段、实时 source 上下文及保留上下文的 executor。
