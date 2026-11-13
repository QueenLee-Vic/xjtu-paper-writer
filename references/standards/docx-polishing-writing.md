# DOCX授权局部润色写入

仅在收到实际改文授权、完成 [学术润色保护](../workflow/academic-polishing.md) 和 [映射/计划](docx-text-mapping.md) 后加载。工具 scripts/apply_polishing_docx.py 消费既有 polish-1.0、docx-map-1.0、schema_version=1.0；独立执行记录 execution_contract_version=polish-write-1.0。它不生成语言、不调用格式写入器，也不修改冻结默认样式。

## 输入与执行

```sh
python3 -B scripts/apply_polishing_docx.py --workspace /你的作业目录 INPUT.docx --output outputs/NEW.docx --plan PLAN.json --mapping MAP.json --request REQUEST.json --candidate CANDIDATE.json --semantic-reviews SEMANTIC.json --report outputs/NEW-report.json
```

全部用户输入路径应位于授权工作目录；映射器执行源文件路径检查。候选为完整 document 投影；未授权段落、元数据、顺序和逻辑对象占位必须原样保留。工具最终直接保留源包对象，绝不把含占位符的投影重新生成 Word。输出与报告限定授权工作目录中的新路径，拒绝覆盖、输入同路径及输出符号链接。不允许借建议模式或仅排版模式写入。JSON 解析复用已有重复键拒绝机制。

重新调用 build_plan：验证原件字节 SHA、映射自校验和重新映射、完整原文、段落/Run/文字定位和哈希、原格式签名、源与范围绑定授权、全部保护检查、候选及逐项语义证据；整个新计划必须与所提供计划一致。计划字段、候选、强度、范围、策略、源或审查输入发生变化都必须重新生成相应证据。缺项、错误、不确定、模拟审查或含义变化阻止整个批次，不悄悄只写通过的子集。

语义证据须有实际 Agent/人工逐维度判断、真实片段与理由，绑定完整源投影/候选/任务、DOCX、mapping 和前后单元哈希。哈希能识别被审版本，不能证明审查结论正确；不把布尔值、正则检查或测试导出器当语义模型。

4B-2A 的 current_phase_write_allowed=false、future_writer_contract.docx_write_ready=false 及 B1 的全文对象重组状态保持原样。4B-2B 的实际调用使用独立执行授权和当次重新核验的局部资格；不是改写历史预览的全局许可。execution-report 单独记录 write_performed/output_published/fidelity/rendering 等实际状态。

## 安全修改范围

- 单 Run 普通文本：修改原 w:t 的 text。
- 格式签名完全一致且每 Run 只有一个直接 w:t：沿用既有分配计划，保留所有 Run/文本节点，包括替换后空节点。
- 格式不同：只支持唯一可归属的单 Run 局部编辑，其他格式锚点文字不变。例如仅把加粗术语后普通 Run 中的“进行分析”改为“开展分析”，术语加粗 Run 原封不动。
- 全文、章节（含子章节配置）、段落或 Unicode code point 半开文本范围沿用映射合同；全文授权仅允许其中安全正文，并不放开复杂对象。仅检查/没有变化不生成 DOCX；格式模式有改稿则拒绝。

只改明确授权且重新匹配的既有 w:t.text，首尾空白需要时更新该节点 xml:space。保留 w:rPr、w:pPr、属性、样式、节、字符样式及所有非目标节点；不增删或清空 Run/段落，不调用 paragraph.text 等重建 API。

混合格式跨 Run 重组、跨段深度重组、多 w:t/制表/换行的复杂 Run、含超链接/域/书签/OMML/修订/文本框/控件的段落、表格文字、题注、参考文献、页眉页脚/脚注尾注均不可改文。文档保护/修订跟踪开启、未知角色或不可靠映射也拒绝。原包其他安全正文仍可独立授权；保护对象不是整份文档不可读取的理由。深度强度超出此能力时仅交建议，不能为了可写扩大范围或重建段落。

## 发布前后的严格增量验证

1. 复用 Phase 3 read_package：ZIP CRC/容量/重复部件、XML 解析、必要部件、内容类型、内部关系与签名拒绝。不是完整 ECMA XSD 校验。
2. 对整个源包部件哈希和每个目标段落/Run/w:t 的原 XML 哈希重验；先验证全部目标，再在内存中只改计划文本。
3. 保留原部件集合、ZipInfo 与归档注释，在输出同目录生成临时 DOCX。除 document.xml 外，其余部件保留原字节；禁止增删包部件。
4. 重新读取实际临时 ZIP，检查每个目标节点实际文字/xml:space 正好符合计划，完整目标段落等于候选。授权 journal 必须等于重新核验的全部补丁。
5. 只在验证副本中撤销刚才已确认的授权文字/xml:space；撤销后整个主 XML 树（含注释、根外处理指令）canonical 必须等于原件。除必要文本表示外，任何正文、格式、对象、结构或次序差异都拒绝。这不是修改前后正文字符串比较，也不是无条件把改动部件替换为原件。
6. 逐部件原字节比较，独立核对原 pPr/rPr/sectPr、表格、图片、OMML 及其顺序、危险子树摘要；在逆变换验证通过之后再复用 Phase 3 snapshot/compare_snapshots 验证恢复后的基线。数字/单位/引用等候选保护已在写前通过，实际输出须精确复现该候选。
7. 再核对输入哈希，使用 os.link 原子发布到新路径，已有目标/竞争目标均不覆盖，finally 清理本次临时文件。验证失败不发布 DOCX。

报告单独写新 JSON；DOCX 与 JSON 不是多文件事务，报告保存失败时 CLI 报错，已验证 DOCX 可能已发布。调用方必须核对退出码及报告，不能因为文件存在就当成可交付。源文件变化、候选/格式/部件破坏、未解释差异均不得标通过。

## 状态与视觉限制

published_structurally_verified_render_pending 仅代表结构检查和授权增量保真通过。rendering=pending、microsoft_word_verified=false、full_ecma_schema_validated=false 明确保留。格式属性不变不等于行数、页数或图片绝对坐标不变；文本长度可引起合理重排，必须用 [渲染工具](equations-rendering.md) 单独检查并报告。renderer复用相同授权工作目录，字体检查和全局布局限制保持原样。

本阶段四份合成文章实际渲染结果见 报告。源测试包包含复杂对象和基线题注分页问题；保留它们不等于已验证任意 Word 对象交互或已修好整篇排版。宋体/TNR 可用不保证所有数学/标题字形均无替换。Phase 3 长公式、数学字体、正确参考文档版本和 Microsoft Word 兼容性待办继续保留，不因局部改文通过而清除。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
