# Hermes Personal Agent

[English](README.md) | 简体中文

Hermes 原生 personal-agent 插件，目标是让一个主 agent 管理项目、承诺、提醒和受控 worker。完整设计见 [docs 索引](docs/README-zh.md)。不运行第二套 agent loop，也不要求额外 API 网关。

## 当前进度

开发中的第一切片：**E0 原生插件兼容基础**，不是可用的 personal-agent MVP。

- `plugin.yaml` 与同步 `register(ctx)` 原生加载。
- 只读 `personal_agent_status` 工具，以及 `in_process` 插件模式下的 `hermes personal-agent status` CLI。
- 严格拒绝非 `read_only` 模式，不注册任何个人数据写入、外发、调度或模型路由能力。
- 离线单元测试，以及固定 Hermes SHA 的真实 discovery、registry dispatch、配置和卸载契约测试。
- 后续 E0.4 失败边界契约及十条阻断写路径的只读清单。`hermes personal-agent coverage` 展示证据，不授权或关闭宿主工具。

本插件**不会禁用或保护其他 Hermes 工具**。E0.4 全部写路径覆盖及 E1 身份/授权尚未完成，不能据此开放受控写操作。当前 status 输出明确给出 `release_gate: blocked`。详见 [第一切片记录](docs/12-foundation-progress-zh.md)、[执行边界契约](docs/13-enforcement-contracts-zh.md) 和 [更新记录](CHANGELOG-zh.md)。

## 开发验证

基线为 `compatibility.json` 内的 Hermes commit；当前实际运行目标是 Python 3.14。没有根据单一 SHA 宣称宽泛的 `requires_hermes` 版本范围。

先在独立目录准备官方 Hermes checkout 和测试环境。不要使用用户的生产 `HERMES_HOME`，不要复制账号密钥：

```bash
git clone https://github.com/NousResearch/hermes-agent.git ../hermes-agent
git -C ../hermes-agent checkout --detach 90d6b98fd86d20981ee06ddd5b7d93e4320f26a4
cd ../hermes-agent
export HERMES_HOME="$(mktemp -d)"
export HERMES_RUNTIME_DIR="$(mktemp -d)"
python -m pm.build_env --source . --out ../hermes-test-venv --group dev --group test
cd ../hermes-superagent
../hermes-test-venv/bin/python scripts/check.py \
  --hermes ../hermes-agent --hermes-python ../hermes-test-venv/bin/python
```

准备环境需要从官方源下载依赖；测试使用合成输入、临时 home 和 Python socket 网络禁用，不访问真实个人账号。检查脚本核对上游 HEAD 与 tracked 文件清洁状态，记录 Python 版本、lock/package 指纹，再调用 Hermes 官方 `scripts/run_tests.sh`。缺少 checkout 或依赖会失败，不会跳过后冒称兼容。已安装包的指纹是所用解释器的观察证据，不证明任意传入环境必定与 lock 完全一致。

只运行 `python scripts/check.py` 会做本仓库单元测试、Ruff、ty 和双语文档结构/链接检查，并明确打印 Hermes compatibility **NOT RUN**。测试工具版本随固定 Hermes dev group，不是插件运行依赖。

## 在隔离 Hermes 中试用

这不是生产安装建议。使用固定、已测试的 Hermes checkout 和临时 profile，按该版本 `hermes plugins install --help` 安装经审阅的**完整 40 字符 commit SHA**；`--ref` 不接受分支名，GitHub tree 分支 URL 也不能替代 pin。然后显式启用插件，插件标识为 `hermes-personal-agent`。

当前实际合同测试覆盖默认 `plugins.isolation: in_process`。在 `plugins.isolation: host` 下，宿主会跳过 `ctx.register_cli_command`，因此这里的 CLI 不可用；隔离 host 模式的完整工具调用尚未运行验证，不要为了显示 CLI 而关闭已配置的隔离。

配置位于宿主 `config.yaml`：

```yaml
plugins:
  enabled: [hermes-personal-agent]
  entries:
    hermes-personal-agent:
      settings:
        mode: read_only
```

合并到你已有配置时保留其他条目，不要覆盖整个 `plugins`。启用不修改 `delegation.backend`、主模型、凭据、tool override 或其他权限。`personal_agent_status` 是否出现在模型工具面还取决于宿主会话的工具集选择；CLI 状态检查不需要 LLM 调用。

## License

[MIT](LICENSE)。上游测试源码不打包进本插件；出处与许可说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
