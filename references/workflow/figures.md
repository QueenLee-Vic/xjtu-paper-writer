# 05 智能学术配图（Phase 4A-1）

本模块只处理配图计划、真实性门槛及基础示意图。不调用语言润色，不改 DOCX。详细真实性原则沿用 [证据规范](../standards/evidence.md)；本文件不将文件存在等同实验真实。

## 四类决策

| 类型 | 材料与用途 | 本阶段执行 |
| --- | --- | --- |
| A 解释性示意图 | 流程、路线、架构、原理、关系和方法比较；需要明确结构与知识依据 | 优先可用 baoyu-diagram，缺失时内置 SVG；题注明确“示意图” |
| B 真实数据可视化 | 曲线、柱状、散点、误差棒、统计结果；需要实际数据及来源 | 核对文件存在/哈希、来源声明及格式接口；缺数据阻止；绘图和数据内容校验留 4A-2 |
| C 实验/仿真材料 | 软件截图、装置照片、实际测试结果 | 登记原材料及来源；缺材料阻止；不生成假截图，不编辑结果信息 |
| D 外部参考图 | 文献或公开科研插图 | 核对出处与授权声明；未知时待确认，不去作者/版权标识，不冒认原创 |

分类依据来源类型和请求意图；实验结果/数据意图不能通过传入 diagram 或声明 image_type=A 绕过。规则识别不了时标未分类，询问关键上下文；不假称自由文本分类百分之百可靠。不存在必要性时不生成，不按文章字数或章节数强凑图片。

输入 need 记录 user_requested、teacher_required、helps_explain；至少一项明确成立。来源、目的或结构不足时只给计划/待确认，不补造科学结论。已有明确材料不重复询问。modify 需 authorized_image_ids；format_only 一律禁止新增图；operation=polish 一律跳过配图。独立调用模块不触发整篇写作。

## 外部 Skill 与宿主边界

1. 从宿主技能目录/目录服务发现实际 baoyu-diagram 的 SKILL.md，读实际指令、记录哈希和支持类型/格式/依赖。目录名字不证明可用，不能假设固定 shell 命令。
2. 核对宿主是否提供实际调用接口，及其证据；依赖通过，并确认支持适合论文的 academic_light 风格。深色默认不自动继承，无法选择浅色时改用内置方案或提出限制。
3. inspect_external 只验证能力声明和文件/指令哈希一致性，ready_for_host_invocation 表示宿主可调度，不表示本脚本已经执行外部 Skill。宿主负责按实际指令调用、检查图像并登记结果，禁止自动安装。
4. 计划中的 external_task 是完整通用任务描述（结构、目的、章节、来源、主题、图题），由 Codex/Claude/兼容 DeepSeek Agent 的宿主适配；不绑定任意模型专用 API。
5. 成功生成后登记实际路径、格式、文件哈希、工具/指令版本、来源及结构/语义/视觉检查。外部生成失败可回退内置，但不能把失败或模拟结果记成外部实际成功。

可选 --capabilities JSON 包含 skill_path、instructions_reviewed、instructions_sha256、host_invocation_available、host_interface、host_evidence、dependencies（available/evidence）、supported_kinds、output_formats、supported_themes。缺信息不强行判可用；测试 simulated=true 仅验证适配合同，不能作为真实集成证据。当前环境实际未发现该 Skill，外部执行尚未验证。

## JSON 请求与工具

```sh
python3 -B scripts/generate_diagram.py --workspace /你的作业目录 --request outputs/figure-request.json --output-dir outputs/new-example --png
```

请求 schema_version=1.0，mode=create/modify/format_only，operation=figures/polish，figures 为列表。单项示例：

```json
{
  "image_id":"experiment-flow",
  "request":"实验流程图",
  "section":"实验方法",
  "purpose":"解释实际提供的实验步骤",
  "need":{"user_requested":true},
  "source":{"source_type":"knowledge_description","source_reference":"用户给定步骤；仅示意，不作为实测结果"},
  "diagram":{
    "kind":"flowchart",
    "nodes":[{"id":"prepare","label":"准备实验"},{"id":"measure","label":"记录测量"}],
    "edges":[{"from":"prepare","to":"measure"}]
  }
}
```

支持 flowchart（单列线性）、roadmap、relationship（相邻层主干 DAG）。节点 2—16，标签最多 500 字符；按字体度量动态宽高/换行。显式 type 支持 start_end/process/decision/input_output/junction，缺省 process，不从文字猜语义。边支持 kind=forward/data/control/feedback 和 direction=forward/both；最多两条明确的向前层反馈走独立侧边通道，未声明循环、跨层主干、超过 24 条边/每层 4 节点及过大画布拒绝。分支/合流使用分开的连接端口和折线；不是复杂自动布局引擎，密集交叉仍需审查。

内置采用白底、浅色节点、深灰边框和箭头、统一文字。不执行标签中的代码，SVG 用 ElementTree 构建/转义，ID 白名单，控制字符/无效连接/重复 ID 拒绝。连线仅穿过层间空白，不穿节点文字；合流端口已分离，密集连线/交叉仍需人工检查。

SVG 是原图，PNG 可选：Pillow 与可加载中文字体可用时从同一布局结构生成，按建议显示宽度给出足够像素。找不到字体/栅格能力时仍保留 SVG，标出度量/CJK 风险，不自动安装或打包字体。PNG 不是从任意外部 SVG 解释执行；只绘制本工具已验证的图元。

## 来源与质量清单

figure-manifest.json 每图记录 image_id、image_type、section、purpose、source_type、source_path、source_reference、source_evidence、source_status、generation_method、caption、status、verification_status、output_path/output_formats/output_hashes、quality 和 docx_interface。

- A 的 source_type=agent_authored_explanatory_schematic，表示 Agent 根据给定知识结构编排的示意，非实验数据或照片。
- B 可用 user_data/program_results/public_dataset 声明来源；source_path 在项目内，只核对文件/非空/哈希及接口格式。provided/file_present 不是已核实数据，deferred_data_validation_and_plotting 表示交给 [科学配图接口](scientific-figures.md) 内容校验后绘图。synthetic_example 不能混入实验结果；synthetic_test_data 仅在工具显式测试授权后生成带醒目标识的测试图。
- C 的 user_image/experiment_output/simulation_output 只是来源声明，文件存在仍标真实性未独立验证；本阶段不裁剪、不增强、不转换图像。
- D 的出处和 user_attested_authorized/public_license_reported 是可追溯声明，不自动视作版权法律核验。缺失者待确认，禁止去水印/作者信息。

自动检查节点/标签边界、连接、SVG XML、输出哈希和推荐打印尺寸；可用字体下为当前度量通过，不等于科学语义或所有客户端渲染通过。SVG 可在其他环境发生字体回退，PNG 固化了当前字体呈现但仍需检查。始终保留 semantic_review=required、manual_visual_confirmation=false；不得因为写出文件就称图片质量验收通过。

## DOCX 插图接口

每张实际生成 A 图提供 image_path、source_svg、image_type、suggested_width_cm、preserve_aspect_ratio、caption、insertion_section、source_reference、quality_status、insertion_authorized=false 和 requires_docx_content_fidelity=true。B 由数据绘图记录提供接口；C/D 仅在实际 PNG/JPEG 文件、来源及权限门槛通过时登记接口，不伪造不存在的图像路径。

图号 {n} 是待插入时分配的占位，不是修改已有图号的授权。消费方应先经过现有模板优先级，沿用冻结规范的居中、图下题注、宋体/TNR 五号、单倍、段前后零，不用图片模块覆盖教师模板。4A-2 已提供授权插图，只有显式选择文档插图时按 [数据绘图与插图合同](scientific-figures.md) 调用；单独画图不自动改 DOCX。

阶段产物与实际测试见 开发报告。

当前科学绘图、可复现记录及 DOCX 授权增量保真的完整规则见 [科学配图接口](scientific-figures.md)。


## 工作区运行合同

工具须传 `--workspace`，用户文件相对授权工作区解析；规则和资源相对安装根解析。所有原有范围授权、哈希绑定、保护与保真检查继续生效。详细入口见 [安装说明](../../INSTALL.md)。
