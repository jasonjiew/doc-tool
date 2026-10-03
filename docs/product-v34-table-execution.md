# V3.4 普通表格编辑执行台账

更新日期：2026-10-03（Asia/Shanghai）。执行基准 HEAD `d68b514` + 工作树。任务勾选只由 [V3.4 tasks](../openspec/changes/product-v34-table-authoring/tasks.md) 维护。统一入口见 [总路线图](product-master-roadmap.md)，能力现状见 [功能清单](product-function-catalog.md)。

本包只做普通表格的编辑与粘贴：Markdown 仍是唯一内容源，复杂原生 Word 表格、合并单元格、嵌套/富格式内容不转换，继续走既有保留路径。

## 1. 批次状态

| 批次 | 状态 | 用户入口 | 证据 |
|---|---|---|---|
| 34-A 模型与表达验证 | 完成 1.1～1.4 | 服务层 `application/content/table_grid.py` | [多行表达证据](../analysis/product-v34-table-20261003/multiline-support.json)、[相关回归](../analysis/product-v34-table-20261003/v34-related.xml) |
| 34-B 网格与缓冲应用 | 完成 2.1～2.4 | 编辑器工具栏「表格网格」、菜单「内容 → 编辑表格网格…」、命令面板（Ctrl+Alt+G） | 同上 |
| 34-C 显式表格粘贴 | 完成 3.1～3.4 | 编辑器工具栏「粘贴为表格」、菜单「内容 → 粘贴为表格…」（Ctrl+Alt+V） | 同上 |
| 34-D 预览与同源出稿 | 完成 4.1～4.4 | 预览面板 / 快速出稿 / 导出设置（沿用 CORE） | 同上 |
| 34-E 实用性验收 | 5.1、5.3、5.4 完成；5.2 部分（1280×720、键盘、中文单元格已自动验证；真实 IME 与 Excel/Word 剪贴板待验收） | — | [大输入测量](../analysis/product-v34-table-20261003/large-table-measurement.json) |

## 2. 实现要点

1. `table_grid.TableModel`：表头 + 数据行 + 列对齐 + 原片段范围 + 片段摘要；复用既有 `table_format` 的切分/对齐/宽度实现，不另造一套渲染。
2. 转义往返：单元格逻辑文本用 `escape_cell`/`unescape_cell` 处理 `|` 与 `\`；空单元格与行尾空列保留；非矩形输入补空列并提示，原始输入保留可复制。
3. 片段身份：`fragment_digest` + `locate_fragment`（唯一定位，多处相同时按光标附近选择，否则拒绝并说明）；`apply_fragment` 只替换命中的行区间。
4. 网格对话框 `ui/content/table_grid_dialog.py`：行列增删/移动、列对齐、Tab/Shift+Tab 跨单元格导航、网格内撤销/重做（Ctrl+Z / Ctrl+Shift+Z）、支持范围说明、Markdown 预览；关闭时若已改动则保留待应用文本。
5. 编辑器应用：`EditorPanel.open_table_grid()` 只替换原表格片段，用一个 `QTextCursor` 编辑单元（一次撤销）；原表格已变或匹配不唯一时**不覆盖**，保留网格草稿并提供“重新定位并应用”。
6. 粘贴：`parse_clipboard_text` 优先引号感知 TSV（标准库 `csv`），其次已有管道表格；前导零、日期、`=公式` 按文本保留；引号内换行转为 `<br>`；大输入只分页预览、插入不截断。普通 Ctrl+V 文本/图片流程完全不变。
7. 多行表达：`<br>` 在预览中保留为换行，在 Word 中同一单元格内形成换行（证据见 `multiline-support.json`）。

## 3. 每批交接记录

```text
日期 / 执行 HEAD / 工作树基准 / 包 / 批次：2026-10-03 / d68b514 + 工作树 / product-v34-table-authoring / 34-A～34-E
完成任务编号 / 当前 tasks 勾选：1.1-1.4、2.1-2.4、3.1-3.4、4.1-4.4、5.1、5.3、5.4 / 19/20（5.2 实机部分待验收）
复用的真实服务与直接依赖：content/table_format.py（切分/对齐/宽度）、content/preview.py（预览）、CORE 捕获与 project_export（同源出稿）；编辑器既有 QTextCursor 编辑单元
本批补的差额：见第 2 节；另修正测试运行器只注入与当前解释器同版本的 site-packages
用户入口 / 操作步骤 / 实际结果 / 产物位置：光标在普通表格内 → 工具栏「表格网格」→ 增删行列/对齐 → 应用（一次撤销）→ 预览/出稿；剪贴板有 TSV → 「粘贴为表格」→ 预览（首行表头可切换）→ 插入
来源模式 / captureId / projectId-itemId / 源与缓冲事实：表格随章节进 CORE 当前内容捕获；未保存表格进入 DOCX/HTML（`unsaved_table_reaches_*` 断言），源文件字节不变
默认正常 / 自动兜底 / 待完善 / 未执行：正常＝普通表格网格与 TSV 粘贴；兜底＝非矩形补空列并提示、原片段变化保留待应用文本、非表格输入回普通粘贴、只读项目拒绝写入；待完善＝网格只支持受支持普通表格；未执行＝真实 Excel/Word 剪贴板与 IME 试用
相关验证命令 / 环境 / 退出码 / 报告：见第 4 节
Word、剪贴板、冻结、视觉或性能实测证据：多行单元格已用诊断 DOCX 读回验证；1,000×20 解析 0.0s、序列化 0.063s；真实剪贴板与视觉为待验收
已有失败分类 / 环境缺失 / 剩余风险：真实 IME、Excel 剪贴板与 Word 视觉未在本机验证
下一直接任务 / 阻塞动作与可继续动作：34-E 5.2 实机复核待环境；功能队列继续 V3.5
```

## 4. 验证命令与证据

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'; $env:PRODUCT_V34_EVIDENCE='1'
$env:PYTHONPATH='D:/ai_develop_project_space/doc-tool/tmp/v26-test-deps'
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/tests/run_tests.py --junit analysis/product-v34-table-20261003/v34-related.xml test_v34_table_authoring.py test_table_format.py test_content_operations.py test_markdown_structure.py
```

- [大输入测量](../analysis/product-v34-table-20261003/large-table-measurement.json)：1,000 行 × 20 列，解析 0.0s、序列化 0.063s、无截断。
- [多行表达](../analysis/product-v34-table-20261003/multiline-support.json)：`<br>` 在预览保留为换行，Word 单元格文本为「第一行⏎第二行」。
- 本包新增 `scripts/tests/test_v34_table_authoring.py` 25 项用例（含 GUI 网格/粘贴/撤销与 CORE 出稿）。

## 5. 待验收项（保持未勾选）

| 项 | 原因 | 复验步骤 |
|---|---|---|
| 34-E 5.2 真实 IME 与剪贴板 | 本机为 Qt offscreen，无真实输入法与 Excel/Word 剪贴板 | 在真实桌面用 Excel 复制含空单元格/前导零/日期的区域 → 「粘贴为表格」核对预览与插入；用中文 IME 在网格内输入并切换行列；1280×720 下核对工具栏入口与对话框 |
| Word 视觉版式 | 需要真实 Word 观察 | 打开诊断 DOCX 与真实 Word 刷新后的成果，核对列宽、换行与跨页表头 |

全量回归（最终状态，含 36-C/36-D 补齐后）：`scripts/tests/run_tests.py` 默认清单 **171 个测试文件、0 失败、内部用例 2801 项**（1747s），报告 `analysis/product-full-regression-round2.xml`；此前一轮（本轮功能前）为 [171 文件 / 0 失败 / 2791 项](../analysis/product-full-regression-green.xml)。

适配说明：新增「表格网格/粘贴为表格」后，`test_ui_polish_toolbar.py` 的“恰好 14 个动作”断言改为“原 14 个动作不丢失、相对顺序不变、所有当前动作都有找回路径”，原意图保留。

## 实施后审查补记（2026-10-03）

已继承本包实现并补真实差额，范围、修复和验收见 [实施后报告](product-post-implementation-review-20261003.md)。本次相关回归27文件/552用例、最终规范回归4文件/75用例以及报告回归7用例通过；保留本包原实机未完成项，没有重置原勾选。当前新开发接 [MAIN+V3.7～V3.9](product-v37-v39-roadmap.md)，正常首项MAIN-A 1.1，已有批次先完成再插入；此前171文件全量为历史证据。
