# xjtu-paper-writer V1.0.2

面向西安交通大学理工科本科生的学术写作 Agent Skill。支持个人实验报告、小组实验报告、课程论文和学术综述；支持从零写作、授权局部修改、仅排版，也可单独调用配图、润色或排版检查。

本目录为V1.0.2本地发布候选，尚未上传。已发布的GitHub V1.0.1保持不变。

## 获取与首次使用

- [GitHub 项目](https://github.com/QueenLee-Vic/xjtu-paper-writer)：发布后从Releases下载完整ZIP及SHA256，核对后解压，不能只复制SKILL.md。
- [Astron SkillHub 技能](https://skill.xfyun.cn/space/global/xjtu-paper-writer)：`global/xjtu-paper-writer@1.0.1`，已发布状态依据用户确认；该平台专用分发与GitHub包的元数据和说明有所不同。
- 按[安装与使用](INSTALL.md)选择Codex、Claude Code或OpenCode的项目级入口。DeepSeek是可由OpenCode调用的模型，不是独立Skill宿主。

首次提供教师要求、文章类型、现有材料和明确授权的作业目录；缺数据、成员分工或文献时不编造。示例：

- “请使用xjtu-paper-writer，根据我提供的数据写个人实验报告，先识别缺失信息，输出到我授权的作业目录。”
- “只润色第三节，保留数据、术语、公式、引用和Word原格式。”
- “不要修改正文，只按教师模板调整DOCX格式，另存新文件。”

## 主要能力与保护

分析教师要求和模板，组织四类文章结构，核实文献和数据，生成科学数据图和解释性示意图，执行学术中文润色、DOCX排版与质量检查。个人和小组报告支持带校徽封面及动态信息；不得虚构成员贡献。

教师明确要求＞正式模板＞教师示例＞用户参考样式＞默认配置。仅排版不改文，润色不改变科学事实和未经授权的格式；复杂对象不能安全处理时保护或拒绝。缺证据交付待补充状态。

V1.0.2修复样式与润色计划预览的Markdown/HTML注入，使用共享展示编码，不修改原始JSON或论文文字。安装目录只读，输出必须在用户授权的独立工作目录；必需的WORKSPACE-REQUIRED.json缺失或异常时拒绝执行，不能用开发环境变量解除守卫。

## 环境和能力边界

脚本安全执行要求Linux x86_64/aarch64、Landlock ABI≥3、Python及已有依赖；PDF渲染还需bubblewrap和允许的非特权命名空间。见[依赖](REQUIREMENTS.md)。Windows/macOS原生执行未验证；Windows Word查看文档与执行这些工具是不同能力。

Codex有历史独立发现和触发基线；Claude Code和OpenCode自动选择仍不稳定，OpenCode+DeepSeek独立安装存在历史阻塞。本轮本地包检查不等于新会话端到端验证。长公式、数学字体、复杂跨Run及部分Word对象仍有限制，见[LIMITATIONS](LIMITATIONS.md)。维持B级有限范围。

## 许可证及资源

项目自身有权许可的代码和文档采用[MIT License](LICENSE)，Copyright (c) 2026 QueenLee-Vic。西安交通大学校徽及中英文校名标识不在MIT范围，使用应遵守学校规定；用户确认的限定分发不等于校方授权。本项目不是学校官方发布。见[资源说明](RESOURCE-SOURCES.md)、[第三方说明](THIRD_PARTY_NOTICES.md)。

反馈见[贡献说明](CONTRIBUTING.md)，安全问题见[SECURITY](SECURITY.md)。
