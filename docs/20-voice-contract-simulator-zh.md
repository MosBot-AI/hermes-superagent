# 20. 离线语音契约模拟器

[English](20-voice-contract-simulator.md) | 简体中文

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

## 5. 测试与剩余门禁

仓库检查器运行离线单元测试、Ruff、ty、双语检查、原生 provider 契约，以及带网络防护的真实顶层 CLI 子进程。输入全部是生成的夹具，本切片不需要 socket listener、麦克风权限、真实音频、模型权重、账户或付费 API。

独立本地身份原型没有打包或导入，其未验证的 socket 相关测试仍受阻，本轮未重试。正式 [owner 边界](18-owner-entry-and-read-authorization-zh.md)、主 Bot 绑定和私人读取仍然关闭。

真实语音启用前，需要实现并验证所选 ASR/TTS 或 realtime bridge、身份/会话绑定、接收方与预算准入、可控输入/输出 lease、可信播放计数、原生 turn 取消及恢复。之后再通过安全交接取得所需的特定 provider 凭据，并进行获准的设备/真实 provider 测试。E0.8/E7.5 仅部分推进，E7.6/E7.7 仍为 Backlog，没有完成任何语音发布门禁。
