# 样式优先级与配置解析

本模块消费 Phase 3A JSON，不重复解析 OOXML，也不写入 DOCX。脚本仅依赖 Python 3.9+ 标准库。默认规范的唯一机器配置为 [default-style.json](default-style.json)，136 个属性均标为 Skill 自定义 default（其中 3 项保留作兼容字段），不是参考文档实测值。

## 调用与请求

```sh
python3 -B scripts/resolve_style_config.py --workspace /你的作业目录 --request outputs/resolve-request.json --output outputs/new-effective.json --preview outputs/new-preview.md
```

输出必须是授权工作目录内不存在的 .json 和 .md 文件，互不相同。已有输出不会被覆盖。结构错误、未知字段/属性、重复 JSON 键、来源不明、版本不支持时返回非零，不生成结果；合法结构中的非法属性值会写入诊断并阻止相关属性执行。

请求示例（教师条款为说明接口的合成示例，实际输入以用户提供材料为准）：

```json
{
  "schema_version": "1.0",
  "kind": "style_resolution_request",
  "mode": "create",
  "sources": [
    {
      "id": "teacher",
      "role": "teacher_requirements",
      "source": "教师作业要求第 2 条",
      "properties": {
        "body.size_pt": {"value": "小四", "status": "explicit", "source": "第 2 条"}
      }
    },
    {
      "id": "reference",
      "role": "user_reference_style",
      "source": "用户指定排版参考",
      "extraction": "inputs/style-config.json"
    }
  ],
  "document": {"input": null, "output": null}
}
```

extraction 与 document 相对路径均相对于请求文件所在目录；默认配置路径由脚本位置确定。每个来源有唯一 id、明确 role 和 attribution（source）。可指定 properties，或指定 Phase 3A extraction，不能两者同时指定。properties 的每个属性接受一条 value/status/source 记录或非空记录列表。物理单位可写在 unit 或数值字符串中，两处冲突时报错。未知/非格式属性不进入配置。

角色和优先级固定：teacher_requirements=1、teacher_template=2、teacher_example=3、user_reference_style=4、skill_defaults=5。外部源不能冒充内置默认；传入 priority 时必须与 role 一致。正式模板与案例的身份由请求中有依据的材料声明，不靠文件名推断。Phase 3A 内嵌 skill_defaults 不被升格为模板实测值。

## 归一化与逐属性决策

每个属性独立收集所有来源，保留原始记录到 alternatives[].raw；字段名对应目标单位：_pt、_cm、_chars。支持 pt、half_pt、twip、cm、mm、in，字符支持 char/hundredth_char。字体名保留名字，不允许带字号单位；常用中文字号转 pt。颜色归一为六位 RGB；auto、未解析主题色不能当黑色。行距用 rule/value/unit 对象，multiple 为倍数，exact/at_least 归一为 pt，不互相猜换。

1. explicit、verified、inherited、extracted、theme_resolved 可参与同属性优先级比较；不把 inherited 改成 verified。default 仅用于内置规范。
2. 同一最高有效优先级出现不同归一化值，产生 same_priority_conflict，最终值留空并待确认；等价单位值合并，不任意选不同设置。所有同值证据仍保留在 alternatives。
3. 不同优先级取高者，差异记录为 priority_override，无需为正常覆盖反复询问。
4. candidate 不自动采用。通常不低于预览选中来源的候选会阻塞；例外仅为逐属性已冻结默认与可选的 user_reference_style 候选：选中默认时记录 confirmed_default_used 理由，保留候选原值/状态，但不再次询问。正式模板、教师案例、教师要求的候选，以及 required=true 的参考候选仍阻塞。更低优先级候选不阻塞明确要求；真实同级冲突不被冻结默认绕过。
5. unknown 原值和状态保留，不参与已验证比较；缺失的普通格式允许用明确标记的默认值填充。教师明确要求中的 unknown，或 required=true 的 unknown，阻止受影响属性执行，不能借默认值绕过未解决要求。
6. 非法值/单位若位于更高或相同优先级，阻止低优先级默认掩盖错误；保留 invalid_parameter 诊断，单位问题额外标 category=unit_inconsistency。

Phase 3A 适配器复用页面、profiles、paragraphs 的属性来源。角色为 candidate 时，即使字号为 inherited，目标“正文样式”仍为候选；raw.original_status 和 extraction_statuses 留存原提取状态。逐 run 不同字体保留为多个候选，不采多数投票。多节不同页面值作为同级冲突处理，不静默只取第一节。未使用的标题定义不用于实际目标样式。邻近题注位置仍是候选，不能当渲染验证结果。

缺少核心参考参数时记录 missing_parameters；原始 unknown、未映射的复杂表格外观、公式结构和布局限制继续以 Phase 3A 为准。当前不从表格边框猜测三线表，不自动把所有未知值升级为默认实测值。

## 明确确认候选

仅在用户已确认时，可在请求中增加 confirmations：

```json
[{"property":"body.size_pt","source_id":"reference","value":10.5,"unit":"pt","confirmed_by":"user","reason":"用户明确选择该正文样本"}]
```

必须匹配既有候选的归一化值；不能确认不存在的值或非法值。被选候选保留 status=candidate，resolution_status 单独标为 confirmed_by_user；未选同源候选保留且标 excluded_by_confirmation。其他来源的同级分歧仍需解决。没有用户确认依据时，Agent 不得自行填写 confirmed_by=user。

## 输出及三模式

schema_version 保持 1.0，用 kind=effective_style 与 Phase 3A 的只读 inventory 区分，不修改旧格式；resolver_version 标识合并工具版本。未来破坏性字段变更需升 schema_version 并提供显式迁移，不能让旧消费者猜测新格式。

| 字段 | 内容 |
| --- | --- |
| effective_properties | 全属性审计预览：value/source/source_id/priority/status/resolution_status/authorized/apply/confirmation_required/alternatives |
| apply_properties | 仅获授权、格式合法且无待确认的属性；不是已实际写入 |
| sources | 来源角色、引用 JSON 的 SHA256 和原提取源哈希记录 |
| conflicts | 同级冲突、候选分歧及已解决的优先级覆盖 |
| diagnostics | 缺参数、候选未采用、非法值及单位不一致 |
| pending_confirmation | 本次允许范围内仍需确认的属性及原因 |
| confirmations | 请求中有用户依据的显式确认记录 |
| writer_contract | 下阶段写入接口；本阶段 write_performed 始终 false |

create 默认生成完整目标规范。modify 必须通过 allowed_properties 授权，未给范围时 apply_properties 为空；未授权的预览条目不是修改许可。format_only 默认只允许安全格式属性，也可提供更窄范围。allowed_properties 支持精确键、body.* 等前缀及 *。

modify 和 format_only 均排除图表重新编号、公式行内/独立结构转换、公式编号及文献引用制式变更；这些可能改变内容，不能因设置格式范围而绕过保护。正文、数字、数据、OMML、引用内容/顺序、图片信息、书签、域及其他非格式数据均列为受保护。图表文字使用独立样式；表格外观支持 grid/three_line，图表编号及引用制式可在 create 目标配置选择，不能在保护模式静默重编号。OMML 保留与等比图片策略不能关闭。

## Phase 3B-2 写入合同（仅定义）

writer_contract 包含 input_path、output_path、source_docx_sha256、effective_style、allowed_properties、protected_content、unresolved_conflicts、expected_validation、ready_for_writer、write_performed。

input/output 都可以暂为空；指定 input 时只读取字节计算 SHA256，未验证包结构。输出必须是项目内新的 DOCX 路径，不得等于输入或覆盖既有文件。无授权属性、路径缺失、有范围内待确认或待布局验证时 ready_for_writer=false。true 仅表示配置前置条件齐备，不证明 DOCX 可打开、对象受支持或渲染通过，也不授予执行权限。

未来写入者仍须检查任务授权、源哈希、新输出路径、属性白名单及内容保真；只消费 effective_style，不执行 alternatives 中未确认值。后续遇到不支持的对象必须阻塞相应操作，不能以配置 ready 替代内容和视觉检查。验证至少包括原件哈希、正文/数字/OMML/图片/字段及其他对象等价、授权属性范围、样式 XML 和视觉检查或明确未验证声明。基础写入实现与部分执行状态见 [写入合同](docx-writing.md)，公式几何操作仍未实现。


## Phase 3B-1A 兼容扩展（resolver/contract 1.2，schema 仍为 1.0）

122 项用户指定默认记录含 `default_confirmation: {"status":"user_confirmed","basis":"Phase 3B-1A explicit user specification"}`。只有内置默认记录可提供冻结依据，身份仍为 skill_defaults=5。confirmed_default 是决策状态，default 是来源状态；其他原始 candidate/unknown/inherited 不变。不是批量将待确认改为 resolved，也不允许确认标签掩盖非法单位或真实同级冲突。未冻结的默认（例如页眉距离）仍会被相关候选阻塞。

### 新字段与单位

| 属性 | 类型与解释 |
| --- | --- |
| references.hanging_chars | 非负数，字符；精确表达悬挂缩进，支持 hundredth_char 归一化，不支持物理单位猜换 |
| image.alignment / max_width / quality_policy | 居中、正文区域宽度限制、优先矢量或清晰打印；图像信息及等比策略保持不变 |
| table.cell.font.eastAsia / font.latin / size_pt / color | 表格文字的独立字体槽、字号和颜色，不操作行列、数据、合并关系 |
| caption.figure.numbering_format / caption.table.numbering_format | 含一个 {n} 的编号呈现模板；仅排版不执行编号变更 |
| equation.paragraph.* | alignment、line_spacing、first_line_chars、space_before_pt、space_after_pt，段落格式不等同公式本体定位 |
| equation.body_alignment / number_alignment / center_reference | 本体居中、编号右对齐，相对于整个 text_area；不能把编号占用宽度先扣除 |
| equation.tab_stops | 两个对象的有序列表：position 为字符数、unit=char、alignment 为 center/right、leader=none |
| equation.numbering_format | 含一个 {n} 的公式编号模板；与原 OMML 公式内容分开 |

制表位对象保留 19.9/39.81 字符。Word 物理制表位位置需要正文区域、字体字符度量、首行/左右缩进及实际渲染验证；本阶段不生成 pt/cm 换算，不写 w:tabs，不保证给定字符数必然满足全宽居中。发生几何冲突须报告并阻塞，不能静默调整公式或生成错误布局。

### 字段互斥与旧字段读取

保留 references.hanging_pt=21 的旧磅值含义，不改成字符；旧 schema 1.0 请求可继续传入该字段。它与 hanging_chars 按来源优先级互斥选择：更高优先级胜出；同级不同单位不得假设等价，报告 incompatible_indent_units。内置默认自身明确以 hanging_chars 为准，旧默认磅值标记 deprecated_default_for，留在审计但不进入执行集合。悬挂缩进启用时不再同时写入中性的 first_line_chars=0；正首行缩进与悬挂缩进同级冲突会阻塞。

equation.alignment 保持旧“本体对齐”含义，equation.number_position 保持旧“编号位置”含义；分别兼容映射到 body_alignment/number_alignment，与 paragraph.alignment 区分。按优先级和授权选择一个写入入口，同级不一致则报告 alias_conflict。不会把旧 equation.alignment 解释为新的公式段落对齐。

schema_version=1.0、旧请求/来源记录和 Phase 3A 适配保持可读；缺少新增字段时由当前默认补齐。旧历史 effective-style 文件作为历史快照保留，不自动迁移原值。resolver_version 与 writer_contract.contract_version 标为 1.2，写入接口新增 required_capabilities、font_mapping、semantic_styles、indent_policy、layout_requirements 和 pending_validation。旧消费者若不支持新增能力必须拒绝相应写入，而不是忽略新字段；不承诺未经更新的旧二进制理解新属性。

### 执行和布局验证分离

pending_confirmation 仅列用户确认问题；pending_validation 列尚未通过的文档几何验证。公式本体、编号、字符制表位和相关段落属性一起进入 equation_geometry 验证组，apply=false，resolution_status=needs_layout_validation。即使用户确认默认位置目标，也不能令这组直接执行。未解决确认、布局组或路径缺失时 ready_for_writer=false。

font_mapping 明确 East Asia → w:rFonts/@w:eastAsia，Latin → ascii/hAnsi；semantic_styles 保留 Title、Heading1、Heading2、Heading3 独立身份。字符缩进可映射 Word 百分之一字符存储（1.64 → 164），这不等于将字符换算成磅。写入器应清理互斥的缩进属性，遵守 allowed_properties 和受保护对象范围，并独立检验 OMML 可编辑性、内容不变、结构不损坏及实际居中/右对齐。上述 3B-1A 冻结阶段只定义合同；当前 3B-2A 仅实现安全普通格式，公式布局与渲染仍未实现。


3B-2A 兼容补充：table.cell.alignment、first_line_chars、line_spacing、space_before_pt、space_after_pt 为可选来源属性，类型与对应正文属性相同；不设新默认。它们可在 allowed_properties 中出现而无有效值，消费者必须忽略缺失值，不能假设允许范围中的每个键都已有可执行记录。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
