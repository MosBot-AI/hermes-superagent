# 仅供审阅的 SSH 草稿连续性

[English](README.md) | 简体中文

此[补丁](ssh-draft-continuity.patch)针对 [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33)，扩展[最初的 SSH 草稿提案](../ssh-draft-recovery/README-zh.md)。它是 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上的独立提交。[清单](manifest.json)记录了精确源码树和补丁。源自上游的材料保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。

旧协议 Gateway 根据当前后端实例、数据库文件身份、SQLite 世代及记录创建时间，为当前附着的精确存储会话生成不透明摘要。客户端在旧协议提交前记录摘要，提交处理器在开始尝试前核对同一摘要。Desktop 在现有的会话作用域套接字上先验证当前证据，再显示查看操作；显示文本前再次验证。证据缺失或不匹配时，日志条目仍保持私有。早期只记录配置路径的条目保留在日志中，但不具备查看资格。在同一次后端实例生命周期内，Gateway 和 Desktop 重启后，受支持的原会话仍可主动查看草稿。原样使用审阅后恢复的草稿，仍会触发防止重复提交的保护。

适用范围是启动身份可读、状态数据库完整且具有精确存储会话记录的 Linux 后端。后端重启进入新的启动周期、数据库恢复或替换、缺少契约、存储不可用或无法解析路径时，查看可能不可用。摘要只约束本地草稿披露。经认证的个人所有者绑定与更广泛的恢复策略仍需独立证据。

## 复现

准备一次性检出及锁定版本的 Node、Python 和 Desktop 依赖。将完整补丁直接应用到干净的 Hermes 基线。从 Personal Agent 仓库运行夹具。

```sh
set -eu
artifact="$PWD/experiments/ssh-draft-continuity"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/ssh-draft-continuity.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/ssh-draft-continuity.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'fix(desktop): bind SSH draft review to the active session store'
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
for case_name in bot-canonical-ssh-draft-crash bot-canonical-ssh-draft-crash-no-continue bot-canonical-ssh-draft-unchanged-route; do
  python -m acceptance.live.run_desktop_profile_routing --case "$case_name" \
    --review-draft-continuity --hermes "$DISPOSABLE_HERMES" \
    --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE"
done
```

运行器在启动隔离 Desktop 和 OpenSSH 夹具前验证完整补丁及源码树。干净基线不加审阅参数。历史负向对照使用独立的最初提案检出及 `--review-proposal`。

源码版在 Electron 和 Gateway 异常退出后的两种原生续跑配置下均通过。路径不变的用例保留凭据、别名和安装标记，并用实际 SQLite 数据库副本替换后端数据。副本保留已存储会话 ID、时间戳和数据库世代。新候选版使替换端输入框保持为空并隐藏查看操作，原日志条目仍保留。切回原状态文件后恢复查看，两次原样按 Enter 均受到保护。后端测试还验证，复制实际数据库并保留其世代元数据时，副本仍具有不同的连续性证据。

## Linux 打包验收

从已提交的候选版本检出中，使用 Hermes Desktop 打包程序构建 bundled 变体。准备新的构建工作目录、本地依赖缓存及 Linux 构建依赖。将 `ICON_PRELOAD` 设置为 [CommonJS 图标工具预加载脚本](../../docs/15-primary-bot-binding-zh.md#当前固定版本的-bot-mode-规范会话拒绝与重试)的绝对路径。从 Personal Agent 仓库根目录运行夹具，运行前计算完整镜像的 SHA-256。

```sh
set -eu
commit=$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = d7c0cb003cfe40b8e7bf0b21603a8cdd55125d3c
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
CSC_IDENTITY_AUTO_DISCOVERY=false \
HERMES_E07_ICON_TOOL_DIR="$DISPOSABLE_HERMES/apps/desktop/build/prepared-packaging-tools/icons" \
NODE_OPTIONS="--import=$ICON_PRELOAD" \
  "$PINNED_PYTHON" "$DISPOSABLE_HERMES/scripts/bundles/desktop.py" \
    --repo "$DISPOSABLE_HERMES" --commit "$commit" --variant bundled \
    --work "$BUILD_WORK" --cache "$BUILD_CACHE"
appimage="$DISPOSABLE_HERMES/apps/desktop/release/HermesBundled-0.0.0-linux-x86_64.AppImage"
sha256sum "$appimage"
for case_name in bot-canonical-ssh-draft-crash bot-canonical-ssh-draft-crash-no-continue bot-canonical-ssh-draft-unchanged-route bot-canonical-ssh-draft-endpoint-replacement; do
  python -m acceptance.live.run_desktop_profile_routing --case "$case_name" \
    --review-draft-continuity --hermes "$DISPOSABLE_HERMES" \
    --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE" --appimage "$appimage"
done
```

夹具核验镜像的干净提交标记、内置 CLI、打包的 Electron 可执行文件和 ASAR。隔离的 OpenSSH Gateway 从已验证的源码检出运行。负向对照可换用干净固定版本或早期恢复提案的镜像。安装标记断言应在启动打包的 Electron 前失败。发生拒绝时，运行器会输出私有诊断目录，具体的 `AppImage commit must match the verified checkout` 断言可见于目录内的 `playwright.json`。

[清单](manifest.json)记录了未签名 Linux x64 构建的精确提交、源码树、工具版本和镜像摘要。此主机为生成的图标工具提供了 CommonJS 包边界、X11 头文件和库，以及早期构建使用同一份 `uv.lock` 缓存的注册表 wheel。打包程序从候选检出重新构建了原生依赖和运行载荷。

打包的渲染进程在原存储上通过了启用和禁用原生续跑的用例。在配置不变的 SSH 路径改为提供 SQLite 存储副本时，应用显示替换端的消息记录，输入框为空且不提供查看。单独修改端点配置的用例同样没有披露草稿。两个用例均保留原日志条目，重开原存储后可主动查看并保留保护。每次原样按 Enter 均不改变提交、消息记录或 provider 调用计数。两个不匹配的镜像都在 Electron 启动前未通过安装标记检查。签名分发、其他系统及经认证的个人 owner 连续性仍待验证。
