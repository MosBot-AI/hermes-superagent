# 19. 统一语音会话与提供方契约

[English](19-unified-voice-provider-contracts.md) | 简体中文

**状态：生产方案，尚未启用。** [文档 20](20-voice-contract-simulator-zh.md) 中已实现窄范围离线模拟器和原生 provider 契约测试，它们不等于本文生产语音 API 已实现。 用户可通过统一的应用层接口，选择本地语音处理、已配置的在线语音 API，或受支持的实时语音到语音服务。本文定义的是由本插件拥有的新契约，不是 Hermes 已有的 `VoiceProvider` API。准备本设计时未使用麦克风、提供方账号、真实音频 API 或付费调用，也不意味着已通过真实设备的延迟或准确率认证。

本范围包括应用内实时语音对话和语音消息，不包括 PSTN 拨号器，也不代表获准呼叫第三方。Hermes 仍是个人 agent 和工具权限的权威。语音层不替代主 Bot、原生会话运行时、授权、worker 路由或凭据系统。这些边界见[文档 07](07-mobile-and-voice-zh.md)、[文档 14](14-client-api-contracts-zh.md)、[文档 15](15-primary-bot-binding-zh.md)与[文档 18](18-owner-entry-and-read-authorization-zh.md)。

独立的[仅供审阅宿主补丁](21-native-voice-ipc-experiment-zh.md)在一次性原型中验证了现有管道上的有类型流传输。插件未集成或启用它，下述正式固定版本的发现保持不变。

## 1. 决策：统一契约，明确能力

统一的是**会话生命周期、音频元数据、事件、取消、恢复、授权与用量计量**，不是各厂商的线上协议或质量宣称。三个 adapter 家族共享此契约：

| 家族 | 数据路径 | 必须明确的区别 |
|---|---|---|
| 使用本地组件的 `pipeline` | 麦克风 → 本地 VAD/ASR → 原生 Hermes turn → 本地 TTS → 扬声器 | 本地内置实现可能基于文件或完整话语，而非真正的增量流式处理 |
| 使用在线或混合组件的 `pipeline` | 麦克风 → 选定 ASR → Hermes → 选定 TTS | ASR 与 TTS 的数据接收方、区域、价格和故障模式可能不同 |
| `realtime_frontend` | 麦克风 ↔ 已配置的语音到语音服务；工作请求交给 Hermes | 前端与 Hermes 担任不同的模型角色；特定协议的委派与恢复需要明确的 adapter |

本文中，ASR 与 STT 指同一语音识别阶段。用户选择具名、经过测试的**语音 profile**，而不是提供一个任意 API URL 并期待它能在所有模式下工作。每个 profile 都指定 adapter/协议家族、模型及版本约束、组件、音色、传输、允许的数据目的地、凭据引用、限制与已获授权的回退顺序。选择 OpenAI 兼容的转写或 TTS 端点，并不证明它兼容 OpenAI Realtime、GPT-Live、Gemini Live 或其他实时协议。

安装不会改变当前的提供方、模型、凭据路径、麦克风权限或回退策略。设置界面展示哪些组件运行在设备、Hermes 宿主和外部服务上。启用在线 profile 需要用户许可的数据共享与支出范围。选定后端不可用或未知时，应明确显示失败；绝不静默选择另一家在线服务。

## 2. 已验证的原生基础与缺口

Hermes 源码基线为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。以下是经源码验证的事实，不是本插件的认证结果：

| 现有原生接口或路径 | 复用方式与限制 |
|---|---|
| `TranscriptionProvider`、`ctx.register_transcription_provider` [V1] | 文件转写，以及可选的单条话语流；流输入为 16 kHz 单声道 s16le PCM；最终结果采用 envelope，而不是通过方法抛出异常 |
| `TTSProvider`、`ctx.register_tts_provider` [V2] | 文件合成、可选的声明采样率的 PCM 流、预热与释放；流处理必须线程安全；失败约定与 ASR 不同 |
| `/api/audio/transcribe-stream` 与 `/api/audio/speak-stream` [V3] | 原生音频流有特定的帧和控制格式；不是任意插件 WebSocket，也不是统一的实时提供方注册表 |
| 本地 faster-whisper/本地命令，以及 NeuTTS/KittenTTS/Piper 路径 [V4] | 当前内置本地 ASR 回退到完整话语文件；所列本地 TTS 路径按句合成，而非保证分块 PCM |
| 原生麦克风端点检测/插话打断 [V4] | 已有 RMS/静音检测及感知播放状态的检测；未找到可公开替换的神经网络 `VADProvider` 注册器 |
| `voice.voice_chat_mode: gpt-live` [V5] | 特定的客户端委派协议：宿主交换 SDP，Desktop 持有 WebRTC，委派进入 Hermes，进度说明返回语音前端；不是通用实时 API 总线 |
| 原生串联的客户端直连与中继模式 [V6] | 某些 Desktop/serve/dashboard 路径可将长期提供方密钥返回到受信任客户端内存；`webapp` 入口强制中继；这些模式的安全属性不同 |
| 原生打断路径 [V7] | 停止播放与打断 agent 仅部分分离；一条 TUI 路径会打断所有运行中的会话。现有提供方 ABC 不保证阻塞式 finalize 可被取消 |

固定版本的合成宿主测试还证实：原生 ASR stream-session 对象及 TTS generator 不能跨 plugin-host IPC 成为可用流对象。仅有 streaming 标志为真并不足够。文件操作是单独通过的契约，见[文档 20](20-voice-contract-simulator-zh.md)。

下文新的 `VoiceSessionAdapter`、组件级 VAD 接口及统一控制均为**提议中的内部接口**。语义合适时，复用现有 ASR/TTS 注册器。不得遮蔽内置提供方名称，也不得将内部流式 `@register` 装饰器导入为公开插件 ABI。若支持新的实时后端需要通用的宿主语音会话扩展，应先结合这一具体使用方定义并测试该扩展接口，再启用它。

隔离运行的 dashboard 插件 HTTP 响应会被缓冲，不能假定它能承载 SSE/WebSocket/音频流，见[文档 14](14-client-api-contracts-zh.md)。优先使用已验证的原生音频/媒体传输与小型控制 adapter。缺少可信会话身份、profile 路由、流式传输或取消支持，是对应模式的发布阻断项；不得关闭隔离、创建并行的特权网关，也不得将 hosted 认证布尔值视为 owner 主体。

## 3. 组件、配置与协商

### 3.1 提议的语音 profile

```json
{
  "schema_version":"personal.voice.profile.v1",
  "id":"voice_local_example",
  "revision":1,
  "family":"pipeline",
  "adapter_id":"native_pipeline_bridge",
  "components":{"asr":"configured_local_asr","tts":"configured_local_tts","vad":"configured_local_vad"},
  "audio_network_policy":"local_audio_only",
  "transport_preference":["native_host_stream"],
  "turn_detection":"local_vad",
  "fallback_policy":{"automatic":false,"approved_profile_ids":[]},
  "limits":{"max_call_seconds":1800,"max_utterance_seconds":60,"input_buffer_ms":500,"output_buffer_ms":500},
  "retention":{"raw_audio":"ephemeral_tempfile","debug_capture":false}
}
```

这些限制是提议的默认值，不是原生实现或提供方的限制。实时 profile 选择明确的实时 adapter 与已配置模型，而不是一对 ASR/TTS 组件。可选的提供方专属配置采用命名空间、允许列表、版本管理及 schema 校验；未知字段会被拒绝，而非作为任意 API 参数转发。秘密与原始 URL 不属于客户端命令字段。服务端负责解析已审查的端点与凭据引用。

`local_audio_only` 表示语音处理不会把原始音频发送到外部 API；它**不**表示 Hermes 语言模型、工具或整个助手都离线。发送给云端 Hermes 模型的文本属于另一条需披露的数据路径。完全离线还要求 agent 和工具依赖也在本地。“本地”指选定的设备或宿主，不一定是手机：远程 Hermes 宿主上的 ASR 仍会通过该可信宿主连接传送麦克风音频。

安装本地模型或引擎仍须明确进行。分别记录代码与模型权重的许可证、来源与校验和、硬件及内存要求、启动和下载成本，以及已验证的语言支持。使用可信且受支持的软件包；不得假定模型许可证与其代码许可证相同。下载模型不是延迟或质量基准测试，写出插件名称也不证明它已安装。

### 3.2 能力通过协商确定，不靠推断

每个 adapter 提供带版本的描述信息，包含：家族/协议修订版；部署模式；输入输出编码、采样率与声道；流式/部分/最终转写支持；轮次检测控制方；取消；播放计量与对账；恢复与上下文还原行为；会话及截止时间限制；用量单位；凭据交付模式；支持的语言区域与音色 ID；以及已记录的隐私属性和数据接收方。

能力片段示例：

```json
{
  "schema_version":"personal.voice.capabilities.v1",
  "adapter_id":"example_realtime_adapter",
  "family":"realtime_frontend",
  "protocol_revision":"reviewed-adapter-revision",
  "transports":["provider_websocket"],
  "input_formats":[{"encoding":"pcm_s16le","sample_rate_hz":24000,"channels":1}],
  "output_formats":[{"encoding":"pcm_s16le","sample_rate_hz":24000,"channels":1}],
  "turn_detection":["provider_vad","manual"],
  "transcripts":{"input":"optional_partial_final","confidence":"unavailable"},
  "interruption":{"generation_cancel":true,"playback_reconciliation":"explicit_played_offset"},
  "recovery":{"provider_resume":false,"safe_context_restore":true},
  "usage_units":["input_audio_tokens","output_audio_tokens"],
  "credential_delivery":["host_only"],
  "verified":false
}
```

这仅用于说明，不是对任何具名厂商的宣称。只有当必需功能与经过测试的 adapter、宿主、设备能力存在可用交集时，才能打开会话。响应明确列出**已选定**的 profile 修订版、实际编解码器与采样率、协议、传输、VAD 控制方、语义请求提交方、限制、隐私范围及回退策略。不存在有效交集时返回 `voice_capability_unavailable`；不得猜测或暗中重新解释配置。

区分 `installed`、`configured`、`credential_resolvable`、`health_checked` 与 `certified_for_mode`。原生 GPT-Live 的 `available` 检查只判断密钥能否解析，并不判断账号、端点、模型或网络是否实际可用 [V5]。健康检查不得在未获授权时启动付费会话或传输样本音频；提供方目录的 `is_available()` 保持为本地、无网络调用的方法。

## 4. 提议的统一 Adapter 契约

本节所有名称都属于本项目的设计。Adapter 将失败归一化为类型化错误，同时保留原生提供方实际的失败与重试语义。不支持的可选方法返回 `unsupported`，不得模拟成功。

| 方法 | 契约 |
|---|---|
| `describe()` | 返回静态/本地能力元数据，不包含凭据，也不进行网络调用 |
| `open(trusted_context, negotiated_config, open_key)` | 预留预算，绑定一个原生对话并打开选定媒体路径；返回会话句柄及实际协商结果 |
| `append_audio(handle, frame)` | 为声明的流 epoch 接收有界音频输入；不暗中转换格式或提交转写文本 |
| `end_input(handle, utterance_id, end_reason)` | 按唯一的轮次控制方关闭一条话语；部分文本不会自动成为原生命令 |
| `submit_backend_output(handle, request_ref, output)` | 在当前生成代次下朗读或转发已获授权的 Hermes 输出；区分逐字 TTS 与模型改述 |
| `interrupt(handle, target, interrupt_id)` | 分别针对播放、提供方生成、原生 turn 或明确的领域 effect；逐项返回 requested/confirmed/unsupported/unknown |
| `ack_played(handle, output_ref, played_boundary)` | 在传输能够测量时记录设备实际播放进度，而非仅记录已接收字节 |
| `reconcile_interruption(handle, output_ref)` | 在支持时修复提供方对话状态；返回 exact/provider-managed/approximate/unsupported 结果 |
| `recover(handle, last_control_cursor, recovery_key)` | 重新授权并对账；恢复已验证的提供方状态，或基于安全上下文打开有明确标记的新媒体 epoch |
| `close(handle, reason, close_key)` | 幂等停止采集与媒体传输并释放租约；单独报告原生工作是否仍在运行 |

提议的 VAD 组件契约消费已声明格式的帧，输出语音活动与时间观测。它不能识别 owner、批准动作、提交原生 turn，或决定谁可以打断。ASR bridge 归一化原生 envelope 错误；TTS bridge 捕获原生合成异常并遵守并发约束。若原生流没有内部取消方法，停止交付会丢弃迟到的输出，但计算可能持续到截止时间。必须报告该成本与资源状态，不得将其标记为已取消。

一次实时通话绑定一个已验证的 owner/profile/原生会话，并在使用主 Bot 时绑定一个 Primary Bot 绑定 epoch。改变前台标签页或默认 profile 不能重定向该通话。多个查看者只能在获得宿主权限后旁观；只有一个采集/轮次控制租约拥有输入权。设备切换须先撤销旧租约并创建新的媒体 epoch，再接收新输入。未经验证的跨设备交接不可用。

## 5. 音频帧、流量控制与事件

### 5.1 媒体封装

对于本项目控制的字节流，使用明确的元数据：

```json
{
  "voice_call_id":"call_example",
  "stream_id":"mic_example",
  "stream_epoch":2,
  "utterance_id":"utterance_example",
  "sequence":41,
  "timestamp_us":820000,
  "sample_count":480,
  "format":{"encoding":"pcm_s16le","sample_rate_hz":24000,"channels":1},
  "payload_bytes":960
}
```

首选传输中的 payload 是二进制，不嵌入 JSON。时间戳相对于该流的单调时钟。解码前验证采样对齐、长度、采样率/声道、序号与最大帧大小。提议的 PCM 分帧目标为 20 ms，可在 10–60 ms 内协商，单帧上限为 64 KiB。WebRTC RTP/编解码协商由 WebRTC 栈处理；不得用此 JSON 格式包装 RTP，也不得通过无关数据通道发送 WebSocket 音频命令。

设备采样率、原生 ASR 的 16 kHz 格式与厂商专用格式之间，需要真正执行重采样。仅修改采样率标签会破坏音频与时间关系。转换过程中保留采样数与已播放偏移量的映射。原生 TTS 可能在首个音频块才给出输出采样率；不得假定所有提供方都输出 24 kHz。Opus 语音消息文件不是实时 PCM 通话帧。

按协商的时长与字节数限制输入/输出队列，设置高低水位、背压及取消优先级。网络停滞时不得构建无界队列。若输入丢失或溢出导致话语不完整，发出 `audio_gap`，结束或丢弃该不完整片段并请求重说；不得静默将它作为完整内容提交。输出被打断时清空待播音频，拒绝旧生成代次的迟到音频块。流式错误后，不得从头重播用户已部分听过的回答。

### 5.2 将持久控制与临时媒体分离

控制事件使用 `schema_version`、`voice_call_id`、`event_id`、单调递增的控制 `sequence`、`stream_epoch`、适用的 `utterance_id/request_id/output_id`、`native_admission_ref`、`occurred_at` 及类型化 payload。对完全相同的重试，在绑定的权限范围内按事件或命令身份去重。提供方 ID 仅用于关联，绝不作为 owner 身份。协商 schema 主版本，并拒绝未知命令字段。

事件家族为 `call.ready/state_changed/closed`、`capture.started/stopped`、`speech.started/ended`、`transcript.partial/final/corrected`、`request.proposed/admitted/settled`、`audio.started/chunk/ended`、`generation.finished`、`playback.progress/finished/stopped`、`interruption.requested/reconciled`、`usage.updated`、`recovery.required/restored` 与 `error`。`generation.finished` 不代表播放完成，两者也都不代表外部动作成功。

持久化最少量的通话/控制状态、原生准入引用、effect receipt 与预算记录。原始音频及音频块、部分字幕默认是临时数据，**不是**持久的领域变更事件流。[文档 14](14-client-api-contracts-zh.md)中的可选 API 可公开已授权的通话摘要或失效通知；重放该事件流不会重放麦克风音频。脱敏的控制重放在游标过期时可请求快照，但不能恢复旧 grant，或将未听到的音频虚构为已交付。

全双工需要相互独立的状态维度：连接（`opening/ready/recovering/closing/closed/failed`）、采集（`off/listening/muted`）、输入活动、提供方生成、原生 turn 与播放。监听、生成与播放可以重叠。不得依赖一个互斥的 listening/thinking/speaking 枚举保证正确性。

## 6. 轮次、Hermes 职责归属与动作安全

恰好一个经协商的控制方负责提交话语：本地 VAD、提供方 VAD，或按住说话/手动控制。额外的 VAD 可以观测指标或抑制回声，但不能独立提交。AEC、降噪、避免回声误触发的插话打断与短时预录缓冲，都是必须明确声明的组件能力，不是拥有 VAD 就隐含具备的优势。说话人分离或声纹相似性不是身份认证。静音必须停止采集与传输，而不只是停止 UI 电平显示。

每个请求恰好由一条语义提交路径负责：pipeline 使用最终 ASR 结果，实时模式使用已验证的前端委派。不得将同一话语的 ASR 转写和实时函数/委派事件分别准入。每个逻辑请求映射到一个稳定的原生准入 key 与 receipt，不随重连时提供方会话 ID 的变化而改变。部分转写仅更新字幕。最终文本的修正携带新修订版，并明确关联原请求；绝不静默重复已接受的动作。

在 `realtime_frontend` 中，在线模型可在获准范围内处理问候、澄清与对话表达。事实性工作、记忆、规划、工具及受控动作仍由 Hermes 负责。Adapter 只暴露受约束的后端委派 bridge；提供方工具调用是交给 Hermes 评估的**提案**。禁用会绕过此边界的提供方托管工具或直连服务凭据。没有经过验证的委派/提案 bridge 的提供方，不能宣称具备等价的个人 agent 实时能力。

前端只接收经同意的上下文，而不是完整 profile 或工具目录。原生会话归属与 owner 来源仍须按[文档 15](15-primary-bot-binding-zh.md)与[文档 18](18-owner-entry-and-read-authorization-zh.md)验证。来电者声称“我是 owner”、说话人匹配、转写文本或模型生成的工具参数，都不能补足身份缺口。语音不能把被阻断的可信上下文接口变成许可。

区分**语音前端模型**、**ASR/TTS 组件模型**、**原生 Hermes turn 模型**与 **worker 模型路由**。固定版本的串联实现可使用 `auxiliary.voice_chat`，而 GPT-Live 委派走另一条路径 [V8]。选定的实际生效模型与数据接收方必须可见并受策略约束；统一语音不得静默改变主模型/worker 模型，也不得宣称 E9 覆盖这些调用。

针对接收方、金额、日期、破坏性动作及信息披露，通过规划中的共享策略服务构造精确的类型化意图与确认预览。提供方不提供 ASR 置信度时，该值可缺省或为未知。语音到语音模型生成的转写文本，不保证精确代表音频模型实际推断出的内容。语音改述不是批准记录：在可信 UI 中保留精确的结构化细节，并使用受支持且经过验证的批准渠道。含糊语音、背景说话人、重放录音或随口的应答，都不能扩大授权。修正会使受影响的过期意图失效。

## 7. 打断、停止与结束通话的语义

| 用户或控制事件 | 必需行为 |
|---|---|
| 停止播放 / 插话打断 | 立即静音本地播放、清空输出队列、隔离旧输出生成代次，请求取消提供方生成，并对账实际已听到的内容 |
| 明确要求停止当前工作 | 还须通过受支持的控制路径，请求打断或取消**已绑定的原生 turn**；报告其 receipt/状态 |
| 明确要求取消外部动作 | 使用领域 effect 独立获授权的取消/对账契约；停止音频不等于回滚 |
| 麦克风静音 | 停止采集与传输；明确保留接收/播放的行为；不据此暗中取消已接受的任务 |
| 结束通话 | 关闭媒体并撤销采集租约；展示仍在运行的原生任务；不得宣称所有工作均已取消 |

配置允许时，插话打断策略也可请求取消已绑定的原生 turn，但绝不遍历无关会话。固定版本 TUI 更宽泛的打断行为是兼容性限制，不是目标契约 [V7]。无法安全地定向打断的 adapter，必须禁用该耦合动作，仅提供更窄的停止播放行为，而非宣称具备完整隔离。

分别追踪已生成、已传输与实际已播放的音频边界。支持时，将已播放边界回传给提供方，并截断或对账未听到的输出。实时服务各不相同：OpenAI WebSocket 使用显式播放计量与截断，而某些 WebRTC 路径由提供方管理；Gemini 没有相同的 OpenAI 式截断契约 [V9]。能力声明为 `exact`、`provider_managed`、`approximate` 或 `unsupported`。若无法安全地对账提供方状态，则丢弃该媒体上下文，以经过批准的安全摘要重新开始并明确标记，或回退到文本。

取消结果采用类型化值：`requested | confirmed | unsupported | already_terminal | unknown`，附带目标范围和观测时间。取消 ACK 不证明远程动作已撤销，也不证明提供方已停止计费。已取消生成代次的迟到音频、转写或工具提案，须丢弃或仅为对账保留；不能创建新的原生命令。

## 8. 恢复、回退与会话限制

应用层 `voice_call_id` 的生命周期跨越网络连接；提供方会话 ID 与媒体 epoch 可以改变。区分凭据过期、新会话启动截止时间、通话截止时间、提供方会话生命周期与恢复句柄过期时间。提供方 API 限制各不相同且可能变化；使用带 adapter 版本的协商值，而不是通用的“token TTL”。短期凭据可能允许多个会话或可覆写配置的会话，因此它本身不是动作或预算边界 [V10]。

断线时停止过时的播放、阻止新的语义提交、保留原生 receipt，并展示正在恢复或离线状态。在重连截止时间内，采用有界且带随机抖动的重试。恢复前重新验证凭据、owner/profile、绑定 epoch、grant、预算与目标。刷新 token 不会恢复已撤销的 grant。

若提供方具有经过测试的恢复支持，只使用其最新适用句柄与声明的可恢复规则。将句柄视为秘密会话材料。否则启动新的提供方会话并告知上下文不连续；仅恢复已获授权、已提交的上下文与实际播放边界。绝不盲目重放结果不确定的音频、旧工具请求或已接受的原生 turn。OpenAI Realtime、GPT-Live 与 Gemini Live 属于不同协议家族，不是可互换的重连策略 [V9, V10]。

对于被打断且尚未提交的话语，除非已证明能够精确恢复，否则应请求重说。若原生请求的 ACK 丢失，应先查询其稳定 receipt，再决定是否重新提交。浏览器消失后原生工作可能继续；重连时展示真实状态，而不是再启动一个 turn。

回退采用明确的允许列表策略，列出目的地、模式、数据类别、限制以及音色/模型变化。不得静默进行本地到云端或跨厂商的音频/上下文传输。获准采用按句/按文件回退时，保留选定提供方，不重放已部分听到的音频。话语中途或工作结果尚不确定时切换提供方，须先对账；新 profile 开启新的媒体 epoch。若缺少必需语义或权限，应安全停止，或降级为按住说话/文本，并解释实际限制。

在线故障、速率限制、未知引擎名称或缺少本地模型，都不得触发原生未知 TTS 名称路径，从而落入非预期的在线默认值 [V4]。统一选择器在调用原生 dispatcher 前验证精确的提供方身份。严格的本地音频策略应测试出站网络约束，而不只是检查提示词设置。

## 9. 隐私、凭据与部署

默认不长期保留原始音频，也不在运行日志中记录转写或音频内容。示例中的 `ephemeral_tempfile` 策略允许原生文件式 ASR/TTS 所需的有界临时媒体：使用私有且受访问控制的存储，规定处理截止时间，在完成或出错时删除，在启动时及崩溃后清理，并在平台支持时将其排除在备份之外。说明任何平台例外、用户保存的录音、原生转写及提供方保留策略。只有验证所有组件与回退路径都不写入持久存储，或使用经过明确验证且具备相应交换空间/崩溃保证的 RAM 存储路径后，才可协商严格的 `memory_only`；否则拒绝该要求或选择另一种实现。处理后删除磁盘文件不等于保证仅在内存中处理。提供方的数据使用方式随端点、账号层级、区域与恢复设置变化；不作通用的零保留或不用于训练承诺 [V11]。恢复云端会话可能比无状态 ASR 保留更多上下文。

激活在线模式前，披露谁会接收麦克风音频、转写、选定上下文、待合成文本与提供方元数据，以及接收目的、经验证的区域/保留信息和适用费用。复用有效的已批准范围，但接收方或数据类别发生实质变化，或共享范围扩大时，需要授权。后台采集与旁观者场景需要明确的 UX 和权限；绝不因安装插件就启用始终监听或唤醒词采集。

通过 Hermes 现有的 profile 范围秘密/认证机制解析长期密钥。保存不透明凭据引用，而不是新建凭据副本，也不把密钥放在项目 YAML/JSON、浏览器存储、URL、遥测或模型上下文中。默认使用宿主中继，或经过测试的提供方 bootstrap/临时凭据路径。TTL 与配置约束必须根据真实 API 核验，不得假定其只能使用一次或不可更改。Bootstrap 必须保留宿主认证、Origin/CSRF 检查、速率/预算准入及目标/profile 绑定。

原生受信任 Desktop 客户端直连模式可能将实际的长期密钥暴露到客户端内存；GPT-Live 的宿主 SDP 交换与 `webapp` 中继路径则不同 [V5, V6]。支持该旧模式需要明确选择受信任设备，并记录密钥生命周期与清理方式；它不是新移动端/浏览器 adapter 的默认模式。不得把所有通过浏览器提供的 Hermes 入口描述为天生无密钥。不得为执行本插件偏好，静默覆盖另一个 profile 已有的语音设置。

经审查的端点引用允许本地推理或在线服务，但不是任意 URL 代理。执行 URL 协议/主机策略、TLS 验证、重定向规则和凭据与源的绑定；阻断针对元数据服务/回环/私有网络的 SSRF，除非对应本地端点已被明确配置且经过验证。不得将凭据带到重定向后的其他源。保护 WebRTC 信令/ICE/TURN 数据与临时凭据；TURN/出口流量可能具有独立费用及网络隐私影响。常规日志不得包含凭据或完整 SDP。

远程宿主不能自行采集手机麦克风。采集与播放权限、设备选择由实际客户端负责，并按受支持的行为在关闭、进入后台或撤权时释放租约。验证浏览器自动播放、耳机/Bluetooth、移动端挂起、网络切换，以及代理/WebSocket/WebRTC 行为。不得仅凭桌面测试就承诺后台通话或手机支持。

## 10. 成本、遥测与质量门禁

按通话和 owner 设置准入前预算，涵盖 ASR、TTS、实时会话时长/音频 token、原生 Hermes turn、辅助调用、worker 调用，以及中继/TURN 费用。保留提供方原生用量单位及价格/配置修订版。估算费用、提供方报告费用与最终结算费用使用独立字段；未知用量不是零。本设计中的静态厂商价格或模型名称不构成购买承诺。

为通话、话语、输出、空闲时长，以及并发和调用速率设定上限。在付费 bootstrap 或生成前保守预留预算，再对账实际用量。必需预算耗尽或无法验证时，停止新的付费准入并请求关闭；无法避免的在途用量仍须可见。重试、回退或额外 reviewer 调用也会消耗预算。关闭本地 socket 不证明提供方已停止计费，尤其是在使用直连凭据时；应披露强制停止能力的限制，并在可用时使用提供方侧配额。

默认遥测是脱敏元数据：adapter/协议/模型修订版、宿主/设备模式、协商格式、各阶段耗时、队列深度、丢帧、VAD 事件、打断到本地静音的耗时、原生准入与结果引用、重连/不连续次数、回退原因及用量。不记录音频、转写内容、说话人生物特征、密钥、恢复句柄或完整提供方错误正文。需主动选择启用的诊断采集拥有独立、明确的保留与访问控制。

分别测量以下阶段的 p50/p95：采集/语音结束 → 最终 ASR、原生准入 → 首个模型输出、合成 → 首段可听播放，以及打断检测 → 本地静音。使用单调时钟，并明确对齐客户端/宿主时钟；不得将无关的墙上时钟直接相减。区分冷启动与预热后的延迟，并区分本地硬件、网络类别、语言与话语长度。初始调优目标为检测后本地静音 p95 不超过 100 ms，并在明确的测试预算内获得预热后的首段可听响应；两者在实测前均不是经过认证的承诺。

按适用情况评估中文 CER/WER，以及姓名/数字/时区/接收方槽位准确率、修正成功率、静音幻觉、回声/误打断、嘈杂环境与口音案例，以及任务结果。仅凭转写准确率，不能认证实时模型对意图的解释。以同一套已披露测试集比较各 adapter，同时保留其实际功能差异。不得宣传基于文件的本地引擎具有与原生流式处理相同的延迟，也不得把快速确认说成已完成的后端回答。

## 11. 错误与验收矩阵

将错误归一化为 `code`、`stage`、`scope`、`retryable`、`retry_after_ms?`、`provider_code?`、`outcome_known`，以及长度有界的脱敏消息。错误码包括 `voice_identity_unavailable`、`voice_capability_unavailable`、`voice_format_mismatch`、`voice_audio_gap`、`voice_budget_exceeded`、`voice_provider_unavailable`、`voice_cancel_unconfirmed`、`voice_resume_unsupported`、`voice_context_discontinuity`、`voice_epoch_conflict` 与 `voice_privacy_scope_required`。原生与远程失败详情保留在受保护的诊断中，不泄露秘密。可重试性绝不绕过授权或结果不确定的 effect 对账。

| 场景 | 必需断言 |
|---|---|
| 本地 pipeline、在线 pipeline、实时前端 | 生命周期与事件契约相同；如实报告能力和不支持的操作 |
| 未知提供方、缺少本地模型、严格本地策略 | 不静默回退到在线服务，也不发生非预期网络传输 |
| 采样率/声道/编解码器不匹配、奇数字节、过大或有缺口的帧 | 按协商拒绝或真正转换；内存有界；不准入不完整话语 |
| 本地与提供方 VAD 同时触发；部分/最终/修订转写 | 每个逻辑请求只有一个轮次控制方和一次语义提交 |
| ASR 与实时委派都看到同一话语 | 一个稳定的原生准入/receipt，不执行两次 |
| 播放/生成/工具工作期间插话打断 | 立即本地静音；限定范围的取消；如实报告外部 effect 状态；不打断无关会话 |
| 迟到音频、部分音频失败、不支持截断 | 隔离旧生成代次；不重播整个回答；声明对账或上下文不连续 |
| 阻塞式原生 finalize 或合成忽略取消 | 交付停止，但资源/用量在结算前仍未确认；不虚称取消成功 |
| ACK 丢失、网络切换、token 过期、恢复句柄过时 | 重新授权；恢复原生 receipt；不盲目重放音频或工具请求 |
| Hermes 工作时浏览器关闭或通话结束 | 独立关闭媒体；原生工作仍可查询且状态标记正确 |
| 通话中使用两个设备/标签页，或主 Bot 改变 | 采集租约与绑定 epoch 防止输入/输出被发往错误 profile |
| 口述金额/接收方修正、重放录音或旁观者批准 | 精确的当前意图与可信批准；不依靠声纹或仅凭转写赋予权限 |
| 在线接收方/区域变化、回退、数据保留选择 | 先获得必需的共享批准并落实预算，再传输；不静默扩大范围 |
| 宿主隔离、不支持的媒体路由、缺少 owner 来源证明 | 禁用受影响功能；不绕过私有 IPC/DB，也不使用默认 owner |
| 速率限制、预算耗尽、提供方会话仍未结束 | 停止新的准入，有界关闭/对账，准确表达成本不确定性 |
| 手机挂起、Bluetooth 回声、代理/TURN、重连风暴 | 测试平台特定的降级与资源清理；不作缺乏支持的通用宣称 |

先使用模拟传输/引擎与合成音频；记录精确的 adapter/原生 SHA、协议/API 版本、模型、宿主/客户端/OS、设备、语言、网络及受测模式。真实提供方探测可能产生费用或共享音频，须获得授权。物理设备与生产认证相互独立。现有的本地任务、授权、源码检查或文档检查，不能替代这些测试的完成。

## 12. 工作包与启用顺序

| ID | 状态与最小依赖 | 交付物 |
|---|---|---|
| E0.8 验证语音提供方契约 | M0；In progress（仅离线契约）；E0.1/E0.2；适用时采用 E0.4/E0.7 身份发现 | 固定版本的 ASR/TTS/原生音频/实时协议矩阵，凭据/取消/流式探测，公开 adapter 接口及不支持的模式 |
| E7.5 定义统一语音会话契约 | M2（M1 设计前期工作）；In progress（仅合成先导切片）；E0.8、E1.1/E1.2/E1.4/E1.5；只有可选 HTTP 门面依赖 E0.6 | 带版本的 profile/能力、音频/控制 schema、租约、作者/轮次归属、预算与隐私策略；合成参考 adapter |
| E7.6 实现本地与在线语音 Adapter | M3；Backlog；E7.5、E7.1/E7.2/E7.3；已启用动作需 E1.3 与相关 E0.4 覆盖 | 一个本地/混合 pipeline 及一个明确选定的在线实时 adapter，原生集成与能力专属控制；不宣称广泛的提供方等价性 |
| E7.7 验证全双工恢复与语音质量 | M3；Backlog；E7.6、E6.4、E8.1/E8.2 测试框架；关联任务/effect 恢复需 E3.5/E4.4 | 设备/延迟/准确率、插话打断、播放修复、重连、预算与隐私测试；记录各模式的发布门禁 |

扩展 E7.1–E7.4，而不是替换现有可用的语音消息计划：统一其 ASR/TTS 配置与安全语义，将语音消息 MVP 与实时全双工分开，并保留可选的实时模式验证。E9 仍负责 worker 模型路由；语音提供方不能静默选择该后端。绑定 Bot 的通话还需适用的 E0.7/E1.6/E3.6 门禁，但不能让每条语音消息都依赖可选的 Bot 登记。

本设计不阻塞本地任务收件箱，也不要求自定义移动 app。E0.8/E7.5 已有部分离线先导切片，但工作包和生产模式均未完成。E7.6/E7.7 仍为 Backlog。先实现经过能力协商的 pipeline，再增加一个经过验证的在线实时家族，之后仅在具备协议/隐私/成本证据时扩展 adapter。现在完成方案与接口文档；不得仅因设计获批，就启用麦克风采集、付费会话、新 grant 或运行时功能。

## 13. 证据与版本说明

- V1：[原生转写提供方与实时流契约](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/transcription_provider.py#L19-L66)及[公开注册器](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_registrars.py#L74-L84)。
- V2：[原生 TTS 提供方契约](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/tts_provider.py#L26-L106)及[流式提供方 bridge](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/tts_streaming.py)。
- V3：[原生音频 HTTP/WebSocket 路由](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/audio.py)及[流式 ASR 包装器](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/transcription_streaming.py)。
- V4：[本地 ASR](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/transcription_local.py)、[TTS 选择与回退](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/tts_tool.py)，以及[原生录音器/VAD](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/voice_mode.py)。
- V5：[GPT-Live 专属 bootstrap](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/voice_live.py)及[Desktop WebRTC/委派](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/apps/desktop/src/lib/voice-live.ts)。
- V6：[客户端直连凭据配置](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tools/voice_client_config.py)、[原生语音配置路由](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/audio.py#L152-L180)，以及[服务入口策略](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_server_surface.py#L50-L72)。
- V7：[原生停止/插话打断范围](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tui_gateway/methods_voice.py#L194-L323)及[gateway 流式交付](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/gateway/streaming_tts_consumer.py)。
- V8：[语音 turn 模型路由](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/voice_turn_route.py)。
- V9：[OpenAI Realtime 对话与打断](https://developers.openai.com/api/docs/guides/realtime-conversations)、[WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=realtime)，以及[Gemini Live 协议](https://ai.google.dev/api/live)。
- V10：[OpenAI client-secret 契约](https://developers.openai.com/api/reference/resources/realtime/subresources/client_secrets/methods/create)、[Gemini 临时 token](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens)，以及[Gemini 会话管理](https://ai.google.dev/gemini-api/docs/live-api/session-management)。
- V11：[OpenAI 数据控制](https://developers.openai.com/api/docs/guides/your-data)、[Gemini 零数据保留限制](https://ai.google.dev/gemini-api/docs/zdr)，以及[Gemini 条款](https://ai.google.dev/gemini-api/terms)。

在线文档核查日期为 2026-11-06。部分 Gemini 证据来自已索引的官方摘录，因为无法获取完整页面。这是文档研究，不是真实兼容性测试。部署前重新检查当前提供方/API/账号条款及 adapter fixture；不得把旧价格、token TTL 或模型可用性变成永久保证。
