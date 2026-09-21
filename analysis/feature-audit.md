# Doc Tool 全功能审查与演进分析（feature-audit）

> 基准：本地工作区 `doc-tool` HEAD `12e8483`（v2.5.1，2026-09-20）。
> 事实来源：仅以本地代码为准（`doc_tool/` 56,110 行 Python、`scripts/` 内核与 57 个测试文件、`openspec/`、`packaging/`）。README / `L0_*` / `L1_*` 报告只作对照。
> 本次只分析，不改业务代码。

## 0. 与既有分析报告的关系（先读、再验证、不重复）

| 既有报告 | 本次验证结论 |
|---|---|
| `L1_DOC_TOOL_GAP_ANALYSIS_REPORT.md`（基于 v2.5.0） | 其 5 项 P0 在 HEAD **全部仍未修复**：① `scripts/build_docx.py:process_markdown` 无围栏代码块状态机（仅 L107 `parse_inline_runs` 对 ```` ``` ```` 行做“原文返回”）；② `build_docx.py`/`pipeline.py`/`kernel.py` 0 处引用 `mermaid`；③ 无 Caption / `SEQ` 域；④ 全文无 `landscape`/`orient`；⑤ 全仓库无 `Bookmark not defined` 检测。**本报告不再重复论证，只在功能表中引用。** |
| L1 报告的 `<br>` 泄漏结论 | **部分过时**：`domain/markdown_structure.py:split_table_row` 已把 `<br>` 还原为 `\n`，`build_docx.py` 表格/段落/标题/列表路径均已 `re.sub(<br>)`。表格 `<br>` 泄漏在 HEAD 已闭环，**从 P0 移除**。 |
| `docs/roadmap.md` 6 个计划 | 计划 1~5 代码已落地；计划 6（`quality-traceability-and-review`）**服务层完成、UI/CLI 未集成**：`traceability.py`、`export/pdf_html.py` 在 `doc_tool/ui`/`cli` 中 **0 引用**；`baselines.py`/`history.py` 仅在发布前检查和归档处被动调用。 |
| `openspec/changes/revision-review-export` | tasks 0/25，纯设计稿；但 `review_docx.py`（1,847 行）+ `review_panel.py`（1,184 行）已用另一路径实现了评审稿导出/意见回流，**该 change 与现状脱节，应归档或重写**。 |
| `coverage.json` | 快照日期 2026-08-21，当时 `main_window.py` 1,190 语句；现 3,588 行。总覆盖 83.8% **已失真**，UI 大文件真实覆盖偏低。 |

---

## 1. 当前产品定位

1. Doc Tool 是一个 **Windows 桌面（PySide6）+ CLI** 的 Docs-as-Code 工作台：把受控 Word 拆成 Markdown 章节树，日常在 Markdown/Git 里协作，出稿时按企业模板重建 DOCX 并用本机 Word 刷新域。
2. 核心用户：**中国企业内部的技术文档工程师/研发**（需求规格、详细设计等受控交付物），环境特点：Windows 10/11、有透明加密/终端管控、多数机器有 Office、部分只有 Git 或 SVN。
3. 核心工作流（代码里真实存在的闭环）：`ImportWizard` 6 步导入（预检→保真→样式映射→试构建往返门禁）→ 章节树 + 编辑器 + 搜索/替换/重构/Lint → 改动面板（Git/SVN/本地快照）→ 评审稿导出 + 评审单回流 → `_revision_record.md` 驱动版本 → `run_pipeline` 六阶段（修订→构建→前校验→Word 刷新→后校验→原子发布）。
4. 做到的程度：**底座扎实**（安全 OOXML 解析、原子写、项目锁、崩溃草稿、进程树隔离的 Word COM、SBOM/签名/加固打包），**工作台功能面很宽**（14 个菜单动作 + 9 个侧栏面板 + 命令面板 + 15 项 PDF 工具 + 20 余种格式互转）。
5. 但 **"出稿表达力"落后于"编辑体验"**：代码块、Mermaid、题注、横向页在正式 Word 里都不成立；且已经写好的追溯矩阵、PDF/HTML 评审导出、构建历史等服务没有入口。
6. 一句话：**已是一个能用的团队内部工具（2.x），距离"成熟企业级 Docs-as-Code 工作台"差的是交付物表达完整性 + 发布门禁 + 把已有服务层暴露出来，而不是再加新面板。**

---

## 2. 完整功能地图

成熟度：★★★★ 生产可用 / ★★★ 可用但有明显缺口 / ★★ 入口存在闭环不全 / ★ 仅服务层或占位

| 一级模块 | 二级功能 | 当前实现 | 代码入口 / 关键文件 | 成熟度 |
|---|---|---|---|---|
| **A 导入** | Word→Markdown 工程化拆分 | 大纲识别、图片/表格/段落格式标记、按标题层级生成目录树 | `adapters/importer.py:extract_content/split_into_tree`、`application/import_project.py` | ★★★ |
| | 导入预检 | 结构/标题样式/损坏检查，旧 `.doc` 防呆 | `adapters/preflight.py`、`ui/wizard.py:_PreflightPage` | ★★★★ |
| | 保真扫描 | 11 类特性 BLOCK/WARN/INFO 分级 | `adapters/fidelity.py:FEATURE_DEFS` | ★★★★ |
| | 样式映射向导 + 大纲树实时预览 | 非标准 Heading 映射 | `ui/wizard.py:_StyleMappingPage`、`manifest.headingStyles` | ★★★★ |
| | 往返门禁（Roundtrip Guard） | 导入后试构建并做事件级比对 | `adapters/roundtrip.py:roundtrip_diff`、`import_project.py` | ★★★ |
| | 重新导入更新源 Word | 三态章节差异、冲突保留本地 | `application/content/reimport.py`、`main_window._on_reimport_source` | ★★ |
| **B 结构** | 章节树 / 拖拽重排 / 重编号 / 新增 / 删除 / 重命名 | 完整 | `ui/content/tree_panel.py`、`application/content/tree.py`、`refactor.py` | ★★★★ |
| | 章节引用联动重构 | 重命名后更新引用 | `application/content/refactor.py:RefactorEngine` | ★★★★ |
| | 引用分析 | 死链/被引用 | `application/content/references.py`、`ui/content/references_dialog.py` | ★★★ |
| | 文件名编号即排序 | 无 manifest 显式 `chapters` 编排 | `scripts/docx_common.py:scan_entries/parse_title` | ★★★ |
| **C 编辑** | Markdown 编辑器 + 工具栏 | 15 个按钮、Ctrl+S/查找/替换 | `ui/content/editor_panel.py:_build_markdown_toolbar` | ★★★★ |
| | 双栏实时预览 | QWebEngine（源码态）/ QTextBrowser 降级；**冻结包排除 WebEngine** | `web_preview_browser.py`、`packaging/doc_tool.spec:142` | ★★★ |
| | 表格美化 / Tab 跳格 | Unicode 宽度对齐 | `application/content/table_format.py` | ★★★★ |
| | 代码高亮（编辑器内） | 8 种语言原生词法 | `ui/content/editor_highlight.py` | ★★★★ |
| | 图片粘贴/拖入/资源面板 | 缺失/未用清理 | `asset_manager.py`、`image_assets_panel.py` | ★★★★ |
| | Mermaid 工作台 | 校验/内置 SVG/mmdc/批量转 PNG | `application/content/mermaid.py`、`mermaid_dialog.py` | ★★★（预览端） |
| | 拼写检查 / 术语词典 | 红线 + 用户词典 | `spellcheck.py`、`resources/dict` | ★★★ |
| | 代码片段 | 占位符 Tab 跳转 | `snippets.py`、`snippet_dialog.py`（coverage 0%） | ★★ |
| | 自动草稿 / 崩溃恢复 / 会话恢复 | 完整 | `autosave.py`、`workspace_state.py`、`unsaved.py` | ★★★★ |
| | 专注模式 / 深色主题 / Ctrl+1..9 切 Tab | 完整 | `main_window.toggle_zen_mode/_toggle_theme` | ★★★★ |
| **D 检索** | 全文搜索 / 正则 / 全字 | 内存索引线性扫描 | `search.py:SearchService.search` | ★★★ |
| | 全局替换 | 预览 + 撤销 | `replace.py`、`replace_panel.py`（coverage 47%） | ★★★ |
| | 快速打开 Ctrl+P（拼音） | 完整 | `main_window.open_quick_open` | ★★★★ |
| | 命令面板 Ctrl+K | 约 45 条命令 | `ui/command_palette.py`、`main_window.open_command_palette` | ★★★★ |
| **E 质量** | Lint 11 规则 + QuickFix + SARIF | 完整 | `lint.py`、`quality_rules.py`、`lint_panel.py` | ★★★★ |
| | 问题中心 | 三源聚合 | `application/issues.py`、`issues_panel.py` | ★★★ |
| | 项目校验 F5 | 结构/资源/门禁 | `main_window._on_validate`、`scripts/validate_docx.py` | ★★★★ |
| | 追踪矩阵（需求-设计-测试） | **仅服务层** | `traceability.py`（UI/CLI 0 引用） | ★ |
| | 质量规则配置页 | 只读加载，无编辑 UI | `quality_rules.py`（`writable=False` 两处） | ★ |
| **F 出稿** | 快速构建（无 Word） | 完整 | `_on_diag_build` → `pipeline.run_pipeline(skip_word_refresh)` | ★★★★ |
| | 正式出稿（Word 刷新 + 原子发布 + 回滚） | 完整 | `pipeline.py:_run_pipeline_inner`、`scripts/refresh_fields.py` | ★★★★ |
| | Markdown→Word 表达 | 标题/段落/行内 b/i/code/链接/脚注/书签/多级列表/表格/图片 | `scripts/build_docx.py:process_markdown` | ★★★ |
| | 代码块 / Mermaid / 题注 / 横向节 | **均未实现** | 同上（见 §0） | ✗ |
| | 修订记录驱动版本 | 末行版本→封面/页眉/文件名 | `revision_record.py`、`pipeline._prepare_revision_sync` | ★★★★ |
| | 发布前检查清单 | 基线/检查项 | `baselines.py:pre_publish_checks`、`_confirm_pre_publish_checks` | ★★★ |
| | 构建历史归档 | 仅写入，无查看 UI | `history.py:BuildHistoryStore.archive` | ★ |
| | 校验报告预览 | 内置筛选 | `_show_validation_report_preview` | ★★★ |
| **G 协作** | Git/SVN 改动检测 + 本地快照兜底 | 三源 | `vcs_changes.py:ChangeDetectionService` | ★★★★ |
| | 提交 / 推送 / 拉取 / Stash / 分支 CRUD | 完整 | `branch_popover.py`、`git_commit_dialog.py`、`changes_panel.py` | ★★★★ |
| | Diff 查看（unified / side-by-side） | 完整 | `changes_panel.py` | ★★★★ |
| | 冲突处理 | 仅报告冲突文件名 | `vcs_changes.py:PullResult.conflicts` | ★★ |
| | 评审稿导出（前后对照 DOCX） | 完整 | `review_docx.py:build_review_draft_docx`、`review_panel.py` | ★★★★ |
| | 评审单回流 / 意见台账 / 证据 / 纪要 / 签审门禁 | 完整（UI 内） | `review_docx.py:extract_comments_from_docx`、`review_store.py:approval_gate` | ★★★ |
| | PDF/HTML 版本评审导出 + 视觉 diff | **仅服务层** | `export/pdf_html.py`（UI/CLI 0 引用） | ★ |
| **H 工具箱** | 文档互转（20+ 方向） | Word COM + 离线 | `application/convert.py`、`adapters/word_convert.py`、`convert_dialog.py` | ★★★★ |
| | PDF 工具箱 15 项 | pypdf + Qt 渲染 | `application/pdf_tools.py`（2,709 行）、`pdf_toolbox_dialog.py` | ★★★★ |
| **I CLI** | 15 个子命令，json 输出，SARIF/JUnit | `build/info/preflight/import/validate/lint/search/status/migrate/autolink/renumber/convert/pdf` | `doc_tool/cli.py`、`cli_commands.py` | ★★★ |
| **J 运行时** | 项目锁 / 取消令牌 / 运行日志 | 完整 | `domain/project_lock.py`、`cancellation.py`、`runtime_log.py` | ★★★★ |
| | 多窗口多项目 | 窗口注册表 | `ui/window_registry.py`、`test_multi_window.py` | ★★★★ |
| | 项目设置 | 6 个字段 | `ui/settings_dialog.py`（77 行） | ★★ |
| | 设置迁移 / 项目迁移 | 完整 | `settings_migration.py`、`migrate_project.py` | ★★★ |
| | 启动自愈 / 诊断 | 冻结态诊断日志 | `application/self_heal.py`、`packaging/portable/diagnose.cmd` | ★★★★ |
| **K 分发** | 安装版 / 便携版 / 签名 / SBOM / 加固 | 完整 CI | `packaging/*.ps1`、`.github/workflows/build-release.yml` | ★★★★ |
| **L 测试** | 57 文件 ≈1,400 test 函数，自定义 runner | 完整但 coverage 快照过期 | `scripts/tests/run_tests.py` | ★★★ |

README 未体现但代码存在的重要能力：SVN 支持、追踪矩阵、PDF/HTML 评审导出、构建历史、检查点/基线、代码片段、拼写检查、`autolink`/`renumber`/`migrate` CLI、评审纪要 DOCX、审批门禁 `approval_gate`。

---

## 3. 逐功能审查

优先级定义：P0 正确性/数据安全/核心流程；P1 高价值近期；P2 明显改善；P3 长期。

### 3.1 导入（Word → Markdown）

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 行内格式提取 | `_para_text` 只收 `t/tab/br/cr` | 粗体/斜体/超链接 URL/内部书签在导入即丢失；而构建端 `parse_inline_runs` 已支持 `**`/`*`/`` ` ``/链接/脚注 → **导入端是保真短板** | 按 `w:r` 遍历 `rPr`(b/i/u/strike) 与父 `w:hyperlink` 的 `r:id` 输出 `**x**`/`*x*`/`[t](url)`；书签转 `{#anchor}`；结果计入 `fidelity` 报告的"实际保留"列 | 高 | 中 | **P1** | `importer.py:442-453`；`build_docx.py:105-180` |
| 合并单元格表格 | `_table_is_simple` 遇 `gridSpan/vMerge/嵌套/图片` → 整表 XML 黑盒 `assets/.../tables/tbl_xxxx.xml` | 企业文档大量表头合并 → 表内文字在 Git/编辑器不可见不可搜；`search.py` 也搜不到 | 二选一：(a) 导出 HTML `<table>` 子集（colspan/rowspan），构建端 `make_table_from_md` 增加 HTML 表解析；(b) 保持 XML 黑盒但**同时**写出只读 Markdown 影子表供搜索/审阅并在编辑器展示"此表为受控 XML，点此在 Word 中编辑" | 高 | 高(a)/低(b) | **P1**(先 b 后 a) | `importer.py:647-657,586-645` |
| 列表层级 | `_emit_paragraph` 只看 `numPr` 是否存在 + 字符启发 | `ilvl` 未读 → 多级列表扁平化，往返门禁把 L 事件去编号比较后掩盖了该损失 | 读取 `numPr/ilvl` 生成缩进 `  - `，并让 `roundtrip._event_text` 比较 ilvl | 中 | 低 | **P1** | `importer.py:536-556`；`roundtrip.py:168-180` |
| 分节/分页符 | 仅保留末尾 `sectPr` | 横向页/分页意图丢失，与构建端"单节锁"互为因果 | 导入时把 `w:sectPr` 与 `w:br type=page` 落为 `<!-- SECTION:landscape -->`/`<!-- PAGEBREAK -->` 标记（构建端同步支持，见 3.5） | 高 | 中 | **P1** | `importer.py:266-410` |
| 保真扫描→用户决策 | BLOCK 项弹窗确认后放行 | 放行后没有"损失清单"落盘到项目，事后无法追责 | 把 `fidelity` 报告写 `.state/import_fidelity.json` 并在问题中心展示为 INFO 项 | 中 | 低 | P2 | `wizard.py:_PreflightPage`、`import_project.py` |
| 重新导入 | `ReimportService.reimport` 同步执行，结果 `QMessageBox` | ① 在 UI 主线程同步跑（大文档卡死）；② 无预览/无逐章节选择；③ 冲突只是"保留本地"，无三方合并视图 | 复用 `TaskRunner` 后台执行 → 变更预览对话框（章节三态 + 选择合入）→ 冲突章节生成 `.theirs.md` 并在改动面板双栏对比 | 高 | 中 | **P1** | `main_window.py:2312-2329`；`reimport.py` |
| 大文档导入反馈 | `_ExecutingPage` 有阶段进度 | 无章节级计数、无取消 | 接 `CancellationToken`，进度按 `body` 子元素计数 | 中 | 低 | P2 | `wizard.py:_ExecutingPage`、`domain/cancellation.py` |

### 3.2 结构与章节树

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 章节排序 | 物理文件名 `第X章`/`N.M` 决定顺序 | 无编号章节（前言/附录/术语表）无法参与；插入章节需要批量重编号（已提供 renumber，但会造成大 diff 噪音） | `project.yml` v2 增加可选 `chapters:` 显式序列（缺省回退扫描）；`renumber` 仍保留 | 高 | 中 | **P1** | `docx_common.py:scan_entries/parse_title`、`manifest.py` |
| 拖拽重排 | `_on_move_node` 落盘重命名 | 一次拖拽=多文件 rename，Git 视为删除+新增（`--follow` 可跟）；无撤销 | 拖拽后弹"预览重命名清单 + 一键撤销（复用 `ChangeJournal`）" | 中 | 低 | P2 | `workspace.py:1544-1634`、`writer.py:ChangeEntry` |
| 删除章节 | 删除后询问是否重编号 | 删除不进回收站，仅靠 Git/快照兜底；本地快照模式下不可恢复文件内容？→ 已有 `.bak` 仅覆盖最近一次 | 删除移动到 `.state/trash/<ts>/`，改动面板可恢复 | 中 | 低 | **P1** | `workspace.py:1274-1392`、`writer.py:5-11` |
| 引用分析 | 对话框列表 | 无"修复死链"动作、无跨项目引用 | 死链项右键"重定向到…"复用 `RefactorEngine` | 低 | 低 | P3 | `references_dialog.py`（coverage 0%） |

### 3.3 编辑器

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 实时预览 | 源码运行走 `QWebEngineView`（marked+mermaid.js）；**打包 spec 显式 excludes WebEngine** → 终端用户只会得到 `QTextBrowser` 降级 | 开发者与最终用户看到的预览不是同一套；`preview.html`/`mermaid.min.js` 资源随包但无人用；用户看不到 mermaid 原生渲染 | 二选一并写进发布决策：(a) 打包 WebEngine（+~120MB，需加固脚本处理 `QtWebEngineProcess.exe`）；(b) 删除 WebEngine 路径，把内置 SVG 渲染做成唯一路径并补齐 class/state/gantt。**建议 (b)**，并让 CI 冻结冒烟测试断言 `HAS_WEB_ENGINE is False` 下功能完整 | 高 | 中 | **P0**（体验一致性/隐性缺陷） | `editor_panel.py:48-52,606-609`；`doc_tool.spec:142-144`；`resources/web_preview/` |
| Mermaid | 校验 + 内置 flowchart/sequence SVG + 可选 mmdc | 只支持 2 种图；`svg_to_png` 首次调用必须主线程（`mermaid.py:974`）→ 批量转换在后台线程会抛错 | 内置渲染扩展 classDiagram/stateDiagram/gantt/er 的子集；PNG 栅格化改为 QueuedConnection 回主线程 | 高 | 中 | **P1** | `mermaid.py:705,914,959-1003` |
| 表格编辑 | 文本级美化 + Tab | 无所见即所得表格、无列增删、无 CSV 粘贴转表 | 编辑器右键"表格→插入列/删除列/从剪贴板 CSV 生成" | 中 | 低 | P2 | `table_format.py`、`editor_panel.py:1242-1287` |
| 图片 | 粘贴/拖入自动命名 | 无压缩、无 DPI 归一化提示；大图直接进 assets 导致仓库膨胀 | 粘贴时按 `max_image_width` 可选缩放 + PNG 量化；面板显示尺寸/体积并支持一键压缩 | 中 | 低 | P2 | `asset_manager.py`、`editor_panel.py:1311-1359` |
| 拼写/术语 | 词典 + 红线 | 术语库是用户词典级别，无企业级"术语 → 规范写法"映射与 QuickFix | 术语库升级为 `terms.yml`（错误写法→标准写法→说明），Lint `term_case` 规则用它做替换建议 | 中 | 低 | **P1** | `spellcheck.py:UserDictionary`、`lint.py:term_case` |
| 片段 | 占位符展开 | UI 覆盖 0%，无项目级共享片段 | 片段存 `project/.doctool/snippets.yml` 随 Git 共享 | 低 | 低 | P3 | `snippets.py`、`snippet_dialog.py` |
| Outline | 无独立大纲面板（预览有锚点） | 长章节内导航靠滚动 | 编辑器左侧折叠式标题大纲（复用 `ContentIndex.headings`） | 中 | 低 | P2 | `content_index.py:HeadingEntry` |
| 编辑器撤销与文件级回滚 | `rollback_last` 用 `.bak` 仅一份 | 二次保存后上上版不可回 | 引入 `.state/local_history/<rel>/<ts>.md`（VS Code Local History 模式），保留 N 份 | 中 | 低 | **P1** | `editor_panel.py:758-809`、`writer.py:24-52` |

### 3.4 搜索 / 替换 / 命令面板

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 全文搜索 | `ContentIndex.lines` 全量驻留内存，线性正则 | 千章节仍可接受，但每次 `_rebuild_index` 全量重读；搜索不含黑盒表格 XML 与图片 alt | 增量刷新按 mtime（已有 `invalidate/refresh` 钩子，未按 mtime 驱动）；为 XML 表格生成影子文本参与索引 | 中 | 低 | P2 | `search.py:112-125`、`content/index.py:99-118`、`content_index.py:141-152` |
| 全局替换 | 预览 + 应用 + 撤销 | 面板覆盖 47%；无正则捕获组替换预览高亮 | 补测试；支持 `$1` 回引 | 低 | 低 | P3 | `replace_panel.py` |
| 命令面板 | 45 条静态命令 | 不含"最近文件/章节"、不含面板内动作（如"导出评审稿""设为基线"） | 命令注册表化：各面板向 `CommandRegistry` 注册，面板动作自动出现在 Ctrl+K | 中 | 中 | P2 | `main_window.open_command_palette:601-874` |

### 3.5 出稿（Markdown → Word）

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 围栏代码块 | 无状态机；` ``` ` 行按普通段落 | 正式 Word 中代码逐行变宋体正文 | 在 `process_markdown` 增加 fence 状态机，复用 `review_docx._create_code_block_box`（浅灰底/边框/Consolas）；抽到 `scripts/docx_blocks.py` 供两处共用 | 高 | 低 | **P0** | `build_docx.py:2049-2249`；`review_docx.py:1059-1103` |
| Mermaid 出稿 | 0 集成 | 预览有图、Word 里是 DSL 源码 | 构建前阶段（`STAGE_BUILD` 之前）调用 `mermaid.render` 生成 `assets/_generated/<hash>.png` 并替换为图片引用；`mmdc` 可用优先；缓存按源码 hash | 高 | 中 | **P0** | `pipeline.py:651-680`；`mermaid.py:959` |
| 图/表题注与交叉引用 | 图 alt 只进 `docPr/@descr`；表无题注 | 不满足"图 3-1 / 表 2-3 / 见图 3-1"硬性规范 | 语法采用 Quarto/Pandoc 惯例：`![图名](x.png){#fig-arch}`、表格前一行 `Table: 表名 {#tbl-if}`，正文 `@fig-arch`；生成 `SEQ 图 \* ARABIC \s 1` 域 + 书签 + `REF` 域，由既有 Word 刷新更新编号；`ExpressionManager` 已有书签/超链接基础 | 高 | 中 | **P0** | `build_docx.py:1218-1260,348-780` |
| 横向页/分节 | 单 `sectPr` | 宽表被裁 | 支持 `<!-- SECTION: landscape -->` … `<!-- SECTION: end -->`：在段落 `pPr` 内注入拷贝自模板并改 `orient` 的 `sectPr`；`validate_docx._section_geometry` 需放行 | 高 | 高 | **P1** | `build_docx.py:2270-2460`；`validate_docx.py:706` |
| 表格宽度门禁 | 列宽累计不检查 | 超版心表格静默放行 | `make_table_from_md` 累计 `widths` > `usable_page_width_emu` 时按比例缩放并 `warning`，作为后校验项 | 中 | 低 | **P1** | `build_docx.py:930-1031,1180` |
| 引用/脚注/HR/引用块 | 支持 `[^n]`、`[]()`；无 `>` 引用块、无 `---` 分隔、无任务列表 | 常用 Markdown 在 Word 里退化 | 引用块→模板 `Quote` 样式或左缩进+左边框；`---` → 分页或细线（可配置） | 中 | 低 | P2 | `build_docx.py:2049` |
| 文档变量 | 无 | 系统名/版本/客户名散落各章节 | manifest `variables:` + `{{var.x}}` 在 `process_markdown` 前替换；Lint 检查未定义变量 | 中 | 低 | **P1** | `manifest.py`、`build_docx.py` |
| Include / 共享章节 | 无 | 多份文档共享"术语表/约定" | `<!-- INCLUDE: ../common/terms.md -->`，构建与预览同解析；限制在项目根内（防路径穿越，复用 `_resolve_inside`） | 中 | 低 | P2 | `writer.py:68` |
| 发布终审（Audit） | 无 | Word 刷新后 `错误!未定义书签`、TODO 残留、空标题、图片缺 alt 无人拦 | 在 `STAGE_VALIDATE_POST` 后新增 `STAGE_AUDIT`：扫描 `w:t` 错误文本、`todo_residual`、表格越界、连续空段；失败则不发布 | 高 | 低 | **P0** | `pipeline.py:60-67`；`word_convert.py:381`（只在互转里提到该错误） |
| 构建性能 | 每次全量重建；图片去重有 | 无增量、无缓存；`process_markdown` 每文件全部 lxml 插入 | 先测：建立 800 页基准；再做 Mermaid/图片 hash 缓存 | 中 | 中 | P2 | `build_docx.py:1056-1110` |
| 无 Word 环境正式出稿 | `skip_word_refresh` 强制 `formal=False` | Linux CI/无 Office 机器永远出不了正式稿 | 提供"预发布制品 + 远程刷新"模式：CI 产 `.prerelease.docx`，任一有 Word 的机器执行 `doc-tool refresh --promote` 完成正式化（状态机新增 `staged`） | 中 | 中 | P2 | `pipeline.py:620-680`、`domain/output_state.py` |

### 3.6 校验 / Lint / 问题中心

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| Lint 与构建门禁 | Lint 是独立动作 | `build` 不会因 Lint error 阻断 | `run_pipeline` 前置 `STAGE_LINT`（可在 manifest `gates.lint: error|warn|off` 配置） | 高 | 低 | **P1** | `pipeline.py`、`cli.py:33-37` |
| 质量规则配置 | `QualityRulesConfig` 仅只读加载 | 用户无法在 UI 开关规则/改级别 | 项目设置增加"质量规则"页（表格：规则/级别/开关/参数） | 中 | 低 | **P1** | `quality_rules.py`、`main_window.py:1459,1717` |
| CLI 统一入口 | `lint`/`validate`/`build` 分散 | CI 需拼 3 条命令、退出码语义不统一 | `doc-tool check --project X --format sarif` = lint + 结构校验 + (可选)构建；退出码 0/1/2 | 高 | 低 | **P1** | `cli.py`、`cli_commands.py` |
| 追踪矩阵 | 服务层完整（ID 正则 + 章节引用） | 无 UI/CLI 入口 → 用户不可见 | 最小落地：`doc-tool trace --project` 输出 md/json + 问题中心新增"未覆盖需求"；UI 后置 | 中 | 低 | P2 | `traceability.py`（0 引用） |

### 3.7 修订记录 / 基线 / 历史

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 生成修订记录 | 弹窗给"章节→小节"定位清单，作者手工写 | 设计取舍合理（模块 docstring 有论证），但连"改动章节列表 + Git commit 摘要"都没预填 | 预填：改动小节 + 该小节区间的 git log 主题行（非 AI），一键"追加为新行（版本自增）"，仍需作者确认 | 中 | 低 | **P1** | `revision_record.py:1-30`、`changes_panel.py:1227-1234` |
| 版本基线/检查点 | `BaselineStore/CheckpointStore` | 无 UI 列表/对比/恢复 | 改动面板"基线"下拉：查看/切换比较基线/恢复检查点 | 中 | 低 | P2 | `baselines.py`、`workspace.set_current_as_baseline` |
| 构建历史 | `BuildHistoryStore.archive` 发布后归档 | 无查看、无两版 diff、无回滚 | "输出"卡片增加历史列表 → 双击打开 / 与当前 diff（复用评审稿生成器） | 中 | 低 | P2 | `history.py`、`pipeline.py:1018-1030` |

### 3.8 Git / Docs-as-Code

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 拉取冲突 | 返回 `conflicts` 文件列表 | 无解决 UI；用户被丢到外部工具 | 冲突文件在改动面板标红，双栏"本地/远端"并提供"取本地/取远端/在编辑器手工"三键（Markdown 章节级冲突通常可解） | 高 | 中 | **P1** | `vcs_changes.py:1621-1775`、`main_window._on_git_pull_menu_clicked` |
| Changed Chapters | `changed_chapters()` 有 | 只用于评审稿；未与 Lint/构建联动 | "仅检查改动章节"快捷 Lint；构建日志列出本次变更章节 | 中 | 低 | P2 | `workspace.py:810-822`、`vcs_changes.py:1031` |
| 提交前门禁 | 无 | 可以提交 Lint error 内容 | 提交对话框显示 Lint 摘要，可配置阻断 | 中 | 低 | P2 | `git_commit_dialog.py` |
| Git 历史 | 无 | 看不到章节历史/blame | 章节右键"查看历史（git log -p -- file）"只读列表 | 中 | 低 | P2 | `tree_panel.py:545-613` |
| 大仓库性能 | `git status` 每次全仓 | 已有缓存；OK | — | — | — | — | `vcs_changes.py:717` |

### 3.9 评审闭环

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 评审稿导出 | DOCX 前后对照，含代码块盒子 | 未走 `build_docx` 主管线 → 两套 Markdown→Word 渲染器（`_render_markdown_lines` vs `process_markdown`）行为漂移 | 抽公共 `docx_blocks`（代码块/表格/行内），主构建先复用 | 高 | 中 | **P1** | `review_docx.py:1104-1348`；`build_docx.py:2049` |
| 评审单回流 | 表头驱动解析 9 列表 | 强绑定公司模板列名；非标表单需回退键 | 列映射可配置（`review_import.yml`），首次导入弹列映射确认 | 中 | 低 | P2 | `review_docx.py:79-92,1568-1666` |
| 意见 → 修复联动 | 跳转定位 | 意见状态与 Git 提交无关联 | 提交信息自动附 `Fixes R-012`，评审面板据此自动置"已确认" | 中 | 低 | P2 | `review_store.py:175`、`git_commit_dialog.py` |
| PDF/HTML 评审导出 | 服务层有 | 无入口 | 评审面板增加"导出 HTML 评审包"（零 Word 依赖，可发邮件） | 中 | 低 | P2 | `export/pdf_html.py:export_html` |
| 审批门禁 | `approval_gate` | 仅评审面板内部使用；正式出稿不查 | 发布前检查清单接入 `approval_gate`（可跳过并记 `history_note`） | 中 | 低 | P2 | `review_store.py:221`、`main_window.py:1681-1795` |

### 3.10 互转 / PDF 工具箱

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| 互转 | 20+ 方向，签名校验，Word 进程隔离 | 多数方向依赖 Word；`convert_dialog.py` 1,310 行 UI 逻辑重 | 维持现状；把"Markdown→Word"方向切换为项目构建内核（同一模板系统），减少两套排版 | 中 | 中 | P2 | `convert.py:744-772`、`markdown_word.py` |
| PDF 工具箱 | 15 项，CLI 同步 | `pdf_tools.py` 2,709 行 + `pdf_toolbox_dialog.py` 2,054 行；功能与核心定位关系弱 | **冻结功能面**，只修 bug；不再新增 PDF 项 | — | — | 暂不建议扩展 | — |

### 3.11 CLI / 配置 / 运行时 / 分发

| 功能 | 当前实现 | 当前问题 | 优化建议 | 价值 | 难度 | 优先级 | 代码依据 |
|---|---|---|---|---|---|---|---|
| `build` CLI | 仅 `--skip-word-refresh`，无 `--output json` | 与其他子命令不一致，CI 解析难 | 统一 `--output json`，输出 `PipelineResult` 事件 | 中 | 低 | **P1** | `cli.py:33-37` |
| 项目设置页 | 6 字段 | 无 headingStyles/bodyStyle/质量规则/变量/门禁 | 设置页分页：基本 / 样式映射 / 质量规则 / 变量 / 门禁 | 中 | 中 | **P1** | `settings_dialog.py` |
| 项目锁 | host+pid+容差 | 网络盘多机场景无租约到期 | 加 `heartbeat` 字段 + 过期时间；另一台机器可见"被 X 占用于 hh:mm" | 中 | 低 | P2 | `project_lock.py` |
| 长路径/中文路径 | 大量 realpath 归一化修复 | 已覆盖；缺少 `\\?\` 前缀处理的显式测试 | 增加 >260 字符路径测试 | 低 | 低 | P3 | `git log`: d561680, 72829ee |
| 日志敏感信息 | `RuntimeLog` 记录路径与错误 | 未见脱敏；路径含用户名 | 诊断包导出时对 `%USERPROFILE%` 做替换 | 低 | 低 | P3 | `runtime_log.py` |
| 安全 | `parse_xml_safe`(no entities, no huge_tree)、zip 炸弹比率、`_resolve_inside`、无 `shell=True` | 良好。外部命令：git/svn/mmdc/taskkill 均 list 参数 | 保持；为 `mmdc` 路径加白名单校验（只允许 `tools/mermaid-cli` 或 PATH） | 低 | 低 | P3 | `ooxml.py:73-91,250-275`、`mermaid.py:1005` |
| 测试 | 57 文件；GUI 离屏测试多 | coverage 快照过期；`run_tests.py` 顺序串行 384s | CI 每次产 coverage；按文件并行（已隔离进程，可 `-j`） | 中 | 低 | P2 | `run_tests.py`、`coverage.json` |
| 分发 | Inno + 便携 + 签名 + SBOM + 加固 | 成熟；`packaging/Output/` 中历史安装包与 `scripts/cert-out/*.pfx` 在工作区 | `.pfx`/密码文件必须移出仓库工作区（即使被 `export_public_source` 过滤） | 高（安全） | 低 | **P0** | `scripts/cert-out/pfx-password.txt`、`codesign.pfx` |

### 3.12 工程质量（横切）

| 问题 | 证据 | 建议 | 优先级 |
|---|---|---|---|
| 超大类 | `main_window.py` 3,588 行（菜单+任务+Git 弹层+会话+结果视图）；`workspace.py` 1,950 行；`pdf_tools.py` 2,709 行 | 按职责拆：`main_window/{menu,tasks,git_actions,session}.py`；Git 动作已在 `workspace` 有服务方法，UI 只保留信号连接 | P1 |
| 两套 Markdown→DOCX 渲染 | `build_docx.process_markdown` vs `review_docx._render_markdown_lines` | 抽 `docx_blocks`（见 3.5/3.9） | P1 |
| 内核仍在 `scripts/` | `build_docx.py`/`validate_docx.py`/`refresh_fields.py`/`docx_common.py` 通过 `adapters/kernel.py:ensure_kernel_importable` sys.path 注入 | 迁入 `doc_tool/kernel/`，`scripts/` 只留薄包装（打包 spec 也更简单） | P2 |
| 服务有、入口无 | `traceability`、`pdf_html`、`history`、`baselines` | 要么接 UI/CLI，要么删除，避免"僵尸能力" | P1 |
| 主线程同步 IO | `_on_reimport_source`、部分 Git 弹层分支操作已异步但 `reimport` 未 | 统一走 `TaskRunner` | P1 |
| 配置硬编码 | Lint 规则级别、`max_compression_ratio`、代码块颜色 | 前两者进 manifest/quality_rules；颜色随模板 | P3 |

---

## 4. 新增功能候选

| 新功能 | 解决的问题 | 使用场景 | 与现有功能关系 | 实现思路 | 价值 | 难度 | 建议 |
|---|---|---|---|---|---|---|---|
| **发布终审 `audit` 阶段** | 带病 Word 出厂 | 每次正式出稿 | 接在 `STAGE_VALIDATE_POST` 之后 | 见 3.5 | 高 | 低 | **建议做** |
| **图/表题注 + 交叉引用** | 国标编号硬要求 | 所有设计/需求文档 | 扩展 `ExpressionManager` | Quarto 语法 + Word SEQ/REF 域 | 高 | 中 | **建议做** |
| **Mermaid → Word 自动出图** | 图在 Word 里是源码 | 设计文档 | 复用 `mermaid.py` | 构建前渲染缓存 | 高 | 中 | **建议做** |
| **代码块容器** | 代码无格式 | 研发文档 | 复用 `review_docx` | 见 3.5 | 高 | 低 | **建议做** |
| **文档变量 `{{var}}`** | 系统名/版本散落 | 多客户版本文档 | manifest v2 | 构建前替换 + Lint | 中 | 低 | **建议做** |
| **Manifest 显式章节编排** | 无编号章节 / 重编号噪音 | 前言/附录 | `scan_entries` 回退 | `chapters:` 列表 | 高 | 中 | **建议做** |
| **横向节** | 宽表 | 接口表/矩阵 | 与导入分节标记配对 | `<!-- SECTION -->` | 高 | 高 | 建议做（第二阶段） |
| **Git 冲突解决视图** | 拉取冲突无处理 | 多人并行 | 改动面板 | 三键合并 | 高 | 中 | **建议做** |
| **Local History（多版本 .bak）** | 只能回一步 | 日常 | writer | `.state/local_history` | 中 | 低 | **建议做** |
| **企业术语库 terms.yml + QuickFix** | 术语不统一 | 评审前 | Lint `term_case` | 映射表 | 中 | 低 | **建议做** |
| **统一 `doc-tool check`** | CI 三条命令 | 流水线 | 包装 lint+validate | 退出码规范 | 高 | 低 | **建议做** |
| **章节 Git 历史/blame 视图** | 谁何时改了此节 | 追责/评审 | tree 右键 | 只读 `git log -p` | 中 | 低 | 可考虑 |
| **Include 公共章节** | 多文档重复 | 术语表/约定 | 构建+预览 | 注释标记 | 中 | 低 | 可考虑 |
| **HTML 评审包导出** | 无 Word 的评审人 | 外部评审 | `pdf_html.py` 已有 | 加按钮 | 中 | 低 | 可考虑 |
| **追踪矩阵 CLI/问题中心** | 需求覆盖 | 需求/设计配对项目 | `traceability.py` 已有 | 先 CLI | 中 | 低 | 可考虑 |
| **提交前 Lint 门禁** | 提交坏内容 | 日常 | commit dialog | 摘要+阻断开关 | 中 | 低 | 可考虑 |
| **无 Word 预发布 + 远程 promote** | Linux CI 无正式稿 | CI | 状态机新增 staged | 见 3.5 | 中 | 中 | 可考虑 |
| **AI：基于改动章节 diff 起草修订记录摘要** | 修订记录手写痛点 | 出稿前 | `revision_record` 弹窗 | 可插拔 provider（企业私有 LLM 端点），输出仅进弹窗，人工确认后写入 | 中 | 中 | 可考虑（需先做"非 AI 预填"版本，再评估） |
| **AI：术语/前后矛盾审查** | 审稿人力 | 评审前 | 问题中心新来源 | 同上，离线可关闭 | 中 | 高 | 暂不建议（先把确定性 Lint/术语库做扎实；企业网络限制大） |
| **AI 文档问答 / 根据代码生成设计文档 / 根据 Git Diff 自动更新文档** | — | — | 与"作者手工维护单一事实源"的设计取舍冲突 | — | 低 | 高 | 暂不建议 |
| 所见即所得表格编辑器 | 合并单元格编辑 | 复杂表 | 与"XML 黑盒表格"互补 | 大工程 | 中 | 高 | 暂不建议（先做影子表/HTML 表） |
| PlantUML / Draw.io / 数学公式 | 图与公式 | 少数文档 | Mermaid 已占位 | 需外部 Java/浏览器 | 低 | 高 | 暂不建议 |
| 审批流/电子签审/归档系统 | 企业流程 | 发布 | `approval_gate` 已有轻量签审 | 属 OA/DMS 领域 | 低 | 高 | 暂不建议（提供导出/回调即可） |
| Web 端实时协同 | — | — | 与 Git 异步协作定位冲突 | — | — | — | 暂不建议 |
| 全局搜索替换 / 双栏预览 / 图片粘贴 / Callout / 脚注 / 文档内链接 / 多窗口 | — | — | — | — | — | — | **已有功能，无需重复** |
| PDF 工具箱继续加项 | — | — | 已 15 项 | — | 低 | — | 暂不建议 |

---

## 5. TOP 20 演进建议

| # | 优先级 | 建议 | 主要模块 | 难度 |
|---|---|---|---|---|
| 1 | P0 | 围栏代码块进正式 Word（复用 `_create_code_block_box`，抽 `docx_blocks`） | `scripts/build_docx.py`、`review_docx.py` | 低 |
| 2 | P0 | Mermaid 构建期自动渲染为 PNG 并内嵌（hash 缓存，主线程栅格化） | `pipeline.py`、`mermaid.py` | 中 |
| 3 | P0 | 发布终审 `STAGE_AUDIT`：域错误文本 / TODO 残留 / 表格越界 / 空段 | `pipeline.py`、`validate_docx.py` | 低 |
| 4 | P0 | 图/表题注 + `@fig-`/`@tbl-` 交叉引用（SEQ/REF 域） | `build_docx.py:ExpressionManager` | 中 |
| 5 | P0 | 预览引擎一致性：冻结包无 WebEngine → 以内置渲染为唯一路径并补图种；或明确打包 WebEngine | `editor_panel.py`、`doc_tool.spec` | 中 |
| 6 | P0 | 把 `scripts/cert-out/*.pfx` 与密码文件移出仓库工作区 | `scripts/cert-out` | 低 |
| 7 | P1 | 导入保留行内格式（粗/斜/超链接/书签）与列表层级 `ilvl` | `importer.py` | 中 |
| 8 | P1 | 复杂表格影子 Markdown（可搜可审）→ 后续 HTML 表子集 | `importer.py`、`search.py` | 低→高 |
| 9 | P1 | `doc-tool check` 统一门禁 + `build --output json` + 构建前置 Lint 阶段 | `cli.py`、`pipeline.py` | 低 |
| 10 | P1 | Manifest v2：`chapters:` 显式编排 + `variables:` 文档变量 | `manifest.py`、`docx_common.py`、`build_docx.py` | 中 |
| 11 | P1 | Git 拉取冲突解决视图（本地/远端/手工） | `changes_panel.py`、`vcs_changes.py` | 中 |
| 12 | P1 | 重新导入改为后台任务 + 变更预览 + 逐章节选择合入 | `main_window.py`、`reimport.py` | 中 |
| 13 | P1 | Local History 多版本快照 + 删除进回收站 | `writer.py`、`workspace.py` | 低 |
| 14 | P1 | 项目设置页扩展（样式映射 / 质量规则开关 / 变量 / 门禁） | `settings_dialog.py`、`quality_rules.py` | 中 |
| 15 | P1 | 企业术语库 `terms.yml` + Lint QuickFix | `spellcheck.py`、`lint.py` | 低 |
| 16 | P1 | 修订记录弹窗预填改动小节 + git log 主题，一键追加行 | `revision_record.py`、`changes_panel.py` | 低 |
| 17 | P1 | 横向节 `<!-- SECTION: landscape -->`（导入/构建/校验三端） | `importer.py`、`build_docx.py`、`validate_docx.py` | 高 |
| 18 | P2 | 把已实现服务接入口：追踪矩阵 CLI、构建历史列表、基线切换、HTML 评审包 | `traceability.py`、`history.py`、`baselines.py`、`pdf_html.py` | 低 |
| 19 | P2 | `main_window.py` 拆分 + 内核迁入 `doc_tool/kernel/` + CI 恢复 coverage 产出 | 工程 | 中 |
| 20 | P3 | 无 Word 预发布制品 + `refresh --promote`；AI 修订摘要 provider（人工确认制） | `pipeline.py`、`output_state.py` | 中 |

排序依据：用户价值 × 使用频率（每次出稿都撞上的 1-4 最高）× 与核心定位匹配度（出稿表达 > 协作 > 工具箱）× 成本（1、3、6、9、13、15、16 均为低成本）× 风险（5、6 属隐性缺陷/安全）。

---

## 6. Roadmap

### 第一阶段（v2.6，1~2 个月）：小改动、高收益，基于现有架构

- TOP 1 代码块、TOP 3 终审阶段、TOP 6 证书出仓、TOP 9 `check`/json/前置 Lint、TOP 13 Local History + 回收站、TOP 15 术语库、TOP 16 修订记录预填。
- TOP 5 先做决策（建议：删除 WebEngine 路径），并在 `test_frozen_smoke.py` 加断言。
- TOP 18 中的"构建历史列表 / 追踪矩阵 CLI"顺手接入。
- 归档 `openspec/changes/revision-review-export`（已被现实现替代），补齐其余 change 的人工验收项。

### 第二阶段（v2.7~v2.8，2~4 个月）：核心能力增强，需要一定架构调整

- 抽 `docx_blocks` 公共渲染层 → TOP 2 Mermaid 出稿、TOP 4 题注与交叉引用、TOP 17 横向节。
- TOP 10 Manifest v2（chapters/variables）+ TOP 14 设置页。
- TOP 7/8 导入保真升级（行内格式、列表层级、复杂表影子/HTML 表）。
- TOP 11 冲突解决视图、TOP 12 重导入异步预览。
- TOP 19 拆 `main_window`、内核迁入包内、coverage 回 CI。

### 第三阶段（v3.0+）：产品级演进

- 无 Word 预发布 + 远程 promote（让 Linux CI 参与正式交付链）。
- Include/共享章节、章节 Git 历史视图、提交前门禁、评审意见 ↔ 提交联动。
- AI 仅以"可插拔 provider + 人工确认"的形式进入修订摘要与术语审查；不做问答/自动改写/自动更新文档。
- 明确不做：Web 实时协同、自研排版引擎、PDF 工具箱扩张、所见即所得复杂表编辑器（除非影子表方案被证明不够）。

---

## 附：验证方法与关键证据索引

- 静态验证：`grep` 确认 `build_docx.py`/`pipeline.py`/`kernel.py` 无 `mermaid`、无 `caption/SEQ`、无 `landscape`；`process_markdown`（L2049-2249）无 fence 分支；`split_table_row`（`markdown_structure.py:81-118`）已还原 `<br>`。
- 入口验证：`traceability.py`、`export/pdf_html.py` 在 `doc_tool/ui`、`cli.py`、`cli_commands.py` 中 0 引用；`history.py` 仅 `pipeline.py:1018` 归档调用；`quality_rules` 两处 `writable=False`。
- 打包验证：`packaging/doc_tool.spec:142-144` excludes `QtWebEngine*`；`editor_panel.py:48-52` 依 ImportError 降级。
- UI 验证：`main_window._build_menu`（L321-512）与 `open_command_palette`（L601-874）动作清单；`workspace._populate_panels`（L377-509）9 个面板。
- 测试验证：`run_tests.py` 44 套件（`test-results.xml`：44 tests, 0 failures, 384s）；`coverage.json` 时间戳 2026-08-21，总 83.8%。
- 安全验证：`ooxml.py` `resolve_entities=False`/`huge_tree=False`/压缩比 2000；全仓无 `shell=True`；`writer._resolve_inside` 防目录穿越。
