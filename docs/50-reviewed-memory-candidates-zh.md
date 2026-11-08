# 50. 经审核的记忆候选

[English](50-reviewed-memory-candidates.md) | 简体中文

独立插件现在可选择让模型从当前原生用户输入起草记忆候选，经过独立本地审核后才写入正式记忆。实现使用受支持的 `pre_llm_call`、模型工具与 `post_llm_call` hook，不依赖实验 worker 补丁。它不启动额外提取模型、不替换已配置 provider、不摄取历史，也不宣称 checkpoint-v2 覆盖。

## 1. 明确启用与审核

保留[记忆工具前置条件](32-session-scoped-memory-tools-zh.md)：`mode: local_tasks`、`local_conversation: true`、`local_memory: true` 和 `memory_model_tools: true`。另行明确设置 `memory_candidates: true`，默认关闭。配置本身不授权捕获。在已准入、受信任的原生 LOCAL 会话中执行：

```text
/personal-memory-tools enable-read
/personal-memory-tools candidate-on
/personal-memory-tools status
```

候选模式要求**只读**记忆激活。已有写权限时会拒绝开启，必须先明确选择 `enable-read`，避免同一已激活记忆写工具绕过候选审核。模式之外的既有写工具仍遵循原有权限；插件不是无关工具的沙箱。候选选择不延长现有 30 分钟授权。续期、`enable-write`、禁用、到期、已观察到的配置撤销、卸载或重启都会清除选择和捕获源。`candidate-off` 停止新提议，不关闭召回或普通记忆读取，也不删除已有候选，需使用以下审核命令。任务工具激活不能授权捕获。

后续合格轮次中，已有主模型可用 `personal_memory_candidate` 提议有用草稿。普通工具续轮可能产生正常模型费用；没有额外后台/provider 请求，也不保证模型一定提出候选。拿到 ID 后在原生界面审核：

```text
/personal-memory candidate-list --limit 20
/personal-memory candidate-show CANDIDATE_ID
/personal-memory candidate-accept CANDIDATE_ID --expected-revision 1 --keep
/personal-memory candidate-discard OTHER_CANDIDATE_ID --expected-revision 1
/personal-memory candidate-purge-expired
```

把 ID 替换为真实返回的 UUID。接受必须明确选择保留期限：`--keep` 表示正式记忆不设到期时间；也可用 `--expires-at 2030-01-01T00:00:00Z` 指定所需 UTC 截止时间，不会推断默认选择。接受前检查正文、主题和精确引文。错误草稿应丢弃，必要时用显式 `remember` 重写，本切片没有候选编辑命令。候选命令返回可读 Unicode JSON；列表仅返回元数据，show 展示草稿与引文。模型工具不能列出、查看、接受或丢弃候选。停止新候选捕获后，只要 `local_memory` 仍启用，原生审核仍可用。

## 2. 捕获什么，以及不能证明什么

仅当前原始纯文本 `user_message` 合格，最多 8,192 字符。历史、助手/工具输出、多模态载荷以及声称的 sender/UID 字段不作为来源权威。完整输入仅保留在进程内存中，不会整体持久化。清理是尽力而为：缺失 post hook 时，明文可能保留到后续清理或卸载。引文必须按从零开始的 Python 字符偏移精确匹配原文子串，不能用字节偏移。不会模糊匹配、规范化或另寻偏移。

准入绑定实际当前主轮次对象、profile、路由、会话、任务、激活代次和选择。每对象 nonce 防止复用字符串 turn ID 重放其他轮次提议。首次来源摘要和结束锁存跨选择开关保留，但不保留完整输入。缺失或过时 hook 状态会拒绝。轮次后清理是尽力而为，不证明原生提交已持久化；提议始终重查实际活跃轮次。远程、子代理、cron、受管和未绑定上下文继续拒绝。

引文匹配只证明子串存在，不证明作者、事实、认可、忠实转述或许可。被引用的第三方指令不是授权，草稿不能变成操作或权限。模型提示中的避密要求**不是秘密检测器**：启用即允许从后续合格输入中明文保存草稿和引文。不希望保留的材料不要开启此模式。LOCAL 是受信任单用户部署边界，不证明物理本地或新鲜人类身份；所有准入的会话控制者共享该权限。

## 3. 持久化、保留和重试

候选与正式记忆共用私有 `records.sqlite3`，但使用独立 schema-v6 表。待审候选不参与正式 list/search/recall 或记忆变更 checkpoint。每个实际轮次最多三条候选，每个 store 最多保留 1,000 行候选，包括终态元数据。没有静默淘汰或自动容量重置；这是拒绝边界，不是无限可用档案。

每条提议正文最多 2,048 字符、主题 128 字符、引文 1,024 字符，另含作用域元数据和来源摘要。创建七天后到期，不能再接受。**到期不是删除截止保证。** 明文清理在后续成功的候选操作或显式 `candidate-purge-expired` 中提交；失败操作会回滚这次清理。离线 store 可更久保留到期明文。没有后台清理器、安全物理擦除、备份删除或原生历史撤回。接受/丢弃也会清除候选正文、引文、来源摘要和会话引用；最小 ID、哈希、时间戳与重试回执仍有界保留。

接受在同一 SQLite 事务中新增正式记忆并关闭候选，只推进一次正式进度。完全相同的重试返回历史元数据回执，不撤销之后的更正或遗忘，不重建记录。改变保留选择会冲突，不会静默改变早先接受结果。正式来源标签描述最近本地操作员编辑路径，不证明原文作者。已接受记录沿用普通更正、到期、遗忘和召回规则。

经授权的普通记忆命令打开已有自有 store 时，会把 schema v1–v5 原子升级到 v6，保留记录、回执、墓碑和进度。原生只读召回永不迁移；旧版 store 的自动召回在这次明确可写打开前不可用。候选 list/show 也使用可写连接，因为可能清理到期草稿。经授权的候选命令可以初始化缺失的自有 store，但不会为强行访问而接管不安全或外来 store。

## 4. 验证与剩余工作

离线测试使用真实固定宿主的命令准入、主轮次 hook、relay 和模型工具注册，以合成输入运行，不发模型请求。覆盖只读捕获、精确来源/Unicode 偏移、作用域拒绝、撤销、复用 turn ID、结束锁存、接受/遗忘/重载后重试、事务回滚、并发接受、损坏、配额和迁移。

不依赖宿主的 `tests/unit/test_memory_crash_recovery.py` 矩阵在记录/事件/回执写入后、候选关闭后以及事务 COMMIT 前后，通过 `os._exit` 突然终止独立 Python 进程。11 个用例验证 COMMIT 前完整回滚、COMMIT 后持久重放、数据库完整性、只创建一条正式记忆，以及遗忘并重新打开后不会复活。测试使用合成数据和 DELETE 日志，验证 SQLite 进程崩溃恢复，不证明断电持久性、物理擦除、真实 Gateway、provider、文件系统/设备故障或完整 E8 发布认证。可在项目 Python 3.14 环境运行 `python -m pytest tests/unit/test_memory_crash_recovery.py -q` 复现。关联 #21。

这是实用的可选草稿审核流程，不是自动正式记忆提取。真实已配置模型的实用性、来源覆盖 checkpoint、后台保留期限执行、语义/中文召回质量与远程 owner 身份仍待完成。既有 provider 不变。离线契约不需要安装器、被拒 Gateway、真实凭据或宿主补丁；先前安装限制继续有效。
