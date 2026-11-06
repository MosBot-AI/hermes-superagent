# 07. 手机与语音

[English](07-mobile-and-voice.md) | 简体中文

## 1. 入口路线

第一阶段优先复用 Hermes 官方 gateway 消息渠道，让手机能够开始/继续任务、查看状态、确认受控动作、收提醒和发送语音消息。桌面/CLI 仍然是同一 Hermes owner/profile 的入口，不为手机再启动一个独立 personal agent。

同时复用原生 web dashboard/desktop 的设置、会话、Projects、Kanban、cron、MCP 页面。新增的 personal overview 仅提供“今天、项目、承诺、待确认、提醒和连接健康”的聚合视图。只有现有入口的实际体验和权限模型不能满足需求时，才做额外手机 PWA/原生壳。

这不等于宣称官方已有完整 iOS/Android personal-agent App。当前源码有手机消息入口、web/desktop 和多种语音路径；响应式布局、通知、后台音频、认证和目标手机适配需实测。

## 2. 渠道能力矩阵

| 能力 | MVP 方案 | 必须验证 |
|---|---|---|
| 手机文字对话 | 选择一个官方支持渠道先交付 | owner ID、线程定位、乱序/重复、消息长度 |
| 任务和提醒 | 原生 gateway delivery + 领域引用 | 送达未知、离线恢复、跨 topic 路由 |
| 批准动作 | 原生可用 approval UI，领域绑定 exact intent | 按钮重放、过期、转发、身份不匹配 |
| 语音消息 | 原生 STT → Hermes turn → 可选 TTS | 中文、人名/时间误识别、文件大小和延迟 |
| 实时语音 | 后续复用已支持的 Hermes 语音路径 | 设备/浏览器兼容、barge-in、恢复与费用 |
| 手机概览 | 先用已有 web 入口，必要时插件 UI | 小屏/触摸、键盘遮挡、错误/空态与授权 |

选择具体主渠道要依据用户已使用服务与部署条件，不在文档中假定某一地区/账号一定能用。新增平台走官方 platform adapter/plugin 合约，不能绕过服务平台规则。

## 3. 连续性模型

`Owner → Verified Channel Binding → Hermes Profile → Session/Thread → Project/Task`。

Owner 可指定已有原生 Bot Mode Bot 作为主要协调者；它的 canonical Bot Chat 不会自动成为手机渠道的对话。默认连续性共享有权访问的领域任务/事实，而不是 transcript 或完整 prompt。通过 `profile_routes` 选择同一 profile，不会合并 Telegram/Discord/Desktop 会话。确实需要同一对话时，必须另行验证原生 attach/handoff 路径。拟议绑定与恢复合同见 [15](15-primary-bot-binding-zh.md)。

渠道切换不自动合并全量 transcript。通过显式任务引用和有界 handoff summary 接续；原会话和新会话保留自己的 route、参与者与权限。群聊中不能因为提到私人项目名就加载全部个人资料。手机里“那个任务”不明确时返回短候选，不猜测敏感目标。

消息包含 `client_message_id/platform_event_id`，请求去重；通知带稳定 task/automation 引用。弱网多次点击不多建任务、不重复批准、不重复发信。审批完成后其他设备及时显示已处理，并拒绝第二次执行。

## 4. 语音是交互层，不是权限捷径

原生 chained 路径是 STT → Hermes turn → TTS；源代码也描述 Desktop full-duplex voice front-end 委托 Hermes 完成工具工作。前端快响应模型不能拥有一套独立凭据或绕过主 agent 的 action gate。

每条语音保留来源和转写置信/可纠错信息，但默认不长期保存原始音频。金额、时间、收件人、姓名、删除和外发等关键字段误识别时，显示或读出结构化确认。普通查询无需机械重复确认；高风险动作不能只因语音模型听到“嗯”就自行扩大 scope。

正在说话时的“停”至少立即停止播放，并触发执行取消请求；**停止朗读不等于外部操作已经取消**。UI 显示 cancel requested 与 cancelled 的差别，若动作已提交则如实说明。

## 5. 凭据与音频路径

本基线官方 Desktop remote 可按配置从 gateway 取得 STT/TTS 设置和凭据，直接调用 provider；webapp 则通常 relay、密钥留在 host。两者不能混为同一安全性质。[原生语音说明](09-upstream-evidence-zh.md#h12-语音)

本项目手机 web 默认优先 host relay 或供应商支持的短时、最小权限会话凭据，不把长期 provider key 下发到浏览器。若采用现成 client-direct 路径，须明确设备信任、内存生命周期、传输保护与用户选择。麦克风、录音、后台播放和第三方音频处理都要遵守相应权限和隐私要求。

## 6. 安全暴露 web 入口

只使用 Hermes 已有认证/会话机制，经验证的 TLS/可信反向代理暴露；不能简单把 dashboard 绑定 `0.0.0.0` 后公开。验证 auth gate 真正启用、CSRF/CORS、session 过期、登出/撤权、附件访问和 webhook 认证。健康检查不能泄露配置与个人内容。

MVP 不要求自建推送基础设施。若平台不提供可靠送达，页面显示真实状态，不承诺秒级必达。移动 OS 后台限制、网络切换和浏览器 autoplay 是测试内容，不是 agent prompt 可以解决的问题。

## 7. 语音/手机验收场景

1. 桌面创建项目，手机查进度，读取的是同一领域对象。
2. 手机语音“明早九点提醒我”解析时区正确，可确认/修改/取消。
3. 断网重发同一消息和重复点击确认只产生一次动作。
4. 收件人或时间识别错，用户纠正后旧 intent 失效。
5. 播放中打断、工具执行中打断、离线后恢复均不假报取消成功。
6. 群里转发 owner 的旧批准、旁人说“继续”，均不能触发受限动作。
7. 音频处理失败回退文字入口，不阻断已有任务。
8. 登出或撤销设备后，旧 WebSocket/session 与待处理审批不能继续写入。

先用用户真实目标设备和主渠道验收，再承诺更广泛兼容。第一版手机语音消息闭环与后续实时语音分别立项，避免把“有 STT”写成“电话式实时助理已经完成”。
