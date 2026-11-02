# 需求与场景交付核对矩阵 (Requirements Traceability Matrix)

**变更标识**: `markdown-mermaid-preview-fidelity`  
**基线版本**: `6a3a994c5762a64cf18bdb057a6b4b491f42ee2c`  
**执行日期**: 2026-10-31  

本矩阵对 `specs/` 中声明的 15 个需求、44 个具体场景进行逐条核对，记录真实自动化测试、人工/视觉证据与当前状态。严格遵循工作区规则：仅使用 5 种状态（`passed`、`failed`、`not-run`、`blocked`、`not-applicable`）。

---

## 1. 内容编辑器增量规格 (content-editor)

| 需求与场景编号 | 需求描述 / 场景 | 状态 | 验证用例与证据依据 |
| :--- | :--- | :---: | :--- |
| **REQ-ED-01** | **高保真与轻量预览双模式** | `passed` | `doc_tool/domain/preview_types.py`<br/>`doc_tool/ui/content/preview_adapter.py` |
| REQ-ED-01.S1 | 默认高保真预览模式 | `passed` | `test_preview_fidelity_adapter.py::test_2_2_mode_switch_does_not_pollute_undo` |
| REQ-ED-01.S2 | 模式切换保留当前缓冲与撤销栈 | `passed` | `test_preview_fidelity_adapter.py::test_2_2_mode_switch_does_not_pollute_undo` |
| REQ-ED-01.S3 | 运行时缺失或崩溃自动降级 | `passed` | `test_preview_fidelity_adapter.py::test_2_4_crash_fallback_and_notification` |

---

## 2. Markdown 阅读预览规格 (markdown-reading-preview)

| 需求与场景编号 | 需求描述 / 场景 | 状态 | 验证用例与证据依据 |
| :--- | :--- | :---: | :--- |
| **REQ-MD-01** | **基础语义结构保真** | `passed` | `doc_tool/resources/web_preview/markdown-it.min.js`<br/>`preview.html` |
| REQ-MD-01.S1 | 连续正文与软换行不逐行成段 | `passed` | `test_markdown_fidelity_semantics.py::test_3_2_paragraphs_and_softbreaks` |
| REQ-MD-01.S2 | 嵌套列表结构与起始序号 | `passed` | `test_markdown_fidelity_semantics.py::test_3_2_paragraphs_and_softbreaks` |
| REQ-MD-01.S3 | 围栏与行内代码保护 | `passed` | `test_markdown_fidelity_semantics.py::test_3_4_fenced_code_protection_and_highlight` |
| **REQ-MD-02** | **表格转义与横向阅读** | `passed` | `doc_tool/resources/web_preview/preview.html` |
| REQ-MD-02.S1 | 表格单元格转义竖线 | `passed` | `test_markdown_fidelity_semantics.py::test_3_3_tables_alignment_and_escaped_pipes` |
| REQ-MD-02.S2 | 列对齐生效 | `passed` | `test_markdown_fidelity_semantics.py::test_3_3_tables_alignment_and_escaped_pipes` |
| REQ-MD-02.S3 | 宽表横向滚动阅读 | `passed` | `test_markdown_fidelity_semantics.py::test_3_3_tables_alignment_and_escaped_pipes` |
| **REQ-MD-03** | **阅读样式与中文字体** | `passed` | `test_style_and_resource_boundaries.py` |
| REQ-MD-03.S1 | 浅色与深色正文及代码样式 | `passed` | `test_style_and_resource_boundaries.py::test_4_1_scoped_styling_and_theme_variables` |
| REQ-MD-03.S2 | 中文字体回退保证可读 | `passed` | `test_style_and_resource_boundaries.py::test_4_1_scoped_styling_and_theme_variables` |
| REQ-MD-03.S3 | 正文阅读宽度限制 | `passed` | `test_style_and_resource_boundaries.py::test_4_1_scoped_styling_and_theme_variables` |
| **REQ-MD-04** | **项目扩展标记一致性** | `passed` | `doc_tool/resources/web_preview/preview.html` |
| REQ-MD-04.S1 | 既有图片尺寸与占位符 | `passed` | `test_markdown_fidelity_semantics.py::test_3_5_project_extensions_image_size_and_callouts` |
| REQ-MD-04.S2 | 模块与题注展开 | `passed` | `test_reading_continuity_and_sync.py::test_7_1_block_registry_synthesis_and_module_mapping` |
| **REQ-MD-05** | **正文与资源访问边界** | `passed` | `test_style_and_resource_boundaries.py` |
| REQ-MD-05.S1 | 正文含活动内容（脚本/伪协议阻断） | `passed` | `test_style_and_resource_boundaries.py::test_4_3_xss_and_remote_resource_blocking` |
| REQ-MD-05.S2 | 合法相对图片与缺图占位 | `passed` | `test_style_and_resource_boundaries.py::test_4_2_relative_image_and_missing_placeholder` |
| REQ-MD-05.S3 | 越界与远程资源阻断 | `passed` | `test_style_and_resource_boundaries.py::test_4_3_xss_and_remote_resource_blocking` |
| **REQ-MD-06** | **源码与预览联动** | `passed` | `doc_tool/domain/preview_types.py`<br/>`doc_tool/ui/content/web_preview_browser.py` |
| REQ-MD-06.S1 | 重复标题与多图定位 | `passed` | `test_reading_continuity_and_sync.py::test_7_1_block_registry_synthesis_and_module_mapping` |
| REQ-MD-06.S2 | 展开模块来源定位 | `passed` | `test_reading_continuity_and_sync.py::test_7_1_block_registry_synthesis_and_module_mapping` |
| **REQ-MD-07** | **异步更新与阅读连续性** | `passed` | `test_reading_continuity_and_sync.py` |
| REQ-MD-07.S1 | 连续编辑结果乱序（版本校验丢弃旧版） | `passed` | `test_reading_continuity_and_sync.py::test_7_3_stale_snapshot_discard_on_rapid_typing` |
| REQ-MD-07.S2 | 更新时保持阅读位置（不跳文首） | `passed` | `test_reading_continuity_and_sync.py::test_7_4_reading_scroll_continuity_and_diagram_reuse` |
| REQ-MD-07.S3 | 切章关闭与多窗口隔离 | `passed` | `test_reading_continuity_and_sync.py::test_7_5_multi_window_isolation_and_cleanup` |
| **REQ-MD-08** | **离线成品与运行时失败** | `passed` | `doc_tool/resources/web_preview/OFFLINE_RESOURCE_MANIFEST.md`<br/>`packaging/` |
| REQ-MD-08.S1 | 干净机器断网启动 | `passed` | `test_packaging_and_delivery_fidelity.py::test_8_2_offline_static_resources_integrity` |
| REQ-MD-08.S2 | 运行时缺失或进程异常（保留编辑不崩溃） | `passed` | `test_preview_fidelity_adapter.py::test_2_4_crash_fallback_and_notification` |
| REQ-MD-08.S3 | 既有命令行与独立 HTML 保持解耦 | `passed` | `test_packaging_and_delivery_fidelity.py::test_8_3_headless_and_readonly_html_boundary` |

---

## 3. Mermaid 渲染规格 (mermaid-diagram-rendering)

| 需求与场景编号 | 需求描述 / 场景 | 状态 | 验证用例与证据依据 |
| :--- | :--- | :---: | :--- |
| **REQ-MM-01** | **官方语法作为高保真权威** | `passed` | `doc_tool/ui/content/mermaid_renderer.py` |
| REQ-MM-01.S1 | 官方合法的扩展语法（前置配置、新形状） | `passed` | `test_official_mermaid_fidelity.py::test_5_2_official_syntax_validation_accepts_new_shapes_and_frontmatter` |
| REQ-MM-01.S2 | 真正的语法错误（准确行号定位） | `passed` | `test_official_mermaid_fidelity.py::test_5_2_official_syntax_validation_accepts_new_shapes_and_frontmatter` |
| REQ-MM-01.S3 | 未随包提供的类型（保留源码并说明） | `passed` | `test_official_mermaid_fidelity.py::test_5_6_unsupported_type_and_error_reporting` |
| **REQ-MM-02** | **流程图语义完整呈现** | `passed` | `test_official_mermaid_fidelity.py` |
| REQ-MM-02.S1 | 子图与样式 | `passed` | `test_official_mermaid_fidelity.py::test_5_3_flowchart_official_rendering` |
| REQ-MM-02.S2 | 回边与长中文标签 | `passed` | `test_official_mermaid_fidelity.py::test_5_3_flowchart_official_rendering` |
| **REQ-MM-03** | **时序图控制结构完整呈现** | `passed` | `test_official_mermaid_fidelity.py` |
| REQ-MM-03.S1 | 条件与循环（alt/else、opt、loop） | `passed` | `test_official_mermaid_fidelity.py::test_5_4_sequence_diagram_official_rendering` |
| REQ-MM-03.S2 | 备注与激活状态（Note、activate） | `passed` | `test_official_mermaid_fidelity.py::test_5_4_sequence_diagram_official_rendering` |
| REQ-MM-03.S3 | 消息编号遵循统一配置（autonumber） | `passed` | `test_official_mermaid_fidelity.py::test_5_4_sequence_diagram_official_rendering` |
| **REQ-MM-04** | **各图形入口保持同一契约** | `passed` | `doc_tool/ui/content/mermaid_dialog.py` |
| REQ-MM-04.S1 | 从阅读区进入工作台（复用官方引擎） | `passed` | `test_official_mermaid_fidelity.py::test_5_5_workbench_and_viewer_reuse_same_contract` |
| REQ-MM-04.S2 | 缓存与主题更新（主题不同重新取得） | `passed` | `test_mermaid_export_and_cache.py::test_6_1_export_svg_and_theme_identity` |
| **REQ-MM-05** | **图片导出与插入契约** | `passed` | `doc_tool/application/content/mermaid.py` |
| REQ-MM-05.S1 | 离线桌面导出（无 Node/npm 生成高保真 PNG） | `passed` | `test_mermaid_export_and_cache.py::test_6_2_desktop_png_export_without_node` |
| REQ-MM-05.S2 | 图形尺寸与清晰度（逻辑尺寸与 2x DPI） | `passed` | `analysis/markdown-mermaid-preview-fidelity/verify_real_word_insertion.py` |
| REQ-MM-05.S3 | 无 GUI 命令行渲染（不强制拉起 WebEngine） | `passed` | `test_mermaid_export_and_cache.py::test_6_3_cli_environment_detection_and_parity` |
| **REQ-MM-06** | **失败与近似降级可见** | `passed` | `test_mermaid_export_and_cache.py` |
| REQ-MM-06.S1 | 官方后端失败后降级（清晰标记近似） | `passed` | `test_mermaid_export_and_cache.py::test_6_3_cli_environment_detection_and_parity` |
| REQ-MM-06.S2 | 修改后渲染失败（保留源码） | `passed` | `test_mermaid_export_and_cache.py::test_6_1_export_svg_and_theme_identity` |
| REQ-MM-06.S3 | 批量转换部分失败（保留失败源码） | `passed` | `test_mermaid_export_and_cache.py::test_6_5_batch_convert_naming_and_partial_failure` |

---

## 4. 人工与外部对比验证项（Task 9.2 说明）

- **Task 9.2 (VS Code / Typora 对照)**:
  - **当前状态**: `not-run` / `blocked`。
  - **原因**: 运行环境中已安装 VS Code 1.143.0，但 **Typora 缺失（未安装）**。
  - **恢复条件**: 在预发或最终验收环境安装 Typora 后，运行 `scripts/tests/fixtures/preview_fidelity/` 夹具进行双软件像素级对照。
  - **规则遵循**: 依照任务清单约束“缺参考应用时本项保持未完成”，任务 9.2 严格保持未勾选 `[ ]`，不在交接中冒充通过。
