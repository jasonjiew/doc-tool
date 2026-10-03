# RD 研发工作区执行台账

更新日期：2026-10-03（Asia/Shanghai）。执行基准 HEAD `d68b514` + 工作树（含 EX-1～EX-3 导出修正与本次 RD 实施）。任务勾选只由 [RD tasks](../openspec/changes/product-rd-workspace-experience/tasks.md) 维护；本文件保存批次交接记录与证据路径。统一入口见 [总路线图](product-master-roadmap.md)，能力现状见 [功能清单](product-function-catalog.md)，默认策略见 [流程与兜底](product-flow-fallback-policy.md)。

本包只做界面集成与最小适配，算法仍在既有服务：`workspace.py`、`overview.py`、`settings.py`、`content/traceable_items.py`、`content/relations.py`、`content/trace_matrix.py`、`content/impact.py`、`content/item_actions.py`、`collection.py`、`collection_ops.py`，成员交付复用 `delivery/gui_tasks.py`、`queue.py`、`collection_bridge.py` 与主窗口既有批量交付入口。

## 1. 批次状态

| 批次 | 状态 | 用户入口 | 证据 |
|---|---|---|---|
| RD-A 基准与适配 | 完成 1.1～1.4 | 菜单「内容 → 研发工作区…」(Ctrl+Alt+D)；薄适配层 `application/rd_surface.py` | [基准与相关回归](../analysis/product-rd-workspace-20261003/rd-a-baseline.xml)、[RD 相关回归](../analysis/product-rd-workspace-20261003/rd-related.xml) |
| RD-B 工作区/概览/设置 | 完成 2.1～2.4 | 工作区新建/打开/保存、引用/复制加入、移除、重新定位、成员打开、概览与下一步、设置分组 | 同上；`test_rd_workspace_surface.py`、`test_rd_workspace_entry.py` |
| RD-C 条目与关系 | 完成 3.1～3.4 | 「条目与关系」页：声明/复制/改编号/定位、双端检索、建立/删除关系、仅保存相关两端 | 同上 |
| RD-D 矩阵与影响复核 | 完成 4.1～4.4 | 「矩阵与影响」页：指标、未覆盖筛选、分页、来源跳转、变化/影响、复核记录与重检 | 同上；[闭环证据](../analysis/product-rd-workspace-20261003/closed-loop.json) |
| RD-E 集合与成果 | 完成 5.1～5.4 | 「集合与成果」页：列表/详情/比较/导出包/打开成果/恢复为副本/成员交付 | 同上 |
| RD-F 验收与交接 | 6.1、6.2、6.4 完成；6.3 部分（1280×720 与键盘已自动验证，真实桌面/Word 试点待验收） | — | 同上 |

## 2. 本批补的真实差额

1. `settings.save_settings` 原先忽略基本信息分组的 `documentName`/`documentNo`，保存分组等于静默丢弃输入；现按既有清单模型写入并保留原校验（名称空值定位到字段，失败不写任何文件）。
2. 关系端点草稿判定原来只看“条目是否在索引里”，而索引包含未保存缓冲；现在另建**只用磁盘内容**的已保存索引，同章节的缓冲修改也会正确进入“仅保存相关两端”流程。
3. `collection_ops.export_package` 需要 ZIP 文件路径；界面按目录选择时会在适配层生成安全文件名，避免把目录当文件写入失败。
4. 集合详情把成果/清单列为相对路径字符串；界面改为两者都接受，否则“打开成果”永远没有可选项。
5. 已保存摘要再变化时，旧复核在界面上显式标为“待重检（内容已变化）”，不再继续显示为通过。
6. 测试运行器只注入与当前解释器同版本的 `site-packages`（原先在 3.12 解释器下追加 3.13 目录，`lxml` 等二进制扩展因 ABI 不符导入失败）。

## 3. 每批交接记录

```text
日期 / 执行 HEAD / 工作树基准 / 包 / 批次：2026-10-03 / d68b514 + 工作树 / product-rd-workspace-experience / RD-A～RD-F
完成任务编号 / 当前 tasks 勾选：1.1-1.4、2.1-2.4、3.1-3.4、4.1-4.4、5.1-5.4、6.1、6.2、6.4；6.3 部分 / 23/24
复用的真实服务与直接依赖：workspace/overview/settings/traceable_items/relations/trace_matrix/impact/item_actions/collection/collection_ops；delivery gui_tasks+queue+collection_bridge；主窗口既有章节打开、缓冲收集、批量交付与导出入口
本批补的差额：见第 2 节 6 项（设置名称写入、已保存索引、导出包目录、成果列表、过期复核标注、测试运行器 ABI）
用户入口 / 操作步骤 / 实际结果 / 产物位置：菜单「内容 → 研发工作区…」→ 成员/概览/设置 → 条目与关系 → 矩阵与影响 → 集合与成果；结果与证据见 analysis/product-rd-workspace-20261003/
来源模式 / captureId / projectId-itemId / 源与缓冲事实：条目身份为 projectId+itemId；界面区分“已保存版本”“当前编辑缓冲”“CORE 捕获”；成员出稿沿用 CORE 捕获，不在此重定义 captureId
默认正常 / 自动兜底 / 待完善 / 未执行：默认正常＝三成员闭环与单文档直用；兜底＝缺成员保留其他成员、关系草稿、部分恢复、只读成员禁写、坏配置字段定位；待完善＝成员交付状态明细仍由既有批量交付页展示；未执行＝真实桌面/Word 试点
相关验证命令 / 环境 / 退出码 / 报告：见第 4 节
Word、剪贴板、冻结、视觉或性能实测证据：无（本包不含 Word/剪贴板实现；视觉为 Qt offscreen 截图/几何）
已有失败分类 / 环境缺失 / 剩余风险：真实 Windows 缩放、IME、Word 视觉、多屏窗口激活未在本机验证
下一直接任务 / 阻塞动作与可继续动作：RD 6.3 实机验收待环境；功能队列继续 V3.4
```

## 4. 验证命令与证据

环境：Windows，bundled Python 3.12.14，`QT_QPA_PLATFORM=offscreen`，PySide6 来自 `.vendor/site-packages`，PyYAML 来自 `tmp/v26-test-deps`，中文字体由既有测试环境注册。

```powershell
$env:PYTHONUTF8='1'; $env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:/ai_develop_project_space/doc-tool/tmp/v26-test-deps'
$env:QT_QPA_PLATFORM='offscreen'
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/tests/run_tests.py --junit analysis/product-rd-workspace-20261003/rd-related.xml test_rd_workspace_surface.py test_rd_workspace_entry.py test_workspace_v29.py test_relations_v29.py test_trace_matrix_v29.py test_impact_v29.py test_collection_v29.py test_collection_ops_v29.py test_item_actions_v29.py test_matrix_page_v29.py test_traceable_items_v29.py test_settings_v28.py test_overview_v28.py test_diagram_viewer_interaction.py test_gui_services.py
```

- [RD 相关回归](../analysis/product-rd-workspace-20261003/rd-related.xml)：15 个测试文件、0 失败，内部用例合计 389 项（含 `test_rd_workspace_surface.py` 35 项、`test_rd_workspace_entry.py` 9 项；`test_gui_services.py` 170 项）。文件级 `failures=0` 只代表这些文件退出 0。
- OpenSpec 校验：`openspec validate product-rd-workspace-experience --strict` → `Change is valid`；`openspec instructions apply` 起始状态 0/24、执行后 23/24。
- [RD-A 基准](../analysis/product-rd-workspace-20261003/rd-a-baseline.xml)：`test_gui_services.py`（高 schema 只读）、`test_settings_v28.py`、`test_diagram_viewer_interaction.py`（Mermaid GUI 状态）、`test_core_export_snapshot.py`（只读项目外部导出不改写项目），0 失败。
- [闭环证据](../analysis/product-rd-workspace-20261003/closed-loop.json)：三成员、3 条目、2 关系、矩阵 1 行、设计/测试覆盖 100%、集合 1 份、缓冲影响 2 行、恢复副本成功；`realDesktopTrial=false`、`realWordTrial=false`。
- 说明：文件级 `failures=0` 只代表这些测试文件退出 0；内部用例数（RD 两个新文件 44 项：31+9+4 详见输出）与观察脚本分开记录，不把诊断退出 0 当作需求通过。

## 5. 待验收项（保持未勾选）

| 项 | 原因 | 复验步骤 |
|---|---|---|
| RD 6.3 真实桌面/Word 试点 | 本机为 Qt offscreen，无真实桌面与 Word 交互条件 | 在 1280×720 及 125%/150% 缩放下打开「研发工作区…」，验证页签切换、键盘焦点、成员窗口激活与中文长名；用真实 Word 项目走一次成员交付并记录逐成员状态 |
| 多窗口成员激活视觉 | 需要真实桌面窗口管理 | 打开两个成员窗口后从工作区点“打开成员”，确认已有窗口被激活而不是新开 |

真实缩放、IME 与 Word 视觉项不影响本包其他功能与后续包。

全量回归（最终状态，含 36-C/36-D 补齐后）：`scripts/tests/run_tests.py` 默认清单 **171 个测试文件、0 失败、内部用例 2801 项**（1747s），报告 `analysis/product-full-regression-round2.xml`；此前一轮（本轮功能前）为 [171 文件 / 0 失败 / 2791 项](../analysis/product-full-regression-green.xml)。

## 实施后审查补记（2026-10-03）

已继承本包实现并补真实差额，范围、修复和验收见 [实施后报告](product-post-implementation-review-20261003.md)。本次相关回归27文件/552用例、最终规范回归4文件/75用例以及报告回归7用例通过；保留本包原实机未完成项，没有重置原勾选。当前新开发接 [MAIN+V3.7～V3.9](product-v37-v39-roadmap.md)，正常首项MAIN-A 1.1，已有批次先完成再插入；此前171文件全量为历史证据。
