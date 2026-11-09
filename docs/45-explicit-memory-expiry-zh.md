# 45. 显式记忆到期

[English](45-explicit-memory-expiry.md) | 简体中文

显式到期为本地记忆记录增加按时间判断的召回资格边界，不安排删除、不推断保留期，也不激活 provider。已有[本地记忆开启条件](31-explicit-local-memory-zh.md)、[模型工具激活](32-session-scoped-memory-tools-zh.md)及[原生 provider 准入](41-native-memory-recall-zh.md)仍各自适用。

后续能力：[经审核的已到期记忆清理](73-reviewed-expired-memory-cleanup-zh.md)增加显式、有界的预览后批量遗忘。仅经过截止点仍不会删除正文；每一批都需要已审核快照和独立的操作人员动作。

## 1. 保存临时旅行计划

以下合成示例使用明确 UTC 截止时间。请自行选择实际截止时间；“旅行结束前”这样的短语不提供时间戳。后续操作使用实际返回的记录 ID 和最新 revision，而非下方占位符。

```text
/personal-memory remember "Trip plan: take the airport train" --topic trip --expires-at 2026-12-01T18:00:00Z --request-id trip-plan-1
/personal-memory show RECORD_ID
/personal-memory correct RECORD_ID --expires-at 2026-12-02T18:00:00Z --expected-revision N --request-id trip-plan-2
/personal-memory list --include-expired
/personal-memory search "Trip plan" --include-expired
/personal-memory correct RECORD_ID --clear-expiry --expected-revision N --request-id trip-plan-3
/personal-memory forget RECORD_ID --expected-revision N --request-id trip-plan-4
```

截止前，旅行备注可以进入普通搜索和召回；到达截止时间后，不再进入普通 list/search 或新的召回。可用 show 或显式 --include-expired 检查。如果旅行延长，可更正截止时间。只有希望备注重新获得不受期限限制的资格时，才清除到期时间。要移除权威存储中的正文，而非只从召回中隐藏，应使用 forget。

--expires-at 只接受有效、规范的 UTC 秒时间戳 YYYY-MM-DDTHH:MM:SSZ。仅日期、本地时间、数字时区偏移、小数秒和相对时长均被拒绝。过去的截止时间合法，会使记录立即失去资格。不推断 TTL。correct 可只修改到期时间，也可同时修改正文/主题；--expires-at 与 --clear-expiry 互斥。更正时省略到期字段会保留原值，remember 时省略则没有到期时间。

## 2. 模型工具与检查

独立激活的记忆写工具在 remember/correct 上接受可选 expires_at：规范 UTC 字符串用于设置，JSON null 用于清除。更正时省略会保留目标记录的原到期时间；remember 默认为无到期时间。记录期限与工具会话的激活 TTL 不同，彼此不会延长。模型不得编造截止时间或悄悄清除它。

读工具仅在显式 list/search 检查中接受 include_expired: true，默认 false。原生命令对应使用 --include-expired。show 和 export 无需该选项便包含已到期记录，已有墓碑行为不变。有界召回和原生 provider 均不提供包含已到期记录的覆盖选项。

记录行增加 expires_at（字符串或 null）及计算出的 expired（布尔值）。记录页面与召回结果增加 evaluated_at，表示该操作捕获的 UTC 墙上时钟评估时间。这些是现有 runtime v1 API 及 personal.memory.record_page.v1 导出契约的增量字段。导出仍有界、restorable: false，不能作为可移植备份。修改回执仍是仅含元数据的历史回执，不是当前召回资格的回读。

## 3. 时间不是存储状态转换

active 记录在 expires_at <= evaluated_at 时到期。每次操作在实际取得 SQLite 快照后，只捕获一次可信 UTC 墙上时钟时间，避免等待锁后仍使用等待前的过时时间；调用方不能提供评估时间。过滤和计算标记同时依据该时间与操作的数据库快照。普通 list/search 排除已到期记录；显式有界召回与原生 provider 召回始终在排序和预算计算前排除它们。

存储状态仍是 active 或 forgotten。时间经过截止点不会生成 revision、事件、回执、后台任务、调度器或 daemon，正文仍保留在存储中。墙上时钟回拨可使仍为 active 的记录重新获得资格，因此到期不是不可逆删除保证。延长或清除期限属于显式、检查 revision 的写操作，可以恢复资格。forgotten ID 是终态，不能通过更正复活。遗忘会同时清除到期时间和权威正文。

到期操作不擦除已有宿主会话历史、返回结果、导出、备份或模型 provider 副本。在到期前返回的召回包，截止后仍可能留在模型上下文与宿主历史中。排除新的召回不承诺撤回此前披露，也不承诺阻止未来重放旧上下文。

## 4. 迁移、重试与适配器兼容

本地自有 SQLite 存储采用 schema v5。获准打开存储的命令或已经激活的模型工具操作，会对精确匹配的自有 v1–v4 存储进行原子升级，保留已有事件、修改回执、消费游标及检查点回执。建议操作员使用 /personal-memory list 主动完成升级。已有记录初始无到期时间。不支持或畸形存储会封闭拒绝；迁移不是跨 profile 导入或修复流程。

原生只读 provider 永远不创建或迁移存储。它拒绝旧 schema，直到获准打开存储的命令或已激活的模型工具操作完成升级，之后新的合规召回才能恢复。本功能不安装或选择 provider，不修改配置、切换模型或更改凭据。

显式新请求字段要求可选的 record_expiry 适配器能力，包括显式传入 null 或 false。缺少能力的旧适配器不会被悄悄传入新字段。省略新字段的旧请求保留原有请求摘要与重放行为。修改结果不确定时，复用相同 request ID 与完全相同的载荷；旧 key 配不同载荷会冲突。更正和遗忘仍要求 expected_revision；冲突后先读取当前状态，不要盲目重试。

## 5. 检查点与验收边界

[本地元数据检查点](39-local-memory-checkpoints-zh.md)覆盖存储的 revision、事件与状态，不覆盖具有时间有效性的召回资格。仅时间流逝未必使检查点过时。检查点不证明所捕获的每条 active 记录仍可召回，也不是备份或原生会话覆盖保证。

到期验收应覆盖截止点相等、未来/过去/null 值、省略与清除的更正差异、显式检查、召回排除与预算、遗忘终态、时钟回拨、旧回执重放、原子迁移及只读入口拒绝旧 schema。使用合成 profile 和可控时钟，分别报告实际单元/原生测试结果；本指南不声称最终验收数量或真实 provider 结果。

严格原生 checkpoint-v2、自动摄取、来源对账、原生 worker 编排及真实 provider 自然语言验收仍未实现或未验证。到期功能不代表完整记忆路线图完成，也不放宽已有隐私/准入门槛。
