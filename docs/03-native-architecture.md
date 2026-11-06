# 03. Hermes 原生架构

## 1. 总体选择

本仓库交付一个 **Hermes 原生 personal-agent 插件及配套 skills**。插件由 Hermes 发现、启用和调度，注册工具、上下文、命令与必要 UI 扩展。Hermes 负责 LLM 循环、会话、provider、工具调用、原生审批、gateway、cron、Kanban、MCP 和语音。

```text
用户：Desktop / CLI / 手机消息 / 语音
                  │ 已验证身份 + 会话路由
                  ▼
Hermes Gateway / Session / Agent Loop
                  │
      personal-agent 原生插件
      ├─ Context：项目、承诺、偏好、任务摘要
      ├─ Domain：事务模型、证据、授权、提案
      ├─ Policy：操作级 scope、审批绑定、撤权检查
      ├─ Adapters：Project / Kanban / cron / MCP / delivery
      └─ Storage：插件自己的 SQLite + 附件引用
                  │
Hermes 原生工具 / MCP / 官方平台适配器 / 受限 workers
                  │
外部服务或隔离执行环境
```

主 agent 是 Hermes session 本身，不是插件里嵌套运行的另一个“人格”。插件内也不复制独立 agent loop。辅助 LLM 调用优先使用官方 `ctx.llm` 和其凭据/预算规则；具体能力先通过 E0 契约测试。

## 2. 已有能力与新增价值

| 层 | 复用 Hermes | 本项目新增 | 明确不做 |
|---|---|---|---|
| 推理 | agent loop、provider、打断、压缩 | 个人事务的工具和工作协议 | 第二套 loop/provider 栈 |
| 会话 | SessionDB、gateway route、profile | owner 绑定和领域对象引用 | 替换 transcript store |
| 项目 | Projects/workspace、Kanban board | 非代码项目、承诺与资料的领域补充 | 直接改宿主数据库 schema |
| 长任务 | Kanban dispatcher、goal contract | 任务映射、结果验收、跨任务汇总 | 自建 worker supervisor |
| 短并行 | `ctx.subagent_lifecycle` 或原生 delegation | 最小上下文与权限裁剪 | 声称句柄可跨重启恢复 |
| 调度 | cron、session heartbeat | 用户意图、预算、停止与外发策略 | 平行 cron daemon |
| 记忆 | MEMORY/USER、session search、单个外部 provider | 结构化事实、来源、纠错、按权限检索 | 默认同时激活多个 memory provider |
| 连接 | MCP、OAuth、插件 catalog | connector 风险清单与最小工具集 | 第三套 OAuth/token store |
| 入口 | 官方消息适配、web/desktop、STT/TTS | personal overview、移动流程验收 | 第一版自建手机聊天和通话栈 |

## 3. 插件模块边界（拟议）

```text
plugin.yaml                     # manifest、依赖、配置和能力声明
__init__.py                     # register(ctx)，薄注册层
personal_agent/
  domain/                      # 项目/承诺/事实/自动化/审批对象
  services/                    # 领域动作与事务边界
  policy/                      # 身份、授权、动作哈希、撤权版本
  adapters/                    # 只调用已验证 Hermes 公共扩展面
  storage/                     # migration、repositories、outbox
  tools/                       # 小而明确的工具 schema 与 handler
  context/                     # 有界、带来源的动态上下文
  observability/               # 脱敏事件、指标、诊断
skills/                        # inbox-review、project-review、weekly-review 等
tests/                         # 单元、契约、恢复、安全、渠道测试
```

这是未来目录建议，本次不创建可执行实现。先用一个插件包避免无意义微服务。需要独立 memory provider 时再分离可选包，不让安装基础功能就替换用户当前 provider。

## 4. 数据与执行的唯一权威

1. 对话与模型执行状态以 Hermes 为准。
2. worker 状态以原生 Kanban/run 为准；领域 `task` 保存引用与业务验收，不再维护一套 competing worker lifecycle。
3. 计划触发以原生 cron/heartbeat 为准；领域 automation 保存目标和策略，不自己再次计算并派发同一 occurrence。
4. 个人事实、承诺、授权提案、来源映射与外部动作账本以插件数据库为准。
5. 外部动作是否成功以外部 receipt/读回为准，不以“模型说已经发了”为准。

跨 SQLite/远端系统不能假装有全局事务。领域事务先写 intent 和 outbox，再交给适配器执行；完成后写 receipt。远端结果未知时进入 `unknown` 并对账，不立即重发。

## 5. Hermes 扩展点使用规则

- 通过 `register(ctx)` 注册工具、hook、命令、skills；运行数据使用官方 `plugin_data_dir` / `plugin_db`，不写安装目录。
- 通用兼容边界是官方文档化 ctx/ABC/事件行为，不依赖任意内部 Python import 永久稳定。
- `pre_llm_call` 只注入有界、相关、带来源的数据。失败时允许主对话继续，但不因此放行受限写操作。
- `pre_tool_call` 在本次固定源码中对 callback 异常/超时/still-running **fail-closed**。`tool_request` 和 `tool_execution` middleware 失败可继续下游，不能拿它们做唯一权限边界。
- hook 回调不执行外发副作用；有副作用的领域 handler 自身再次检查权限、版本、幂等和审批。
- `ctx.subagent_lifecycle` 仅在活动父 turn 中可用；进程退出后 `reconnect` 不会恢复执行。长期工作使用 Kanban。
- 原生 `desktop_project` 当前是 GUI 工具集，不能假设手机 session 默认可见。跨入口项目操作需要 E0 验证可用适配路径。
- 不直接导入 `hermes_cli.projects_db` / `kanban_db` 修改数据，不直接写 `jobs.json` / SessionDB。缺公共写入入口时，先验证官方命令/dispatch 支持；确实缺 seam 时提出最小通用上游扩展。

## 6. 上下文组装

每轮只给主 agent：身份与当前 scope、当前项目摘要、相关承诺、少量事实、活跃任务变化、未决审批。长文档按需检索。每个片段标注来源、时间和可信级别；检索出的外部文本与用户命令分区。

上下文预算初始设为可配置上限，按实际模型测试确定，不能为了“全都记得”把全部个人资料放入所有请求。跨 profile 默认不共享。worker 只拿 handoff snapshot，不拿整份用户档案与全量聊天。

## 7. 部署与升级

个人版最小部署是一台持续在线的 Hermes host、一个 owner profile、插件数据目录和一个主要手机渠道。执行不可信代码时使用 Hermes 支持的受限环境并单独验证 filesystem/network/credential 隔离；进程隔离本身不等于沙箱。

版本锁记录 Hermes SHA、插件版本、schema version、启用连接器及测试结果。升级先备份插件数据库与配置，跑契约和恢复测试，再小范围启用。禁止自动升级到未经验证的 `main` 后宣称兼容。回滚代码不等于回滚数据；migration 必须声明可逆性和恢复方案。
