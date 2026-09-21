## 目标

让正式 Word 交付物在图（Mermaid）、题注/引用、横向宽表、章节编排四个维度不再需要人工二次排版；让拉取冲突与重新导入在工具内闭环；让导入保真从"文本级"升到"行内格式级"。同时完成两项工程债（`main_window` 拆分、内核入包）。

## 决策

### D1 `STAGE_PREPARE`：源码预处理阶段

- 位置：`STAGE_REVISION` → **`STAGE_PREPARE`** → `STAGE_BUILD`。
- 输入 `content/`，输出内存中的 `PreparedSource{rel_path -> text}` 传给 `build_with_project`（`kernel.config_from_project` 新增 `source_override` 参数），**不改写用户 Markdown**。
- 子步骤（按序）：变量替换 → Include（第三阶段）→ Mermaid 出图替换 → 题注/引用编号预扫描。
- 取消令牌在每个章节边界检查；进度按章节数上报。

### D2 Mermaid 出图

- `mermaid.extract_blocks` 已能定位围栏；对每块计算 `sha1(source + renderer_version)`，目标 `assets/<type>/_generated/mermaid-<sha1[:12]>.png`（存在即复用）。
- 渲染优先级：`tools/mermaid-cli`（`mmdc`）→ 内置 SVG（`_render_flowchart_svg`/`_render_sequence_svg` + 新增 class/state/gantt）→ 失败时保留代码块并发 `warning`（`gates.mermaid: error|warn`，默认 warn）。
- `svg_to_png` 主线程约束：管线在 `TaskRunner` 子线程运行，因此 PNG 栅格化通过 `QMetaObject.invokeMethod(..., BlockingQueuedConnection)` 回主线程；CLI 场景（无 QApplication）由 `_ensure_qgui_application()` 创建离屏实例（`pdf_tools.py:473` 已有同款逻辑）。
- 替换文本：```` ```mermaid ```` 块 → `![<首行 title 或 "图">](_generated/mermaid-xxx.png){#fig-<slug>}`（若块前一行是 `%% title:` 注释则取其为图名）。
- `_generated/` 不进 `ImageAssetsPanel` 的"未使用清理"候选（按目录前缀排除）。

### D3 题注与交叉引用

- 语法：
  - 图：`![图名](path){#fig-id}`；表：表格前一行 `Table: 表名 {#tbl-id}`；节：标题自带（`@sec-<slug>` 或 `@sec-3.2`）。
  - 引用：`@fig-id` / `@tbl-id` / `@sec-id`；可选 `[@fig-id]` 形式与 `见 @fig-id`。
- 编号规则：`图 <一级章号>-<章内序号>`（可配置为全局连续，`manifest.captions.numbering: chapter|global`）。
- Word 生成：
  - 图：图片段落后追加题注段落（模板样式 `Caption`，缺失则创建）：`图 ` + `{SEQ 图 \* ARABIC \s 1}` 域 + ` ` + 图名；整段外包书签 `fig_<id>`。
  - 表：题注段落在表格**前**（国标习惯），`SEQ 表`。
  - 引用：`{REF fig_<id> \h}` 域，缓存值预填"图 N-M"以便未刷新时也可读；`ExpressionManager` 已管理书签与关系，扩展 `register_caption()`/`append_ref()`。
- `SEQ \s 1` 依赖标题为 Heading 1 大纲级别——`_effective_heading_styles` 已保证。
- 预览：`preview.render_markdown_html` 预扫描编号并把 `@fig-id` 渲染为链接。
- 校验/终审：`lint.dangling_xref`（引用不存在的 id、重复 id）；`audit.dangling_xref` 检查产物中 `REF` 域缓存值为空。

### D4 横向节

- 标记：`<!-- SECTION: landscape -->` … `<!-- SECTION: end -->`（不闭合视为到章节末）。
- 构建：块结束处的最后一个段落 `pPr` 内注入 `sectPr`（拷贝模板 `body/sectPr`，交换 `pgSz` w/h，`orient=landscape`，页边距上下左右按旋转映射）；块前一个段落也注入一份原始 `sectPr` 以关闭前一节。页眉页脚关系 `r:id` 沿用模板，确保横向页仍有受控页眉。
- 表格自适应：横向节内 `usable_page_width_emu` 取横向版心。
- 导入：`extract_content` 遍历时遇 `pPr/sectPr` 且 `orient=landscape` → 在该段落之后输出 `<!-- SECTION: end -->`、在上一 `sectPr` 之后输出 `<!-- SECTION: landscape -->`；显式 `w:br type=page` → `<!-- PAGEBREAK -->`（构建为 `w:br type=page`）。
- 校验：`validate_docx._section_geometry` 改为比对"节序列"而非"唯一节"；`word_semantic_preservation_errors` 允许节数 ≥ 模板。

### D5 Manifest v2

```yaml
schemaVersion: 2
chapters:            # 可选；存在则按此顺序，未列出的文件不进构建（Lint 提示）
  - 前言.md
  - 第1章 概述/
  - 附录A 术语表.md
variables:
  system_name: 呼吸机中央监护系统
  customer: XX 医院
gates: {lint: warn, audit: error, mermaid: warn}
captions: {numbering: chapter}
```
- `chapters` 条目可为文件或目录（目录内仍按文件名扫描）。`scan_entries(config)` 新增 `explicit_order` 分支；`tree.py`/`ContentIndex` 排序同步。
- 变量替换：`{{var.system_name}}` 与 `{{doc.version}}`/`{{doc.name}}`/`{{doc.no}}`（来自 manifest）；未定义 → `lint.undefined_variable`(error)。围栏代码块内不替换。
- 迁移：`settings_migration.migrate_v1_to_v2()` 只加字段、备份 `project.yml.bak`；打开 v1 项目弹"升级项目文件？"，拒绝则只读。

### D6 设置页

- `SettingsDialog` 改 `QTabWidget`：基本 / 样式映射（下拉选模板样式，复用 `wizard._StyleMappingPage` 的样式列举）/ 质量规则（`QualityRulesConfig` 打开 `writable=True`，表格编辑）/ 变量（键值表）/ 门禁。
- 保存仍走 `manifest.save(backup=True)`；质量规则保存到既有 `.state/quality_rules.json`。

### D7 导入保真

- `_para_text` → `_para_markdown(p, rel_map)`：遍历 `w:r`/`w:hyperlink`/`w:bookmarkStart`：
  - `rPr/b` → `**`，`rPr/i` → `*`，`b+i` → `***`；相邻同格式 run 合并；格式跨越空白时把空白挪到标记外（避免 `** x**`）。
  - `w:hyperlink r:id` → `[text](target)`；内部 `w:anchor` → `[text](#anchor)`。
  - `bookmarkStart` 名不以 `_` 开头（用户书签）→ 段末 `{#name}`。
  - `numPr/ilvl` → 缩进 2×ilvl 空格的 `- ` / `1. `；`roundtrip._event_text` 比较 ilvl。
- 复杂表影子：`_emit_table` 黑盒分支在 `<!-- TABLE:n:file -->` 后追加
  ```
  <!-- TABLE-SHADOW-BEGIN -->
  | 合并单元格表（只读镜像，请在 Word 中编辑 assets/.../tbl_0001.xml） |
  | 单元格1 | 单元格2 | … |
  <!-- TABLE-SHADOW-END -->
  ```
  构建端跳过 SHADOW 区间；`ContentIndex` 索引其文本；编辑器把该区间渲染为只读灰底提示。

### D8 冲突解决视图

- `PullResult.conflicts` 非空 → `ChangesPanel` 进入"冲突模式"：列表置顶红色项；选中后三栏（本地 `:2:` / 合并结果 / 远端 `:3:`）用现有 side-by-side 组件扩展；按钮"取本地"/"取远端"/"在编辑器手工解决"。
- 解决后 `git add <file>`；全部解决后提示"完成合并提交"（复用 `git_commit_dialog`，消息预填 `Merge …`）。
- SVN：`svn resolve --accept mine-full|theirs-full`。
- 二进制/XML 表格文件只提供取本地/取远端。

### D9 重新导入

- `main_window._on_reimport_source` → `TaskSpec(reimport)` 后台执行，`ReimportService.plan(source) -> List[ChapterChange]` 与 `apply(selected)` 拆分为两步。
- 预览对话框 `ui/reimport_preview_dialog.py`：三态列表 + 勾选 + 双击查看 diff；冲突项默认不勾选并生成 `<name>.theirs.md`。
- 应用后触发 `_rebuild_index`、改动面板刷新；`.theirs.md` 被 `scan_entries` 忽略（下划线/点前缀规则扩展为 `.theirs.md` 后缀）。

### D10 工程重构

- `main_window.py` 拆分：`window.py`（壳与生命周期）、`menu.py`（菜单/快捷键/命令注册）、`tasks.py`（TaskRunner 编排与结果处理）、`git_actions.py`（分支弹层与 Git 动作）、`session.py`（几何/主题/Dock 状态）。对外 `MainWindow` 类名与信号不变。
- 内核入包：`doc_tool/kernel/{build_docx,validate_docx,refresh_fields,docx_common}.py`；`scripts/*.py` 变为 `from doc_tool.kernel.x import main; sys.exit(main())`；删除 `adapters/kernel.ensure_kernel_importable` 的 sys.path 注入；`doc_tool.spec` hiddenimports 相应更新。
- CI：`run_tests.py --coverage --coverage-min 80` 并上传 `coverage.json`；测试并行 `-j 4`（进程已隔离）。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| `SEQ`/`REF` 域在 Word 刷新前显示旧值 | 域缓存值预填正确编号；快速构建产物明确标注"草稿" |
| 横向节破坏页眉页脚/模板校验 | 新节拷贝模板 `sectPr` 全量属性；`validate_docx` 增加节序列用例；先在 1 份真实文档验证 |
| Manifest v2 迁移失败 | 备份 + 失败回滚（沿用 `manifest.save(backup=True)`）；v1 仍可只读 |
| 行内格式导入引入 `**` 误配 | 空白外移规则 + 往返门禁比较可见文本；提供导入选项"不保留行内格式" |
| `main_window` 拆分回归 | 先补 `test_gui_services` 的菜单/快捷键/任务流用例，再拆；分 PR |
| Mermaid 栅格化跨线程崩溃 | 统一经主线程 invoke；CLI 离屏 QGuiApplication；覆盖测试 |

## 验收标准

- 含 3 种 Mermaid 图的章节正式出稿后 Word 中为 PNG 图 + 题注；二次构建复用缓存（日志显示 hit）。
- `![架构](a.png){#fig-arch}` + 正文 `见 @fig-arch` → Word 中"图 3-1 架构"与"见 图 3-1"，Ctrl+点击可跳转；删除图后 Lint 报 `dangling_xref`。
- 横向节内 12 列表格正式出稿后为横向页、页眉正确、后续页恢复纵向；`validate` 通过。
- `chapters:` 指定 `前言.md` 在首位后构建/树/搜索顺序一致；未列出文件 Lint 提示。
- `{{var.system_name}}` 在预览与 Word 中均被替换；未定义变量 Lint error 阻断（`gates.lint: error`）。
- 含粗体/超链接/二级列表/合并表的源 Word 导入后：Markdown 含 `**`/链接/缩进列表；影子表可被 Ctrl+F 搜到；往返门禁通过。
- 人为制造 Git 冲突后拉取：面板标红、三栏可选、解决后提交成功。
- 重新导入 200 章文档 UI 不冻结；预览对话框可只勾选 3 个章节合入。
- `main_window` 拆分后 `test_gui_services`/`test_multi_window`/`test_command_palette` 全绿；`scripts/build_docx.py` 仍可独立运行。
- CI coverage ≥ 80% 且 `coverage.json` 时间戳为当次构建。
