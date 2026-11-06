# 18. Owner 入口与只读授权基础

[English](18-owner-entry-and-read-authorization.md) | 简体中文

**已实现：确定性的内部读取评估器，以及不读取个人数据的访问诊断。尚未实现：生产身份签发入口、owner 登记、真实私人读取、grant/policy 存储、主 Bot 绑定或受控写入。** 本切片推进 E0.7 和 E1.1/E1.2 的准备部分，不代表其发布门禁完成。[主 Bot 方案](15-primary-bot-binding-zh.md)仍受门禁约束。

基线为 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。测试本切片不需要 API Key；补充模型凭据也不能解决宿主可信契约缺失。

## 1. 为什么渠道身份仍然不够

官方 slash-command 回调提供 `source`、`platform`、`session_id` 与 `session_key`。`source` 来自 adapter，包含稳定 user/chat ID；宿主文档明确说明它是 transport identity，不是授权 grant [I1]。它比名字或命令正文更适合作为候选输入，但仍不具备全部必要边界。

同一个 runtime profile 可能接收多个 transport Bot 的消息。公开的 `SessionSource.profile` 表示运行时路由；接收 adapter 被保存在私有动态属性 `_transport_adapter_ref` 中，由私有宿主代码解析 [I2]。本插件不导入或使用这些内部实现。Hosted IPC 只序列化声明的 dataclass 字段，会丢弃该动态引用 [I3]。因此，两个公开 actor/chat/profile 字段相同的回调，可能来自不同接收 Bot。

仅按 user/chat ID 设置 allowlist，会暗中允许这两条路由访问数据，不符合[文档 15 的选定 Bot 边界](15-primary-bot-binding-zh.md)。在受支持的接收 transport/account 契约可用前，私人任务读取与绑定仍须拒绝。Profile 名称、本地 CLI 操作者、HTTP authenticated 布尔值或 `Bot Chat` 标题匹配都不能补足缺口。

## 2. 可运行诊断

插件只新增以下不读取个人数据的 slash 诊断：

```text
/personal-access
/personal-access status
```

本地 CLI 对应入口没有 transport source：

```bash
hermes personal-agent access
```

返回 JSON，包含 `schema_version: personal.access-diagnostic.v1`、`status: blocked`、`decision: deny`、有界原因码、只含布尔值/platform 类别的 `actor_observation`、缺失契约名称，以及均为 false 的 `protected_reads_enabled` 与 `primary_binding_enabled`。诊断成功运行不等于授权成功。CLI 可以因诊断本身正常完成而成功退出，但响应仍为 blocked。

输出不包含私人 ID、profile 路径、账号名称、任务内容、token 或原始命令参数。诊断不读取配置、任务存储或个人数据，不创建会话、启动 gateway、签发 ticket、绑定 Bot 或另行发送消息。原生宿主展示普通命令结果，这不是持久投递 receipt。

仅接受空参数或 `status`，输入上限 32 字符。`--owner`、`approved` 或任意 JSON 声明均无效。缺少 source 返回 `source_unavailable`。CLI/Desktop/local 和未测试平台返回不可用或不支持结果，不回退到默认 owner。

对于可识别的 Telegram DM 候选，观察器检查平台匹配、精确布尔型的非 bot/非 relay/路由未拒绝信号、没有线程或群组 scope，以及相同的正十进制 user/chat ID。它处理公开属性投影，包括 hosted IPC Record，而不要求特定宿主类。这只识别一种结构，**不证明真实性**。即使 source 形状完美，仍返回 `receiving_transport_unverified`，绝不创建 verified context。回调没有完整 forwarded/internal 来源信息，因此诊断也不能证明是直接 owner 指令。

唯一的模型工具仍是 `personal_agent_status`。Status 现区分已实现的评估器、缺失的生产 context issuer 与仍关闭的私人读取。不新增任务工具、读取数据的 slash 命令、HTTP 路由或可修改 policy 的命令。

## 3. 纯内部只读评估器

`personal_agent.authorization` 定义 frozen、slotted 内部记录：

| 记录 | 含义 |
|---|---|
| `VerifiedReadContext` | 已由独立机制验证的 owner/profile、transport/receiver、principal/session、policy revision/epoch 及自有任务 ID |
| `ReadGrant` | 精确身份与读取 scope、resource ID、可信当前撤权状态及 UTC 有效区间 |
| `ReadRequest` | 单一 operation、target、resource-ID tuple 与 data scope |
| `ReadDecision` | 仅有 `allowed` 与稳定原因码 |

这些 Python 对象**不是身份认证证明或沙箱**。任意同进程代码都可以构造或修改它们。本切片没有生产函数签发 VerifiedReadContext，没有从 JSON 导入它、登记 owner 或提供真实 grant。诊断不会用猜测的身份调用评估器。Allow 结果只在完整指定的合成内部 fixture 中验证。

`evaluate_read` 要求未来可信调用者显式提供当前 policy revision、epoch 和 UTC 时间，不执行 I/O 或读取时钟。校验拒绝错误或缺失字段、子类/未初始化记录、可变 ID 容器、未知 operation、通配符、无效时间及 scope 冲突。Opaque ID 为 1–128 个 ASCII 字母/数字或 `._:-`；ID tuple 不重复且最多 1,024 项。Revision/epoch 必须是从零到有符号 64 位最大值的精确整数，不能是布尔值。

六项身份必须与 grant 一致：owner、profile、transport、接收 transport 账号/Bot、principal 和 session。Context 与 grant 的 revision/epoch 都必须等于可信当前值。已撤销 grant 拒绝。时间必须是精确内建 UTC datetime，满足 `not_before <= now < expires_at`，不猜测时区或强制转换数字时间。

评估器只支持两个 operation：

- `personal.tasks.read` 配合 `tasks.summary`，target 为非空且明确的自有任务 ID 集合，或显式命名且不携带 ID 的 `own_inbox` 集合。精确请求可以是精确 grant 的子集，但 grant 中每个 ID 都必须独立属于 context。整个收件箱授权仅限该 owner/profile，不是全局 SQL 权限。
- `personal.primary_binding.inspect` 配合 `primary_binding.metadata`，target 为该 profile 的绑定元数据，不含 resource ID。它不是创建、确认、恢复或激活绑定。

没有 target 隐式转换、写 scope、委派权限或宽泛通配符。未来 adapter 必须对资源查询执行获准字段投影与 owner/profile 过滤；评估器本身不读取或脱敏记录。`tasks.summary` 只用于最小任务投影，不含完整详情、来源正文、秘密或任意附件。

## 4. 当前 Policy 与竞态边界

评估器检查传入的 snapshot，不持久化也不证明其新鲜度。它不是 E1.4 hard revoke、事务准入记录、grant issuer 或执行引擎。未来领域读取必须一致地取得当前身份、policy/撤权和获准资源 snapshot。调用者不能把旧缓存 policy 的 revision 复制到两个输入中，就声称它是当前策略。

任何读取判断都不能复用于后续修改或其他 scope。外部执行仍需[文档 06](06-plugins-mcp-and-security-zh.md)规定的独立授权提交与 effect/对账协议。内部 allow 不证明动作已发生、数据已投递或所有 Hermes 路径都受保护。

现有显式本地任务 CLI 仍是独立的可信本地操作者功能，不会通过该评估器获得 verified owner 身份，新诊断也不会将该收件箱开放给渠道。

## 5. 下一步最小通用宿主契约

受支持的 command/HTTP adapter 需要**宿主签发、服务端推导的 context**，而不是另一套插件登录服务。具体 API 命名由上游设计决定，本文件不声称固定版本已有这样的统一 accessor。最小证据必须区分：

1. 已认证 actor 与 issuer、actor 类型、直接/转发/内部来源，以及当前 session/credential 权限。
2. 接收平台账号/Bot 与 transport profile，并与执行 runtime profile 及已验证宿主权限观察分离。
3. 无法被命令正文、请求 JSON、header 或对端提供的 record 覆盖的 routing/profile scope 来源。
4. In-process 与 isolated-host 边界的版本化传递，保留相同保证，或明确标识缺失证据。
5. Adapter 每次受保护读取前查询当前 owner binding 与插件 policy。宿主认证本身不是该绑定。

Context 缺失或不受支持时，插件必须 fail closed。私有 adapter 导入、环境变量回退、同名标题匹配、首条消息自登记或本地 CLI 签发凭据，都不是可接受的绕路。现有 Desktop `host.profileRoutes()` / `host.requestProfile()` 是有用且受支持的 canonical 观察路径 [I6]，但不因此提供领域 owner grant。

## 6. 测试与发布含义

单元测试覆盖严格类型/不可变性、精确身份/scope/所有权、错误 receiver/session、policy/epoch 变化、已撤销/过期 grant、无效时间、禁止写操作及脱敏结果。Source 观察器测试包含缺失、错误、群组/线程、bot、relay 和不匹配的 context。

固定宿主契约验证真实插件注册/派发/重载/卸载和序列化行为，展示接收 adapter 引用丢失，而非假装它被保留。注入测试覆盖 `allow_gateway_control=False` 下的原生 resolver 与 quick/plugin dispatch sink，不覆盖完整 inbound pipeline。只调用回调的 fixture 不等于验证安全入口。Hosted HTTP 的 admission 布尔值仍不充分 [I4]。未测试真实个人账号或生产绑定。

请在待验证 commit 上运行[全仓检查器](../README-zh.md#开发验证)。E0.7 仍是部分进展，E1 owner 登记/当前 policy 持久化仍未实现，主 Bot、私人读写发布门禁继续关闭。未来连接配置及任何持久访问应使用获准的原生安全流程，不应要求用户在聊天中粘贴秘密。

## 7. 固定源码证据

- I1：[公开 slash context 与授权注意事项](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#L1796-L1816)。
- I2：[接收 adapter 附加](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/platforms/base.py#L4751-L4754)及[私有 transport/runtime 解析](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/session_identity.py#L109-L121)。
- I3：[Host IPC 序列化](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_host_wire.py#L132-L164)。
- I4：[Hosted HTTP admission 标记](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_host_http_auth.py#L17-L23)。
- I5：[原生命令派发](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/run_inbound_hooks.py#L262-L301)及[注入命令控制标志](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/platforms/event.py#L176-L185)。
- I6：[Desktop 路由感知宿主 API](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md#L1446-L1514)。
