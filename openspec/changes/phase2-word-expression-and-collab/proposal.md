## Why

第一阶段修复了"每次出稿都撞上"的表层缺陷，但 Doc Tool 距离"正式交付物无需人工二次排版"仍差四类结构性表达：Mermaid 图在 Word 里是 DSL 源码、图/表没有国标式编号题注与文中引用、宽表无法横放、章节顺序只能靠文件名编号。同时协作侧两个高频断点未闭环：Git 拉取冲突把用户丢给外部工具；"重新导入更新源 Word"在主线程同步执行且没有预览。导入保真也停留在纯文本级（粗斜体/超链接/列表层级丢失、合并表格黑盒）。

这些改动需要一定架构调整（公共渲染层扩展、Manifest v2、管线新增预处理阶段、`main_window` 拆分），因此作为第二阶段（v2.7~v2.8）。前置依赖：第一阶段的 `docx_blocks`、`STAGE_AUDIT`、`gates`。

## What Changes

- **Mermaid 构建期出图**：管线新增 `STAGE_PREPARE`（`STAGE_REVISION` 后、`STAGE_BUILD` 前），扫描围栏 ```` ```mermaid ````，用 `mermaid.render`（mmdc 优先，内置 SVG 回退）生成 `assets/<type>/_generated/<sha1>.png`，以图片引用替换后交给构建；按源码 hash 缓存。内置渲染补 `classDiagram`/`stateDiagram`/`gantt` 子集。
- **题注与交叉引用**：采用 Quarto/Pandoc 惯例——`![图名](x.png){#fig-arch}`、表格前行 `Table: 表名 {#tbl-if}`、正文 `@fig-arch`/`@tbl-if`/`@sec-…`。构建生成"图 N-M 图名"段落（`SEQ` 域 + 章号）、书签与 `REF` 域；既有 Word 刷新阶段更新编号；`STAGE_AUDIT` 检测悬空引用。预览同步渲染编号。
- **横向节**：`<!-- SECTION: landscape -->` … `<!-- SECTION: end -->` 在构建时注入拷贝自模板并改 `orient` 的段落级 `sectPr`；导入端把源文档分节/横向页落为同一标记；`validate_docx._section_geometry` 放行。
- **表格宽度自适应**：`make_table_from_md` 累计列宽超版心时按比例缩放并 warning（配合 audit 的 `table_overflow`）。
- **Manifest v2**：`schemaVersion: 2`，新增 `chapters:`（显式章节序列，缺省回退文件名扫描）与 `variables:`（`{{var.name}}` 构建/预览前替换；Lint 检查未定义变量）；`settings_migration` 提供 1→2 迁移与备份。
- **项目设置页扩展**：分页 = 基本信息 / 样式映射（headingStyles、bodyStyle）/ 质量规则（开关、级别、参数）/ 变量 / 门禁（gates）。
- **导入保真升级**：`_para_text` 改为按 `w:r` 遍历输出 `**`/`*`/`[t](url)`/`{#anchor}`；读取 `numPr/ilvl` 生成缩进列表；复杂表格保留 XML 黑盒的同时写出只读"影子 Markdown 表"（`<!-- TABLE:… -->` 下方以 HTML 注释形式嵌入纯文本网格），供搜索/审阅/Diff。
- **Git 冲突解决视图**：拉取产生冲突时，改动面板将冲突文件标红，提供"本地 / 远端 / 手工"三栏视图（`git show :2:`/`:3:`），选择后 `git add` 并提示完成合并提交。
- **重新导入异步化 + 预览**：`ReimportService` 走 `TaskRunner`；完成后弹出章节三态列表（新增/修改/删除/冲突）供逐项勾选合入；冲突章节生成 `<name>.theirs.md` 并可在改动面板双栏比较。
- **工程重构**：`main_window.py` 拆为 `ui/main_window/{window,menu,tasks,git_actions,session,results}.py`；`scripts/{build_docx,validate_docx,refresh_fields,docx_common}.py` 迁入 `doc_tool/kernel/`，`scripts/` 保留薄包装；CI 恢复 coverage 产出并设阈值。

## Capabilities

### New Capabilities

- `build-mermaid-render`: 构建期 Mermaid 渲染、缓存与失败降级语义。
- `build-captions-xref`: 图/表/节题注编号、交叉引用语法与 Word 域生成。
- `build-sections`: 局部横向节标记与导入/构建/校验三端契约。
- `project-manifest-v2`: `chapters`/`variables` 字段、迁移与回退规则。
- `import-inline-fidelity`: 行内格式、列表层级、复杂表影子表的导入契约。
- `vcs-conflict-resolution`: 冲突文件识别、三栏视图与解决动作。
- `reimport-preview`: 异步重导入与逐章节合入。

### Modified Capabilities

- `content-editor`：预览渲染变量替换与题注编号。
- `content-lint`：新增 `undefined_variable`、`dangling_xref` 规则。
- `release-audit`：新增 `dangling_xref` 检查。
- `project-settings`：多页设置。

## Impact

- **代码**：`pipeline.py`（新阶段）、`kernel/build_docx.py`（题注/横向/变量/围栏 mermaid 替换点）、`kernel/validate_docx.py`、`adapters/importer.py`、`domain/manifest.py`、`application/{settings_migration,content/vcs_changes,content/reimport,content/mermaid,content/preview,content/lint}.py`、`ui/settings_dialog.py`、`ui/content/{changes_panel,workspace}.py`、`ui/main_window/*`。
- **数据**：`project.yml` schemaVersion 1→2（自动迁移、备份 `.bak`）；`assets/<type>/_generated/` 进 Git（图片是交付物一部分，可复现）。
- **兼容性**：v1 项目打开时提示迁移；未迁移仍可只读构建。旧语法（无题注的图片、无标记的表格）行为不变。
- **非目标**：所见即所得表格编辑器、PlantUML/Draw.io、AI 能力、无 Word 正式出稿（第三阶段）。

## Decisions

- **Mermaid 出图放在管线阶段而非编辑器保存时**：保证 CLI 构建与 GUI 一致，且源码是唯一事实源；生成图进 Git 便于无 mmdc 环境复现。
- **题注语法采用 Quarto 惯例而非自创**：与 Pandoc/Quarto 生态一致，GitHub 渲染时 `{#fig-…}` 无害；避免私有 DSL。
- **横向节用 HTML 注释标记**：与既有 `<!-- TABLE: -->`、`<!-- P: -->`、`<!-- TBL: -->` 标记体系一致。
- **复杂表先做影子表而非 HTML 表**：零风险地解决"不可搜、不可审"；HTML `<table>` 双向转换留待影子表被证明不够时再做。
- **冲突解决限定 Markdown 文本文件**：二进制（图片/XML 表）冲突只提供"取本地/取远端"。
