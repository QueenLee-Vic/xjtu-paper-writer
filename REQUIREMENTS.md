# 依赖

Python 3.10+；lxml；科学图使用 Matplotlib/NumPy，示意图 PNG 使用 Pillow。新报告构造器目前只支持已验证的 Pandoc AST 1.20（Pandoc 2.9.2.1）；遇其他 AST 版本拒绝猜测。XLSX 是有限的字面值解析，不猜公式或日期缓存。

PDF/页面检查使用 LibreOffice、pdftoppm、pdftotext、pdffonts、fc-match。缺宋体/Times New Roman 要报告替换，不自动下载字体。复杂数学字体仍可能回退。

安全工作区入口要求 Linux x86_64/aarch64 的 Landlock ABI≥3；其他系统及禁止此系统调用的沙箱会阻塞，不提供不安全回退。Codex、Claude Code、OpenCode 为宿主；模型和文献检索能力由用户已有环境提供。

baoyu-diagram、Humanizer-zh-academic 均为可选，缺失使用内置方案。不会自动安装软件、字体或账号。

安全PDF渲染另需已安装的 bubblewrap（bwrap）及允许非特权用户/挂载命名空间的Linux环境；IPC目录绑定到工作区，宿主/tmp不授予写入。宿主禁用命名空间时保持blocked，不自动安装或绕过限制。
