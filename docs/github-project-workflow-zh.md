# GitHub Project 执行流程

[English](github-project-workflow.md) | 简体中文

使用 [Hermes Personal Agent Project](https://github.com/orgs/MosBot-AI/projects/2) 和[仓库 Issues](https://github.com/MosBot-AI/hermes-superagent/issues)记录实时研发进度。[路线图](08-roadmap-and-acceptance-zh.md)定义范围、依赖和验收门槛。范围变化时，同步更新 Project 与 Issues。Hermes 运行时的 Projects 和 Kanban 用于跟踪用户在 Hermes 内的事务。

## Issues 与状态

用加入 Project 的仓库 Issue 跟踪史诗、工作包和可独立验收的实现任务。保留史诗和工作包的路线图 ID，以及已有的编号和证据。条件允许时，将旧草稿卡片原地转为 Issue。一个工作包需要多项改动时，把可分别验收的较小任务关联到父 Issue，并保留父项的全部验收条件。

| Project 状态 | 使用条件 |
| --- | --- |
| Backlog | 等待常规依赖满足或范围明确。 |
| Ready | 范围和验收条件明确，适用依赖已有核验证据，且 Issue 可领取。 |
| In Progress | Issue 有当前负责人，工作正在推进。 |
| Blocked | 需要特定外部条件或决定才能推进。记录该条件及验证解除的方法。 |
| In Review | 已关联可评审的 PR，列出已运行的检查和待完成的验收。 |
| Done | 实现已合并，Issue 的所有适用条件已核验，证据已关联，Issue 已按完成关闭。 |

从旧看板迁移的卡片可能基于此前的部分交付继续处于 In Progress。只有 Issue 同时记录负责人及分支、运行记录或活跃 PR 时，才视为当前已认领。

使用现有的 `Epic`、`Delivery milestone`、`Priority`、`Dependencies` 和 `Acceptance evidence` 字段。原生 Issue 关系与依赖说明同时存在时，保持两者一致。所选范围涉及可选模式时，应用相应门槛。取消或重复关闭的 Issue 不能满足依赖。依赖仅涉及较小范围时，关联并核验该部分的验收证据后即可推进，即使范围更广的父项仍开放。

## 领取、实现与核验

1. 检查本地改动，阅读当前 Issue、Project 字段、依赖证据和相关设计。保留已有工作，并从当前 `main` 创建任务分支。
2. 编辑前，领取可用 Issue 并分配给自己，以英文领取评论记录 agent 或运行标识、分支和范围，再设为 In Progress。重新检查归属和状态。Project 更新无法提供原子领取。出现竞争时先明确归属再编辑，接手他人的工作时明确交接。
3. 在任务分支实现，运行适用的[开发验证](../README-zh.md#开发验证)，并用英文在 Issue 记录有实质变化的进度或阻塞。关联证据，注明剩余检查。避免重复发布未变化的状态。
4. 创建面向 `main` 的 PR 并关联 Issue。工作期间可使用草稿 PR，改动和验证结果可供评审时设为 In Review。常规项目变更通过 PR 进入 `main`。只有合并即可满足关联 Issue 的验收条件时，才使用自动关闭关键词。
5. 核对合并后的版本以及当前范围所需的 CI、契约、安全、部署或实际运行验收证据。将链接写入 Issue 和 Project 的 `Acceptance evidence` 字段，将 Issue 按完成关闭，设为 Done，再检查直接下游依赖。待完成的门槛留在 In Review 或 Blocked。已合并的 PR 或离线 CI 运行仅为实际覆盖的工作和检查提供证据。

## 读取实时看板

```sh
gh project view 2 --owner MosBot-AI
gh project item-list 2 --owner MosBot-AI --limit 100 --format json
gh project field-list 2 --owner MosBot-AI --format json
gh issue list --repo MosBot-AI/hermes-superagent --state all --limit 100
```

写入前查询当前的 Issue、Project 条目、字段和状态选项标识。访问失败时，记录无法核验的实时状态。公开的 Issue、PR 和证据中不得包含凭据或私有运行时数据。
