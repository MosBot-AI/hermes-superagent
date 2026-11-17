# 38. 已保存路由就绪诊断

[English](38-routing-readiness-inspection.md) | 简体中文

状态：**已实现只读原生 CLI 诊断。** 本切片在[离线路由前置切片](35-offline-worker-routing-zh.md)上增加对已保存本地 delegation 声明的检查。不实现路由 backend，也不认证在线 shadow 基线。

## 入口与范围

在普通进程内 Hermes 安装中启用本插件后，运行：

```bash
hermes personal-agent routing inspect
```

既有 `personal-agent` CLI 在 `read_only` 和 `local_tasks` 模式下均注册此子命令。没有新增斜杠命令、模型工具、HTTP 入口、backend 注册或启用设置。不提供选择其他 profile、model、endpoint 或配置文件的参数。通用状态会显示已有诊断能力，但不读取配置。

检查器通过宿主当前选择的本地 `FileBackend` 读取该注册所绑定 profile 的已保存用户层文档。不合并默认值或 managed overlay，不展开环境变量引用，不解析模型别名或凭据，不加载已选 delegation backend，不检查其他 profile，不启动 worker，也不调用模型。不修改配置、任务/记忆存储或路由选择。普通 Hermes 启动仍由宿主管理，包括既有 config/bootstrap 行为；检查器不宣称可以屏蔽所有宿主启动日志或副作用。

如果选中远程/自定义配置 backend，会在读取其文档前拒绝，不以读取本地影子文件作为替代。managed worker，包括普通冻结配置 worker 和 safe worker，都会在读取 profile 前被拒绝。profile 改变、回调已卸载、宿主 API 不可用、文档损坏或读取失败均返回有界错误。本地用户配置缺失或为空时，只报告未声明设置，不视为可用固定基线。

## 如何理解报告

`scope` 始终为 `saved_user_config_only`。`status: ok` 和退出码 0 只表示已检查保存的声明，**不表示可以开始执行**。诊断被阻止时退出码为 1，语法/参数错误遵循宿主 CLI parser。每个报告的 `execution_authorized`、`shadow_ready`、`automatic_routing_ready` 和 `plugin_live_routing_enabled` 均为 false。最后一项只描述本插件，不判断其他已安装 backend 是否已在路由 worker。

报告区分显式 provider/model 或 endpoint/model 声明，以及依赖父路由、profile、backend 或未指定/未解析的情况。这些是配置字面结构，不预测宿主将采用哪个凭据解析分支或实际 route。provider/model/endpoint 身份与能力核验仍未执行。

警告突出固定版本宿主的重要区别：

- 仅保存主 agent 模型不证明 worker 已被固定。父路由和既有 session backend pin 未被观察。
- 显式空 `fallback_providers: []` 与缺失/null、有内容和格式错误的声明分开报告。不认证实际 fallback 链。profile/自定义 backend 可替换这些字段。
- 已识别的请求 reasoning effort 与未知的 effective wire effort 分开显示。自定义映射不展开检查；声明禁用思考不证明 provider 能禁用。
- 固定版本的默认 backend 会移除 `delegation.service_tier`；诊断不会把它视为实际速度或收费设置。自定义 backend 的语义仍未知。
- `child_timeout_seconds` 是无活动超时，不是整个任务的总截止时间。
- request override 和内联凭据字段只按是否存在提示，不复制或求值其内容。

报告列出剩余未知项：当前 session/backend 状态、凭据有效性、实际 endpoint/接收范围、能力、effort 编码、service tier、fallback、用量/费用、授权及预算/取消执行保障。报告包含目标 Hermes commit，但不核验当前运行宿主的 commit。E9.1 仍为部分完成，可信上下文及 E9.2–E9.6 运行门禁仍未关闭。

## 隐私与生命周期

输出只由固定分类、原因码和已识别的 effort 枚举构成。不包含调用者提供的 provider/model/backend/profile 名称、URL、API mode、路径、密钥值、哈希、任意字段名或异常明细。不递归检查未知嵌套设置和 fallback 项。与离线样例报告允许调用者提供不透明 ID 不同，此诊断不输出原始身份引用。

命令仍会读取可能包含密钥的本地配置文档。它只最小化输出，不能替代宿主密钥存储、文件权限、日志脱敏或可信代码审查。注册时绑定解析后的 profile。两个命令在读取前、读取后及计算报告后均核验 profile 和注册状态。如果操作期间发生 profile 切换或插件卸载，命令会丢弃结果。不写入审计文件或持久化快照。

## 已保存的能力登记表

运行 `hermes personal-agent routing inventory` 校验已保存的登记表并查看路由数。追加 `--route synthetic-text` 可按区分大小写的精确路由 ID 查看单条路由的能力观测结果。此诊断沿用上述已保存用户层、profile 与卸载检查，并读取以下规范的 `settings` 配置位置。

```yaml
plugins:
  entries:
    hermes-personal-agent:
      settings:
        routing_inventory:
          schema_version: personal.routing.registry.v1
          routes:
            synthetic-text:
              binding:
                provider: synthetic-provider
                model: synthetic/text-v1
                account_ref: synthetic-account
                api_mode: synthetic-mode
                transport: https
                endpoint_ref: synthetic-endpoint
                recipient_scope_ref: synthetic-recipient
                data_scope_ref: synthetic-scope
              evidence:
                synthetic-observation:
                  source: native_contract_test
                  observed_at: "2026-11-16T12:00:00Z"
                  valid_until: "2026-11-17T12:00:00Z"
              capabilities:
                text: {state: supported, evidence: synthetic-observation}
                image_input: {state: unsupported, evidence: synthetic-observation}
                context_tokens: {state: supported, evidence: synthetic-observation, value: 8192}
                health: {state: unknown}
```

每条路由均声明完整绑定。账号、端点、接收方范围与数据范围均使用不透明引用。路由 ID、证据引用及绑定标签使用 1 至 96 个 ASCII 字母、数字、点、下划线或连字符，首字符为字母或数字。模型标识还可使用斜杠或冒号作为分隔符，长度上限为 128 个字符。传输类型为 `in_process`、`local_process`、`local_http` 或 `https`。密钥应存放在 Hermes 凭据存储中。清单无法验证所引用的身份、权益或隐私范围。

登记表最多包含 64 条路由，每条路由最多 64 条证据记录。证据归属特定路由，并声明来源类别（`provider_documentation`、`account_configuration`、`native_contract_test` 或 `operator_observation`）以及加引号、精确到秒的 UTC 观测与到期时间。每项 `supported` 或 `unsupported` 能力引用一条证据。有效期包含观测时刻，排除到期时刻。已过期和尚未到观测时间的记录均显示为 `unknown` 并附带时效原因。省略某项与显式声明 `unknown` 等价。

可声明存在性的能力包括 `text`、`image_input`、`audio_input`、`tool_calling`、`structured_output`、`reasoning_effort`、`reasoning_token_budget`、`reasoning_toggle`、`reasoning_disable`、`service_tiers`、`cache_metering`、`usage_metering` 和 `pricing`。价格项记录证据来源。受支持的 `context_tokens` 或 `output_tokens` 提供不超过十亿的正整数。受支持的 `health` 提供上次观测得到的 `available`、`degraded` 或 `unavailable`。

`personal.routing.inventory.v1` 报告返回声明的登记表版本和路由数。精确查询还返回固定能力名、证据类别、时效状态及可识别的当前值。报告省略路由 ID、绑定内容、证据引用和时间戳。未配置登记表时报告 `not_configured`。任一记录无效时会阻止整个登记表并返回固定原因码。精确查询不存在的路由也会以退出码 1 返回。即使存在当前有效的证据，就绪与执行标志也保持为 false。登记表条目属于本地操作员声明。

## 验证与限制

登记表测试覆盖能力状态、观测与到期边界、同一路由内的证据和脱敏失败。Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上的离线集成测试通过真实本地配置 backend 调用已注册的 CLI，并验证卸载后或使用非文件 backend 时拒绝操作。[原生路由契约测试](../tests/contracts/test_worker_routing_contracts.py)覆盖该固定版本的 delegation provider 注册、路由解析与会话 schema 行为。

单元测试覆盖错误声明、字面路由结构、环境变量引用、请求/实际 effort 区别、fallback 状态、无效 tier/超时警告、封闭错误码和输出最小化。原生契约覆盖真实注册和顶层 CLI dispatch、读取最新保存配置但不修改缓存、损坏文档、读取和计算期间的卸载与 profile 切换、非文件 backend 拒绝、未知 backend 错误、冻结/safe worker 拒绝，以及默认 backend 对 service tier 的固定版本行为。测试使用合成临时 home 和网络阻断，不使用真实账号、provider 请求或 socket 绕过。

使用固定 Python 3.14 环境，按 [README](../README-zh.md#开发验证) 运行完整检查器。此命令不测试实际 worker 执行、hosted-plugin IPC、在线 backend 健康、provider 编码、权限、预算或生产配置验收。不能把其成功退出码作为启用路由的准入凭证，仍须通过[路由设计](11-worker-model-routing-zh.md)和[路线图](08-roadmap-and-acceptance-zh.md)门禁。
