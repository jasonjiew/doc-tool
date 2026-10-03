# product-main-workflow-optimization 实施任务

MAIN-A～F，6 批/24 项。先核对已有能力与差额；复用原服务，不重做 CORE 和交互包。正常先 MAIN 后 V3.7～V3.9；已执行中的批次完成后插入 MAIN。原任务编号、已完成功能与实机待验收保持。

## 1. MAIN-A 导入质量与资源完整性

- [x] 1.1 建立 Word/Markdown 混合内容样例及当前基准，核对标题、列表、表格、图片、链接/代码、保留对象的真实导入路径，记录已有能力与实际差额。（证据：scripts/tests/test_main_a_import_quality.py::test_mixed_word_import_reads_back_structure；真实差额=段落代码缩进被 `_para_text().strip()` 抹掉，已修）
- [x] 1.2 补导入解析/大纲/应用的内容对照和来源定位；默认有标题/无标题均能开始编辑，缺图或复杂对象不丢原件、不阻塞合法正文。（证据：同上 ::test_complex_objects_keep_original_and_exact_location、::test_no_heading_document_imports_without_template_or_numbering；新增 target_path+target_line 精确定位，拆分后按锚点回查真实章节文件）
- [x] 1.3 修正多来源资源身份与引用映射差额，验证 a/logo.png 与 b/logo.png、两来源 image.png、同内容复用及项目副本离开来源目录后可读。（证据：scripts/tests/test_project_from_markdown_v28.py 六个 MAIN-A 1.3 用例；资源身份改按相对路径判定，冲突改名并只改写引用它的章节；assetRoot 统一为 assets/<类型>）
- [x] 1.4 从既有入口验证批量部分成功与复导入局部应用，失败只重试对应输入，活缓冲冲突保留，无关章不隐式保存；38-C 后续复用同一接口。（证据：test_main_a_import_quality.py::test_markdown_batch_partial_success_continues_and_reports、::test_reimport_applies_non_conflicting_and_keeps_local_edit）

## 2. MAIN-B 编辑效率与章节操作

- [x] 2.1 查找替换工作集接入当前缓冲及当前章/选章/整份范围，预览前后差异，选择应用且支持实际修改范围的撤销/恢复。（证据：scripts/tests/test_main_b_replace_scope.py；ReplaceService 新增 scope_paths/text_overrides，替换面板新增范围下拉与活缓冲写回，当前章替换落在编辑器撤销栈）
- [x] 2.2 补常用标题/列表及显式粘贴文本整理的差额，保留代码围栏、缩进、空值与文本含义，一次动作可撤销，普通粘贴保持可预测。（证据：同文件 FormatToolCodeFenceTests；标题/列表/引用前缀跳过围栏代码块与空行）
- [x] 2.3 跑通章节新建/复制/重命名/排序与确定性引用联动；复制新身份、移动保留身份，歧义引用列位置，当前未保存章不被覆盖。（证据：scripts/tests/test_main_b_chapter_copy.py；新增 copy_chapter/copy_chapter_markdown 生成新 DOC-ITEM ID，章节树新增「复制章节…」入口）
- [x] 2.4 验证批量预览后正文再次变化、保存失败和草稿重开，跳过冲突项继续其余，复用写入清单/本地恢复且导出仍能使用活缓冲。（证据：test_main_b_replace_scope.py::test_stale_line_skips_that_file_and_continues_others、BufferExportTests；草稿/保存失败见 test_safety_recovery.py）

## 3. MAIN-C 图片、图表与引用修复

- [x] 3.1 统一图片粘贴/拖入/选文件入口到既有资源写入，相对引用与同名目标可用，插入/撤销及导出资源按实际文件验证。（证据：scripts/tests/test_main_c_assets_and_refs.py::ImageEntryPointTests；三条入口共用 import_image→import_image_data，一次撤销回退引用且资源文件保留）
- [x] 3.2 缺图问题接通定位→选择替代→应用选定引用→重检，显示实际引用范围，默认不批量替换未选引用或删除未引用文件。（证据：::MissingImageRepairTests + scripts/tests/test_asset_batch.py；未引用资源只在面板报告、文件保留）
- [x] 3.3 完善章节链接/题注/引用的有效定位与确定性修复，验证同名标题、代码中的类链接文本、跨章移动及项目副本。（证据：::ReferenceFixDeterminismTests；改名只联动真实解析到该章的引用，同名歧义引用保持原样）
- [x] 3.4 对 Mermaid/宽图验证当前源码缓存、失败源码兜底、预览及 HTML/DOCX 内容一致；旧缓存不冒充新图，其他章节继续。（证据：::MermaidSourceCacheTests；渲染缓存键含当前源码）

## 4. MAIN-D 检查、修复与预览

- [x] 4.1 当前章/选章/整份检查接入真实活内容和范围，术语/编号/链接/图片/结构结果能定位，不重复报告已在缓冲修复的问题。（证据：scripts/tests/test_main_d_lint_scope.py::LintScopeTests；检查面板新增范围下拉与 scoped linter，缓冲修好的问题不再按旧磁盘报告）
- [x] 4.2 支持确定性 quick fix 的差异预览、所选应用及撤销；内容变化后刷新建议，不自动改变业务条目身份、关系复核或正式状态。（证据：同文件 ::test_quick_fix_shows_diff_and_can_be_undone、::test_quick_fix_writes_to_live_buffer_without_saving；应用前差异确认，新增「撤销上次修复」）
- [x] 4.3 补预览/检查的去抖、代次和生命周期差额，验证快速输入→切章→返回及关闭视图，最新正文正确呈现且旧事件不污染新章。（证据：同文件 ::PreviewLifecycleTests；EditorPanel 新增 stop_pending_work/closeEvent）
- [x] 4.4 复用增量索引测量常用检查/预览热路径，至少5次采样，对照完整扫描和缓存损坏兜底；性能改善以真实台账说明，不减少检查内容。（证据：analysis/main-d/measure-check-hotpath.json，120 章 ×5 次采样；单章变更 parseCount=1/reuseCount=119；缓存损坏重建结果与完整扫描一致；热路径端到端仅约 1.16×，如实记录）

## 5. MAIN-E Word 排版与出稿质量

- [x] 5.1 用当前底模/样式/版式服务核对实际映射和正文边界，补有效默认及回退差额，保留封面/页眉/页脚和复杂对象支持契约。（证据：scripts/tests/test_main_e_output_quality.py 真实构建后读回 OOXML；缺底模仍可用通用底模回退，封面/页眉/页脚来自底模未被改写）
- [x] 5.2 优化支持的标题/列表、普通表格宽度/长表表头、多行空值、宽图、代码/链接，保留前导零与文本；通过实际 OOXML/HTML 和内容对照验证。（证据：同文件 5 个用例；修复=Markdown 普通表格首行补 tblHeader，长表跨页自动重复表头；宽图收敛在页面宽度内；前导零 007、空值、<br> 多行、代码缩进、外链超链接均有断言）
- [x] 5.3 验证整份当前内容的快速默认、显式选章及同轮 DOCX/PDF/HTML/源码资源一致性；旧轮补齐保持原捕获，CLI 文件输出含义不变。（证据：scripts/tests/test_main_e_export_rounds.py、test_main_f_flow.py::WordFlowTests；同轮 captureId 一致，选章范围只含所选章；修复=整份快照补齐只有 _index.md 的父章节正文，此前这类章节在出稿中整章丢失）
- [x] 5.4 补目标占用/不可写、单格式失败/无 Word 的真实续行差额，尝试有效副本目录或文件，保留已有可读成果并显示真实状态，不伪报正式成功。（证据：test_main_e_export_rounds.py::test_occupied_target_gets_a_fresh_copy_path、::test_unwritable_destination_falls_back_or_reports、::test_single_format_failure_keeps_other_results；修复=单格式实现异常不再中断整轮，转为该格式失败结果）

## 6. MAIN-F 主流程验收与交接

- [x] 6.1 从真实入口执行 Word导入→未保存编辑→章节调整/缺图修复→检查→整份/选章出稿闭环，核对实际内容、范围、资源与原件未改写。（证据：scripts/tests/test_main_f_flow.py::WordFlowTests::test_full_word_loop、::test_missing_image_repair_then_export）
- [x] 6.2 执行 Markdown多来源→同名资源→范围替换→复导入局部冲突→副本离线出稿闭环，运行直接相关回归并记录当前默认清单实际覆盖。（证据：::MarkdownMultiSourceFlowTests；同名资源不串来源、范围替换只改所选章、离线副本出稿两种格式可用；复导入局部冲突见 MAIN-A 1.4 用例）
- [ ] 6.3 执行可用真实企业底模/Word/IME/Excel剪贴板试点；缺环境保持本项未验收，自动内容/结构检查与真实视觉分列。（本机无真实企业底模/Word/IME/Excel 剪贴板条件，保留待验收；复验步骤见 docs/product-v37-v39-execution.md 第 6 节）
- [x] 6.4 更新 MAIN 独立记录、功能清单/路线图/持续指令和 OpenSpec strict，说明实现差额、未验收与下一直接任务；接续 V3.7～V3.9。（本次更新 tasks、docs/product-v37-v39-execution.md 与功能清单）
