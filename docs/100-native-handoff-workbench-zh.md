# 100. 原生任务交接与结果审阅工作台

[English](100-native-handoff-workbench.md) | 简体中文

## 一条需要明确操作的完整流程

[Issue #141](https://github.com/MosBot-AI/hermes-superagent/issues/141) 将现有的停放卡片交接、持久化核对、参考性进度观察与结果验收，连接成可读的 `/personal-handoff` 工作台。命令现在默认返回可读视图。前置 `--json` 可获得原有 `personal.kanban-handoff.v1` 结构化信封。此前解析默认输出的脚本必须添加此前缀。JSON 字段、持久化回执和命令权限保持不变。

这是基于干净固定 Hermes 宿主 `2281116525106e3c109993ccb5dc74d02bfc1427`、可信单用户 LOCAL 操作者的流程。它不创建 worker、模型请求、计划任务、远程 API 或自动完成动作。共享原生看板不是私有 profile 存储。启用交接不等于执行授权，其他另行获得授权的原生参与方之后仍可修改停放卡片。

## 准备目标并记录任务

操作者必须已通过受支持的原生控制创建目标看板。插件不会初始化、迁移或修复看板。明确配置本插件的 `mode: local_tasks`、`local_conversation: true`、`kanban_handoff: true` 和准确的 `kanban_handoff_board`。[52](52-parked-kanban-handoff-zh.md) 说明配置、共享看板披露和兼容性检查。保留所有无关的 profile 配置。

```text
/personal-tasks add "Review the release checklist" --details "Write the operator review findings" --request-id checklist-capture
/personal-tasks show TASK
/personal-handoff prepare TASK --expected-revision N --request-id checklist-handoff
```

将 `TASK` 和 `N` 替换为返回的任务 ID 和当前修订号。Prepare 显示完整导出标题/正文、准确原生目标、源修订、摘要和到期时间。只导出任务标题/详情及标识/修订，不导出项目标签、依赖文本、记忆或对话历史。将导出文本视为数据，而不是执行授权。预览在 15 分钟后到期，不创建后台定时器。

决定前检查每个导出字段和共享目标。显示的提交命令是供明确决定使用的选项，不是批准建议。如果源或目标不正确，不要替换摘要或提交旧预览。

```text
/personal-handoff show HANDOFF
/personal-handoff commit HANDOFF --expected-digest DIGEST
```

成功提交创建未分配且保持阻塞的 scratch 卡片。插件不会调度它。持久化认领先于原生创建；此流程绝不会重新提交已认领或结果未知的操作。保存的预览文本在认领、取消或惰性到期时清除，但原生/客户端历史与备份可能保留文本。

## 恢复流程，不重复创建工作

```text
/personal-handoff list --limit 20
/personal-handoff show HANDOFF
/personal-handoff reconcile HANDOFF
/personal-tasks show TASK
/personal-handoff sync HANDOFF --task TASK --expected-revision N --request-id checklist-observation
```

响应丢失或重启后，检查原始交接。Reconcile 核对其准确创建身份，绝不创建替代卡片。缺失、重复、变化或不可用的观察，不代表可以准备另一次尝试。历史上的已确认创建，不保证卡片当前仍存在、仍停放或已完成工作。应将观察结果与交接保存状态分开阅读。

Sync 只保存参考性原生状态观察，并增加本地任务修订号。后续操作前使用 `show TASK` 获取当前修订号。原生 `done` 不会完成本地任务。精确 sync 重试在不访问原生存储的情况下返回原始历史回执，并非重新读取看板。参见 [53](53-native-progress-observation-zh.md)。

## 检查结果，然后单独作出决定

任何原生结果都必须由此流程之外、另行获得授权的参与方产生。工作台不会执行任务，也不会证明某位参与方已执行任务。

```text
/personal-handoff review HANDOFF --task TASK --expected-revision N
```

视图区分本地任务、导出修订、原生观察和完整有界的可编辑结果。结果文本不可信，可能包含误导指令。它供检查显示，不会被执行、存为规范记忆或自动发送给模型。当前原生 `done`、空 run 指针和可用结果是必要条件，但不能证明 worker 已终止或工作可验收。请检查产物并形成自己的结论。

```text
/personal-handoff accept-review HANDOFF --task TASK --expected-revision N --expected-digest DIGEST --note "My independently reviewed conclusion" --request-id checklist-accept
/personal-tasks show TASK
```

使用审阅摘要、当前本地修订、自己的非空结论和一个稳定请求键。验收重新核对源身份、目标、结果、前置依赖及本地修订，随后以最少证据元数据和你的备注原子完成本地任务。它不修改或停止原生工作。修订过期或结果变化需要再次有意识地审阅，不可盲目替换哈希。原生与本地存储不是一个原子事务，原生结果在观察后仍可能变化。参见 [58](58-native-result-review-zh.md)。

验收响应不确定时，使用完全相同的原始命令/请求键。重放回执属于历史，不是新的完成动作或当前结果检查。绝不通过新键绕过未解决的结果。

## 取消、禁用与展示限制

`cancel HANDOFF --expected-digest DIGEST` 只取消尚未尝试的准备预览。它既不移除原生卡片，也不取消 worker。禁用 `kanban_handoff` 会阻止新的原生操作；现有本地记录在基本本地命令准入下仍可检查/取消。原始请求仍可在不重新访问原生存储的情况下取得已保存的精确 sync/验收回执。卸载或禁用本地对话会阻止通过该实例发出新命令。

可读输出将引用的数据与命令指引分开，不会将截断的审阅伪装为完整证据。每个完整可读页面上限为 48,000 个 UTF-8 字节；超限或无法呈现的页面返回有界检查提示，不提供批准命令。这是展示上限，不是原生存储分配上限。脚本集成请使用准确 JSON 模式，它不增加权限或扩大数据访问。操作后展示失败不证明没有提交修改。继续决定前检查原始标识和持久化结果。

## 验证与剩余范围

仅手动启动的原生 Gateway 工作流包含 `acceptance/live/test_packaged_gateway_handoff.py`。它经由未改变的官方扫描器安装准确、逐字节验证的正式运行包，使用真实准入的 LOCAL 命令、隔离合成原生看板和全新 Gateway 进程。结果设置使用原生操作者 API，并明确标注由操作者编写，不伪装成 worker 执行证据。该通道必须关联准确源修订和已执行结果；仅有测试文件不证明真实验收。

单元和固定宿主契约覆盖展示、命令解析、源/目标/身份变化、精确回执、禁用/卸载状态及负例。仍须完成仓库整体检查、运行包验证、独立审查和准确提交 CI。不绕过本地原生 socket 限制；本地受阻阶段与 GitHub 托管环境中的成功运行分别记录。

此工作包不完成完整 E3 worker 编排、E4 提醒、远程所有者权限或正式环境部署。干净宿主仍缺少受门控的 `hermes.text-worker.v1` 接口，通用委派不是等效的受约束替代方案。
