# 已存原生观察的关注复盘

[English](54-saved-native-attention.md) | 简体中文

## 读取已存观察，不读取实时看板

`/personal-tasks native-review --on YYYY-MM-DD` 只读取本地任务已保存的 `native_progress` 快照，不打开原生看板或交接账本、不调用提供商、不刷新观察，也不派发工作。明确日期用于计算 UTC 截止时间，不创建后台监测。

可选筛选为 `--project LABEL` 或 `--unassigned`。`--stale-after-days` 默认 7（1–365），`--per-bucket-limit` 默认 5（1–20），`--max-chars` 默认 16000（2048–32000）。只考虑 captured 本地任务。摘要有界，按观察时间从旧到新、再按稳定任务序号排序。

四类可以重叠：

- `awaiting_review`：已存 current 状态为 review。
- `board_closed`：已存 current 状态为 done 或 archived。
- `identity_issue`：已存观察为身份、缺失或重复等失败结果。
- `stale`：观察时间严格早于指定日期 UTC 午夜减去选定天数。

独立关注总数不重复计算跨分类任务。没有观察表示尚未观察，不证明没有关联卡片。所有结果都需要人工核实：已存状态不代表实时状态、本地完成或解除阻塞、完成、派发的许可，不建议自动刷新或修改。

## 范围与隐私

这是基于[明确原生同步](53-native-progress-observation-zh.md)既有元数据的一条本地读取流程。有界摘要包含任务 ID、标题、修订、项目、到期日、工作状态及已存观察，不包含来源详情或原生输出。该查询可通过另行配置并在会话激活的任务模型工具使用既有读取范围；不增加模型写动作，也不自行调用提供商。

状态只说明实现及配置，不探测实时看板。这次仅本地开发的功能未安装或通过真实验收，也未完成[原生编排验收](08-roadmap-and-acceptance-zh.md)。
