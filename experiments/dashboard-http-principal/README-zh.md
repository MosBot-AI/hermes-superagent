# Dashboard HTTP 调用方身份提案

[English](README.md) | 简体中文

可选 personal API 必须先取得由宿主验证的调用方身份和实际服务的 profile，才能检查集合访问权限。在未修改的 Hermes `2281116525106e3c109993ccb5dc74d02bfc1427` 上，原生 dashboard 准入层处理请求，manifest 挂载插件，隔离进程收到 `hosted_http_authenticated`。该进程没有收到对应的已验证提供方身份。未修改版本的对照使用同一个合成插件，经过原生认证后，由受保护的探针返回 `503 host_identity_unavailable`。

[评审专用补丁](dashboard-http-principal.patch)为 dashboard 插件的 HTTP 处理器提供 `get_plugin_http_principal(request)`。现有宿主提供方准入层验证 cookie 会话（包括刷新）或 bearer 后，宿主记录凭据类别。在解析 profile 且确认插件许可后，宿主生成不可变快照，其中包含 `provider`、`issuer`、`subject`、`organization`、`credential_kind` 和 `profile_name`。在隔离模式下，宿主通过现有私有请求通道仅序列化这六个字段。子进程仅在同一请求通过原生宿主准入且字段有效时接收快照。两种模式都通过同一个读取函数访问请求状态。

生成快照需要有效提供方、由其验证的非空签发方与主体，以及宿主解析的 profile 名称。组织字段可以为空。快照不含 bearer、cookie、显示名、邮箱、本地 home 路径或策略。服务 profile 是可重命名的路由标签。使用方仍需独立验证当前 owner 绑定、对象授权和撤销栅栏。身份信息仅为当前请求按需保留，脱离宿主请求后不具备独立权限。[受保护的合成使用方](test_http_principal.py)演示这一接口，全程不读写领域数据。

| 现有凭据 | 候选版本结果 |
| --- | --- |
| 通过提供方准入的 cookie，包括刷新后的 cookie | 生成标记为 `cookie_session` 的快照 |
| 通过提供方准入且签发方和主体已经验证的 bearer | 生成标记为 `provider_bearer` 的快照 |
| 部署会话令牌（包含 bearer 形式），或无签发方的会话 | 原有准入可以成功，读取函数无快照可返回。 |
| 回环浏览器令牌、原生同用户 HTTP grant 或已注册的服务令牌 | 原有准入依据各自原生路由，读取函数无快照可返回。 |

同一组对照覆盖启动 profile 的进程内和隔离路由、独立的次级 profile 宿主、cookie 刷新及后续使用、不同主体的并发请求、持有有效 cookie 时拒绝无效 bearer、拒绝来自其他页面的 cookie 写请求，以及未知 profile 和插件运行时禁用。对照也覆盖原生 grant、回环令牌和部署令牌在没有提供方身份时的准入。测试使用固定版本真实 dashboard ASGI 应用。提供方与 Gateway 权限测试替身使用合成输入。隔离请求进入真实插件子进程。本次对照尚未验证已部署入口、真实身份提供方、响应进行中隔离宿主的撤销行为或共享任务 API。

在 Python 3.14.9 上，两棵源码树各通过七项对照用例。候选版本通过上游逐文件运行器的 132 项用例，也通过上游全部 15 项静态检查与导入边界检查。[清单](manifest.json)记录确切的暂存源码树及测试输入。

## 在临时 checkout 中复现

将 `PROJECT` 设为本项目 checkout，`CLEAN` 和 `PROPOSED` 分别设为基线的独立干净 checkout，并将 `PYTHON` 设为固定版本 Hermes 的 Python 3.14.9 测试解释器。保留常规项目检查使用的干净兼容 checkout。

```sh
set -eu
ARTIFACT="$PROJECT/experiments/dashboard-http-principal"
BASE=2281116525106e3c109993ccb5dc74d02bfc1427
test "$(git -C "$CLEAN" rev-parse HEAD)" = "$BASE"
test "$(git -C "$PROPOSED" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$PROPOSED" status --porcelain)"
git -C "$PROPOSED" apply --check "$ARTIFACT/dashboard-http-principal.patch"
git -C "$PROPOSED" apply --index "$ARTIFACT/dashboard-http-principal.patch"
"$PYTHON" "$ARTIFACT/run_tests.py" --clean "$CLEAN" --proposed "$PROPOSED" --python "$PYTHON"
```

运行器验证两个 checkout 的确切内容和[清单](manifest.json)，清除子进程继承的环境，为每组测试使用临时 home，并禁止外网。它验证对照用例均通过且无捕获输出，再使用上游逐文件运行器执行已选原生回归。请参阅[上游许可证](LICENSE.hermes-agent)。补丁未启用且尚未提交上游。
