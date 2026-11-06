# 可审阅的原生语音 IPC 实验

[English](README.md) | 简体中文

## 状态与范围

该 Hermes 本地测试分支解决一个具体兼容性缺口：固定上游基线中的原生语音消费者无法使用隔离插件返回的实时 ASR 会话或 TTS 迭代器。原型为这些现有消费路径加入有类型的管道桥接。它不是另一套 Agent、音频网关、新 provider 或可用的语音通话版本。

原型基于 Hermes `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`，位于分支 `prototype/typed-voice-streams`。原型源码与干净上游副本及本地身份原型分开，该源码未配置 Git remote。其补丁现收录于 Personal Agent 开发分支供审阅，并未集成运行时。下文的本地原型提交仅用于来源记录，不是已发布的提交链接。此目录仅收录经审阅的实验补丁，本轮打包未执行上游发布、部署、PR 或合并。Personal Agent 的正式兼容性固定版本保持不变。

## 已实现路径

- 现有 ASR 消费入口 `tools.transcription_streaming.open_streaming_session` 获得有类型的宿主 `TranscriptionStreamSession`，输入 PCM、观察部分文本并取得最终结果封装。
- 现有 TTS 消费入口 `tools.tts_streaming.resolve_streaming_provider` 获得配置指定的宿主 `TTSProvider`，通过现有 streamer 按需拉取 PCM。
- 专用 `voice_open`、`voice_op`、`voice_close` 及批量 `voice_release` 消息使用现有每 profile 插件宿主管道。桥接不引入新的监听器或传输方式。
- 只有已识别的 ASR/TTS ABC 及对应流方法能进入该路径。任意回调、标记、类型注解和其他返回对象不会因此获得通用远程对象接口。
- 消费者在完成、错误、取消、提前退出及达到原生字节上限时关闭支持的租约。没有 `close` 的既有进程内会话和迭代器仍受支持。

## 限额与生命周期

桥接限制每个宿主最多 32 个活动语音条目、每块最多 1 MiB、每条流累计音频最多 32 MiB，编码后的打开参数或每个接受的文本字段最多 64 KiB。这些是原型兼容性限制，不是生产音频 profile 的协商限制。

TTS 使用拉取式迭代，每次请求只推进一块，不提前展开整个迭代器。每条会话只允许一个在途操作。ASR finalize 为单次操作。无效输出、错误、关闭、provider 卸载和宿主 generation 变化会使相关句柄失效；旧流不会在重启的宿主中恢复。

超时或关闭后的操作仍可能在 provider 内执行。对应条目会继续占用容量，直至该调用及可选清理返回。清理保留 profile 上下文并单独运行，因此阻塞的 provider 清理不会卡住无关管道调用。关闭确认意味着逻辑隔离及已安排清理，不代表远端计算或计费已停止。清理确认采用独立的有限等待。垃圾回收释放为尽力而为，在后续宿主调用时发送，不保证即时清理。

## 验证含义

新增测试使用真实 `PluginManager` 发现、独立插件宿主 PID、现有管道及现有原生 ASR/TTS 消费者。Provider 引擎是确定性 fixture，不是真实语音服务。测试验证传输、结果、profile/provider 解析与生命周期，不验证识别准确率、可听播放或延迟。

历史最终选定测试入口为 `run-tests.sh`，准确结果及环境指纹保存在 [manifest.json](manifest.json)。本目录的可移植入口是下文说明的 `run_tests.py`。较早一次探索性运行还成功执行了两个现有 loopback WebSocket STT 测试，它们不属于最终聚焦管道的测试集。现有较大的 TTS 测试集因模块需要但环境没有 `numpy` 而跳过。两者均不计为完整语音认证。此前受限的九项身份 socket 测试未运行或重试。

后续经单独授权，使用同一 lock 新建含 NumPy 2.5.4 和 sounddevice 0.5.6 的隔离 PM 环境。此前跳过的 TTS 文件通过 44 项测试，无失败或跳过，包含其 loopback fixture；provider/设备行为仍被 mock。原有 88 包环境未改，新环境为 90 包，既有包版本均未变化。这解决了缺少 NumPy 的测试缺口，不意味着全部 164 个不同测试在新环境一起重跑。清单的 `numpy_tts_follow_up` 保留两套指纹和精确单文件范围。可移植的无监听器测试选择不变。

## 尚未满足的发布门槛

- 上游尚未采用此补丁，Personal Agent 插件也未包含它。正式固定版本测试仍正确描述原有 `Opaque` 返回边界。
- 原生 ASR 输入队列仍无界。桥接限制不能证明端到端缓冲、deadline 或内存有界。
- 通用 IPC 异常封装和线程分派未更改。每 profile 插件进程不能抵御恶意插件或同一 OS 用户访问，不是这种安全沙箱。
- 没有增加 owner 身份、登记、权限授权、主 Bot 绑定、私人读取、原生 turn、外部操作、provider 凭据、麦克风或设备权限。
- 未使用在线 provider、真实 ASR/TTS 引擎、音频硬件、实际通话或延迟/质量测试。当前验证不需要 API Key。
- 产品启用前需要采用受支持的宿主接缝，完成有界原生媒体准入/取消、身份/会话绑定及预算/隐私控制，再经授权的安全配置流程验证实际选定 provider 和设备。

本轮推进 E0.8/E7.5 的可行性证据，不代表完成任一工作包，也没有开始 E7.6/E7.7 的生产启用。

## 版本与结果

本地提交：`40889c64e1e2fbf194ec7ece73a63e7d84c52420`。13 文件选定测试集通过 120 项，无失败，有一个模块跳过；最后仅注释修改后，两个新增文件再次通过 17 项。全部 14 项上游静态检查通过。两处经过审阅的 catch-all 注释保留了错误封装和尽力关闭契约，没有增加 provider 数据日志。补丁已在干净基线上验证可应用，未修改该基线。

## 审阅与手动复现

完整七文件补丁为 [typed-voice-stream-prototype.patch](typed-voice-stream-prototype.patch)，SHA-256 为 `3e49d2993c9d1eadc7cf3c65e3f0ba0e63a750040f2ef757db7dd4a93330d2df`。源自上游的内容保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。清单列出所有打包文件与修改的上游文件。插件、打包过程和常规检查器不会安装或应用本目录内容。

仅使用另行准备的、位于精确基线的**一次性、无凭据** Hermes Git 副本。不要修改正式兼容性测试的干净副本、已安装的 Hermes、生产 profile 或本项目副本。基线与 Python 3.14 测试解释器应通过上游支持的方式单独准备，本入口不获取源码、不安装依赖。历史环境指纹用于记录来源，不证明当前环境与锁文件一致。

审阅补丁后，按本机位置设置绝对路径：

```bash
set -eu
ARTIFACT="/path/to/hermes-superagent/experiments/voice-ipc"
COPY="/path/to/disposable-hermes"
PYTHON="/path/to/prepared-test-venv/bin/python"
test "$(git -C "$COPY" rev-parse HEAD)" = 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
test -z "$(git -C "$COPY" status --porcelain)"
sha256sum "$ARTIFACT/typed-voice-stream-prototype.patch"
git -C "$COPY" apply --check "$ARTIFACT/typed-voice-stream-prototype.patch"
# 仅在此一次性副本中有意执行手动应用：
git -C "$COPY" apply --index "$ARTIFACT/typed-voice-stream-prototype.patch"
"$PYTHON" "$ARTIFACT/run_tests.py" --checkout "$COPY" --python "$PYTHON" \
  --disposable-copy --check-only
"$PYTHON" "$ARTIFACT/run_tests.py" --checkout "$COPY" --python "$PYTHON" \
  --disposable-copy
```

任一守卫命令失败就停止。应用前应将输出校验和与上文核对。不要在一次性副本中提交补丁：入口要求 HEAD 仍为精确基线、暂存差异与审阅补丁完全相同、没有未暂存的受跟踪修改、没有未忽略的未跟踪文件。`--check-only` 不执行上游 Python。守卫在比较差异前拒绝 assume-unchanged 和 skip-worktree 索引标志。它仅比较 Git 可见的受跟踪/暂存源码，不认证磁盘上的全部内容或被忽略内容。必须使用全新、可信的一次性源码副本和可信的已准备解释器，不能使用生产目录。该入口运行可信且经审阅的测试代码，并非安全沙箱。

可移植入口调用上游规定的 `bash scripts/run_tests.sh`，明确传入已准备好的 `HERMES_PYTHON`、临时 HOME/runtime 路径和不携带凭据的最小环境。在此精确基线上，入口会在 `pytest` 可导入时使用该解释器。`__HERMES_TESTS_REEXEC=1` 使环境检查失败时直接退出，不进入环境安装流程；明确的 runtime 路径阻止查找当前账号的共享工具目录。包装入口先检查 Python 3.14 和 `pytest`，不会以内部调度器代替规定的测试入口。

`portable_test_files` 选择 **12 个文件**，同时排除 `tests/tools/test_transcription_streaming.py`、`tests/tools/test_tts_streaming.py` 和全部身份 socket 测试。历史 TTS 模块因缺少 `numpy` 而跳过，但依赖齐全时可能创建 loopback WebSocket 监听器，因此必须排除出可移植测试范围。历史 13 文件、120 项通过与一个模块跳过仍仅作为历史证据，不是对不同选择的结果承诺。未经单独审阅，不应加入监听器测试。本轮打包未重新运行语音测试集。

项目常规检查器仍要求干净的正式固定版本及其 `Opaque` 兼容性边界。向 `scripts/check.py --hermes ...` 传入此补丁副本属于不匹配，其源码干净度守卫应拒绝。不要削弱正式测试，也不要用本实验替代正式兼容性结果。可审阅证据不等于原生集成或真实语音认证。
