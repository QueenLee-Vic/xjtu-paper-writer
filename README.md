# xjtu-paper-writer V1.0.1

面向西安交通大学理工科本科生，辅助个人实验报告、小组实验报告、课程论文和学术综述。支持从零写作、授权局部修改、仅排版，以及科学数据绘图、示意图、学术中文润色、DOCX 与质量检查。

Agent 完成需求分析、资料判断、写作和语义审查；Python 执行可验证的保护和文件操作。缺数据不编造，缺文献不补假引用，仅排版不改文，润色不改格式。教师明确要求优先于正式模板、示例、参考样式、默认配置。

先读 [安装](INSTALL.md)、[依赖](REQUIREMENTS.md)、[限制](LIMITATIONS.md)。提供真实材料并明确授权工作目录，例如：“请使用 xjtu-paper-writer，根据我提供的数据写个人实验报告，将结果保存在我指定的作业目录。”不要在 Skill 安装目录存作业。

校徽随包提供，可关闭，缺资源回退文字学校名；来源与限定范围见 [资源说明](RESOURCE-SOURCES.md)。本版为B级有限范围发布准备版；远程公开发布须经最终确认。本项目不代表学校官方发布。

## 安装与基础使用

完整解压后，将Skill目录放到目标项目的 `.agents/skills/xjtu-paper-writer/`（Codex）或 `.claude/skills/xjtu-paper-writer/`（Claude Code）。OpenCode优先使用其支持的兼容入口；DeepSeek是模型，OpenCode是宿主。详细步骤与工具参数见 [INSTALL](INSTALL.md)。

使用示例：

- 从零写作：“请使用 xjtu-paper-writer，根据我给出的数据写个人实验报告，输出到我授权的作业目录；缺少的数据不要补造。”
- 局部修改：“只润色第三节，保留实验数据、引用和原Word格式。”
- 仅排版：“不要修改内容，只按教师模板调整DOCX格式，另存新文件。”

程序运行要求Linux x86_64/aarch64、Landlock ABI≥3；PDF渲染另需bubblewrap及可用的非特权命名空间。未宣称Windows/macOS原生运行通过。Claude/OpenCode自动触发不稳定，OpenCode+DeepSeek独立调用仍有已记录限制。复杂公式、数学字体和新RC的Microsoft Word专项验证范围见 [LIMITATIONS](LIMITATIONS.md)。

## 开源许可与资源例外

项目自身有权许可的代码及文档采用 [MIT License](LICENSE)，不附加仅限学生、非商业等代码许可限制。版权署名为 Copyright (c) 2026 QueenLee-Vic。原RC.3保留不变。

西安交通大学校徽及中英文校名标识不属于MIT许可；它是独立第三方资源，使用应遵守学校相关规定。本项目不是西安交通大学官方发布。用户对项目分发的确认不代表校方授权。详见 [资源来源](RESOURCE-SOURCES.md) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。

反馈和贡献方式见 [CONTRIBUTING](CONTRIBUTING.md)，安全问题处理见 [SECURITY](SECURITY.md)。计划公开仓库：`QueenLee-Vic/xjtu-paper-writer`；远程创建与上传尚待最终批准。仓库建立后可在该仓库提交Issue或Pull Request。
