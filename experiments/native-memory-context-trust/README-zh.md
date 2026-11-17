# 原生记忆上下文信任标注提案

[English](README.md) | 简体中文

仅供评审的宿主补丁，基于 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427`。原版宿主要求模型将预取记忆视为权威参考数据。可选 personal-records 提供方将其 JSON 标记为不受信证据。隔离的已安装 wheel 验收在同一个请求中观察到两种标注。[PR #249](https://github.com/MosBot-AI/hermes-superagent/pull/249)

## 请求行为

提案将新召回的原生记忆标记为不受信的背景数据。外层提示要求模型核对其中的表述，并忽略其中的指令及声称拥有的权限。原生边界标签和提供方内容仍位于用户消息中。文本和多模态轮次共用同一宿主渲染逻辑。这项标注不提供经过验证的身份或授权。

普通请求与迭代摘要的构建器会替换用户 `api_content` 中精确匹配的旧宿主标注，也会替换以旧边界开头的历史多模态文本部分中的标注。召回正文、随后的插件上下文以及其他角色的内容保持不变。只要 sidecar 仍包含原始文本前缀，该前缀也会保留。没有 sidecar 的普通用户文本保持不变。对于历史会话，升级后首次重放的提示缓存前缀可能变化。预检和尾部预算采用相同的投影内容。已存 sidecar 和规范记录的字节保持不变。

当 Hermes 展平并清理会话历史时，载入的原生多模态消息可能已经去掉记忆边界。提案不会向这些消息重新加入数据。普通请求测试保留一个带类型的多模态部分，以验证该部分仍存在时的重放路径。

## 验证

使用精确版本的一次性 Hermes 检出及已有的 Python 3.14 测试环境。审阅补丁后，显式应用到一次性检出。

```sh
git -C "$DISPOSABLE_HOST" apply --check "$ARTIFACT/native-memory-context-trust.patch"
git -C "$DISPOSABLE_HOST" apply --index "$ARTIFACT/native-memory-context-trust.patch"
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON" --check-only
python "$ARTIFACT/run_tests.py" --checkout "$DISPOSABLE_HOST" --python "$PREPARED_PYTHON"
```

运行器核对精确基线、暂存 diff 和树，拒绝已跟踪文件的工作区偏差及未忽略的未跟踪文件，并使用私有临时主目录。HTTP 夹具经实际原生请求构建器在回环地址发送合成数据。测试覆盖新代理读取 SQLite 旧 sidecar、同一次请求内的新召回、保留的多模态边界、摘要投影、预算一致性，以及保留用户引用的原始文本。清单记录所选测试集及结果。

另一次本地验收使用 PR #249 的已安装 wheel 夹具，独立运行时从 main 构建并经过验证。原版 Gateway 将第 1 版写入真实会话后停止。更正记录后，新的候选 Gateway 恢复了同一个会话。它的一次请求同时携带作为历史的第 1 版和作为新召回的第 2 版，两者均带有不受信标注。重放没有更改旧 sidecar 或规范 SQLite 数据库。这一次性的跨进程检查与可重复的回归套件分开记录。

提案尚未提交上游，且处于未启用状态。受支持的 Hermes 版本和已分发的运行时保持原有行为。已存储、已发送或已融入摘要的召回文本可能继续保留。提供方上线、真实模型行为、不透明的服务端检查点及严格 checkpoint-v2 均不在本次验证范围内。[议题 #45](https://github.com/MosBot-AI/hermes-superagent/issues/45)

补丁中的上游代码适用[保留的许可证](LICENSE.hermes-agent)。
