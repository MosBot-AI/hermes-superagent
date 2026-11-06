# 仅供评审的宿主命令上下文实验

[English](README.md) | 简体中文

## 状态与来源

本目录封装已有本地上游原型供评审，**不由本项目安装、应用、发布为运行能力或启用**。正式兼容性基线及生产插件不变，受保护读取继续关闭。在项目功能分支分发补丁不代表上游投稿、PR、部署或合并。

- 官方来源：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。
- 基线：`90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。
- 本地原型提交：`adfb1feb207943d2bb539555adcbb667bcb571ab`；tree：`2eed0582216b9bdec676ac9787f8a7cb724dbe54`；分支：`prototype/verified-command-context`。
- 本地提交仅为来源标识，不是已公开的提交链接；原型没有配置远端。
- 精确九文件[补丁](command-context-prototype.patch)，SHA-256：`ab47d5f7c25c4cbc007332cb05e4f5dbf146ba701ef90cd77e09df10a5af1f20`。
- 上游衍生代码保留 [Hermes MIT 许可证](LICENSE.hermes-agent)。

[manifest.json](manifest.json) 记录来源、补丁与证据哈希、文件清单、历史结果、局限及后续门槛。[verification.json](verification.json) 和 [installed-packages.json](installed-packages.json) 保留原始历史结构化记录。前者的项目提交及状态仅描述当时快照，不是本功能分支当前状态。原始完整日志含机器路径，未随本包分发；结构化记录不等于可独立复现的完整日志。

## 原型观察什么

现有 Telegram 即时命令入口在既有门禁之后捕获人类直接私聊。短期回执绑定原始事件，不依赖可序列化的 SessionSource 标志；固定接收方数字 Bot 账户、适配器代次、用户、原始命令、原生路由身份及已经存在的匹配活动会话。不支持的、转发、编辑、机器人、变换、批处理或恢复事件不符合条件；变化或取消的事件默认拒绝。

原生命令分派提供可选且经签名参数筛选的 `command_context`；一次性 `consume()` 返回带版本的宿主传输观察或空值，作用域结束回收句柄。托管插件经现有 pipe 接收宿主持有的随机 ticket，消费时检查调用生命周期和宿主代次。普通 JSON、Record 恢复、插件名称或 RPC 关联来源不能铸造 ticket。新增诊断避免记录身份字符串或包含 token 的 SDK URL。

这**不是 owner 登记、owner 授权、Primary Bot 身份绑定或完整授权**。接收 Bot 账户观察不等于规范的 Primary Bot 发现；活动会话不证明 owner 身份。已消费字典是可复制的数据，不能作为权威重新接收。不开放私有读取、原生 turn、外部操作或权限。

## 历史证据与局限

历史新增契约测试通过 70 项（生产者/观察 35 项，回调/IPC 35 项）。扩展选择为 **146 通过、9 项在环境初始化阶段失败**：临时 gateway 控制 socket 绑定返回 `EPERM` / `Operation not permitted`，未到达验收断言。历史上获准复跑一次同样失败；这些测试没有被跳过、计为通过或解决。

涉及 `tests/gateway/test_cli_plugin_command_in_gateway.py`（六项）、`tests/gateway/test_cli_plugin_command_own_socket.py`（两项）及 `tests/gateway/test_plugin_command_choice.py`（一项失败，另一项通过）。因此不是全绿结果。历史 14 项上游静态检查及干净基线补丁应用检查通过。本次封装不复跑任何上游或身份/socket 测试。

测试使用合成入口，覆盖原生生产者 → gateway handler → 真实托管子进程；未验证真实 Telegram 账户、polling/webhook、网络/TLS 认证、设备或远端 CI。使用 Python 3.14.9 和观察到的 88 包 PM 环境，指纹不是与锁文件完全等价的证明。评审无需 API Key，密钥也不能解决 socket 限制。

## 后续设计与集成门槛

1. 采用上游支持的**仅命令调用**上下文接口。原型在通用 callable proxy 拦截 `command_context`，自定义 hook 同名参数可能导致托管与进程内行为差异；采用前必须消除冲突并验证兼容性。
2. 增加单调递增的 policy、路由、连接、会话 revision 防护。当前快照相等不能检测 A→B→A（ABA）历史变化，也不能消除撤销与操作竞态。一次性消费不是原子的权限到操作准入事务。
3. 显式设计首次会话登记：尚无原生会话的首次命令得不到观察，不得以调用者自报身份或恢复标志替代。
4. 完成规范 Primary Bot 发现/绑定、明确 owner 登记和持久化 grant；每次受保护读取/操作准入须原子检查当前 owner、policy、grant、session 及 worker 来源，并支持撤销与恢复。
5. 评审同 UID/共享进程信任假设：它不是 Python 沙箱，不隔离同一宿主内互不信任插件，也不抵御恶意同用户 OS 进程。官方 SDK endpoint 配置不等于独立网络证明。
6. 另行评审并授权合适环境处理九项受限 socket 测试，不能自动重试。再经授权安全配置验证真实入口与诊断，补齐生命周期、重放、取消、重启及发布评审。

只推进 E0.7 可行性证据，不完成 E0.7、E1、Primary Bot 绑定或任何私有读取发布门槛。参见[集成记录](../../docs/23-host-command-context-experiment-zh.md)。

## 仅离线评审与 apply-check

本包刻意**不提供可执行测试 runner**。项目静态制品测试只检查文件与哈希，不导入或执行补丁；不得把历史测试选择复制进自动重试流程。

自行准备可信、一次性、无凭据且位于精确基线的 Hermes Git 副本。不要使用已安装实例、生产 profile、本项目或正式干净兼容性 checkout。先评审补丁，再执行：

```bash
set -eu
ARTIFACT="/path/to/hermes-superagent/experiments/command-context"
COPY="/path/to/disposable-hermes"
test "$(git -C "$COPY" rev-parse HEAD)" = 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
test -z "$(git -C "$COPY" status --porcelain)"
printf '%s  %s\n' ab47d5f7c25c4cbc007332cb05e4f5dbf146ba701ef90cd77e09df10a5af1f20 "$ARTIFACT/command-context-prototype.patch" | sha256sum --check -
git -C "$COPY" apply --check "$ARTIFACT/command-context-prototype.patch"
```

任一门禁失败即停止。这些命令不应用补丁、不执行上游代码，也不认证被忽略内容或隐藏的 index 修改，必须使用新的可信副本。apply-check 只证明补丁可应用，不证明行为或安全。应用及运行测试须另有经评审的计划。不要将修改后的 checkout 交给常规项目 checker，也不要削弱正式基线、源码洁净度及不支持该上下文的现有预期。
