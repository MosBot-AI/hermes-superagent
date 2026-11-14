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
