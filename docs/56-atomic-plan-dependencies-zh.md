# 原子计划中的明确依赖

[English](56-atomic-plan-dependencies.md) | 简体中文

## 同一批次，明确前置关系

`capture_plan` 现在允许每条任务带可选 `depends_on` 列表。数字是**同一次提交批次内从 1 开始的位置**，不是任务 UUID 或优先级。允许引用后面的任务。排列顺序本身不创建依赖；省略 `depends_on` 与 `[]` 归一化为原有无边行为。

```text
/personal-tasks plan --project "Launch" --tasks-json '[{"title":"Draft"},{"title":"Review","depends_on":[1]},{"title":"Publish","depends_on":[2]}]' --request-id launch-with-links-1
```

既有 CLI 接受相同 `plan --tasks-json` 参数。既有明确写入激活之后，`personal_tasks_write` 的 `capture_plan` 接受相同逐项字段。不新增独立规划模型或激活机制。按 shell/客户端正确引用；`--tasks-json` 是内联数组，不是文件路径。

N 条任务的批次仅接受 1 至 N 的整数位置，拒绝布尔值、重复、自引用、批次外引用或环。全部任务共享明确选定的项目标签。引用已有任务仍使用单独明确的[依赖编辑流程](51-project-task-dependencies-zh.md)，不从任务文字推断关系。

## 原子存储与既有门控

所有新任务、依赖边、初始元数据事件及共享回执一起提交或全部不提交。当前任务 schema 仍为 v6，本切片不新增迁移。历史无边计划回执仍只是历史结果。不确定响应后复用相同请求 ID 及相同归一化计划，不另造批次。

既有 `ready` 查询及开始/完成检查会立即考虑保存的前置关系。只有标记 done 的前置才满足依赖，取消不等于成功。保存计划不会把工作标记为 blocked、启动 worker、完成任务、创建原生 Kanban 卡片或安排提醒。返回计划是本地记录，不是执行计划的许可。

## 验收范围

本功能使用既有干净固定宿主的命令、CLI 及已激活模型写入入口，不增加宿主补丁、安装重试、提供商请求、真实模型验收或 Gateway 动作。以离线夹具检验实现，此处不声明数字或真实验收通过。[原子计划捕获](47-atomic-project-plans-zh.md)及[项目依赖](51-project-task-dependencies-zh.md)记录此前切片；[路线图](08-roadmap-and-acceptance-zh.md)保留未完成编排门槛。
