# product-v38-authoring-and-exchange-ux 实施任务

5 批/20 项，按 A→B→C→D→E 推进。保留既有实现和本次复核修正；旧实机缺项不阻断独立编码。勾选需要实际入口/行为证据，计划校验不算业务验收。

## 1. 38-A 表格日常编辑

- [x] 1.1 实现 TSV/Markdown 粘贴预览的上一页/下一页/总行数，翻页与首行表头切换不修改完整模型。（证据：scripts/tests/test_v38_table_paste_paging.py；本轮修复=table_grid.preview_page + 预览对话框翻页按钮与页码，翻页/表头切换不改完整数据）
- [x] 1.2 为网格增加多行文本编辑和列宽/行高交互，沿用 <br> 表达，验证真实输入、序列化和一次撤销。（证据：test_v34_table_authoring.py 的网格编辑/多行/一次撤销用例）
- [x] 1.3 完善未应用表格草稿继续、源变化详情、复制原文/Markdown 和显式目标重定位，保留源文件身份和锚点检查。（证据：test_v34_table_authoring.py::set_source_changed/relocate 用例、test_v34_v35_entries.py）
- [x] 1.4 验证 1000×20 的末页查看→完整插入→HTML/诊断 DOCX，尾空行/空列/前导零/公式文本不丢，记录界面响应。（证据：test_v38_table_paste_paging.py::test_dialog_pages_and_keeps_complete_model；1000×20 翻到第 50 页后完整插入，前导零/公式/尾空列均保留）

## 2. 38-B 规范资源与表单

- [x] 2.1 从当前项目建草稿前提供底模/章节/变量/术语/规则选择，区分空骨架与正文副本，不默认选全部业务正文。（证据：scripts/tests/test_v38_pack_skeleton_mode.py；本轮修复=draft_from_project 默认只写标题层级骨架，正文副本必须显式 include_body，草稿记录 skeletonMode 并在对话框询问）
- [x] 2.2 按实际消费者字段实现术语及支持规则表单（严重级别/启用/受支持参数），验证保存后原消费者读回。（证据：test_v35_standard_pack.py、test_standard_pack_v28.py 的 terms/rules 读回断言）
- [x] 2.3 提供高级 JSON 与结构表单切换、未知键合并及未完成输入恢复；错误就地定位，允许保存不完整草稿。（证据：test_v35_standard_pack.py::test_incomplete_draft_can_be_saved_and_reopened、::test_unknown_declarative_content_is_preserved）
- [x] 2.4 完善变量行、资源路径、同名骨架选择和草稿重开体验，验证仅写制作目录，原项目/安装包保持。（证据：test_v35_standard_pack.py::test_draft_from_project_copies_resources_without_touching_source、test_v38_pack_skeleton_mode.py::test_source_project_is_not_modified）

## 3. 38-C 导入与复导入

- [x] 3.1 整合来源选择/章节预览/保留对象/缺图摘要，默认少步骤导入，复杂项有原件定位。（证据：test_core_entries_ui.py、test_core_intake_presets_gui.py、test_main_a_import_quality.py::test_complex_objects_keep_original_and_exact_location）
- [x] 3.2 批量来源按文件显示进度和结果，单文件失败后其余可用输入继续，集中汇总问题和可重试来源。（证据：test_core_scope_presets_batch.py、test_main_a_import_quality.py::test_markdown_batch_partial_success_continues_and_reports）
- [x] 3.3 复导入展示来源变化、缓冲/磁盘变化和冲突，支持先应用无冲突项及保留当前/另存副本。（证据：test_reimport_plan_v28.py 的 auto_applicable/choices 用例、test_main_a_import_quality.py::test_reimport_applies_non_conflicting_and_keeps_local_edit）
- [x] 3.4 从真实入口验证导入→编辑→复导入→继续编辑，选定范围应用，不隐式保存无关章节或覆盖脏缓冲。（证据：test_reimport_preview_v28.py、test_main_f_flow.py、test_v38_table_paste_paging.py 的范围应用断言）

## 4. 38-D 出稿与规范试用

- [x] 4.1 优化出稿设置的来源/范围/格式/目的地/版式顺序和实际摘要，保留上次有效选择，失效范围回到可见设置。（证据：test_ui2_export_settings.py、test_ui_polish_quick_export.py）
- [x] 4.2 按格式展示可读/待刷新/正式及失败原因，打开、补原轮、最新新轮和换目录均验证 captureId/范围/实际内容。（证据：test_main_e_export_rounds.py、test_export_round_recovery.py、test_core_export_snapshot.py）
- [x] 4.3 为规范样例提供轮次历史、过期原因、旧成果定位和补原样例 Word/生成最新样例；沿用独立目录与原结果索引。（证据：test_v35_standard_pack.py 的样例轮次用例、test_v34_v35_entries.py）
- [x] 4.4 对样例/大文件导入和有实测耗时的冻结/ZIP 动作复用后台机制，界面响应、取消/失败保留旧草稿和成果。（证据：test_v36_large_document.py 的取消/部分结果用例、test_v35_standard_pack.py 的冻结/ZIP 用例）

## 5. 38-E 完整消费闭环

- [x] 5.1 运行制作→保存重开→样例→冻结 ZIP→同事新建→编辑→出稿闭环，按实际文件和资源读回验证。（证据：test_v35_standard_pack.py::test_frozen_pack_is_consumable_and_resources_read_back、test_v34_v35_entries.py）
- [x] 5.2 覆盖坏可选配置、缺底模/图、空值、未知字段、同版本不同摘要和无 Word，验证可用兜底与原件不变。（证据：test_main_a_import_quality.py、test_main_e_export_rounds.py、test_v35_standard_pack.py、test_main_c_assets_and_refs.py）
- [ ] 5.3 执行可用的真实 Excel/Word 剪贴板、IME、企业底模试点；未支持对象和缺环境明确单列。（本机无 Excel 剪贴板/真实 IME/企业底模条件，保留待验收；粘贴服务已用真实 TSV 文本验证，见 test_v38_table_paste_paging.py）
- [x] 5.4 运行相关回归/OpenSpec strict，更新独立台账和下一任务；本包已有实现按差额补齐，继续 V3.9。（本次更新 tasks 与 docs/product-v37-v39-execution.md）
