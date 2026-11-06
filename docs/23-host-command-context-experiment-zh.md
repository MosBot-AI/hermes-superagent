# 23. 宿主命令上下文实验

[English](23-host-command-context-experiment.md) | 简体中文

## 决策

将既有原生命令来源原型封装为[仅供评审的实验](../experiments/command-context/README-zh.md)，不作为插件能力。精确补丁、Hermes MIT 许可证、机器可读来源/哈希清单及历史证据一起版本化。不附可执行 runner，常规安装及检查不得应用或执行它。

正式兼容性基线仍为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。修订后的本地原型提交 `b93642ca32739d4426293603e66175a72582de98` 只表示来源，不是上游发布或公开提交。不启用私有读取、owner 授权、账户访问、Primary Bot 绑定或外部操作。

## 证据边界

原生 Telegram 即时人类私聊路径生成绑定原始事件的短期回执，再提供一次性上下文。托管消费者通过现有 pipe 使用宿主持有的 ticket。这展示的是宿主传输观察接口，**不是 owner 身份或授权**。接收 Bot ID 观察不等于规范的 Primary Bot 发现；恢复的 JSON/Record 不能替代活动句柄，消费后的字典只是数据。

历史结果为 **新增 70 项通过；总计 146 通过、9 项 socket 初始化因 EPERM 失败**。九项未到达验收断言，历史获准复跑仍失败。14 项上游静态检查通过。这些仍是历史结构化记录，不是上游全绿认证。真实 Telegram 入口、网络认证、真实账户及远端 CI 尚未验证。

## 仅命令调用修订证据

原始 `adfb1feb207943d2bb539555adcbb667bcb571ab` 回执单独保留。修订补丁仅选择原生 `register_command` 绑定的精确 handler，使用专用 `invoke_command` 操作；通用 callable 保留普通 `command_context` 数据，不能导入观察描述符。没有新增 issue/export RPC。这解决的是原型兼容缺陷，不是 owner 授权阻断。

另行审计、禁止 socket 的运行通过 **87 项测试**（生产者 35、原 host 35、新回归 17），以及全部 **14 项静态检查**。保留生产 launcher/入口选择，仅以临时测试 sitecustomize 阻断子进程联网，并验证 guard 标记及不同 PID。这些测试与历史结果重叠，不能相加。九项受限 socket 用例没有运行，真实入口与完整上游验收仍未验证。子进程 ref 表保留原有协作宿主信任假设。

## 集成之前的门槛

- 采用受支持的公共仅命令调用接口。本地修复现将 `command_context` 处理限制到精确注册的命令 handler，通用 hook/工具关键字兼容性已测试，但不代表上游接受或逐插件认证。
- 提供单调 policy/路由/session/连接 revision 防护，包括 ABA 变化；读取/操作准入必须原子绑定权限，不能只依赖快照相等。
- 设计首次会话登记：原型要求已存在的匹配活动原生会话，不会引导 owner 身份建立。
- 完成规范 Primary Bot 发现/绑定、明确 owner 登记、当前持久化 policy/grant 检查、worker 来源、撤销与恢复。
- 评审同 UID 和共享进程信任：该接口不能隔离进程内 Python 或同一托管进程中的互不信任插件。
- 另行授权适合处理九项未解决 socket 测试的环境，不能自动重试；发布评审前通过安全配置验证真实入口和保护隐私的诊断。

实验 README 提供中英文设计细节，以及在独立准备的一次性副本中非修改性的 `git apply --check` 指引。项目静态制品测试检查清单、哈希、历史分类、许可证及无可执行 runner，不执行上游代码。评审无需 API Key，密钥也不能解决 socket 限制。

这里只推进 E0.7 可行性证据。E0.7、E1 及受保护读取发布门槛仍未完成。独立的[语音实验](../experiments/voice-ipc/README-zh.md)不补足身份/授权保证；未经集成评审，不要组合两个补丁或将其视为生产支持。

## 最小有门禁端到端路径

首个有价值的受保护操作可以是在已验证 owner 私聊中回复有界任务摘要，无需调用模型、运行 worker、注入 canonical turn 或合并 transcript。下面是拟议顺序，不是已启用流程：

1. 选择明确的 bootstrap 授权来源。一种可行设计是由受信任部署操作者预设精确的待激活外部 issuer/actor/接收账号白名单，附带范围、revision 和审计回执。使用前需要明确设计/部署决定；本地 UID、profile 名称或首位发信人不是经过认证的 owner 证明。待激活记录不能签发真实上下文或 grant。
2. 独立取得当前原生入口证明，包含单调 route/connection/session fencing 及 host-instance 生命周期。如果先通过正常设置建立 DM session，应验证 session 确实存在，再要求新的受保护命令。不得输出私人数据或用第一条消息自行注册 owner。复制的观察字典永远不是证明。
3. 将真实 actor 与事先获授权的待激活映射匹配，再在当前 revision 下确认绑定 actor/receiver/session/scope 的短期 challenge。精确到 session 的 grant 不得静默转移给替换后的会话。
4. 另行通过受支持的 registry/route adapter 解析并确认已有 Hermes canonical Bot。Telegram 接收账号 ID 不是 canonical Bot 身份。DM 仍为 `owner_entry`，不会变成 canonical transcript。
5. 显式预览并接管准备暴露的任务集合。当前本地任务没有 `owner_id` 列或远端 grant 关联，新注册不能静默获得全部已有本地记录。应使用 owner 范围资源，或严格执行的单 owner authority/store，并制定迁移和恢复规则。
6. 实现单一明确的授权读取准入：消费真实 host 证明，使 host 失效和数据库撤权与准入有确定顺序，加载当前持久化 enrollment/binding/grant，在一致的资源/策略快照中仅读取有界 `tasks.summary` 投影。简单地把 `evaluate_read()` 包在 `TaskStore.run("list", ...)` 外面并不原子：当前 store 自己管理事务，host 状态则位于别处。准入前提交的撤权必须拒绝；已准入的读取可以完成，已交给传输层的回复也不能被追溯撤回。
7. 验证恢复/克隆 fencing 及受支持部署。恢复数据库中的旧 epoch 不能证明自身新鲜度；没有外部 authority 时并发克隆保持禁用。仅在另行获授权的合适环境中解决九项受限测试，然后通过真实安全入口与安全诊断验证，才能激活。

不受限的准备工作可以实现待激活 enrollment 存储、带版本策略和禁用 adapter 后面的准入契约，但不能伪造远端授权。之后部署需要选定唯一权威 Bot/profile、精确外部 owner/receiver 对、显式接管的任务集及安全原生账号连接。本补丁没有做出这些部署选择、配置凭据或授予权限。Provider API key 不能解决身份缺口或 socket 限制。
