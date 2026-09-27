# 设计：模板填充（Word 模板 + Markdown → 格式一致的 Word）

## Context

### 现状：两条互不相通的 Word 生成管线

1. **项目出稿管线（底模驱动）**：`doc_tool/application/pipeline.py::run_pipeline` → `doc_tool/adapters/kernel.py::build_with_project`（269 行）→ `scripts/build_docx.py::build(config=...)`（2495 行）。模板为项目内 `template/template.docx`（`doc_tool/domain/paths.py:20-32` 常量约定）。构建时模板包整体读入、styles.xml/numbering.xml/页眉页脚/封面/节属性原样保留，仅向 document.xml 追加内容：标题按 `config["headingStyles"]`（级别→styleId）写 `w:pStyle`（`make_heading`，build_docx.py:1047），正文段落用 `config["bodyStyle"]`（`make_paragraph`，build_docx.py:407）；`documentType` 非 requirement/design 时跳过封面字段表（`update_cover`，build_docx.py:1587）与页眉改写（`update_headers`，1653）；修订记录缺失时 `update_revision_record` 返回 0 不阻断；目录域刷新靠 `set_update_fields`（2235 行）写 settings.xml，真正刷新由 Word（COM）完成。**这是本仓库唯一能「格式与模板一致」的装配路径。**
2. **互转中心 CSS 版式管线**：`convert.py::_markdown_to_docx_via_word`（744 行）→ `markdown_word.py::markdown_to_word_html`（271 行，硬编码 CSS）→ Word COM HTML 导入（`word_convert.py::convert_document`）。与任何底模无关，无法继承模板版式。

### 现成可复用的能力

- `doc_tool/domain/ooxml.py`：`parse_heading_styles`（503 行）、`resolve_heading_styles`（465 行）、`heading_style_candidates`（380 行）、`read_docx_package`（186 行）——解析任意 docx 样式表与安全读包能力现成。
- `doc_tool/adapters/importer.py::_find_body_style`（247 行）——正文样式推断逻辑可仿写复用。
- 导入样式映射向导（能力 `import-style-mapping`）——样式候选清单与「级别下拉 + 有效性校验」交互模型可直接借鉴。

## Goals / Non-Goals

- **Goals**：单/多文件 Markdown → 用户模板底模 → 格式一致的 DOCX；互转中心与 CLI 两个入口；无模板时回退既有 CSS 版式方向；图片内嵌与域刷新跟随内核既有行为。
- **Non-Goals**：不做模板编辑器；不建项目（无 project.yml、无修订记录、无评审链路）；不改导入链路与项目出稿管线；不保证与「导入建项」产物完全等价。

## Decisions

### D1. 复用构建内核（管线 A），不走 HTML 导入（管线 B）

只有内核按模板 styleId 装配并保留封面/页眉/编号；管线 B 的 HTML 导入无法继承模板版式，只保留为「无模板」时的既有路径。

### D2. 组装内核 config 直接调 `build(config=...)`，不建持久项目

配置与 `kernel.config_from_project` 同形：`paths.template` 指向用户模板、`paths.content` 指向临时章节树目录、`documentType` 为 general（自动跳过封面/页眉改写）。Markdown 文件按文件名自然排序复制为 `content/` 下章节文件，拼为同一文档的连续章节。

- **风险**：`build()` 会执行 `validate_content_tree(config)`，对章节树结构可能有硬约束（如要求至少一个 H1）。实现时先以最小树验证；若确需内核放行，仅在 `validate_content_tree` 增加非侵入的可选参数并单独提交评审。

### D3. 标题样式解析复用 ooxml.py，用户映射兜底

- 自动路径：`resolve_heading_styles(styles_root, usage)` 推导 `headingStyles`（级别→styleId），仿 `_find_body_style` 推断 `bodyStyle`。
- 兜底路径：解析不完整/样式为自定义命名时，用 `heading_style_candidates` 列出候选样式，用户在对话框映射级别（styleId→级别，仅本次生效），映射经 `convert_paths` 的 `template_style_map` 下传。
- 极端回退：模板没有任何可用标题样式时，回退 Word 内置「标题 1~6」styleId 约定并告警，不阻断。
- 映射有效性校验复用导入映射规则：至少一个级别 1、映射后无层级跳跃。

### D4. 图片与表格

Markdown 相对路径图片复制到临时 assets 目录并随内核内嵌；表格走内核既有 Markdown 表格渲染。图片缺失或为远程地址时告警不阻断。

### D5. 域刷新

构建后沿用 `set_update_fields` 写 `updateFields`；本机有 Word 时可选走 `scripts/refresh_fields.py` COM 刷新目录页码，无 Word 时保留刷新标记由 Word 打开时刷新，均不阻断。

## Risks / Trade-offs

- `[模板多样性]` 用户模板千差万别（无 numId=1 多级列表、样式命名怪异）→ 标题编号依赖模板约定，无多级列表时退化为无编号标题并在结果中告警。
- `[内核耦合]` 直接调 `build()` 意味着内核校验规则变化会影响本功能 → 以集成测试锁定：`test_template_fill.py` 加入 `DEFAULT_TESTS` 随 CI 门禁执行。
- `[DocGuard 环境]` 仓库文件透明加密，检索与验证必须走受信任进程（Read 工具 / Python），bash grep 不可用。

## Migration Plan

无存量数据迁移，纯增量：新服务 + 新方向行 + 可选参数（默认值不启用）。回滚 = 移除方向行与参数，既有路径不受影响。

## Resolved Defaults

（不阻塞实现，按以下默认值执行）

- 多文件 Markdown 的拼接顺序：按文件名自然排序；对话框内保持用户选择的列表顺序展示，允许拖动调整（实现成本高时先落自然排序）。
- `--template` 仅在与 Markdown 源同用时生效，其余组合在 CLI 校验时报错。
