# DOCX只读样式分析

入口：项目内 `scripts/inspect_docx.py`，仅依赖 Python 3.10+ 标准库。调用示例（输出必须不存在）：

```sh
python3 scripts/inspect_docx.py --workspace /你的作业目录 inputs/reference.docx --output outputs/new-style-config.json
python3 -B -m unittest discover -s tests -v
```

工具通过只读 ZipFile 解析 OOXML，不解压媒体、不调用 Word、不保存 DOCX。执行前后计算 SHA256；源文件变化则失败，不输出成功配置。CLI 拒绝覆盖已有文件、拒绝项目外输出及非 JSON 输出。输入错误、损坏 XML、非支持命名空间返回非零；解压后总容量超过 100 MB 拒绝处理。缺少 styles/theme/numbering 时保留 unknown，不安装依赖。

## JSON v1.0 合同

| 字段 | 含义 |
| --- | --- |
| schema_version | 当前为字符串 1.0；消费方不支持版本时停止导入 |
| source | 参考文件名、分析前后 SHA256 及 unchanged |
| source_role / priority | user_reference_style / 4；不是教师正式模板 |
| pages | 各节 pgSz、pgMar、分节类型、分栏、文档网格 |
| paragraphs | 主文档中全部段落的索引、样式 ID、角色判断、段落属性、逐 run 属性；不含文字 |
| heading_definitions | 标题/一级至三级标题的样式定义；defined_only=true 表示未被段落直接使用，不能当实际用例 |
| profiles | 正文、标题、图题、表题、参考文献等候选的样式频次及段落索引；只是候选，不是全篇统一格式 |
| tables | 表宽、网格列、行、单元格宽度/纵向对齐/合并/边框/段落索引、重复表头及条件样式声明 |
| images | 图片出现位置、DrawingML 尺寸或 VML 宽高、浮动标志、OLE 预览标志、邻近图题候选 |
| equations | 原生 OMML 对象数、所在段落及布局、显示/行内、编号模式候选；不含公式内容 |
| counts | 结构数量；图片为出现次数，不等于唯一图片素材数 |
| skill_defaults | 独立的 Skill 自定义规范，不属于文档提取值；合并优先级为 5 |
| uncertainties / scope | 未支持行为及未分析的其他部件 |

属性记录形如 `{"value":"21","source":"word/styles.xml/style[1]/rPr","status":"inherited"}`。

状态：explicit（段落/run 直接格式）、inherited（默认/样式继承）、extracted（结构属性）、theme_resolved（已解析主题槽）、candidate（角色/邻接判断）、default（Skill 自定义）、unknown（未确定）。未指定也用 null/unknown，不静默补 Word 默认值。unknown 可保留部分已读原始值及 reason，不能作为已确定参数使用。

`word/document.xml/p[7]` 等是工具按文档序生成的 **0 起始定位标识，不是可直接执行的 XPath**。嵌套表格/文本框段落也可能出现；段落数据在 inventory 中，表格单元格通过 paragraph_indices 引用，避免复制文字。source 相对于包内 XML 部件，方便复核。样式 ID 用于定位，不作为研究内容。

## 单位与解释

保留 OOXML 原始值，不把不确定单位统一转换：pgSz/pgMar/段落普通缩进和间距为 twip（1440/in，20/pt）；字号 sz/szCs 为半磅；firstLineChars 等为百分之一字符；run spacing 为 twip；图片 extent 为 EMU（914400/in）；表格宽度需同时读取 type（dxa、pct、auto）；边框 sz 为八分之一磅。行距 lineRule=auto 时 line/240 为倍数；exact/atLeast 时 line 为 twip，未给规则则保持未确定。下划线、粗体等保留原始开关值，不能将字符串 "0" 当真。

## 继承范围和保守降级

解析 docDefaults → 基础表格样式属性 → 段落 basedOn 链 → 字符 basedOn 链 → 直接格式，保留最后生效来源。段落标记的 rPr 不作为正文 run 的字体。样式层粗体/斜体按 toggle 处理，直接格式按开关覆盖。主题字体仅解析明确非空 latin/ea 槽；东亚槽为空时不猜测语言对应字体。主题颜色未解析时标 unknown。字体名称不是实际字体可用性证明。

编号级段落属性另行记录，尚未纳入最终段落级联。表格条件样式有声明时，受其影响且非直接格式的候选属性保守标 unknown；完整 tblLook/合并位置规则及单元格边框冲突尚未解析。直接/表格级边框均可检查，但网格表/三线表的最终视觉外观不能仅凭 tblBorders 判定。

标题用样式名称和 outlineLvl 识别，不仅靠字号；文档标题样式未被实际使用时不猜测首段角色。图表题注采用常见文字模式在内存识别，仅导出角色；图/表对应关系仅按 XML 邻近位置给 candidate，浮动对象或复杂布局需人工/未来渲染确认。参考文献用独立标题标记界定候选区，手工编号只导出模式，不导出条目。复杂标题、字段自动生成题注、文本框或列表标题可能无法识别。

只识别原生 OMML；legacy OLE 公式/其他对象只计数，不解码。页眉页脚、注释及脚注等部件列为未分析；没有执行视觉渲染或字体替换检查。

## Phase 3B 读取边界

先核对 schema_version、源 SHA256 和 source_role，再按既有模板优先级逐属性合并。教师要求优先级 1，正式模板 2，案例 3，用户参考样式 4，Skill 默认 5；来源身份由用户材料决定，文件名不能提升优先级。

仅使用已支持状态的属性；candidate 需选定样本或人工确认，unknown 不能覆盖可信来源。profiles 中同一角色存在不同样式/逐 run 差异时应保留差异，不直接把第一段当全篇标准；未使用的标题定义不能自动应用。Skill 默认与实际文档提取并存，冲突按来源及任务范围决策，不覆盖真实提取记录。内容保护仍遵循 [格式规范](formatting.md)，本工具不提供 DOCX 写入接口。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
