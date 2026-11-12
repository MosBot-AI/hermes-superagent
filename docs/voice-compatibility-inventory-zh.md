# E0.8 语音兼容性清单

[English](voice-compatibility-inventory.md) | 简体中文

## 范围与复现

[Issue #36](https://github.com/MosBot-AI/hermes-superagent/issues/36) 核实可复用的原生语音契约。测试使用干净的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`，记录在 [compatibility.json](../compatibility.json)。项目提交 `ba614693e2a6b6ec4ad8bcbd4f395ac586021a27` 的基线在 Linux、Python 3.14.9 和已准备的 Hermes `dev` 与 `test` 环境下通过 4,843 项单元测试和分布于 88 个文件的 1,542 项原生契约测试。[开发检查](../README-zh.md#开发验证)会验证宿主版本和工作区干净状态，并记录环境指纹。[合并后主分支 CI](https://github.com/MosBot-AI/hermes-superagent/actions/runs/43246720356) 也已通过，[Issue 证据](https://github.com/MosBot-AI/hermes-superagent/issues/36#issuecomment-6827997518)记录了对应离线包的验证结果。

测试使用临时 profile、生成的 PCM 和文本、虚构的凭据标记、替身设备、内存 ASGI 消息，并阻止 turn 调度。SDP 交换替换了服务商 I/O。准入夹具允许探测 IPv6 回环地址是否可用，无需监听或建立连接。

模拟器使用独立的 `personal.voice.simulation-config.v1`、`personal.voice.simulation-frame.v1`、`personal.voice.simulation-capabilities.v1` 和 `personal.voice.self-test.v1` 版本。原生音频 WebSocket 测试协商 `hermes-gateway-v1`。Canonical `prompt.submit` 和 `prompt.receipt` 属于 [Hermes 网关 OpenRPC 版本 1](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/shared/src/gateway-contract.openrpc.json)。清单中的 Python 与原生 HTTP 契约按确切宿主 SHA 标识。[带日期的服务商协议对照](voice-provider-protocol-comparison-zh.md)单独记录外部协议版本和文档证据。

## 各模式的就绪状态

`已安装`标明测试环境中存在的包、provider 夹具或原生代码。`已配置`标明已验证的选择或策略。`凭据可解析`适用于所列凭据路径和测试范围。`已做健康检查`记录实际执行的检查。`已通过模式验收`要求满足相应运行模式的验收条件。目录可用性标志、流式能力标志和 GPT-Live 密钥解析结果分别提供不同证据。

| 模式 | 已安装 | 已配置 | 凭据可解析 | 已做健康检查 | 已通过模式验收 |
|---|---|---|---|---|---|
| 项目模拟器 CLI | 在进程内放置并加载插件。宿主隔离模式跳过 CLI 注册。 | 默认、`read_only` 和 `local_tasks` profile 使用固定模拟器。 | 不适用。 | 离线自检通过。 | 离线诊断不适用。 |
| 已注册的 ASR 与 TTS 文件处理 | 在 `in_process` 和 `host` 模式发现合成 provider。 | 显式选择夹具 provider。 | 不适用于夹具。 | 验证了夹具的可用性判断和分派。 | 无部署语音验收。 |
| 进程内已注册 ASR 与 TTS 流 | 发现合成流式 provider。 | 验证 ASR 显式开启流式与 TTS 显式选择。 | 不适用于夹具。 | 合成 PCM 和转写检查通过。 | 无部署语音验收。 |
| `host` 模式已注册 ASR 与 TTS 流 | 发现合成 provider。有类型 IPC 实验未安装。 | 验证合成流式配置选择。 | 不适用于夹具。 | 能力标志或解析通过。ASR 会话使用和 TTS 迭代失败。 | 已测插件 IPC 路径不支持。 |
| 内置本地或在线引擎 | 存在分派代码。实际引擎包、权重和服务商账户未验证。 | 模拟回退引擎选择。 | 跳过真实凭据解析。 | 替换了内置合成调用。未检查真实引擎。 | 无。 |
| 原生采集、转写交接、播放与 TUI 控制 | 原生代码、provider 夹具和替身设备。 | 临时 profile 和合成媒体。 | 不适用于夹具。 | 回调、WAV 与控制检查通过。跳过设备健康检查。 | 无。 |
| 原生音频 WebSocket | 原生应用、本地票据存储和合成 provider。 | 临时 profile 和本地音频授权。 | 核销合成本地票据。服务商凭据不适用。 | 检查内存 ASGI 交换。跳过监听器和设备健康检查。 | 无。 |
| Chained 客户端直连与中继配置 | 原生 HTTP 应用和语音配置解析器。 | 验证 `gateway`、`serve`、`dashboard`、`webapp` 和 profile 关闭直连。 | 直连路径解析虚构密钥。已测中继响应未下发密钥。 | 检查配置与本地准入。跳过服务商与中继媒体健康检查。 | 无。 |
| 原生 GPT-Live SDP | 原生 HTTP 应用和 SDP 请求构造器。 | `gpt-live` 和 `chained` 夹具模式。 | 解析虚构 profile 密钥。缺少密钥时拒绝。 | 检查本地状态和模拟交换。跳过服务商及 WebRTC 健康检查。 | 无。 |
| Canonical voice-live 准入 | 原生 authority、本地票据存储和临时会话数据库。 | 合成本地会话已附接，并阻止执行。 | 核销合成本地票据。服务商凭据不适用。 | 检查持久化排队准入与回读。 | 无 turn 执行或副作用验收。 |
| 统一适配器、可互换 VAD、第三方实时语音和可信远程语音 | 项目未集成这些运行模式。 | 已禁用或未实现。 | 跳过。 | 跳过。 | 无。 |

## 已测行为与剩余缺口

| 模式 | 已测、失败或跳过的结果 |
|---|---|
| 模拟器 | 生成的全零 PCM 验证帧处理、有界队列、重试、恢复和打断。原生 CLI 运行时无需任务存储、设备、provider 调用或原生提交。模拟器可停止自己的输出，原生工作打断返回 `unsupported`。[模拟器与 CLI 测试](20-voice-contract-simulator-zh.md#3-窄范围模拟契约) |
| 文件 ASR 与 TTS | 真实 `PluginManager` 发现流程验证 provider 类型、命名冲突和卸载。已注册 ASR 返回成功或错误 envelope。禁用、不可用或配置为未知 provider 时，ASR 拒绝且不自动回退。TTS 合成异常可跨越已测插件边界。即使 TTS 列表就绪检查为 false，文件分派仍可执行，配置的 provider 优先于单次调用参数。部分失败会清理暂存文件并保留已有目标文件。[Provider 契约测试](../tests/contracts/test_voice_provider_contracts.py) |
| 未知的文件 TTS provider | 配置未知名称可能触发 Edge 合成，结果仍报告该配置名称。Edge 不可用时可能触发本地 NeuTTS，两者均不可用时则失败。夹具替换引擎边界以阻止对外分派。未来限制引擎或数据接收方的模式必须先拒绝未知名称，再调用原生分派器。[文件分派](20-voice-contract-simulator-zh.md#当前固定版本的文件语音分发) |
| 插件流 | 进程内 ASR 消费 16 kHz 单声道 s16le PCM，原生 worker 将已测 32 kHz 输入转换为 16 kHz。TTS 以夹具声明的 22,050 Hz 返回单声道 s16le。测试验证禁用、未注册及不适合流式的选择被拒绝。在 `host` 模式，投影出的 ASR 对象无法支持必要的会话调用，投影出的 TTS generator 无法迭代。本地 ASR 取消可使 wrapper 返回结果，被阻塞的 provider finalize 仍可能完成。并发要求来自 ABC，未验收 provider 并行执行。[流式消费者](20-voice-contract-simulator-zh.md#当前固定版本的流式消费者) |
| 原生采集与播放 | 24 kHz 替身设备验证 RMS 静音端点、过短录音丢弃、过期 WAV 清理和播放泄漏检测。实时 ASR 成功返回非空转写时跳过文件 ASR 及其 hook。返回空转写或失败 envelope 时回退至已注册的文件 provider，回退 hook 收到 `source="voice_mode"`。转写辅助函数保留输入文件。按键通话调用方在成功或失败后都删除该文件。进程内替身播放器收到 PCM，隔离宿主的 TTS 可能以零帧 WAV 完成。实际已播放位置未测量。[采集与交接](20-voice-contract-simulator-zh.md#当前固定版本的原生捕获转写交接与语音准入) · [播放](20-voice-contract-simulator-zh.md#当前固定版本的播放与打断) |
| 原生打断 | TUI 播放打断停止共享媒体。生成打断还会通知 sidecar 夹具中的两个运行中会话。直接调用的 LOCAL 类型化停止辅助函数阻断目标采集的后续回调，TTS 停止仍为共享操作。上述语音用例未验证该辅助函数的传输层授权或运行中原生 turn 的确认取消。[语音控制测试](../tests/contracts/test_native_voice_control.py) |
| 原生 WebSocket | 本地票据路径通过内存中的原生应用准入 profile 作用域内的 STT 与 TTS。缺少或重放票据时拒绝，STT 还拒绝错误用途、外部 profile 选择和带 Origin 的本地握手。`host` 模式 TTS 返回 `fallback` 控制消息，未生成 PCM 或执行文件合成。跳过 `POST /api/audio/transcribe` 或 `POST /api/audio/speak` 文件中继，以及断开或停止的时序检查。[音频 ASGI 测试](../tests/contracts/test_native_voice_audio_asgi.py) |
| 直连、中继与 GPT-Live HTTP | 固定版本的 Desktop 客户端获取此配置。通过准入的直连配置响应返回对应 profile 的虚构密钥。已测 webapp 和关闭 `voice.client_direct` 的配置返回中继，响应不披露密钥。原生服务器解析流式 STT 的操作独立于中继凭据下发。无效票据和外部 profile 选择在配置解析之前被拒绝。GPT-Live 状态检查解析结果，无服务商调用。模拟的 `POST /v1/live/sessions` 带有票据 profile 的虚构 bearer、准确的 SDP、历史记录和客户端委派配置。空 offer 和缺少 profile 密钥在分派前被拒绝。模拟的上游错误验证转换至 HTTP `502`。[Desktop 客户端](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/apps/desktop/src/lib/voice-client-direct.ts) · [HTTP 配置与 SDP](20-voice-contract-simulator-zh.md#当前固定版本的原生-http-语音配置与-sdp) |
| Voice-live 准入与副作用 | 源于本地票据的连接将一项准入写入队列。第二个已附接连接以相同提交 ID 和载荷重放，并读到相同回执。语音上下文变更产生冲突。错误 surface、缺失附件、未附接和外部主体均被拒绝。跳过 Desktop 服务商事件去重、执行及下游副作用。准入回执标识原生工作，不携带副作用结果。[准入测试](../tests/contracts/test_native_voice_admission.py) · [E0.4 副作用边界](13-enforcement-contracts-zh.md) |

## 可复用契约与缺失的接入点

- 公开扩展点是 `ctx.register_transcription_provider` 和 `ctx.register_tts_provider`。ASR 契约覆盖文件转写及可选的单段语音流。一个输入线程向 `push_audio` 传入 16 kHz 单声道 s16le，`finalize` 返回标准结果 envelope 且不抛出异常。基础流契约没有取消方法。TTS `synthesize` 写入文件，失败时抛出异常。PCM 流式处理须显式开启并声明采样率，且须确保并发处理句子时的线程安全。`warm` 与 `release` 是尽力执行的生命周期方法。[注册方法](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/plugins_context.py#L865-L872) · [ASR ABC](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/transcription_provider.py) · [TTS ABC](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/agent/tts_provider.py)
- 原生音频路由和 canonical 网关 RPC 是已有的客户端契约，各自规定准入和帧处理方式。原生 `pre_transcription` hook 可调整文件转写的上下文。流式 wrapper、TTS 内部 `register` 装饰器、录音器、sidecar 停止辅助函数和 authority 实现属于宿主内部。固定版本没有公开的可互换 VAD 或通用语音会话注册器。隔离宿主的插件流需要受支持的跨进程媒体接入点。[仅供审阅的 IPC 实验](21-native-voice-ipc-experiment-zh.md)针对历史版本。原生 ASGI 夹具覆盖内置路由。通过隔离 dashboard 转发项目插件 WebSocket 或 SSE 仍未经验证，且处于禁用状态。[原生音频路由](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/hermes_cli/web_routers/audio.py) · [TTS 内部流式处理](https://github.com/NousResearch/hermes-agent/blob/2281116525106e3c109993ccb5dc74d02bfc1427/tools/tts_streaming.py) · [客户端传输限制](14-client-api-contracts-zh.md)
- 宿主认证布尔值、模型密钥或来源标题均无法证明 owner 身份。在取得适用的可信 owner 与会话、凭据与数据接收方批准、预算、媒体传输、实际播放及有明确作用域的取消证据前，项目保持真实语音禁用。原生 turn 取消与外部副作用取消各自需要独立控制和回执。未经授权，健康检查不得启动付费调用或发送音频样本。发布门禁按受影响的模式适用，可选项目 HTTP 与控制入口依赖 E0.6，授权或副作用所需的条件依赖 E0.4/E0.7/E1。[Owner 入口边界](18-owner-entry-and-read-authorization-zh.md) · [语音设计](19-unified-voice-provider-contracts-zh.md) · [路线图](08-roadmap-and-acceptance-zh.md)
