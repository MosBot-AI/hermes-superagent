# 离线运行包

[English](runtime-distribution.md)

此导出仅生成独立插件包，不代表安装或授权批准。原扫描拒绝及发现仍然有效；
本工作不重试安装。未来安装必须保留扫描，并取得所有必要的同意。

先提交构建器、`packaging/runtime-files.json` 明确清单、说明和运行源码，
再使用该提交中的构建器及完整源提交 SHA：

```text
python scripts/build_runtime_distribution.py --source-commit FULL_SOURCE_SHA --output-dir NEW_DIRECTORY
python scripts/build_runtime_distribution.py --source-commit FULL_SOURCE_SHA --output-dir NEW_DIRECTORY --verify
```

父目录须已存在，输出目录不得存在。只读取已提交 Git 对象，不包含工作区修改。
后续可另行提交生成目录；分发提交与源提交不同。构建器不会自行提交。
`PROVENANCE.json` 记录全部分发源码、构建器和清单的哈希，不包含自身哈希。
校验时从源提交重建预期字节；哈希不是数字签名。

所有生产 Python 文件、原始元数据、MIT 许可证和第三方声明保持原字节。
研究文档、测试和实验宿主补丁保留在来源仓库，按记录的源提交查看。
原声明中的相对链接指向完整源码树。可选原生记忆提供器的构建声明不打包或启用。

默认仍为 `read_only`，个人存储、会话及模型记忆工具关闭。显式本地选项仅适合
可信单用户配置；LOCAL 不证明物理本地身份。任务和记忆为明文本地数据，分别
激活后可能进入宿主历史或配置的模型。插件不保护其他 Hermes 工具，发布门槛和
真实模型验收尚未完成。运行导出不包含实验宿主补丁及比较用消费者；
[受门控生产规划模块](55-gated-plan-worker-zh.md)是不同的包内源码。`plan_worker`
默认关闭。未修改的固定宿主缺少准确已审阅文本 worker 约定，因此不注册 worker。
采用兼容约定的宿主还必须具备当前 `llm.text_worker` 同意及本地任务/会话/模型工具前提。
每次操作重验门控，不回退到通用 launch 或其他提供商。
打包不会启用这些选项，也不会安装或升级宿主。

官方支持 Git 子目录安装，但此处不执行。仍须原样扫描、同意和 PM 准入；
无依赖不保证离线或不改变环境。子目录包的更新路径尚未验证。

## 下载推送构建的运行包

`Foundation checks` 的分支 **push** 运行成功后，会在该运行的 **Artifacts** 区域提供
`hermes-personal-agent-runtime-FULL_COMMIT_SHA`。拉取请求运行也会构建并验证精确的 PR head 提交，包括冷会话门槛，
但不发布运行包。它使用普通的 `pull_request` 事件、只读令牌，不持久化检出凭据，
不使用仓库密钥；不会引入特权 `pull_request_target` 执行。这是保留 30 天的 CI 产物，不是正式发行、签名或安装批准。
信任下载前应核对仓库、分支、提交和工作流成功状态；`PROVENANCE.json` 与哈希
只证明内容对应，不证明作者身份。

产物包含 `hermes-personal-agent.tar.gz`、`VALIDATION.json` 和 `SHA256SUMS`。
压缩包中是独立的 `hermes-personal-agent/` 目录。校验报告应放在旁边，不放进插件。
GitHub 产物 ZIP 的摘要不同于内部 tar 包的 SHA-256。

推送和拉取请求流水线都会先执行源码和干净宿主契约，再从当前精确提交构建两份，不使用 Git
替换对象。归档条目排序、时间戳与所有者固定，文件权限为 `0644`、目录为 `0755`；
两份压缩归档必须逐字节相同。随后解包，测试前再次与已提交源码核对。

固定宿主未修改的官方 `plugin_guard` 扫描完整解包内容，保留全部发现，只有
`safe` 才继续加载。safe **不等于零发现**。固定 `ed6bcdc15d883dc429f2dbb0559a62204965ab04`
产物有六项中等混淆提示，其中三项为中文 Unicode 范围模式，三项为 SQLite
header/journal 字节模式。应阅读实际 `VALIDATION.json`，其他修订的发现可能不同。不会隐藏发现、修改扫描规则，也无法在此流水线覆盖
CAUTION。这项直接静态扫描不等于安装器的目录检查、同意或 PM 准入。
原完整仓库安装拒绝仍是独立的未解决事项。

扫描器与宿主加载器从固定 Git blob 重新构建的干净快照执行，不使用调用者的
工作区或被忽略的字节码，也不修改原宿主文件。这样可避免隐藏索引标记或陈旧
字节码在 Git 状态看似干净时悄悄替换扫描器或加载器。

冷进程验收使用新建的 `python -I -B` 进程与一次性合成配置，导入路径不含源码
仓库，并禁止全局 `personal_agent` 导入。真实宿主发现复制的运行包。默认只读
注册不得创建任务存储或工作器；只在测试中显式开启本地任务后，必须成功捕获、
更新、重载并重放一个任务，不能产生重复。网络连接、监听与子进程均被拒绝
（扫描器仅可用其精确只读 Git 命令盘点字节码）。不调用安装器、运行中的用户
配置、凭据、Gateway 监听器或模型。这些测试防护不是针对恶意原生扩展的
操作系统沙箱。任何门槛失败都不会产生可下载的包。

## 本地归档与验收

构建已提交运行目录后，在目录外独占创建新归档：

```text
python scripts/build_runtime_distribution.py --source-commit FULL_SOURCE_SHA --output-dir RUNTIME_DIRECTORY --archive-file NEW_ARCHIVE.tar.gz
python scripts/check_runtime_distribution.py --repo SOURCE_CHECKOUT --source-commit FULL_SOURCE_SHA --package RUNTIME_DIRECTORY --hermes CLEAN_PINNED_HOST --hermes-python PREPARED_PYTHON --report NEW_REPORT.json
```

报告必须位于源码、运行包及宿主目录之外。使用已准备且可信的宿主和测试解释器；
校验器不安装任何东西。要求精确且干净的宿主，扫描前核验全部文件，运行目录缺失
或变化时会在导入包之前拒绝。验收后再次核验归档对应的内容。本次仅覆盖合成的
进程内 CLI 流程；真实安装、原生客户端/Gateway、模型工具和工作器正式采用仍有
独立验收门槛。不要用此产物重试已经拒绝的安装。

## 打包后的原生会话验收门槛

同一个已验证运行包还会在独立冷进程中通过固定版本宿主的原生 LOCAL 命令分发器运行。
合成的已认证内存传输会录入并读取任务、重新加载插件，再手动重复相同请求，确认不会重复创建。
缺少读取或控制能力时，必须在任何任务修改前拒绝。插件模块必须来自已验证运行包，而非源码检出目录。
网络、监听器、子进程、模型工具及 worker 注册仍保持禁用。

这项新增门槛验证制品的会话入口，不代表安装、登录、真实传输、CLI/TUI 或模型提供商验收；
应另查对应精确检查点证据；原始 #40 本地会话范围后来已关闭，并不代表整个产品获验收。
验证报告通过 `conversation_acceptance` 单独记录结果，
任何失败都会阻止运行包报告被标记为通过。

## 固定检查点操作者入口

源码 `ed6bcdc15d883dc429f2dbb0559a62204965ab04`（树
`24bae909c2caf97e11620a1d9a660cba22272670`）的已验证开发产物为
[`hermes-personal-agent-runtime-ed6bcdc15d883dc429f2dbb0559a62204965ab04`](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656/artifacts/13785725174)。
它来自成功的 main [Foundation 运行 42859787656](https://github.com/MosBot-AI/hermes-superagent/actions/runs/42859787656)，
产物 ID 为 `13785725174`，到期时间为 **2026-12-10 17:04:08 UTC**。下载可能要求
登录 GitHub。这是保留 30 天的 CI 产物，不是已发布 release 或永久更新渠道。
不得在未经重新审查时换成其他后续产物。

下载 ZIP 的 SHA-256 为
`cf4fa2b3fdf55a53b42d29b5aa51889b42f5c46abe7d14ed6e6ce61a8bed9943`。
内部 tarball 的 SHA-256 为
`e2be57dadc9cb4fedebb7b822d3a2553e8014b3b9ba25396a695da10d45a3e86`。
独立只读核对确认 ZIP 摘要、两个内部校验和、全部 83 个分发源文件与已提交 Git
对象逐字节一致，且验证报告的 provenance 一致。该审查没有安装或调用模型。
报告注明 `installation_performed: false`；真实传输验收另见[固定本地 M1 ledger](90-local-m1-acceptance-zh.md)。

### 先验证，再暂存为本地 Git 源

使用包含该精确提交的可信源码 checkout，以及固定宿主
`2281116525106e3c109993ccb5dc74d02bfc1427` 和通过官方流程准备的 Python 3.14.9
环境。[开发环境说明](../README-zh.md#开发验证)提供宿主准备步骤；会下载依赖，
但不提供 provider 凭据，也不要求使用日常 profile。若升级已有记忆存储到支持
维护锁的实现，应先停止旧 runtime。

核对 ZIP 摘要后，将它解压到新目录。在该目录执行：

```bash
sha256sum -c SHA256SUMS
tar -xzf hermes-personal-agent.tar.gz
```

将 `SOURCE` 设为可信源码 checkout 的绝对路径，`RUNTIME` 设为解压所得
`hermes-personal-agent` 目录的绝对路径。必须**先验证，再创建 `.git`**：
严格运行包校验会有意拒绝额外目录。

```bash
python "$SOURCE/scripts/build_runtime_distribution.py" --repo "$SOURCE" \
  --source-commit ed6bcdc15d883dc429f2dbb0559a62204965ab04 \
  --output-dir "$RUNTIME" --verify
git -C "$RUNTIME" init -b main
git -C "$RUNTIME" add .
git -C "$RUNTIME" -c user.name=Acceptance -c user.email=acceptance@example.invalid \
  commit -m 'test: stage verified runtime'
PACKAGE_COMMIT="$(git -C "$RUNTIME" rev-parse HEAD)"
```

官方 `file://` 安装器克隆的是 Git 仓库，不是普通解压目录。该本地暂存提交与
`PROVENANCE.json` 记录的源码提交不同；不要将原源码 SHA 作为暂存仓库的 `--ref`。
将 `VALIDATION.json` 和 `SHA256SUMS` 留在运行包旁边，而非包内。

### 隔离安装与确定性使用

使用全新的私密 profile 与用户 home，不复制日常 `.env` 或凭据。
将 `HOST`、`HERMES_PYTHON`、`PROFILE`、`USER_HOME` 和 `RUNTIME_DIR` 设为绝对路径；
后三者应创建为彼此独立的私密目录。从 `HOST` 执行。
**每次**安装和后续命令均使用相同的干净环境：

```bash
cd "$HOST"
env -i PATH="$PATH" HOME="$USER_HOME" LANG=C.UTF-8 \
  HERMES_HOME="$PROFILE" HERMES_RUNTIME_DIR="$RUNTIME_DIR" \
  "$HERMES_PYTHON" -m hermes_cli.main plugins install "file://$RUNTIME" \
  --ref "$PACKAGE_COMMIT" --yes-deps --enable
```

`--yes-deps` 明确同意安装器正常的依赖准备，`--enable` 启用已审查的插件。
保留官方扫描、catalog 检查和 capability 同意流程。遇到拒绝即停止，不使用
`--force`、`--allow-removed`，不修改扫描器或降低隔离。若依赖下载需要已有且获准
的代理/CA 设置，只显式保留这些设置，不继承整份日常环境；绝不禁用 TLS 验证。
固定已测路径是新的可信单用户进程内 profile，不是修改现有 hosted 隔离策略。
其他宿主版本需要单独兼容性审查。

在该隔离 profile 保留安装器生成的配置，仅设置本插件的 `mode: local_tasks`
和 `local_conversation: true`，见[本地会话指南](28-profile-first-local-conversations-zh.md)。
没有另外请求时，保持模型工具、worker、记忆、外部连接器和 provider 关闭。
重复上述干净环境前缀，使用 `"$HERMES_PYTHON" -m hermes_cli.main personal-agent tasks list`
进行确定性 CLI 操作。在已获准的原生 LOCAL 会话中使用 `/personal-tasks help`，
再执行 `/personal-tasks add "Synthetic first task" --request-id first-task-1`。
使用实际返回的 ID/revision 和稳定重试键。CLI 不需要模型；宿主交互 UI 可能另有
前提，这些步骤不会配置 provider。任务文本是明文，并可能进入宿主历史。
