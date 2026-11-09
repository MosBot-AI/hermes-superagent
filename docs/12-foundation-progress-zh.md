# 12. 第一开发切片：原生插件基础

[English](12-foundation-progress.md) | 简体中文

当前目标更新：[76](76-native-memory-contracts-zh.md) 记录 Hermes `22811165` 的独立 E0.9 原生记忆核验矩阵。不改变下方历史基础结果，也不启用持久 checkpoint-v2、远程身份或生产写入。

此页记录较早的 E0 切片。当前新增的显式本地任务收件箱见 [16](16-local-task-inbox-zh.md)；它不启用这里列出的原生/外部受控写路径。

本页记录实际代码边界，其他设计文档不因此变成已实现功能。开发切片为 E0.1/E0.2/E0.5 的第一部分；E0 epic 和 M0 仍未完成。不得把它标成 M1 可用版。

## 已实现

- 原生目录插件 `plugin.yaml`、同步 `register(ctx)`、插件相对导入。
- `personal_agent_status` 工具与默认 `in_process` 模式下的 `hermes personal-agent status`，输出同一有版本的 JSON readiness 报告。Host isolation 会跳过 CLI 注册，不应为此关闭用户已配置的隔离。
- 配置只接受 `mode: read_only`。宿主 schema 的警告不能替代检查，非支持值在注册工具前直接拒绝。
- 工具无业务参数；伪造 `approved`、owner、action、敏感正文一律拒绝，错误不回显原输入。
- 明确报告未实现的数据、授权、提醒、外发、路由能力及阻断发布的原因。
- 无第三方运行依赖，无 agent loop、scheduler、账号连接、网络调用、后台线程、数据库或凭据读取。
- `compatibility.json` 固定上游 SHA；来源和许可记录、可复现检查脚本及 CI 工作流。
- 保留现有 Python 忽略规则，新增 macOS/Windows 系统文件规则及 Git 行为测试。

“只读”描述本插件当前工具，不是宿主隔离保证。本插件没有拦截或关闭原生 shell、MCP、browser、RPC、批量或 worker 工具；这些路径在 E0.4 尚未验收，不能作为受控 personal-agent 写功能发布。

## 实际兼容合同

测试基线：Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`，Python 3.14、Linux、默认 `in_process` 插件模式。测试用官方 PM 的冻结依赖环境和官方 `scripts/run_tests.sh`。没有运行 host isolation 的完整子进程工具、Windows/macOS 或手机合同测试。

| 合同 | 测试方式 | 结论范围 |
|---|---|---|
| manifest / 入口 / 工具 | 复制真实插件到临时 home，真实 `PluginManager.discover_and_load()` | 不是 mock ctx；只证明这个插件在该 SHA 上的行为 |
| config / default | 真实 config.yaml、缺省与六类非法值 | `config_schema.default` 不自动注入，代码显式传默认值 |
| tool return | 真实 scoped registry dispatch，解析返回字符串 | handler 返回 JSON 字符串，不返回普通 dict |
| enable / disable | 真实 allow/deny 配置，不修改 gate | 禁用不注册工具或 CLI |
| reload / unload | force reload 后 dispatch、从有效配置切到非法/禁用配置后 reload，再 unload | 清除该插件工具和 CLI 注册，不断言全局 registry 数量 |
| CLI | 实际注册的 argparse setup 与 handler | status 输出一致；不是完整终端/手机 E2E |
| Doctor | 真实宿主 doctor | 补充 manifest/加载验证，不替代 discovery/业务调用 |
| package metadata | 固定宿主 PM declaration reader 读取实际 staged pyproject | 没有运行依赖或包安装；插件自身不导入 PM 内部实现 |
| public storage helper | 仅在临时 home 调用 `plugins.plugin_storage.plugin_data_dir` | 每次遵守当前 profile，拒绝路径穿越；不是 ctx 方法。实际 status 不调用创建型存储 API |

单元测试与宿主合同测试分开。检查脚本不带 `--hermes` 时只跑 unit/lint/type 并明确打印 compatibility NOT RUN；指定兼容测试后，缺环境、错误 SHA、脏的 tracked 上游源文件或非 3.14 解释器都会失败。脚本记录 Python 版本、上游 `uv.lock` SHA256 和已安装包清单指纹。解释器由调用者传入，这些观察不保证任意解释器与 lock 完全等价。本次本地环境通过固定 checkout 的 `python -m pm.build_env --source . --out <fresh-path> --group dev --group test` 构建。

测试过程使用合成输入和临时 home，并阻断 Python socket connect；它不是恶意插件进程沙箱，也不声称拦截所有子进程网络。

## 未完成与下一步

1. E0.3：后续[原生生命周期契约](75-native-lifecycle-contracts-zh.md)覆盖有界的 Project/Kanban/cron 操作行为及缺失的插件 CRUD 接口。本历史切片不包含那些探测。原生弱去重、取消请求和未知尝试不得当作受控执行或可靠投递。
2. E0.4：逐工具/路径覆盖，hook、dispatcher、middleware、safe mode、managed worker 的异常与撤权行为。此项通过前不能启用相应写集合。
3. E0.5：后续[离线合成连接器测试夹具](74-synthetic-connector-fixtures-zh.md)增加持久假远端及固定宿主 MCP stdio 场景。此历史基础切片本身没有完整连接器模拟器；后续测试框架不完成 E0.4、E1、E5 或真实服务商验收。
4. E1：verified owner、grant、intent hash、审批、事务准入/撤权和脱敏审计。
5. 完成这些门槛后，再接领域存储、可靠提醒与任务纵切。E9 路由继续 Backlog，不抢先上线自动切换。

## 验证记录

复验入口见仓库 [README](../README-zh.md)。本切片提交前执行 unit、Ruff lint/format、ty 及固定宿主合同检查。精确计数和远端 CI 结果以该分支/PR 的验证回执为准；代码提交不等于 CI 已通过，也没有运行真实账号、手机、语音或线上 provider 测试。
