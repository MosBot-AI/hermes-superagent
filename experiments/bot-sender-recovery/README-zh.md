# 仅供评审的原生 Bot 发送端恢复方案

[English](README.md) | 简体中文

[Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) 跟踪基于 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 的候选方案。[补丁](bot-sender-recovery.patch)及[清单](manifest.json)用于一次性评审构建。已安装插件和官方兼容性固定版本使用未修改的宿主。来自上游的内容保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。

## 恢复路径

同一安装内已准入的 Bot 投递已有原投递 ID，以及读取接收方回执的等待进程。当 POSIX 发送端是已绑定且支持异步投递的本地 Gateway 会话时，候选方案让原等待进程写入原生进程输出日志。设置监视器后，原进程 ID、启动时间、父会话及通知路由会写入检查点。Gateway 同时承载多个 profile 时，仅拥有该日志输出目录的 profile 可以接管检查点条目。

后继进程读取同一等待进程的输出及记录的退出码。现有 Gateway 监视器和会话权威服务准入原进程的完成通知。本地会话无客户端连接时，将结果存为完成记录。接收方保留原 Bot 准入与回执。该方案无需再次发送 Bot 请求，也无需增加对话记录写入方或模型工具。

等待进程完成后，其通知路由和处理状态保存在现有进程结果中。启动时，宿主在原 profile 下恢复待通知结果，保留进程 ID、启动时间和父会话。准入已提交时，现有会话准入账本处理重放。显式读取完整输出会在同一结果中记录已消费状态，启动恢复会跳过该结果。

若针对进程结果的写入失败，只要原 profile 内的输出及尚未过期的退出记录仍在，原生检查点就保留原交接条目。后继进程读取同一输出，持久化结果后移除交接条目。结果路径不可写时，读取完整输出可以在保留的交接条目上记录已消费状态。已提交的准入通过同一原生完成身份对账。

计划重启时，Gateway 在成功排空后给本地回执等待进程最多一秒的共享时间，用于读取已准入投递的结果。该窗口受关闭看门狗的剩余预算约束。常规关闭清理仍会终止其余等待进程。结果和检查点写入使用等待进程启动或接管时记录的 profile，宿主级清理线程也遵循这一归属。

发送方检查点和进程结果保留准确的目标 profile、目标会话、准入 ID、投递 ID、profile 目录身份，以及原消息和作者的摘要。如果等待进程在输出前被终止，原生发送方监视器可以读取准确的回执，并与目标 profile 的本地终态准入和保留结果核对。监视器使用原进程完成身份。回执缺失、仍待处理、不匹配或属于未支持类型时，只保留进程退出通知。查询不连接接收方，也不重放投递。

## 复现

准备一份位于清单所列基础版本、干净且可丢弃的 Hermes 源码副本，以及包含固定宿主测试依赖的 Python 3.14 环境。Linux 需支持用户、网络、挂载和 PID 命名空间以及 PID 描述符。启动器在启动任何 Gateway 前检查候选提交的父提交、提交树、补丁摘要和源码副本的干净状态。发布运行包不包含此实验。

```sh
set -eu
artifact="$PWD/experiments/bot-sender-recovery"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/bot-sender-recovery.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/bot-sender-recovery.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'fix(bot): recover local reply completions across gateway loss'
for mode in --owner-loss --settled-loss --finished-loss --consumed-loss --admitted-loss \
    --planned-restart --held-waiter-restart --drained-waiter-restart \
    --result-write-failure --consumed-write-failure --admitted-write-failure \
    --killed-settled-receipt --mismatched-waiter-receipt; do
  sh acceptance/live/run_native_bot_poll_reply.sh \
    --hermes "$DISPOSABLE_HERMES" --hermes-python "$PINNED_PYTHON" \
    "$mode" --review-recovery
done
```

对未修改的固定版本运行 `--owner-loss`、`--settled-loss`、`--finished-loss`、`--planned-restart`、`--held-waiter-restart` 和 `--drained-waiter-restart`，并省略 `--review-recovery`，即可验证对照组。

## 证据

Linux 和 Python 3.14.9 下，三项未修改宿主意外退出对照用例复现了发送端完成通知缺失。评审树通过了两项等待进程退出前的真实 Gateway 用例。已结算回复在原发送会话中出现一次，保留原投递 ID、进程 ID 和退出码零。中断用例产生一次不确定的完成记录，告知发送端保留回执、避免重发，退出码为一。两项均验证只有原接收方的一次模型请求、恢复期间无发送方推理、接收方原回执可原样重放、保留的进程结果限定在发送方 profile，且 Gateway 再正常重启一次也不会产生重复完成记录。上游专项套件通过 255 项，跳过 5 项。其中 profile 回归用例验证启动和发送方 profile 均保存同一检查点条目时的接管行为。

等待进程结果已保存的对照用例保留原回复，但不会显示发送端完成通知。候选宿主对待通知结果呈现一次。故障前真实读取日志会阻止通知，故障前已准入的完成记录在恢复后仍只有一条。三项补丁用例均验证接收方保留原回复且仅执行一次推理，并在再次正常重启后复查。

计划重启用例在等待进程结束且发送方完成通知尚未进入会话队列时，向夹具持有的 Gateway 发送原生 `SIGUSR1`。用例验证计划重启标记、服务重启退出状态和端点释放，再启动后继进程。未修改宿主保留接收方回复，但不会恢复发送方记录。候选方案恢复一条记录，不触发再次推理，再重启一次也没有重复记录。

三项候选专用用例在发送方结果原子写入前注入 `ENOSPC`，同时保留检查点、输出日志和退出记录。此前的候选树 `0e9be5956551d182605e133ef2377443cf4e91b7` 会在这一窗口丢失交接条目。当前候选树保留原交接条目，在同样的原生计划重启且写入恢复后重建结果。待处理通知出现一次，显式消费的结果保持静默，已使用同一身份准入的通知去重。三项均保留接收方原回执、没有重发，并验证之后重启不会重复准入。专项测试还验证存在匹配结果或原生退出记录超过保留期限后，交接条目会被清理。

收到重启信号时，等待进程仍在运行。排空用例在宿主报告正在排空后才释放合成接收方。两个宿主均保留原接收方的已结算回复。候选方案在原发送方 profile 中收集该回复，并显示一条完成通知。在强制中断用例中，夹具保持接收方响应挂起，并暂停自己持有的等待进程，确保关闭清理覆盖它。接收方保留一条中断的准入和包含关闭诊断的失败投递回执。候选方案从正确的 profile 恢复一条发送方进程退出通知，其中包含原投递 ID 和经校验的失败诊断。在另一用例中，接收方成功排空，但暂停的等待进程在读取已结算回复前被终止，候选方案在同一完成通知中恢复该回复。若夹具将已保存的目标会话替换为不匹配的 ID，监视器只发出进程退出通知。两个宿主的原样重试都对账到原回执，且未重发。两个未修改宿主对照均未恢复发送方通知。

## 边界

恢复契约覆盖等待进程尚未退出时的一次宿主意外退出、后继进程接管以及随后一次正常重启。输出已持久化的用例分别覆盖尚未准入、已消费，以及已准入但本地确认丢失三种情况。结果和检查点同时写入失败、已保存的结果替换检查点后消费状态无法写入、含重试准入的重发布回执、回执缺失或未达终态时超出进程退出通知的处理、接管期间的多次故障、启动时已有客户端连接的竞态、远程路由、Windows、已安装环境的采用以及真实服务商均需要独立证据。候选方案尚未启用，也尚未提交上游。
