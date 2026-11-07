# 41. 可选原生记忆召回提供方

[English](41-native-memory-recall.md) | 简体中文

另一条受支持路径：[49](49-session-memory-recall-zh.md)在独立插件内增加另行开启的自动召回，无需安装/选择本 provider。若分别启用，两条路径可能重叠；均不进行提取或 checkpoint-v2。

后续：[45](45-explicit-memory-expiry-zh.md)要求 schema v5，并按每次新召回捕获的 UTC 墙上时钟时间排除已到期记录。只读 provider 永远不迁移。恢复召回前，获准打开存储的命令或已经激活的模型工具操作均可升级自有旧存储；建议操作员使用 /personal-memory list 主动完成升级。评估时间在实际取得 SQLite 快照后采样，而非在等待锁之前。不更改 provider 选择或配置。到期无法撤回已进入原生历史或模型上下文的召回包。

状态：可选的真实 Hermes `MemoryProvider` 已把现有本地记忆存储接入原生 prefetch 和会话生命周期。它对**规范记录只读**，不执行摄取，仍声明 checkpoint API v1。不支持必需的原生 checkpoint-v2。这是经过离线测试的实现，不是真实在线提供方验收或生产启用。

## 1. 显式选择与数据披露

独立插件不会导入、注册、选择或安装此提供方。独立的可选打包声明在真实 `hermes_agent.memory_providers` 入口点组声明 `personal-records = personal_agent.native_memory_provider:register`。每次原生加载创建独立实例。由源码构建的 wheel 包含实现和元数据；加载现有独立插件不会安装此软件包。可使用 `python scripts/build_native_memory_provider.py --output-dir /tmp/personal-provider-wheel` 构建；需要已有的 setuptools，不安装或下载依赖。构建在临时目录中进行，不改变主插件的无安装依赖声明。

安装所有者必须通过其支持的 Hermes 环境流程准入已审阅软件包。不要向 PM 管理的环境直接注入软件包，也不要为启用它而关闭已有隔离。软件包安装和原生提供方选择是两个独立步骤。本切片仅支持显式选择、文件配置、普通进程内运行的 Linux 受信单用户配置。支持原生 CLI／TUI／Desktop 的主会话；拒绝远程消息、cron、子代理、flush、隔离插件主机、受管理 worker 和非文件配置后端。LOCAL／原生标签不证明物理本地性或已验证的人类身份。 宿主检测到任何托管策略 scope 时也会拒绝，即使其中配置为空或格式错误。读取已保存用户配置前后、以及返回召回内容前都会检查 scope；用户层启用不能覆盖托管策略。这与包管理器的 `HERMES_MANAGED` 设置不同。

操作员必须主动把它选入 Hermes 唯一的外部提供方槽位。它不能作为第二个外部提供方并存，也不能在静默保留另一个已选提供方的同时启用。保留其他提供方的用户仍可使用显式个人记忆工具。必须保留其他所有配置，包括已选模型和凭据。此提供方自身不调用模型／API，但召回数据会进入该会话已配置模型的输入，可能影响正常 token 费用和数据留存。

以下为合并配置示例，只能在明确选择和数据共享决定后使用：

```json
{
  "memory": {
    "provider": "personal-records",
    "personal_records": {"recall_enabled": true, "max_chars": 6000, "max_records": 6}
  },
  "plugins": {
    "enabled": ["hermes-personal-agent"],
    "entries": {
      "hermes-personal-agent": {
        "settings": {"mode": "local_tasks", "local_conversation": true, "local_memory": true}
      }
    }
  }
}
```

独立插件必须保持启用和本地记忆设置；它与 `personal-records` 均不能出现在 `plugins.disabled`。每次新召回准入和读取完成后都会重新检查显式启用状态。这是面向支持的主本地会话的配置级自动读取授权，区别于 30 分钟模型工具激活，不产生新的记忆写权限。安装／选择后应重启原生代理；既有实例不会重新绑定到其他配置目录。

## 2. 有界、即时召回

Prefetch 读取当前会话查询，提取最多八个不同的字面文字块，每块最多 128 字符，调用现有有界召回操作。跳过斜杠命令、主机认定的简单寒暄、非法控制字符，以及超过 2,048 字符的查询。文字块区分大小写；中文标点和空格构成边界，但不会对任意中文长句做语义分词。这是确定性的字面检索，不是语义召回质量保证。

每次 prefetch 都独立打开并关闭连接。提供方不保留正文缓存、后台预取结果或会话缓冲。现有排序器选择当前有效记录，并保留修订及编辑路径标签。返回 JSON 明确标注这些内容是不受信的已存证据，不是指令、已核实事实、授权或任务真值。完整返回的 ASCII JSON 受 `max_chars` 限制（2,048–12,000，默认 6,000），记录数受 `max_records` 限制（1–20，默认 6）。超预算时省略完整记录，不截断正文，元数据报告被省略匹配数。没有记录能放入预算、读取不可用或准入失败时，不返回上下文。

**即时召回不等于清除会话历史。** 固定版本主机会把成功的 prefetch 内容写入原生会话 `api_content`，并在之后的模型请求中重放历史 `api_content`。更正、遗忘、禁用、切换会话或移除提供方可以阻止新的不合规召回，却无法删除已经送出或由主机持久保存的上下文。新建会话不会删除旧历史、导出、备份或模型提供方的副本。删除这些目标属于另行授权的工作。不能承诺遗忘一条本地记录后，未来所有提示词都会完全不含曾经送出的文本。

## 3. 会话、配置目录与关闭契约

初始化绑定唯一的主机提供配置目录和非空会话 ID。必须有 `agent_context: primary`，平台必须是 `cli`、`tui` 或 `desktop`；缺失上下文时拒绝。重复初始化被拒绝，包括关闭之后。每次读取时，当前原生配置上下文都必须匹配绑定目录。真实 Hermes manager 还会执行调用方配置校验及单外部提供方限制。

Prefetch 必须提供完全一致的当前会话 ID。原生 `on_session_switch` 只改变会话绑定并清空召回计数。不支持的切换会拒绝后续召回。一把锁协调切换／关闭与已准入的有界读取。关闭是终结状态并释放绑定；没有提供方自建线程、未关闭数据库句柄或写入队列需要排空。主机已排队的后台调用仍可触发无操作 hook，但不能让已关闭实例再次读取。

`sync_turn`、会话结束提取、委派、内置记忆镜像及后台 queue-prefetch 都保持无操作，不复制会话、不创建事实、不推进消费者游标，也不创建元数据检查点。`on_pre_compress` 仍是尽力而为的 v1，不提供持久会话覆盖。要求严格 checkpoint-v2 时，真实原生 manager 仍会报错。本地[元数据检查点](39-local-memory-checkpoints-zh.md)不能替代该保证。

## 4. 规范记录只读存储及边界

读取器使用既有的固定配置目录内路径，执行私有目录／文件检查，以 `mode=ro` 加 `query_only` 打开 SQLite。必须匹配当前精确 schema 和命名空间。缺失存储、旧 schema、不安全路径、已观察到的 sidecar 或 WAL 模式会被拒绝，不创建、不迁移、不修复权限，也不降级绕行。应先通过现有操作员流程初始化／升级记忆，再进行原生召回。此读取器不提供规范写操作或写能力。

支持的存储使用 SQLite 回滚日志。读取器在打开前检查文件头，并在数据库读事务内、读取记录之前重新检查日志模式。无关进程可能在初步检查后把数据库切到 WAL，形成竞争。即使使用 `mode=ro`，SQLite 也可能在后续拒绝之前创建或更新 WAL／共享内存 sidecar。因此这是**规范记录只读契约，不是针对无关同 UID 代码的严格文件系统／VFS 沙箱**。插件不会为掩盖竞争而删除这些 sidecar。不要在外部改变运行中存储的日志模式。

正常更正／遗忘由 SQLite 读取快照排序。已准入并返回的上下文，在读事务结束后可能立即变为历史。写入竞争或发现日志时，召回可能暂时被抑制，而不是退回陈旧缓存。这不保护其他原生工具、不证明记录正确，也没有解决从旧数据库备份恢复的问题。

## 5. 验证与剩余工作

合成单元测试覆盖启用／禁用／撤回、配置目录／会话不匹配、非主上下文拒绝、关闭、字符预算、字面查询、注入内容仅作为数据、更正／遗忘后的新鲜读取、只读操作拒绝、缺失存储、不安全文件、旧 schema 及外部 WAL 切换竞争。原生契约使用真实入口点加载器和 `MemoryManager`，仅提供合成入口点清单，验证独立实例、外部提供方槽位、prefetch／sync／switch／shutdown、配置目录拒绝、规范数据库及配置不变，以及严格检查点失败。另行验证本地构建的 wheel，不会安装进实际运行的 Hermes 环境。

没有使用真实 LLM、个人数据、Gateway 监听器、凭据、生产配置或远程写入。自动摄取、会话证据检查点、提供方设置界面、隔离／受管理兼容、中文语义召回评测及经过授权的在线验收仍待完成。所有真实提供方验收都必须保留用户已选模型／提供方，不能静默替换。

固定版本源码证据：[提供方 ABC](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_provider.py)、[加载器](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/plugins/memory/__init__.py)、[manager 与检查点门禁](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/memory_manager.py)、[prefetch 持久化及重放](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/agent/turn_context.py#L1030-L1072)。
