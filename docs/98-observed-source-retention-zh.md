# 98. 显式保留观察来源

[English](98-observed-source-retention.md) | 简体中文

## 已实现的边界

[Issue #137](https://github.com/MosBot-AI/hermes-superagent/issues/137) 通过显式 LOCAL 命令，将[原生来源审阅工作台](97-native-source-workbench-zh.md)连接到[规范保留来源接受](96-retained-source-acceptance-zh.md)。实现使用 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 的公开 SessionDB 读取 API，无需宿主补丁。这是已实现的生产包代码，不代表已安装、部署或通过真实个人数据验收。

仍须满足既有的 `mode: local_tasks`、`local_conversation: true`、`local_memory: true`、已准入配置档和准确的当前 Gateway 支持的 LOCAL 会话门禁。不提供自动摄取、模型工具入口、提供方启用、checkpoint-v2 或 HTTP/API 契约变更。原生文本仍是不可信证据，不是许可或经过验证的作者身份。命令不能选择其他配置档、数据库路径或会话。

## 审阅、预览与显式保留

先按文档 97 使用 `source-list` 和 `source-show`。选择一条合格原始行，然后自行指定消费者、预期已完成序号及请求键：

```text
/personal-memory source-preview UID --expected-snapshot HASH --consumer-id reviewed --expected-sequence 0 --request-id retain-001 --retention independent_snapshot --keep
/personal-memory source-retain UID --expected-snapshot HASH --consumer-id reviewed --expected-sequence 0 --request-id retain-001 --retention independent_snapshot --keep --expected-digest DIGEST
```

将 `UID` 和 `HASH` 替换为已审阅的选择，将 `DIGEST` 替换为预览的 `query.expected_digest`。序号 `0` 仅适用于尚无已完成决定的新消费者。对于已有消费者，应先检查其游标。消费者 ID 使用小写，以字母开头，最多 64 个字符，可包含字母、数字、`_`、`.` 和 `-`。请求键包含 1–128 个 ASCII 字母、数字、`_`、`.` 或 `-`。不要生成新键来绕过不确定结果。

两个命令都要求 `--retention independent_snapshot`，并且必须在 `--keep` 与 `--expires-at UTC` 中恰好选择一个。`--keep` 显式选择规范记录无到期时间；也可使用有效 UTC 时间戳，例如 `2030-01-01T00:00:00Z`。可选的 `--topic LABEL` 属于已审阅请求的一部分。从预览到保留应保持全部参数相同，仅添加 `--expected-digest`。支持既有的 `/personal-memory --json ...` 形式。

预览返回完整规范 `payload`，包含精确来源内容、主题、来源标记和保留策略，以及不含载荷的 `query`，其中包括请求 ID 和规范化摘要。它还报告选择元数据、吸收 UID、`canonical_admission: false` 和 `automatic_ingestion: false`。尝试保留前应保存 query。预览读取原生数据，但不打开规范存储，也不预留待决槽位；它不保证之后能通过规范准入。

保留会重新读取相同的预期原生观察，在该快照内取得真实宿主 `store_instance_id`，验证完整请求，并在暂存前检查规范化摘要。摘要变化返回 `source_preview_changed`；观察变化返回 `source_snapshot_changed`。应重新列出并审阅，不要盲目替换摘要。检查通过后，保留通过既有显式本地操作者写入路径暂存并接受。规范接受以事务方式创建一条记录、事件和回执，并完成一个来源序号；重试不会创建第二条记录或重复推进。

规范内容必须不超过 2,048 字符，并符合支持的文本控制字符要求；主题最多 128 字符。超限或包含不支持字符的文本会被拒绝，绝不截断或总结。一条行可能适合只读查看，却不符合保留要求。工作台独立的整次观察上限及排除规则仍然适用。

## 如实的来源标记与 schema 兼容性

观察导入使用 `kind: observed_native_snapshot` 和 `observation_id`，绝不伪造 `receipt_id`。它保留原始角色、精确 UTF-8 内容指纹和来源身份。来源身份对带标记的元组 `native_original_v1`、真实宿主存储 UUID、原生会话 ID 和原始消息 UID 计算哈希。观察 ID 绑定已审阅快照与该 UUID。宿主身份缺失或畸形时，捕获会返回 `source_store_identity_unavailable`；读取器不会创建或修复该身份。

观察摘要仍绑定配置档路径/文件系统绑定及原生 revision/行。因此，即使 UUID 不变，移动或复制存储也可能使此前审阅的观察失效。UUID 派生的来源身份可以在完整移动/复制后保持一致；它表示来源连续性，不提供克隆隔离、经过验证的所有权或权限。共享 UUID 的数据库副本不会仅因路径变化而变为独立来源。

当早期回执实验的调用方实际使用了同一宿主 UUID 时，其身份公式与此一致。任意旧可信调用方身份不会被重新映射或宣称等价。精确指纹抑制仍跨当前输入、旧回执和观察来源路径生效，受已记录的精确匹配限制约束。

可写 schema-13 迁移增加带类型的观察来源，同时保留每一条 schema-12 决定的回执来源、请求摘要、历史输出和抑制状态。旧 `retained_native_snapshot` 来源保留其 `receipt_id` 和原请求格式。新观察来源改用 `observation_id`。不会虚构原生回执或静默重写历史导入身份。只读状态/游标绝不迁移旧存储；需要迁移时，应使用明确授权的可写路径。

## 状态、待决恢复与丢弃

```text
/personal-memory source-status retain-001 --expected-digest DIGEST
/personal-memory source-cursor --consumer-id reviewed
/personal-memory source-discard retain-001 --expected-digest DIGEST
```

状态和游标仅以只读方式读取已有规范存储的元数据。它们绝不重新打开原生文本、载入规范载荷、创建存储、迁移或修复存储。规范存储缺失会报告 `memory_store_missing`，不会返回空的成功结果。状态分别报告已保存决定和当前记录元数据；历史接受回执不保证当前记录仍活动、未修改或未到期。元数据和指纹仍需私密处理。

每个消费者最多有一个未解决的待决槽位。暂存只保存元数据和摘要，不保存来源内容、主题或会话标签。待决槽位不会推进已完成游标，也不会自动到期。原生删除或丢失若阻止之后的保留，该槽位仍可通过状态/游标查看，并可使用已保存的精确键/摘要显式丢弃。丢弃不读取原生文本、不创建规范记录，只解决匹配的待决决定。它推进该消费者的来源游标并抑制精确来源指纹；不会撤销已接受记录。后者应使用规范遗忘操作。

提交结果未知后，重试前应检查原始键/摘要。即使原生来源不可用，也可核实已接受决定。重放原生保留命令仍会重新读取已审阅来源，因此原始观察消失后，即便规范提交已成功，重放仍可能失败。状态是恢复路径，不是原生来源仍存在的证明。决定缺失仅表示在所检查快照中缺失；较早的写入仍可能随后提交。不能因此推断可以安全地更换键或越过未解决的尝试。

## 独立生命周期与抑制

显式授权、且已由保留操作捕获的独立快照，可以在读取后原生文本消失的情况下被接受。不提供规范提交时原生来源仍有效的保证，也不提供跨存储原子事务。原生删除不会遗忘规范记忆；规范遗忘也不会擦除原生行、备份、导出、客户端历史或此前返回的上下文。

规范更正/遗忘和保留来源丢弃会跨路径执行既有精确来源/指纹抑制。新的请求键、消费者 ID 或观察不能复活同一被抑制来源。这不是语义擦除，也不能检测所有改写。历史接受结果仍仅是历史，不会恢复已遗忘载荷。文档 96 的既有决定/消费者上限、待决槽位语义和规范写入锁仍然适用。

## 验证与剩余门禁

运行仓库与文档检查：

```sh
python scripts/check.py
python scripts/check_docs.py
git diff --check
```

使用隔离临时 home 和合成来源运行独立固定宿主测试集：

```sh
python scripts/check.py --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

准确的检出/解释器前置条件见[开发验证设置](../README-zh.md#开发验证)。审查命令解析、完整预览与摘要绑定、真实 SessionDB UUID/快照读取、仅创建一条记录的重试、schema 迁移、原生存储不可用时的仅元数据恢复、待决来源丢失/丢弃、未知结果、跨路径抑制、畸形/超限文本、来源门禁和只读行为。PR 中实际执行的检查、准确修订和独立审查才是证据；本文不固化临时测试数量，也不声称已通过完整生命周期、生产或模型验收。自动来源选择、更广原生覆盖和完整记忆路线图验收仍是独立工作。
