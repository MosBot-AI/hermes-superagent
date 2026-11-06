# 05. 主动工作、调度与交付

[English](05-automation-and-delivery.md) | 简体中文

## 1. 主动不是无限自主

主动模块负责发现值得推进的事务，并在用户授权范围内行动。每个 automation 都有目标、数据来源、动作范围、目的地、频率、预算、到期/停止条件。默认是读取、整理和向 owner 报告；给第三方发消息、修改外部系统和消费需要匹配的权限。

后台检查不到有用变化时保持安静。它不能为了证明“在工作”新造任务，也不能因收到外部内容而接受其中的指令。用户的停用、撤权和新消息优先于后台继续执行。

## 2. 三类机制严格分工

| 类型 | 原生机制 | 生命周期 | 例子 |
|---|---|---|---|
| 当前会话内观察 | session `/heartbeat` | 一个 session 一条；只在空闲轮次执行；reset/switch 等边界有明确清理语义 | 看当前 PR 是否结束 |
| 站立式提醒/报告/监控 | Hermes cron | 持久 job、时区、执行账本、结果投递 | 明早九点、每周五简报 |
| 需要持续推进的工作 | Hermes Kanban/goal | 依赖、worker attempt、验收、阻塞与恢复 | 多步骤调研、项目交付 |

不要用一个高频 cron 轮询所有任务，也不要把一个长任务塞进无穷 `/goal`。Heartbeat 保存状态并不意味着在没有存活 CLI/gateway 时仍会运行。安装和服务健康必须可见。

## 3. 建立 automation 的最小记录

`goal`、`trigger_spec`、`timezone`、`source_scope`、`allowed_effects`、`destination_binding`、`quiet_hours`、`priority`、`dedupe_window`、`max_runs/cost`、`expires_at`、`stop_when`、`native_job_id`、`created_from_source`。

相对时间保留创建时刻与解析后的绝对时间；“每天九点”保存当地日历语义和 IANA zone。跨 DST 必须有明确歧义/不存在时间策略，不能只存 UTC offset。用户旅行后，固定时区提醒不自动跟随定位；跟随型需明确模式。

## 4. 可靠执行链

```text
原生触发 + native occurrence/run id
  → 验证 automation 仍有效、未撤权、预算足够
  → 幂等领取领域评估（必要时）
  → 读取增量证据
  → 生成 observation / action proposal
  → 确认是否值得打扰
  → effect / delivery outbox
  → 原生渠道发送或连接器动作
  → receipt / unknown / retryable failure
  → 对账 + stop condition
```

插件的 outbox 只承担其拥有的领域副作用，不能重复接管 Hermes 已有 cron delivery queue。适配器必须选定一个交付责任方：使用 native cron delivery 时以其 receipt 同步；插件自有交付时禁用该 job 的自动重复投递。一次成果不能由两方同时发。

## 5. 幂等与未知结果

- 调度去重 key：`profile + automation_id + native_occurrence_id`，不使用会因重试改变的时间戳。
- 外部动作 key：`intent_id + payload_hash + destination`；接收端有 idempotency key 则传递，并保存 receipt。
- 接收端没有幂等功能时，先查询目标是否已有指定对象/marker。查询不充分则把结果标 unknown，请求必要确认，而不是盲目重发。
- 标记“已入队”“平台接受”“确认投递”“用户已读”是不同状态；很多平台没有 delivery/read receipt，界面必须承认未知。
- 崩溃在“远端成功、本地未提交”之间时，需要 remote reconciliation。事务 outbox 不能提供端到端 exactly-once 保证。

Hermes 已有 cron 执行、occurrence、delivery 等可靠性机制；本项目先测并复用，不重复实现其 tick lock、worker reclaim 和 next_run_at 算法。

## 6. 提醒去重与打扰预算

通知前检查最新源数据、任务是否已完成、最近一次同义通知、用户 quiet hours、目的地权限以及信息有效期。默认优先级：紧急且有明确影响 > 有截止时间的阻塞 > 定时简报 > 建议。频率与配额是可配置产品规则，不写成隐藏魔法值。

先做 rule-based shortlist，再给模型判断内容价值。用户未回复不等于同意继续催促，也不等于永久关闭全部主动功能；只按该 automation 的重复与升级规则处理。过期信息不发送。无变化只写运行账本。

## 7. 用户打断、暂停与撤销

暂停 automation 先更新持久状态和 policy revision，再停止未来触发并取消仍可取消的待执行 intent。已经提交给外部服务的动作无法“撤回历史”，应记录事实、检查能否补偿并如实提示。

运行中的 worker 在每个有副作用的工具准入前检查当前持久授权；不能像只发送一条“权限改了”的通知或修改 profile 快照那样假设它已停止。准入与撤权按 [06 §8](06-plugins-mcp-and-security-zh.md#8-撤权审计与应急停止) 的事务线性化点排序；已经准入的在途请求只能尽力取消，不能保证撤回远端执行。取消是请求状态，只有 worker/外部回执确认后才标 cancelled。手机离线、会话 reset 或旧消息回复不能自动恢复失效授权。

## 8. 故障分类

| 故障 | 处理 |
|---|---|
| 读取临时超时/429 | 有界指数退避，尊重 retry-after，保留 cursor |
| 凭据撤销/权限不足 | 停用对应动作，标 blocked，不换凭据/渠道绕过 |
| 模型失败 | 降级为模板化提醒或保留待处理，不伪造完成结果 |
| policy/approval 服务不可用 | 有副作用动作 fail-closed；只读与普通聊天可降级 |
| 外发超时但可能已成功 | 标 unknown，读回/人工决策后再继续 |
| gateway 重启 | 用原生恢复 + 领域对账，不能重播所有旧通知 |
| 接收者/群变化 | 重新验证 route，敏感内容不自动跟随未知新群 |
| 预算到顶 | 暂停后台，给 owner 一个合并后的可操作提示 |

## 9. 最小可观测性

每次运行串起 `automation_id / native_job_id / native_run_id / intent_id / effect_id / delivery_id`。可查最后成功读取、下次触发、最后通知、停止原因、重试次数和费用估计。日志不存完整个人文档或 token。健康页应区分“调度正常但投递失败”与“从未运行”。
