# 31. 显式本地记忆记录

[English](31-explicit-local-memory.md) | 简体中文

状态：已实现、需显式开启的 E2.6/E2.7 本地先导切片，不代表[完整记忆方案](30-pluggable-memory-contracts-zh.md)完成。用户可在已有 Hermes 原生会话中保存、查看、更正和遗忘短记录。本切片不增加记忆模型工具、自动召回/提取、原生 MemoryProvider 桥接、包加载器、Markdown 投影、向量服务或远程账号。

## 1. 开启受限本地模式

按 [28](28-profile-first-local-conversations-zh.md) 使用固定 Hermes 版本与隔离的可信单用户 profile。保留其他设置，并显式加入：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: local_tasks
        local_conversation: true
        local_memory: true
```

`local_memory` 默认为 `false`，仅接受布尔值，且要求另外两项设置。配置变更后通过宿主重载。加载或查看帮助不会创建记忆数据库。本功能注册 `/personal-memory`，不注册模型工具或后台 hook；原生 provider 配置与 MEMORY.md/USER.md 保持不变。即使另行启用已有任务模型工具，它们也不会获得记忆访问权。

支持范围为已测试的原生进程内 LOCAL 命令入口和 POSIX 存储。宿主已授权的 owner/operator 控制端共享访问。Profile 范围是存储边界，不是经过认证的个人身份，LOCAL 也不能证明物理本地性。不要在对外开放或多用户部署中启用。Managed/hosted-plugin 及远程消息模式未获验证；不要为开启本功能而关闭已有隔离。

## 2. 在原生会话中使用

以下示例使用合成信息；后续命令应替换为返回的记录 ID 和当前 revision：

```text
/personal-memory remember "Use concise Chinese summaries" --topic preference --request-id preference-1
/personal-memory list --limit 10
/personal-memory search "Chinese"
/personal-memory show RECORD_ID
/personal-memory correct RECORD_ID --text "Use concise bilingual summaries" --expected-revision 1 --request-id preference-2
/personal-memory forget RECORD_ID --expected-revision 2 --request-id preference-3
/personal-memory export --limit 10
```

包括原生桌面在内均使用 POSIX 引号。`correct` 可通过 `--text` 修改内容、通过 `--topic` 修改主题，或同时修改。`list`、`search`、`export` 接受来自 `next_cursor` 的 `--after RECORD_ID`。搜索是区分大小写的内容/主题字面子串匹配，支持中文短词；`%` 和 `_` 不具有通配含义。这不是语义检索或模糊人物匹配。

每次修改使用稳定 `request_id`；省略时生成并回显。结果不确定时，应先检查状态，或手动用相同 key 和完全相同 payload 重试。更换 key 可能创建另一条记录；旧 key 对应的 payload 变更会被拒绝。更正和遗忘要求最新 `expected_revision`，版本冲突后应先读取。命令不会静默重试。

结果采用 `personal.local-memory.v1`，包含 `status`、`data`、`replayed`、`request_id` 和脱敏 `error`。修改回执包含记录 ID、revision、操作、状态和事件序号，不包含私有内容。旧回执是历史，不证明当前状态；`show` 才读取当前状态。遗忘后，`show` 返回 content/topic/source/session 字段为 null 的 tombstone，普通列表/搜索隐藏该记录。更正不能复活同一 ID。用户明确发起新的 `remember` 可创建另一记录；本切片没有自动重新提取引擎。

## 3. 事实与隐私边界

记录表示**明确的本地操作员编辑**，不是已核验的外部事实，也不证明真实人工作者。来源标记为 `explicit_local_operator`，session 引用记录已准入路由的会话。不附加虚构 owner ID、聊天原文引语或原生消息 ID。笔记不能授予权限、完成任务或证明外部动作成功。

命令 handler 本身不发模型请求，也不自动注入提示词。但命令和结果可能保存在宿主正常会话历史中，随后进入该会话已配置模型的上下文。本地保存不等于承诺历史永不发送到用户的模型 provider。不要把密码、token 或支付凭据存进这个明文记录库。

`forget` 原子地将权威 payload/source/session 字段替换为终止性 tombstone。record/receipt/event 保留的元数据包含 ID、revision、操作 key、digest 和时间戳，以维持重放和顺序。这些标识符/digest 仍可能是个人元数据。SQLite secure-delete 与回滚日志不是加密，也不能保证物理介质擦除。已返回文字、宿主历史、备份和导出页不会被该操作删除，不得宣称“已从所有地方删除”。

本切片没有生成的 Markdown 或外部索引，因此不存在异步衍生物重新发布已删除内容；对应发布栅栏仍是 [30](30-pluggable-memory-contracts-zh.md) 的后续门禁。遗忘前已准入的读取可能完成，之后读取可见 tombstone。卸载等待已准入本地命令完成，随后永久拒绝保留回调。配置通过重载一致生效，不把冻结 profile 快照的修改说成立即策略撤销。

## 4. 存储、限制与适配器边界

存储位于注册时当前 profile 下的 `plugin-data/hermes-personal-agent/memory/records.sqlite3`。Namespace 绑定源于 profile 路径，不是 owner 认证；移到或复制到另一条路径会因 namespace 校验失败，目前没有受支持的跨 profile 迁移。私有 POSIX 文件/旁文件检查会拒绝不安全链接、共享文件和可由其他用户写入的父目录，不修复已有数据。不支持的平台关闭功能。这不能防御以相同 OS 用户身份运行的任意恶意代码。

SQLite 是本切片唯一权威。精确自有 schema/version 检查、事务、revision 校验、原子 receipt 和终止性 tombstone 保护支持的操作。内容上限 2,048 字符，主题/查询 128 字符，每页 50 条，包含 tombstone 的总记录 1,000 条，非终止性修改 10,000 次。达到编辑配额后，每条记录仍预留一次终止性遗忘；重放不消耗配额。耗尽时明确报错，不自动清除或切换后端。字面扫描受记录总量限制，不宣称已具备 FTS/CJK 分词质量。

小型内部 `MemoryBackend` 协议提供 `describe`、`execute`、`close`，`MemoryService` 在分发前校验操作。SQLite 连接初始化仅属于内置适配器。这将命令与存储分开，提供经过测试的可替换边界，**并不是** [30](30-pluggable-memory-contracts-zh.md) 中完整公共 SDK 或动态第三方包加载。不支持的生命周期/checkpoint/导入/change-feed 操作返回类型化错误。不发现、安装或选择任何原生 provider。

`export` 返回有界、版本化的 `personal.memory.record_page.v1` 当前记录/tombstone 页及已提交 watermark。每页是独立快照，并发修改可能使多页导出不一致。它明确返回 `restorable: false`，不包含 receipt/event 历史、不写文件，也不能作为可移植备份导入。完整一致导出、迁移、保留/元数据清理和适配器选择仍在规划中。

## 5. 验证与剩余工作

单元测试覆盖输入上限、Unicode/字面搜索、receipt、revision 竞态、回滚、配额、被遗忘载荷、schema/namespace 隔离、私有路径和配置/卸载拒绝。原生契约测试使用固定版本的真实插件加载器与 SessionAuthority/LOCAL 命令分发及合成 profile，覆盖保留已有原生记忆配置、不同 profile、operator 准入、非法/关闭配置、重载与保留回调。

这些检查不使用真实模型、API Key、麦克风、监听器或个人账号，不认证实际 GUI/网络传输、任意自定义适配器、MemoryProvider 生命周期、召回质量或远程身份。历史受限身份 socket 测试未触碰。原生命令保留现有配置，不代表 E0.9 完整 provider 生命周期/checkpoint 矩阵已完成。

下一步：补齐版本化 SDK 与符合性门禁、有界检索/上下文及用户审阅的候选流程，再做显式选择的原生生命周期集成。Markdown 投影、完整导出/导入和自动记忆开放，均须通过各自删除、来源、隐私与恢复门禁才能启用。E2.6/E2.7 为 In Progress，完整记忆系统尚未 Done。
