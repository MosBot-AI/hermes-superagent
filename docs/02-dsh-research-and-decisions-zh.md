# 02. DSH Superagent：源码、报道与设计取舍

[English](02-dsh-research-and-decisions.md) | 简体中文

## 1. 研究对象与证据强度

本次研究对象是官方组织下的 [deepseek-ai/dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype)，固定提交 [8c32a9dc5d72c033816c6a8110b37f40cf94fba4](https://github.com/deepseek-ai/dsh-superagent-prototype/commit/8c32a9dc5d72c033816c6a8110b37f40cf94fba4)，提交时间 2026-10-31T12:06:31Z。本次查询到的公开 commit 只有这一条，releases 返回空数组；未验证 tag 列表，不能据此断言没有 tags。

README 明确说明它是研究原型，不是正式 DeepSeek 产品；公开版本经过改编，与内部版本和设计文章不完全一致，文章中的部分方向未实现。本文把“源码中可见”“文章提出”“本项目建议”分开，不把热度和媒体判断当作稳定性证据。[README](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/README.md)

package 版本 0.1.0，TypeScript ESM，依赖 DSH/Cordis interfaces；它不是把 executor 换成 Hermes 就能直接成为原生插件的独立库。复用代码时须保留 MIT notice；本方案优先借鉴领域设计，不整体移植 runtime。[package.json](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/package.json)、[LICENSE](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/LICENSE)

## 2. DSH 实际解决的问题

它主要协调团队围绕一个代码仓库产生的工作，而不是完整个人助理。核心链路是 `Source → Trigger → Thread → Eval → Mandate → Ticket → Assignment → Executor`，Channel 承担回复写侧。Trigger 是去重事件，Thread 是串行评估/讨论单元，Ticket 是授权工作单元，Assignment 是一次执行绑定，Mandate 是不可变授权快照。任务不随着一次模型 session 结束而消失。[领域模型](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/001-domain.md#L25-L60)、[Engine](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/engine.ts)

这对 Hermes 的最有价值启发是：**任务、证据、授权、执行尝试与消息交付必须是可恢复的对象，而不只是一段聊天上下文。** 但 Hermes 已有 Kanban、cron、session 等底座，因此应补领域映射，不照搬 DSH 的第二套执行系统。

## 3. 值得直接学习的机制

### 3.1 确定性准入在前，模型语义判断在后

Policy 先依据可信 actor、bot 标记、直接寻址、范围和规则，区分 explicit/inferred/inadmissible。inferred 接单需 auto 模式并匹配 enabled rule；默认 observe 只记录 would_accept。规则、mode 和 Source policy 形成版本 hash，过期评估不能继续提交。模型不应自行决定“我是否有权限”。[policy.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/policy.ts#L111-L242)

**采用方式**：Personal-agent 有 IntakeGate 和 ActionGate 两道门。前者决定事件是否成为候选事务，后者决定每一次具体副作用是否获准。先 observe，再逐类启用有限自动行为。

### 3.2 后续事件直达已拥有它的任务

Subscription 允许同 Thread 后续消息直达 worker，而不每条都经过 Router LLM。context-only subscription 只提供上下文，不授予新请求权，也不能唤醒已结束任务；越界事件 hand back 后再做新评估。[intake.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/intake.ts)、[授权文档](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/002-authorization.md)

**采用方式**：以 source/thread/task 的显式关联减少重复建任务；关联只提供上下文。owner follow-up 可在授权仍有效时继续，第三方 follow-up 只能提供证据或触发已经获准的条件，不能扩大 grant。

### 3.3 事务写状态，持久 effect 执行外部动作

Core 是同步、无 I/O 的领域引擎，状态与 effect 入队同事务。SQLite WAL、单进程状态目录锁、effect kind/key 去重和 generation 防止旧 attempt 删除新 payload。Later 与故障分开，前者不增加失败计数。[Store](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/store.ts#L50-L160)、[Effects](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/effects.ts#L60-L145)

**采用方式**：插件自有领域状态与自有副作用 outbox 同事务；Hermes 已拥有的 cron、Kanban、delivery 路径直接复用，不能出现双 dispatcher 或双发送方。

### 3.4 回复是业务对象

DSH 区分 acknowledgement、answer、result、attention，结果回任务起点，回答回被问消息。Outbox 保存 receipt，GitHub 评论使用稳定 marker 检查，飞书使用 message.id 幂等。永久不可达标 dropped，不能把“已入队”当“已发出”。[Replies](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/replies.ts)、[Outbox](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/outbox.ts)、[GitHub channel](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/sources/github-channel.ts)、[Feishu channel](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/sources/feishu-channel.ts)

**采用方式**：question、approval、blocked、result、delivery_failed 和 unknown outcome 分开。把“为什么需要你”“接下来怎么办”呈现给人，完整 trace 留在可查审计中。

### 3.5 把人的注意力放在吞吐前

原型默认 maxWorkers=3，并为人的 follow-up/status 留出额外 slot；后台作业和子 agent 仍占用真实运行容量，不假装 idle。执行器有前台转后台、有界等待、清理和恢复规则。[执行文档](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/003-execution.md#L23-L61)

**采用方式**：少量 worker、前台预留容量、用户打断优先、真实 backpressure。数字是原型选择，不照搬为 Hermes 性能承诺。

### 3.6 有引用的上下文，不是无限 prompt

Cards 传摘要和可展开资源；资源读取限定在当前 Ticket/Thread 的相关对象，并有分页/文本上限。可见 ID 应能够解析到来源。但资源 API 限制不等于 OS 隔离。[资源接口](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/007-architecture.md#L534-L595)、[resources.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/resources.ts)

**采用方式**：项目摘要、来源和 artifact 引用图按需展开；长期用户事实由 Hermes 记忆与领域事实库管理，不把任务历史都塞入 USER.md。

## 4. 必须改变的安全和产品假设

| 原型边界 | 事实与风险 | Hermes personal-agent 决策 |
|---|---|---|
| Mandate | 有准入/恢复校验、worker 工具 allowlist、Ticket ended guard；自由文本 scope 不是每条命令/外发的确定性校验 | 增加操作级授权、payload/recipient 绑定和执行前重验 |
| 执行环境 | session 设 `danger-full-access`；同 OS 用户；CLI wrappers 不隔离文件与网络 | 个人敏感数据和凭据最小暴露，不可信执行进入验证过的隔离环境 |
| 身份 | 不建跨 Source identity mapping | 最小 Owner + VerifiedAccountBinding，显示名不授权 |
| 恢复 | 原线程 human 后续可尝试恢复 ended Ticket，scope 判断依赖 worker | 第三方消息不能自动恢复外部操作权限 |
| 策略变化 | 通知 live Ticket，不立即 revoke；pause 不必打断当前 turn | soft pause 与硬撤权分开，动作提交前检查最新 policy revision |
| 幂等 | 回复 outbox 有机制，不代表 worker 自由 shell 的全部动作 exactly-once | 每类 effect 定义 idempotency/receipt/unknown/reconcile |
| 项目假设 | 仍有 GitHub/飞书/PR 特定依赖 | 统一 artifact/receipt/result，不让个人事务伪装成 PR |
| 记忆 | `core/memory.ts` 是测试用 InMemoryRepositories，不是个人长期记忆 | 复用 Hermes memory，补 provenance、纠错、遗忘、scope |

执行环境证据：[sessions.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/app/sessions.ts#L137-L154)、[部署权限](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/006-deployment.md#L13-L19)、[mandateInstructions](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/executor/dsh.ts#L88-L95)。身份/恢复见[领域模型](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/001-domain.md#L39-L59)与[授权文档](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/002-authorization.md)。撤权见[policyEffects/revalidate](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/policy.ts#L144-L241)。其他边界见[恢复规则](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/003-execution.md#L144-L152)、[Source 特定依赖](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/007-architecture.md#L275-L287)、[core/memory.ts](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/src/core/memory.ts)。

这些是把研究原型迁到个人数据场景时的设计差异，不是未经运行验证的漏洞利用结论。

## 5. 文章与新闻核对

- 官方中文文章入口为[微信公众号文章](https://mp.weixin.qq.com/s/zoS7GlReWPhfCjENGxXCdg)，本次无法读取正文；[DeepSeek Harness X 入口](https://x.com/DeepSeekHarness/status/2116857257245987236)返回 403，没有绕过访问限制。
- 可读的署名转载为 [ChainCatcher](https://www.chaincatcher.com/article/2300676)。它呈现 Router/Worker、Inline/Spill、多跳回忆、异步交互、compute/state/environment 分离和独立 Watchdog 等设计讨论。转载不是官方站点；实现判断仍以固定源码为准。
- [The Next Web，2026-11-01](https://thenextweb.com/news/deepseek-super-agent-open-source-coding-agent)报道实验性、单仓库、可选飞书和减少协调负担，同时说明不是正式产品。
- [South China Morning Post，2026-11-01](https://www.scmp.com/tech/article/3372884/deepseek-unveils-ai-super-agent-coding-race-openai-anthropic)的可读部分描述其减少人工协调多 agent 的目标；未从不可读正文推断技术细节。

文章的调度实验包含合成消息和耗时 mock 工具，不能当作真实 coding quality、个人助手效果或安全基准，也不能证明“多 agent 天然更便宜”。原型确有 startup recovery、health 和每小时独立 profile 检查服务的部署指导，不能笼统说“没有 watchdog”；但尚未证明文章描绘的通用语义 Watchdog、多环境无状态 compute/端侧 daemon 全套架构都已落地。[部署检查](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/docs/006-deployment.md#L133-L141)

## 6. 最终决策

学习 DSH 的任务/执行分离、事件直通、事务 effect、结构化 attention 和引用上下文；在 Hermes 原生底座上补个人领域、owner 身份、操作级授权、立即撤权、记忆治理与通知预算。第一阶段完成单机可靠闭环，不移植 DSH/Cordis runtime，不复制它的 full-access 单仓团队部署假设。

本次为源码与文献审阅，未运行 DSH 或 Hermes 测试。DSH 的[测试目录](https://github.com/deepseek-ai/dsh-superagent-prototype/tree/8c32a9dc5d72c033816c6a8110b37f40cf94fba4/tests)可供用例组织参考，不作为本项目测试已通过的证据。
