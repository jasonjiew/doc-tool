## Why

导入链路（预检 → 模板生成 → 内容提取 → 拆分 → 试构建 → 发布）已可运行，但存在两个保真与安全缺口：OOXML 解析散落在 `preflight.py` / `importer.py` / `build_docx.py` / `validate_docx.py` / `docx_common.py` 多处，安全参数与防御深度不一致（只有预检做了 DTD/实体禁用与包体量上限）；导入前只检查标题/图片/表格计数，不识别超链接、书签、批注、修订、脚注、公式、图表、文本框等可能损失内容，也不执行「源 Word→Markdown→重建 Word」往返差异门禁，非标准 Heading 文档更直接被 `MissingHeading1Error` 阻断而无人工映射入口。

## What Changes

- **统一安全 OOXML 解析入口**：新增 `doc_tool/domain/ooxml.py` 作为安全解析单一事实源（ZIP 体量上限、CRC、DTD/实体/网络禁用、良构校验），`scripts/docx_common.py` 加薄适配；模板生成、复杂表格读取、导入、构建、校验全部经同一入口读取包与解析 XML，删除各处的重复实现。
- **导入保真度门禁**：导入前扫描源 DOCX 的超链接、书签、批注、修订、脚注、尾注、公式、图表、文本框、OLE、内容控件、域等特性，按「阻断 / 告警」分级报告；导入中自动执行「源 Word→Markdown→重建 Word」往返差异检查，关键损失（业务元素数量不一致、正文段落丢失、标题层级变化、图片缺失）阻止发布，不留下半成品项目。
- **导入样式映射向导**：非标准 Heading 文档允许用户在向导中把 Word 段落样式手动映射到章节级别（1~6 / 忽略），映射驱动模板生成、内容提取与构建，写入 `project.yml` 并持久化回读。
- 本变更不改 `project.yml` 现有字段语义（`headingStyles` 复用为 `级别→styleId`），不改变正式构建/校验产物格式。**无破坏性变更**；往返差异门禁为导入新增阶段，`ImportResult.events` 增加 `roundtrip_check` 阶段事件（兼容既有调用方）。

## Capabilities

### New Capabilities

- `unified-safe-ooxml-parsing`: 模板、复杂表格、导入、构建、校验全部走同一安全 OOXML 解析入口（包体量上限 + CRC + DTD/实体/网络禁用 + 良构），消除重复解析逻辑与攻击面差异。
- `import-fidelity-gate`: 导入前识别超链接、书签、批注、修订、脚注、公式、图表、文本框等不支持或可能损失内容并分级报告；自动执行「源 Word→Markdown→重建 Word」往返差异检查，关键损失阻止导入。
- `import-style-mapping`: 非标准 Heading 文档允许人工指定 Word 段落样式与章节级别的映射，映射驱动导入、构建与校验并持久化。

### Modified Capabilities

无。当前主规格（content-* / pyside6-app-shell 等）不涉及导入链路的既有 Requirement；本变更新增独立能力规格，不改既有规格行为。

## Impact

- **代码**：新增 `doc_tool/domain/ooxml.py`（安全解析入口，纯 domain，无 Qt）；`scripts/docx_common.py` 增加安全解析薄适配；改造 `doc_tool/adapters/preflight.py`、`doc_tool/adapters/importer.py`（`generate_template`/`extract_content` 接受样式映射覆盖）、`doc_tool/application/import_project.py`（新增保真扫描与 `roundtrip_check` 阶段）、`doc_tool/adapters/kernel.py`、`scripts/build_docx.py`、`scripts/validate_docx.py` 复用共享入口；新增保真扫描/往返差异服务（复用 `validate_docx.body_events`/`compare_baseline_events`）；`doc_tool/ui/wizard.py` 增加样式映射页与保真报告展示。
- **存储**：`project.yml` 的 `headingStyles` 字段复用（`级别→styleId`），不改格式；成功项目在 `logs/` 写入保真报告与往返差异摘要；失败诊断日志含保真扫描摘要。
- **测试**：扩展 `scripts/tests/test_import_preflight.py` / `test_import_project.py` / `test_docx_common.py` / `test_validator_negative.py`，新增保真扫描、往返差异与样式映射单测。
- **兼容性**：既有预检/导入/构建/校验 CLI 与产物不变；`ImportResult.events` 新增阶段事件为追加字段；无破坏性变更。
