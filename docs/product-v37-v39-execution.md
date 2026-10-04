# 主功能优化 + V3.7～V3.9 独立执行台账

日期：2026-10-03。范围依据 [主功能补充](product-main-workflow-optimization.md)及 [产品/UI/交互路线图](product-v37-v39-roadmap.md)，继承 [实施后修复](product-post-implementation-review-20261003.md)。原开发指令保留在 [历史提示词](product-main-v37-v39-execution-prompt.md)；最新下一队列见文末第8节及 [V4.0～V4.3完整指令](product-v40-v43-execution-prompt.md)。

## 1. 当前状态

| 包 | 任务入口 | 规划状态 | 实施勾选 | 未勾选项 |
|---|---|---|---|---|
| MAIN | [product-main-workflow-optimization](../openspec/changes/product-main-workflow-optimization/tasks.md) | 4/4 artifacts | 23/24 | 6.3 真实企业底模/Word/IME/Excel 试点 |
| V3.7 | [product-v37-daily-workflow-ux](../openspec/changes/product-v37-daily-workflow-ux/tasks.md) | 4/4 artifacts | 17/20 | 2.4 三成员实机、4.4 真实截屏、5.3 真实桌面/IME/缩放 |
| V3.8 | [product-v38-authoring-and-exchange-ux](../openspec/changes/product-v38-authoring-and-exchange-ux/tasks.md) | 4/4 artifacts | 19/20 | 5.3 真实 Excel/Word 剪贴板、IME、企业底模 |
| V3.9 | [product-v39-rd-workspace-productivity](../openspec/changes/product-v39-rd-workspace-productivity/tasks.md) | 4/4 artifacts | 16/20 | 2.4 三成员实机、4.4 三档对象释放、5.1 三成员闭环、5.3 真实大工程 |

合计：实际任务勾选75/84，九项未完成。需逐项核对自动可执行与真实环境部分；39-D 4.4合成三档/释放量测可先补，三成员和页面状态亦先核对可自动覆盖范围。任务全部验收满足前保持未勾选。

## 2. MAIN-A～F 实际改动与证据

| 编号 | 真实差额 | 修复 | 证据 |
|---|---|---|---|
| 1.1 | Word 段落代码缩进被 `_para_text().strip()` 抹掉 | 新增 `_para_text_raw`，仅在确有前导空白时保留原文 | `scripts/tests/test_main_a_import_quality.py` |
| 1.2 | 保留对象只有章节标题，无章节文件与行号 | 新增 `target_path`/`target_line`，拆分后按锚点回查真实章节文件 | 同上 |
| 1.3 | Markdown 资源按 basename 去重：同名不同目录丢图、两来源 `image.png` 串来源 | 资源身份按相对路径判定，冲突改名并只改写引用它的章节；`assetRoot` 统一 `assets/<类型>` | `scripts/tests/test_project_from_markdown_v28.py` |
| 2.1 | 查找替换只看磁盘、无范围 | `scope_paths`/`text_overrides` + 范围下拉 + 活缓冲写回 | `scripts/tests/test_main_b_replace_scope.py` |
| 2.2 | 标题/列表工具改写围栏代码块 | 跳过围栏代码与围栏行，空行不加前缀 | 同上 `FormatToolCodeFenceTests` |
| 2.3 | 没有「复制章节」，条目身份无法保证 | `copy_chapter`（新 `DOC-ITEM` ID）+ 章节树「复制章节…」 | `scripts/tests/test_main_b_chapter_copy.py` |
| 2.4 | 预览后正文变化会按陈旧列偏移写错位置 | 校验命中行文本，冲突文件整体跳过并继续其余 | `test_main_b_replace_scope.py` |
| 4.1 | 检查只看磁盘、无范围 | 检查面板范围下拉 + scoped linter（含未保存缓冲） | `scripts/tests/test_main_d_lint_scope.py` |
| 4.2 | 修复无差异预览、无撤销 | 差异确认 + 「撤销上次修复」；当前章修复写活缓冲 | 同上 |
| 4.3 | 关闭视图后挂起的去抖仍会触发 | `EditorPanel.stop_pending_work()` 与 `closeEvent` | 同上 `PreviewLifecycleTests` |
| 4.4 | 无实测数据 | `analysis/main-d/measure-check-hotpath.json`（120 章 ×5 次采样） | 见第 3 节 |
| 5.2 | 普通 Markdown 长表首行没有 `tblHeader` | 管道表首行标记为表头行，跨页重复表头 | `scripts/tests/test_main_e_output_quality.py` |
| 5.3 | 整份出稿丢失「只有 `_index.md` 的父章节」 | `_materialize` 整份范围补齐全部 `_index.md` | `scripts/tests/test_main_f_flow.py` |
| 5.4 | 单格式异常中断整轮，已生成成果一起丢失 | 每个格式独立兜底，转为该格式失败结果 | `scripts/tests/test_main_e_export_rounds.py` |

MAIN-C 3.1～3.4 经核对为既有实现，本轮以新增用例固定行为（`scripts/tests/test_main_c_assets_and_refs.py`）。

## 3. MAIN-D 4.4 性能实测

`analysis/main-d/measure-check-hotpath.json`，120 章项目，每项 5 次采样（Python 3.13 / Windows）：

| 口径 | 中位耗时 |
|---|---|
| 完整扫描（无派生缓存）+ 检查 | 44.28 ms |
| 复用增量缓存 + 检查 | 38.29 ms |
| 仅索引构建：完整扫描 / 缓存复用 | 36.85 / 31.66 ms |
| 改一章后刷新 | 31.46 ms（`parseCount=1`、`reuseCount=119`） |
| 缓存损坏后重建 | 44.37 ms，问题清单与完整扫描一致 |

结论（如实记录）：单章变更只重解析 1 章；缓存损坏可重建且检查结果与完整扫描一致；但**端到端检查热路径只快约 1.16×**。索引与规则成本须在同次运行内进一步拆分，现有不同采样口径不能证明检查遍历是唯一瓶颈。不作为已达成的提速指标宣传。

## 4. V3.7～V3.9 实际改动与证据

| 编号 | 真实差额 | 修复/验证 | 证据 |
|---|---|---|---|
| 37-B 2.1 | 跳转返回只还原章节与光标，丢失原页面/筛选/选中行 | `NavLocation` 增加 `panel`/`view`；工作区采集并恢复面板状态；问题面板新增 `view_state`/`restore_view_state` | `scripts/tests/test_v37_navigation_context.py` |
| 37-C 3.1 | 无结果时没有下一步动作 | 问题面板无结果时就地出现「清除筛选」，空/失败状态文案给出下一步 | 同上 |
| 38-A 1.1/1.4 | 粘贴预览只有第一页，无法翻到末页 | `table_grid.preview_page` + 预览对话框上一页/下一页/总行数；翻页与表头切换不改完整模型 | `scripts/tests/test_v38_table_paste_paging.py`（1000×20，第 50 页） |
| 38-B 2.1 | 从项目建规范包默认把整份业务正文装进骨架 | `draft_from_project` 默认只写标题层级骨架，正文副本需显式 `include_body`；草稿记录 `skeletonMode` | `scripts/tests/test_v38_pack_skeleton_mode.py` |
| 39-A 1.3 | 无覆盖口径实测 | 25 需求分 3 页时指标/覆盖率完全一致；未声明需求为 N/A 而非 0% | `scripts/tests/test_v39_matrix_coverage.py` |

其余 V3.7～V3.9 项经核对为既有实现，本轮以对应测试套件固定行为并在 tasks 中逐项标注证据路径。

## 5. 验证与回归

分块回归：`analysis/regression/run_tests_chunked.py` 逐文件限时（300s）运行 `scripts/tests`，报告写入 `analysis/regression/report.json`（含每个文件退出码、耗时、通过/失败计数与超时标记），避免整套运行在解释器退出阶段挂起而丢失覆盖统计。

原分块回归记录（180个测试文件）：**2860 passed / 4 failed / 15 skipped / 1 timeout**。报告另有8个非零退出文件，含直接相关test_main_e_export_rounds.py。下表保留原执行时的现象/判定，不代表已经证明全部与改动无关；根因与适配在40-A复现核实，不能以未修改文件判定无关。

| 文件 | 现象 | 判定 |
|---|---|---|
| `test_core_export_ui.py` | `ChangeDirectoryActionTests` 在 `main_window._present_export_report` 的 `QMessageBox.exec()` 上阻塞（faulthandler 栈已确认） | 既有问题：该用例类未打桩 `QMessageBox`，与本轮改动无关（`doc_tool/ui/main_window.py` 未修改） |
| `test_home_experience_iteration.py` | `ProjectBar._close_btn.isHidden()` 期望 False | 既有：与 `project_bar.py` 无关（本轮未修改） |
| `test_local_history.py` | 读文件用默认编码（本机 GBK）触发 `UnicodeDecodeError` | 既有：区域设置相关 |
| `test_release_review_bundle.py` | CLI stdout 控制台编码乱码导致断言失败 | 既有：控制台编码相关 |
| `test_iteration_scenarios.py` / `test_validator_negative.py` | `no tests ran`（rc=5） | 既有：非 pytest 收集型脚本 |
| `test_review_docx.py` | 退出码 0xC0000374（堆损坏） | 既有：解释器退出期崩溃，用例本身 17 passed |

原专项记录报告直接相关套件通过；与分块报告中非零退出的差异须按环境、命令和退出阶段复现，不据此宣称最新整套全绿或全部失败无关。

本轮新增/修改的直接相关检查（命令、退出码与断言）：

| 命令 | 结果 |
|---|---|
| `python -m pytest scripts/tests/test_main_a_import_quality.py -q` | 5 passed |
| `python -m pytest scripts/tests/test_project_from_markdown_v28.py -q` | 18 passed |
| `python -m pytest scripts/tests/test_main_b_replace_scope.py test_main_b_chapter_copy.py -q` | 12 passed |
| `python -m pytest scripts/tests/test_main_c_assets_and_refs.py -q` | 8 passed |
| `python -m pytest scripts/tests/test_main_d_lint_scope.py -q` | 6 passed |
| `python -m pytest scripts/tests/test_main_e_output_quality.py test_main_e_export_rounds.py -q` | 9 passed |
| `python -m pytest scripts/tests/test_main_f_flow.py -q` | 3 passed |
| `python -m pytest scripts/tests/test_v37_navigation_context.py -q` | 5 passed |
| `python -m pytest scripts/tests/test_v38_table_paste_paging.py test_v38_pack_skeleton_mode.py -q` | 8 passed |
| `python -m pytest scripts/tests/test_v39_matrix_coverage.py -q` | 3 passed |
| `python analysis/main-d/measure_check_hotpath.py` | 见第 3 节，缓存损坏重建与完整扫描结果一致 |
| `python -m pytest scripts/tests/test_gui_services.py test_authoring_services.py test_format_check_search.py -q` | 170 + 80 + 11 passed |
| `python -m pytest scripts/tests/test_project_from_markdown_v28.py test_core_scope_presets_batch.py test_import_project.py test_intake_word_v28.py test_core_result_page.py test_v34_table_authoring.py test_v35_standard_pack.py test_expression_contract.py test_project_build.py -q` | 436 passed / 1 skipped |
| `python analysis/regression/run_tests_chunked.py` | 180 文件：2860 passed / 4 failed / 15 skipped / 1 timeout（见第 5 节既有问题表） |
| `npx --no-install openspec validate <四个 change> --strict` | 四个 change 全部 valid |

## 6. 真实环境未验收项与复验步骤

| 项 | 缺失条件 | 复验步骤 |
|---|---|---|
| MAIN-F 6.3 | 企业底模、真实 Word、中文 IME、Excel 剪贴板 | 有 Word 的机器上导入真实企业文档 → 企业底模出稿 → Word 刷新目录/页码 → 核对封面/页眉/页脚；中文 IME 输入；Excel 复制 1000×20 粘贴为表格 |
| 37-B 2.4 / 39-B 2.4 / 39-E 5.1 | 真实三成员工程 | 三成员分别建项 → 声明条目 → 建关系 → 看矩阵/影响 → 成员交付 → 集合比较与副本恢复 |
| 37-D 4.4 / 37-E 5.3 / 38-E 5.3 | 真实桌面截屏、125%～200% 缩放、真实剪贴板 | 在 1024×640/1280×720/1920×1080 与 125%/150%/200% 缩放下截屏并量取文字宽度与相邻控件边界 |
| 39-D 4.4 | 三档量测未完成；合成部分不必等待真实工程 | 三档各5次采样切换/关闭及对象释放/完整扫描对照，先合成基准，真实工程可用时另补 |

离屏测试、诊断 DOCX 与 OpenSpec strict 不作为真实验收替代。

## 7. 下一直接任务

1. 当前执行中的批次先完成，随后40-A 1.1复现已有失败/非零退出/超时并逐项核实旧九项，记录实际环境与可执行部分。
2. 39-D 4.4合成50/300/1000章及释放接42-A/E；检查耗时在同次运行拆分发现、读取/摘要、索引、规则与UI，按实测优化而非预设单一瓶颈。
3. 真实Word/底模/IME/团队/大工程条件具备时补原任务；三成员合成闭环接43-E。缺环境只保留对应部分，继续新队列无依赖工作。

## 8. 后续正式队列

更新：2026-10-03。最新读取 HEAD `7ba19dd`；MAIN/V3.7～V3.9 已勾选 **75/84**，余下九项按真实依赖分别补验收。当前新增队列 **V4.0→MAIN2→V4.1→V4.2→V4.3**，26 批/104 项、实施 0/104。先完成已有执行中的批次，再从 **40-A 1.1** 接续。见 [新路线图](product-v40-v43-roadmap.md)、[新台账](product-v40-v43-execution.md)、[完整持续指令](product-v40-v43-execution-prompt.md)。

V4.0先核实回归分类/生命周期，再由 [MAIN2](product-mainline-optimization.md)补真实主线差额，随后模板/检查/交付复用原服务。五包规划strict/apply ready，目前业务0/104；原测试/任务证据保持，本次没有声称已修复回归或完成真实验收。
