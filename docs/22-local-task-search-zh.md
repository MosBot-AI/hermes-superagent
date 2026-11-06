# 22. 本地任务检索

[English](22-local-task-search.md) | 简体中文

[项目分组](24-local-project-groups-zh.md)现增加可选的精确项目/未分组筛选。当前存储为 schema v3；下述检索行为不变，历史回执不会重写。

## 1. 已实现范围

可信本地操作人可以按标题或详情中的字面文本搜索现有显式启用的任务收件箱。这是 E2.2 的有限本地检索先导切片，不是 Agent 记忆、语义检索、owner 认证或完整 personal-agent MVP。[收件箱](16-local-task-inbox-zh.md)和[日程](17-local-task-agenda-zh.md)的边界继续适用。

不需要凭据、模型、网络、监听器、新 provider、原生 Projects/Kanban 访问或外部操作。没有新增任务数据模型工具、对话斜杠命令或 HTTP 路由。正式 Hermes 基线和数据库 schema 均保持不变。

## 2. 命令与匹配

按 [16](16-local-task-inbox-zh.md) 使用已测试的隔离 profile，并显式将本插件设为 `local_tasks`。不要仅为开放 CLI 而关闭宿主隔离。

```bash
hermes personal-agent tasks search --query "weekly review"
hermes personal-agent tasks search --query "review" --state all --limit 10
```

查询为非空白单行字符串，最多 240 个字符。保留精确空格，拒绝不安全控制/格式字符。匹配采用**区分大小写的字面子串搜索**，不做 Unicode 归一化、词干处理、模糊匹配或 SQL 运算。中文及其他 Unicode 文本可以按原文匹配。`%`、`_`、引号和看似 SQL 的字符串都是普通字符，不是通配符或可执行语句。查询通过 SQL 参数传入。

只检索标题和详情，不检索完成/取消备注、请求回执、原生记忆、其他 profile 或外部系统。默认状态为 `captured`；查看终态记录时显式选择 `done`、`cancelled` 或 `all`。默认每页 20 条，limit 必须为 1–100 的精确整数。

## 3. 结果与分页

结果使用 `personal.local-tasks.v1`、`status: ok`、`scope: trusted_local_cli_only` 和 `replayed: false`。`data` 包含 `items`、`next_cursor` 和 `has_more`；条目是包含可空截止日期的当前任务记录，不是历史重放回执。响应不重复查询文本。

任务按不可变创建顺序倒序排列，最新在前。保持相同查询和状态，将返回的 UUID 作为 `--after` 传入：

```bash
hermes personal-agent tasks search --query "review" --state all \
  --limit 10 --after "UUID returned as next_cursor"
```

游标是当前存储中的任务 ID 锚点，不是绑定查询、状态或跨页快照的签名令牌。不存在或其他存储中的 ID 会被拒绝。更改查询或状态时应从头开始，不沿用旧游标。页面之间的编辑可能改变匹配成员；这是实时视图，不是持久 change feed 或导出。

页面大小有界。字面子串匹配可能扫描存储中的记录；它不是带索引的全文搜索，也没有经过验证的大数据库延迟上限。

## 4. 安全与兼容性

任务存储打开前先验证输入。默认 `read_only` 模式拒绝该操作，既有 profile/模式、POSIX 文件/目录所有权、权限、链接及 SQLite sidecar 检查继续适用。错误不回显查询文本、SQL 或私人路径。查询参数和输出仍可能出现在本地 shell 历史、进程列表或终端日志中，不要使用秘密作为查询。

检索不创建任务事件或请求回执，不更改任务状态或 revision。与 list/agenda 相同，打开显式启用的存储可能初始化它，或迁移精确匹配的受支持旧 schema。因此检索不承诺完全没有文件系统写入。现有历史回执字节和修改请求摘要保持不变。

没有增加备份、恢复、导出、遗忘策略、加密、排序评分或自动任务执行。本地 OS 访问不是经过验证的渠道 owner 身份，不得通过不可信执行器暴露该 CLI。

## 5. 验证

测试覆盖标题/详情匹配、Unicode/大小写语义、特殊字符字面匹配、非法输入、状态、当前截止日期、空页面、顺序、分页、无效游标、旧版本迁移/重放兼容以及无任务修改。真实固定版本宿主 CLI 测试覆盖既有模式/profile/存储门禁和带防护的顶层子进程路径。

这些检查通过只证明本地收件箱功能。E1、完整 E2.2、原生任务集成和 M1 发布门槛仍未完成。
