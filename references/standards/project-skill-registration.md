# 项目级 Skill 发现与独立验证

开发源始终是项目根目录。注册不等于触发成功；根目录有 SKILL.md 也不等于宿主已发现。Phase 5B-1 不改核心描述、不安装全局 Skill。

## 当前适配

Codex 使用 `.agents/skills/xjtu-paper-writer/`，Claude Code 使用 `.claude/skills/xjtu-paper-writer/`。两处入口 SKILL.md 与根文件为同一 inode 的硬链接；references、scripts、assets、tests 分别以 `../../../名称` 符号链接指向根资源。不要将 skill 目录直接链接至项目根目录：该结构会回到宿主发现目录，产生目录环。

实际 Codex CLI 0.167.2 的新进程未收录“入口文件本身为符号链接”的初版适配，换成硬链接后，真实 prompt-input 的 Available skills 中出现名称、原 description 和项目路径。因此不把文件存在当作发现证据。Claude Code 2.1.322 只完成路径准备，未宣称模型调用通过。

硬链接不复制内容，但有维护限制：编辑器若通过另存临时文件再重命名替换根文件，会断开 inode 绑定。更新入口后在新会话核对实际加载路径、资源访问及脚本 --help 结果；若失效，核对旧入口身份及内容，明确更新本项目适配，不能覆盖未知同名用户文件。打包/跨文件系统不能假定硬链接保留，需在目标宿主重新验证注册，不用全局复制掩盖问题。

资源引用以 Skill 目录为基准；脚本实际调用应确认目标是本项目 scripts，采用已验证的 Python 和接口，不猜命令。此适配不解除现有输出目录白名单、授权、冲突、保真或语义审查约束。

## 证据边界

新会话必须没有旧对话注入。正向请求不提供入口路径或要求 cat SKILL.md，以实际目录选择及读取命令区分自然触发与手动路径加载。显式名字调用、自然请求、无关 Python 请求分别记录。无附件只做需求识别与关键材料阻塞；不能寻找旧实验材料来伪造交付。

DeepSeek 是模型而不是发现 Skill 的宿主，后续应在实际兼容宿主中验收。完整跨平台、Word 视觉、长公式、数学字体、字符缩进仍按原计划保留。

## 官方依据

- [OpenAI 项目级安装目录](https://developers.openai.com/api/reference/cli)：Codex `.agents/skills/`、Claude `.claude/skills/`；修改后启动新会话。
- [Claude Code Skills](https://code.claude.com/docs/en/skills)：描述用于选择，支持项目级技能和显式调用。


Phase 5B-2 已进行真实 Claude/OpenCode 调用，旧“仅准备”的记载为 5B-1 当时状态。当前 OpenCode 可复用 .agents/.claude 两入口且观察到两种基目录，二者同源，不新增 .opencode 副本。自然触发失败和原生入口成功分开记录，详见 实跑结果。


Phase 5B-2R 未发现项目级禁止自动调用项，description 不作无依据扩大。Claude 原生斜杠、OpenCode 显式子任务均应检查实际资源与工具结果；原生 Skill、Agent 自行 Read 入口、显式宿主展开分别记录。三次相同请求不代表所有任务的概率，也不将一次成功称稳定。参见 复测。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
