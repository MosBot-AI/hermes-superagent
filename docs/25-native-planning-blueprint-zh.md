# 25. 原生个人计划 Blueprint

[English](25-native-planning-blueprint.md) | 简体中文

**已实现原生模板集成，不是受控提醒投递或主 Bot 授权。** 显式启用的计划模板会出现在 Hermes 现有 Automation Blueprint 目录中，用户通过原生 `/blueprint`、Desktop Cron 或 dashboard 流程配置。不增加新的 personal-agent CLI 命令、调度器或 agent loop。

插件仅注册静态模板。注册时不会创建 cron job、读取本地收件箱、访问账户、选择模型、获取凭据或调用 provider。测试使用合成 profile，不启动真实计划任务。Hermes 仍固定为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。

## 1. 显式启用

在现有插件条目中增加此设置，保留其他设置与插件：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: read_only
        planning_blueprint: true
```

`planning_blueprint` 默认为 `false`，必须是真正的布尔值，不能是字符串、整数或 null。无效值会拒绝插件注册。它独立于 `mode`：无需启用本地任务存储即可注册模板。已有 `local_tasks` 用户可保留该模式。修改模板配置后，应使用宿主支持的生命周期操作重新加载插件/profile；单独编辑配置文件不是即时撤权机制。

注册后目录键为 `hermes-personal-agent:planning-check-in`，标题为 **Personal planning check-in**。它不会替换内置模板或其他插件模板。关闭该选项并重新加载、禁用插件或卸载插件，会将模板从目录移除。**已经创建的 job 仍会运行，必须在 Hermes 中单独暂停或移除。** 本插件不会枚举、取消或管理这些 job。

## 2. 用户配置项

| Slot | 契约 | 默认值 |
|---|---|---|
| `time` | 原生 `HH:MM` 调度输入 | `09:00` |
| `recurrence` | 严格枚举：`everyday`、`weekdays`、`weekends` | `weekdays` |
| `focus` | 严格枚举：`priorities`、`commitments`、`weekly-review` | `priorities` |
| `language` | 严格枚举：`English`、`Simplified Chinese` | `English` |
| `deliver` | 原生投递目标，建议值为 local/origin；原生 UI 可提供已配置目标 | `local` |

模板围绕选定主题提出三个简短的反思问题，要求用户提供当前事实，不假装已经检查任务、消息或日历。提示词不要求浏览、账户访问、工具或外部动作。这些句子是**提示词指令，不是沙箱或强制工具限制**。Blueprint API 不提供单 job 工具白名单、消费上限或领域授权门禁。

主题不会决定频率：`weekly-review` 配合 `weekdays` 仍会在每个工作日运行。请选择实际需要的频率，并核对原生计划。本模板不增加自己的日期、时区或 DST 语义。依赖某个本地时间之前，应核验宿主调度器的实际时区及下次运行时间；不会推断用户所在地时区。

`local` 将原生 cron 结果保存在本地，不发送消息。这是默认值，不是对 Hermes 的限制。投递 slot 有意沿用原生目标选择，改成 `origin` 或已配置频道会改变接收方。排程之前应确认目标。本地投递仍会运行 agent/模型，可能向已配置 provider 发送提示词并产生费用；它不表示离线计算。

## 3. 明确使用原生排程

打开原生 Blueprints 目录，选择带命名空间的模板。核对字段后，仅在准备创建普通 cron job 时提交。Desktop/dashboard 提交是动作，不是 dry run。

聊天命令也并非统一的预览：

- `/blueprint` 列出目录。
- `/blueprint hermes-personal-agent:planning-check-in` 进入对话式配置流程，可能启动 agent turn。模型可能询问选项，不应将它视为免费且无执行行为的静态表单。
- 选择模板键并附带内联 `slot=value` 参数，可经 Hermes 的确定性快捷路径直接创建 job。这不是预览，因此本文不将其作为可直接复制执行的设置命令展示。

真实执行需要可用的原生调度器和已配置的模型/provider。非本地投递还需要原生传输连接。周期任务可能持续产生模型调用费用，直到被停止。我们没有为用户配置这些服务或凭据。如果真实测试需要 key，应通过获授权的安全凭据流程配置；不要在聊天或模板字段中粘贴 key。

使用 Hermes 正常 cron 界面检查、暂停或移除创建的 job，并核验结果。移除插件不会撤销普通原生 job 的访问权限。创建后，job 的提示词、计划、执行与投递状态归宿主管理；本插件不声称提供持久领域回执或 exactly-once 投递。

## 4. 安全与产品边界

- 模板不附加本地任务/项目数据，插件工具也不读取这些数据。它不与[本地收件箱](16-local-task-inbox-zh.md)或[项目分组](24-local-project-groups-zh.md)同步。
- 不注册 owner、不验证接收 Bot、不选择主 Bot、不授予私人读取权限，也不准入受控动作。[身份门禁](23-host-command-context-experiment-zh.md)仍未完成。
- 用户走原生排程流程，不代表本插件已经保护全部现有 Hermes 工具。原生 job 保留宿主自身的模型、工具、权限、投递与保留行为。
- 本次不实现安静时段、升级、周期费用、跨频道同意、硬取消、outbox 对账或投递结果未知的策略。提示词不能填补这些缺口。
- 此模板不依赖随插件提供的 skill。填好的提示词被复制到原生 job 状态，后续插件更新不会自动更新已有 job。

这是 E0.3/E4.2 的窄范围原生模板先导。E4 受控提醒、E1 授权及 M1 验收门禁仍未完成。状态报告继续将提醒与外部投递标记为尚不可用的**插件管理受控能力**，同时单独声明模板实现；它不探测用户是否已经排程。

## 5. 验证与来源

测试覆盖严格布尔配置、默认缺席、原生注册/发现、模板填充与严格选项、默认本地投递、清理/重新加载，以及合成 test double 下的原生排程交接。注册不得创建任务或 cron 存储。测试明确区分生成计划规格和执行 job。真实 provider 调用、调度触发、手机投递及设备 UI 验收仍未验证。

宿主支持在 plugin-host 隔离下注册纯数据 blueprint。即使测试了 pipe 注册，也不能等同于生产隔离或 owner 边界；它不消除[已有本地 CLI 隔离限制](../README-zh.md#在隔离-hermes-中试用)。

- [公开 blueprint API 与生命周期](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/website/docs/developer-guide/plugins/index.md#L1965-L1996)。
- [注册与清理记录](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/plugins_content.py)。
- [原生目录与填充](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/cron/blueprint_catalog.py)。
- [聊天选择与直接创建的区别](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/blueprint_cmd.py)。
- [Dashboard 实例化与动态投递选择](https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/hermes_cli/web_routers/cron.py#L901-L966)。
