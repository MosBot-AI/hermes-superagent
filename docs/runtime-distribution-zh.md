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
真实模型验收尚未完成。运行包不含工作器实验；固定生产宿主也不支持该实验。
不会注册工作器或切换提供器。

官方支持 Git 子目录安装，但此处不执行。仍须原样扫描、同意和 PM 准入；
无依赖不保证离线或不改变环境。子目录包的更新路径尚未验证。
