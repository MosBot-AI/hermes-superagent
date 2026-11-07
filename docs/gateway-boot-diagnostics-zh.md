# Gateway 启动诊断

[English](gateway-boot-diagnostics.md) | 简体中文

关联 [#50](https://github.com/MosBot-AI/hermes-superagent/issues/50) 和父任务 [#40](https://github.com/MosBot-AI/hermes-superagent/issues/40)。

## 已知失败与证据边界

历史 Gateway 日志先报告 `Gateway control socket failed to start: [Errno 1] Operation not permitted`，随后启动失败。固定版本宿主的 `GatewayControlServer.start()` 捕获异常后只记录消息，没有保留异常堆栈，因此日志不能指出失败的系统调用。socket 最后的 `chmod` 已被上游抑制异常，不能单独导致这条致命失败路径。其他路径操作以及 `asyncio.start_unix_server` 中的 socket 创建、绑定、监听仍是候选。

Linux 的 EPERM 表示操作不被允许，不是要求 GitHub 授权，也不是 API 凭据失败。文档将 `bind` 的普通路径搜索或访问拒绝列为 EACCES。seccomp 过滤器可以不执行系统调用而直接返回错误码，但看到 `Seccomp: 2` 不能确定命中规则，也不能证明历史失败原因。参见 [bind(2)](https://man7.org/linux/man-pages/man2/bind.2.html) 和 [内核 seccomp 文档](https://docs.kernel.org/userspace-api/seccomp_filter.html)。

## 只读规划

使用固定版本宿主及其现有解释器。默认命令验证宿主版本和受跟踪源码洁净状态，报告不含秘密的进程策略标志并打印计划，不启动 Gateway、不创建 socket、不安装任何内容，也不创建输出目录。

```sh
python scripts/diagnose_gateway_boot.py \
  --hermes /path/to/pinned/hermes \
  --hermes-python /path/to/hermes-venv/bin/python \
  --output /private/new-evidence-directory
```

本地回归测试使用合成异常和模拟子进程执行，验证堆栈保留、模块调用限制、私有证据目录、失败退出码传递、拒绝覆盖证据及无凭据环境。这些测试不是原生传输验收。

## 原生执行前提

只有独立确认选定执行环境允许未修改的官方私有传输时，才添加 `--run-native`。此参数用于防止误执行，不是绕过平台策略的权限。不要禁用 seccomp、放宽 socket 权限、替换成 TCP、使用 sudo，或把被拒操作转移到别处以规避限制。泛泛地声称 CI 支持联网，并不能证明具体策略允许该操作。

运行器委托固定上游的 `evals/shared_gateway/normal_boot.py` 执行。一个小型解释器启动器仅为控制监听器现有失败警告恢复当前异常堆栈，不修改宿主、socket 函数、对端校验或准入。上游探针提供一次性无凭据配置、仅继承 PATH/LANG/TZ 的环境、有界就绪期限，并清理其自身 Gateway 进程组。不提供供应商密钥、插件、真实用户数据或模型请求。运行器创建新的 0700 私有证据目录，拒绝覆盖已有目录。

产物包括 `PLAN.json`、`BOOT.json`、`BOOT.log` 及诊断启动器。审阅前保持原始日志私有；路径和堆栈可能识别执行环境。上游描述符判定成功仅证明启动就绪，不证明已认证客户端连接、模型任务执行、实际 Gateway 重启后的持久化，也不代表 #40/#50 完成。执行失败后，应先保留堆栈和准确源码版本，再提出修复方案。

此次诊断准备没有重试原生操作，也没有运行或启用新的 CI 传输任务。历史环境阻塞仍然开放。
