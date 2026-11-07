# 24. 本地项目分组

[English](24-local-project-groups.md) | 简体中文

**已实现的开发切片：显式本地任务分组与进度计数。** 受信任的本地操作者可以用单个项目标签整理已有收件箱、筛选任务并查看各组当前计数。这不是 Hermes 原生 Project、Kanban 看板、worker 分派、权限范围，也不代表完整个人助手 MVP。

此功能在同一固定 Hermes 基线上扩展[本地收件箱](16-local-task-inbox-zh.md)、[日程视图](17-local-task-agenda-zh.md)和[字面搜索](22-local-task-search-zh.md)，无需 API Key。生产级 owner 身份、主 Bot 绑定及通过频道或 HTTP 读取个人数据仍未启用，见 [18](18-owner-entry-and-read-authorization-zh.md) 和 [host 上下文实验](23-host-command-context-experiment-zh.md)。

## 1. 启用与整理

沿用 [16](16-local-task-inbox-zh.md) 的隔离 profile 配置与显式 `mode: local_tasks` 启用方式。默认 `read_only` 仍会在打开存储之前拒绝所有任务命令。CLI 需要已测试的宿主 `in_process` 模式；不要为暴露该 CLI 而关闭已有隔离。

```bash
hermes personal-agent tasks capture \
  --title "Review the migration plan" --project "Website" \
  --due-date 2026-11-20 --request-id website-capture-001
hermes personal-agent tasks list --project "Website"
hermes personal-agent tasks search --query "migration" --project "Website"
hermes personal-agent tasks agenda --on 2026-11-20 --project "Website"
hermes personal-agent tasks projects --limit 20
```

每个任务最多有一个可空的 `project` 标签。未提供标签的新任务为未分组状态。标签是区分大小写的精确字符串，长度为 1–80 个字符，不允许首尾空白、换行或受禁控制/格式字符。不执行 Unicode 规范化，因此 `Website`、`website` 以及视觉相似的 Unicode 字符串可能代表不同分组。标签不是 ID，也不能证明外部项目存在。

从返回结果中复制任务 UUID 和当前 revision：

```bash
TASK_ID="UUID returned by capture"
hermes personal-agent tasks update "$TASK_ID" \
  --project "Website launch" --expected-revision 1 --request-id website-move-001
hermes personal-agent tasks update "$TASK_ID" \
  --clear-project --expected-revision 2 --request-id website-clear-001
hermes personal-agent tasks list --unassigned
```

分组变更沿用已有 revision 与 request-ID 门禁。`--project` 和 `--clear-project` 互斥。终态任务不能编辑或重新分组，其历史分组仍出现在计数及显式终态查询中。本次不增加批量改名、项目实体创建、删除、归档或项目生命周期命令。只要至少一个任务持有该精确标签，分组就存在，其中包括终态任务。

## 2. 筛选与汇总契约

`list`、`search` 和 `agenda` 接受互斥的 `--project NAME` 或 `--unassigned`。两者均未指定时，所有分组均可入选。现有状态、日期、查询过滤继续生效：list/search 默认筛选 `captured`，agenda 仅包含显式日期当天及之前到期的 captured 任务。没有匹配任务时返回空页，而非错误。

`projects` 接受 `--limit`（1–100，默认 20）及 `--after`（有效项目标签），沿用 `personal.local-tasks.v1` CLI 外层格式。其 `data` 结构如下，数字为本地快照示例：

```json
{
  "items": [
    {"project": "Website", "captured": 2, "done": 1, "cancelled": 0, "total": 3}
  ],
  "unassigned_counts": {"captured": 1, "done": 0, "cancelled": 0, "total": 1},
  "next_cursor": null,
  "has_more": false
}
```

计数覆盖全部任务状态，且仅针对当前 profile 的插件自有存储。每个 projects 响应中的标签桶与未分组计数来自同一个读取快照；不同分页请求仍是实时视图，可能反映期间的编辑。每页单独返回未分组计数，不得跨页累加。未分组不是命名桶，不占标签分页限额，也没有游标。完成计数代表本地操作者的声明，不是独立验证的外部执行结果。

分组按 SQLite 二进制文本顺序升序排列。存在下一页时，游标为本页最后一个标签。它是通过语法校验的 keyset 边界，而非签名令牌；即使该标签之后消失，仍可使用。分页是实时视图，不是稳定的多页快照：两次调用之间的编辑可能改变计数和成员。不要把跨多次调用的总数当作原子报告。list/search 游标仍是任务 UUID，agenda 保留日期/序号游标语义。对任务翻页时应保持筛选条件不变。

## 3. 持久化与兼容性

当前存储 schema 版本为 3。初始化仅接受精确匹配且归本插件所有的 v1/v2 schema，或精确匹配的 v3 schema。它会在事务中添加缺少的 `due_date` 和/或可空 `project` 列，校验最终 schema 后提交。外来或结构被修改的数据库会被拒绝，而不是自动修复。已有任务变为未分组，不会从标题或详情推断项目。

升级保留任务 ID、创建序号、时间戳、revision、事件、请求摘要及序列化回执原始字节。在 capture/update 中省略新字段不会向旧请求摘要插入新默认值。重放返回原始历史回执，其中可能没有 `due_date` 或 `project`；新的 show/list/search/agenda 返回包括两个可空字段的当前任务表示。显式值（包括显式清空）是不同请求。变更内容时不要复用旧 request ID。

旧 schema-v2 插件无法读取升级后的数据库。回滚并不自动执行降级迁移。备份/恢复尚未实现，对有价值的数据使用实验性 schema 升级前应先规划恢复。读取派生分组不会修改任务记录或回执，但打开任意任务命令可能初始化或迁移存储，因此不承诺磁盘零写入。

## 4. 安全与剩余产品门禁

- 现有 profile 绑定、显式启用、POSIX 私有目录/主文件/sidecar 校验、脱敏错误及存储前校验保持不变。Windows 任务存储仍不受支持；已测试 Linux。
- 本地 OS 账户被视为可信。项目标签不隔离同账户其他代码、不改变权限授权，也不认证 owner。不要通过不可信远端执行器暴露这些命令。
- 标签、任务文本及计数是明文本地数据。参数可能进入 shell 历史或进程列表。本次不增加凭据、账户连接、远端写入或后台工作。
- 没有面向这些数据的模型工具、私人 slash-command 访问、HTTP endpoint、原生 Project/Kanban 映射、分派、调度或提醒投递。分组不会打开任何已有发布门禁。

这是 E2.1/E2.2 的窄范围本地先导。E3.1 原生项目映射与 E1 owner/动作授权仍是 [08](08-roadmap-and-acceptance-zh.md) 中的独立要求。后续集成必须使用稳定的领域/原生 ID 及已验证权限，不能把这些展示标签升级为身份或权限键。

## 5. 验证范围

项目单元测试覆盖校验、精确筛选、未分组任务、分组/计数、分页、revision/幂等行为，以及保留历史回执的 v1/v2 迁移。固定宿主契约测试覆盖真实注册的 CLI、模式/profile/存储门禁及合成数据持久化。[仓库检查器](../README-zh.md#开发验证) 使用已有离线守卫与固定上游副本运行这些测试。

测试不授权真实 owner，不使用生产账户，也不验证受限的身份 socket 用例。另行打包的 host 上下文补丁不会由安装过程或普通项目检查应用。

后续：[项目依赖](51-project-task-dependencies-zh.md)增加明确同项目前置集合和 ready 队列。当前任务存储为 schema v5，原子 v1–v4 迁移保留历史回执。计划捕获本身仍不推断或接受索引依赖，也不启用原生 Kanban 或 worker 集成。
