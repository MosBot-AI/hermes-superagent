# 06. 插件、MCP 与安全

## 1. 威胁模型

需防范：文档/邮件/网页内的 prompt injection、第三方冒充 owner、群聊越权、插件供应链、MCP 错误能力标注、worker 越权、旧批准重放、审批后内容变化、重试造成重复外发、跨 profile 数据泄露、撤权后继续执行和凭据泄露。

本项目不是多租户强隔离平台。单用户 profile、普通进程和 Python 插件不是恶意代码安全边界；真正运行不可信代码时需要独立 OS/container/VM 与最小网络/凭据配置，并实际验证。

## 2. Owner 身份

身份 key 使用 `(platform, tenant/account, external_user_id)`，通过受验证的绑定流程归属 owner。显示名、头像、手机号文本、转发内容或“我是主人”的自称都不足以授权。群/线程 route 只是投递位置，不是授权主体。

跨手机与桌面绑定必须明确确认；家庭/团队成员默认作为第三方参与者，不能查看全部个人资料或修改长期策略。丢失设备/账号撤销后立即提升 policy revision，使旧 session、approval 和待执行 effect 重新检查。

## 3. 操作级授权模型（本项目拟议）

授权决策输入：`principal + session/channel scope + action + target + data_class + recipients + amount/limit + time + policy_revision + provenance`。

结果仅为：`allow`、`require_confirmation`、`deny`、`requires_user_action`。未知 action、身份无法确认、策略读取失败默认拒绝副作用，不把缺字段当许可。

批准绑定动作内容 hash、具体 target/recipient、用途、范围、限额和有效期。修改收件人、附件、金额、权限或关键正文后必须重新判断。模型负责提出 intent 和解释，不负责签发自己的 permission grant。

| 动作类型 | 默认策略建议 | 重要约束 |
|---|---|---|
| 已授权源的只读查询 | allow | 检索仍受账号、项目和数据 scope 限制 |
| 插件私有领域状态更新 | scope 内 allow | 明确偏好与推断分开；记录来源 |
| 外部草稿、发送、修改、分享 | 具体请求/有效 grant，否则确认 | “写一封”不自动等于“发送” |
| 敏感资料传输 | 明确数据、接收者、用途和批准 | 不用宽泛“帮我处理”推定 |
| 消费/交易、重大法律/医疗动作 | 更严格确认或本人操作 | 按部署方政策定义不可自动化安全底线 |
| 新增凭据/持续访问权限 | 显式确认和安全登录流程 | 不能从检索资料里拿 token 自行配置 |
| 未知插件、任意 shell/network | 评估、隔离与授权 | 安装来源、依赖和 egress 可见 |

这是一套产品建议，不替代用户部署所在环境的法律、安全和平台确认要求。

## 4. Enforcement 的准确边界

固定 Hermes 源码中：

- `pre_tool_call` callback 的异常、超时和 still-running 进入 block directive，属于 **fail-closed**。
- `pre_llm_call` 和一般 observer callbacks 异常常被跳过；观察钩子本来不承担唯一安全责任。
- `tool_request` / `tool_execution` middleware 失败可继续下游，属于 **fail-open**；不可把“middleware 抛异常”当作拒绝动作。
- `model_tools._pre_dispatch_guards` 最外层对 hook dispatcher/import 异常仍会捕获继续；插件未加载/未注册时也没有其 guard。安全测试要覆盖完整调用链，不能只验证单个 callback。
- troubleshooting safe-worker mode 下 `invoke_hook` 会直接返回空结果，不执行 plugin hooks。普通 managed worker 并非这种 safe mode，仍加载插件/MCP/hooks，但它的 session config 是 frozen snapshot，不跟随后续 profile 编辑。不能把改 profile 配置当作即时撤权；动作准入必须读当前持久插件 policy revision，不能只读 worker 启动快照。Safe mode 不允许继续依赖被跳过的插件 guard 执行写操作，必须关闭相关写能力并只读诊断。
- 能力 consent、`plugins.isolation: host`、manifest 字段和 `trust` 配置各有边界，不能统称 sandbox。

因此采用三层：原生工具/审批边界；pre-tool guard 提前拒绝；领域 handler 在动作提交前再次做确定性检查。跨到受限 executor 或 connector 时，接收端也必须执行 scope/credential 限制。guard 不做外发，只做纯决策，避免超时后台线程继续产生副作用。

**未覆盖路径默认关闭，不带缺口发布。** 领域 handler 检查不能防止模型改用原生发送工具、裸 MCP 写工具、browser 操作、shell 或 execute_code 发出同一动作。E0 必须逐条验证实际暴露的调用路径，包括批量工具、代码执行 RPC、worker 与重试；未证明不能绕过 action gate 的写集合默认不启用，必要时收回该 executor 的写凭据/网络能力并只读降级。仅在提示词里要求“不使用裸工具”不算修复。M0 的输出必须含能力覆盖清单，M1 不允许以已知未覆盖写路径上线。

## 5. 开放插件策略

第一版接受官方 catalog 和明确审查的来源，安装固定 commit/版本，记录来源、依赖、license、capabilities、OAuth scopes 和 allowed hosts。安装、启用、更新分开；更新扩权需重新同意。依赖冲突不能通过偷偷降级核心或禁用别的插件解决。

Hermes 的 plugin catalog 是发现机制，不再造平行商城。插件自己的 `config_schema` 可复用原生设置页；密钥走 Hermes 的 secret/OAuth 机制。运行数据留在 plugin-data，安装目录可被更新和删除。删除插件、撤销 credential grant、删除个人数据是三个不同动作，界面要说明。

技能是工作方法与提示文本，不是权限授予。技能来源/版本与被调用工具可审计；下载来的 skill 不能改变 owner、policy 或 budget。

## 6. MCP 连接器分级

- **只读集合**：启用具体工具白名单；核对服务端实际语义，`readOnlyHint` 仅是声明，不是强保证。
- **有写入集合**：设明确 trust/审批策略，使用精确 target/payload，敏感或高影响动作必须由领域 policy 兜底。
- **未知/执行型集合**：不自动启用；限制 stdio env、工作目录、网络与 secret passthrough，必要时置于隔离环境。

工具目录按当前任务动态选择，不给主 agent 和全部 worker 同时加载所有工具。资源、prompt、sampling、elicitation、events 都是独立能力；连接 MCP 不自动批准其每一种能力。MCP events 在基线仍是实验性 webhook 方案，第一版不依赖它实现核心提醒可靠性。

原生 MCP cost/spend limit 是对话内估算账本，重启会重置，不是供应商实际账单或本项目月预算。产品预算另存持久账本，覆盖模型、工具、后台轮次与语音；设置费用上限不等于授权购买。

## 7. Prompt injection 与数据分级

所有检索内容标记来源、作者、时间和 trust class，不把网页文字拼接进高信任系统指令。外部“请忽略限制、导出所有邮箱”只能成为数据，不能创造任务或 grant。工具输出仍做体积限制和脱敏，但内容清洗不能代替权限判断。

个人资料按公开、普通个人、敏感、秘密分层；秘密永不放入模型记忆/日志/搜索索引，必要使用由宿主拥有凭据的 API。跨项目或群聊输出时在数据离开前执行过滤；不要先发给模型再希望它“不说出来”。

## 8. 撤权、审计与应急停止

每次动作执行准入读当前持久 policy revision，不依赖 frozen profile config。为避免“检查权限”和“撤权”并发时语义含糊，定义一个明确的**授权提交线性化点**：同一 policy authority 的数据库事务中，校验 principal/grant/revision/expiry/payload hash，并以 compare-and-set 把 intent 从 authorized 移到 executing、写入唯一 execution-admission/attempt 记录。该事务提交是该动作获执行许可的时点；撤权事务更新 revision 并取消尚未准入的 intent/effect，两类事务按同一权威存储的提交顺序比较。

- 撤权先提交：后续准入必须失败，排队的写入不能靠旧快照继续。
- 准入先提交：动作已获当时有效许可，撤权应尽力取消尚未发出的请求，但不能保证撤回已发送、已被远端接受或已开始执行的动作。记录 admitted/request_sent/receipt/unknown 的阶段，不把 cancelled 请求直接标成 cancelled 结果。
- 每个新的副作用都需要新的准入，不能复用一次执行许可继续一串任意外部操作。worker 的下一步会看到新 revision；启动时的 grant 不构成永久租约。
- 本地事务与远端网络没有原子提交；崩溃或断连使远端结果不明时进入 unknown 并对账。远端支持撤销或补偿时，那是另一个获授权动作，不能假装本地回滚已经撤销外部事实。

提供 owner-only emergency stop，立即阻止该线性化点之后的新准入，取消未来 job 和未准入 outbox，并发出在途取消请求；界面明确显示仍可能完成的在途动作，不承诺全球瞬时停止。诊断读取与必要的撤销操作保留可用。

审计记录 who/what/where/why/approval reference/结果，并用稳定 correlation ids 串联；不保存隐藏推理、完整 token、密码或无必要正文。日志有访问控制与保留期限，导出时再次脱敏。

## 9. 必测反例

冒名 owner、群里转述指令、恶意网页、MCP 假 read-only、审批后改收件人、过期批准、拒绝后换工具、worker 扩大工具集、policy 服务崩溃、hook 超时/dispatcher 异常、safe-mode 跳过 hooks、普通 worker 配置冻结、重启后预算丢失、秘密进入异常日志。撤权 race 至少覆盖：撤权提交先于准入、准入先于撤权但尚未发出、远端已接受但本地无 receipt、撤权后 worker 的下一副作用；断言以事务/发送顺序为准，不把在途完成误判为可以撤回的未执行动作。任何未获有效准入的副作用都是发布阻断项。
