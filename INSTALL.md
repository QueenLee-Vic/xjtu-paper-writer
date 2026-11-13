# 项目级安装与使用

完整解压目录，不要仅复制 SKILL.md。先确认目标不存在，避免覆盖已有 Skill。

- Codex CLI：安装在项目 `.agents/skills/xjtu-paper-writer/`；新会话显式输入 `$xjtu-paper-writer` 或“请使用 xjtu-paper-writer …”。
- Claude Code：安装在项目 `.claude/skills/xjtu-paper-writer/`；新会话显式 `/xjtu-paper-writer 任务要求`。
- OpenCode：优先复用其支持的 `.agents/skills/` 或 `.claude/skills/` 入口，确认宿主返回的实际加载目录；不要多份不同规则。选择自己已经配置且获授权的模型，不要求任何特定 Provider。DeepSeek 是模型，OpenCode 是宿主。

发现机制由宿主版本决定；自动选择不稳定时使用显式入口，核对 references 的实际加载与工具执行结果。不要修改全局 API 配置或复制凭据到 Skill。

## 独立工作目录

准备用户拥有且不对组/其他用户开放写入的现有目录，与安装树分离。以下为已实现的公共参数：

```sh
python3 -B /你的安装目录/scripts/resolve_style_config.py --workspace /你的作业目录 --request request.json --output effective-style.json --preview style-preview.md
python3 -B /你的安装目录/scripts/build_experiment_report.py --workspace /你的作业目录 --request report-request.json --output-dir report
```

请求 JSON 按对应 references 合同提供。全部相对路径按工作目录解析。输出必须使用新名称；图表、DOCX、PDF、质量报告及 `.xjtu-runtime` 缓存均留在该目录。当前版本不代替用户决定目录授权；宿主执行前应明确授权。未指定目录会拒绝业务执行，`--help` 可安全查看。

安全运行目前要求 Linux x86_64/aarch64、Landlock ABI≥3。缺少内核能力时不降级写入。勿以 HOME、宿主配置目录或 Skill 的父目录作为工作区。已有文件只读使用，输出另存。不要把作业目录重新打包成 Skill；维护构建采用单独的文件白名单。

## 获取与校验

本地准备包名为 `xjtu-paper-writer-v1.0.1.zip`，解压后的顶层目录为 `xjtu-paper-writer/`。公开仓库和Release建立后，从 `QueenLee-Vic/xjtu-paper-writer` 的Release获取完整ZIP及配套SHA256，先核对下载哈希，再解压到上述项目级入口。不要把整个开发目录、历史测试日志或用户作业作为Skill安装。

[MIT许可](LICENSE)的版权署名为QueenLee-Vic；校徽不在MIT范围，见[资源说明](RESOURCE-SOURCES.md)。
