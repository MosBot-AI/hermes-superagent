# 仅供评审的 Webapp Bot Chat 作用域提案

[English](README.md) | 简体中文

[候选补丁](bot-webapp-canonical.patch)面向 [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33)，在 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上提出 Desktop 路由修正。提案尚未提交上游，也未激活。官方兼容性固定版本仍为干净的 Hermes 修订。源自上游的文件保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。[清单](manifest.json)绑定确切的补丁摘要及提案源码树。

## 范围

命名 Bot Mode 会话按确切标题查询 `session.list`，并携带后端 `profile` 参数。查询返回空列表时，回退的 `session.info` 探测名册中的规范会话 ID。已保存的 Webapp 令牌套接字从启动 authority 开始，可将显式指定 profile 的请求路由到提供服务的其他 profile。提案为带来源的回退调用添加后端 `profile` 参数，并增加一项别名测试。没有来源路由的回退调用保留原参数形态。[固定版本源码和验收边界](../../docs/15-primary-bot-binding-zh.md#当前固定版本的已保存-webapp-bot-mode-路由)

## 复现

使用单独准备、可丢弃且不含真实凭据的 Hermes 检出和锁定的 Desktop 工具链。从 Personal Agent 仓库根目录执行，将 `DISPOSABLE_HERMES`、`PINNED_NODE` 和 `PINNED_PYTHON` 设置为 `/tmp` 之外的绝对路径。[Electron 运行器](../../acceptance/live/run_desktop_profile_routing.py)使用私有 Linux 命名空间、Xvfb 和仅回环网络。它校验提案是固定提交的干净直接子提交，检查构建标记，并通过上游检查确认 Desktop 和 Webapp 产物来自当前源码。补丁由下列命令手动应用。下面手动创建的本地提交 ID 可以与已评审提交不同，但源码树必须与清单一致。

将固定版本 pnpm `12.15.0` 加入 `PATH`，并准备锁定的 Desktop 依赖及 Webapp 构建所用的独立依赖工作区。Webapp 构建器的隔离镜像需要单独准备好的依赖，或已有内容的 pnpm 缓存。通过验证的离线构建使用该缓存的私有副本，并设置 `npm_config_offline=true`。

```sh
set -eu
ARTIFACT="$PWD/experiments/bot-webapp-canonical"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
printf '%s  %s\n' \
  e50e573140b1de21d9c8b5ddeb3a82ed0bd898e53b1fcdb345863fbe9cecbf80 \
  "$ARTIFACT/bot-webapp-canonical.patch" | sha256sum --check
git -C "$DISPOSABLE_HERMES" apply --check "$ARTIFACT/bot-webapp-canonical.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$ARTIFACT/bot-webapp-canonical.patch"
git -C "$DISPOSABLE_HERMES" commit -m "fix(desktop): scope Bot Chat fallback lookup"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD^{tree})" = 49ff33f721dd356bc1ea853dde8a1623c460ac05
(
  cd "$DISPOSABLE_HERMES/apps/desktop"
  export npm_config_offline=true
  "$PINNED_NODE" scripts/build.mjs
  "$PINNED_NODE" scripts/build-webapp.mjs
)
python -m acceptance.live.run_desktop_profile_routing \
  --case bot-canonical-saved-token --review-proposal \
  --hermes "$DISPOSABLE_HERMES" \
  --hermes-python "$PINNED_PYTHON" \
  --node "$PINNED_NODE"
```

使用准备好的干净基线检出单独运行 `--case bot-canonical-saved-token`。该次调用省略 `--review-proposal`。

测试捆绑式 Linux x64 安装包时，在两个检出目录分别运行上游 `scripts/build-bundle.sh`，并使用[固定版本的图标工具解决方法](../../docs/15-primary-bot-binding-zh.md#当前固定版本的-bot-mode-规范会话拒绝与重试)构建本地 AppImage。请等打包完成后再将验收夹具放入检出目录。每次运行验收时添加 `--appimage /absolute/path/to/Hermes.AppImage`。启动器验证镜像标记与夹具使用的干净提交或已验证的候选提交完全一致。重新构建的候选提交可以使用不同 ID，其父提交、文件树和补丁必须与清单匹配。请使用各自对应的镜像运行干净版本和候选版本。

## 证据

干净构建与提案构建各通过一项隔离的 Linux Electron 用例。两次运行均使用两个由夹具控制的 Gateway 安装，并在真实的命名 profile 查询后注入一次空结果。[界面夹具](../../tests/desktop/desktop_bot_saved_token_refusal.spec.ts)

- 干净 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 向远程 `default` 处理器发送无 profile 参数的 `session.info`。收到 `4001 not_found` 后，同一次点击执行第二次带作用域的查询并打开原会话。
- 基于本地提交 `14c1a21fc4601de51000cba05d61894902773524` 构建的提案发送 `profile: scout`。原生命名处理器确认现有会话，界面保留原焦点并提示重试。随后明确点击打开原会话。

两次运行均观察到四个夹具数据库的会话、消息和准入投影保持不变，无会话创建或提示词提交，且模型补全次数为零。夹具重构后，干净版本的 profile 路由和本地 Bot Mode 用例也通过。提案源码通过 52 项选定的上游 Vitest 用例，包括 15 项规范会话注册表用例（含新增别名用例）、20 项名册用例和 17 项路由用例。

认证与授权仍由原生宿主管理。补丁仍为评审工件。上游采用、受支持的打包和其他凭据模式需要独立证据。
