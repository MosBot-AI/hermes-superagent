# 44. 可读的原生任务工作台

[English](44-readable-task-workbench.md) | 简体中文

已实现：在现有本地任务操作上提供可读视图。原生 `/personal-tasks` 命令默认输出文字，不再默认返回 JSON 响应包。任务工具仍使用原有 JSON schema，本地 CLI 仍默认 JSON。这个展示层不新增任务、项目、权限、执行或调度能力。

## 1. 从已有命令开始

沿用可信本地配置与原生会话准入。空命令或 help 展示简短工作流程；下列示例都要求已启用本地任务。

```text
/personal-tasks help
/personal-tasks add "Review the draft" --project "Demo" --request-id draft-1
/personal-tasks review --on 2026-11-07
/personal-tasks list --work-status blocked
/personal-tasks show TASK_ID
/personal-tasks progress TASK_ID --expected-revision N --work-status waiting --note "Waiting for the attachment" --request-id waiting-1
```

使用实际返回的任务 ID/revision，每次有意修改使用独立 key，并提供目标日历日期。文字输出展示准确 ID/revision、已记录进度、项目标签和截止日期。show 及成功修改还会展示已有任务详情和当前进度/完成说明。进度不证明 worker 正在运行。done/cancelled 结果明确表示本地记录变化，不证明现实工作或外部取消已经执行。

存储的标题、标签和多行说明会加引号；嵌入换行和控制字符会转义，不能冒充单独生成的状态行。存储内容仍是不可信数据。加引号不构成模型指令安全边界，本插件也不保护其他 Hermes 工具。初版展示标签为英文，存储的 Unicode 文本保留原样。

## 2. 明确保留机器契约

原生输出有意调整为面向人的视图。此前解析 `/personal-tasks` 输出的脚本应使用开头的 `--json` 选项。它保留原有 `personal.local-conversation-tasks.v1` 响应包，包括早期 profile/来源/配置拒绝及无效命令错误：

```text
/personal-tasks --json list
/personal-tasks --json review --on 2026-11-07
/personal-tasks --json add "Review the draft" --request-id draft-1
hermes personal-agent tasks list
hermes personal-agent tasks list --format text
hermes personal-agent tasks review --on 2026-11-07 --format text
```

有效原生命令后也可附加 `--format json` 或 `--format text`，但它仅在准入后解析。如果调用方需要解析每条原生回复，包括准入前失败，应使用开头的 --json。开头 --json 与 --format text 组合会被拒绝。展示选项不进入存储请求或幂等摘要。CLI 普通 JSON 输出和整数成功/失败退出码不变，生成的 CLI 翻页命令会保留 --format text。

`personal_tasks_read` / `personal_tasks_write` 仍是原有机器接口，不接受展示标记，仍要求明确配置、会话激活和 turn 上下文。选择 JSON 或文字不会激活工具、授权写入、切换 profile 或绕过被拒绝的来源。

## 3. 有界视图与安全后续步骤

列表、搜索、agenda、项目和历史文字视图最多展示 20 条。当存储分页或文字视图还有条目时，More 命令从实际最后展示的条目之后继续。生成的只读命令保留原过滤条件，并将分页数量设为 20。它只是建议，不会自动执行。参数值使用 shell 引号和 --name=value 形式，确保以横线开头的合法标签/查询仍是值而非选项。

每日回顾的四个日期分组各最多展示五条标题摘要，同时保留所有匹配任务的精确日期/进度数量。每组说明未展示多少匹配任务，兼顾原结果预算与额外展示上限。日期窗口之外的未来任务仍只计数。不虚构回顾游标或推断优先级，可用既有 show 和带过滤的 list 深入查看。空页面只说明没有匹配结果，不声称全部工作已经完成。

列表/回顾视图省略任务正文和阻碍说明；show 获取所选任务的完整存储信息。不会悄悄截断完整标题、ID、revision 或已展示说明。文字视图沿用字段上限和条目上限。回顾 max_chars 仍按[40](40-daily-task-review-zh.md)衡量结构化 data，不是可读视图的标点或字符数量。

## 4. 回执、失败与验证

成功修改会展示请求 ID，包括原生命令生成的 key。完全相同的成功重试明确标注为已保存回执重放，可能描述较旧 revision；当前状态请用 show。旧 revision 错误要求先读取并核对，幂等冲突不会建议盲目换 key。错误消息使用稳定脱敏代码，不包含原始异常、本地路径或失败请求中的私人输入。

渲染在原有操作后进行，不增加额外读取、写入、模型/provider 调用、派发、自动重试或远程行动。如果无法渲染意外的旧结果形状，会返回真实的结构化结果，而不是将已提交写入误报为失败。存储 schema、回执、事件、激活和准入不变。

测试覆盖原生文字/JSON 一致、跨格式相同 key 去重、旧回执、终态/进度措辞、明确日期、有界列表/回顾、完整字段、多行文本引号、安全翻页往返及横线开头标签、不解析私人命令的早期拒绝、CLI 退出码和不变的模型工具 JSON。固定宿主测试实际调用原生命令入口。测试使用合成临时 profile 和网络保护，实际 GUI/手机渲染及真实 provider 自然语言任务编排仍未验证。
