# 原生 cron 投递回执回写

[English](README.md) | 简体中文

此评审产物修复 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 的原生投递记账。发送由原生队列负责。候选使用队列现有的终态回执，结算原执行及匹配的当前作业摘要。精确暂存树和验证输入见 [manifest.json](manifest.json)，上游许可证见 [LICENSE.hermes-agent](LICENSE.hermes-agent)。

## 恢复行为

如果 Gateway 进程在队列提交终态回执后退出，干净版本的原生队列在重启后会跳过该回执，因为发送已经成功、被拒绝、被抑制，或已被标记为未知。执行记录可能一直处于 `queued`，作业也可能继续显示正在投递。干净版本还会将队列回执的 `unknown` 在执行账本中记为 `failed`。

候选保留执行记录的 `queued` 标记，直到精确的作业更新完成，或作业摘要已指向更新的执行。后续原生队列处理分批查找仍保留的排队执行和终态回执，包括队列修剪后保留的墓碑。原生回写会校验作业与执行的绑定，使用 CAS 结算具体执行，保留较新的作业摘要，并区分 `unknown` 与 `failed`。较新的执行可能已经开始，但尚未写入摘要。较新的摘要提交前，排队摘要仍归最近一次权威完成的执行。如果进程在作业更新和执行更新之间再次退出，该标记仍可供下一次原生队列处理恢复。恢复过程不会选择任何投递供传输，也不会新增队列记录。

`hermes cron runs` 将已记录的投递结果与执行状态分别展示。`hermes cron list` 使用随当前作业摘要保存的结果，较新的执行仍在运行时也会提示未知投递。较新的执行完成后会清除先前的结果。重试未知结果前须核对原目标。原生队列的 `delivered` 记录发送回调成功，不能证明接收人已收到或阅读。恢复需要仍保留带 `queued` 标记的执行，以及终态队列回执。它不会回溯迁移早期已归并的失败，也不会重建已修剪的执行。

## 验证

两个干净版本对照分别复现回写丢失和未知结果被归并。Python 3.14.9 下，11 项候选用例和 89 项原生回归均通过。候选使用真实 cron 执行入口、持久队列和重启恢复路径。子进程分别在合成传输接受前、接受后、队列提交后和作业摘要写入后退出。独立的仅追加测试回执可区分零次和一次模拟接受。后续队列连续处理两次，均未重发。用例还覆盖修剪后的回执、较新执行已完成、较新执行仍在运行时的成功及未知回执、等待超时、作业 ID 不匹配、队列提前结算及现有 CLI 展示。15 项上游静态检查及导入边界检查全部通过。

产物位于运行时包之外，只使用合成 profile。宿主采纳、生产权限、真实通知投递及完整 E4 验收仍待完成。

## 复现

将 `PROJECT` 设为本项目检出，`COPY` 设为干净的一次性 Hermes 检出，`PYTHON` 设为准备好的 Python 3.14 测试解释器。

```bash
set -eu
ARTIFACT="$PROJECT/experiments/cron-delivery-writeback"
BASE=2281116525106e3c109993ccb5dc74d02bfc1427
test "$(git -C "$COPY" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$COPY" status --porcelain --untracked-files=all)"
printf '%s  %s\n' 877018e2bd1a41d25b6dbc9b528669271523c099033767bfbd94a74deac90053 "$ARTIFACT/cron-delivery-writeback.patch" | sha256sum -c
cd "$COPY"
CHECK_HOME="$(mktemp -d)"
export HOME="$CHECK_HOME"
export HERMES_PYTHON="$PYTHON"
umask 022
bash scripts/run_tests.sh "$ARTIFACT/test_writeback.py" --file-retries 0 -- -o "pythonpath=$COPY" -k clean_pin -q
git apply --check "$ARTIFACT/cron-delivery-writeback.patch"
git apply --index "$ARTIFACT/cron-delivery-writeback.patch"
test "$(git write-tree)" = fb0c17aaf12e3656400b3b96306770fd017e9a00
bash scripts/run_tests.sh "$ARTIFACT/test_writeback.py" --file-retries 0 -- -o "pythonpath=$COPY" -k candidate -q
bash scripts/run_tests.sh tests/cron/test_delivery_queue.py tests/cron/test_delivery_queue_retention_race.py \
  tests/cron/test_delivery_outcome_writeback.py tests/cron/test_queued_delivery_fencing.py \
  tests/cron/test_execution_ledger.py tests/cron/test_cron_cancel_bookkeeping.py \
  tests/gateway/test_cron_delivery_housekeeping.py tests/hermes_cli/test_cron.py --file-retries 0 -- -q
"$PYTHON" scripts/check --base "$BASE" --staged
"$PYTHON" scripts/boundary_lint.py --check
```
