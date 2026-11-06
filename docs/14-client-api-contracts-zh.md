# 14. 拟议客户端 API 与连接器合同

[English](14-client-api-contracts.md) | 简体中文

**状态：仅设计。下文所有新的 domain endpoint、DTO、能力标志、策略 scope、保留期限和连接器接口均为拟议，尚未实现。** 当前实现切片没有暴露这套 API，没有证明端到端 owner 授权，也没有启用受控外部效果。[18](18-owner-entry-and-read-authorization-zh.md) 的内部读取评估器和保持阻断的访问诊断只是局部准备，不代表 E1 授权已经完成。检查 Hermes 源码不等于运行时认证。已核对的源码基线为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`；基础实现证据见 [12](12-foundation-progress-zh.md) 和 [13](13-enforcement-contracts-zh.md)。

原生 Primary Bot 选择与绑定的拟议合同见 [15](15-primary-bot-binding-zh.md)。该能力实现后，将增加仅 owner 可用的绑定控制、经过授权的绑定摘要快照及绑定/投递失效通知。这些服务方法不是下文已经注册的路由；未来 HTTP facade 仍须满足本文可信 principal、幂等与 transport 门禁。原生 Bot 选择不需要自建手机 App。

拟议[统一语音合同](19-unified-voice-provider-contracts-zh.md) 增加经能力协商的本地/在线媒体适配器与通话控制。可选 HTTP facade 可以暴露经过授权的通话摘要与控制回执，但领域变更流不承载/重放麦克风音频。串流只使用已验证的原生/provider 媒体传输；被缓冲的 hosted 插件 HTTP 不会因此变成 WebSocket/音频路由，语音配置也不能绕过可信 principal 门禁。

本文将 [10 的领域合同](10-interface-contracts-zh.md) 具体化，供可选客户端使用；不替代[授权设计](06-plugins-mcp-and-security-zh.md)、[移动端范围](07-mobile-and-voice-zh.md)或[路线图](08-roadmap-and-acceptance-zh.md)。

## 1. 分层与发布边界

| 层 | 负责 | 不得演变为 |
|---|---|---|
| Hermes 原生渠道与会话传输 | 已认证的平台输入、会话所有者、agent loop、持久化接纳、工具执行、原生审批、流式输出、调度和 worker | 第二套个人 agent 运行时 |
| 个人领域服务 | 业务项目、承诺、任务验收、intent/grant、策略检查、effect/outbox/receipt 记录、授权后的数据投影 | 平行的完整聊天记录、调度器、凭据保险库或通用工具执行器 |
| 拟议领域 HTTP API | 与工具/渠道 handler 共用领域服务的类型化命令和读取 | 绕过原生权限或操作级权限检查的通道 |
| 可选客户端 | 展示、安全的本地草稿、请求 ID、重连和用户决定 | owner 身份、grant 或“执行成功”结论的签发者 |

**M1 始终优先使用现有渠道。** 手机入口是一个现有 Hermes 消息渠道，不依赖 E6.5–E6.7、PWA/原生 App、自建推送或另一套 gateway 部署。HTTP facade 尚未存在时，领域工具和已认证的渠道 handler 即可共用这些服务。可选 M2/M3 客户端复用已部署的原生宿主和传输。

项目标识有两类：插件的不透明业务 `project_id`，以及经验证的 `native_refs`，例如 Hermes 项目/看板引用。GitHub Project issue/item 属于工程规划元数据，不是运行时任务身份。客户端不得从一种 ID 推导另一种 ID，也不能通过提交其他 owner 的原生引用获得访问权限。

## 2. Hermes 实际承载方式与缺失接缝

### 2.1 Dashboard 插件注册

固定版本的 Python plugin context 没有 `ctx.register_http_router`。官方挂载方式是插件 dashboard manifest 加模块级 FastAPI router [H1, H2]。以下是**未来文件布局示例**，不是本设计新增的运行时文件：

```text
hermes-personal-agent/
  plugin.yaml
  dashboard/
    manifest.json
    plugin_api.py
```

```json
{"name":"hermes-personal-agent","api":"plugin_api.py"}
```

```python
from fastapi import APIRouter

router = APIRouter(prefix="/v1")
# 身份和策略关卡具备后，才在 router 上声明未来的类型化路由。
```

Hermes 将该 router 挂载到 `/api/plugins/hermes-personal-agent`。因此拟议绝对基路径为 **`/api/plugins/hermes-personal-agent/v1`**，下文简称 `B`。`B` 只是文档缩写，不是字面 URL。部署时保留经过验证的反向代理基础前缀。不要声称这些路由存在于独立的原生 API-server listener 上。

正常 HTTP 鉴权先于插件 handler。未认证请求先收到 401，不暴露插件是否存在；已认证请求访问禁用/未知插件时收到 404。用户 Python 插件必须由宿主启用；项目目录内的 dashboard 插件不会自动导入 Python。宿主负责绑定 profile home 和 secret scope。成功导入模块不代表有权执行操作。

### 2.2 宿主模式能力协商

| 已核对的宿主行为 | 对拟议 API 的影响 |
|---|---|
| 进程内 handler 共用宿主事件循环 | 阻塞工作使用异步 I/O 或 worker thread；限制并发和请求体大小 |
| `plugins.isolation: host` 缓冲转发的 HTTP 响应 | 有界普通 JSON 轮询是正确性路径；不得宣称支持插件 SSE |
| 托管插件不支持 WebSocket；次级 profile socket 可能返回 501 | 没有真正受支持且通过测试的路由时，`domain_websocket` 保持 false |
| Desktop 插件 `ctx.socket` 在 OAuth remote 上是 no-op | 不得把 socket 可用性当作状态恢复的前提 |
| 插件广播是实时、进程内、fire-and-forget | 只能作为刷新提示，不是持久化操作或送达回执 |
| 宿主鉴权存在多种 credential/principal 形状 | 每种模式都要验证规范化的可信 principal adapter，包括 host IPC |

不要为了可选 UI 而关闭隔离。未发现原生通用 `ctx.current_http_principal()` 合同。特别是，隔离宿主的 `with_hosted_admission` 只设置 `hosted_http_authenticated: true`；这个布尔值只是准入决定，**不是经过验证的 owner/principal/profile/policy 上下文** [H13]。原生请求的 `request.state.native_http_principal` 也不是通用 plugin-context API。E0.6 必须验证受支持、规范化的宿主边界，或者提出**具有本项目具体使用方的通用上游 principal 接缝**。隔离 host IPC 的可信身份透传是明确的未解决阻塞项。插件不得自行解码 cookie、接受客户端身份，或信任任意转发身份 header。若无法取得已验证的 principal/profile，受保护读写均返回 503 `host_identity_unavailable`，不得退化到默认 owner。已认证但尚未绑定的用户收到 403 `owner_binding_required`。

## 3. 鉴权不等于领域授权

### 3.1 既有宿主鉴权路由

以下是既有宿主路径，**不是新增领域 endpoint** [H3–H5]：

| 方法/路径 | 既有用途与限制 |
|---|---|
| `GET /api/auth/providers` | 发现可用的交互式宿主登录 provider |
| `GET /auth/login`, `GET /auth/callback` | 宿主浏览器登录和回调 |
| `POST /auth/logout` | 宿主注销行为；不能证明所有设备/凭据均被撤销 |
| `GET /api/auth/me` | 脱敏后的已验证 session 或已认证 loopback 身份 |
| `POST /api/auth/ws-ticket` | 已验证交互式 session 获取有效期 30 秒、单次使用的 WebSocket ticket |
| `GET /auth/native/authorize` | 系统浏览器原生登录，使用 S256 PKCE 和严格 loopback 回调 |
| `POST /auth/native/token` | 用 `{code, code_verifier}` 兑换原生 bearer token |
| `POST /auth/native/refresh` | 通过宿主刷新 `{refresh_token, provider?}` |

Dashboard cookie、原生 App bearer 凭据、已启用的 deployment/session-token 模式和原生同用户 grant，签发与撤销规则各不相同。私有 native grant header 不是手机可从远端签发的凭据。原生 API-server 的 `API_SERVER_KEY` 不会自动成为 dashboard 插件路由的凭据。本设计不增加插件登录数据库、token 签名服务或 refresh-token 存储。

Canonical 本地会话有意允许**同一 profile** 中经过验证的操作员跨宿主鉴权路径附加会话。这不会在共享操作员 profile 内建立逐人隔离。首期部署是一个可信 owner/profile；多个 owner 应使用独立 Hermes profile，除非另有独立验证过的受限宿主策略。插件 ACL 无法隐藏操作员本来就能通过宿主原生 API 读取的数据。

### 3.2 拟议信任请求上下文

由 adapter 而非 JSON body 构造：

```json
{
  "principal_id":"verified-host-subject",
  "issuer":"verified-host-issuer",
  "profile_id":"opaque-host-profile-ref",
  "owner_id":"own_example",
  "credential_class":"interactive_session",
  "auth_context_id":"server-owned-binding",
  "permission_revision":12,
  "policy_revision":31,
  "domain_scopes":["personal.read","personal.tasks.write"],
  "request_id":"req_example"
}
```

这些是**拟议内部字段**，不是 Hermes 原生 payload。不得在其中存储 bearer token。`domain_scopes` 是插件策略名称，不是新增宿主 token claim：`personal.read`、`personal.projects.write`、`personal.tasks.write`、`personal.commitments.write`、`personal.automations.write`、`personal.actions.prepare`、`personal.actions.execute`、`personal.approvals.decide`、`personal.connectors.sync`、`personal.artifacts.write`、`personal.control.revoke`。持有其中某项也不能覆盖源 ACL、收件人/数据限制、具体操作审批、当前策略或原生能力。Prepare scope 不会隐式授予 execute scope。受限工具/worker surface 在受支持的创建边界选择，不通过破坏缓存的会话中途 prompt 修改实现。

每次读取和命令都检查当前 credential、owner binding、profile、对象/源 scope、policy revision 和允许的状态转换。不得根据展示名、模型输出、源 URL、转发消息、请求 body `owner_id` 或 correlation ID“修复”被拒绝的身份。HTTP body 不得提供 `approved`、`principal`、`grant`、`policy_revision`、原始凭据或任意原生路由字段。原生引用必须通过已检查访问权限的服务端 resolver 才能接受。

### 3.3 浏览器、网络与手机登录关卡

- 复用 Hermes 的 Host/Origin 检查、已认证 session 过期和 cookie 防护。所有拟议不安全浏览器方法还须验证同源请求，或者验证显式允许的 origin 加宿主认可的防 CSRF 机制。某个宿主模式无法提供此保证时，禁用该模式下 cookie 鉴权的 mutation。无效 bearer 不得意外退回 cookie 鉴权。
- CORS 使用明确 origin allow-list，不得通配同时携带凭据。使用已验证 TLS/反向代理；不要把公开 wildcard 绑定当安全部署方案。GET 不执行领域 mutation 或外部操作。所有敏感响应使用 `Cache-Control: no-store`。
- 固定版本的原生登录回调只允许规范化的 `http://127.0.0.1[:port]/...` 或 `http://[::1][:port]/...`，拒绝 `localhost`、App scheme 和 claimed HTTPS 手机回调 URL。支持 PKCE 不代表 iOS/Android 客户端可用。
- 可选 PWA 首先使用已有浏览器登录。E6.7 在支持的回调路径、目标设备恢复、安全凭据存储和设备撤权得到验证前保持 Blocked。若需要通用 callback/device-control 扩展，应放在现有宿主边界，而不是平行插件鉴权服务。
- Webapp 注销和原生 App 凭据的生命周期不同。浏览器注销可使绑定的浏览器 socket 失效，而原生 App 登录仍然存续。没有已验证宿主机制时，不承诺“注销撤销全部设备”。插件硬撤权仍须阻止被撤销 binding 后续的领域接纳。

## 4. 拟议传输约定与限制

本节所有数值都是**项目设计值**，不是观测到的 Hermes 默认值。

| 合同 | 拟议 v1 数值 |
|---|---|
| 编码/版本 | UTF-8 JSON；路径主版本 `/v1`；`schema_version: "personal.api.v1"` |
| ID/时间 | 不透明、区分大小写的 ID；RFC 3339 UTC 时刻；另存 IANA 时区 |
| JSON 请求体上限 | 256 KiB；单独设关卡的二进制上传路由除外 |
| 分页 | `limit` 默认 50、范围 1–100；不透明 cursor；列表不提供无界导出 |
| 读取超时/轮询 | 客户端超时 15 秒；前台每 5 秒、空闲每 30 秒轮询；离线指数退避到 60 秒并加 jitter |
| 幂等键 | 提交前生成的 UUIDv4；每个拟议 POST/PATCH 命令必填 |
| 幂等保留 | pending/unknown reservation 保留至解决；完整结果在终态结算后保留 7 天；随后再保留 key/digest tombstone 90 天 |
| 审批展示 | 新生成的 256-bit 随机 nonce；默认 5 分钟过期；一次成功决定后消费 |
| 变更保留 | 每 profile 最多 7 天或最新 100,000 条，以先到的过期条件为准 |
| 快照 | 某个已提交 watermark 上不可变的授权投影；TTL 15 分钟；每页 100 行；总上限 10,000 行/10 MiB |
| 可选上传 | 每文件 20 MiB，每请求一个文件，每 owner 最多 10 个 pending upload；完成 TTL 1 小时 |
| 可选 artifact | 无引用 staging 24 小时后过期；已引用对象在元数据中明确保留期；不暗示永久保存 |

幂等 namespace 是 `(owner, profile, method, normalized route, key)`，同 owner 的已验证 cookie/native 鉴权路径之间保持稳定。原 principal/auth context 仅保留作审计，不用于拆分去重范围。对规范化后的已验证命令、资源 revision 和 domain scope 计算 digest，不包含 transport credential。使用确定性 JSON canonicalization（RFC 8785）和 SHA-256，拒绝非有限数值和有歧义的重复 JSON key。完全相同的重试在检查当前调用者访问权限后返回原回执，并设置 `Idempotency-Replayed: true`；不会继承原调用者的权限。digest 变化返回 409 `idempotency_conflict`；结果已过期但仍有 tombstone 时返回 409 `idempotency_expired`，不执行。key 永不复用，包括 tombstone 过期后。客户端必须先 reconcile 再创建新 key；过期不代表可以重复副作用。

数据库事务共同保留命令、更新领域状态并写 changes/outbox。原生 dispatch 和远端 effect 仍属于不同事务：使用稳定 effect key 和 reconcile，不宣称跨系统 exactly-once。接纳前校验失败且未创建 reservation 时，可用原 key 修正；一旦保留，修改 payload 必须用新 key 并重新满足相应授权。

单资源读取返回 `ETag: "<id>:<revision>"`。PATCH 和针对既有资源的状态变更命令必须提供完全匹配的强 `If-Match`；缺失返回 428，陈旧返回 412。准确幂等重试应在因旧 ETag 而拒绝前识别，但仍须先检查当前鉴权/授权。写响应代表已提交状态，不证明原生或远端 effect 已完成。

```json
{
  "schema_version":"personal.api.v1",
  "request_id":"req_example",
  "data":{"id":"task_example","revision":3,"status":"ready"},
  "operation_id":null,
  "error":null
}
```

列表在 `data` 中放置 `{items, next_cursor, has_more}`；普通列表不是跨资源快照。错误设置 `data: null`，在 `error` 中放置 `{code, message, retryable, field_errors?, recovery?}`。`message` 仅用于展示，客户端按 code 分支。`recovery` 包含枚举和已授权对象引用，不包含秘密或任意导航 URL。日志记录 request/operation ID 和脱敏元数据，不记录 token、approval nonce、原始审批 payload 或上传内容。

| HTTP | 含义/示例 |
|---|---|
| 200 / 201 | 读取或已提交本地变更 / 已创建本地对象 |
| 202 | 持久化操作已接纳，须查询状态；不是“完成”或“送达” |
| 400 / 422 | JSON/header 格式错误 / 格式正确但命令字段无效 |
| 401 / 403 | 缺少鉴权或已过期 / 已认证但操作不被允许 |
| 404 | 对象不存在或不在 scope；不泄露其他对象存在性 |
| 409 | 幂等冲突/过期、决定已结算、非法转换、未知结果需 reconcile |
| 410 | snapshot/change cursor 或审批展示过期；重新读取授权状态 |
| 412 / 428 | revision 不匹配 / 缺少前置条件 |
| 413 / 415 | 超过大小上限 / 不支持的媒体类型 |
| 429 | rate/budget 接纳被拒；遵守 `Retry-After`，不切换凭据绕过 |
| 503 | 宿主身份、策略/存储、native adapter 或 draining 状态不可用；fail closed |

## 5. 路由注册表与资源形状

下列所有路由都**拟议位于 B 下**。其他章节的宿主 auth 路径和 canonical RPC 不是它们的别名。拒绝未知命令字段。所有读取都要求 `personal.read` 加对象/源权限；表中列出额外 mutation scope。不提供通用 `tool_name + args` 执行器、任意 URL 代理、SQL endpoint 或客户端指定文件系统路径。

### 5.1 发现与读取模型

| 方法/路径 | 请求 | `data` 结果 |
|---|---|---|
| `GET /capabilities` | 无；须认证 | 版本、限制、transport/adapter flag 和真实发布关卡 |
| `GET /context` | 无 | 脱敏的 owner/profile 引用、时区、domain scope、permission revision；有控制权限的调用者还获得当前 `policy:{id,revision,etag}`；无宿主 token |
| `GET /overview` | `date=YYYY-MM-DD`, `timezone=<IANA>` | `as_of`、任务/提醒/审批/连接摘要、过期 native projection |
| `GET /operations` | cursor, limit, status，可选 object_ref | 有权读取的 operation 清单，包括不关联 task 的 pending/unknown connector sync |
| `GET /operations/{operation_id}` | 无 | 下文定义的操作回执 |
| `GET /receipts/{receipt_id}` | 无 | 第 10 节定义的脱敏 effect/delivery 证据 |
| `GET /snapshot` | 首次无；后续 `cursor` | 一致快照页及最后的 change cursor |
| `GET /changes` | `cursor`，可选 `limit` | 持久化变更和 next cursor；必填 cursor 来自 snapshot |

以下是**未来**能力响应示例；其中 true 表示通过关卡后的目标部署，不是当前仓库状态：

```json
{
  "schema_version":"personal.api.v1","request_id":"req_caps",
  "data":{
    "api_major":1,"plugin_id":"hermes-personal-agent",
    "contract_revision":"2026-11-06.design.1",
    "native_baseline":"90d6b98fd86d20981ee06ddd5b7d93e4320f26a4",
    "deployment_mode":"host_isolated","principal_adapter":"verified",
    "features":{
      "domain_reads":true,"domain_mutations":false,"controlled_writes":false,
      "change_polling":true,"domain_sse":false,"domain_websocket":false,
      "artifact_upload":false,"artifact_download":false,
      "canonical_session_attach":false,"native_mobile_sign_in":false
    },
    "limits":{"page_max":100,"json_body_bytes":262144,"upload_bytes":20971520},
    "release_gate":"blocked"
  },"operation_id":null,"error":null
}
```

`native_baseline` 记录兼容性证据，不声称运行中宿主与之匹配；若可以独立验证，另行暴露实际 runtime version。flag 根据已测试宿主模式、已配置授权和 adapter health 计算。客户端不得从登录成功或发现 endpoint 推断写入已启用。不暴露原始 host home 路径。

### 5.2 领域对象与命令

| 方法/路径 | 允许的命令字段/查询 | 额外 scope 与结果 |
|---|---|---|
| `GET, POST /projects` | GET: cursor, limit, status。POST: `name, goal, context_scope, source_refs?` | POST `personal.projects.write`；201 Project |
| `GET, PATCH /projects/{id}` | PATCH: `name?, goal?, status?` | PATCH 同 scope + If-Match；200 Project |
| `GET, POST /tasks` | GET: cursor, limit, project_id, status。POST: `project_id, outcome, acceptance[], constraints, source_refs?, artifact_ids?` | POST `personal.tasks.write`；201 Task，状态为 `captured`/`ready`，不自动 dispatch |
| `GET, PATCH /tasks/{id}` | PATCH: `outcome?, acceptance?, constraints?`；运行中的实质变化使相关 intent 失效 | PATCH 同 scope + If-Match；200 Task |
| `POST /tasks/{id}/start` | `reason?`；If-Match | 同 scope，加 action admission 检查；202 Operation 映射到原生 worker/Kanban |
| `POST /tasks/{id}/cancel` | `reason?`；If-Match | 同 scope；202 Operation，task 独立于业务状态记录 `cancel_requested` |
| `GET /tasks/{id}/attempts` | cursor, limit | Native ref、attempt 状态、result/receipt 引用和已知取消能力 |
| `GET, POST /commitments` | POST: `project_id?, content, promisor_ref, promisee_ref?, due_at?, timezone, source_refs[]` | POST `personal.commitments.write`；201 Commitment |
| `GET, PATCH /commitments/{id}` | PATCH: `content?, due_at?, timezone?, status?, evidence_refs?` | 同 scope + If-Match；200；fulfilled 需要证据或 owner 指令 |
| `GET, POST /automations` | POST: `goal, trigger, timezone, destination_ref, stop_condition, source_refs?` | POST `personal.automations.write`；202 Operation，再建立 Automation/native job 映射 |
| `GET, PATCH /automations/{id}` | PATCH: `goal?, trigger?, timezone?, destination_ref?, stop_condition?` | 同 scope + If-Match；202 Operation；外部授权变化须重新评估 |
| `POST /automations/{id}/pause`, `/resume`, `/cancel` | `reason?`；If-Match | 同 scope；202 Operation，原生确认后才进入最终状态 |
| `POST /action-intents` | 第 6 节的类型化操作 | `personal.actions.prepare`；201 Intent；仅准备 |
| `GET /action-intents/{id}` | 无 | 经授权脱敏的 intent、状态、approval/operation 引用 |
| `POST /action-intents/{id}/execute` | `intent_revision, payload_hash`；If-Match | `personal.actions.execute`；重验当前精确 grant/approval 和 policy；202 新 Operation 或 200 既有执行回执 |
| `GET /approvals`, `GET /approvals/{id}` | 列表：cursor, limit, status | 当前允许的审批投影；nonce 仅在有权读取的单项展示中提供 |
| `POST /approvals/{id}/decision` | 第 6 节的决定；If-Match | `personal.approvals.decide`；200 Decision，可附已接纳 operation ID |
| `POST /control/revoke` | `scope_type, target_ref, reason`；目标 policy 的 If-Match | `personal.control.revoke`；200 revocation revision 及受影响 operation 引用 |

资源公共字段：`id`、`schema_version`、`revision`、`created_at`、`updated_at`、有权读取的 owner/profile 引用和 `source_refs`。Project 另含 `name, goal, context_scope, status, native_refs`。Task 另含命令字段、业务 `status`、`execution_state`、`cancel_requested_at`、`native_refs`、`last_operation_id`、`acceptance_evidence_refs`。Commitment 另含命令字段和 `status`。Automation 另含 `status, native_refs, next_due_at, last_occurrence_ref, reconciliation_state`。Native ref 可空且由服务端写入；`stale_at` 区分缓存投影与当前读取。

复用 [04 的业务状态机](04-domain-data-and-memory-zh.md)。`cancel_requested` 是执行/控制条件，不是虚构的业务取消成功。Patch 不得赋值 `done`、`authorized`、`succeeded`、native run ID 或任意验收证据。任务完成依赖验收服务和证据，不依赖 worker 的终态消息。

`constraints` 是类型化对象：`deadline_at?`、`data_scope_refs[]`、`allowed_connector_ids[]`、`max_attempts`、`budget_ref?`。客户端值只能收窄已有授权，不能扩大。Automation 的 `trigger` 是 tagged union：`{kind:"once", at}` 或 `{kind:"cron", expression, dst_policy, misfire_policy}`。`destination_ref` 解析到已经验证的 route；不把任意 email/phone/chat ID 当作有权限的目的地。`stop_condition` 为 `{until_at?, max_occurrences?}`，v1 至少要求一个上限。时间解析/预览和原生语义通过 E4 验证，不由 HTTP 重写。

### 5.3 请求、操作与并发示例

```http
POST /api/plugins/hermes-personal-agent/v1/tasks
Content-Type: application/json
Idempotency-Key: d10152d8-1a2f-4ea1-802f-9bdd97245899

{"project_id":"proj_example","outcome":"准备每周回顾","acceptance":["包含未解决承诺和来源链接"],"constraints":{"data_scope_refs":["scope_project"],"allowed_connector_ids":[],"max_attempts":1},"source_refs":["src_owner_request"]}
```

```json
{
  "schema_version":"personal.api.v1","request_id":"req_create",
  "data":{"id":"task_example","revision":1,"status":"captured","execution_state":"not_started","native_refs":{},"last_operation_id":null},
  "operation_id":null,"error":null
}
```

该精简响应只展示所选字段；资源还包含公共字段和已验证提交字段。HTTP 状态为 201，附 `ETag: "task_example:1"`。启动任务是另一个 `POST /tasks/task_example/start`，使用新幂等键和 `If-Match: "task_example:1"`：

```json
{
  "schema_version":"personal.api.v1","request_id":"req_start",
  "data":{
    "id":"op_example","revision":1,"kind":"task.start","object_ref":"task_example",
    "status":"accepted","phase":"awaiting_native_admission",
    "created_at":"2026-11-06T10:00:00Z","updated_at":"2026-11-06T10:00:00Z",
    "native_refs":{},"effect_refs":[],"receipt_refs":[],
    "cancel_requested_at":null,"error_code":null,"retryable":false
  },"operation_id":"op_example","error":null
}
```

HTTP 202 包含 `Location: B/operations/op_example`，实际须展开 B 为真实基路径。Operation status 为 `accepted | running | waiting_user | succeeded | failed | cancel_requested | cancelled | unknown_outcome`。终态为 `succeeded`、`failed` 或 `cancelled`；`unknown_outcome` 仍未解决。本地 intent/approval 可以成功，而其独立 effect operation 仅被接纳。取消或丢失响应后重新读取状态。可重试性不能覆盖操作策略或未知 effect 的 reconcile 要求。

并发修改时，陈旧 ETag 返回 HTTP 412：

```json
{
  "schema_version":"personal.api.v1","request_id":"req_edit","data":null,"operation_id":null,
  "error":{"code":"revision_conflict","message":"任务已变化，请重新读取后再修改。","retryable":false,"recovery":{"kind":"reload_resource","object_ref":"task_example"}}
}
```

## 6. 操作准备、人工决定与撤权

### 6.1 类型化操作与 hash

`POST /action-intents` 准备一个已知操作 kind，而非任意 connector 参数：

```json
{
  "kind":"message.send","connector_id":"conn_example","account_ref":"acct_example",
  "target_ref":"recipient_verified","payload":{"draft_ref":"draft_example","draft_revision":4,"attachment_ids":["artifact_example"]},
  "source_refs":["src_owner_request"],"task_id":"task_example"
}
```

服务端解析不可变 recipient/account ID、精确内容、附件字节/hash、数据类别、交付方式、可见费用/限额和授权证据。对包含这些事实和 native adapter operation 的版本化 canonical action 计算不可变 `payload_hash`，而非只 hash 展示文本；可变资源 revision/status 不纳入此 action hash。记录 canonicalization version。Intent 响应包含 `id, revision, kind, status, payload_hash, policy_revision, grant_ref?, expires_at, approval_ref?, operation_id?, redacted_preview`。准备不发送，也不悄悄创建 standing grant。每种 kind 的 schema 使用 allow-list；未知 kind 返回 422。

`GET /approvals/{id}` 在权限检查后返回 `id, revision, intent_id, intent_revision, payload_hash, policy_revision, expires_at, allowed_decisions, presentation_nonce, preview`。`preview` 展示实际收件人/目的地、精确实质内容或可审阅 artifact revision、共享数据、附件、费用及相关后果。列表/事件不包含 nonce。展示 nonce 绑定该已验证 principal/auth context、profile、approval、当前 intent/hash/policy 和有效期；仅保存其 hash。多个设备可以分别生成展示，但决定事务只能结算审批一次，并使所有展示失效。

### 6.2 决定事务

```http
POST /api/plugins/hermes-personal-agent/v1/approvals/appr_example/decision
Content-Type: application/json
Idempotency-Key: 23c3543c-3893-43d9-b324-445f6d703c44
If-Match: "appr_example:2"

{"decision":"approve_once","intent_id":"intent_example","intent_revision":3,"payload_hash":"sha256:<64-hex-digest>","presentation_nonce":"<one-use-secret-from-current-presentation>"}
```

v1 仅允许 `approve_once` 和 `deny`，不提供批量批准、standing grant、`approved:true` 或 agent 生成的审批。仅有 nonce 不足以操作，还需要当前宿主鉴权和 owner policy。转发卡片、重放按钮、bot 回复或第三方表述不能作决定。

在一个事务中：解析当前身份/策略；验证 nonce/expiry/intent revision/hash；比较 approval revision；记录不可变人工决定；消费全部展示；更新 intent 和 audit/change 行；仅对已授权 effect 入队。成功 200 响应包含 `{approval_id, decision_id, decision, intent_id, intent_status, operation_id}`。`approve_once` 可返回 `intent_status:"authorized"` 及已接纳 operation，不暗示送达。相同幂等键的准确重试返回该决定回执，不再次入队；结算后使用不同 key 返回 409 `approval_already_settled`。

已有有效 grant 覆盖的 intent，prepare 仍不发送。显式执行命令为 `POST B/action-intents/{id}/execute`，要求 `personal.actions.execute`、Idempotency-Key、当前 intent If-Match 和 `{intent_revision, payload_hash}`。重新验证已确认 owner/profile、当前精确 grant 或先前审批、expiry、target/data/cost 限制、当前 policy 和已覆盖 connector write path。Scope 本身不是批准。审批尚未解决返回 409 `approval_required` 和有权读取的引用；denied/不兼容已结算 intent 返回 409，撤销授权返回 403，policy/identity 不可用返回 503。客户端不能提供 grant 或 dispatch permit。

Approval decision 的授权入队和该 execute 路由，在共享 admission service 中使用**同一个 intent execution slot**，固定以 `(owner_id, profile_id, intent_id)` 唯一标识。Slot 记录不可变 action hash；资源 `revision` 仅用于 If-Match/CAS 前置条件，不属于 slot 身份。状态转换可以增加 revision，但不能分配另一个 slot；实质操作变化必须创建新 intent ID。不同 HTTP command key 或两个入口竞态不能创建第二个逻辑 effect。对已分配 slot 的有权访问返回既有 operation；provider dispatch retry 保持该 effect 的稳定 key 并 reconcile 不确定性。每个 effect 仍需要当前 dispatch permit，任何入口都不能直接调用 raw tool 走捷径。

`deny` 将 intent 置为终态 `denied`，不创建 effect operation。超时/展示过期不是拒绝，也不产生授权。收件人/内容/附件/费用发生实质变化时创建新 intent，使旧审批失效并重新评估。被拒 intent 不能通过重试、换 connector 或重写 prompt 复活。新的明确 owner 指令加相关新授权可支持创建带 `supersedes_intent_id` 的新 intent；第三方内容不可以。

### 6.3 撤权与在途真实状态

`POST /control/revoke` 支持 `scope_type: "grant" | "channel_binding" | "all_domain_writes"`，带服务端解析的 `target_ref` 和当前 owner/profile policy ETag。有权调用者从 `GET B/context` 获取，例如 `policy:{id:"policy_example",revision:31,etag:"\"policy_example:31\""}`；将该精确值放入 If-Match，不能猜 revision。三个 revoke scope 都更新同一个 governing policy resource，并返回新 ID/revision/ETag。事务原子提交新 policy revision 并阻止新接纳。这里没有任何 endpoint 声称撤销宿主 device token；那是需要独立验证的宿主操作。

授权接纳和撤权按 [06](06-plugins-mcp-and-security-zh.md) 的数据库事务边界串行化。对外传输前，executor 重新检查当前策略并原子 claim effect dispatch permit。撤权先提交，就不能获得新 dispatch permit。permit 先提交但尚未传输时尝试取消，并如实记录状态。已传输/被远端接纳的工作可能无法撤回：标记 `cancel_requested` 或 `unknown_outcome`，reconcile 并报告远端回执。不得在网络 I/O 期间持有数据库事务，也不得承诺分布式原子的 revoke/send 边界。

每个 effect 都读取当前持久化策略，包括 frozen config worker 和调度执行。策略不可用则以 503 拒绝新 effect。不得通过所谓“fallback”原始 MCP/shell/browser dispatch 绕过拒绝。原生审批展示必须适配到精确 intent binding；若宿主无法安全关联，受控写入保持 blocked。现有基础版本的 hook/inventory 不是这套授权系统。

## 7. 复用原生会话传输，不建新 Chat Loop

### 7.1 Canonical WebSocket 集成

继续原生 CLI/TUI/Desktop/messaging 所有的会话时，使用已有、已认证的 `/api/ws`，并检测 **canonical** `hermes-gateway-v1` 协议能力 [H5, H6]。使用该 listener 由宿主记录的 credential/ticket 流程。不得把私有 bootstrap ticket 复制到远端客户端，也不把长期凭据放入生成 URL。

| 原生 canonical 方法 | 相关参数和含义 |
|---|---|
| `runtime.describe` | `{}` → instance/profile/authority epoch、capability、支持的会话创建字段 |
| `session.create` | `{request_id, source, ...supported_fields}` → 持久化稳定 session 身份；同一已认证 principal/profile 重复 request ID 复用它 |
| `session.resume` | `{session_id}` → 权威 snapshot 和当前 control 状态 |
| `prompt.submit` | `{session_id, submission_id, text}` → 持久化 admission receipt，不是推理完成 |
| `prompt.receipt` | `{session_id, admission_id, include_result?}` → 当前 admission 和保留结果 |
| `prompt.cancel` | `{session_id, admission_id}` → 取消排队输入或中断已开始输入 |
| `session.interrupt` | `{session_id, execution_generation}` → 绑定 generation 的控制 |
| `session.steer` | `{session_id, execution_generation, text}` → 修正回执；queued 不等于已消费 |
| `approval.respond` | `{session_id, execution_generation, prompt_id, choice}` → 仅处理原生待审批 |
| `clarify.respond` | `{session_id, execution_generation, prompt_id, answer}` → 原生澄清，不是另一个推理 turn |
| `session.events.since` | `{session_id, last_sequence?, last_seen?, replay_epoch?}` → replay 或需 snapshot 标记 |
| `prompt.resolve_unknown` | `{session_id, admission_id, execution_generation}` → 确认丢失执行，永不重放 |
| `session.mutate` | `{session_id, request_id, expected_revision, operation, payload, expected_generation?}` → 原生 revision-fenced mutation |

原生 admission status 为 `queued | started | unknown | terminal`，附 `admission_id`、`ref:{profile_id,session_id}`、`sequence`、`outcome`、`authority_epoch`、`execution_generation`。它不是 domain operation enum，须明确映射。Source/session-creation 字段是策略选择，不是身份凭据。只附加宿主授权的会话；任务关联不能扩大消息渠道所有权。

Canonical 和旧 TUI-sidecar 合同存在相同方法名但 payload 不同。生成/使用正确 canonical 类型，不假设所有旧 RPC 或 server request 都受 canonical listener 支持。若采用旧连接，先协商 `client.capabilities({server_requests:true})` 再声称处理 server request；未知方法应回应 JSON-RPC error，而不是默许。没有经过验证的 adapter binding，原生 `approval.respond` 不能替代 domain approval decision。

原生 replay event 包含 `type, session_id, payload, replay_epoch, seq`，以及可选 `authority_epoch, execution_generation, admission_id`。Replay 结果包含 `events, latest_seq, last_sequence, epoch, replay_epoch, truncated, snapshot_required, count`，可选 `open_requests`。Epoch 不匹配/截断时恢复 native snapshot 和当前待处理 control。Viewer 断开不代表 turn 被取消。对于已确认但响应丢失的输入，检查 durable receipt 前不要用新 submission ID 重提。

### 7.2 既有原生 HTTP API 是独立选项

原生 API server 已提供 `POST /v1/chat/completions`、`POST /v1/responses`、`POST /v1/runs`、`GET /v1/runs/{id}`、`GET /v1/runs/{id}/events`、`POST /v1/runs/{id}/stop`、`/steer`、`/approval`、`/clarify`、`/resolve-unknown` 和 `GET /v1/capabilities` [H7]。它要求路由到的 profile 的 `API_SERVER_KEY`，其鉴权和能力检测独立于 dashboard 插件路由。

**API 会话是自身独立的会话。** 对于 CLI/TUI/Desktop/ACP/messaging 所有的会话，这些推理路由返回 HTTP 409 `permission_denied`。继续这种对话应附加 canonical WebSocket，不要创建一个在同一 transcript 上启动第二 agent 的手机 REST wrapper。

原生 run 的 `Idempotency-Key` 有自己的合同：1–255 个可见 ASCII 字符；精确重试返回原 run、HTTP 202 和 `Idempotency-Replayed: true`；payload 变化返回 409；最后状态更新后保留 24 小时。这**不同于拟议 domain 保留期限**。原生 stop 先报告 `stopping`，实际退出才完成取消。Native run SSE 不是 domain change feed，也不是 artifact store。

## 8. 持久化领域变更与一致恢复

### 8.1 快照协议

可轮询 JSON 是必需的正确性路径。领域状态、revision、需要的 outbox 行和单调有序 change 行共同提交于同一个插件数据库事务。该 sequence 由 domain 拥有，不把原生 token-stream sequence 当领域 commit watermark。

`GET B/snapshot` 在单一已提交 watermark `S` 上物化授权后的领域投影，并包含 `snapshot_id`、`feed_generation`、`permission_revision` 和不可变分页视图。使用事务读取/物化快照，不是对实时表分别分页。每页含 `rows:[{resource_type, resource}]`、`next_cursor`、`expires_at`；仅最后一页返回严格从 `S` 之后开始的 `changes_cursor`。支持的行包括 projects、tasks、commitments、automations、pending approval 摘要、有权读取的 operation、connector 摘要和 artifact 元数据。纳入全部未解决 operation，尤其不关联 task 的 pending/unknown sync，以及最近 7 天更新的终态 operation。`GET /operations` 提供另行分页的授权恢复历史。重装或第二设备从服务端发现这些状态，不依赖本地记住的 operation ID。大型 source body/content 保持单独授权读取。

```json
{
  "schema_version":"personal.api.v1","request_id":"req_snapshot",
  "data":{
    "snapshot_id":"snap_example","feed_generation":"feed_example","watermark":817,
    "permission_revision":12,"expires_at":"2026-11-06T10:15:00Z",
    "rows":[{"resource_type":"task","resource":{"id":"task_example","revision":3,"status":"ready"}}],
    "next_cursor":null,"changes_cursor":"opaque-authenticated-cursor"
  },"operation_id":null,"error":null
}
```

示例资源行省略展示其他必需字段。初次加载时先在本地暂存所有页，再原子替换缓存；不能把部分替换快照展示为完整状态。快照超过上限返回 413 `snapshot_too_large`，要求明确设计更窄投影，不得静默截断。页过期返回 410 `snapshot_expired`，须从头开始。权限变化须在返回内容前使所有剩余页失效。

### 8.2 变更页与客户端算法

```json
{
  "schema_version":"personal.api.v1","request_id":"req_changes",
  "data":{
    "events":[{
      "schema_version":"personal.change.v1","event_id":"chg_example","sequence":818,
      "type":"task.updated","occurred_at":"2026-11-06T10:00:02Z",
      "resource":{"type":"task","id":"task_example","revision":4},
      "operation_id":"op_example","changed_fields":["execution_state"],"deleted":false
    }],
    "next_cursor":"opaque-next-cursor","has_more":false,"watermark":818,
    "permission_revision":12
  },"operation_id":null,"error":null
}
```

事件是**失效通知记录**，不是完整对象 payload 或推理 delta。首批事件词汇：`project.updated`、`task.updated`、`commitment.updated`、`automation.updated`、`approval.updated`、`operation.updated`、`connector.updated`、`artifact.updated`、`resource.deleted`。可选提示使用相同对象引用；不广播 approval nonce、消息、秘密 token 或无限制 connector payload。

1. 完成鉴权，检查 capability 和 permission revision，再取得完整 snapshot 及其 change cursor。
2. 从该 cursor 轮询 change；`has_more` 为 true 时继续读取有界页面。按 `event_id`/sequence 去重，不退回较低资源 revision。
3. 将收到的失效记录和 next cursor 一起提交到本地持久化存储。在当前访问权限下重读引用资源，新的对象或 tombstone 应用前保留待处理失效项。cursor 前进后发生 crash 也不能丢失必需的重读。
4. 重读可能得到比事件更新的 revision，应接受。404 从缓存移除对象，不区分已删除还是已失去权限。暂时失败保持显式 stale 状态。
5. 遇到 410 `cursor_expired`、`feed_generation_changed` 或 `snapshot_required`，清理/暂存替代投影并重新获取 snapshot。遇到 403 `permission_changed`，立即清除受影响缓存内容，仅在重新授权后恢复。遇到 401，停止轮询/mutation 并清除敏感内存状态。

Cursor 是由服务端认证的不透明值，绑定 owner/profile、principal binding、permission revision、feed generation 和最后已提交 sequence。客户端不能修改 scope 或降低 cursor 以取得无权读取的历史。已删除资源在保留的 change window 中留下最小 tombstone；落后超过窗口的客户端必须替换快照。Restore/migration 改变 feed lineage 时增加 `feed_generation`，不能在恢复后复用旧 cursor 权限。

离线缓存是设备本地展示数据，不是授权源。敏感 body/approval 默认只保存在内存；持久化缓存需要平台保护和明确注销清理。离线修改保留为草稿，不排队等待以后提交审批决定或自动对外发送。重连先重验 auth、policy、resource revision 和 receipt；未发送的低风险草稿随后才可使用原稳定 request key 提交。

### 8.3 可选实时加速

内部 `ctx.emit(event, payload)` bus 发布 `<plugin-id>:<event>`，返回已安排的 subscriber 数量。`broadcast_plugin_event(plugin_id, event, payload)` 通过实时进程内 client stream 发出 `plugin.<id>.<event>`。二者都不是持久化 feed 或送达确认 [H8, H9]。

只有独立测试通过后才可声明 `GET B/events/stream`（SSE）或 `B/events/ws`（WebSocket）。它们仅携带脱敏的“有新变更”提示，不携带特权命令 frame，并使用现有宿主 auth/Origin 边界；不替代 `/changes`，不要求新 token issuer，也不能保留无界 buffer。在 host-isolated 模式、OAuth plugin-socket 受限模式或 principal/lifecycle 测试失败时，声明 false 并轮询。宿主可能缺少通用有 scope 的实时投递接缝；应记录为 blocker，而不是导入私有 broadcast 内部函数。

## 9. Artifact 与真实原生文件边界

### 9.1 现有能力与限制

Hermes 原生 API server 支持 inline image，但**不支持上传文档/file ID**。旧 `/v1/artifacts/*` browser-controller 路由已移除，二者都不是通用 artifact registry [H7]。

宿主 Webapp 的 `POST /api/chat/file-upload` 接受 multipart `file` 和通过宿主边界选定的可选 profile。它在解析后的 profile uploads 目录中暂存唯一 0600 文件，返回 `{ok, path, size, staged_upload?}`，供已有 `file.attach` 流程使用。调用者不选择服务端路径，已删除 profile 不被重新创建。`POST /api/chat/image-upload` 是独立原生图片路径。这些路由受 surface gate 控制，不能假设每个 listener 都可用 [H10]。

原生 `POST /api/files/ticket` 为既有 download/stream 路径产生绑定 route/resource 的 ticket。在该 pin 中，download ticket 有效 60 秒，最多允许三次 GET/HEAD；stream ticket 有效一小时。它们是进程内状态，具有依凭据而异的注销语义，不是永久 file ID，也不保证统一撤销 [H11]。

### 9.2 拟议不透明 artifact adapter

所有 artifact 路由在 native storage/attachment/read 边界通过测试前保持禁用。插件 artifact ID 是**新的插件自有元数据**，不是虚构的原生 `artifactfileID` 能力。拟议元数据：

```json
{
  "id":"artifact_example","schema_version":"personal.artifact.v1","revision":1,
  "filename":"weekly-review.pdf","mime_type":"application/pdf","size_bytes":14201,
  "sha256":"<64-hex-digest>","status":"ready","classification":"private",
  "task_id":"task_example","source_refs":["src_example"],
  "created_at":"2026-11-06T10:00:00Z","expires_at":"2026-12-06T10:00:00Z",
  "download_supported":true
}
```

Storage locator、profile home、staging descriptor 和 native path 留在服务端。客户端文件名只是展示标签，不是路径。验证 MIME、接收时限制大小、完成时验证 checksum；未知 active content 按附件下载，不在已认证 App origin 内渲染。阻止 traversal/symlink escape、跨 profile 引用、credential-file 访问、解压炸弹和已删除 profile 复活。保留清理遵循 task/reference policy 和隐私删除，不把宿主 staging 伪装成持久存储。

| 拟议路由 | 合同 |
|---|---|
| `POST B/artifact-uploads` | `filename, mime_type, size_bytes, sha256, task_id?`；`personal.artifacts.write`；201 `{upload_id, revision, expires_at}` |
| `PUT B/artifact-uploads/{id}/content` | 已认证 octet stream、声明长度、upload ETag 和相同 content digest；一次完整文件；仅有界 staging；重复相同内容幂等 |
| `POST B/artifact-uploads/{id}/complete` | Idempotency-Key + If-Match；验证 bytes/hash 和 scope；201 Artifact 或 422；部分文件不能 ready |
| `GET B/artifacts/{id}` | 仅返回当前有权读取的元数据 |
| `POST B/artifacts/{id}/download-ticket` | Idempotency-Key + If-Match；当前读取权限；200 `{url, expires_at, method:"GET"}`，对应已测试原生 resource ticket |

v1 不宣称支持断点续传。失败/过期 upload 先 reconcile，再使用新 upload 身份重启。Content PUT 是 POST/PATCH 幂等键规则的例外：身份为服务端签发的 upload ID 加不可变 expected content hash；冲突字节返回 409。最终化必须原子 claim 该 owner/profile 的 staged file，仅保存已验证 storage reference，并创建 metadata/change 行。扫描或存储失败时保持 quarantined/failed upload，不成为 agent 可读 artifact。

返回 download URL 必须是已验证 deployment/native route 和短期 resource ticket，不是长期 session token 或任意远端 URL。Ticket 响应重放不延长有效期；过期后客户端用新 key 请求新 ticket。若某宿主模式的 native ticket route 无法安全服务 scoped artifact，`artifact_download` 保持 false，不用宽泛文件系统代理填补缺口。

## 10. 连接器与插件合同

### 10.1 能力描述与原生凭据

```json
{
  "schema_version":"personal.connector.v1","connector_id":"conn_example",
  "plugin_id":"reviewed-connector","plugin_version":"1.0.0","source_revision":"<reviewed-commit>",
  "account_ref":"acct_example","status":"read_only","auth_health":"connected",
  "operations":[{
    "kind":"message.send","input_schema":"personal.message-send.v1",
    "output_schema":"personal.effect-result.v1","mode":"write",
    "required_scopes":["provider.message.send"],"data_classes":["message_body","contact"],
    "destinations":["verified-provider-host"],"approval_policy":"exact_intent",
    "idempotency":{"mode":"native_key","retention_seconds":86400},
    "reconcile":{"supported":true,"by":"client_reference"},
    "cancel":{"supported":false,"phase":"none"},
    "receipt_level":"accepted","cost":{"currency":"USD","upper_bound":"0.00"}
  }],
  "sync":{"polling":true,"webhook":false,"cursor_schema":"provider-cursor.v1"},
  "limits":{"batch_max":1,"concurrency":1},"write_release_gate":"blocked"
}
```

以上数值是示例，不是对真实厂商的声明。`status` 为 `disconnected | read_only | controlled_write | degraded`；`auth_health` 为 `connected | expired | revoked | unavailable | unknown`。逐操作描述能力；账户可读不证明有写权限。`idempotency.mode` 为 `native_key | reconciliation_only | none`，记录真实 provider retention，不是拟议 domain retention。源/工具声称只读，在语义和替代路径测试通过前只是不可信元数据。

使用 Hermes 已有 MCP trust/tool filter、插件 enablement 和原生 OAuth grant。Plugin OAuth declaration 已支持指定 scope/HTTPS host，并通过 `credentialed_provider_request` 使用宿主拥有的 token 存储/refresh；声明变化可能要求重新登录。不新增 vault，不把 token 复制到 domain state，也不启动秘密 refresh daemon [H12]。固定版本的 plugin OAuth CLI 登录拒绝由 gateway/cron/agent 发起，所以手机连接设置需要受支持的宿主 handoff，而非伪造 OAuth URL 路由。连接同意和持久访问范围扩大仍须满足适用授权。

### 10.2 类型化内部连接器接口

以下是**拟议插件内部协议**，不是原生 `ctx` 方法，也不是通用公共 RPC：

```text
describe(context) -> ConnectorDescriptor
health(context) -> ConnectorHealth
read(context, ReadCommand, cursor?) -> ReadPage
prepare(context, TypedAction, operation_id) -> PreparedEffect
execute(context, prepared_effect_id, dispatch_permit, effect_key) -> EffectResult
reconcile(context, effect_ref, last_receipt?) -> EffectResult
cancel(context, effect_ref, reason) -> CancelResult
```

`context` 由服务端拥有：owner/profile/principal binding、account binding、当前 policy、data scope、deadline、budget admission、request/operation ID。Dispatch permit 是不透明的内部单 effect 授权记录，不是暴露给客户端/模型的 bearer token。Connector 不能扩大操作、账户、目的地、数据、费用上限或截止时间。

`prepare` 验证精确 provider 语义并返回 `prepared_effect_id, action_kind, canonical_payload_hash, resolved_target_refs, account_ref, required_scopes, cost_upper_bound, currency, expires_at, idempotency_capability, reconciliation_capability, cancellation_capability`。准备对外必须只读。若厂商的 prepare 自身会写入/预留/支付，应先将其建模为独立受控 effect 再调用。不持久化 access token 或多余 provider payload。

`execute` 验证 prepared hash/version 和当前 permit，然后用稳定 `effect_key` 发送至多一次已接纳 effect attempt。不确定的重复调用不能生成新的 provider idempotency key。Provider 缺少安全 key/reconciliation 时，标记 `unknown_outcome` 并等待已验证证据或 owner 决定，不盲重试、不换 connector。首期关闭 batch（`batch_max:1`）；后续 batch 要求每项独立 intent/permit/key/receipt 和明确 partial-result 语义。

### 10.3 结果、对账与取消

```json
{
  "schema_version":"personal.effect-result.v1","effect_id":"effect_example",
  "operation_id":"op_example","attempt_id":"attempt_example",
  "status":"accepted","provider_ref":"opaque-provider-message-ref",
  "receipt":{"id":"receipt_example","level":"accepted","observed_at":"2026-11-06T10:01:00Z","evidence_ref":"evidence_redacted"},
  "retryable":false,"reconcile_after":"2026-11-06T10:01:30Z",
  "cancel_supported":false,"error":null
}
```

`EffectResult.status` 为 `succeeded | accepted | denied | failed | unknown_outcome | cancel_requested | cancelled`。`receipt.level` 为 `submitted | accepted | delivered | read | reconciled`；它们是证据标签，不是必然逐级推进的过程。Provider 接纳发送不证明 delivered/read。只有操作特定验收合同满足后才可 `succeeded`；provider/tool 自述不是证据。`reconciled` 记录如何解决不确定性，并单独保留实际 outcome。

`CancelResult` 包含 `status: cancelled | requested | unsupported | already_terminal | unknown`、`effect_ref`、`observed_at`、`receipt_ref?`。`requested` 不直接映射到 domain `cancelled`。Reconciliation 只读，scope 限于相同 account/target/effect；不得重发、换账户、扩大搜索权限或重新打开 denied intent。存在多个可能远端匹配时，保持 unknown/needs-review，不猜测。

拟议 connector HTTP 读取为 `GET B/connectors`、`GET B/connectors/{id}`（当前有权读取的 descriptor 和 ETag，也是 `connector.updated` 的重读目标）及 `GET B/connectors/{id}/health`。`POST B/connectors/{id}/sync` 接受 `{scope_ref, cursor_ref?}`，要求 `personal.connectors.sync`、Idempotency-Key 和 connector If-Match，返回执行有界 read sync 的 202 Operation。这些路由不接受凭据、provider URL 或任意 tool 参数。Webhook ingestion 不在首期 HTTP 范围；后续 adapter 必须验证 provider signature/timestamp/replay identity，在推进 cursor 前去重，并把 payload 当证据而非 owner 授权。

## 11. 离线、故障与安全验收矩阵

以下是未来必需测试，**不是本次文档变更已运行的测试**。先使用 synthetic account 和 fake remote boundary；实机/真实 provider 认证是另一个经授权步骤。

| 场景 | 必需断言 |
|---|---|
| 创建 ACK 丢失、重复点击、双设备、进程 crash | 同 key/payload 只产生一个领域命令/effect；改变 payload 冲突；回执可查 |
| 同 owner 经不同 cookie/native credential 重试 | 一个 owner/profile command reservation；重验当前访问权限，保留原 actor 审计，不重复 effect |
| 有效先前 grant、execute/approval 竞态、approve → revision 增加 → execute 使用新 key | Prepare 不发送；执行重验当前 grant；固定 owner/profile/intent slot 在资源 revision/key 变化后仍返回同一 operation/effect |
| 读取 context policy ETag 后撤权 | 陈旧前置条件拒绝；新 context 提供权威 ETag；不猜 policy revision |
| 新设备/重装、无 task 的 pending sync、connector 变化 | Snapshot/operation list 发现未解决工作；connector 单项读取恢复 descriptor |
| Domain commit 与 native enqueue 之间 crash | 通过稳定 outbox/native correlation 对账，不盲目创建第二 worker/job |
| 远端接纳后、本地回执前 crash | 持久保留 unknown outcome；按精确 effect key 对账；不推测重发 |
| Domain/native 幂等窗口过期 | 对账或显式冲突；不宣称无限期 exactly-once |
| 陈旧 ETag 和旧 approval nonce/hash | 按情况返回 412/410/409 或拒绝；无副作用 |
| 转发审批、错误 owner/profile/issuer、bot 或群成员 | 不提升身份/源权限；其他对象保持隐藏 |
| 设备 A 已批准，设备 B 同时决定 | 一个已结算决定和 effect；其他展示失效 |
| Denied intent 改用其他工具/connector 提出 | 原 denied 为终态；替代原始路径不能执行 effect |
| 撤权先/后于 dispatch permit；远端已接纳 | 验证事务顺序和真实取消/unknown 状态，不承诺不可能的远端回滚 |
| Policy store 不可用；frozen worker config；safe worker 跳过插件 | 受控 effect fail closed；不退化为 prompt-only enforcement |
| 已认证同 profile 操作员、独立 profile、隔离 host IPC | 明示共享操作员信任；证明 profile 隔离和可信 principal 透传 |
| 无效 bearer 加有效 cookie；CSRF/CORS/Host/Origin 探测 | 无意外 fallback 或跨源 mutation；不泄露凭据 |
| 注销/设备撤权、待审批和 socket | 遵循真实 host revocation 语义；domain admission 持续拒绝；不虚构统一 token revocation |
| 原生手机 callback、App 被杀/后台、网络切换 | 每种宣称支持的设备展示受支持回调和安全凭据处理；否则 E6.7 blocked |
| Snapshot 并发写入、页过期、ACL 变化、删除和 restore | 无混合快照；cursor 在 watermark 之后；撤权缓存移除；generation reset 要求替换 |
| 提示重复/乱序、事件缺失、cursor 截断、重读时 crash | Cursor 前进后 pending invalidation 不丢失；轮询/快照恢复不执行命令 |
| 无 socket 的 host isolation 和 OAuth remote | 所有 read/change 流程通过有界 JSON polling 完成；不要求 SSE/WS |
| 超大文件、MIME/hash 不匹配、symlink/traversal、secret path、已删除 profile | 不产生 ready artifact 或文件泄露；不打开客户端控制的路径 |
| File ticket 过期、权限撤销、上传/下载中断 | 重新授权并取得新 scoped ticket；URL 不含长期 token，不使用宽泛 proxy |
| MCP 谎称只读、scope 扩大、grant 轮换/撤销 | 操作语义 gate 和 native consent 仍是权威 |
| Native prompt replay、重连、旧 generation、unknown admission | 同一个 owner runtime、durable receipt 和正确 native snapshot；不产生平行 API-server turn |
| 停止语音播放 / 停止 worker / 取消外部发送 | 三类状态独立；不得从音频停止推断外部取消 |

发布证据记录准确 plugin/native SHA、host mode、credential mode、profile 设置、transport、device/browser/OS、测试故障点和跳过情况。单元/schema/static check 不能单独证明部署鉴权、网络 containment、远端回执或手机行为。

补充基线证据：已有上游 `test_dashboard_auth_native_flow.py`（20）、`test_plugin_api_consent_gate.py`（7）、`test_plugin_host_route_auth.py`（4），通过官方逐文件 runner，在独立 PM Python 3.14.9 环境和隔离临时 HOME 下合计 31/31 通过。这些只覆盖上游 stub-auth、consent 和 IPC 回归；没有实现/测试本插件拟议 API，没有验证真实身份 provider 或手机，没有证明 IPC 中的可信领域身份，也不代表 E0.6 完成。

## 12. 工作包与精确依赖

| ID/标题 | 里程碑/状态 | 窄依赖 | 交付与发布关卡 |
|---|---|---|---|
| E0.6 Verify Client Transport Contracts | M0；Backlog | E0.1/E0.2；使用 E0.4 findings，但不宣称所有写路径已完成 | 固定版本 route/ctx/auth/RPC/isolation/file probe、host-principal adapter 决策、生成的 contract fixture；无私有/虚构 API |
| E6.5 Build Domain API and Change Feed | M2 可选；Backlog | E0.6；E1.1–E1.5；E2.1；E3.2/E3.5；E4.2–E4.4 | 类型化 REST/operation schema、事务 command dedup/outbox/change feed、授权一致快照、轮询插件总览；只启用逐个通过验证的 adapter |
| E6.6 Validate Client Recovery Flows | M3 可选；Backlog | E6.5；E6.2/E6.4；这些路径对应的 E8.1/E8.2 fault harness；artifact 测试需 E0.6 file evidence | 双设备/离线/replay/expiry/ACL/isolation/cancellation 测试集；复用 native session；不强制自建 push 或 live socket |
| E6.7 Validate Native Mobile Sign-in | M3 可选；Blocked | E0.6 auth findings；E1.1/E1.4/E1.5；E6.4；设备认证前先解除 callback 和 device-revocation 宿主合同阻塞 | 证明受支持 native callback、PKCE、安全凭据处理、真实撤权和实机恢复；否则 native mobile feature 保持 false |

E0.6 是独立的可选客户端分支，规划里程碑为 M0；它不阻塞渠道优先 M0/M1 纵切，后者适用的 E0 关卡为 E0.1–E0.5。E6.5 可以在 write adapter 通过前实现/测试 read projection，但不能靠宣布“API 完成”启用受控写入。E6.6 不等待整个 E8/M4，只要求列明的 observability/fault harness。E6.7 的发现工作可以早于 E6.5，也不得阻塞浏览器/渠道优先交付。M1 不依赖任何可选自建客户端工作包。

扩展现有 **E5.1**：operation descriptor、schema version、真实 idempotency/receipt/reconciliation/cancellation 限制和 health。扩展 **E5.2**：类型化 prepare/execute/reconcile/cancel adapter、一个 read 和一个 controlled-write synthetic vertical slice、逐 effect admission 及 partial/unknown-outcome 测试。不新增 E5 ID。Connector interface 设计可随 E0.6/E1.2 推进；启用写入仍要求 E1.3/E1.4、E4.3/E4.4 和该 connector 的 E0.4 路径覆盖。API 实现不等待未来所有 connector。

完成这份双语设计不会把任何实现 item 标为 Done。实现工作保持 Backlog；E6.7 因明确 host/device 缺口为 Blocked。同步计划前验证 Project issue/item ID；文档 ID 不是远端 Project item 已存在的证据。

## 13. 固定版本源码引用

- H1：[Dashboard 插件后端 API 文档](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/extending-the-dashboard.md)。
- H2：[插件挂载、运行时同意 gate 和 hosted response 行为](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server_dashboard.py)。
- H3：[宿主 auth 路由、WS ticket 和 native callback 校验](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/dashboard_auth/routes.py)。
- H4：[Dashboard middleware 与宿主 token 边界](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server.py)。
- H5：[Canonical 本地会话、操作员共享和登录生命周期](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/gateway-local-sessions.md)。
- H6：[Canonical session/replay 模型](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tui_gateway/contracts/canonical_sessions.py)和 [admission/control 模型](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tui_gateway/contracts/canonical.py)。
- H7：[既有 HTTP API、幂等、会话所有权和文件限制](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/user-guide/features/api-server.md)。
- H8：[公开 PluginContext 方法与内部 event bus](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins.py)和 [plugin broadcast helper](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_events.py)。
- H9：[Desktop 插件 REST/socket 合同与限制](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/desktop-plugin-sdk.md)。
- H10：[Webapp 文件上传](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/uploads.py)和 [staged-upload 所有权/布局](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/staged_uploads.py)。
- H11：[绑定资源的 file ticket 与生命周期](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server_file_tickets.py)。
- H12：[插件开发与原生 OAuth grant 合同](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md)。
- H13：[Hosted HTTP admission 只传鉴权布尔值，不传完整领域身份](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugin_host_http_auth.py)。
