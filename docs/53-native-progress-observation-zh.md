# 原生进度的建议性观察

[English](53-native-progress-observation.md) | 简体中文

## 明确同步，不执行工作

`/personal-handoff sync HANDOFF --task TASK --expected-revision N --request-id KEY` 是既有默认关闭 `kanban_handoff` 配置下的操作者命令。它读取有界原生元数据，原子保存一份最新建议性 `native_progress` 快照、本地修订/事件及持久重试回执。绝不改变本地状态、工作状态、进度说明、依赖或完成标记。选择另一份合格交接只替换建议性快照，不增加模型工具、自动同步、worker 派发或原生写入。

新同步需要当前启用、已确认且身份绑定的交接、准确来源任务 UUID，以及仍为 captured 的本地任务预期修订。完全相同的重试在检查交接账本、原生存储或创建启用状态之前返回原始持久回执，即使本地任务已终结。它是历史结果，不是重新观察。冲突复用请求键会被拒绝；原生结果缺失或不明绝不触发重新创建。

## 先持久绑定身份，再观察

原生创建在原生事务提交前，把 `{card_id, created_at, created_event_id}` 保存到交接账本。绑定后崩溃仍表示结果不明，不是再次提交的许可。观察必须匹配卡片 ID、交接键、时间戳及原始创建事件。重复键、卡片替换、键变更或垃圾回收后原始事件缺失，都不能把另一张卡片当作原卡片。这是身份检查，不保证事件水位或全局顺序。

如果创建已提交但响应丢失，其他获授权的原生操作者可能在明确核对之前推进了原卡片。只有准确匹配已持久保存的身份锚点与当前卡片，核对才可以返回 `identity_confirmed`，即使卡片不再停放，也能确认历史创建。这允许后续明确同步，但不宣称仍处于停放状态、执行成功或本地任务完成。身份缺失、重复或不匹配仍会拒绝。

所有已经尝试创建的 v1 记录永久为 `legacy_unbound`，不能同步：事后观察不证明原始创建身份。尚未尝试的 v1 预览可以在将来明确创建时获得身份锚点，不进行隐式接管或重建。

## 展示契约

快照仅含 `handoff_id`、`card_id`、`outcome`、`status`、`observed_at`（UTC epoch 秒）及 `exported_revision`，不回拷原生标题、正文、消息或运行输出。`current` 支持原生 triage、todo、scheduled、ready、running、blocked、review、done、archived 状态。其他结果是 missing、duplicate、identity_changed、key_changed、identity_unavailable；其 status 为 null，绝不保留上次原生状态。

任务详情及有界列表/复盘明确标注 **Native board observed … (not local completion)**。原生 done/review 不会完成或推进本地任务。旧回执缺少字段表示历史未知；当前字段为 null 表示尚未记录观察。新观察只替换建议性快照，不替换原交接或历史回执。状态仅报告配置可用性，不证明原生运行时或真实验收已验证。保存的快照成为本地任务数据，可以由另行激活的任务模型读取工具返回。本功能不增加模型同步动作或提供商调用，也不自动丰富 focus 投影。同步本身会递增本地修订，因此仅比较导出修订与当前修订不能判断正文是否过时。

## 限制

[停放式交接](52-parked-kanban-handoff-zh.md)的来源/schema 检查、共享看板边界及可信宿主导入假设不变。观察采用只读 SQL，但仍可能触发 SQLite WAL 记账。重新检查当前启用和任务 CAS，不代表原生与本地数据库构成同一事务；卡片可能在观察后立即改变。保存时间表示本地观察时刻，不证明持续新鲜或提供商执行。

本里程碑仅有离线夹具覆盖，不宣称安装、真实 Kanban、Gateway 或模型验收通过，现有扫描限制不变。[路线图](08-roadmap-and-acceptance-zh.md)中的 worker 编排和通用任务映射仍未完成。


[原生交接工作台](100-native-handoff-workbench-zh.md) 现在为这条完整操作者流程提供显式 `--text` 可读视图，同时保留默认 JSON 及显式 `--json` 输出。其手动安装包 Gateway 通道与准确源版本执行证据，和本篇原始离线里程碑分别记录。
