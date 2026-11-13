# 可复现数据绘图与授权 DOCX 插图

此文件扩展 [配图计划](figures.md)，只在需要数据图或已授权的实际插图时加载。不启动润色；不把测试数据称作真实实验。Phase 3 的长公式、数学字体、参考版本和 Word 验收待办仍保留。

## 数据绘图

`python3 -B scripts/plot_scientific_data.py --workspace /你的作业目录 --config CONFIG.json --output-dir NEW_DIR`：输出到授权工作目录中的新目录（示例可使用 outputs/）；拒绝覆盖。依赖已有 Matplotlib/NumPy/Pillow，字体由当前 fontconfig 查找，不安装或分发。

请求 schema_version=1.0，例如（项目内相对数据路径）：

```json
{
  "schema_version":"1.0",
  "figure_id":"measurement",
  "chart_type":"multi_line",
  "source":{"source_type":"user_data","source_path":"data/measurements.csv","source_reference":"用户实际测量文件及实验条件说明"},
  "x_column":"time",
  "y_columns":["voltage_a","voltage_b"],
  "units":{"time":"s","voltage_a":"V","voltage_b":"V"},
  "labels":{"x":"时间","y":"电压"},
  "series_labels":{"voltage_a":"方案 A","voltage_b":"方案 B"},
  "caption":"两组实测电压比较"
}
```

source_type 为 user_data/program_results/public_dataset 时必须有文件及具体来源声明，但仍标 source_attested_not_independently_verified。没有真实数据就停止对应结果图；仅软件测试可用 synthetic_test_data 加 allow_synthetic_test_data=true，并强制在图内、题注及清单标明合成测试。旧 synthetic_example 不会因此变成实验数据。

格式支持 CSV/TSV UTF-8、JSON 数组或 records 数组、JSONL 对象行。XLSX 使用标准库 ZIP 加 lxml，只读单个明确工作表的字符串/数值：支持共享字符串和 inlineStr；多表需 sheet，公式、非零样式索引（包括可能的日期/格式化数值）及未知单元格类型拒绝，要求显式导出 CSV。不是完整 Excel 引擎，不猜自由文本日志，不重新计算公式。

chart_type：line、multi_line、scatter、bar、errorbar。每个使用字段必须存在且数值有限；x/y 单位必填，允许显式 dimensionless；多 y 单位必须一致，不自动转换。柱状图 x 可是分类标签，重复分类拒绝自动聚合。line/multi_line/errorbar 的逆序 x 需显式 sort_x；重复观察保留并报告。NaN、无穷和非法数据拒绝；缺失值默认拒绝，preprocessing.drop_missing=true 才能删除并记录行号，sort_x=true 才能排序。没有插值、平滑、归一化或自动异常值剔除；稳健偏离提示不改变数据。

误差棒必须声明 error.method 和 meaning：

- replicates：按相同 x 分组；每组至少 2 个实际观察，计算均值及样本标准差 ddof=1，或标准误 SD/√n。保存各组 n，图内及题注说明含义。
- provided：指定 column 及同 y 单位；负误差拒绝。meaning 可以是 sample_standard_deviation、standard_error、confidence_interval、provided_uncertainty；CI 要给 0—1 内的 confidence_level。来源提供的误差不会被称为本工具重新计算，当前仅对称 y 误差。

保存 plot-config.json、plotted-values.json、artist-values.json、figure-record.json 和 300 dpi PNG/SVG。实际 Matplotlib artist 数据与所选数据核对，误差棒跨度与计算值核对；配置、数据及输出哈希记录，可用保存的配置重跑。固定 SVG hashsalt、移除图内时间元数据；相同环境输入/配置的 PNG/SVG 测试哈希相同，跨版本/平台像素一致不作保证。generation_timestamp 仅在旁车记录，文件哈希不证明科学真实性。

旧版 Matplotlib 使用文本级字体：含中文标签整体宋体，纯西文标签 TNR，因此混合标签中的西文也是宋体。记录实际字体/替换及此限制，检查缺字和画布边界；不声称逐字形字体成功。SVG 默认转轮廓，未分发字体文件，PNG 固定当前呈现。图例、科学解释、灰度打印和真实数据来源仍需按任务审查。

## 插图合同

`scripts/insert_figure_docx.py INPUT.docx --output NEW.docx --manifest MANIFEST.json --request REQUEST.json --config EFFECTIVE.json --report REPORT.json`。

复用 Phase 3 的 read_package、snapshot/compare_snapshots、保守 caption 格式写入、分页模块与原子发布。没有另建文档格式优先级系统。最终样式来自已有 resolver schema 1.0/合同 1.2，教师仍优先；未解决的实际插图属性阻止执行，公式全局未就绪不被改写。输出及报告位于授权工作目录，新文件、不覆盖原件。

资源可为 A1 的 figures 清单或 B 的单条 figure-record；C/D 已登记的项目内 PNG/JPEG 通过来源/权限声明后也可提供 docx_interface，但其真实性和授权仍非独立核实。SVG 保留为原图，插入经过检查的 PNG/JPEG，禁止执行任意 SVG 或静默转换。校验媒体类型、像素、哈希、比例、页面宽高及所处节；多栏/未知节几何和无法容纳的图片题注对拒绝。记录实际显示宽度、有效 DPI；低清输入不能因为 OOXML 有路径就称清晰。

请求必须带 schema_version=1.0、mode=create/modify、精确 source_docx_sha256、authorized_image_ids、insertions 列表。每项：image_id、authorized=true、needed=true、quality_approved=true、quality_review_basis、position，width_cm 可选。资源默认 insertion_authorized=false；新的绑定输入哈希的显式授权请求才允许新增。quality_approved 是调用方审查声明，不冒称程序独立确认科学真实性。合成图还需 allow_synthetic_test_data=true。

position.kind/value 支持：

- paragraph_index：直接 body 段落的零基索引，不包括表格内部段落。
- paragraph_id：唯一的 w14:paraId。
- bookmark：唯一书签所在直接 body 段落之后。
- exact_reference：完整段落严格相等，不作模糊匹配。
- section_end：唯一且具语义标题样式的同名章节末尾，在下一个同级/更高标题之前。

所有位置针对原稿解析，再逆序插入；多个候选、节边界或复杂容器定位拒绝。书签不移动、不删除。当前不支持图片替换/删除、复杂子图自动拆装、表格/文本框内插图或跨宿主执行。

新增图片独立居中、等比、限当前节正文区域，题注在下方；新图题参数由原写入器读取有效 caption.figure.*。存在唯一安全图题样式时复用该语义样式，无唯一样式时仅应用明确的直接格式。新图片和图题通过既有 pagination_layout 设置 keepNext/keepLines，只操作新增块，不借此改动旧段落分页。

图号只追加在现有最大号之后，不改原图号/题注/交叉引用；用 docPr 的稳定 image_id 摘要标记拒绝重复插入。已存在重复图号、章节式/无法解释的编号、SEQ 域或不支持的教师编号策略拒绝；当前使用显式文字题注，不伪称建立了自动 SEQ/交叉引用。若新图插在旧图之前，numbering_review 报告数值顺序需人工决定，不能静默重编号。

format_only 无条件禁止新增；文字润色任务不调插图。modify 只允许授权 image_id；本程序不改原图大小和原正文。create 也必须绑定输入骨架与图片授权。

## 保真及发布

保留原 ZIP 部件和未知结构，仅追加两个 body 段落、媒体、关系及 content type。日志记录确切新增块位置/摘要、关系/媒体哈希。写临时包后重新读包：仅剔除这些精确授权新增项，要求原 document 的规范 XML 全等、原关系与 content types 规范 XML 全等、其他原部件逐字节全等，再运行原分层快照（OMML、文字顺序、表格、媒体、域、页眉页脚、脚注尾注等）。任何不明变化拒绝发布，临时件清理，输入哈希复核，原子硬链接拒绝覆盖并发目标。

原媒体另做可用栅格解码检查；不支持或损坏的原资源保留并报告视觉风险，不能将结构保真当渲染无损。数字签名/受保护文档拒绝。复杂对象仍保持原字节，但全 ECMA XSD、Word 行为和宏等语义不能因此被宣称完整验证。

用现有 render_docx.py 的授权工作目录中的新目录执行 LibreOffice→PDF→PNG；配置写入、内容保真、PDF 几何、Agent 抽查和用户/Word 验证分别报告。生成物应另存来源、保真及页面检查记录。

多序列图的纵轴应描述共同物理量和单位，图例使用series_labels或列名，不从纵轴名称借用。核对图像配置、输入数据及实际内嵌资源的绑定，既有输出不得覆盖。


Phase 5A 输出可在自身测试目录内复用这些工具，不再写回历史阶段。调用成功退出后仍需读取每图 status、实际路径和来源；计划器可能安全阻塞而没有生成图。当前词法分类对否定短语（例如含“非实验截图”的解释用途）可能过于保守，Agent 须核对真实意图并形成新版本计划，不把阻塞算生成成功，也不能借示意图声明绕过真实实验结果门槛。DOCX 新图号的段首启发式仍可能混淆正文图引用，新增写作应给出明确语义和引用位置，发现歧义保守复核，不自动改原图号。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
