# 35. 离线 Worker 路由样例验证

[English](35-offline-worker-routing.md) | 简体中文

状态：**已实现离线前置切片，不是在线路由 backend。** 本切片推进 E9.1 契约证据，并为 E9.2/E9.3 准备约束样例；未完成可信上下文，未启用自动选择，也未启动真实 shadow 模式。

## 范围与复现

`personal_agent.routing_shadow.evaluate_shadow_fixture` 先过滤调用者提供的合成路由清单，再按显式优先顺序排列剩余候选。不接受任务正文或模型分类器。不读取或修改配置，不解析凭据，不调用 provider，不启动 worker，不持久化审计，不注册或切换 backend。

使用与仓库检查器相同的 Python 3.14 解释器，在仓库根目录运行随附的合成示例：

```bash
python scripts/check_routing_fixture.py experiments/routing/synthetic-shadow.json
```

退出码：0 表示建议性比较，1 表示基线路由不合格，2 表示输入无效。输入必须是严格 UTF-8 JSON，最大 64 KiB，拒绝重复对象键。错误不回显输入路径或正文。这是开发工具，不是新安装的 Hermes 命令。

样例 schema 使用封闭字段和显式版本。示例列出全部必填字段。最多允许 32 个候选，route ID 必须唯一，优先顺序必须恰好包含每个候选一次。未知字段、密钥或路由覆盖字段、错误布尔值、非法 token 上下界及未知 effort/capability 名称都无法通过验证。

## 约束与基线

每个候选声明已配置/可用状态、provider/model/endpoint/API 标识、证据引用、接收方、数据范围、区域/本地性、能力、上下文/输出上限、请求的 effort 及 service tier 支持。这些是**样例声明，不是已核验事实**。route ID 不是密码学身份或授权凭证。未来可信宿主集成必须提供并重新核验 provider endpoint 绑定、当前能力证据、policy revision 和确切清单身份；本验证器不认证这些信息。

先过滤，再排序：

- 路由必须在允许 ID 集合内，且已配置、可用。
- 所有接收方都必须获准，数据范围必须明确声明。未知接收方或范围默认拒绝。远程执行不能宣称接收方为空；local-only 约束也会拒绝声明了外发接收方的候选。
- 必须满足所需模态、工具、结构化输出能力、区域、包含预留输出的上下文容量和输出上限。所需能力未知时排除候选。
- provider/model/route/effort 精确 pin 不可更改。不支持的 effort 被拒绝，不自动降档或替换；`provider_default` 与 `none` 不同。
- 请求的 service tier 必须匹配，并明确声明支持。不自动建议付费升级。
- 硬预算或任务总截止时间约束会拒绝所有候选，因为本切片没有预算预留或执行层强制保障。

显式基线路由接受相同约束检查。基线缺失或被排除时，报告为 blocked，即使其他候选可行也不返回建议，避免把无效基线上的推荐说成合格 shadow 运行。不产生空的原生 route，不继承任意父路由，没有 fallback 执行或升级计划。

## 报告与信任边界

报告包含 policy/capability 引用、基线/建议 route ID、建议的请求 effort 枚举和稳定的排除原因码。不包含 provider/model/endpoint 明细、精确 pin、任务正文、凭据或自由文本解释。ID 必须是调用者提供的**不含敏感信息的不透明引用**：语法验证不是自动脱敏，不能用于清洗私密标识符或 URL。脚本只打印报告，不保存审计记录。

每个结果都明确标记 `execution_authorized: false`、`live_routing_enabled: false` 和 `quality_validated: false`。实际路由、effective wire effort、用量和费用均为 null，不从能力声明推断，也不视为零。`advisory` 只表示合成基线通过样例检查，不代表授权、运行时安全、在线可用性、质量、成功率、节省成本或 provider 兼容性。

## 固定版本原生契约

`tests/contracts/test_worker_routing_contracts.py` 使用 `compatibility.json` 中的确切 Hermes commit。临时测试插件经真实原生插件管理器加载。schema、注册、provider dispatch 和路由解析均为真实实现；在任何凭据读取之前，以内存记录器替代凭据解析器。不启动 child，不发出模型请求。

已覆盖边界：确定性 schema 快照、注册/卸载、保留字段不进入 provider payload、未声明/无效参数在 dispatch 前被拒绝、丢弃未知 route 字段、单任务拒绝/异常不取消有效同批任务、已选 backend 不可用/缺失时拒绝、未知 effort 拒绝、session backend pin 优先、内部调用绕过 provider，以及显式 `fallback_providers: []` 与继承链的差别。记录的 route 字段不是最终 wire 元数据，也不能证明执行了 fallback。

未覆盖：hosted-plugin IPC、实际 worker 构造/后台 delegation、cron/Kanban/public lifecycle 路径、跨 profile 行为、完整的保存/新会话/resume schema 切换、实际 provider encoder、在线用量/费用、取消、预算竞争或可信 owner/授权上下文。不宣称任何 provider 能力或质量基准。E9.1 仍为部分完成，E9.2–E9.6 运行门禁仍未关闭。参见[路由设计](11-worker-model-routing-zh.md)和[路线图](08-roadmap-and-acceptance-zh.md)。

## 验证

按照 [README](../README-zh.md#开发验证) 的说明，以固定 Hermes checkout 和对应测试解释器运行仓库常规检查器。完整检查包含新增单元/原生契约测试、Ruff、格式检查、ty 和双语文档检查。合成负面样例覆盖硬约束、精确 pin、无效基线、错误输入、审计信息最小化和未实现的运行时保障。测试有网络阻断，不调用真实 provider/model。
