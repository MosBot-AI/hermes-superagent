# 仅供评审的 Desktop 已保存令牌恢复方案

[English](README.md) | 简体中文

[候选补丁](desktop-saved-token-recovery.patch)处理 [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) 在 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上发现的已保存令牌重连失败。[清单](manifest.json)绑定补丁摘要和确切的派生源码树。源自上游的补丁遵循 [Hermes MIT 许可证](LICENSE.hermes-agent)。

Desktop 连接编辑器保存替换令牌后，会刷新该连接的池化描述。运行中的主连接还持有一份进程级连接描述。当实际主连接从同一 URL 的已编辑注册表条目获取令牌时，候选方案在保存后使该描述失效。如果主窗口仍在该来源上，则使用现有连接应用信号重连。补丁沿用现有路由优先级、注册表保存及原生授权路径。

## 复现

准备一个位于确切基线提交、不含凭据且可随时丢弃的 Linux checkout。使用锁定的 Desktop 工具链及[固定版本构建说明](../../docs/15-primary-bot-binding-zh.md#当前固定版本的-electron-profile-路由)。将 `DISPOSABLE_HERMES`、`PINNED_NODE` 和 `PINNED_PYTHON` 设置为 `/tmp` 之外的绝对路径。从 Personal Agent 仓库根目录执行以下命令。

```sh
set -eu
ARTIFACT="$PWD/experiments/desktop-saved-token-recovery"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
printf '%s  %s\n' \
  cbeb4455ae2dbe2ea17afead6b8b63fb6e5d717dc110ebba2f64ff87fe9151f8 \
  "$ARTIFACT/desktop-saved-token-recovery.patch" | sha256sum --check
git -C "$DISPOSABLE_HERMES" apply --check "$ARTIFACT/desktop-saved-token-recovery.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$ARTIFACT/desktop-saved-token-recovery.patch"
git -C "$DISPOSABLE_HERMES" commit -m "fix(desktop): reconnect the primary after a saved token edit"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = b9c556f7f33fcf5e777eaff57ff4a6d85773f8cf
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
"$PINNED_PYTHON" -m acceptance.live.run_desktop_profile_routing \
  --case desktop-saved-token-sign-out --review-proposal \
  --hermes "$DISPOSABLE_HERMES" --hermes-python "$PINNED_PYTHON" --node "$PINNED_NODE"
```

运行器在启动隔离夹具前验证完整补丁、源码树、干净且直接继承固定提交的关系，以及源码构建标记。另行准备干净固定版本，去掉 `--review-proposal` 执行对照用例。测试本地打包的未签名 Linux x64 AppImage 时，在对应 checkout 中使用 `scripts/build-bundle.sh` 和[已记录的图标工具处理方法](../../docs/15-primary-bot-binding-zh.md#当前固定版本的-bot-mode-规范会话拒绝与重试)。向验收命令添加 `--appimage /path/to/Hermes.AppImage`。运行器在 Electron 启动前验证安装包标记。

## 证据

干净源码对照中，旧 Desktop 套接字关闭，旧令牌收到 HTTP `401`，更新注册表后限定作用域的 SDK 读取仍被拒绝。完整重启 Desktop 后可打开原 `scout` Bot Chat。候选版在显式更新注册表后重连，原 Electron 进程和渲染文档继续运行。显式点击 Bot Mode，经新的限定作用域套接字发出打开请求，并聚焦原会话。独立的原生票据路由在轮换后及恢复后均可读取自己的同名会话。用例验证路由可用性及两个 Gateway 的身份。Desktop 应用连接时可能重建另一条路由的渲染器套接字。

两个源码用例比较执行前后同样的四组 SQLite 会话、消息及准入字段。夹具未观察到新会话、提示词提交或模型补全。候选版通过了 Electron 类型检查和 138 项路由、注册表及后端状态专项测试。评审用例覆盖由注册表提供实际主连接凭据时，在同一 URL 显式替换已保存令牌。签名构建、其他凭据模式、跨安装恢复和经认证的 owner 连续性需独立验收。候选方案尚未提交上游，也未启用。

本地打包的未签名 Linux x64 AppImage 复现了干净版本和候选版本的结果。候选包来自 `a2f9c951bddfa31e275ca0508cddb8d53ed93320`，SHA-256 为 `a4fa2154b79fb95cebb5960d6e3371594addbdab8b4453957b7822b6f01d8e16`。在候选模式下提供干净安装包，运行器会在 Electron 启动前拒绝。候选安装包的本地构建使用 Clang `19.1.7` 及图标工具处理方法。由于缺少 XInput2 头文件，构建器省略了可选的 X11 修饰键监视器。
