## Context

导入主链路（`preflight` → `generate_template` → `extract_content` → `split_into_tree` → 试构建 → 原子发布）已完整，但 OOXML 处理存在结构性问题：

- **解析口径分散**：`preflight.py` 有安全 `_parse_xml`（DTD/实体/网络禁用）+ `_check_zip_limits`（条目 2 万/展开 512MB/单条目 256MB/压缩比 2000），但 `importer.py` 的 `generate_template`/`extract_content` 直接 `etree.fromstring`，`build_docx._validate_zip_xml`、`validate_docx.DocxPackage`、`docx_common._expected_table_xml` 均为裸解析；`kernel._effective_heading_styles` 不经上限读 styles.xml。同一攻击面五种防御深度。
- **保真无门禁**：`preflight` 只统计标题/图片/表格；`analyze_docx.py` 用正则清点过超链接/书签/批注/修订/脚注/文本框/OLE/内容控件/域，但只出分析报告，不参与导入决策。`validate_docx` 已具备 `baseline` 模式的源/重建业务事件对比，可作为往返门禁底座，未接入导入流程。
- **非标准 Heading 无出路**：`preflight._parse_heading_styles` 只认「Heading N / 标题 N」，自定义样式文档直接 `MissingHeading1Error` 阻断，无人工映射入口。

复用基础：`validate_docx.body_events`/`compare_baseline_events`（往返对比）、`import_project` 阶段事件与暂存/发布模型、`ProjectManifest.headingStyles`（级别→styleId）、向导 `QWizard` 页式流程、`kernel.config_from_project`（构建配置装配）。

## Goals / Non-Goals

**Goals:**

- 单一安全 OOXML 解析入口：包体量上限、CRC、DTD/实体/网络禁用、良构校验全链路一致；删除重复解析实现。
- 导入前保真扫描分级报告；导入中往返差异门禁，关键损失 fail-closed 不留下半成品。
- 非标准 Heading 文档经向导样式映射可导入，映射驱动构建/校验并持久化。
- 保持现有构建/校验/导入产物与 CLI 不变（无破坏性变更）。

**Non-Goals:**

- 不在本变更中支持批注/修订/公式/图表等的完整重建（往返门禁只做检测与阻断，重建能力属后续扩展）。
- 不做自动样式猜测（仅识别候选，必须经用户确认）。
- 不新增运行时依赖；安全解析仅用 lxml。
- 不改 `project.yml` 字段格式与构建/校验输出格式。

## Decisions

### 1. 安全解析单一事实源：`doc_tool/domain/ooxml.py` + `docx_common` 薄适配
新增 `doc_tool/domain/ooxml.py`（纯 domain，无 Qt，仅 lxml）：集中 `PARSE_LIMITS` 常量、`OOXMLSecurityError`（含部件名/原因）、`parse_xml_safe(data, part_name)`（DTD/实体声明前缀拒绝 + `resolve_entities=False/no_network=True/load_dtd=False/huge_tree=False` + doctype 复查）、`read_docx_package(path)`（扩展名、ZIP 完整性、CRC、上限、按需读取部件，返回部件字典）。`scripts/docx_common.py` 加 `sys.path` 单次引导后转发 `parse_xml_safe`/`read_docx_package`/`OOXMLSecurityError`，`build_docx`/`validate_docx` 改经 docx_common 调用；`preflight`/`importer`/`kernel` 直接 `from doc_tool.domain.ooxml import ...`。

**Alternatives considered:**

- 直接在 `docx_common.py` 内实现安全解析，doc_tool 侧经 `kernel.ensure_kernel_importable` 引用 → 使 doc_tool→scripts 依赖方向固化，且预检在 kernel 尚未导入时也要先引导路径，不划算。
- 各模块保留各自安全解析仅统一参数 → 逻辑仍重复，后续规则漂移风险不变，排除。
- 新模块放 `doc_tool/domain`：doc_tool 免路径引导直接导入；scripts 侧经 docx_common 薄适配保持自包含，scripts→doc_tool.domain 的纯 domain 依赖可接受（migration 薄壳本已如此）。

### 2. 错误映射策略
`ooxml.py` 只抛中性 `OOXMLSecurityError`。导入侧（preflight/importer/import_project）捕获后映射为 `InvalidDocxError`/`BrokenRelationshipError` 等（带错误码与建议）；构建/校验侧捕获后映射为 `AutomationError`。`kernel._effective_heading_styles`、`import_project._verify_valid_docx` 一并改为复用 `read_docx_package`/`parse_xml_safe`。

**Alternatives considered:**

- 安全解析直接抛 `DocToolError` → scripts 侧无此依赖且领域倒置，排除。
- 各调用方直接 `except lxml.XMLSyntaxError` 本地判断 → 信息丢失且重复，排除。

### 3. 保真扫描：`fidelity.py` 复用并形式化 analyze_docx 清单
新增 `doc_tool/adapters/fidelity.py`：`scan_fidelity(parts) -> FidelityReport`（每特性：类型/计数/严重级 BLOCK|WARN|INFO/位置采样）。特性清单沿用 `analyze_docx` 的正则/遍历方式改为统一入口的树遍历：`w:hyperlink`(WARN)、`w:bookmarkStart`(WARN)、`comments.xml`/`w:commentRangeStart`(BLOCK)、`w:ins`/`w:del`/`w:rPrChange`/`w:pPrChange`(BLOCK)、`word/footnotes.xml`/`w:footnoteReference`(BLOCK)、`m:oMath`(BLOCK)、chart part(BLOCK)、`w:txbxContent`(BLOCK)、`o:OLEObject`(BLOCK)、`w:sdt`(WARN)、`w:fldChar`/`w:instrText`(INFO)。`preflight` 集成扫描并把报告挂到 `ImportPreview.fidelity`；向导预检页渲染报告，存在 BLOCK 且未确认时 `isComplete=False`。

**Alternatives considered:**

- 把保真扫描并进 preflight 单函数 → 职责膨胀且难独立测试；独立 `fidelity.py` 可先单测。
- 用 analyze_docx 的正则计数直接复用 → 正则与树遍历混用易漏（如跨多行的 w:ins），统一树遍历更可靠。

### 4. 往返差异门禁：复用校验器事件对比，新增 `roundtrip_check` 阶段
新增 `doc_tool/adapters/roundtrip.py`：`roundtrip_diff(source_docx, rebuilt_docx) -> RoundtripReport`，内部经 `ensure_kernel_importable` 复用 `validate_docx.DocxPackage.body_events()` 与 `compare_baseline_events`，补充关键损失判定（元素数量不一致、`P` 段落丢失、`H` 层级变化、`I` 图片缺失为 BLOCK；纯表示性格式差异为 WARN）。`import_project` 在 `trial_build` 后、`publish` 前新增 `STAGE_ROUNDTRIP_CHECK`：失败（含 BLOCK 差异）→ 清理暂存、写诊断日志、返回失败；仅 WARN 且请求方未显式要求阻止 → 放行。`ImportRequest` 增加 `require_exact_roundtrip: bool = False`（默认允许非关键差异），UI 向导「导入确认」页给出开关。

**Alternatives considered:**

- 直接调 `kernel.validate_with_project(baseline=True, output_override=trial)` → 返回 bool 且报告混入大量非往返检查，拿不到结构化差异；自建 roundtrip 对比更精准。
- 往返门禁放发布后 → 半成品已落地，违背 P0-3「导入失败/门禁未通过不得留下半成品」，排除。

### 5. 样式映射：`census` + 向导页 + 映射贯穿
`preflight` 新增 `census_paragraph_styles(parts) -> Dict[styleId, {name, count, suspected_heading}]`（styles.xml 名称 + document.xml 实际使用计数 + 是否含层级数字特征）。`importer.generate_template`/`extract_content` 新增可选参数 `heading_style_map: Optional[Dict[str,int]]`，传入时不再自行解析、直接使用；`_build_heading_tree`/`_validate_heading_hierarchy` 按映射工作。向导在预检页与项目信息页之间插入「样式映射」页：表格列出候选样式与级别下拉（1~6/忽略），校验 H1 存在且层级无跳跃后放行。`ImportRequest` 携带映射，`_build_manifest` 按映射写 `headingStyles`（级别→styleId），构建/校验经 `config_from_project` 自动使用。重新导入时回读既有 `headingStyles` 作默认。

**Alternatives considered:**

- 只允许「全部忽略，纯正文导入」→ 丢标题结构，违背导入保真目标，排除。
- 映射仅作用于导入、不写清单 → 构建/校验与导入标题口径漂移，排除。

## Risks / Trade-offs

- [统一入口改造影响既有构建/校验产出] → 每步改造后跑现有 `test_docx_common`/`test_import_preflight`/`test_validator_negative`/`test_project_build` 回归；要求解析结果逐字节等价。
- [保真阻断过于严格导致合法文档无法导入] → BLOCK 仅限明确会损失内容的特性，且用户可显式「仍然导入」；告警默认不阻断。
- [往返门禁把表示性差异误判为关键损失] → 复用 `normalize_business_text` 归一化 + 关键损失判定白名单；`require_exact_roundtrip` 默认关闭，仅显式要求时才全等。
- [mermaid/复杂特性计数不准] → 统一树遍历而非正则，`scan_fidelity` 独立单测覆盖各类特性正反例。
- [样式映射后标题树仍不闭合] → 映射页复用 `_validate_heading_hierarchy` 即时校验，错误定位到样式。

## Migration Plan

1. 新增 `doc_tool/domain/ooxml.py` + 单测（DTD/实体拒绝、上限拒绝、CRC、良构）。
2. `docx_common` 加薄适配；`build_docx`/`validate_docx`/`docx_common` 内部改走安全解析；回归构建/校验测试。
3. `preflight`/`importer`/`kernel` 改走统一入口，删除重复实现；回归导入/预检测试。
4. 新增 `fidelity.py` 并接入 `preflight` + 向导预检页；新增 `roundtrip.py` 并接入 `import_project` 的 `roundtrip_check` 阶段；补单测。
5. 新增 `census_paragraph_styles` + 向导样式映射页 + `ImportRequest`/`importer` 映射贯穿 + 持久化回读；补单测。
6. 全量回归 `scripts/tests/run_tests.py`；人工验收清单（见 tasks）。

回滚：`ooxml.py`/`fidelity.py`/`roundtrip.py` 均为新增模块；既有入口在统一化后保持行为等价，移除接线即可回退，无数据迁移。

## Open Questions

- 往返门禁对「页眉页脚/封面/TOC 域」等模板保留内容是否纳入对比（当前 `body_events` 只对比正文业务元素）——倾向不纳入，模板语义由既有 `template_preservation_errors` 覆盖。
- BLOCK 特性清单是否需要按文档类型（需求/设计/通用）差异配置，还是全类型统一——倾向统一，后续按需放宽。
- 样式映射页是否允许「同一样式跨级别」（如 2.1 与 2.1.1 共用样式）——当前按同一样式单一级别处理，待人工验收确认是否需要扩展。
