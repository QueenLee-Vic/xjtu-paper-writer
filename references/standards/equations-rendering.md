# 公式布局与页面渲染检查

扩展既有 format_docx.py；equation_layout.py 是其内部助手，不是第二套配置或写入器。render_docx.py 使用现有 LibreOffice、pdftoppm、pdftotext、pdffonts、fontconfig，无新增软件包。schema 1.0、冻结默认及全局待验证组不变。

## 公式分类与安全范围

inventory 按段落记录独立 m:oMathPara、行内/未编号、字面编号、已有制表位、表格内及复杂多行结构。只有主正文中的单个短 m:oMath、一个已存在的字面数字编号、无其他正文/域/复杂结构、单个明确 A4 纵向节才允许试排。编号必须位于公式之后。最多 50 字符仅是保守筛选，不是宽度通过证明。复杂运算结构、多行、表格、显示容器、长公式、RTL、装订线、分栏、多节或非零左右段落缩进均拒绝，保持原结构。

--equation-indices 接受明确的 0 起始段落序号 JSON 列表；整个公式几何属性组须在授权范围，目标配置必须明确。本次在仅排版模式只增加定位 tab 运行和直接段落属性；原 OMML、文本、编号及顺序不变，不插入公式或重新编号。从零创建公式不由本写入器隐含授权，测试公式由独立合成 fixture 显式构造。

## 原生制表位替代方案

[微软 TabStop 文档](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.tabstop) 规定相对段落前沿定位；[TwipsMeasureType](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.twipsmeasuretype.val) 说明物理属性的二十分之一磅单位。本实现没有将 19.9/39.81 字符乘字号；原字符参考仍保存在布局报告和默认配置。

本次采用 **physical_text_area_tabs** 替代方案：实际页宽减左右页边距得到正文宽度，设中点 center tab 和正文右界 right tab，leader=none；在原公式和原编号前增加 tab。公式段落保持两端对齐、单倍、首行 2 字符、段前后零。原公式本体不改 m:jc、不转换图片，也不将“公式+编号”整段居中。

测试 A4 为 11906 twip、左右各 1800 twip，正文宽度 8306 twip；制表位为 4153/8306 twip。这是页面几何推导，不是字符制表位换算，更不声称与用户 Word 字符设置等价。首行缩进、字体、公式宽度的实际效果仍需渲染；不能从两个物理数值直接宣布几何通过。

## 保真扩展

snapshot 增加可选、明确的 equation_targets。只对这些已安全筛选的段落，在内容投影中忽略纯 tab 运行及 pPr/tabs；仍逐个比较完整 OMML、文本/编号顺序、表格和其他包部件。未选中的公式及复杂段落继续比较完整子树。格式属性差异必须有授权日志。只放宽定位所需结构，不忽略数学对象变化；故障注入修改公式内容会阻止输出发布。

输出仍是另存测试文件，写入器保持 formula_geometry_ready=false、full_ready_for_writer 原值和待验证组。布局输出是待渲染候选，不是自动解除全局阻塞。只有独立 readiness-and-geometry.json 中实际量测样本可标为本环境验证，不回写默认配置。

## 渲染与量测

```sh
python3 -B scripts/format_docx.py --workspace /你的作业目录 INPUT --config CONFIG --output NEW_DOCX --report NEW_REPORT --equation-indices INDICES_JSON
python3 -B scripts/render_docx.py --workspace /你的作业目录 NEW_DOCX --output NEW_RENDER_DIRECTORY --checks OPTIONAL_GEOMETRY_JSON
```

输出到授权工作目录中的新目录，不覆盖既有文件。LibreOffice使用私有挂载/网络命名空间，IPC、缓存、临时文件和UserInstallation均落在工作区。子进程超时60秒；Poppler生成页面文本坐标及85 DPI预览。宿主拒绝命名空间时明确报告阻塞，由用户决定是否授权正常原生环境执行，不取消工具安全边界。

--checks 仅为已知合成公式的唯一 token、原编号及左右边距（pt）量测规格，不用于导出参考论文内容。PDF 中全角编号可能被拆成多个字形，检查器按同行位置拼接，不降低容差。量测本体 bbox 中心与正文中心差，以及编号最右 bbox 与右边界差，容差 2 pt；仅对应被测 token，不泛化到复杂数学的视觉中心。未提供 checks 表示未量测公式，不应将 formula_geometry_passed=false 误读为已验证失败。

renderer 同时报告页面尺寸/数量、PDF 字体清单、fontconfig 匹配、页外文字 bbox 数量。没有页外 bbox 不等于无溢出；页边距、行距、图表位置、字体每字形回退和分页仍有人工检查项。LibreOffice 不是 Word，可能刷新域的 PDF 显示值；源 DOCX 哈希仍核对不变。

## 状态和字体

分开报告：内容保真、基础 ZIP/XML/关系检查、实际写入属性、PDF/PNG 生成、公式 bbox 几何、Agent 页面抽查、用户人工确认及 Microsoft Word 验证。宋体和 TNR 在当前环境可用且出现在 PDF 字体表；Cambria Math 探测回退至 Latin Modern Math，样本公式 PDF 实际还使用 Liberation Serif Italic。不能认定“字体名称正确”等于所有字符无替换。

当前两条简单公式 LibreOffice 几何通过；长公式样本确有 1 个页外文字 bbox，未强行修改。多行/行内/表格内及参考文档公式未定位。完整公式、整篇视觉及 Word 就绪均保留 false；不能直接据此进入 Phase 4 的全面验收。



Phase 3B-2C 的缺项审计、长公式溢出阻塞及显式原生分页计划见 [分页与内容审计](pagination-audit.md)。保真通过不代表用户描述的另一参考版本已验收，数学字体和复杂公式仍保留限制。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
