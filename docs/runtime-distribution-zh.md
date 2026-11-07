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
`hermes-personal-agent-runtime-FULL_COMMIT_SHA`。拉取请求运行仍检查源码契约，
但不发布运行包。这是保留 30 天的 CI 产物，不是正式发行、签名或安装批准。
信任下载前应核对仓库、分支、提交和工作流成功状态；`PROVENANCE.json` 与哈希
只证明内容对应，不证明作者身份。

产物包含 `hermes-personal-agent.tar.gz`、`VALIDATION.json` 和 `SHA256SUMS`。
压缩包中是独立的 `hermes-personal-agent/` 目录。校验报告应放在旁边，不放进插件。
GitHub 产物 ZIP 的摘要不同于内部 tar 包的 SHA-256。

推送流水线先执行源码和干净宿主契约，再从当前精确提交构建两份，不使用 Git
替换对象。归档条目排序、时间戳与所有者固定，文件权限为 `0644`、目录为 `0755`；
两份压缩归档必须逐字节相同。随后解包，测试前再次与已提交源码核对。

固定宿主未修改的官方 `plugin_guard` 扫描完整解包内容，保留全部发现，只有
`safe` 才继续加载。safe **不等于零发现**：目前用于防护的 SQLite 头和 journal
字节产生一项中等混淆提示。不会隐藏发现、修改扫描规则，也无法在此流水线覆盖
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
