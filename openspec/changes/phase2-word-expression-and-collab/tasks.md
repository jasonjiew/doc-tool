> 第二阶段（v2.7 → v2.8）实施清单。依赖第一阶段 `docx_blocks`、`STAGE_AUDIT`、`gates`。
> 建议拆两个小版本：v2.7 = 第 1~5 节（出稿表达 + Manifest v2）；v2.8 = 第 6~10 节（导入保真 + 协作 + 重构）。
> 来源：`analysis/feature-audit.md` TOP 2/4/7/8/10/11/12/14/17/19。

## 1. 管线预处理阶段与 Mermaid 出图（TOP 2）

- [ ] 1.1 `pipeline.py` 新增 `STAGE_PREPARE`，`PreparedSource` 数据结构，`kernel.config_from_project(source_override=)`
- [ ] 1.2 `application/prepare.py`：变量替换（占位，D5 完成后启用）、Mermaid 块提取与替换、进度/取消
- [ ] 1.3 `mermaid.py`：`render_to_asset(block, assets_dir) -> Path` 含 sha1 缓存；主线程栅格化桥接；CLI 离屏 QGuiApplication
- [ ] 1.4 内置渲染新增 `classDiagram`、`stateDiagram-v2`、`gantt` 子集（含语法校验规则同步）
- [ ] 1.5 `manifest.gates.mermaid`（默认 warn）；失败保留代码块 + warning 事件
- [ ] 1.6 `image_assets_panel` 排除 `_generated/`；`.gitattributes` 建议 `*.png binary`
- [ ] 1.7 测试：`test_project_build`（三图种、缓存命中、mmdc 缺失回退、失败降级）、`test_lock_log_cancel`（预处理阶段取消）

## 2. 题注与交叉引用（TOP 4）

- [ ] 2.1 `domain/markdown_structure.py` 新增题注/引用语法解析（`{#fig-id}`、`Table: … {#tbl-id}`、`@fig-id`）
- [ ] 2.2 `prepare.py` 预扫描全项目 id → 编号表（章节号来源于 `scan_entries`）
- [ ] 2.3 `kernel/build_docx.py`：`ExpressionManager.register_caption()/append_ref()`；图后/表前题注段落、`SEQ`/`REF` 域、书签；`Caption` 样式缺失时创建
- [ ] 2.4 `preview.py` 渲染编号与引用链接
- [ ] 2.5 `lint` 新增 `dangling_xref`、`duplicate_caption_id`；`audit` 新增 `dangling_xref`
- [ ] 2.6 `validate_docx` 事件生成识别题注段落
- [ ] 2.7 测试：编号规则（chapter/global）、跨章引用、重复 id、刷新前缓存值、往返门禁不受影响

## 3. 横向节与表格自适应（TOP 17）

- [ ] 3.1 `kernel/build_docx.py`：`<!-- SECTION: landscape/end -->` 与 `<!-- PAGEBREAK -->` 解析；段落级 `sectPr` 注入（拷贝模板、旋转页边距、沿用页眉页脚关系）
- [ ] 3.2 `make_table_from_md` 累计列宽超版心按比例缩放 + warning；横向节内取横向版心
- [ ] 3.3 `adapters/importer.py`：源文档分节/横向/分页符落为标记
- [ ] 3.4 `kernel/validate_docx.py`：节序列比对；`word_semantic_preservation_errors` 放行多节
- [ ] 3.5 测试：单横向块、连续两块、未闭合到章末、页眉保持、`validate` 通过；导入→构建往返保留横向

## 4. Manifest v2：章节编排与变量（TOP 10）

- [ ] 4.1 `domain/manifest.py`：`schemaVersion 2`、`chapters`、`variables`、`captions`；校验规则（chapters 路径存在、变量名合法）
- [ ] 4.2 `settings_migration.migrate_v1_to_v2()`；打开 v1 项目的升级提示与只读回退
- [ ] 4.3 `docx_common.scan_entries` 显式顺序分支；`tree.py`/`ContentIndex`/快速打开排序同步
- [ ] 4.4 `prepare.py` 启用变量替换（跳过围栏块）；`lint.undefined_variable`、`unlisted_chapter`
- [ ] 4.5 `preview.py` 变量替换
- [ ] 4.6 `resources/default_project.yml` 更新为 v2 示例；`docs/migration-guide.md` 补章节
- [ ] 4.7 测试：`test_project_model`（v2 校验/迁移/回退）、`test_docx_common`（显式顺序 + 混合目录）、`test_authoring_services`（变量 Lint）

## 5. 项目设置页扩展（TOP 14）

- [ ] 5.1 `ui/settings_dialog.py` 改 Tab：基本 / 样式映射 / 质量规则 / 变量 / 门禁
- [ ] 5.2 `QualityRulesConfig` 可写路径与 UI 编辑表格
- [ ] 5.3 样式映射页复用向导的模板样式枚举
- [ ] 5.4 测试：`test_gui_services` 各页保存/校验失败/只读禁用

## 6. 导入保真升级（TOP 7/8）

- [ ] 6.1 `importer._para_markdown`：粗/斜/超链接/内部锚点/用户书签；空白外移；导入选项"保留行内格式"（默认开）
- [ ] 6.2 列表层级 `ilvl` → 缩进；`roundtrip._event_text` 比较层级
- [ ] 6.3 复杂表影子 Markdown（`TABLE-SHADOW` 区间）；构建跳过；`ContentIndex` 索引；编辑器只读灰底渲染
- [ ] 6.4 `fidelity` 报告新增"实际保留"列并落 `.state/import_fidelity.json`；问题中心展示
- [ ] 6.5 测试：`test_import_project`/`test_fidelity`/`test_roundtrip` 覆盖以上；用 3 份真实历史文档做导入回归对比

## 7. Git 冲突解决视图（TOP 11）

- [ ] 7.1 `vcs_changes.py`：`conflict_sides(path) -> (ours, theirs, base)`、`resolve_conflict(path, choice)`、SVN `resolve`
- [ ] 7.2 `changes_panel.py` 冲突模式 UI（置顶红项、三栏、三键）
- [ ] 7.3 全部解决后引导合并提交（预填消息）
- [ ] 7.4 测试：`test_vcs_changes` 真实 git 冲突夹具（两工作副本）、二进制文件分支、SVN 注入序列

## 8. 重新导入异步化与预览（TOP 12）

- [ ] 8.1 `reimport.py` 拆 `plan()`/`apply(selected)`；冲突生成 `.theirs.md`
- [ ] 8.2 `ui/reimport_preview_dialog.py`：三态列表、勾选、双击 diff
- [ ] 8.3 `main_window` 改走 `TaskRunner`；`scan_entries` 忽略 `.theirs.md`
- [ ] 8.4 测试：`test_gui_services`（离屏对话框）、`test_import_project`（plan/apply 幂等、只勾选部分）

## 9. 工程重构（TOP 19）

- [ ] 9.1 先补 `test_gui_services` 菜单/快捷键/任务流回归用例
- [ ] 9.2 拆分 `main_window.py` → `ui/main_window/{window,menu,tasks,git_actions,session,results}.py`
- [ ] 9.3 内核迁入 `doc_tool/kernel/`；`scripts/*.py` 薄包装；删除 sys.path 注入；spec/hiddenimports 更新
- [ ] 9.4 `run_tests.py -j`；CI `--coverage-min 80` 并上传 `coverage.json`
- [ ] 9.5 冻结冒烟测试（`test_frozen_smoke`、`test_installer_smoke.ps1`）通过

## 10. 回归与发布

- [ ] 10.1 v2.7：第 1~5 节完成后全量测试 + 真实设计文档出稿人工比对（图/题注/横向/变量）
- [ ] 10.2 v2.8：第 6~9 节完成后全量测试 + 导入回归 + 冲突/重导入人工验收
- [ ] 10.3 design.md 验收标准逐条勾选；`docs/使用说明.md` 补题注语法、横向节、变量、chapters
- [ ] 10.4 `openspec/specs/` 同步；归档本 change
