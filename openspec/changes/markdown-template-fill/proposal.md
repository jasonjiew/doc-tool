# 模板填充：Word 模板 + Markdown → 格式一致的 Word

## Why

互转中心现有的「Markdown → Word」走「Markdown → 内嵌 CSS 的 HTML → Word COM 导入」链路（`doc_tool/application/convert.py::_markdown_to_docx_via_word`），版式来自硬编码 CSS 与 Word 内置标题映射，无法继承企业已有的 Word 模板封面、页眉页脚、字体字号与标题编号。而具备「按模板 styleId 精确装配」能力的项目出稿管线（`scripts/build_docx.py`）必须先走完整的 Word 导入建项流程才能使用。企业用户普遍持有现成的 Word 版式模板（红头文件、投标书、研发文档底模），期望的操作是「导入一个 Word 模板 + 选择 Markdown 文档 → 自动填充生成格式与模板保持一致的 Word」，一键完成、无需建项。

## What Changes

- **新增模板填充应用服务**：`doc_tool/application/template_fill.py` 用 `doc_tool/domain/ooxml.py` 既有能力解析用户模板的标题样式（`resolve_heading_styles`/`parse_heading_styles`）与正文样式；把选中的 Markdown（单文件或多文件）装配为最小章节树；组装与 `adapters/kernel.py::config_from_project` 同形的内核配置（`paths.template` 指向用户模板、`documentType` 走 general 跳过封面/页眉/修订记录改写），调用 `scripts/build_docx.py::build(config=...)` 生成 DOCX——样式、编号、节属性全部继承用户模板。
- **互转中心新增「Markdown → Word（模板填充）」方向**：`convert.py` 的 `DIRECTIONS` 注册表新增方向行与后端函数；`Direction`/`build_plan`/`convert_paths` 增加可选 `template_path` 参数（默认 `None`，不影响既有方向）；`ui/convert_dialog.py` 在源为 Markdown、目标为 Word 的行上提供「底模（可选）」文件选择。
- **样式映射兜底**：用户模板的标题样式不符合 Heading 约定时，允许在转换对话框中手动把段落样式映射到标题级别（复用导入样式映射的交互模型与 `heading_style_candidates` 候选清单），映射仅作用于本次转换、不落盘。
- **CLI 支持**：`doc_tool/cli.py` 的 `convert` 子命令增加 `--template <docx>` 可选参数。
- 本变更不改既有两条管线（项目出稿、CSS 版式互转）的任何行为，全部新增参数均有默认值。**无破坏性变更**。

## Capabilities

### New Capabilities

- `markdown-template-fill`: 以用户提供的 Word 模板为底模，将 Markdown 内容自动填充生成格式与模板一致的 DOCX；涵盖模板样式解析、标题级别映射兜底、按模板样式装配构建、图片内嵌与域刷新。

### Modified Capabilities

无。主规格（content-* / pyside6-app-shell 等）不含互转能力规格；互转中心方向注册表为代码级扩展点（`DIRECTIONS` 按设计即「加一行注册数据」），本变更新增独立能力规格。

## Impact

- **代码**：新增 `doc_tool/application/template_fill.py`（模板样式解析 + 章节树装配 + 内核配置组装）；`doc_tool/application/convert.py`（`DIRECTIONS` 新增方向行，`Direction`/`build_plan`/`convert_paths` 增加可选 `template_path`）；`doc_tool/ui/convert_dialog.py`（底模选择行 + 样式映射兜底交互）；`doc_tool/cli.py`（`--template` 参数）。不改动 `scripts/build_docx.py`、`scripts/validate_docx.py`、`doc_tool/adapters/importer.py` 等既有模块（若 `build()` 的 `validate_content_tree` 对单文件章节树存在硬约束，允许在内核增加非侵入的可选开关，实现时另行评审）。
- **存储**：无项目态字段变更；产物为独立 DOCX 文件，输出到用户指定目录；临时章节树在系统临时目录生成并在完成后清理。
- **测试**：新增 `scripts/tests/test_template_fill.py` 并加入 `scripts/tests/run_tests.py` 的 `DEFAULT_TESTS`；夹具复用 `templates/requirement-template.docx`（`test_convert.py` 同款）与 `fixture_factory.py`。
- **兼容性**：既有互转方向、项目出稿、导入链路行为不变；`convert_paths` 新增参数为可选关键字参数，既有调用方无需修改。
