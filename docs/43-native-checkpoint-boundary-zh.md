# 43. 原生检查点证据边界

[English](43-native-checkpoint-boundary.md) | 简体中文

状态：已实现固定宿主版本的兼容性测试和内部无 I/O 证据准备器。**未启用原生 checkpoint-v2、自动摄取、来源解析器或运行时配置。** 可选[原生召回 provider](41-native-memory-recall-zh.md) 仍为 API v1。本切片明确能力边界，不代表端到端记忆检查点已完成。

## 1. 固定宿主实际提供的能力

测试使用的 Hermes commit 为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。

- 原生消息具有持久化的 `message_uid`，重开存储后保持不变；相同文本的不同消息仍有不同身份。物理行 ID 不能替代这些逻辑身份。
- 原生合并记录保留首个组成消息的 UID，并在 `_absorbed_message_uids` 中记录其他有身份的组成消息。恢复会话时，相邻两个用户行可能合并成一个回调候选。
- 公共 `SessionDB` API 支持只读访问和 `conversation_revision()`。改写正文保留 UID，但会改变 revision；压缩也会改变 revision。
- 压缩前的原生规范化选择用户/助手直接正文，移除派生摘要和纯工具消息，并去掉助手工具调用。其他字典字段可能保留，包括 UID、合并来源、`api_content` 和显示元数据。manager 移除被拦截 prompt 的元数据并执行通常的清理。
- provider 可以显式声明 checkpoint API v2，严格门禁会传播其失败。任何正常返回都视为成功，包括无操作测试 provider 返回空字符串；宿主不验证返回的持久 receipt。

这些能力确实存在，不能将其描述成宿主 API 缺失。问题在于这些能力与回调所收到证据之间的关系。

## 2. 当前交接为何不足以满足本项目

回调收到规范化消息字典和 `require_checkpoint`，没有与压缩提交栅栏绑定的来源快照、来源 revision、持久化/解析接口或检查点 receipt。初始化中的会话/profile 信息不能认证后来每个消息字典。

普通 preflight 可能包含尚未持久化的当前用户消息。parent-adoption 仅在持久父会话比内存历史更长时才刷入待存输入。provider 不能假定每次回调都已有完整持久覆盖。更隐蔽的是，原生合并记录会忽略没有 UID 的组成消息：合并结果可能带着有效的已存 UID，却含有额外的未存正文。仅凭 UID 格式有效绝不能通过来源验证。

provider 可以独立读取 `SessionDB`，解析精确正文并拒绝缺失或不匹配的候选。这是实现更窄的“仅已存来源”子集的可行基础，但不会持久化待存输入，不能将读取与后续原生提交原子绑定，不能保证来源保留，也无法恢复被排除的工具/效果/审批证据。读取两次 revision 不会自动形成这种绑定。另一方面，明确且持久地归档收到正文的 provider 可以实现宿主更窄的 v2 承诺；本项目不会为此悄悄引入第二份原始对话归档。

其他边界也已测试：非主上下文仍可能调用该 hook；manager 切换会话不会独立验证传入消息的来源会话；异步 sync 队列显示 drained 时，仍可能存在 provider 写入失败。原生 `codex_app_server` 模式仍不支持严格检查点。这些结果均不授权绕过隔离或更改已选模型。

## 3. 已实现的有界准备

`personal_agent.checkpoint_evidence.prepare_checkpoint_evidence()` 接收已经规范化的直接消息候选，不执行 I/O，不注册回调/工具，已交付的 provider 也不调用它。输出是供未来来源核对使用的不可变内存候选，不是记忆事实或持久 receipt。

准备器要求非空纯文本、用户/助手角色、32 位小写十六进制 UID，以及无歧义的有序合并来源。它拒绝摘要、工具调用、无效 Unicode、缺失身份、重复或重叠身份。上限为 256 个候选、每条 16,384 字符、总共 65,536 字符、1,024 个来源身份。超限或不支持的证据直接失败，不静默截断覆盖范围。

仅保留直接正文、角色、逻辑身份和正文 SHA-256 摘要，不复制显示字段、API prompt sidecar、推理、声称的作者、会话或权限。摘要供以后比较候选正文，不能证明作者或持久化。候选对象含有私人文本，不能被记录到日志或作为可信指令发送给模型。独立的元数据诊断仅公开计数，并明确报告 `source_verification: not_performed`、`durable_checkpoint: false` 和 `automatic_ingestion: false`。

准备器有意接受一部分“UID 有效但含待存合并正文”候选的*结构*，同时继续标记未验证。未来解析器必须拒绝其来源正文不匹配。单独准备候选绝不能推进游标、发布记忆、授权写入或满足原生 v2 门禁。本切片不会持久化来源正文或内容摘要。

## 4. 最小下一步集成契约

通用的来源引用检查点需要宿主负责的交接：

1. 在宣称持久覆盖前，持久化每个符合条件的待存来源，或明确分类其处置方式。
2. 提供限定范围的不可变来源引用、完整合并覆盖、来源 revision 和明确的待存来源状态。另行标明项目更广契约要求的工具/效果/审批引用。
3. 将覆盖验证和来源保留与压缩提交栅栏绑定，并能识别中止/重试结果。provider 返回字符串或无关的本地元数据标记不足以满足要求。

可以复用已有 UID、revision 和压缩事务机制，无须复制宿主对话存储。这仍是提案，不是已修改或验证的宿主 API。provider 侧仍需完成明确的采集/保留 opt-in、profile/会话/上下文准入、精确来源核对、有界事务 receipt、幂等性、撤销/遗忘竞态，以及未知提交后的恢复。只读召回 opt-in 不等于允许自动采集或额外向模型 provider 分享数据。

在这些契约实现并通过测试前，provider 保持 API v1，严格检查点要求继续失败关闭。不能仅增加一个开关便声称具备 v2 持久保证。E0.9 和 E2.8 均未完成。

## 5. 验证与证据

单元测试覆盖不可变准备、Unicode、字段排除、摘要行为、仅元数据诊断、歧义和全部上限。原生契约测试运行真实 manager/规范化器/SessionDB，覆盖稳定身份、恢复时合并来源、普通未刷入尾部、缺失组成身份的合并尾部、改写/压缩 revision、无操作 v2 被接受、错误传播、上下文/会话范围、异步 sync 失败和 app-server 拒绝。门禁错误测试仅证明回调失败传播且输入不变，不是完整压缩事务回滚证明。

所有输入均为合成数据，存储位于临时目录。测试不调用模型，不使用个人账号或生产 profile，不开启 Gateway 监听，不修改宿主源码或远程仓库。本切片不改变已有记忆 schema 或运行时能力。

固定来源：[身份与合并记录](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/message_metadata.py)、[公共对话读取与 revision](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_state_messages.py)、[压缩和待存尾部顺序](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/conversation_compression.py)、[manager 检查点处理](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py)、[provider API 文档](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/memory-provider-plugin.md)。
