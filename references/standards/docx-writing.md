# DOCX基础排版接口

工具为 scripts/format_docx.py，依赖现有 lxml 和 Python 标准库；没有安装新包。复用 resolve_style_config.py 的 load_json/normalize 和 effective_style schema 1.0、writer_contract 1.2，不重新提取样式。

```sh
python3 -B scripts/format_docx.py --workspace /你的作业目录 outputs/basic-input.docx --config outputs/writer-config.json --output outputs/new-formatted.docx --report outputs/new-report.json
```

输出 DOCX/报告必须是授权工作目录内的新文件，不能覆盖输入或既有输出。--scope 接受精确属性键 JSON 列表，与配置允许范围取交集；--role-map 接受主文档段落 0 起始序号到 body/title/heading.1—3/caption.figure/caption.table/references/table.cell 的明确角色映射。人工映射需来自任务授权，不能靠字号猜测。

## 实际支持

只修改 document.xml 的授权直接格式，不重建文章，不改共享 styles.xml。标题沿用已有 pStyle、样式名/basedOn/outline 语义，保留层级；不可靠的自定义样式跳过。图表题注按明确样式或“Caption 样式 + 图/表标记”识别，不改文字、编号、顺序，也不搬移图片或段落。参考文献按明确 Bibliography 样式或独立“参考文献/References”区域识别；复杂非标准区域需显式映射。

支持页面尺寸/方向/边距和页眉页脚距离，逐个保留 sectPr；有公式或 OLE 对象时跳过页面变更，避免间接改变公式区域。正文与可靠标题/题注/参考文献支持 East Asia、ascii/hAnsi、半磅字号、RGB、粗斜体、对齐、字符首行/悬挂、物理悬挂、倍数及 exact/at_least 行距、段前后。首次指定字符缩进时移除互斥物理属性，不把字符换算成固定磅数。

简单表格直接设置网格/三线边框及单元格边框覆盖，不重建行、列、gridSpan/vMerge/hMerge。三线表首行作为表头分隔线，复杂多层表头不作推断；存在复杂对象、嵌套或浮动定位的表格跳过。表格内字体使用 table.cell 四项；可选 table.cell.alignment/first_line_chars/line_spacing/space_before_pt/space_after_pt 可由既有配置解析器的来源记录明确提供，缺省不自动套正文缩进，也不新增默认来源。

图片只对安全的独立单个 inline 图片段落居中，不改 extent、媒体或图片编码；anchor、混排及复杂图片保留。图片限宽/清晰打印策略、图表重新编号和题注位置移动等未执行，均在 skipped_properties 报告。

## 部分就绪与复杂对象

所有 equation.* 一律不执行，即使输入配置被手动改写为 apply=true；公式相关段落完整跳过，OMML 保持原状。待布局验证组保留，global ready_for_writer 不改为 true。报告独立给出 partial_ready_for_supported_operations、partial_scope_execution 和 full_ready_for_writer，只有当前已支持操作在自身范围完成，不表示整篇格式完成。

当前 scope 内未解决的用户确认直接拒绝；待公式几何验证不阻碍其他安全对象。对域、修订、文本框、批注/注释锚点、脚注/尾注引用、OLE、未知段落/文本运行结构及浮动图所在段落保守跳过。页眉页脚、脚注、尾注、关系、样式、媒体和其他包部件原字节复制，不格式化。保留包内未知结构不等于已验证其渲染或交互行为。

## 分层保真与发布门槛

1. 读取 ZIP：CRC、重复条目、100 MB 解压容量上限、必要部件、XML 可解析、内容类型覆盖及内部关系目标存在；拒绝 DTD/实体和数字签名包。未执行全量 ECMA XSD 校验或 Microsoft Word 打开验证。
2. 修改前快照：主文档去除已实现格式节点后的 canonical XML 摘要、正文 t 顺序、每个 OMML 对象、危险段落完整子树、其余部件原字节 SHA256 和部件名集合。表格结构、书签、超链接属性、域、修订等均在树中；其他部分包括页眉页脚、注释、脚注尾注、关系和嵌入资源。
3. 格式授权审计：每次 setter 记录属性、节点路径及实际属性变化；原/新全树属性差异必须与计划逐项吻合。内容投影忽略格式，不代表允许任意改格式；未计划的字体或对象属性变化也拒绝。
4. 保存到同目录临时文件后重新读取输出包，重新生成所有快照。差异不明、源哈希变化或包检查失败时不发布 DOCX；CLI 返回非零，错误说明在 stderr，不能报告通过。
5. 用原子硬链接发布新输出，已有目标不会被替换；finally 清理本次临时文件。报告单独保存；若报告写入失败，CLI 报错，已验证 DOCX 可能已发布，不会覆盖或删除它。

报告只保留哈希、属性名、位置和状态，不导出学术正文。结构一致性通过与视觉通过分开；运行报告明确 visual_verification=not_performed。写入器只验证所支持 OOXML 结构和部件保存，不宣称任意复杂对象完全无损或最终 Word 排版验收。



公式布局扩展：默认仍不动公式；仅明确 --equation-indices 时使用 [有限公式定位及渲染规范](equations-rendering.md)，目标输出必须位于授权工作目录的新路径。原 2A 保护和测试继续适用，不能把该显式试排视作全局公式就绪。

[段落/Run 映射与预览](docx-text-mapping.md) 复用本合同的包检查和快照，但不调用格式写入或润色写入。它仅提出原 w:t 的候选补丁，所有写入许可保持 false；实际局部改文、另存及输出保真留给独立授权的 4B-2B。


[局部润色写入](docx-polishing-writing.md) 复用本合同 read_package/snapshot/compare_snapshots 和临时文件/原子新路径发布；沿用图片插入模块的授权增量验证原则，只允许已有 w:t 和必要 xml:space 的变更。它不调用本格式写入器，不修改任何格式配置、对象或其余部件。


新稿可使用兼容版本Pandoc转换后调用排版器。表格宽度应在新稿源AST中明确，并验证内容未变；不重建已有用户文档。字符单位缩进在LibreOffice的显示可能不同，冻结规范不变，需单独检查。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
