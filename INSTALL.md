# 安装与首次运行

## 先确认环境

准备已有Codex CLI、Claude Code或OpenCode及其获授权模型；不需要特定Provider，不修改API配置。Python工具仅支持满足Landlock ABI≥3的Linux x86_64/aarch64；依赖见[REQUIREMENTS](REQUIREMENTS.md)。无此能力时安全停止，不关闭隔离。Windows/macOS原生执行未验证。

## 下载及核对（V1.0.2发布后）

本轮只有本地候选，不能把本地副本称作GitHub下载验收。正式发布后，在项目目录中从[GitHub Releases](https://github.com/QueenLee-Vic/xjtu-paper-writer/releases)下载V1.0.2的ZIP和同名.sha256文件。已安装gh时可用：

```sh
gh release download v1.0.2 --repo QueenLee-Vic/xjtu-paper-writer --pattern 'xjtu-paper-writer-v1.0.2.zip*'
sha256sum -c xjtu-paper-writer-v1.0.2.zip.sha256
```

也可通过浏览器下载。目标已有同名文件时先核实，不覆盖。ZIP顶层为xjtu-paper-writer/。以下安装方式择一，先确认没有同名技能，完整目录包含scripts、references、assets和安全配置。

## Codex项目级安装

在目标项目目录运行：

```sh
mkdir -p .agents/skills
test ! -e .agents/skills/xjtu-paper-writer && unzip -n xjtu-paper-writer-v1.0.2.zip -d .agents/skills
codex
```

在新会话显式输入 `$xjtu-paper-writer`，或“请使用xjtu-paper-writer规划一份实验报告”。核对实际加载位置，按需读取规则并调用Python；未提供实验数据不能虚构结果。

## Claude Code项目级安装

```sh
mkdir -p .claude/skills
test ! -e .claude/skills/xjtu-paper-writer && unzip -n xjtu-paper-writer-v1.0.2.zip -d .claude/skills
claude
```

新会话显式输入 `/xjtu-paper-writer 规划一份课程论文`。自动选择不稳定时使用显式入口；文档说明不替代真实工具执行验证。

## OpenCode与已配置的DeepSeek模型

OpenCode支持项目.opencode/skills及兼容的.agents/skills、.claude/skills。如果上面已安装一份，优先复用并核对实际ID和路径，不创建同名不同规则。

```sh
mkdir -p .opencode/skills
test ! -e .opencode/skills/xjtu-paper-writer && unzip -n xjtu-paper-writer-v1.0.2.zip -d .opencode/skills
opencode
```

使用自己的已有Provider及获授权模型，输入“请加载xjtu-paper-writer技能，分析这份作业要求”，核对宿主实际skill工具加载和Python执行结果；不把模型给出代码当作已执行。不假定存在通用斜杠命令。历史OpenCode+DeepSeek独立安装仍有阻塞记录，本轮未重新验证模型调用。

目录与调用规则依据：[Codex项目目录](https://developers.openai.com/api/reference/cli)、[Claude Code Skills](https://code.claude.com/docs/en/skills)、[OpenCode Skills](https://opencode.ai/docs/skills/)。CLI版本差异应以实际帮助与加载路径核对。

## 授权作业目录

不要在安装目录写作业。选择用户拥有、不对其他用户开放写入的现有目录，不能是HOME、宿主配置目录或安装树的父/子目录。首次可在项目中建立独立目录：

```sh
mkdir -m 700 work
```

先明确授权该目录，再提供材料。安装树与work互不包含。请求JSON按references合同填写，相对输入输出从工作目录解析。例如（替换实际路径）：

```sh
python3 -B /你的安装目录/scripts/resolve_style_config.py --workspace /你的作业目录 --request request.json --output effective-style.json --preview style-preview.md
python3 -B /你的安装目录/scripts/build_experiment_report.py --workspace /你的作业目录 --request report-request.json --output-dir report
```

输出名称必须新建；已有文件不覆盖。配置、DOCX、图表、PDF和.xjtu-runtime缓存均留在授权目录。--help只读；JSON安全配置缺失时连帮助也拒绝，不得删除或弱化配置。复杂对象和语义审查未通过时不强行写入。

[Astron SkillHub](https://skill.xfyun.cn/space/global/xjtu-paper-writer)另有平台专用包。GitHub使用标准元数据与LICENSE，不将该平台的顶层version扩展或文档删减直接复制过来。校徽不属于[MIT](LICENSE)，见[资源说明](RESOURCE-SOURCES.md)。
