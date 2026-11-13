# DOCX段落与Run安全映射

Phase 4B-2A 只读实现；不写入或重建 DOCX。按需从 [学术润色规则](../workflow/academic-polishing.md) 加载。复用 Phase 3 的 read_package/snapshot/compare_snapshots、Inspector 样式继承，Phase 4B-1 的完整保护与逐项语义审查，以及 Phase 4A 的精确来源绑定思路，不另建 ZIP/样式或润色系统。

## 工具与数据

```sh
python3 -B scripts/map_docx_text.py --workspace /你的作业目录 INPUT.docx --output outputs/NEW-map.json
python3 -B scripts/plan_polishing_docx.py --workspace /你的作业目录 INPUT.docx --mapping MAP.json --request REQUEST.json --candidate CANDIDATE-document.json --semantic-reviews SEMANTIC-list.json --output-dir outputs/NEW-preview
```

输出必须是授权工作目录内的新文件/目录，拒绝覆盖。只接收授权工作目录内的 DOCX，使用已有 lxml、标准库和已有分析程序，不安装依赖。读取包校验 ZIP/XML/类型/关系及源哈希，并前后复查全部原件部件和 Phase 3 快照。已有包检查拒绝的签名/非标准文档仍拒绝，不能声称完整 ECMA XSD 或 Word 打开验收。

map 的 schema_version=1.0、kind=docx_text_map、mapping_contract_version=docx-map-1.0；包括源路径/字节哈希、mapping_hash、段落/Run/对象/章节、各故事部件、完整部件哈希、Phase 3 快照和 polish_document。映射本身不是修改授权。

## 稳定标识和坐标

- 段落 ID：部件路径 + 部件内唯一 w14:paraId；缺失/重复时使用部件路径 + XML 结构路径。原生 ID 重复不随机选第一项。
- Run/对象 ID：部件路径 + XML 结构路径；记录原始 XML 摘要。相同段落文本不合并，定位不靠正文搜索。
- 所有标识绑定源 DOCX SHA256 和完整 mapping_hash。路径回退仅保证同一快照内定位，不承诺结构编辑后的跨版本稳定。源文件被另存、结构或文本发生变化必须重新映射。
- range 使用 Unicode code point 半开区间，不是 Word COM UTF-16 偏移。对象用逻辑占位符投影，这些位置不是实际 Word 字符位置。复杂对象段落不产生文本补丁；后续不得把占位符写进文档。
- 文本摘要沿用 polish-1.0 的规范 JSON UTF-8 标量哈希，同时给出 raw UTF-8 摘要，字段语义不静默替换。

后续写入器应在精确源包中重新枚举段落/Run/文本节点的 ID、结构路径和哈希，而不是只匹配正文，也不能对外部缓存 XPath 不加核对就执行定位。完整来源绑定比文本相同更严格。

## 识别与保护

识别正文、总标题、多级语义标题、图/表题、参考文献标题及范围、表格段落、辅助故事、超链接、域、书签/批注范围、OMML、图片、修订、格式修订、文本框及内容控件。域和书签跨段延续时，中间无显式标签的段落也只读；不平衡域/范围把相应故事标为不可编辑。

标题优先 outlineLvl、样式链及可靠语义名称，不凭字号、加粗或短句赋等级。参考文献标题标记与后续语义标题界定范围；未知自定义样式保守待处理。候选题注按原提取状态记录，不冒充教师模板的确定参数。

每个 Run 记录原文、逻辑范围、文本节点路径/摘要/xml:space、原 rPr XML/属性、字体及字符属性的显式/继承/unknown 状态和 format_signature。East Asia、ascii/hAnsi 分开处理；加粗、斜体、下划线、颜色等由已有 Inspector 提取，未展开属性仍保留在原 XML 指纹。条件表格样式不能准确解析时保持 unknown，不能伪称最终实测字体。

对象记录实际源 XML 哈希和锚定段落、路径、关系/书签属性；OMML 区分行内/独立对象。主文档以外的页眉页脚、脚注尾注、批注等可读但不可润色。表格、题注、参考文献、域、超链接、书签、修订、文本框、内容控件、节边界或未知结构的段落不产生可执行文本映射。保护文档或开启修订跟踪时也只读。

这是已识别结构的逻辑投影，不是最终排版视图：修订/域/复杂对象不自动接受、更新或计算；所有其他包部件也以哈希保留。未知对象的渲染和交互仍未验证。

## Run 归属策略

| 情况 | 当前预览策略 |
| --- | --- |
| 单个普通文本 Run | 原节点内的替换候选，保持完整 rPr/pPr |
| 多个 Run，全部格式签名相同 | 可跨 Run 计划；按原长度分配到原 w:t，剩余给最后节点，保留所有原节点，包括可能变空的 w:t |
| 混合格式，唯一单 Run 的局部变更 | 其他 Run 的原文/位置顺序必须完整不变，以前后锚点唯一确定归属 |
| 混合格式跨 Run 重组、归属多解或某个格式组消失 | 待人工处理，不让加粗术语扩散为整句加粗，也不自动移动强调 |
| 多 w:t、tab/break、对象混排或复杂容器 | 映射只读，拒绝补丁 |

format_signature 同时包含完整原 rPr、Run 属性、段落样式及 styles.xml 哈希；不是只比较粗体或字号。可行性表示结构归属受限可确定，不代表 Word 视觉效果已验证。新换行/制表位或无效 XML 字符不当作普通文本写入。

提出的操作只有 existing w:t 的文字及必要 xml:space；需要保存首尾空格时规划 preserve，其他 Run、段落、样式、对象、关系和媒体均不可改。没有清空段落、替换整个 Run、复制正文生成新 DOCX 的程序。

## 授权范围

请求延续 Phase 4B-1 字段，新增 mapping_hash 和 authorization。request.document 必须逐项等于实际映射导出的 polish_document；不能删除公式/引用/对象再检查。

scope 支持：document（主文档）、paragraphs/paragraph_ids、sections/section_ids 或唯一完整 section_titles、ranges。章节默认含子章节，可明确 include_subsections=false；重名/未知范围拒绝。指定文本范围示例：

```json
{"kind":"ranges","ranges":[{"paragraph_id":"p...","start":8,"end":15,"allow_end_insertion":false}]}
```

range 不允许重叠，end 不包含在普通替换区间中；尾部插入需明确 allow_end_insertion=true。段落范围则允许其内部及结尾的局部插入。差异必须完全落在授权原文范围内，不能用全文替换绕过边界。

authorization 至少有 granted=true、实际 source_docx_sha256、scope_sha256（规范 JSON 范围摘要）和具体 basis。授权来自实际用户任务，脚本只核对绑定声明，不替用户授予权限。仅检查或仅排版没有新增编辑权限；这些模式的改稿会拒绝。

## 保护与语义证据

适配器将 ranges/子章节解析为 Phase 4B-1 段落集合，再附加精确字符范围校验；重新执行既有数字/单位/公式/引用/术语、范围/结构/对象与十项语义审查。缓存报告或单个 ready=true 没有放行权。

每个实际语义审查记录保留 B1 的逐项状态、前后片段、理由、身份及单元哈希；另须绑定 docx_source_sha256、mapping_hash、source_document_hash、candidate_document_hash 和 task_hash，且显式 simulated=false。task_hash 包含模式、操作、强度、原始范围、保护策略 SHA、术语/单位/术语修正与跨段计划。改强度、扩范围或换上下文后必须重新审查，不能自动补字段升级旧评审。

模拟、缺项、不确定、哈希/引用片段不符，或硬保护失败时，后续候选资格为 false。实际语义记录仍是 Agent/人工的有据声明，不是独立科学真值或身份认证；不确定就保留待审。

Word 对象占位和 B1 全文交付状态原样保留。源 Word 中含公式不意味着其他普通段落不能形成局部预览，但 all_planned_edits_mapping_eligible 与 full_text_delivery_ready 分开；任何一项不等于本阶段写入许可。未来局部编辑必须直接保留原对象，不将逻辑投影重新生成正文。深度跨段内容重组当前只做保护审查，Run 写入归属仍拒绝。

## 计划和下阶段接口

计划含目标 ID/路径、原文与候选及哈希、源段落/Run/文本节点摘要、范围、拟改 Run、保留格式/部件、保护对象、风险/待定项及语义结果。CLI 同时输出 plan.json/preview.md，不生成 DOCX。

future_writer_contract 在 polish-1.0 基础上添加 mapping_extension=docx-map-1.0，不改旧 B1 结果：paragraph_mapping_verified 表示源映射已核实，simple_scope_mapping_eligible 表示所有拟改项满足当前局部映射条件。docx_write_ready=false、docx_write_performed=false、final_publish_status=preview_only_phase4b2a 始终保留。即使所有候选合格，本阶段也不写入。

4B-2B 需独立授权后重新验证源文件、映射、任务和审查证据，对原 w:t 应用精确补丁并复用 Phase 3 的原部件/对象保真及未授权变更检查。源段落/run/t 或任何样式/非文本对象变化即拒绝；另存新输出，不改原件。实际保存、内容保真、渲染和 Word 验证属于后续验收，不得提前标完成。



## Phase 4B-2B 的兼容消费者

映射/计划器保持本文件的只读行为和旧 false 字段；实际消费者见 [局部润色写入](docx-polishing-writing.md)。它重新计算整个计划后，只对当前受限资格且获实际授权的文本补丁执行写入，独立记录 polish-write-1.0 执行与输出保真，不将预览状态改成全局就绪。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
