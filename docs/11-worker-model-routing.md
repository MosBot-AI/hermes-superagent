# 11. Worker 模型与思考强度路由插件

状态：**已选定设计方向，尚未实现或运行验证**。本页依据 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。用户希望主 agent 委派工作时，按任务难度自动选择用户已配置的 provider、model 与思考强度；已审阅并选择原生插件路线。本次只更新文档和规划，不安装或运行路由服务。

## 1. 结论与范围

采用独立分发、由 Hermes 加载的 **worker routing 原生插件**，通过 `DelegationProvider.route_task` 返回每个 worker 的执行 route。主 agent 仍负责理解用户、拆任务、授权、验收和汇报；Hermes 仍负责创建/停止 worker、工具隔离、会话、凭据解析、并发和结果。路由插件只回答“这个任务用哪条已许可 route”。

这属于任务级模型分流，不要求新建 API 网关。已有 LiteLLM、OpenRouter 或其他兼容 endpoint 可以作为用户配置的 provider，但不能让它在下游暗中改模型、数据接收方或预算，变成第二个决策中心。第一阶段不改变主 agent 的模型，也不在同一 worker 的每轮推理中来回切换。

首选顺序：**确定性规则和静态能力配置 → shadow 模拟选择 → 有界启用 → 有证据后再评估分类器/学习策略**。复杂度只影响候选排序，不授予权限；“更强模型”不替代外发审批或解决敏感数据传输许可。

安装或启用插件只让其可被发现，不自动修改 `delegation.backend`。Owner 明确选择该 backend 后，默认进入 shadow；启用真实自动选择是另一个明确设置。Shadow 必须引用已有、仍获准的静态 delegation baseline，并核验其 provider/model/effort/数据范围；没有合格基线时先配置并验证，不能用空 route 随意继承父模型，也不能声称 shadow 已开始。

## 2. 当前 Hermes 能做什么

### 2.1 已有原生接入点

- 插件通过 `ctx.register_delegation_provider()` 注册，`delegation.backend` 选择当前 backend；配置放在 `delegation.backends.<backend>`。
- `route_task(task, config)` 可返回 provider/model、reasoning_effort、service_tier、fallback_providers、label 等 route 字段，凭据由宿主 resolver 解析。
- `task_parameters(config)` 可以声明有限 enum，例如 `work_class`、`effort_hint`。核心拒绝保留字段和未声明参数；schema/description 对同一配置必须确定，不在每轮根据网络/时间动态改变。
- 选中的 backend 缺失或不可用时 fail-closed，不会自动切到 default。单 task 路由拒绝不必取消同批其他合法任务。
- Hermes 保留 spawn、roles、depth、concurrency、stop fan-out、output_schema、progress 等生命周期；插件不重新实现它们。

证据：[DelegationProvider ABC](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/delegation_provider.py)、[官方插件指南](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/delegation-provider-plugin.md)、[route resolver](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_routes.py)。

### 2.2 不能误认为已经具备的能力

当前 `route_task` 收到的 payload 只有 `goal`、`context`、`index` 和模型填写的插件参数；它没有完整、可信的 owner/task identity、模态、预算余额、授权、取消状态或工具需求。把这些写进模型参数不能使其可信。当前接口也没有完整的宿主预算原子预留契约。

| 路径 | 本基线边界 | 设计处理 |
|---|---|---|
| 原生 `delegate_task` | 调用 delegation backend，包括受支持的后台委派 | 第一个集成面，逐路径测试 |
| `ctx.subagent_lifecycle` | 文档明确不咨询 `delegation.backend`；request 没有单独 effort 字段 | 不能声称自动覆盖；需显式桥接或最小宿主 seam |
| Kanban 初始 worker / cron | 各自 profile/job/model 路由，不因启用 backend 自动全部接管 | MVP 不改；未来接入须单独验证 |
| `/review` 等内部调用 | `route_for_config` 明确绕过 provider，使用自身 route | 审查/辅助调用单独计费与权限，不假定受本插件控制 |
| 跨 profile route | profile 决定模型、凭据、reasoning 等，其他 route keys 被忽略；普通 managed worker 的 frozen snapshot 限制跨 profile route | MVP 不用切 profile 偷换模型或身份 |

public lifecycle 仍不支持 per-launch timeout、cwd override、per-tool block 等请求字段；`delegation.child_timeout_seconds` 是**空闲/无进展超时，不是总 wall-clock deadline**。任务总 deadline、总成本和取消传播若需要硬保证，必须由宿主执行路径补足，不能虚构一个 route 字段。[public lifecycle](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/subagent-lifecycle-api.md)、[timeout 实现](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/delegate_tool_config.py#L192-L201)

## 3. 候选 route 与能力清单

候选必须是用户已配置并明确允许用于对应工作/数据范围的 route。记录 `route_id`、provider identity、model、api_mode/endpoint identity、能力、effort 支持、价格/计量来源、健康、隐私范围和证据版本；密钥只保留宿主引用，不能进入任务 prompt、审计正文或插件自建 secret store。

能力条目至少包括：工具调用、structured output、图片/音频输入、上下文/输出限制、reasoning 控制形态、是否允许禁用、服务档位、缓存/使用量计量、数据接收者及其可验证范围。配置为可用不等于已验证所有能力；未知项保持 unknown，不能从模型名称猜测。

使用用户自定义别名（如 fast-text、balanced-code、deep-review）呈现候选，而非强制购买或指定某品牌。别名只是已配置 route 的映射，不绕过精确 model pin。用户明确指定模型/effort 时优先遵从合法 pin，不把其悄悄替换为“更省钱”的 route。

## 4. 从约束到选择

```text
宿主验证后的任务上下文 + 当前策略
    → 过滤用户未允许/不可用/不满足硬约束的 route
    → 评估任务需求与不确定性
    → 比较可行候选的任务完成质量、总成本和延迟
    → 生成可审计 RouteDecision
    → 宿主重新核验、预算准入、构造 worker
    → 记录实际 route/usage/结果，必要时有限重试或升级
```

**先过滤，再排序**：数据接收方/地域/本地限制、用户 pin、模态、上下文、工具/输出 schema、预算、deadline、effort 和服务档位是硬约束。质量、预计总成本、延迟、缓存、历史成功率只用于剩余候选排序。没有可行候选就拒绝/等待输入，不自动跨隐私边界、提额度或购买升级。

复杂度初始可用结构化信号：任务类型、步骤/依赖数量、证据冲突、可验证性、代码变更范围、模态、输入长度、历史失败。模型给出的难度和 `work_class` 仅是 hint；短任务可能高难，长文本可能只是格式转换。风险分类与难度分开，不能因为“简单发送邮件”就取消确认。

示例策略为评测起点：确定性提取/格式化优先低成本候选；有明确测试的局部代码修改用平衡候选；跨文件诊断、冲突证据和高要求审查考虑深度候选。不能把表面关键词直接当正确率，也不默认所有任务都先跑一次最便宜模型。

## 5. 思考强度必须按 route 归一化

### 5.1 记录三个不同概念

1. `requested_effort`：用户或策略希望使用的档位。
2. `effective_effort` 与 `wire_shape`：宿主针对 provider/model/api_mode 实际编码的参数或 provider-default/omitted。
3. `usage/outcome`：真实返回的 token/费用/结果证据。wire 上写 high 不证明模型内部投入了固定数量计算。

Hermes 内部 effort ladder 为 none/minimal/low/medium/high/xhigh/max/ultra，但不是跨 provider 的统一算力单位。`clamp_effort` 一般向最近较弱支持档映射，必要时到 provider 的最低档，并有厂商特例；supported set 未知时函数可原样返回，**这不证明该值被服务端支持**。[reasoning_effort.py](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/reasoning_effort.py)

### 5.2 固定源码中的映射例子

| Route 家族 | 基线中的差异 | 本插件要求 |
|---|---|---|
| OpenAI/Codex Responses | 支持集合按模型代际不同；部分没有 none/minimal；ultra 不是通用 wire 值，Codex app-server 有独立 harness 语义 | 复用对应 resolver/encoder，不把 ultra 发给所有兼容 endpoint |
| xAI | 新旧模型支持集合不同，不能把 xhigh 当所有 route 都支持 | 固定 model/api_mode 能力后选档 |
| Kimi K3 | 支持 low/high/max；基线特例把 medium→high、xhigh→max | 映射可能升档，重新检查成本和用户限制，不宣称永远向下 clamp |
| DeepSeek V4 | 支持 low/medium/high/max，xhigh→max；thinking toggle/wire 字段有特殊组合 | 交给宿主 provider 编码，不手工混拼通用参数 |
| Gemini native | 新代采用 thinkingLevel，旧式可有 thinkingBudget；输出 token 编码也可能为 thinking 调整 | 预算按最终有效请求估算；原始 max_tokens 不是硬费用保证 |
| 其他/自定义 endpoint | 可能只有开关、token budget、provider 默认，或完全不支持 reasoning knob | 未经能力验证不发送猜测字段；硬要求无法满足则不选该 route |

上表是固定 Hermes 源码行为示例，不是对这些模型当前可购买性、账号资格或在线 API 支持的独立认证。[thinking 编码](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/reasoning_effort.py)、[Gemini native 请求](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/gemini_native_adapter.py)

精确 effort pin 不支持时应报不匹配，不能偷偷降档。自动策略只可在已许可范围内归一化，并记录变化原因；显式关闭思考而模型不能关闭时不能假装 none 已生效。`reasoning_effort`、输出 token 上限、总预算和 `service_tier` 是不同控制；fast/ultrafast 可能影响服务资格和费用，默认不自动升级。

原生结果 route 可报告 child 实际 provider/model/effort 和 fallback 标记，但不保证反映每次传输编码或服务端内部行为；有效 wire 观测不足时标 unknown，补通用脱敏请求元数据 seam，不读取或展示隐藏推理。[result route 合约](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/delegation-provider-plugin.md#result-route)

## 6. 可信 RouteContext 与最小宿主扩展

以下是**拟议扩展，不是已有 API**：

- `RouteContext`：宿主绑定 owner/profile、task/attempt、source/authorization refs、parent/child role、所需工具/模态/上下文、用户 pin、data_scope、policy revision、budget reservation scope、deadline/cancel token。模型可提议 task hints，不能伪造这些权威字段。
- `RouteDecision`：候选集、选定 route、effort 要求、约束检查、有限 fallback plan、policy/capability snapshot ids、reason codes。决策不携带明文 key，也不自己启动 worker。
- `BudgetAdmission`：宿主对 task/owner/provider 的预算做跨并发原子预留，绑定 attempt/route/最终有效请求上界；实际 usage 回填、失败释放或标 unknown、重启对账。
- `RouteEnforcement`：worker 构造前和每次收费请求/route 变化前核验当前授权/取消/预算，产出脱敏的最终 provider/effort/limit 元数据；不能仅依赖可 fail-open middleware。

小扩展应是通用、可测试的宿主能力：新增只读可信上下文和准入回执，不把 personal-agent 专属分支硬塞入 Hermes loop。保持旧插件兼容，测试 in-process 与 plugin-host。只有经运行验证可覆盖委派、fallback、辅助调用和 API 请求路径，才可以称为硬限制。

内部 RouteDecision 记录与当前 route_task 返回值分开：返回宿主时只投影到已支持的 ROUTE_KEYS。当前 resolver 会丢弃未知 key，不能把 budget token、deadline 或 policy receipt 随手加进 route dict 就认为已受执行层约束。

若这些能力尚不可用，插件只做本地 shadow 选择/报告，或在合成/获准脱敏 fixture 等由宿主可核验其数据与预算边界的窄场景试验；模型自称“没有敏感信息”不满足这一要求。**不能靠 prompt 中的“预算 1 元/仅本地”开启自动敏感路由**。一旦必须满足的条件无法核验，应拒绝自动选择。当前普通 managed worker 配置是 frozen snapshot，撤权必须读取当前持久 policy，而非等配置热更新。[既有安全边界](06-plugins-mcp-and-security.md)

## 7. 隐私、成本与取消

### 隐私

改变 provider 就可能改变数据接收者。已配置账号不等于允许其接收所有个人资料；硬过滤先于任何网络分类调用。分类器、embedding、reviewer、fallback 和日志平台同样是数据接收方，不能只约束最终 worker。默认本地规则不额外外发，远端分类器需明确允许的数据范围，发送最少必要片段，不附全量个人档案。

### 预算

比较**完成一个任务的总成本**，包括分类、worker 多轮、重试、升级、review、缓存写/读、工具和语音等相关调用，而非只比较一次请求的 token 单价。账本区分估算、预留、已知实际、未知费用；未知价格/用量不写零。

并发 worker 不能分别读到同一剩余额度后同时花掉它。预留必须在共享权威存储中原子完成，fallback 与 reviewer 也消耗同一任务额度。最终 provider adapter 的输出/思考上限、额外收费字段和自动增大 cap 要纳入校验；若 provider 无法给出可执行上界，只能标软预算、拒绝硬限额场景或使用明确获准的替代方案，不能承诺供应商账单绝不超额。

### 取消与在途调用

总 deadline 与 inactivity timeout 分开；取消先阻止下一次收费准入，向运行中 worker 传播停止请求。已发送模型/API 请求可能继续计费，不能把取消标成已退款。延用 [06 §8 的准入线性化](06-plugins-mcp-and-security.md#8-撤权审计与应急停止)，每个新调用和 fallback 单独准入，不复用无限期许可。

## 8. 有界 fallback 与升级

MVP 在创建 worker 时选定 route，并尽量保持整个 attempt 亲和，避免每轮重分类造成 cache 损失、模型震荡和上下文兼容问题。之后的改变只因清晰事件：provider 暂不可用、能力不支持、可验证任务失败或用户修改要求。

- 区分 transport retry、同等级故障 fallback 和能力升级。一次 429/超时不自动等于“任务太难”；权限拒绝不换 provider 绕过。
- 每任务有最多尝试次数、总 deadline、模型调用与成本上限；具体数值在测试/用户配置中确定，不能无限“便宜模型→贵模型→reviewer”。
- fallback 的每个候选都重新过隐私、模型 pin、能力、effort 和预算门禁。Hermes 非 profile route 会继承 delegation.fallback_providers；插件必须给出审核后的显式列表，MVP 可返回 `[]` 禁用未经检查的继承链。
- 切换前确认工具副作用结果；已经发送消息/创建对象的任务不能为换模型重放。无法确定是否执行时先对账。只把最小成果/证据 handoff 给新 attempt，不盲转未知格式的私有 reasoning blocks。
- 升档依据测试、schema 验证、事实核验或有限人工 review，而非模型“我没信心”的单一自评。reviewer 自身也受权限与预算约束。

## 9. Shadow 与审计

Shadow 模式保持原有、已获准的固定 delegation route，计算“建议 route”并记录比较，不改变实际 worker provider/effort，不为了验证建议再跑一份完整任务。不能承诺零成本：默认本地规则无额外 LLM 请求，但未来启用 classifier 或 replay benchmark 必须单独计量/获准。

审计最少记录：task/attempt/parent、policy/capability 版本、候选及排除原因、用户 pin、requested/effective effort、实际 provider/model/api_mode、价格来源、预算预留、fallback/retry 原因、调用数、usage、延迟、验证结果、最终状态。决策理由用简短 reason code/证据摘要，不存隐藏思考过程或全量敏感 prompt。

无法获得真实 wire effort、usage 或接收方时明确 unknown。Shadow 日志只证明建议差异，不能证明新模型会完成任务；质量/成本收益要用获准的脱敏或合成回放、可验证输出和未参与调参的测试集验证。

## 10. 相关 GitHub 实现比较

均为源码/文档审阅，**没有安装、压测或验证与 Hermes 的实际兼容**。本项目不宣称实现了 dots 或 Grokbot 的内部机制，用户观察只说明期望体验。

| 参考实现 | 已核验内容 | 借鉴与限制 |
|---|---|---|
| NVIDIA NeMo Switchyard | parent 与 sub-agent 可使用独立路由；基于可信 child/session identity 保持选择；libsy 可嵌入并有 Python binding 指引 | 最接近“委派任务分流”的设计参考；libsy 为 Beta，runner/client 更早期，standalone server 定位 demo，不直接部署为生产第二主脑 |
| LiteLLM complexity_router | 本地 heuristic，另有可选 LLM/capability 分类；tier 可附 reasoning_effort 等请求参数；有 session/cache 相关策略 | 适合已有统一 provider 网关的用户，非本项目必须依赖；分类复杂度不是准确率保证，默认 heuristic 的离线特性不能泛化到所有模式；部分调优能力有 license/entitlement 配额，采用前核对所需功能 |
| vLLM Semantic Router | complexity signal 用 hard/easy 原型差异或远端 scorer，输出 easy/medium/hard；支持显式 unknown/failure 行为 | 适合已有推理路由部署；对单用户插件引入额外服务/模型/配置负担。score margin 不是正确率，远端 embedding/scorer 同样涉及数据外发 |

固定来源：
- Switchyard `c365efe832822541024704aadf6a0d5c81cc0528`：[sub-agent routing](https://github.com/NVIDIA-NeMo/Switchyard/blob/c365efe832822541024704aadf6a0d5c81cc0528/docs/routing_algorithms/subagent_routing.md)、[架构与稳定级别](https://github.com/NVIDIA-NeMo/Switchyard/blob/c365efe832822541024704aadf6a0d5c81cc0528/README.md)。子路由需 harness 提供 child identity，不能靠 prompt 猜父/子身份。
- LiteLLM `b1d8ee719186bd7ed62e40ddf0c04035257c1943`：[complexity_router](https://github.com/BerriAI/litellm/blob/b1d8ee719186bd7ed62e40ddf0c04035257c1943/litellm/router_strategy/complexity_router/README.md)。例如 heuristic-v1 custom dimensions/tuning 有未授权时的配置数量限制；不能把整套算法概括为全部免费或全部付费。
- vLLM Semantic Router `abf9778f2cb754f015f519e3fb066ec1c5054a22`：[complexity signal](https://github.com/vllm-project/semantic-router/blob/abf9778f2cb754f015f519e3fb066ec1c5054a22/website/docs/tutorials/signal/learned/complexity.md)。

决定：先实现最小原生插件契约和本地策略。Switchyard 可作为后续嵌入算法候选；LiteLLM 作为已有网关的可选承载；vLLM SR 暂不成为依赖。任何下游路由都要暴露并限制最终模型/数据接收方，无法做到时不进入敏感/硬预算自动模式。

## 11. 分阶段路线与验收

本功能使用新增 **E9**，不重编号 E0–E8。所有实施项初始为 Backlog；本页完成不代表插件已开发。

| ID | 工作包 | 里程碑 | 依赖与交付 |
|---|---|---|---|
| E9.1 | Verify Hermes Routing Contracts | M0 | 依赖 E0；固定插件发现/route_task/结果/schema 切换契约，列出未覆盖路径和能力清单 |
| E9.2 | Define Trusted Route Context and Constraints | M1 | 依赖 E9.1、E1.1/E1.2/E1.4/E1.5 的身份/grant/撤权/数据 scope 契约，以及 E3.2 的 task/attempt 标识契约；不等待整个 E3 完成 |
| E9.3 | Build Shadow Routing and Audit | M2 | 依赖 E9.1/E9.2；本地选择建议、实际 route 不变、脱敏审计、baseline 数据 |
| E9.4 | Enable Bounded Worker Routing | M3 | 依赖 E9.3 质量证据及 E9.5/E9.6 安全 gate；只在已许可的窄任务启用，保留用户控制 |
| E9.5 | Validate Effort and Fallback Policies | M2（M3 重测） | 依赖 E9.1/E9.2；各 provider effective effort、继承链、故障/质量升级、取消与副作用不重放测试 |
| E9.6 | Integrate Budget Admission and Release Gates | M3 | 依赖 E9.2、E1.3/E1.4 的执行准入/撤权、E3.2/E3.5 的 attempt/对账契约、E8.1 审计计量和 E8.2 故障 fixture；预算预留/对账与路由发布 gate，不等待整个 E8/M4 发布 |

主顺序：E9.1 → E9.2 → E9.3 shadow；E9.5/E9.6 可并行验证，但所有启用门槛通过后才进入 E9.4。禁止为了先演示自动切换而跳过可信 context 或硬预算缺口。

### 必测场景

1. 用户配置/允许之外的 provider/model 永不被选；用户 pin 不被自动优化覆盖。
2. 模态、工具、schema、context、effort 不支持或 unknown 时给出确定结果；无合法候选不能偷偷继承任意父 route。
3. 中英文、短难题、长简单任务、误导性难度提示和 tool-output injection；分类器不是权限源。
4. requested/effective/wire effort 分开，none 不支持、厂商升档特例、未知 endpoint、service tier 资格、最终输出 cap 都有覆盖。
5. 同一剩余额度被多个 worker 并发使用、预留后崩溃、使用量晚到、价格未知、取消仍计费，均不能虚报硬预算保障。
6. classifier/reviewer/embedding/fallback 与主 worker 同样受隐私 scope 和预算约束；敏感数据不被 shadow 日志或远端 scorer 额外泄露。
7. selected backend 缺失/不可用、route_task 异常与网络故障按原生合约 fail-closed，验证单任务拒绝/批量兄弟任务边界；插件未加载不能自行提供 shadow，也不能自动换回 default。只有 owner 明确切回已批准的静态配置才恢复相应委派。Shadow 只适用于插件已成功加载且用户已选定 shadow 模式的路径；safe-mode/缺可信 context 时不得启用自动选择，保留受支持的只读诊断，或在已具备合格 shadow 路径时仅做模拟。
8. 429、鉴权失败、工具副作用未知、质量测试失败分别处理；禁止无界升级、重复外发或用切模型绕过拒绝。
9. 安装/启用插件不自动切 backend；owner 明确选择后默认 shadow，有合法静态 baseline 才运行；缺基线不得任意继承父 route。普通配置保存、新会话、`/delegation <backend> --now`、resume/compression 的 schema/backend pin 一致。切回 default 是明确操作，新旧会话与在途任务行为可解释；不能宣称配置一保存就即时切换所有任务。
10. 以固定模型池/工具/数据集比较 task success、每成功任务总成本、p95 完成延迟、route 开销、误降档、fallback 次数和人工介入。收益必须包括 classifier/reviewer/retry 成本，安全失败为零且满足预先声明的质量门槛才逐步扩大。

未知、失败、未运行的测试分别列出。发布只证明已验证场景，不承诺路由一定更便宜或更正确。插件可停用/回到获准静态配置，但撤权和预算安全门禁不能随回退一起被跳过。
