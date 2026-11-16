# 固定 Hermes 版本的 Telegram 命令观察

[English](README.md) | 简体中文

本评审产物为一次性 Hermes 检出 `2281116525106e3c109993ccb5dc74d02bfc1427` 增加可选的进程内命令观察。测试通过真实插件加载器注册合成消费方，验证该协议。项目兼容性目标仍是干净的宿主版本。精确的暂存树、补丁和测试输入见 [manifest.json](manifest.json)，上游许可证见 [LICENSE.hermes-agent](LICENSE.hermes-agent)。

## 观察契约

适配器准入即时命令后，将原始 Telegram SDK `Update.message` 标记在原始事件上。原始更新和消息都必须绑定到接收适配器已初始化的 SDK Bot 对象。标记仅适用于非话题内的直达人类私聊且消息未被编辑，并排除转发、机器人中介和商业消息。延迟处理的拆分命令走原有缓冲路径，不会获得标记。

Gateway 实际注册的回调可声明可选关键字 `telegram_observation`。它是一个可调用对象，可一次性返回发送者 ID、接收 Bot 账号 ID、传输 profile 和注册命令名称，或者返回 `None`。读取时检查原始事件、命令文本、当前接收器及其注册项、同 profile 路由和 Gateway 当前允许名单。有效期自适配器捕获起为五秒，回调退出时保留的句柄立即失效。通用 `**kwargs` 回调继续收到原有上下文，宿主子进程命令不接收观察句柄。

观察反映合作式宿主中读取瞬间的本地传输来源。网络认证、已认证 owner 登记、设备和策略版本、路由 ABA 栅栏及原子准入仍需要独立证据。句柄只覆盖一次回调，SDK 包重新投递可能触发新回调。返回值可复制，不携带权限。探针只输出合成标识。运行时包不包含此产物。

## 验证结果

两个树均使用 Python 3.14.9 和 Hermes 锁定的精确 Telegram SDK 22.8 wheel。一个干净版本对照确认同一份直达 SDK 输入在已有处理器上拿不到观察。候选的 17 项检查和现有的 36 项原生回归均通过。上游工具报告没有新增阻断性或提示性代码健康问题，15 项静态检查和导入边界检查也通过。[历史实验](../command-context/README-zh.md)中的九项套接字用例不在本次选择范围内。

候选用例覆盖两个合成接收账号、一次性读取和回调退出失效、转发、编辑、群消息、机器人消息、内联机器人中介、编号相同但 SDK Bot 对象不同、构造事件、原事件副本、超时、适配器断开或重新归属、SDK Bot 更换和丢失初始化状态、允许名单变化、旧回调结构和独立宿主子进程。SDK 初始化使用合成数据，没有网络调用。

## 在一次性检出中复现

将 `PROJECT` 设为本项目检出路径，`COPY` 设为干净的一次性 Hermes 检出，`PYTHON` 设为其 Python 3.14 测试解释器，`WHEEL` 设为 `manifest.json` 记录的 SDK 22.8 wheel。将 `SDK` 设为两个仓库之外的新目录。标准项目检查使用的检出保持干净。

```bash
set -eu
ARTIFACT="$PROJECT/experiments/telegram-command-observation"
BASE=2281116525106e3c109993ccb5dc74d02bfc1427
test "$(git -C "$COPY" rev-parse HEAD)" = "$BASE"
test -z "$(git -C "$COPY" status --porcelain --untracked-files=all)"
printf '%s  %s\n' 42373918097f1b837cc4e717d588c19ea79651497ec712bb5b0c76e5e63c50e1 "$WHEEL" | sha256sum -c
printf '%s  %s\n' d1eb37a9d1346915393186547a5a5bd66bc726f30937475c77921aeeca679723 "$ARTIFACT/telegram-command-observation.patch" | sha256sum -c
mkdir "$SDK"
"$PYTHON" -m zipfile -e "$WHEEL" "$SDK"
cd "$COPY"
TEST_HOME="$(mktemp -d)"
export HOME="$TEST_HOME"
export HERMES_PYTHON="$PYTHON"
umask 022
PROBE="$ARTIFACT/test_observation.py"
IMPORTS="$COPY $PROJECT $PROJECT/tests/contracts $SDK"
bash scripts/run_tests.sh "$PROBE" --file-retries 0 -- -o "pythonpath=$IMPORTS" -k clean_pin -q
git apply --check "$ARTIFACT/telegram-command-observation.patch"
git apply --index "$ARTIFACT/telegram-command-observation.patch"
test "$(git write-tree)" = 97146739f6d9a6ba44b68338215490011ed38f5d
bash scripts/run_tests.sh "$PROBE" --file-retries 0 -- -o "pythonpath=$IMPORTS" -k candidate -q
bash scripts/run_tests.sh "$PROJECT/tests/contracts/test_owner_telegram_ingress.py" \
  tests/hermes_cli/test_plugin_command_source.py tests/gateway/test_multiplex_transport_matrix.py \
  tests/gateway/test_telegram_callback_auth_fail_closed.py tests/gateway/test_telegram_auth_check.py \
  --file-retries 0 -- -o "pythonpath=$IMPORTS" -q
"$PYTHON" scripts/check --base "$BASE" --staged
"$PYTHON" scripts/boundary_lint.py --check
```
