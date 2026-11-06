# 更新记录

[English](CHANGELOG.md) | 简体中文

本文件区分方案设计、开发变更与已发布能力。当前尚无生产版本。

## 未发布

### 新增

- E0 原生插件基础：只读 readiness 工具及 `in_process` 模式 CLI。
- 严格只读配置与参数校验，不提供个人数据写入或外部动作工具。
- 固定 Hermes 兼容基线，真实 discovery/dispatch/reload/unload/Doctor 契约、合成单元测试及离线测试保护。
- 可复现检查脚本和 SHA 固定的 GitHub Actions 工作流。
- 保留现有 Python 忽略规则，新增 macOS、Windows 系统文件规则及 Git 行为测试。
- README、更新记录和全部设计文档采用英文原名、中文 `-zh` 的分文件版本，并提供语言互链。
- E0.4 合成失败边界契约，覆盖 policy callbacks、dispatcher/middleware 失败、直接 registry dispatch 及 managed/safe worker 配置。
- 只读阻断写路径清单与 `personal-agent coverage` CLI；没有新增写授权或全宿主执行保护。

- 详细双语客户端/连接器 API 设计：插件 HTTP 命名空间、宿主认证适配缺口、canonical 会话传输、持久变更流、审批/幂等/恢复语义及原生手机认证阻断。尚未实现 HTTP 端点。
- E0.6 与 E6.5–E6.7 工作包，以及 E5.1/E5.2 连接器契约细节。
- JSON 示例语法验证及回归测试；不代表 API schema 或运行时行为已验证。

- 显式 `local_tasks` CLI 收件箱，使用插件自有 SQLite、稳定 request receipt、compare-and-set revision、明确完成/取消、有界分页和终态校验。
- Profile/mode gate、POSIX 主文件/sidecar 私有权限、不安全链接/权限拒绝及数据库所有权/schema 核验；默认诊断仍不打开存储。
- 合成并发/回滚/存储测试、真实宿主 CLI 生命周期测试及带网络 guard 的顶层 CLI 子进程。
- 独立双语主 Bot 绑定方案及条件式 E0.7/E1.6/E3.6 工作包，没有启用绑定代码。

- 本地日期式截止日期与有界 agenda，支持显式设置/清除日期、指定查看日期及原有幂等和 revision 检查，不进行时钟推断或提醒投递。
- 原子式精确 schema v1→v2 升级，保留旧 digest/receipt，并测试失败回滚、并发升级及旧请求重放。

### 边界

- E0.3、完整 E0.4 覆盖、E0.6、身份授权、完整领域存储、提醒、连接器、手机、语音及 E9 模型路由尚未实现。
- 本地任务存储信任本地操作员，不是 owner 认证、原生任务执行或 OS 沙箱。Windows 存储、加密、导出/遗忘和完整保留策略仍不支持。
- 本插件不保护其他 Hermes 工具；状态输出明确保留发布阻断门槛。
- 没有验证完整安装事务或隔离 host 执行；固定宿主不支持 host-isolated CLI。

## 设计基线：2026-11-06

- 提交 `c254c86a17c61e1bd13d74d00d5b44016abab13d` 建立 Hermes 原生 personal-agent 架构、DSH 研究、授权/撤权语义、可靠交付、记忆、手机/语音及 E0–E8 路线。
- 提交 `e4eb446c0d0c20d3ce83aa20f7b5139261d593f9` 增加 worker 模型/思考强度原生路由设计、shadow 先行、宿主约束缺口、开源方案比较及 E9.1–E9.6 工作包。
- 上述提交交付方案与规划，不代表产品功能已经运行。
