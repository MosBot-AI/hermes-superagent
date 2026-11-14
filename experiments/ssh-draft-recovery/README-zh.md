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

## Linux 打包验收

从干净的提案提交构建未签名的 Linux x64 AppImage，使用 Hermes 构建器及[固定版本的图标工具预加载脚本](../../docs/15-primary-bot-binding-zh.md#当前固定版本的-bot-mode-规范会话拒绝与重试)。以下命令调用 `scripts/build-bundle.sh` 背后的上游驱动，允许操作者指定独立的工作目录和缓存目录。从 Personal Agent 仓库根目录运行。所有路径均使用 `/tmp` 之外的绝对路径，并在复制验收夹具前完成构建。

```sh
set -eu
commit=$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = 94260c86f63b93084d97acd2df76a2aa838bf608
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
CSC_IDENTITY_AUTO_DISCOVERY=false \
HERMES_E07_ICON_TOOL_DIR="$DISPOSABLE_HERMES/apps/desktop/build/prepared-packaging-tools/icons" \
NODE_OPTIONS="--import=$ABSOLUTE_PRELOAD_PATH" \
  "$PINNED_PYTHON" "$DISPOSABLE_HERMES/scripts/bundles/desktop.py" \
  --repo "$DISPOSABLE_HERMES" --commit "$commit" --variant bundled \
  --work "$BUNDLE_WORK" --cache "$BUNDLE_CACHE"
```

给两个提案用例都加上 `--appimage /absolute/path/to/Hermes.AppImage`。两个干净对照使用干净固定版本及匹配镜像，去掉 `--review-proposal`。负向对照则将干净镜像传给提案用例。预期在启动打包 Electron 前报 `AppImage commit must match the verified checkout`。夹具启动打包渲染进程并验证安装标记、ASAR 及可执行的内置 CLI。夹具自有的 Gateway 从检出的测试源码运行。

[清单](manifest.json)记录了候选和干净镜像的摘要。两种镜像在启用及禁用续跑时均通过。干净镜像重开原会话，输入框为空。候选镜像在显式查看时恢复文本，两次原样按 Enter 各产生一条新警告，且没有再次提交。重新加载渲染进程后，原日志记录再次可供查看，渲染进程草稿存储仍为空。启用续跑时恰好续跑一次，禁用时为零。干净镜像在提案用例中于启动前未通过安装标记检查。

使用同一运行器的 `--case bot-canonical-ssh-draft-endpoint-replacement`，可在禁用原生续跑的情况下检查所配置端点的替换。分别使用匹配的干净和提案构建，仅在提案用例中添加 `--review-proposal`。异常退出后，夹具将已保存的 SSH 连接改为不同的监听端点、客户端密钥及启动器。两个安装使用相同的命名 profile 及已存储会话 ID，并各有不同的安装标记和会话记录。替换端显示自己的会话记录，输入框为空，也没有草稿查看操作。原日志条目仍保留，访问期间两个会话记录均未改变，也没有新提交、会话创建或 provider 调用。恢复原端点后，候选构建再次提供显式查看，并保护两次原样按 Enter 的操作。两个源码构建和两个本地构建的未签名 Linux x64 AppImage 均通过此用例。

运行 `--case bot-canonical-ssh-draft-unchanged-route` 可验证修改端点用例通过后仍存在的发布条件。夹具保留已保存的注册表、SSH 凭据和启动器，停止原后端并提供另一个具有相同安装标记及规范会话 ID 的合成数据目录。两个源码构建和两个本地构建的未签名 AppImage 均显示替换端自己的消息记录，输入框保持为空。提案版仍在该会话提供草稿查看，干净对照没有此操作。测试在替换端特意不点击它，并验证原日志条目仍存在，访问期间两个会话记录、提交数和 provider 调用数均未变化。切回原会话后仍可查看草稿，并保留已有的未确认提交保护。

候选方案需要与当前后端绑定的原生连续性信号，才能在重新连接后安全提供查看操作。相同的 SSH 配置值和安装标记可指向不同的数据目录。owner 验证、签名发行包、其他系统及上游采用仍需单独验收。

[单独的连续性提案](../ssh-draft-continuity/README-zh.md)增加并测试了这项后端检查。原补丁保留为复现不明确查看操作的对照。
