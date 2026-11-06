# 第三方许可说明

[English](THIRD_PARTY_NOTICES.md) | 简体中文

本插件按仓库的 MIT 许可分发，自身没有第三方 Python 运行依赖。宿主 API 由 Hermes 提供。

兼容性测试在独立 checkout 中使用 **NousResearch/hermes-agent**，固定提交为 `90d6b98fd86d20981ee06ddd5b7d93e4320f26a4`。Hermes 采用 MIT 许可，本仓库没有打包完整宿主。重新分发 Hermes 本身时须保留其许可：

- 源码：https://github.com/NousResearch/hermes-agent/tree/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
- 许可：https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/LICENSE
- 行为契约参考：https://github.com/NousResearch/hermes-agent/blob/90d6b98fd86d20981ee06ddd5b7d93e4320f26a4/tests/hermes_cli/test_plugin_api_compat.py

[语音 IPC 实验](experiments/voice-ipc/README-zh.md)包含仅供审阅的补丁，含部分上游衍生代码/上下文及新增原型代码。原始 Hermes MIT 声明完整保留于 [LICENSE.hermes-agent](experiments/voice-ipc/LICENSE.hermes-agent)。插件不会安装、导入或应用该补丁，补丁也未提交上游，正式兼容性固定版本不变。

开发及 CI 环境解析固定 Hermes `uv.lock`，包含其 `dev` 和 `test` 分组。相关依赖保留各自许可，不打包进插件。工作流使用 SHA 固定的官方 `actions/checkout` 和 `actions/setup-python`。

DSH Superagent、Switchyard、LiteLLM 和 vLLM Semantic Router 是 `docs/` 中的研究参考。本基础切片不包含或执行它们的实现代码。
