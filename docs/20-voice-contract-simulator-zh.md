# 20. 离线语音契约模拟器

[English](20-voice-contract-simulator.md) | 简体中文

独立的[仅供审阅宿主补丁](21-native-voice-ipc-experiment-zh.md)在一次性原型中验证了现有管道上的有类型流传输。插件未集成或启用它，下述正式固定版本的发现保持不变。

## 1. 已实现范围

这是 E0.8/E7.5 的离线开发先导切片，不是可用的语音或通话。它实现严格的合成媒体配置、帧格式、有界队列和生命周期检查。[生产语音方案](19-unified-voice-provider-contracts-zh.md)仍需要可信身份、授权、预算、真实 provider adapter 与设备验证。

正式插件不为此功能注册语音 provider、麦克风、音频设备、HTTP 端点或模型工具。自检不读取个人任务，也不提交原生 turn。它只在内存中生成全零 PCM 字节，不使用音频文件、转写文本、账户或凭据。安装不会改变 Hermes 的语音/provider 设置，不需要 API Key。

## 2. 运行本地自检

在已测试的隔离 Hermes profile 中启用插件后执行：

```bash
hermes personal-agent voice self-test
```

固定宿主版本的原生 CLI 仅在 `in_process` 插件模式可用。Hermes 会跳过隔离宿主 CLI，不要为使用此命令关闭隔离。默认 `read_only` 和显式 `local_tasks` 模式均可运行诊断，不打开任务存储。

成功时返回单个 JSON 对象，包含 `schema_version: personal.voice.self-test.v1`、`status: ok`、`simulation: true`、有界 `checks` 列表、`live_voice_enabled: false`、`microphone_used: false`、`provider_calls: 0` 和 `native_turns_submitted: 0`。23 项固定检查分别报告布尔结果。报告失败时返回非零退出码。命令不接受 provider、端点、密钥、音频文件、麦克风或生产 profile 选项。

`personal-agent status` 单独标明已实现的合成检查及未开启的真实能力。通过自检只证明列出的模拟不变量，不证明识别准确率、真实播放、延迟、网络兼容性或生产授权。

## 3. 窄范围模拟契约

`personal_agent.voice` 提供 `SyntheticVoiceAdapter`、`simulation_config()` 和 `run_voice_self_test()`。其 schema 专门使用 `personal.voice.simulation-config.v1`、`personal.voice.simulation-frame.v1` 和 `personal.voice.simulation-capabilities.v1`，不是文档 19 中拟议生产 profile、音频或 provider API 的别名。

| 范围 | 已实现限制 |
|---|---|
| 配置 | 精确字段集合与类型；仅 `pcm_s16le`、16000 Hz、单声道，不含 turn detector |
| 帧 | 10–60 ms 的精确整数时长，声明采样数与 payload 长度必须一致；只接受全零字节 |
| 队列 | 每个方向按配置的帧容量限制，最多 500 ms；不足一帧的容量向下取整 |
| 顺序 | sequence 从零开始逐一递增，timestamp 必须符合精确帧时长 |
| 重复处理 | 仅保留最近一个已接收帧，识别完全相同的重试；拒绝冲突及更早重试 |
| 输入丢帧/溢出 | 清空输入并要求显式恢复，不把不完整输入标为已提交 |
| 输出丢帧/溢出 | 清空输出并推进 generation，阻止旧块重新进入 |
| 恢复 | 比较 expected epoch，丢弃旧夹具，推进 epoch/generation；仅识别紧邻上一次恢复的重试 |
| 打断 | 停止模拟输出、推进其 generation 并识别紧邻重试；输入独立；原生工作打断始终为 `unsupported` |
| 关闭 | 终态且幂等；清空夹具队列并拒绝之后的媒体和恢复 |

未知字段/版本、用 bool 冒充 int、不支持的采样率/声道、错误长度和非静音 payload 均被拒绝。不执行重采样或编解码转换，不能仅改采样率标签让帧变得有效。状态与诊断输出都有界，快照只含计数器和模拟标志，不含 payload 字节。

adapter 是单线程的。`append_input`/`append_output` 将夹具加入队列，`drain_fixture` 只丢弃它们，不代表设备播放确认、ASR 完成或原生准入。`recover` 创建新的模拟 epoch，不恢复 provider 状态。带版本的自检不是生产服务 API，也不是通用音频校验器。

## 4. 已核实的原生 Provider 边界

固定宿主：`90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。新增契约夹具通过真实 `PluginManager` 发现流程及公开 `ctx.register_transcription_provider` / `ctx.register_tts_provider` 加载合成 provider，其 availability 明确为 false。它们仅存在于临时测试 profile，不属于正式注册。

- ASR/TTS provider 对象在两种已测模式下保留预期 ABC 类型。文件操作结果可跨 plugin-host 管道；TTS `ValueError` 得以保留，ASR 则使用 success/error envelope。
- 可选 ASR stream 是单 utterance 对象。测试只证明合成夹具的单次使用行为，不声称宿主对任意 provider 都强制该行为。
- streaming 标志可以跨 IPC，但已测 ASR stream-session 对象在子进程到父进程的投影中没有可用的 `push_audio`/`finalize` 方法，TTS generator 也不可迭代。标志为真不代表隔离流式能力可用。
- 仅文件的 ABC 默认拒绝 streaming，不提供取消保证；查询未知能力时返回 false。
- 内置 provider 名称冲突被拒绝，unload 会清理对应作用域 provider，注册不改变 provider/model 配置。

这些结果不表示原生 Desktop 内置能力不能 streaming，也不表示所有隔离流式传输都不可行；它们说明的是已测试的插件返回对象边界。启用对应模式前，需实现受支持的 streaming bridge 或验证其他原生路径，不得通过关闭隔离或另建有特权的 gateway 绕过。

### 当前固定版本的文件语音分发

[文件分发契约](../tests/contracts/test_voice_provider_contracts.py)使用 Python 3.14.9，在干净的 Hermes 固定版本 `2281116525106e3c109993ccb5dc74d02bfc1427` 上运行。测试在 `in_process` 和 `host` 模式下通过真实 `PluginManager` 发现流程注册合成 provider，再调用原生文件入口。回退用例在内置 TTS 引擎边界替换就绪探测和合成。测试使用生成的媒体数据和临时 profile。确切运行结果记录在 [Issue #36](https://github.com/MosBot-AI/hermes-superagent/issues/36)。

| 原生路径 | 覆盖行为 |
| --- | --- |
| `tools.transcription_tools.transcribe_audio` | 已注册夹具的可用性探测返回 true 时，显式选择会调用该夹具。夹具收到本次调用指定的模型以及配置中的语言和提示。夹具不可用、STT 已关闭或显式选择的 provider 未注册时，调用返回失败，不会切换到自动探测的后端。 |
| `tools.tts_tool.text_to_speech_tool` | 调用传入不同的 `provider` 参数时，仍由配置中的 provider 决定分发。显式选择会调用已注册的夹具，即使其可用性探测返回 false。夹具收到配置中的音色、模型、语速和规范化的输出格式。如果 provider 写入部分内容后抛出异常，分发器会返回错误，清除暂存的部分输出，并保留目标路径上的已有文件。 |
| `tools.tts_tool.check_tts_requirements` | 工具列表的就绪检查对不可用的夹具及未注册的名称返回 false。两种情况下直接调用仍可能合成文件，因此列表的检查结果不足以判断直接调用的行为。 |
| 内置文件 TTS 回退 | 配置中未注册的名称可能选用 Edge 合成，成功响应仍报告配置中的名称。Edge 不可用时，分发器可以选用本地 NeuTTS，并报告 `neutts`。两者均不可用时返回错误。 |

如果切换引擎或向在线服务发送文本需要同意，文件 TTS 调用方须在分发前验证配置中的路由。响应报告的 provider 可能与实际运行的引擎不同。测试直接调用原生分发器，覆盖表中的文件路径。

### 当前固定版本的流式消费者

[流式契约](../tests/contracts/test_voice_provider_contracts.py)沿用文件契约的干净 Hermes 固定版本及临时 profile 环境。原生消费者在 `in_process` 和 `host` 模式下调用由真实插件管理器注册的合成 provider。夹具使用生成的 PCM 和文本。

| 原生路径 | 覆盖行为 |
| --- | --- |
| `tools.transcription_streaming.streaming_available` 和 `open_streaming_session` | 所选插件声明 `streaming_capable` 时，即使可用性检查返回 false，也能通过探测并打开会话。流式传输关闭、STT 关闭、provider 仅支持文件或 provider 缺失时，均不返回流。进程内传入 16 kHz 单声道 s16le 会产生夹具的部分转写和最终转写。后台 worker 也会将 32 kHz 输入重采样为 16 kHz，夹具收到预期的两两平均样本。在 `host` 模式下，消费者可以打开包装会话，但访问投影后的会话对象时会返回失败，转写为空。 |
| ASR 会话取消 | 进程内的合成 provider 阻塞在 `finalize` 时，取消会使包装会话返回取消结果。释放后 provider 仍能完成操作。在这一已测顺序中，包装会话会丢弃迟到的结果。 |
| `tools.tts_streaming.resolve_streaming_provider` | 就绪夹具以其声明的 22,050 Hz 单声道 s16le 速率解析。配置中的音色、模型和语速与 PCM 格式一同传给 provider。进程内消费者读到预期的音频块。在 `host` 模式下，调用到达 provider 子进程，但首次读取因投影后的生成器不可迭代而抛出异常。显式选择不可用、采样率无效、仅支持文件或缺失的流式 provider 时，解析器不返回流，也不会改用配置中的就绪 provider。 |

测试使用原生 ASR 包装会话和 TTS 解析器作为消费者入口。插件的注册方法仍是 provider 的公开扩展入口。声明支持流式传输、成功打开或成功解析，均不足以证明 `host` 模式中的音频可以消费。

### 当前固定版本的播放与打断

[扬声器契约](../tests/contracts/test_voice_provider_contracts.py)和[语音控制契约](../tests/contracts/test_native_voice_control.py)在干净的 Hermes 固定版本 `2281116525106e3c109993ccb5dc74d02bfc1427` 上使用合成 PCM、替身播放器及替身代理。扬声器契约走原生临时 WAV 路径，由替身播放器读取传入的文件。

| 原生路径 | 覆盖行为 |
| --- | --- |
| `tools.tts_tool_speaker.stream_tts_to_speaker` | 进程内，替身播放器收到预期的 3 帧 22,050 Hz 单声道 16 位 PCM。在 `host` 模式下，调用到达已注册 provider 后迭代失败，替身播放器仍收到格式有效但含零帧的 WAV。两条路径都删除临时 WAV 并设置管线完成事件。本用例中的失败停留在流式路径，没有调用文件合成。 |
| 合成期间的本地播放停止 | 停止标志不会释放处于阻塞中的合成 provider。测试释放 provider 后，播放器未收到迟到的 PCM。第二段已经开始读取队列，其 WAV 仍传给替身播放器，但包含零帧。 |
| TUI sidecar 全双工打断 | 播放阶段打断会停止流式及回退媒体，然后发出打断事件。生成阶段打断还会在停止媒体后，请求 sidecar 进程中两个运行中的代理中断。空闲代理未收到请求。 |
| TUI LOCAL 键入停止辅助函数 | 辅助函数修改目标 LOCAL 会话的语音模式。停止另一会话时，当前捕获回调仍可用。停止当前捕获所属会话后，迟到的回调会被拦截。两次停止均通过共享的 sidecar 函数请求停止 TTS。测试直接调用辅助函数。传输层授权与准入需另行取证。 |

即使播放器未收到任何 PCM，管线完成事件和播放器调用也可能发生。设备播放回执、provider 侧取消和已确认的原生轮次取消仍待完成。

### 当前固定版本的原生音频 WebSocket 准入

[音频 ASGI 契约](../tests/contracts/test_native_voice_audio_asgi.py)在干净的 Hermes 固定版本 `2281116525106e3c109993ccb5dc74d02bfc1427` 上，通过 `GatewayRuntimeAPI` 向原生 dashboard 应用发送合成帧。测试使用真实原生票据存储和两个临时 profile，通过该存储签发合成本地交互票据，并提供就绪的 runner 夹具。

| 原生路径 | 覆盖行为 |
| --- | --- |
| 本地 WebSocket 准入 | 新的交互票据打开流并协商 `hermes-gateway-v1`。缺失或已消费票据在任何新 provider 调用之前收到关闭码 `4401`。STT 路由还会拒绝用途不符的票据、指向其他 profile 的选择参数，以及带 Origin 的本地握手。合成 provider 的记录标识了票据所属的 profile 及其作用域内的配置。 |
| `/api/audio/transcribe-stream` | 已注册的进程内 STT 夹具收到提交的 16 kHz PCM 及配置中的提示。路由发送最终转写响应并关闭连接。 |
| `/api/audio/speak-stream` | 已注册的进程内 TTS 夹具收到文本及配置参数。路由声明 22,050 Hz 单声道输出，并发送预期的 PCM 块和结束消息。在 `host` 模式下，调用到达 provider，但投影后的流在首次读取时失败。路由发送 `fallback` 消息后关闭连接。这次交互未进行文件合成，也未输出 PCM。 |

测试通过内存 ASGI 消息验证应用边界。可信远程授权方签发票据、真实监听器、设备播放，以及在线 provider 或真实设备验收均需另行取证。

### 当前固定版本的原生 HTTP 语音配置与 SDP

[语音配置契约](../tests/contracts/test_native_voice_http_asgi.py)和 [GPT-Live 契约](../tests/contracts/test_native_voice_live_asgi.py)在干净的 Hermes 固定版本 `2281116525106e3c109993ccb5dc74d02bfc1427` 上，通过内存应用与原生 HTTP 票据准入验证行为。合成凭据用于区分启动 profile 和票据所属 profile。GPT-Live 的上游请求由替身记录。

| 原生路径 | 覆盖行为 |
| --- | --- |
| `GET /api/audio/voice-config` | 启用直连语音时，`gateway`、`dashboard` 和 `serve` 界面夹具返回票据所属 profile 的 STT 和 TTS 直连配置及其合成密钥。`webapp` 界面和关闭 `voice.client_direct` 的 profile 返回 relay 配置，响应不携带密钥。缺失、已消费或用途不符的票据收到 `401`，选择另一个已存在的 profile 收到 `403`。四类拒绝均发生在调用语音配置解析器之前。 |
| `GET /api/audio/voice-live/status` | 响应返回配置中的模式、模型和音色，以及 profile 凭据能否解析。已测状态响应不携带密钥，也不发起上游请求。 |
| `POST /api/audio/voice-live/session` | 在请求获准且凭据可解析时，已测的 `gpt-live` 和 `chained` 模式均可进入模拟交换。出站请求携带票据所属 profile 的合成 bearer、包含 CRLF 的原始 SDP、合成历史和客户端委派配置。空 offer 返回 `400`。票据所属 profile 缺少密钥时，即使启动 profile 有密钥也返回 `503`。这两类拒绝均未向替身发送请求。合成上游 `429` 会转换为 `502`，响应携带夹具的错误详情。 |

界面测试使用本地夹具票据验证响应策略。浏览器登录、部署环境中的凭据交付、可信远程身份、真实网络和 WebRTC 传输，以及真实设备和在线 provider 验收仍待完成。

### 当前固定版本的原生捕获、转写交接与语音准入

[捕获](../tests/contracts/test_native_voice_capture.py)、[转写交接](../tests/contracts/test_native_voice_transcription_handoff.py)和[语音准入](../tests/contracts/test_native_voice_admission.py)契约在临时 profile 中验证干净的 Hermes 固定版本 `2281116525106e3c109993ccb5dc74d02bfc1427`。录音测试为合成 PCM 提供输入流、时钟和最小数值夹具，保留原生 RMS 计算、录音回调和 WAV 写入。准入测试使用由已兑换的本地票据派生的夹具连接身份，并阻止轮次调度。

| 原生路径 | 覆盖行为 |
| --- | --- |
| `tools.voice_mode.AudioRecorder` 与播放打断检测器 | 持续的合成 PCM 后进入静音，会触发录音停止通知。调用停止后，以夹具的 24 kHz 设备采样率写出预期的单声道 16 位 WAV。短录音被丢弃，原生清理会删除过期的夹具 WAV。独立的检测器测试用合成 RMS 值验证播放起始宽限、播放漏音抑制和持续输入触发播放打断。 |
| `tools.voice_mode.transcribe_recording` 与按键通话清理 | 录音器将合成的流式终态对象与录制的 WAV 关联。流式结果成功且非空时直接返回，空结果或失败结果会转入已注册的合成文件 ASR。`pre_transcription` 钩子收到 `source="voice_mode"`，选定的语言传给 provider。直接调用的辅助函数把 WAV 留给调用方。原生按键通话包装器在文件转写成功或失败后均删除本次录音，并保留无关 WAV。 |
| 原生 `voice-live` 提示准入与回执 | 已附加的夹具会话将一条包含语音上下文的准入记录持久化并排队。通过第二条已附加连接用同一提交 ID 与内容重试时，会返回原排队回执，`prompt.receipt` 也返回同一记录。同一 ID 下更改语音上下文会冲突。授权层拒绝未附加连接的提交、同一 profile 下其他主体读取回执、错误界面提交语音提示，以及缺少暂存附件的请求。此夹具不会产生对话记录或执行轮次。 |

原生后端回执证明调用方提交 ID 的准入结果。Desktop provider 事件去重、真实音频设备行为、委派执行和下游副作用回执均需另行取证。

## 5. 测试与剩余门禁

仓库检查器运行离线单元测试、Ruff、ty、双语检查、原生 provider 契约，以及带网络防护的真实顶层 CLI 子进程。输入全部是生成的夹具，本切片不需要 socket listener、麦克风权限、真实音频、模型权重、账户或付费 API。

独立本地身份原型没有打包或导入，其未验证的 socket 相关测试仍受阻，本轮未重试。正式 [owner 边界](18-owner-entry-and-read-authorization-zh.md)、主 Bot 绑定和私人读取仍然关闭。

[E0.8 兼容性清单](voice-compatibility-inventory-zh.md)汇总确切固定版本的离线结果，并关联[提供方协议对照](voice-provider-protocol-comparison-zh.md)。E7.5 仍处于合成先导阶段。E7.6/E7.7 仍为 Backlog。

启用真实语音模式前，需要实现并验证该模式选定的 ASR/TTS 或 realtime bridge、身份/会话绑定、接收方与预算准入、可控输入/输出 lease、可信播放统计、原生 turn 取消及恢复。通过安全交接取得所需的 provider 凭据，并进行获准的设备和真实 provider 测试。
