# 仅供审阅的 profile 重命名 LOCAL 回执保留

[English](README.md) | 简体中文

针对 [Issue #33](https://github.com/MosBot-AI/hermes-superagent/issues/33) 的[审阅补丁](local-receipt-rename.patch)在独立 Hermes 构建中添加 `hermes profile rename OLD NEW --preserve-local-sessions`。[清单](manifest.json)记录精确基线、候选源码树和补丁摘要。来自上游的材料保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。

Linux 候选要求持有安装和原命名 profile 的原生维护锁，并在确认目标路径尚不存在的情况下移动实际 home。在迁移后的存储中，现有的原生 SQLite 重命名事务先验证 LOCAL 创建身份、精确路由条目、已存会话谱系及空闲状态，再迁移回执中的路由和来源 profile。创建 ID、创建时路径、主体、创建请求、策略、消息记录和持久准入保留原身份。校验拒绝时事务回滚，私有 home 返回旧名称。单独运行 `profile migrate-identity` 不会获得迁移回执的权限。

适用范围是在支持 `renameat2` 与 `RENAME_NOREPLACE` 的文件系统中，对同一 Linux 安装内空闲的命名 profile 显式重命名。审阅参数排除 `default`、特殊的 `main` 命名空间、运行中 Gateway 的所有权，以及从旧会话接管的 LOCAL 回执。发布目录时发生进程退出、文件系统或 SQLite I/O 失败，引用 profile 内路径及凭据，跨新旧 home 重试无标题会话创建，以及经认证的所有者恢复，均需单独验收。仅对一次性存储运行夹具。受支持的固定版本及运行时归档不包含此补丁。

## 复现

准备一次性的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 检出和兼容的 Hermes 测试解释器。从 Personal Agent 仓库根目录应用补丁并提交候选版本，夹具随后会验证精确源码树及差异。

```sh
set -eu
artifact="$PWD/experiments/local-receipt-rename"
test "$(git -C "$DISPOSABLE_HERMES" rev-parse HEAD)" = 2281116525106e3c109993ccb5dc74d02bfc1427
test -z "$(git -C "$DISPOSABLE_HERMES" status --porcelain)"
git -C "$DISPOSABLE_HERMES" apply --check "$artifact/local-receipt-rename.patch"
git -C "$DISPOSABLE_HERMES" apply --index "$artifact/local-receipt-rename.patch"
git -C "$DISPOSABLE_HERMES" commit -m 'feat(profile): preserve local receipts during explicit offline rename'
scratch="$(mktemp -d /var/tmp/lr.XXXXXX)"
mkdir "$scratch/home" "$scratch/tmp"
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 HOME="$scratch/home" TMPDIR="$scratch/tmp" \
  HERMES_TEST_ROOT="$DISPOSABLE_HERMES" HERMES_REVIEW_LOCAL_RECEIPT_RENAME=1 \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$PINNED_PYTHON" -m pytest -q -p no:cacheprovider --show-capture=no \
  --basetemp="$scratch/pytest" acceptance/live/test_native_local_receipt_rename.py
```

夹具在其自有的 home 中启动真实 Gateway，认证 host 作用域客户端，并从已验证候选的私有导出运行原生 CLI。夹具通过 Gateway 创建原 Bot Chat，使用原生存储操作准备合成的压缩子会话和准入，不调用模型。现有的[干净固定版本重命名夹具](../../docs/15-primary-bot-binding-zh.md#当前固定版本的原生-profile-重命名)覆盖受支持的运行时。

候选夹具检查运行中的所有权、已占用的目标路径、指向副本的目标路径以及待处理准入都会导致拒绝。取消待处理输入后，移动的是同一个物理状态数据库。使用新的原生票据可在新名称下读取并恢复原 Bot Chat。名册保留原始根和压缩末端，能看到压缩消息，重复按标题打开会返回原会话。已取消的准入及所比较的消息行保持一致。单独重试身份迁移也不会改变已迁移的回执。
