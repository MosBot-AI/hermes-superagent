# 32. 会话范围的记忆模型工具

[English](32-session-scoped-memory-tools.md) | 简体中文

状态：已实现对[本地记录](31-explicit-local-memory-zh.md)的显式开启模型工具访问，复用[任务工具](29-session-scoped-task-tools-zh.md)所用固定版本的原生进程内 turn 边界。真实 provider 的自然语言验收仍待完成。这不实现 [30](30-pluggable-memory-contracts-zh.md) 中的原生 MemoryProvider 桥接、自动提取/prefetch、向量嵌入或第三方后端加载。

## 1. 显式配置与独立激活

在已测试的可信单用户 profile 中保留已有配置，并显式开启：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
        local_memory: true
        memory_model_tools: true
```

`memory_model_tools` 默认 `false`，要求另外三项设置，仅接受布尔值。`local_model_tools` 是独立的任务工具选项，此处不要求。加载会在已有 `personal_agent` 工具集中注册 `personal_memory_read` 与 `personal_memory_write`，但不打开记忆存储或激活会话。通过宿主正常控件选择工具集，并按要求重载/启动会话。

使用原生会话命令：

```text
/personal-memory-tools enable-read
/personal-memory-tools enable-write
/personal-memory-tools status
/personal-memory-tools disable
```

读权限允许本地有界记忆数据进入本会话已配置的模型。写权限另允许本地记住/更正/遗忘。两者均持续 30 分钟，每个已加载记忆工具实例最多激活 64 个会话。Status 不续期；写权限后启用读权限会降级。状态仅在内存中，绑定精确 profile/session/route，重载、卸载或进程重启均会清除。

**任务与记忆权限相互独立。** `/personal-tools` 不能授予记忆访问权，`/personal-memory-tools` 不能授予任务访问权。关闭一个不会改变另一个独立选定的激活状态。两者都不授予远程权限，也不修改其他 Hermes 工具。

## 2. 自然语言路径与工具契约

写激活后，可让已有模型记住偏好、查找、更正和遗忘，例如“记住我偏好简洁的中文摘要”，再问“查一下我的摘要偏好”。这是发给已配置模型的操作员请求，不代表已验证每个模型都会选择正确工具。应检查返回回执并读回记录，而不是仅接受口头“我记住了”。

- `personal_memory_read`：`list`、`show`、`search`，不向模型提供 export。每页最多 50 条，查询最多 128 字符，为区分大小写的字面匹配，不是语义搜索。
- `personal_memory_write`：`remember`、`correct`、`forget`。每次修改要求稳定 `request_id`；更正/遗忘要求从读取获得的真实记录 ID 和当前 `expected_revision`，更正可改内容和/或主题。
- 未知、无关及 owner/profile/session/source/approval 字段均被拒绝。模型不能选择存储路径或冒称操作员来源。内容上限仍为 2,048 字符，主题为 128 字符。
- Schema 提示模型只执行明确要求的修改，不从任意文字推断长期偏好或 grant。但准入边界仍是已激活会话，不是对每条新人工指令的确定性证明。

合成调用示例：

```json
{"action":"remember","content":"Use concise Chinese summaries","topic":"preference","request_id":"summary-preference-1"}
```

响应采用 `personal.session-memory-tools.v1`，带 status/data/error、request ID 和 replay 标记。修改回执只是仅元数据的历史证据。遗忘后重放旧成功 remember 会返回旧回执，但不会恢复内容，描述当前状态前应重新读取。同一 key 下改变 payload 会冲突，新的显式 key 可以创建新记录。没有自动重试，也不宣称遗忘等于全局擦除。

## 3. 模型来源与存储升级

模型创建/更正的记录使用 `source: activated_session_model`，直接 `/personal-memory` 编辑使用 `explicit_local_operator`。这表示**最近编辑的入口**，不是经验证的原始说话者或独立事实核查。模型写的记录不会因为内容说“用户已批准”就变成 owner 权限。读取显示来源区别。重放旧回执不会改写当前记录或其来源。

打开存储时由适配器绑定 `source_kind`，不是由工具参数提供。精确自有记忆 schema 在 namespace/schema/application 检查后，于写事务中原子地从 v1 升到 v2；保留记录 ID、revision、tombstone、顺序高水位、事件行及精确 receipt 字节/digest。未知 schema、外来数据库或变化的 namespace 会被拒绝，而不是被接管。仅修改插件记忆 DB，不修改原生记忆或任务 DB。

首次受支持的打开可能迁移 v1 DB，读取命令也可能触发。升级前备份私有插件数据；旧代码会拒绝 v2，不能把回滚代码当作数据降级。跨 profile 恢复/迁移与完整可移植恢复仍不支持。不要通过旧备份覆盖当前数据来回滚，否则可能复活已遗忘内容。

## 4. 准入、撤权与隐私

每次工具调用，包括直接 registry 分发，都会检查固定宿主的真实 active turn、dispatcher task/session ID、profile lease、支持的 `cli`/`tui`/`desktop` 平台、无 parent/delegated/cron 上下文、精确绑定 route、当前配置及未过期的记忆激活。Schema 可见不等于授权；只有复制 session ID 或 source 对象而没有真实上下文，不能激活或访问存储。

共用机制保留锁顺序：真实 turn finalization lock，然后是该功能的 activation lock，并持有到有界存储操作结束。Disable/卸载阻止之后准入，之前已准入事务仍可能完成。过期同样只影响之后准入，不执行回滚。任务和记忆拥有不同激活对象与锁。读取配置不意味着跨进程策略立即传播，应按宿主流程重载。

**已激活会话中的所有模型活动及已准入控制端共享访问。** 这不是逐消息人工意图证明，也不能防御任意同进程代码或为其他 Hermes 工具提供沙箱。如果担心该范围内的提示注入或模型错误选择，应使用只读激活或直接命令，不能宣称插件已证明用户意图。

工具返回的记忆内容和 source/session 引用进入已有配置模型的上下文和正常宿主历史，可能产生普通 provider 费用，但不增加第二个模型或切换 provider。遗忘清除权威 payload 和之后的插件检索，不能撤回已发送上下文、宿主历史、provider 保留、备份或已交付导出。保留的 digest/ID 仍可能是个人元数据。只有允许该模型与会话接收这些记录时才激活。

## 5. 不支持模式与验证

仅支持已测试的普通原生进程内模式。Managed worker 与 hosted plugin 不继承父进程的内存激活/turn 上下文；委派/cron/远程消息入口及缺少上下文的代码执行 RPC 仍被拒绝。不要为使用本功能而关闭隔离。Profile 仍是存储/配置分区，不是人的身份；不要把本地模式部署到公开或共享多用户 gateway。

测试使用合成记录、临时 profile，以及真实固定版本的 slash/SessionAuthority 准入、TurnFacade 生命周期与 `model_tools.handle_function_call`，不连接真实模型。覆盖任务/记忆独立激活、读写降级、TTL/session/route/profile 不匹配、finalization 竞态、关闭/卸载/重载、来源标签、校验、CAS、遗忘后重放、精确 v1 迁移与回滚。已有任务工具和直接记忆命令回归也通过。历史受限的九个身份 socket 用例未重跑。

真实自然语言验收仍需符合条件的会话、明确选择的 provider/model，以及在必要时安全配置凭据。这些测试不隐含 API Key 配置、凭据保存、收费请求或生产部署。使用真实个人记录前，应先用合成数据验收“记住 → 查询 → 更正 → 遗忘 → 关闭后拒绝”。本切片推进本地 E2.6/E2.7；E0.9 完整原生 provider 矩阵及 E2.8 自动生命周期集成仍为独立门禁。
