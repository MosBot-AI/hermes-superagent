# SSH 草稿恢复审阅提案

[English](README.md) | 简体中文

[补丁](ssh-draft-recovery.patch)让用户可以在原 SSH 会话中显式查看结果不确定的普通文本提交。它针对 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上的 [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33)。[清单](manifest.json)绑定精确补丁和源码树。源自上游的代码保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。

Electron 异常退出时，渲染进程草稿可能丢失。旧协议发送前，现有原生日志已保存原提交 ID 和意图。提案在发出旧协议尝试前，将 SSH 目标配置的摘要附加到同一条记录。显式重开原作用域会话后，用户可以在空输入框中用原 ID 查看原始编辑文本。未编辑的发送、排队和引导操作均显示现有的结果不确定警告，保留输入框中的草稿，且不发出传输请求。编辑内容适用现有 composer 规则，成为新草稿。未经编辑的审阅副本只保留在限定作用域的日志及当前输入框，避免进入仅按会话 ID 索引的普通草稿存储。

恢复按精确保存连接、Desktop profile、目标 profile 和已存会话筛选。目标配置变更、缺少路由证据、旧版含糊记录、斜杠命令、排队或隐藏提交，以及附件均不会恢复。显示文本前，该操作会重新读取日志并核对当前路由和输入框。摘要描述所配置的路由，无法证明沿用同一配置的替换环境拥有相同物理安装、主机密钥或 owner。操作者需重开原会话并主动选择查看。该操作不授予准入权限，不向其他客户端同步草稿，也不自动发送。

## 复现

使用固定版本的临时 Hermes 检出、固定 Node 和 Python，以及准备好锁定依赖的 Desktop 工作区。仅在该检出中应用并提交补丁，构建前将源码树与清单核对。

```sh
set -eu
artifact="$PWD/experiments/ssh-draft-recovery"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/ssh-draft-recovery.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/ssh-draft-recovery.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'fix(desktop): recover unconfirmed SSH drafts after process exit'
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
for case_name in bot-canonical-ssh-draft-crash bot-canonical-ssh-draft-crash-no-continue; do
  python -m acceptance.live.run_desktop_profile_routing \
    --case "$case_name" --review-proposal --hermes "$DISPOSABLE_HERMES" \
    --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE"
done
```

运行器要求清单摘要、干净父提交和源码树、跟踪文件、精确补丁及构建产物均匹配。测试在只含环回网络的 Linux 命名空间内运行，使用合成 SSH 凭据、消息和 provider。[基线](../../docs/15-primary-bot-binding-zh.md#当前固定版本的-openssh-desktop-异常退出)使用干净固定版本，去掉 `--review-proposal`。提案尚未提交上游或启用。支持基线和分发运行时仍使用干净 Hermes 版本。
