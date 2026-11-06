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

### 边界

- E0.3/E0.4、身份授权、领域存储、提醒、连接器、手机、语音及 E9 模型路由尚未实现。
- 本插件不保护其他 Hermes 工具；状态输出明确保留发布阻断门槛。
- 没有验证完整安装事务或隔离 host 执行；固定宿主不支持 host-isolated CLI。

## 设计基线：2026-11-06

- 提交 `c254c86a17c61e1bd13d74d00d5b44016abab13d` 建立 Hermes 原生 personal-agent 架构、DSH 研究、授权/撤权语义、可靠交付、记忆、手机/语音及 E0–E8 路线。
- 提交 `e4eb446c0d0c20d3ce83aa20f7b5139261d593f9` 增加 worker 模型/思考强度原生路由设计、shadow 先行、宿主约束缺口、开源方案比较及 E9.1–E9.6 工作包。
- 上述提交交付方案与规划，不代表产品功能已经运行。
