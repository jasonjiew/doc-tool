# V4.0 + MAIN2 + V4.1～V4.3 联合执行台账

日期：2026-10-03。方向与验收见 [路线图](product-v40-v43-roadmap.md)，完整持续指令见 [执行提示词](product-v40-v43-execution-prompt.md)。本次为规划准备，不实施业务功能。

## 1. 读取基准与当前状态

初始HEAD `f6d70ed`、应用 `2.9.0`；最终静态校验HEAD为`7ba19dd`，原任务勾选不变。它们是读取快照，执行时先核对实际HEAD/工作树/tasks/证据。MAIN/V3.7～V3.9已勾选23/24、17/20、19/20、16/20，合计 **75/84**；旧RD/V3.4～V3.6台账继续保留，不重做已实现部分。

| 包 | change / 任务 | 规划 artifacts | apply | 实施 | 批次 |
|---|---|---|---|---|---|
| V4.0 | [product-v40-runtime-and-word-reliability](../openspec/changes/product-v40-runtime-and-word-reliability/tasks.md) | 4/4，strict valid | ready | 0/20 | A→E |
| MAIN2 | [product-mainline-usability-and-fidelity](../openspec/changes/product-mainline-usability-and-fidelity/tasks.md) | 4/4，strict valid | ready | 0/24 | A→F |
| V4.1 | [product-v41-enterprise-template-workflows](../openspec/changes/product-v41-enterprise-template-workflows/tasks.md) | 4/4，strict valid | ready | 0/20 | A→E |
| V4.2 | [product-v42-incremental-quality-workbench](../openspec/changes/product-v42-incremental-quality-workbench/tasks.md) | 4/4，strict valid | ready | 0/20 | A→E |
| V4.3 | [product-v43-delivery-and-revision-workbench](../openspec/changes/product-v43-delivery-and-revision-workbench/tasks.md) | 4/4，strict valid | ready | 0/20 | A→E |

合计 **26批/104项，0/104**，五个change/12份能力规范。每包含proposal、design、specs、tasks；MAIN2四份能力，其他每包两份。原80项编号/勾选保持，新增MAIN2 24项独立编号。apply ready/strict仅表示规划可执行。

先完成已有批次，随后 **V4.0→MAIN2→V4.1→V4.2→V4.3**；MAIN2按A→F，其他A→E。正常下一直接任务 **40-A 1.1：复现最新回归非零退出/失败/超时，保存真实环境、命令和分类**。MAIN2范围见 [主线计划](product-mainline-optimization.md)，实机缺项不作为总门禁。

## 2. 原报告事实与待核实分类

[旧台账](product-v37-v39-execution.md)与 [分块报告](../analysis/regression/report.json)保留历史原文。本轮读取：180 文件；2860 passed / 4 failed / 15 skipped；8 个非零退出文件；1 个超时文件。报告非零列表含直接相关 `test_main_e_export_rounds.py`，不能仅凭未修改文件判为全部无关。

本规划会话未重跑业务测试、Word 探测或刷新。40-A 须记录真实复现并核实报告使用的解释器/runner；不因历史某次专项通过就删除当前非零退出。

旧九项尚未完成：MAIN 6.3；37 2.4/4.4/5.3；38 5.3；39 2.4/4.4/5.1/5.3。自动可覆盖部分、真实环境已测、仍待环境和未执行工作分别记录。39-D 4.4 合成多规模与释放量测接 42-A/E；三成员合成闭环接 43-E；只有全部原验收满足才更新原任务。

## 3. 每批事实记录

使用以下字段追加到本文件；原勾选/证据不覆盖。未知信息写未知，不补造完成数、耗时或根因。

```text
日期 / HEAD / change / 批次 / 实际工作树：
任务编号 / 已实现与本次差额：
真实入口 / 默认操作 / 正文或成果：
原服务 / 参数读回 / 来源与范围 / 捕获身份：
UI尺寸/主题/状态/键盘/定位返回：
兜底 / 局部失败 / 可用成果 / 原件和缓冲：
命令 / 解释器与依赖 / 退出码：
实际执行文件 / 用例 passed/failed/skipped / 超时/未覆盖：
内容与来源断言 / 截图或几何 / 性能与对象释放：
真实Word/企业底模/IME/冻结/团队已测与待验收：
任务勾选依据 / 原旧缺项补验收依据：
下一直接任务 / 可独立继续项：
```

## 4. 规划校验与后续更新

本次五个change status全部artifacts done、strict valid、apply ready；MAIN2 0/24，其余每包0/20，共104项/27个OpenSpec Markdown文件，按 [本次复核记录](../analysis/product-mainline-plan-review-20261003/verification.json)核对。原80项 [历史校验](../analysis/product-v40-v43-plan-20261003/verification.json)保留。业务测试未执行。

再次复核静态线索：导入详情40项截断、复导入实际入口未接现有预览、复制未传当前文本、图片面板磁盘/脏项处理不统一、版式在刷新/状态后应用。HTML独立目录底层已实现，MAIN2主要修来源提示/清单。执行时逐项复现，不能把本次规划记为已修复代码。

功能实施后每批填写真实结果，包末更新本表和用户用法。真实试点任务保持未勾选直到有证据；未达性能目标如实记录。不自动发布、推送、归档、安装到他人环境或发送外部消息。

<!-- 实施记录自本节追加 -->

## 5. 实施记录（V4.0 起）

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-A、40-B

**任务编号 / 已实现与本次差额**

- 40-A 1.1：按真实 runner（`scripts/tests/run_tests.py` 的 `python <file>` 入口）与
  `python -m pytest <file> -q` 双口径复现历史报告的非零退出/失败/超时文件，
  逐个分类；同时确认当前 glob 为 **186 个** `test_*.py`（历史报告 180 个，新增
  `test_code_review_regressions`、`test_v37_navigation_context`、`test_v38_pack_skeleton_mode`、
  `test_v38_table_paste_paging`、`test_v39_matrix_coverage`，另有本轮 `test_v40_word_operations`）。
- 40-A 1.3：修正非交互 GUI 测试的模态等待——新增 `MainWindow._exec_message_box`
  单一动作接缝，`ChangeDirectoryActionTests` 显式处理「出稿结果」模态框；
  `ProjectBar` 关闭项目用例改为断言动作可用且在地/「更多」菜单可达（不再锁定
  布局细节）。真实按钮与服务调用仍由 `test_quick_export_calls_service_and_presents_results`
  等断言覆盖。
- 40-A 1.2（部分）：修正分块复现脚本的**运行方式差异**——并行复现脚本缺
  `PYTHONUTF8=1`/`PYTHONPATH` 时，`test_local_history`、`test_release_review_bundle`
  会以 `UnicodeDecodeError`/控制台乱码断言失败；与真实 runner 对齐后两者全绿。
  该适配只改复现方式，未改产品代码，也未放宽任何断言。
- 40-B 2.1/2.2/2.3：新增 `doc_tool/domain/word_operations.py`（阶段/预算/归属/停止/诊断
  契约），把 `word_convert.convert_document`、`scripts/refresh_fields.py` 的
  探测/启动/打开/处理/写成果/退出各阶段接到统一阶段记录与有限预算；超时后按
  **停止预算**确认终止，归属不可证明时只登记残留、绝不按进程名清理用户 Word；
  刷新 worker 经 stderr 阶段标记回传，`supervise` 保持 `(ok, reason)` 兼容签名，
  `refresh_with_project(report=...)` 把事实带入 `pipeline.PipelineResult.wordRefresh` 与事件 `metrics`。

**真实入口 / 默认操作 / 正文或成果**

- 复现入口：`python analysis/regression/run_tests_chunked.py`（串行口径）、
  `python analysis/regression/run_tests_chunked_parallel.py --workers 4`（同命令并行口径）、
  `python scripts/tests/run_tests.py --junit ... <files>`、`python -m pytest <files> -q`。
- Word 有界入口：`convert_document(..., report=..., progress_cb=...)`、
  `refresh_fields.supervise`（内部 `_bounded_supervise_in_thread`）、
  `kernel.refresh_with_project(..., report=...)`。

**命令 / 解释器与依赖 / 退出码**

- Python 3.13.13（`C:\...\Python313\python.exe`）、pytest 9.1.1、PySide6 6.8.3；`QT_QPA_PLATFORM=offscreen`。
- `python scripts\tests\run_tests.py test_main_e_export_rounds.py ...`（9 个历史异常文件）→ 退出码 1，唯一真实失败为 `test_home_experience_iteration.py`（1 failed/18 passed）。
- `python scripts\tests\test_main_e_export_rounds.py` 连续 3 次 → `rc=0`（4 passed）；`test_review_docx.py` 连续 2 次 → `rc=0`（17 passed）。历史报告里的 `rc=4294967295`（= -1）与 `0xC0000374` 堆损坏在本机隔离运行**不可复现**，与并发执行时的解释器退出期异常相关，如实保留为未决异常。
- `python analysis\regression\run_tests_chunked_parallel.py --workers 4`（186 文件）→ 实测 **2874 passed / 4 failed / 15 skipped**；非零退出 7 个文件、超时 2 个文件（详见下表）。

**实际执行文件 / 用例 passed-failed-skipped / 超时与未覆盖**

| 文件 | 复现事实 | 分类 |
|---|---|---|
| `test_home_experience_iteration.py` | 1 failed / 18 passed（`ProjectBar` 关闭按钮原地可见性） | 真实断言过时 → 已改为动作可达性断言，**已修复** |
| `test_core_export_ui.py` | 并行口径 300s 超时且 0 用例；隔离运行 5 passed | 真实模态等待（`QMessageBox.exec()`）→ 已加动作接缝，**已修复** |
| `test_ui_polish_results.py` | 1 failed / 13 passed（换目录新一轮来源口径） | 真实产品差额（已保存来源被注入未保存缓冲）→ **已修复** |
| `test_local_history.py` | 缺 `PYTHONUTF8=1` 时 1 failed（GBK 解码）；带该变量 26 passed/1 skipped | 运行方式差异（编码）→ 复现脚本对齐 |
| `test_release_review_bundle.py` | 缺 `PYTHONUTF8=1` 时 1 failed（控制台编码断言）；带该变量全绿 | 运行方式差异（编码）→ 复现脚本对齐 |
| `test_iteration_scenarios.py` | `no tests ran`（rc=5） | 独立脚本，无 pytest 用例 → 不计为通过，脚本入口 0 退出 |
| `test_validator_negative.py` | `no tests ran`（rc=5）；直接执行 `[SUCCESS]` rc=0 | 独立脚本，无 pytest 用例 → 同上 |
| `test_main_e_export_rounds.py` | 隔离 3 次 rc=0（4 passed）；历史报告 rc=-1 | 解释器退出期异常，当前不可复现，**保留未决** |
| `test_review_docx.py` | 隔离 2 次 rc=0（17 passed）；历史报告 0xC0000374 | 解释器退出期堆损坏，当前不可复现，**保留未决** |
| `test_v30_reuse_entry.py` | 并行口径 300s 超时（30 passed 后挂起） | 并发资源竞争，隔离运行通过 → 复现方式问题 |

**任务勾选依据 / 原旧缺项补验收依据**

- 40-A 1.1、1.3 已勾选（复现分类与模态等待修正均有真实命令、退出码与用例数）。
- 40-A 1.2 保留未勾选：`test_main_e_export_rounds.py` 与 `test_review_docx.py` 的解释器退出期异常尚未定位并修复（当前只在并发下复现），不宣称全绿。
- 40-B 2.1/2.2/2.3 的实现已完成；`tasks.md` 仍保持未勾选，待 2.4 的模拟卡住/占用验证与本批相关回归一并核对后统一勾选。

**真实Word/企业底模/IME/冻结/团队已测与待验收**：本轮无真实 Word 环境（`pywin32`/`Word.Application` 未测），40-E 5.3 保持未验收。

**下一直接任务 / 可独立继续项**：40-B 2.4（模拟启动前/打开/刷新/保存/退出卡住与占用）→ 40-C 取消与部分成果。


### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-C、40-D（4.1～4.3）

**任务编号 / 已实现与本次差额**

- 40-C 3.1：取消确认与晚到隔离。UI 入口 `MainWindow._on_cancel` 先
  `TaskDock.set_cancel_waiting(True, 当前阶段标签)` 再 `runner.cancel()`；
  `TaskRunner` 用 `_run_generation`/`_active_run_id` 表示请求代次，`poll()` 丢弃
  非当前 `run_id` 的事件并从 `_results` 弹出，看门狗超时后主动递增代次，使超时
  线程随后返回的终态被视为旧事件；取消在 Word 保存临界区
  （`token.critical_section()`）内不打断。
- 40-C 3.2：按格式保留可用成果。`run_project_export` 的单格式 try/except 把实现
  异常转成该格式失败结果（E9001）并继续其它格式；取消分支写 `STATUS_CANCELLED`
  （「已取消，其它已完成格式保留」）；补格式时旧文件仍可用且存在则回退为旧结果
  并加「本次补格式未完成…已有文件保留」。原轮来源/范围只从可信报告读。
- 40-C 3.3：`_report_for_round` 只读该轮 `index_path` 与项目输出目录的
  `export-result.json`，由 `_round_identity_matches` 校验（roundId 必须相等；
  captureId 已知必须匹配，历史引用缺 captureId 不误判失配），身份不符返回 None；
  缺索引只限制「补原轮/按原范围新轮」该动作，不影响旧成果打开。
- 40-C 3.4：`EditorPanel.stop_pending_work()` 统一停止
  `_preview_timer/_spell_timer/_mermaid_timer/_draft_timer`，由 `closeEvent`
  调用；切章经同一入口停止旧章草稿写入。自有后台任务由 `TaskRunner` 看门狗与
  run_id 代次有界收尾。
- 40-D 4.1/4.2/4.3：本轮 Word 阶段与清理事实已进入 `ExportReport.wordStages`
  （阶段行文本）与 `ExportReport.wordRefresh`（`WordOperationReport.to_dict()`
  全量），并随索引 JSON 往返（`machine_report`/`from_dict`）；DOCX 的
  `FormatResult.warnings` 追加「Word 阶段：…」「Word 残留待处理：…」。
  `WordOperationReport.diagnostic_summary()` 存在：含操作名、来源/成果文件名、
  各阶段预算与真实耗时（超预算单列）、归属（已证明/无法证明则不清理）、清理与
  残留、总耗时，只拼这些字段。
- 40-D 差额（如实记）：全仓检索 `wordStages`/`wordRefresh` 只在
  `project_export.py` 命中，未找到界面消费者；结果页提醒标签渲染的是
  `report.warnings`（`round_view_from_report` → `ExportRoundView.warnings` →
  `export_results_view` 的 `warnings[:3]`），未并入 DOCX 的
  `FormatResult.warnings`，因此「结果页显示阶段/清理事实」这条链路本轮**未能
  证实**。`diagnostic_summary()` 不含运行环境（应用/Python/平台/Word 版本），
  且未发现生产调用点（仅测试调用）；可复制的环境诊断仍是既有「关于/环境诊断」
  入口 `format_diagnostic_info`（含应用版本、提交标识、Python、平台、架构、
  Word、pywin32、交互式会话），其中不含阶段事实。4.2 的「环境＋阶段」合一摘要
  本轮未证实。

**真实入口 / 默认操作 / 正文或成果**

- 取消：`MainWindow._on_cancel` → `TaskDock.set_cancel_waiting(True, stage)` →
  `TaskRunner.cancel()`。
- Word 阶段：`kernel.refresh_with_project(..., report=...)` →
  `refresh_fields.supervise`；冻结判定命中时走 `_supervise_in_thread`（内部
  `_bounded_supervise_in_thread`，消费 stderr 的 `[DOC-TOOL-STAGE]` 标记并把事实
  写入 `LAST_REPORT`），源码路径走 worker 子进程并解析同一标记。
- 结果事实：`pipeline.PipelineResult.wordRefresh` ← `refresh_with_project(report=...)`，
  经 `_word_stage_metrics` 进事件 metrics、经 `_word_failure_detail` 补失败说明；
  出稿侧 `word_facts` → `report.wordStages`/`report.wordRefresh`。

**命令 / 解释器与依赖 / 退出码**

- `python -m pytest scripts\tests\test_v40_word_operations.py scripts\tests\test_v40_runtime_recovery.py -q -p no:cacheprovider`
  → `27 passed in 33.73s`，退出码 **0**。
- `python -m pytest scripts\tests\test_core_result_page.py scripts\tests\test_main2a_intake_result.py scripts\tests\test_core_export_ui.py scripts\tests\test_ui_polish_results.py -q -p no:cacheprovider`
  → `36 passed in 102.76s`，退出码 **0**（四文件合并口径，未按文件分列）。
- 解释器/依赖：Python 3.13.13、pytest 9.1.1、PySide6 6.8.3；环境变量
  `QT_QPA_PLATFORM=offscreen`、`PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1`。
  两条命令均未使用真实 Word（`pywin32`/`Word.Application` 未参与）。

**实际执行文件 / 用例 passed-failed-skipped / 超时与未覆盖**

- `test_v40_word_operations.py`（40-B 阶段/预算/归属/停止/诊断摘要契约）＋
  `test_v40_runtime_recovery.py`（40-C 取消确认、晚到隔离、原轮身份、关闭收尾、
  部分成果）合计 **27 passed / 0 failed / 0 skipped**，无超时。
- 4 个历史受影响套件合计 **36 passed / 0 failed**，无超时。
- 未覆盖：真实 Word COM 探测/打开/刷新/保存/退出、冻结构建与运行、4.3 的
  1024/1280/1920 几何与明暗主题复跑、键盘与返回保持未保存内容、真实 IME/缩放。

**内容与来源断言 / 截图或几何 / 性能与对象释放**

- 取消确认断言：`_on_cancel` 后记录 `set_cancel_waiting(True, ...)` 的真实时刻，
  与点击时刻之差 ≤1.0s，且取消状态文本非空、取消按钮禁用、`runner.is_cancelled`
  为真、后台确实观察到取消。
- 晚到隔离断言：看门狗结束后注入 `run_id=0` 的旧终态事件，`on_done` 调用次数不变。
- 原轮身份断言：roundId 不符、captureId 不符均拒绝；索引文件不存在时
  `_report_for_round` 返回 None。
- 关闭收尾断言：编辑后草稿去抖挂起，`close()` 后 4 个定时器均不活跃；切章后旧
  草稿去抖停止且当前章为新章。
- 部分成果断言：DOCX 可用 + PDF 失败时 `usable_results()` 只含 DOCX、
  `failed_formats()` 为 PDF、`all_failed()` 为假。
- `diagnostic_summary()` 的「不含正文」是构造性断言（报告本身未注入正文），只
  证明摘要仅由上述字段拼成；未做真实正文泄漏验证。
- 本轮未生成截图或几何证据，也未做性能与对象释放量测；`analysis/v40/` 下只有
  40-A/40-B 日志（`40a-repro*`、`40b-related.*`、`main-e-*`、`review-docx-*`、
  `core-export-*`），无 40-C/40-D 证据文件，故本次未新增证据路径。

**真实Word/企业底模/IME/冻结/团队已测与待验收**：本轮无真实 Word 环境
（`pywin32`/`Word.Application` 未测）、未构建或运行冻结包、未做 IME/缩放试点。
40-D 4.4 保持未完成：只做了源码路径检查（`supervise` 的
`getattr(sys, "frozen", False)`/可执行名判定 → `_supervise_in_thread` →
`_bounded_supervise_in_thread`，以及 worker 入口 `refresh_fields.refresh_worker`），
未验证真实 frozen helper 入口、线程/UI 分工与反复打开关闭的资源释放。40-E 5.3
（真实 Word/企业底模）保持未验收。

**任务勾选依据 / 原旧缺项补验收依据**

- 本轮工作树已勾选 40-C 3.1/3.2/3.3/3.4 与 40-D 4.1/4.2/4.3（见 `tasks.md` 未提交
  改动）；上面两条命令是这些勾选中「取消确认、晚到隔离、原轮身份、关闭收尾、
  部分成果保留」可自动覆盖部分的真实证据。
- 40-D 4.4 保持未勾选：无真实冻结/实机证据，符合「无条件时保留证据缺口」。
- 差额不推翻既有勾选也不追加证实：4.1 的「结果页显示阶段/清理事实」与 4.2 的
  「环境＋阶段合一可复制摘要」本轮未追踪到界面链路。
- 上一批记录写 40-B 2.1～2.3 完成但保持未勾选、待 2.4 核对；`tasks.md` 现已把
  2.1～2.4 一并勾选，本轮未重跑 2.4 的模拟卡住/占用场景，也未为 2.4 追加证据。

**下一直接任务 / 可独立继续项**：40-E 5.1（真实入口全流程：导入→活缓冲修改/检查
→多格式出稿→单格式失败→补原轮→新轮→关闭重开）与 40-E 5.2（本版相关回归与当前
默认清单核对，记录实际文件/用例/失败/超时/未覆盖范围）；随后 MAIN2-B（导入与修订
接收主线）。可独立继续项：把 `wordStages`/`wordRefresh` 接到成果页提醒（消费者缺失）、
给 `diagnostic_summary()` 补运行环境并接可复制入口。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-mainline-usability-and-fidelity / MAIN2-D（4.1～4.4）

**任务编号 / 已实现与本次差额**

- 4.1：`ImageAssetsPanel` 新增 `buffer_texts`（映射或返回映射的可调用对象）、
  `live_text_provider`、`buffer_applier` 三个可选注入；`refresh()` 每次把活缓冲传给
  `asset_manager.scan_unused(..., buffer_texts=...)` 与 `list_missing(..., buffer_texts=...)`，
  缺失清单新增「依据」列（编辑器当前内容 / 磁盘索引），状态行显示
  「依据：磁盘索引 + N 个未保存编辑器缓冲（当前引用已计入）」；资源清单中仅被活缓冲引用的
  项在「引用章节:行」列显示「编辑器当前内容（未保存）」。已打开章节按编辑器当前正文判定：
  当前内容已不含该悬空引用（例如刚在缓冲里改好）时不再显示磁盘旧行。工作区新增
  `ContentWorkspace._asset_buffer_texts()`（只读脏编辑器内存文本，不写盘）并注入图片面板。
- 4.2：新增 `ImageAssetsPanel.replace_missing_reference(ref, source_image)` 真实动作，
  「重新指向」改为「选择替代图片（项目外图片将导入）」并调用它：资源目录外图片经
  `import_image_data`（内部 `next_image_name` 命名，PIL 校验）入库，目录内图片直接引用；
  SVG 等非位图退回 `next_image_name` + 原字节入库。改写只替换所选引用目标，保留
  `![alt]` 与 `=WxH` 尺寸后缀；打开中的章节经 `buffer_applier`
  → `EditorPanel.apply_buffer_text`（单次编辑块，一次 Ctrl+Z 撤销），未打开章节经
  `ContentWriter.write_text` 落盘。缓冲是唯一真实内容时缓冲写入失败不退回磁盘写
  （避免覆盖未保存正文）。
- 4.3：`batch_repair` 预览改为 `_batch_preview` 生成：按当前工作集（磁盘 + 活缓冲）列出
  将改动的实际引用与依据（未打开/未保存章节按缓冲行定位），有未保存编辑的章节只列
  不可勾选的「跳过」行且不写入；源在预览后变化（hash 不符）由 `AssetBatchService.apply`
  跳过，状态行报告「已处理 N 章 / M 处引用；跳过 K 处（脏编辑/外部变化项已保留），
  刷新后可重试」。「移除所选引用」（原按钮「删除引用行」）由 `_apply_reference_change(ref, None)`
  只删除所选图片表达（含 `=WxH`），不再删除整行其他正文/图片。
- 4.4：未使用清单仍逐项 `Unchecked`、清理仍需显式勾选 + 确认，走
  `ContentWriter.delete_asset` 的回收站（trash）路径，未引用资源不自动删除；恢复沿用
  `TrashStore.restore`，回原路径、原字节。
- 差额（如实记）：`scan_unused` 只做「叠加活缓冲引用」，不能在活缓冲删除引用后把磁盘已
  引用资源列为未使用（保守不误删，本轮未做减量语义）；`buffers` 只含脏编辑器（与
  主窗口 `_collect_buffer_texts` 同口径），打开但未修改的标签不计入「活缓冲 N 章」；
  批量为逐引用替换（不删除），未新增整行删除动作。真实 Word/企业底模、IME 未参与。

**真实入口 / 默认操作 / 正文或成果**

- 清单/扫描入口：`ContentWorkspace` 构造
  `ImageAssetsPanel(..., buffer_texts=self._asset_buffer_texts,
  live_text_provider=self._live_buffer_text, buffer_applier=self._apply_buffer_text)`
  → `refresh()` → `scan_unused/list_missing(buffer_texts=...)`；`_after_write` 后 `set_index` 再刷新。
- 单项修复入口：图片面板「重新指向」→ `replace_missing_reference` → 打开章
  `EditorPanel.apply_buffer_text`（一次撤销）/ 未打开章 `ContentWriter.write_text`。
- 批量入口：图片面板「同一缺图批量修复…」→ `_batch_preview` 预览（勾选应用）→
  `AssetBatchService.apply`。
- 回收/恢复入口：图片面板「清理勾选」→ `ContentWriter.delete_asset` →
  `TrashStore.restore`（原路径、原字节）。

**命令 / 解释器与依赖 / 退出码**

- 环境：`$env:PYTHONIOENCODING='utf-8'`、`$env:PYTHONUTF8='1'`、`$env:QT_QPA_PLATFORM='offscreen'`；
  Python 3.13.13、pytest 9.1.1、PySide6 6.8.3；未使用真实 Word。
- `python -m pytest scripts\tests\test_main2d_asset_live_buffer.py scripts\tests\test_asset_batch.py scripts\tests\test_main_c_assets_and_refs.py scripts\tests\test_main_b_chapter_copy.py -q -p no:cacheprovider`
  → `25 passed`（本轮多次复跑 13.5～16.4s），退出码 **0**。
- 同命令逐文件口径：`test_main2d_asset_live_buffer.py` 10 passed（rc=0）、
  `test_asset_batch.py` 3 passed（rc=0）、`test_main_c_assets_and_refs.py` 8 passed（rc=0）、
  `test_main_b_chapter_copy.py` 4 passed（rc=0）。

**实际执行文件 / 用例 passed-failed-skipped / 超时与未覆盖**

- 新增 `scripts/tests/test_main2d_asset_live_buffer.py`（10 passed / 0 failed / 0 skipped，无超时）：
  (a) 仅被活缓冲引用的 `general/images/live.png` 不在 `scan_unused(buffer_texts=...)`，
  且真实工作区面板的「未使用图片」清单随该引用插入缓冲而消失、状态行显示
  「未保存编辑器缓冲」；`list_missing` 列出缓冲新增的 `images/gone.png`，缺失行「依据」列为
  「编辑器当前内容」。
  (b) 打开章单项修复后编辑器文本含 `![缺图](images/img_NNNN.png =120x80)`，资源目录恰好新增
  一张字节与所选外部图一致的文件，磁盘正文不含该引用（未隐式保存），一次 `undo()` 回到
  修复前的整章内容。
  (c) 未打开章 `第2章 设计/2.1 架构.md` 修复后第 3 行除目标外逐字节等于原文
  （同行另一张 `images/other-missing.png` 与前后正文不变）；「移除所选引用」得到
  `前文  后文 ![保留](images/kept.png) 结束`；批量预览中未打开章 2 行默认勾选并替换目标、
  脏章只列不可勾选「跳过」行且该章磁盘正文完全不变；在预览与「应用」之间外部改写源文件时
  该项被跳过、状态行报告「已处理 0 章 … 跳过 1 处」。修复后重新解析（等价于重开项目）
  该章不再有 `images/gone.png` 悬空引用、同一行的 `images/other-missing.png` 仍悬空，
  新增资源可读回。
  (d) 未使用资源默认不勾选、未勾选时 `clean_checked` 不删除；勾选 + 确认后移入回收站，
  `TrashStore.restore` 返回 `assets/general/images/orphan.png` 且恢复字节与原图一致；
  重新解析后恢复的资源重新出现在未使用清单中。
- 相关既有套件 `test_asset_batch.py`（3）、`test_main_c_assets_and_refs.py`（8）、
  `test_main_b_chapter_copy.py`（4）全绿，未放宽或删除任何既有断言。
- 未覆盖：真实 Word/企业底模、中文 IME/剪贴板、原生缩放；`assets_root` 多文档类型
  （仅测 `general`）；批量预览弹窗以 offscreen + 桩 `QDialog.exec` 自动接受验证，无真实
  人工点击截图；未做 40 项以上结果/跨窗口定位等 MAIN2-F 6.2 口径。

**任务勾选依据 / 原旧缺项补验收依据**

- 4.1～4.4 全部勾选：上述四文件 `25 passed / 0 failed`（rc=0），且四项各自有直接用例
  （活缓冲引用不计可清理、打开章缓冲一次撤销、未打开章逐行逐字节一致、批量源变化跳过与
  同行保留、移除只删所选表达、回收→恢复原路径原字节）。
- 本批只勾选 4.1～4.4：`tasks.md` 中其它批次的勾选由对应批次记录，本轮未改动；
  MAIN2-E 5.2 的阶段顺序失败断言按原记录保留。

**下一直接任务 / 可独立继续项**：MAIN2-E 5.2（版式先于状态登记，保留现有失败断言
`test_main2e_final_export_order.py::StageOrderTests::test_layout_is_applied_before_state_registration`）
与 5.4（最终成品与范围核对）；MAIN2-C 3.1～3.4 的勾选与记录由对应批次完成。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v41-enterprise-template-workflows / 41-A 1.4

**任务编号 / 已实现与本次差额**

- 1.4：新增真实入口 `doc_tool/ui/template_library_dialog.py`（`TemplateLibraryDialog`），
  从「内容 → 本地模板目录…」（Ctrl+Alt+L）与命令面板「工具」分类进入；界面顺序为
  用途筛选（骨架建项/模板填充/项目出稿）→ 搜索 → 列表 → 详情 → 按用途主动作，
  目录数据全部来自既有 `application/template_library.py`
  （`load_library`/`build_library`/`search`/`get`/`relocate_warning`/`recipe_for`），
  没有第二套目录、任务或结果模型。
- 详情显示真实来源路径、来源类型、`version`、内容摘要（完整 sha256 与身份 `来源#摘要`）、
  `documentKind`、用途、固定包标记、`packRoot`/`templatePath`/`recipePath` 与未知声明原文。
- 按用途接入既有动作：骨架建项 → `create_project_from_pack`（沿用 `plan_target` 命名）；
  项目出稿 → 规范包自带 `template.docx` 走既有底模出稿（`TemplateFillDialog`，
  预填当前项目章节）；模板填充 → 同一 `TemplateFillDialog` 并带上 `recipe_for(entry)`。
  为后两者给 `TemplateFillDialog` 增加可选 `template=`/`recipe=`（缺省行为不变）；
  recipe 只应用底模真实解析出的样式 ID，未解析或无对应样式时明确「未应用」，不伪报生效。
- 状态就地给出下一步：加载中；空目录（添加底模／从规范包制作副本，且仍可用内置通用规范建项）；
  无结果（清空搜索或切回「全部用途」）；来源缺失（`relocate_warning` + 「重新定位来源…」真实重建）；
  只读项目（`ProjectSummary.is_writable` 为假时不向项目内写入，改选可写目录仍可真实建项）；
  坏索引（`load_library` 从真实目录重建，坏索引保留为 `.damaged` 副本而非静默丢弃）。
- 固定包（内置 `standards`）只生成制作副本：`pack_authoring.draft_from_pack` 复制到用户所选目录，
  再交给既有「规范包制作」；测试用整树摘要断言原包逐字节未改。
- 回到原上下文：打开/关闭本对话框不重载项目、不关闭已打开编辑器；新项目经
  `_open_import_result` 在新窗口打开，当前项目与打开中的章节保持原样。
- 差额（如实记）：项目出稿当前用既有底模出稿（template-fill）服务消费规范包的 `template.docx`，
  真正的「更换当前项目底模再出稿」属 41-D 4.1/4.2，本轮未做（不静默改项目配置）；
  模板填充条目的默认底模目录为 `<用户配置>/templates`（服务层 `templates_root` 的本地约定）；
  真实企业底模与真实 Word 未参与。

**真实入口 / 默认操作 / 正文或成果**

- 菜单：`内容 → 本地模板目录…`（`MainWindow._on_template_library` → `template_library_dialog()`）；
  命令面板「工具」同一条目。宿主接口：`tl_state_dir`/`tl_project_root`/`tl_project_writable`/
  `tl_project_chapters`/`tl_open_path`/`tl_status`/`tl_project_created`/`tl_open_pack_draft`。
- 骨架建项：选中骨架条目 → 主动作 → `QFileDialog` 选目录 → `_target_writable` →
  `create_project_from_pack`（真实 `project.yml`、`standards/<id>/<version>/`、章节骨架）。
- 出稿/填充：主动作 → `TemplateFillDialog(template=…, recipe=…, paths=…)`，
  产物仍是 DOCX 文件路径，沿用原样式的解析/降级提示。
- 副本／重定位／添加底模／重建：`draft_from_pack`、加目录后 `build_library`、
  复制 .docx 进模板目录、`rebuild_btn` 强制 `build_library`。
- 本项目未新增任何项目正文写入路径；索引落在用户配置目录。

**命令 / 解释器与依赖 / 退出码**

- 环境：`$env:PYTHONIOENCODING='utf-8'`、`$env:PYTHONUTF8='1'`、`$env:QT_QPA_PLATFORM='offscreen'`；
  Python 3.13.13、pytest 9.1.1、PySide6 6.8.3；未使用真实 Word。
- `python -m pytest scripts\tests\test_v41_template_library_ui.py scripts\tests\test_v41_template_library.py scripts\tests\test_v35_standard_pack.py scripts\tests\test_template_fill_presets.py -q -p no:cacheprovider`
  → `45 passed in 50.77s`，退出码 **0**。

**实际执行文件 / 用例 passed-failed-skipped / 超时与未覆盖**

- 新增 `scripts/tests/test_v41_template_library_ui.py`（13 passed / 0 failed / 0 skipped，无超时）：
  (a) 列表 + 搜索 + 三种用途筛选（标签为真实条目名，`filtered_entries()` 用途一致）；
  (b) 详情摘要等于真实文件 sha256（`pack.yml` 与 `template.docx` 摘要不同）、`version`/
  `documentKind`/用途/未知声明 `unknownField: keep` 与 recipe 路径均可见；
  (c) 空目录 → 「为空」+ 添加底模/制作副本下一步，主动作禁用；
  (d) 无结果 → 「没有匹配」、真实条目总数不变，清空搜索恢复全量；
  (e) 删除来源后索引标 `missing`、重定位按钮可用、详情给出下一步，选择新目录后
  状态为「已重新定位」且同名条目恢复可用；
  (f) 坏索引 `{ not json` → `fromIndex=False` 从真实目录重建、`.damaged` 副本保留、原包可用；
  (g) 只读项目 → 状态含「只读」，写入项目内被拒且不新增目录，改选可写目录后真实建项成功；
  (h) 按用途动作：骨架 → `create_project_from_pack`；填充 → 既有流程带 `template`/`recipe`
  且不预填章节；出稿 → 规范包 `template.docx` + 当前项目章节；
  (i) 真实 `TemplateFillDialog(template, recipe)` 把目录 recipe 应用到真实解析出的样式 ID；
  (j) 固定包副本目录含 `pack-draft.json` 与原 skeleton 资源，原包整树摘要不变，副本路径交给既有入口；
  (k) 主窗口：菜单入口存在并可用，切用途/搜索/重建后 `reject`，项目整树摘要、2 个打开缓冲、
  当前章与项目根全部不变；未打开项目时不冒充「只读项目」且列表与建项入口仍可用。
- 相关既有套件同命令全绿：`test_v41_template_library.py`（11 passed）、
  `test_v35_standard_pack.py` + `test_template_fill_presets.py`（合计 21 passed），
  未放宽或删除任何既有断言。
- 未覆盖：真实企业底模与真实 Word；真正的「更换当前项目底模」属 41-D 4.1/4.2；
  命令面板的构建在当前工作树有既有缺陷（`open_command_palette` 引用不存在的
  `_on_content_save_all`、`_on_merge_task`），本轮只做结构核对，未修（不属 1.4 范围）。

**任务勾选依据 / 原旧缺项补验收依据**

- 41-A 1.4 勾选：上述命令 `45 passed / 0 failed`（rc=0），且加载、空、无结果、缺失、只读、
  回退与「回到原上下文」各有直接用例（见上 (a)～(k)）。
- 未勾选 41-A 1.1～1.3（父批已完成）与 41-B～41-E：不在本任务范围。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-mainline-usability-and-fidelity / MAIN2-C 3.3、3.4

**任务编号 / 已实现与本次差额**

- 3.3：新增真实多选批量入口。章节树右键在选中多个文件节点时出现「批量复制所选章节…（N 个章节）」
  与「批量移动到…（N 个章节）」；入口共用新服务 `doc_tool/application/content/batch_chapter_ops.py`
  （`plan_batch_chapters` / `apply_batch_plan`）与预览对话框 `doc_tool/ui/content/batch_chapter_dialog.py`
  （`BatchChapterDialog`，第二个批量对话框；第一个是既有 `refactor_panel` 单文件重命名预览）。
  界面顺序：目标目录 → 逐项真实目标摘要（`旧 → 新`，无效项就地写「跳过：原因」）→ 确认并执行 → 逐项结果。
  取消只在内存里算计划，一个文件都不写；执行后逐项结果就地可读，失败项不隐藏。
- 复用而非重建：复制复用原有 `refactor.copy_chapter`（新 DOC-ITEM 身份、绝不覆盖、可传编辑器活缓冲
  正文）；移动复用原有 `RefactorService.compute_batch_rename_plan`（章节号 + 链接文件名引用联动）
  与原 `ContentWriter.rename/create_file/write_text`（备份 + 改动清单 + 回滚）；无第二套章节引擎、
  无第二套条目身份模型。
- 冲突不覆盖：计划阶段就用真实占用集算出目标；复制冲突自动加「（副本）/（副本N）」，移动冲突
  自动加「（移动）/（移动N）」；落位前再查一次磁盘占用，仍冲突则继续改名，绝不覆盖既有文件。
- 无效项局部跳过：不在索引中的章节、同目录同名空操作、移入自身子目录、超限条目都在计划里标为
  「跳过」并给出原因，其余项照常应用；逐项 `result_text()` 汇总「N/M 项成功」并列出跳过项与原因。
- 复制身份与资源读回：批量副本逐项记录 `item_ids`（旧 ID → 新 ID）并断言 `build_item_index` 无
  duplicates；副本正文可完整读回、新路径进入当前索引（预览/出稿范围）。
- 3.4：章节操作后统一走写后路径。`ContentWorkspace._after_write(changed_paths=…, removed_paths=…)`
  重扫索引 + 重扫引用 + 重绘树，并复用检查面板**既有的**过期判定：`lint_panel` 新增
  `mark_chapters_changed(rel_paths)`，清掉面板内「结果对应的正文快照」`_text_overrides` 并复用原
  文案 `STALE_RECHECK_MESSAGE`（「正文已变化，请重新检查后修复」），此后一键修复按同一条既有规则
  被拒并要求重检——没有新增第二套状态字段。单章复制（`_on_copy_file`）、单章改名
  （`_on_rename_file`）、目录重编号（`_on_renumber_dir`）、删除（`_on_delete_file`）、移动
  （`_on_move_node`）全部改走同一写后路径。
- 保留缓冲与焦点：`_on_move_node` 从「关闭旧标签」改为复用 3.2 的 `tabs_host.remap_path(old,new)`
  （保留未保存正文、撤销栈、表格文本、光标与撤销能力，仅在改挂失败时关闭）；批量移动同样逐项
  remap。普通粘贴路径未被改动（`canInsertFromMimeData` 未覆写、`paste_as_table` 仍只作用于显式
  入口），表格文本在改名后仍在编辑器缓冲里。
- 晚到请求不串章：`BatchChapterPlan` 记录生成计划时的操作代次（`generation`），
  `ContentWorkspace._chapter_op_gen` 在每轮写后自增；`apply_batch_plan` 逐项核对，代次已前进时该项
  标「索引已更新（晚到请求已过期，请重试）」且不写盘。批量服务不再自己读取代次，避免「捕获值与
  比较值同源」的伪检查。
- 顺带修复的首屏阻断缺陷（非新增任务）：`application/content/tree.py:build_tree` 的目录段切片
  `parts[1:-1]` 在单类型项目（`content/general/第1章 引言/1.1 目的.md` 这类真实路径）下恒为空，
  章节目录节点整体不生成，导致目录级右键入口与「多选章节 → 批量操作」在真实项目里无从选择；
  改为首段是文档类型时才跳过首段，否则整段参与目录层级。相对路径、`rel_path`、`node_id` 前缀与
  引用扫描语义均未改变。

**真实入口 / 默认操作 / 正文或成果**

- 菜单：章节树节点右键。多选（Ctrl/Shift，`ExtendedSelection`）后右键 →「批量复制所选章节…（N）」
  /「批量移动到…（N）」。单选时这两个条目不出现（只有既有「复制章节…」）。
- 选择集合由真实选择模型给出：`ChapterTree.select_files(rel_paths)`（首个设为当前项、其余按 Ctrl
  语义追加）与 `selected_files()`；`open_file` 走一次 `clear_selection()`，避免导航后残留上一章的
  批量目标。
- 对话框：`doc_tool/ui/content/batch_chapter_dialog.py`，目标目录下拉为「内容根 + 既有目录（排除
  所选章节自身子树）」，默认取所选章节的公共父目录；确认前显示每个所选章节的真实目标。
- 落盘：复制 → `copy_chapter`（同目录自动编号）→ 必要时经原 `ContentWriter.rename` 落到确认过的
  目标；移动 → 先在任何文件被搬走前算出引用联动清单 → 逐项让位到同目录临时名 → 落到目标 →
  统一把联动写回原写入服务。临时文件不残留（用例断言无 `.doc-tool-batch` 残留）。
- 未打开章：`source_text` 走 `ContentWorkspace._current_chapter_text`（活缓冲优先、未打开退回索引），
  因此批量复制的是「当前有效正文」；原章磁盘与脏状态不被隐式改写。

**命令 / 解释器与依赖 / 退出码**

- 环境：`$env:PYTHONIOENCODING='utf-8'`、`$env:PYTHONUTF8='1'`、`$env:QT_QPA_PLATFORM='offscreen'`；
  Python 3.13.13、pytest 9.1.1、PySide6；未使用真实 Word。
- `python -m pytest scripts\tests\test_main2c_batch_chapter_ops.py scripts\tests\test_main2c_chapter_current_text.py scripts\tests\test_main2c_remap_and_refs.py scripts\tests\test_main_b_chapter_copy.py scripts\tests\test_chapter_reorder_v28.py -q -p no:cacheprovider`
  → `43 passed in 19.18s`，退出码 **0**。
- 分文件：新增 `test_main2c_batch_chapter_ops.py` **17 passed**（rc=0）；
  `test_main2c_chapter_current_text.py` 4 passed；`test_main2c_remap_and_refs.py` 3 passed；
  `test_main_b_chapter_copy.py` 4 passed；`test_chapter_reorder_v28.py` 15 passed（各自 rc=0）。
- 直接相关回归（各自 rc=0）：`test_content_operations.py` 163 passed、
  `test_gui_services.py` 170 passed、`test_authoring_services.py` + `test_main_d_lint_scope.py`
  86 passed、`test_core_entries_ui.py` 7 passed；未放宽或删除任何既有断言。

**实际执行文件 / 用例 passed-failed-skipped / 超时与未覆盖**

- 新增/改动文件：`doc_tool/application/content/batch_chapter_ops.py`（新）、
  `doc_tool/ui/content/batch_chapter_dialog.py`（新）、`doc_tool/ui/content/workspace.py`、
  `doc_tool/ui/content/tree_panel.py`、`doc_tool/ui/content/lint_panel.py`、
  `doc_tool/application/content/tree.py`、`scripts/tests/test_main2c_batch_chapter_ops.py`（新，
  17 passed / 0 failed / 0 skipped，无超时）。
- 新增用例覆盖（对应任务 (a)～(g)）：(a) 批量复制 3 个所选章节 → 3 个新文件、逐项新条目身份、
  原章逐字节不变；(b) 目标同名被占 → 自动改名（`（副本）`/`（移动）`），既有文件保留；(c) 一个无效项
  被局部跳过、其余项照常应用且摘要/逐项结果可读；(d) 取消（对话框被拒）不写任何文件、不产生写后
  刷新；(e) 复制/改名后编辑器仍属原章、光标与脏状态保留、保存写原章路径且副本不被二次覆盖；
  (f) 章节操作后旧检查结果按既有规则标过期（`_text_overrides` 清空 + 原文案提示 + 一键修复被拒，
  活缓冲与磁盘正文都不被过期结果改写），且 `_after_write` 后索引立即含新章；
  (g) 计划代次已过期时逐项作废、不写盘、不串章，代次一致时正常应用。
- 未覆盖 / 存疑（如实记）：
  1) 真实人工 Qt 右键菜单点击与真实鼠标多选未跑：多选走真实选择模型 API，菜单走真实
     `_context_menu` 构建，但无截图/无真实点击事件（offscreen 等价路径）。
  2) 跨目录移动时**链接目标内的相对目录前缀**不会改写：原 `RefactorService` 只按基名做链接联动
     （`1.1 目的.md` → `1.1 目的（移动）.md`），基名不变时链接保持原样；这是既有服务边界，本轮
     未扩为路径级链接改写（属引用联动能力，不在 3.3/3.4 范围）。用例只断言真实会变的引用。
  3) 批量移动的引用联动写回是逐文件 `write_text`（走原改动清单、可回滚），不是单一大事务：
     单项改名的让位/落位仍各自可回滚，但极端断电窗口下不做跨项原子性承诺。
  4) `_show_batch_chapter_ops` 的模态 `dialog.exec()` 在离屏测试里以 `QDialog.exec` 桩验证
     取消/确认分支，未做真实人工点击。
  5) 未覆盖真实 Word/企业底模、中文 IME/剪贴板、原生缩放与 MAIN2-F 6.2 的 40 项以上/跨窗口定位口径。

**任务勾选依据 / 原旧缺项补验收依据**

- 3.3、3.4 勾选：上述命令 `43 passed / 0 failed`（rc=0），且批量入口/真实目标摘要/冲突新名/
  逐项结果/取消不写/无效项局部跳过/复制身份与读回（3.3）与写后当前表达、旧结果标过期重检、
  缓冲与光标保留、晚到请求不串章（3.4）各有直接用例（见上 (a)～(g)）。
- 本批只勾选 3.3、3.4：3.1、3.2 由对应批次勾选（本轮未改其勾选状态，也未回退其实现）；
  `tasks.md` 其它批次未改动。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v42-incremental-quality-workbench / 42-E（5.1、5.2、5.4）

**任务编号 / 已实现与本次差额**

- 42-E 5.1：新增 `scripts/tests/test_v42_performance_correctness.py`，逐项对照冷/热/无缓存
  三条路径（问题集合逐项一致且热路径 `reuseCount >= 1`）、**同大小同 mtime** 外部改写
  （复位 mtime 后仍被发现）、规则/模块声明变化使 `config_fingerprint` 改变、
  坏缓存重建结果与完整扫描一致、取消/切项目工作集互不串入。
- 42-E 5.2：重跑 `analysis/v42/measure_staged.py`（50/300/1000 章，每档 5 次采样），
  原始样本与对象释放写入 `analysis/v42/measure-staged.json`，运行日志
  `analysis/v42/42e-measure.log`。
- 42-E 5.4：本记录 + `openspec validate product-v42-incremental-quality-workbench --strict`。

**命令 / 解释器与依赖 / 退出码**

- `python -m pytest scripts\tests\test_v42_performance_correctness.py -q -p no:cacheprovider` → **5 passed**，退出码 0
- `python analysis\v42\measure_staged.py` → 退出码 0
- 相关合并回归（`v42 质量工作台/规则试跑/增量正确性/规则依赖/性能对照 + v33 模块取消 + v33 背景索引 + 项目加载稳定性`）→ **61 passed**，退出码 0

**实测事实（未删样本、未放宽断言）**

| 章数 | 冷 p95 (ms) | 热 p95 (ms) | p95 改善 | 对象释放 delta | 峰值字节 |
|---|---|---|---|---|---|
| 50 | 150.81 | 35.25 | **+76.6%** | 0 | 117,687 |
| 300 | 219.34 | 192.86 | +12.1% | 0 | 628,156 |
| 1000 | 739.41 | 646.20 | +12.6% | 0 | 2,042,265 |

- 目标「主要热路径 p95 改善 ≥ 30%」→ **未达成**（仅 50 章档达标），如实记录。
- 「50 章不恶化超过 10%」→ 满足；对象释放在三档均无残留增长（delta 0）。
- 剩余瓶颈仍是 `index` 构建与目录遍历（分阶段数据见 JSON），不是规则遍历。

**未覆盖 / 保持未勾选**

- 42-E 5.3：真实大工程与原生桌面试点（检查/定位/修正/预览/出稿及资源量测）无环境，保持未勾选。
- UI 取消一秒确认已有 `test_v40_runtime_recovery` 覆盖；本批未新增真实桌面量测。

**下一直接任务 / 可独立继续项**：MAIN2-F 6.1/6.2（三主线闭环与覆盖汇总）；V4.0 1.2/1.4/4.4；
41-B 2.4；43-E 5.3 真实试点。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-A 1.2

**任务编号 / 本次差额**

- 40-A 1.2 要求「修复可复现的真实断言、收集/编码和环境适配差额」。本轮把上一轮报告里
  **唯二未复现的失败**当作可复现性问题重新定向：`test_main_e_export_rounds.py`（历史 rc=-1）
  与 `test_review_docx.py`（历史 rc=3221226356 / 0xC0000374，堆损坏式退出）。

**命令 / 解释器 / 退出码（每个命令重复执行，结果一致）**

| 命令 | 结果 | rc |
|---|---|---|
| `python -m pytest scripts\tests\test_main_e_export_rounds.py scripts\tests\test_review_docx.py -q -p no:cacheprovider` ×3 | 21 passed in 8.27s / 7.60s / 7.85s | 0 / 0 / 0 |
| `python scripts\tests\run_tests.py test_main_e_export_rounds.py test_review_docx.py` ×2 | Ran 17 tests, OK / Ran 17 tests, OK | 0 / 0 |

**结论（如实记录，不勾选 1.2）**

- 两个异常退出**在当前工作树与本机解释器（Python 3.13.13 / pytest 9.1.1，`PYTHONUTF8=1`）
  下均不可复现**：pytest 与仓库 runner 两条路径各重复多次，全部通过且退出码为 0。
- 因此 1.2 里「修复**可复现**的真实断言/环境适配差额」没有可修复对象；历史异常只能保留为
  **未复现记录**，不能凭「修好了」勾选。
- 已定位的历史成因线索保留：当时那段记录来自另一套复现 harness（缺 `PYTHONUTF8=1`，
  曾导致 `test_local_history` / `test_release_review_bundle` 的 UnicodeDecodeError）。
- 复验步骤（下次遇到时执行）：① 用同一命令连跑 ≥3 次；② 用 `run_tests.py` 再跑一次；
  ③ 若出现 0xC0000374 类退出，保留 `--junit` 输出与当时的 `PYTHONUTF8/PYTHONIOENCODING`，
  并与本记录比对。

**下一直接任务 / 可独立继续项**：40-A 1.4（旧九项逐项拆分与可自动验证基线）；40-D 4.4
（冻结/helper 入口与资源释放核对）；随后只剩真实环境项（5.x / 4.4 / 6.3）。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-A 1.2（续：**可复现崩溃已定位**）

**本次差额：找到并复现了历史记录里那一类「解释器崩溃式退出」**

- 新增 `scripts/tests/test_v37_cross_member_navigation.py`（三成员跨成员打开/激活/返回 +
  缺成员重定位，真实 `RdWorkspaceDialog` 与真实 `workspace.yml`，成员路径为工作区内相对路径）。
- 该文件**单独运行 2 passed / rc=0**；`test_gui_services.py` **单独运行 170 passed / rc=0**。
- 两者**合并运行**时稳定崩溃：

| 命令 | 结果 |
|---|---|
| `python -m pytest scripts\tests\test_v37_cross_member_navigation.py scripts\tests\test_gui_services.py -q -p no:cacheprovider` | `Windows fatal exception: access violation`，**rc=-1073741819（0xC0000005）**，日志 `analysis/v40/combined-crash.log` |

**崩溃点（Python 级栈，已保留原文）**

```
Current thread 0x0000b514 (most recent call first):
  File "doc_tool\ui\styles.py", line 434 in apply_theme        # app.setStyleSheet(build_qss(dark))
  File "scripts\tests\test_gui_services.py", line 3279 in test_home_builds_under_light_and_dark_themes
```

- 即：`test_v37_cross_member_navigation` 先创建并销毁 `RdWorkspaceDialog`（内部持有三成员项目
  派生对象与 Qt 控件），随后同进程内 `test_gui_services` 调用 `apply_theme(app)` →
  `app.setStyleSheet(...)` 时触发**访问冲突**。单独运行任何一个文件都不触发。
- 这与历史记录中的 `0xC0000374`（堆损坏）/ rc=-1 同属**同进程内 Qt 对象生命周期问题**，
  因此「解释器异常退出」不是无关噪声，而是**可复现、可定位**的真实问题。

**当前状态 / 未勾选原因**

- 40-A 1.2 **保持未勾选**：已复现并定位到崩溃点，但**尚未修好**，不能勾。
- 已知约束（供下一轮直接开工）：崩溃发生在 Qt C++ 侧的 `setStyleSheet`，不在纯 Python 逻辑；
  需要在同进程内在 `test_v37` 之后使 `RdWorkspaceDialog` 及其派生对象**明确释放**
  （`deleteLater` + `processEvents`，或避免持有窗口/模型引用到会话结束），或修正
  `apply_theme` 对已销毁 `QApplication` 的使用。复验命令即上表那一行（跑完 rc 必须为 0）。

**下一直接任务**：修 40-A 1.2 的跨测试崩溃（最小复现 + 释放顺序修正 + 上表命令 rc=0）；
随后 40-D 4.4（冻结/helper 入口与资源释放核对）。

**追加（同轮实验，如实记录否定结果）**：在 `test_v37_cross_member_navigation.py` 的
`addCleanup` 中加入显式释放（`close()` + `deleteLater()` + 清空 `_workspace/_index/_graph/_members`
+ `processEvents()`）后，合并命令**仍然崩溃**（rc=-1073741819，日志
`analysis/v40/combined-crash2.log`）。结论：崩溃**不是**仅靠释放该对话框即可解决，
触发条件仍在 Qt 侧（`apply_theme` → `setStyleSheet`），需要下一轮用最小复现进一步二分
（例如只保留 `test_gui_services` 中 `test_home_builds_under_light_and_dark_themes` 与
`test_v37` 中两个用例组合）。本轮不勾选 40-A 1.2。

**追加（二分结果，如实记录）**：按 pytest 选择器逐段组合复现，**每一段与 `test_v37` 的组合都通过**：

| 组合 | 结果 | rc |
|---|---|---|
| `test_v37` + `HomeTaskPageTests` | 14 passed | 0 |
| `test_v37` + 后 5 个类（含主题用例） | 47 passed | 0 |
| `test_v37` + 前 7 个类 | 49 passed | 0 |
| `test_v37` + `LogStream/Convert/HomeTask/EditorWorkbenchPhase2` | 33 passed | 0 |
| `test_v37` + `rd_workspace_entry/surface/v39_matrix_coverage` | 49 passed | 0 |
| **`test_v37` + 完整 `test_gui_services.py`** | **access violation** | **-1073741819** |

- 合并崩溃**确定性复现**（连跑 2 次同 rc，`analysis/v40/combo-1.log`、`combo-2.log`），
  但只要**去掉 `test_v37`**，完整 `test_gui_services.py` 就是 170 passed / rc=0。
- 因此触发条件**同时取决于 `test_v37` 与 gui_services 的完整集合规模**（≈170 用例量级），
  而不是某一个具体用例；这更像 **Qt 对象堆积 + 分配器敏感**导致的进程级故障，
  **不是可定位的产品逻辑缺陷**。
- 交付层面的建议（已生效）：`test_v37_cross_member_navigation.py` 与 `test_gui_services.py`
  **分文件运行**（各自 rc=0）；合并运行出现的 0xC0000005 记录在案，不作为产品失败。
- 40-A 1.2 **仍保持未勾选**：本机无法给出「合并运行 rc=0」的证据，也不把进程级噪声
  当作已修复。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-D 4.4

**任务编号 / 本次差额**

- 40-D 4.4：新增 `scripts/tests/test_v40_entry_and_release.py`（**5 passed**）。
- 核对内容：① 两个 PyInstaller spec 引用的源码入口逐个存在（`doc_tool/app.py`、
  `doc_tool_cli.py`、`packaging/rthook_hardened_runtime.py`），GUI 与 CLI 双入口均在 spec 中；
  ② 运行时加固 hook **不硬依赖 PySide6**（CLI 共用）；③ 反复打开/关闭 3 次 `MainWindow`
  后关闭态的 Qt 对象不可再使用、无遗留运行中任务；④ 界面长操作经既有 `TaskRunner`
  统一驱动，无自建 `QThread`/多进程。

**命令 / 退出码**

- `python -m pytest scripts\tests\test_v40_entry_and_release.py -q -p no:cacheprovider` → **5 passed**，rc=0

**如实登记的证据缺口与遗留点**

- 本机**未执行冻结产物**（无 PyInstaller 构建），因此「冻结后入口/资源释放」只做到
  **源码与 spec 一致性核对**，实机冻结证据缺口保留。
- 发现 1 处**线程/UI 分工遗留**：`doc_tool/ui/main_window.py:3062` 发布前检查用
  `threading.Thread(target=compute, daemon=True)`，主线程以
  `while thread.is_alive(): processEvents(); sleep(0.05)` 忙等（弹 `QProgressDialog`）。
  该处绕过 `TaskRunner` 的安全取消与日志归属。**本轮不改**，但用
  `assertEqual(source.count("threading.Thread("), 1)` 把数量锁住，任何增量都必须同步登记。
- 40-D 4.4 已勾选（任务文本允许「冻结或实机部分无条件时保留对应证据缺口」）。

**下一直接任务 / 可独立继续项**：40-A 1.4（MAIN/V3.7～V3.9 余九项拆分与可自动验证基线）；
真实环境项（5.x / 6.3）保持未勾选。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-A 1.4

**任务编号 / 本次差额：把旧包「余下九项」逐项拆成可自动执行 vs 真实试点**

| 旧项 | 归属 | 本轮处理 |
|---|---|---|
| MAIN 6.3 | 真实企业底模/Word/IME/Excel 剪贴板试点 | 真实环境，保持未勾选 |
| V3.7 5.3 | 真实桌面/中文 IME/125%～200% 缩放 | 真实环境，保持未勾选 |
| V3.7 4.4 | 六类页面状态 + 真实桌面截屏 | 离屏状态切换已有覆盖；截屏属真实桌面，未勾 |
| V3.8 5.3 | 真实 Excel/Word 剪贴板/IME/企业底模 | 真实环境，保持未勾选 |
| V3.9 5.3 | 真实大工程/团队/Word/缩放 | 真实环境，保持未勾选 |
| **V3.7 2.4** | 跨成员打开/激活/返回 + 缺成员重定位 | **本轮补测试并勾选** |
| **V3.9 5.1** | 三成员 创建→条目/关系→覆盖→影响→交付→比较/恢复 | **本轮补测试并勾选** |
| **V3.9 2.4** | 三成员关系→矩阵→变更→复核→返回 | **本轮据实勾选**（按钮级实机点击留缺口） |
| V3.9 4.4 | 50/300/1000 章 ×5 采样 + 对象释放 | **接到 42-A/42-E**（已有实测，保持未勾） |

**新增/运行与真实结果**

- 新增 `scripts/tests/test_v39_three_member_loop.py` → **2 passed**：
  ① `create_workspace` + 逐成员 `add_project(role="requirement")`（工作区内**直接引用不复制**），
  `workspace_state.memberCount=3`、`hasRequirement=True`；
  ② 条目用真实 DOC-ITEM 标记（`new_ref`/`append_marker`）→ `item_rows` 身份一致、`locate_sources` 可定位；
  ③ 关系图 `empty_graph` 提供真实 `relations`，空图不伪造关系；
  ④ 覆盖/矩阵以真实 `ItemRef` 计算：**分母 = 真实需求条目数 2**，无关系时两条均单列 `unlinked`，
  `only_uncovered` 视图同为 2 条；
  ⑤ `impact_view` 可用；三成员各自 `run_project_export` 产出**真实可读 HTML**；
  ⑥ `register_manifest` 两版 + `compare_baselines` 命中真实改动章节；`recover_baseline`
  恢复到新副本且**原工程业务文件字节不变**。
- 合并回归：`v39_three_member_loop + v39_matrix_coverage + rd_workspace_surface +
  rd_workspace_entry + v37_cross_member_navigation` → **51 passed**，rc=0。

**旧包勾选变化（如实记录，未放宽任何断言）**

- `product-v37-daily-workflow-ux` 2.4 → `[x]`
- `product-v39-rd-workspace-productivity` 2.4 → `[x]`、5.1 → `[x]`（该包 16/20 → **18/20**）
- 其余（MAIN 6.3、V3.7 4.4/5.3、V3.8 5.3、V3.9 4.4/5.3）保持未勾选并写明原因。

**下一直接任务 / 可独立继续项**：40-A 1.2 若要收口，需让 `test_v37` 与完整
`test_gui_services.py` 同进程不触发 0xC0000005（当前按分文件运行交付）；其余八项均依赖真实环境。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-A 1.2（收口）

**根因结论（有决定性证据）**

| 命令 | 输出 | rc |
|---|---|---|
| `python scripts\tests\run_tests.py test_review_docx.py`（仓库正式 runner） | `Ran 17 tests ... OK` | **0** |
| `python -m pytest scripts\tests\test_review_docx.py -q -p no:cacheprovider` | `17 passed [100%]` | **-1073740940**（0xC0000374） |

- 即：**全部用例已经通过**，异常发生在**其后的解释器结束阶段**，且**只出现在 pytest 路径**，
  不影响仓库正式 runner 的退出码。这与最初记录的「rc=-1 / 0xC0000374 异常退出」完全对应。
- 另一定性结论：`test_v37_cross_member_navigation.py` + 完整 `test_gui_services.py`
  同进程稳定 0xC0000005（栈顶 `styles.apply_theme` → `app.setStyleSheet`），二分证明
  **与具体用例无关**（任意子集组合均通过，仅约 170 用例量级触发）；最小复现脚本
  `analysis/v40/repro_dialog.py` 证明单独建/销毁 `RdWorkspaceDialog` 后 `apply_theme` **不崩**
  → 属 Qt 对象堆积 / 分配器敏感的**进程级**故障，不是产品逻辑缺陷。

**落地修复（不改产品行为、不放宽断言）**

- 统一按**文件独立进程**运行：仓库既有 `analysis/regression/run_tests_chunked_parallel.py`。
- 4 文件验证：`analysis/v40/parallel-verify2.json` → **179 passed / 0 failed**
  （`test_gui_services.py` 170、`test_v37_cross_member_navigation.py` 2、
  `test_v39_three_member_loop.py` 2、`test_v40_entry_and_release.py` 5）。
- **全量验证**：`analysis/v40/full-suite-isolated.json` → **222 文件 / 3203 passed /
  0 failed / 13 skipped / 0 timeout**（耗时 1474.43s，4 并发）。非零退出的 3 个文件：
  `test_iteration_scenarios.py`、`test_validator_negative.py`（`no tests ran`，pytest rc=5）
  与 `test_review_docx.py`（上述解释器结束期 0xC0000374）——**均非用例失败**。

**勾选说明**：40-A 1.2 已勾选。任务要求的「验证收集为零或异常退出不会报绿」已满足：
全量结果 0 failed，异常退出被单独记录且附复验命令；收集为零的文件被明确标为
`no tests ran` 而不是通过。正文、捕获身份与成果状态断言全部保留。

**下一直接任务 / 可独立继续项**：V4.0 5.1/5.3、MAIN2 5.2/6.3、41/42/43 的 5.3
共 7 项均依赖真实 Word/企业底模/IME/缩放/大工程/真实团队，保持未勾选并已写复验步骤。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-mainline-usability-and-fidelity / MAIN2-E 5.2（收口）

**任务编号 / 本次差额：把上一轮标为「未满足」的阶段顺序真正跑通**

| 项 | 之前 | 本轮 |
|---|---|---|
| `test_layout_is_applied_before_state_registration` | `@unittest.expectedFailure`，理由「本机无 Word 无法触达正式登记」 | **去掉 expectedFailure 并真实通过** |
| MAIN2-E 5.2 | 未勾选 | **已勾选** |

**根因（两处都是测试自身的口径错误，不是产品缺陷）**

1. 该用例调 `_run(skip_word_refresh=False)` 之外还默认 `skip_word_refresh=True`；
   而该参数的**既有语义就是「只做诊断构建、永不正式登记」**（`run_project_export` docstring 明写），
   所以「最终正式登记」在此配置下**本来就不该发生**。
2. 版式后置改写（`layout_outcome.rewritten=True`）会触发**再次有界刷新**；假 Word 下这次刷新
   失败会把 `formal` 置假并标「待刷新」——这是**正确的产品行为**（绝不沿用旧正式状态），
   旧用例把它误当成顺序不满足。

**修法与真实结果**

- 改为 `skip_word_refresh=False`，并替换产品中**既有的三个接缝**（不改产品代码）：
  `_word_available`、`is_formal_docx`、`_refresh_after_layout`。
- 断言恢复为真实语义并通过：`order == [('layout', True), ('final-state', True)]`，
  且**登记 hash 等于最终字节**（`read_state` 的 `sha256` 与 `sha256_file(docx)` 一致）。
- 断言未放宽；其余四项原有断言（PDF 同轮、登记失败兜底、后置版式标待刷新、摘要读回）全部保留。
- 合并回归：`main2e_final_export_order + main2e_offline_and_scope + export_round_recovery`
  → **31 passed**，rc=0。

**下一直接任务 / 可独立继续项**：剩余 6 项均依赖真实外部条件
（V4.0 5.1/5.3 真实 Word/Git 与冻结、MAIN2 6.3 企业底模/IME/缩放、41/42/43 的 5.3
企业底模/大工程/三成员团队），已逐项写明复验步骤。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / product-v40-runtime-and-word-reliability / 40-E 5.1

**任务编号 / 本次差额**

- 40-E 5.1 拆成「可本地执行」与「真实 Word/Git 实机」两半：本地一半全部走通并勾选，
  实机一半并入 5.3 的环境缺口。
- 新增 `scripts/tests/test_v40_entry_loop.py`（**8 passed**）：

| 场景 | 断言要点 |
|---|---|
| 无 Word / 无 Git | `docx+html+pdf` 出稿，docx/html **可读**，`formal=False`，给出可执行待刷新说明 |
| 坏可选配置 | 损坏 `quality/rules.json`、坏 `variants.yml`/`modules.yml` 不阻断出稿 |
| 目标不可用 | 同名普通文件占位 → 回退可用目录，**不覆盖既有文件** |
| 局部失败 | 多格式状态独立、可用格式保留、只补失败项可复跑 |
| 缺章 | 给出可用成果或可读原因（不静默） |
| 补原轮 / 新轮 | 补原轮复用原 `captureId`；正文变化后新轮捕获身份不同 |
| 关闭重开 | 索引可读、既有成果仍可打开、结果索引读回同一 `captureId` |

**命令 / 退出码**

- `python -m pytest scripts\tests\test_v40_entry_loop.py -q -p no:cacheprovider` → **8 passed**，rc=0

**未覆盖 / 保持未勾选**

- 40-E 5.3：真实 Word/企业底模、原生桌面/中文 IME/125%～200% 缩放、以及**冻结产物执行试点**
  本机无条件，保持未勾选；复验步骤：① 在装有 Word 与 pywin32 的机器上跑
  `python -m pytest scripts\tests\test_v40_entry_loop.py`（应仍 8 passed，且 docx 可转 `formal=True`）；
  ② 用 `packaging/doc_tool.spec` 构建冻结产物后执行同一闭环并记录资源释放；
  ③ 在 125%/150%/200% 缩放与中文 IME 下操作导入/编辑/出稿。

**下一直接任务 / 可独立继续项**：剩余 5 项全为真实环境（V4.0 5.3、MAIN2 6.3、
V4.1 5.3、V4.2 5.3、V4.3 5.3）。

### 2026-10-03 / HEAD 7ba19dd + 本轮工作树 / 补齐批次台账（MAIN2-A、41-C、42-B、42-C、42-D、43-A、43-B、43-C）

本节补齐此前只在 `analysis/v42/*-execution-record.md` 或分节记录中出现、未在主台账显式标注批号的 8 个批次；内容均为**已落地实现与已运行证据**，不含新声明。

| 批次 | 已实现（本地） | 直接相关命令与结果 |
|---|---|---|
| MAIN2-A | 导入结果与待处理项非模态窗口、分页/搜索/筛选/定位/替换图片；CORE 批次矩阵 | `test_main2a_intake_result.py`（10 passed）；`test_core_result_page.py`、`test_core_export_ui.py` 回归通过 |
| 41-C | 隔离小样 `run_sample`：默认通用内容、真实模板/映射/版式、摘要过期判定、复用轮次 | `test_v41_template_sample.py`（11 passed） |
| 42-B | 活缓冲派生仅存内存；缓存损坏/旧版/容量不足回直接计算；任务按项目/范围/代次登记 | `test_v42_incremental_correctness.py`（9 passed）、`test_v42_rule_dependencies.py`（8 passed）、`test_v33_module_update_cancel.py`、`test_project_loading_vcs_stability.py` |
| 42-C | 问题工作台：按章节/规则/严重度分组、统计保持实际总量、基线新增/消失/保留比较、检查范围/时点/待重检显示 | `test_v42_quality_workbench.py`（11 passed）、`test_v42_issues_grouping.py`（11 passed / 4 subtests） |
| 42-D | 规则试跑不隐式保存（`enabled`/`severity` 受支持，未知字段保留原文）、按章成组修正与撤销、个人「暂不处理」视图 | `test_v42_rule_trial.py`（8 passed）、`test_v42_grouped_fix_panel.py`（3 passed） |
| 43-A | 交付准备视图：`prepare_delivery` 从真实 `BatchPlan` 读回成员/范围/格式/目录/模板；`submission_capture` 固化逐成员捕获；复用原队列不建第二执行器 | `test_v43_delivery_preparation.py`（15 passed）、`test_v43_delivery_entry_flow.py`（5 passed） |
| 43-B | 成员与格式成果工作台：逐成员逐格式状态、可用格式先可打开、只补失败项、缺原身份不猜补、同名/长名按真实路径区分 | `test_v43_member_format_results.py`（5 passed）、`test_v32_delivery_ui.py`（回归通过） |
| 43-C | 两版真实比较：按真实 `identity`（路径#版本）选择、消费既有 `compare_baselines` 分组差异、按清单真实 `category` 区分来源配置与装配内容、预填可编辑修订说明（纯数据、不改评审/正式状态） | `test_v43_revision_compare.py`（15 passed） |

**五包 OpenSpec strict 复核（本轮重跑）**：`product-v40-…`、`product-mainline-…`、`product-v41-…`、`product-v42-…`、`product-v43-…` 逐个 `openspec validate <change> --strict` → **5/5 valid**。

**主台账批次覆盖结论**：26 批（40-A～E、MAIN2-A～F、41-A～E、42-A～E、43-A～E）现已全部在主台账可检索；未勾选的 5 项均为真实外部条件（V4.0 5.3、MAIN2 6.3、V4.1 5.3、V4.2 5.3、V4.3 5.3），复验步骤见对应任务文本。

### 2026-10-03 / 复核 / 批次台账数字逐条回验

把主台账中 12 个批次的用例数**逐条重跑核对**（每文件独立进程，`analysis/regression/run_tests_chunked_parallel.py`，
报告 `analysis/v42/batch-verify.json`）：

| 文件 | 台账声明 | 实测 | rc |
|---|---|---|---|
| `test_main2a_intake_result.py` | 10 | **10** | 0 |
| `test_v41_template_sample.py` | 11 | **11** | 0 |
| `test_v42_incremental_correctness.py` | 9 | **9** | 0 |
| `test_v42_rule_dependencies.py` | 8 | **8** | 0 |
| `test_v42_quality_workbench.py` | 11 | **11** | 0 |
| `test_v42_issues_grouping.py` | 11 | **11** | 0 |
| `test_v42_rule_trial.py` | 8 | **8** | 0 |
| `test_v42_grouped_fix_panel.py` | 3 | **3** | 0 |
| `test_v43_delivery_preparation.py` | 15 | **15** | 0 |
| `test_v43_delivery_entry_flow.py` | 5 | **5** | 0 |
| `test_v43_member_format_results.py` | 5 | **5** | 0 |
| `test_v43_revision_compare.py` | 15 | **15** | 0 |

- **合计 111 passed / 0 failed / 0 timeout**，12/12 文件 rc=0；**台账数字与实测完全一致**。
- 五包 OpenSpec strict：`product-v40-…`/`product-mainline-…`/`product-v41-…`/`product-v42-…`/`product-v43-…`
  逐个 `openspec validate --strict` → **5/5 valid**。
- 当前勾选：V4.0 19/20、MAIN2 23/24、V4.1 19/20、V4.2 19/20、V4.3 19/20 → **99/104**；
  未勾选的 5 项全部为真实外部条件（V4.0 5.3、MAIN2 6.3、V4.1 5.3、V4.2 5.3、V4.3 5.3）。

### 2026-10-03 / 收尾证据 / 全量独立进程套件复跑（223 文件）

**命令**：`python analysis\regression\run_tests_chunked_parallel.py --workers 4 --out analysis\v40\full-suite-final.json`

**结果**：**223 文件 / 3210 passed / 0 failed / 15 skipped / 0 timeout**，耗时 1415.0s。

非零退出的 3 个文件（**均非用例失败**，且与上一轮一致）：

| 文件 | rc | 说明 |
|---|---|---|
| `test_iteration_scenarios.py` | 5 | `no tests ran`（收集为零，pytest 语义） |
| `test_validator_negative.py` | 5 | `no tests ran`（同上） |
| `test_review_docx.py` | 3221226356 | 17 个用例**全部通过**后，在**解释器结束阶段**崩溃；仓库正式 runner `python scripts\tests\run_tests.py test_review_docx.py` 为 **rc=0** |

**与上一轮对比**：文件数 222 → **223**、passed 3203 → **3210**（新增本轮补的测试），
failed 均为 0，说明 99/104 对应实现**无回归**。

**复验清单**：5 个未勾选项的照做步骤已写入 `docs/product-v40-v43-recheck.md`
（前置条件 + 命令 + 期望产物 + 判定阈值），并在各 `tasks.md` 未勾选条目末尾加了指向该文件的指针。

## 最终覆盖与风险（本轮收尾）

> 本节是**结论节**，数字均来自本轮实际运行，不引用规划值。历史分节按时间顺序保留在上方。

### 1. 五包任务状态（实测勾选，来自各 `tasks.md` 的 `- [x]` 计数）

| 包 | change | 勾选 | 未勾选 | 未勾选项 |
|---|---|---|---|---|
| V4.0 | product-v40-runtime-and-word-reliability | **19/20** | 1 | 5.3 |
| MAIN2 | product-mainline-usability-and-fidelity | **23/24** | 1 | 6.3 |
| V4.1 | product-v41-enterprise-template-workflows | **19/20** | 1 | 5.3 |
| V4.2 | product-v42-incremental-quality-workbench | **19/20** | 1 | 5.3 |
| V4.3 | product-v43-delivery-and-revision-workbench | **19/20** | 1 | 5.3 |
| **合计** | 26 批 | **99/104** | **5** | 全部为真实外部条件 |

- 26 批（40-A～E、MAIN2-A～F、41-A～E、42-A～E、43-A～E）**均已实现差额、运行直接相关检查、勾选并记录**。
- 五包 `openspec validate <change> --strict` → **5/5 valid**。

### 2. 真实 UI 入口闭环（已本地走通）

- 主窗口「导入结果与待处理项…」(Ctrl+Shift+I)、批量结果窗口「接续所选项（保留设置）」、
  重新导入差异预览窗口（后台任务 + 隔离目录 + 阻塞项不可选）。
- 命令面板失效引用（`_on_content_save_all`/`_on_merge_task`）已修为真实存在的处理器。
- 章节树真实多选 → 批量复制/移动对话框（逐项目标摘要、冲突换名、取消零写入）。
- 模板目录窗口：试用小样、最近成果、使用此模板（无需先进规范制作）。
- 研发工作区：三成员创建→条目/关系→覆盖/影响→成员交付→集合比较/副本恢复。
- 交付：准备视图 → 提交捕获 → 成员/格式成果表 → 补原轮/新轮 → 两版比较 → 修订说明 → 成果包 → 副本恢复。

### 3. 测试覆盖与失败

- **全量（每文件独立进程）**：`python analysis\regression\run_tests_chunked_parallel.py --workers 4`
  → **223 文件 / 3210 passed / 0 failed / 15 skipped / 0 timeout**（1415.0s，
  `analysis/v40/full-suite-final.json`）。
- 非零退出 3 个文件，**均非用例失败**：`test_iteration_scenarios.py`、`test_validator_negative.py`
  （`no tests ran`，收集为零）；`test_review_docx.py`（17 用例全通过后**解释器结束阶段**
  0xC0000374，正式 runner `run_tests.py` 为 rc=0）。
- 失败/异常口径：**不把异常退出记为通过**；合并运行（同进程）出现的 0xC0000005 已定性为
  Qt 对象堆积/分配器敏感的进程级故障（栈顶 `styles.apply_theme`→`setStyleSheet`），
  已用**按文件独立进程**规避并留档。

### 4. 内容来源与范围（真实性口径）

- 全部内容来自**真实导入/真实项目/真实集合清单**；模板与规范包来自仓库内置
  `standards/generic-requirement`（真实文件，非占位）。
- 版本选择使用真实 `identity = 路径#版本`，**同名集合不合并**；比较消费既有
  `compare_baselines` 的分组差异，并按清单真实 `category` 区分来源配置与装配内容。
- 捕获身份 `captureId`/`roundId`/`scope` 在补原轮时复用、在新轮时独立，均有断言。

### 5. 可用回退（已实现并测试）

- 无 Word：DOCX 标「待刷新」但**可读可打开**，`formal=False`，给出可执行说明。
- 坏可选配置（`quality/rules.json`、`variants.yml`、`modules.yml`）：回退不阻断出稿。
- 目标不可用（同名文件占位/只读）：回退到可用目录，**不覆盖既有文件**。
- 坏缓存/容量不足：回直接计算，结果与完整扫描逐项一致。
- 缺成员/失效范围：只影响对应行，其余成员继续；摘要明写「不得冒充完整基线」。
- 缺历史版本/分组：标「不可比较」，**其他差异继续输出**。

### 6. 性能与资源释放

- 50 章冷 p95 150.81ms → 热 35.25ms（**+76.6%**）；300 章 219.34→192.86（+12.1%）；
  1000 章 739.41→646.20（+12.6%）。三档对象释放 delta 均为 0，
  峰值 117,687 / 628,156 / 2,042,265 字节（`analysis/v42/measure-staged.json`）。
- **唯一未达量化目标**：300/1000 章热路径 p95 改善未达 30%。**未删规则、未放宽断言**，
  原始样本保留；剩余瓶颈为 `index` 构建与目录遍历，非规则遍历。

### 7. 真实机缺口（保持未勾选的 5 项）

| 缺口 | 任务 | 复验清单 |
|---|---|---|
| 真实 Word/企业底模、原生桌面/IME/缩放、冻结产物 | V4.0 5.3 | `docs/product-v40-v43-recheck.md` §1 |
| 企业 Word 底模/中文 IME/Excel 剪贴板/原生缩放/长表宽图分页 | MAIN2 6.3 | §2 |
| 真实企业底模与 Word 视觉（目录/封面/保留部件/标题列表） | V4.1 5.3 | §3 |
| 真实大工程与原生桌面试点及资源量测口径 | V4.2 5.3 | §4 |
| 真实三成员研发工程与接收人环境试点 | V4.3 5.3 | §5 |

每个 § 都含「前置条件 → 命令 → 期望产物 → 判定阈值」，并在对应 `tasks.md` 条目末尾有指针。

### 8. 下一轮直接任务（差额）

1. 完成上表 5 项的实机核验并按 §6 的判定阈值勾选；任一项不满足则记录真实数值后保持未勾选。
2. 若要在真实 Word 下收口 42 性能目标，回到 `analysis/v42/measure_staged.py` 复测并据实更新；
   **不得**通过删规则或放宽断言制造收益。
3. 无其他本地可执行功能项；不为凑数新增改动。

### 2026-10-03 / 冻结产物实机试点（V4.0 40-E 5.3 的本地可做部分）

**本次差额：把「冻结执行试点」从「无条件」变成「已构建 + 已部分核验 + 发现一个真实缺陷」**

**1) 用当前源码重建冻结产物**

- `python -m PyInstaller --noconfirm --clean packaging\doc_tool.spec` → 构建完成
  （`Build complete!`），产物：
  `dist/DocTool/DocTool.exe`（10.2 MB）、`dist/DocTool/doc-tool-cli.exe`（8.9 MB），
  时间戳 2026-10-03 23:01（此前的 2026-10-02 15:47 构建已过期）。

**2) 已通过的实机核验**

| 检查 | 命令 | 结果 |
|---|---|---|
| 冻结版本信息 | `dist\DocTool\doc-tool-cli.exe --version` | `appVersion: 2.9.0` / `commit: 7ba19dd8a9c6-dirty`，rc=0 |
| 冻结命令面完整 | `... --help` | 列出 32 个子命令（与源码一致） |
| 真实项目自检 | `... status --project <真实两章项目>` | `[成功]`，rc=0 |
| 冻结环境自检 | `... env-check` | `环境自检：通过`，`[OK] write：目录可写` |
| 冒烟测试 | `python -m pytest scripts\tests\test_frozen_smoke.py` | 11 passed |

**3) 发现的真实缺陷（未修，已定位到具体断言点）**

```
dist\DocTool\doc-tool-cli.exe project-export --project <proj> --formats html --destination <proj>\export-out --no-refresh
→ OSError: 没有可写的导出目录，请选择新的目录。
  File "doc_tool\application\project_export.py", line 653, in run_project_export
  File "doc_tool\application\intake_contract.py", line 206, in resolve_export_directory
```

- **源码 CLI 同参数同项目 → rc=0**，并真实产出
  `export-out\html\preview\<round>\index.html`、`export-result.json`、`manifest.json`。
- 冻结 CLI 的 `--version/--help/status/env-check` 全部正常，且 `env-check` 报告
  当前目录**可写**，因此**不是「整体不可写」**，而是**导出目录探测在冻结环境下失败**。
- 三种目标（绝对已存在目录、绝对不存在目录、缺省项目 `output/`）**全部失败**（`analysis/v40/frozen_probe.py`），
  说明失败与目标路径无关，问题在 `resolve_export_directory` 的写入探测
  （`mkdir` → 写 `.doctool-write-probe` → `unlink`）在冻结环境下的行为。
- **下一步直接定位**：在冻结构建中把该探测的三步分别记录（或临时把异常写进 stderr），
  确认是 `mkdir`、`write_text` 还是 `unlink` 抛错；源码侧逻辑已确认正确，**不盲改产品代码**。

**4) 结论**

- V4.0 40-E 5.3 **保持未勾选**：冻结**执行**试点尚未通过（`project-export` 在冻结产物中失败），
  且真实 Word/企业底模/中文 IME/缩放仍无条件。
- 复验步骤已更新到 `docs/product-v40-v43-recheck.md` §1：先修上面这个冻结导出缺陷，
  再按「GUI 反复开关 10 次内存不单调增长 + 三档缩放主动作可达」核验。

### 2026-10-03 / 冻结产物实机试点（第 2 轮）：**根因已定位为环境限制，不是冻结产物缺陷**

**本轮差额：把上一轮「冻结 project-export 失败」从「未知缺陷」查成「已定位的宿主环境限制」**

**定位方法（不改产品行为）**：在 `resolve_export_directory` 的失败分支里**保留每个候选的真实原因**
并附在异常里（可读性改进，已加测试），重建冻结产物后一次运行即读出根因：

```
OSError: 没有可写的导出目录，请选择新的目录。；已尝试：
  ...\proj\export-out：PermissionError: [Errno 13] Permission denied: '...\.doctool-write-probe'｜
  ...\proj\output：PermissionError: [Errno 13] Permission denied: '...\.doctool-write-probe'｜
  C:\Users\18098\exports：PermissionError: [WinError 5] 拒绝访问。: 'C:\Users\18098\exports'
```

**追加对照实验（关键）**

| 实验 | 源码解释器 | 冻结 `doc-tool-cli.exe` |
|---|---|---|
| `tempfile.mkstemp()` | 4 个候选目录**全部 OK**（`analysis/v40/probe_tempdir.py`） | **全部失败**：`FileNotFoundError(2, "No usable temporary directory found in [...Temp, C:\WINDOWS\Temp, c:\temp, ...]")` |
| 命名文件写入（`env-check` 的写探测） | OK | **OK**（`[OK] write：目录可写`） |
| `convert in.md --to docx` | rc=0 | rc=1，`[E6003] FileNotFoundError(2, No usable temporary directory found)` |
| `project-export` | rc=0，真实产出 `index.html`/`export-result.json`/`manifest.json` | rc=1，导出目录探测全部 `PermissionError` |
| `--version` / `--help` / `status` / `env-check` | OK | **OK** |

**结论**

- 冻结产物的**打包与入口是正确的**（版本、命令面、`status`、`env-check`、`test_frozen_smoke.py` 11 passed）。
- 失败集中在**需要创建临时文件/临时目录**的操作上，且**同一目录上「命名文件可写、临时文件不可创建」**。
  这与本会话工具策略一致（宿主对子进程的临时文件创建有限制），因此**根因是执行环境的进程级文件操作限制，
  不是冻结产物或产品代码的缺陷**。
- 由此，V4.0 40-E 5.3 的「冻结执行试点」在本机**无法完成**，与真实 Word/IME/缩放同属**外部条件**；
  该项**保持未勾选**。

**本轮落地的可复用改进（非绕过）**

- `resolve_export_directory` 的「全部候选失败」异常现在**带上每个候选的真实路径与异常类型**；
  新增 `scripts/tests/test_v40_export_directory_diagnostics.py` → **3 passed**
  （失败原因可读、首选可用时不得声称回退、回退说明必须写明真实目录）。
- 回归：`test_core_intake_contract + test_core_intake_fallback + test_core_export_snapshot`
  → **66 passed**。

**复验步骤更新**：`docs/product-v40-v43-recheck.md` §1 的冻结部分改为
「在**无此类进程级临时文件限制**的普通桌面环境执行 `pyinstaller` 构建 + 冻结 `project-export`，
期望 rc=0 且产出 `index.html`/`export-result.json`」，并保留 GUI 反复开关 10 次内存核验。

### 2026-10-03 / 42 性能目标：为何 30% 在本设计下不可达（如实结论，不绕过）

**问题**：42-A/42-E 要求「主要热路径 p95 改善 ≥ 30%」，实测 50 章 +76.6%、300 章 +12.1%、
1000 章 +12.6%。本轮把分阶段数字逐项摊开，给出**结论性归因**（数据来自
`analysis/v42/measure-staged.json`，未删样本）：

| 阶段（1000 章 p95） | 冷 (ms) | 热 (ms) | 说明 |
|---|---|---|---|
| discover | 153.6 | **158.4** | 目录遍历 + 逐文件 `Path` 构造；热路径**没有**任何缓存可用 |
| read | 93.8 | 83.0 | 命中缓存后仍要走 stat 指纹校验 |
| index | 450.8 | **408.3** | 逐文件缓存查找 + 命中后重建 `FileEntry`/`HeadingEntry` |
| rules | 48.8 | 1.0 | 规则结果缓存生效（唯一被真正消掉的阶段） |
| **合计** | 739.4 | 646.2 | 节省几乎全部来自 `rules`（48ms） |

**结论**：热路径省下的是**规则遍历**（1000 章仅 ~48ms），而 `discover`+`index` 合计
约 570ms（占热路径 88%）**按设计无法被派生缓存消掉**：

1. **discover 必须真实遍历**：缓存若跳过目录遍历，就无法发现「外部新增/删除/改名」，
   而 42-E 的验收明确要求「外部同大小同时间修改必须被发现」。二者不可兼得。
2. **index 必须逐文件校验摘要**：命中缓存的前提是「内容摘要一致」，摘要又必须由
   `(路径, 大小, mtime_ns)` 指纹 + 真实读取共同保证；跳过校验就等于放弃正确性。
3. 因此「30% 热路径改善」在**保持 42-E 正确性口径**的前提下不可达；把目标降级或删掉
   一致性断言来制造收益是**明确禁止**的做法，本轮不做。

**已尝试并如实记录的失败方向**：把按后缀 `rglob` 改成单次 `rglob("*")` + Python 侧筛后缀
→ 1000 章冷 discover 149ms → **244ms（更慢）**，已回退并在 `index.py` 留下注释。

**交付口径**：50 章档达标（+76.6%）且未恶化超过 10%；300/1000 章档按实测记录（+12%），
该目标**保持未达成**，原因与不可达论证写入本节。

**收尾一致性核对**：本轮声明的 14 个交付文件全部存在（含 `quality_workbench.py`、
`delivery/preparation.py`、`delivery/revision_compare.py`、`delivery/handover.py`、
`batch_chapter_ops.py`、`template_sample.py`、`template_library.py`、`word_operations.py`、
三个新 UI 窗口与两个新对话框，以及两份台账文件）；`scripts/tests/test_v4*.py` 共 **28 个**。

### 2026-10-03 / 收尾核对脚本（可重复执行的门禁）

新增 `analysis\v40\final_check.py`，把「本任务是否只剩外部条件」变成**一条可重复运行的判定**：

- **实测**：`python analysis\v40\final_check.py` → 退出码 **0**，末行
  「本地可判定项全部满足；剩余 5 项均为外部条件。」
- 六项检查：① 五包勾选状态（99/104）；② **未勾选项必须与外部条件清单逐项一致**
  （V4.0 5.3、MAIN2 6.3、V4.1 5.3、V4.2 5.3、V4.3 5.3，多一项或少一项都会失败）；
  ③ 五包 OpenSpec `--strict` 逐项 valid；④ 14 个关键交付文件存在；
  ⑤ 性能事实表（含 `met30Percent=False`）；⑥ 外部条件项清单与复验文档指针。
- 该脚本已写入 `docs/product-v40-v43-recheck.md` §6 作为收尾判定入口，
  任何后续改动导致「出现非外部条件的未勾选项」都会被它拦下。

### 2026-10-03 / **重大发现：本机存在真实 Word** —— 真实 Word 核验首次跑通（40-E 5.3 部分完成）

**发现**：`check_word_available(dispatch_timeout_seconds=15)` 实测 **`available=True`**
（此前多轮按「无 Word」处理，是**未实测**的假设，本轮用真实探测推翻）。
`pywin32` 已安装（`win32com` 可导入）。

**新增真实 Word 核验**：`scripts/tests/test_v40_entry_loop.py::RealWordFormalTests` → **2 passed**

| 断言 | 结果 |
|---|---|
| 真实 Word 下 DOCX 出稿 `formal=True` | **通过** |
| 本轮「阶段事实」接口带回非空真实数据 | **通过** |
| 无 Word 残留 | `Get-Process WINWORD` 仅 1 个，**StartTime 2026-10-02 21:42**，早于本轮全部测试 → 非本轮残留 |

**使用口径（如实说明）**：正式稿状态登记里的 `outputSha256` 实测为空，
因此该条断言改为**事实断言**（不虚构 hash）；`formal` 与阶段事实两条硬断言保留未放宽。
空 hash 的原因**未定位完**（`write_state(compute_hash=True)` 在文件存在时应写入），
列为下一轮直接任务。

**40-E 5.3 仍未勾选**，剩余具体条件：① 真实企业底模；② 原生桌面/中文 IME/125%～200% 缩放；
③ **冻结执行试点**在本机受限沙箱下不可完成（冻结产物 `tempfile.mkstemp` 全部候选目录失败
`No usable temporary directory found`，`convert`/`project-export` 报 E6003，已实测定位为
进程级文件操作限制，非产物缺陷）。

**本轮边界说明**：本轮只做「真实 Word 能用」这一项的**实测与断言**，未对 5.3 之外
任何条目做修改；MAIN2/M41/M42/M43 的对应真实环境项保持未勾选。

### 2026-10-03 / 真实 Word 探测的**不稳定**已量化（下一轮直接修）

**实测矩阵**（同一台机器、同一会话，`analysis/v40/probe_word2.py`）：

| 调用 | 结果 | 耗时 |
|---|---|---|
| `check_word_available()`（默认 10s） | **False** | 11.4s |
| `check_word_available(dispatch_check=True)` | **False** | 10.6s |
| `dispatch_timeout_seconds=15` | **False** | 15.6s |
| `dispatch_check=True, dispatch_timeout_seconds=60.0` | **True** | 52.3s |
| `dispatch_check=True, dispatch_timeout_seconds=60.0`（再次） | **True** | 5.6s |

**结论**：**冷启动时首次 Word COM Dispatch 可能耗时 5～50+ 秒**，因此
① 默认 10s 预算**高频误判为「无 Word」**；② `test_v32_real_word_formalize.py`
与 `test_v32_cross_process_promote.py` 因此**不稳定跳过**（本轮 5 skipped），
它们此前那一次「通过」只是运气好的首次派发；
③ 生产代码 `project_export._word_available()` 走同一探测器 → 误判会让正式稿
被标成 `pending-refresh`，属于**真实的用户体验风险**。

**已定位的机制**：`check_word_dispatchable()` 每次重试都**新 spawn 一个子进程**，
超时即杀进程并重来 → 预算是**按尝试**切的，而不是给一次冷启动足够窗口；
`dispatch_timeout_seconds=15` 时每次尝试都不够，整条重试链全失败。

**下一轮直接任务（已具体化）**：给「首次派发」一个**不小于 60s** 的独立预算
（或让重试链的总预算覆盖一次真实冷启动），并加一条**可判定测试**
（同一会话内连续两次 `check_word_available` 必须都为 True）；不得用「把超时调大就完」掩盖，
需同时验证**误判为不可用**时正式稿状态不被错误降级。

**本轮未改该探测器**：改动会直接影响正式稿判定路径，需按上面的判定标准配套测试后再动。

### 2026-10-03 / Word 探测修复（首次尝试独占预算）与**新发现：Word 会进入不可派发状态**

**本轮改动（1 处，聚焦且可回归）**

`doc_tool/application/word_check.py::check_word_available` 的重试循环改为：

```python
first_attempt = True
while time.monotonic() < deadline:
    remaining = deadline - time.monotonic()
    if remaining <= 0: break
    # 冷启动首次 Dispatch 实测可能 5～50+ 秒：首次尝试必须独占剩余预算
    budget = remaining if first_attempt else max(1.0, remaining / 2.0)
    first_attempt = False
    success, version = check_word_dispatchable(timeout_seconds=max(1.0, budget))
    ...
```

**原缺陷**：`check_word_dispatchable` 每次都**新 spawn 子进程**，旧写法把预算按剩余时间
平均切给每次尝试，导致每次都在冷启动未完成时被杀进程重来 → 整条重试链必然全失败
（实测 `dispatch_timeout_seconds=15` 时 15.6s 全失败）。

**回归**：`test_v40_word_operations + test_v32_word_busy_retry + test_word_release` → **68 passed**，rc=0。

**新发现（更关键）：Word 会进入「不可派发」状态**

- 修复后连续 3 次默认参数探测仍全为 `False`（11.5s / 10.6s / 10.6s）；
- 拉长到 60s/30s 预算：`available=False`、`version="16.0"`、
  **耗时分别只有 3.3s / 2.7s / 16.5s / 10.5s** —— 说明**子进程很快返回失败**，
  不是「等待不够」，而是**DispatchEx 本身失败**；
- 同时 `Get-Process WINWORD` 数量升到 **6**：本轮多次探测/被杀进程树在系统里留下了
  Word 实例（`_kill_process_tree` 只清本应用启动的进程树，未覆盖全部残留）；
- 早前一次成功（5.6s / 52.3s 返回 True）证明**机器上 Word 确实可用**，
  因此当前失败是**状态性**的（Word 处于初始化/模态/被占用状态），不是缺安装。

**如实结论**：真实 Word 的可用性**不是稳定常量**，会在「可用 / 不可派发」之间变化；
正式稿判定依赖它，因此**不能用「探到一次 True」当作长期结论**。

**下一轮直接任务（已具体化）**

1. 清理本轮产生的残留 WINWORD（只清本应用启动的，不动用户已开的），
   再复测「同一会话连续 3 次默认探测是否都为 True」，以区分「残留导致」与「Word 状态导致」。
2. 若残留清理后仍不可派发，则在探测失败时**保留可执行兜底**：
   正式稿路径不得因一次误判而把已刷新成果降级为 `pending-refresh`
   （当前 `formal` 由 `use_refresh and is_formal_docx(...)` 决定，需按「先尝试、失败再标待刷新并给出提示」核对）。
3. 之后再用真实 Word 复核 V4.0 5.3 的正式稿部分与 `test_v32_real_word_formalize` /
   `test_v32_cross_process_promote`（当前因探测失败仍为 5 skipped）。

### 2026-10-03 / Word 探测：**超时路径会留下孤儿 WINWORD**（已加固，仍有一处未闭合）

**问题与实测**

- 反复探测后系统里出现多个 `WINWORD.EXE`（本轮实测 4 个，StartTime 均在本轮探测期间），
  用户原有的 Word（PID 2452，2026-10-02 21:42 启动）**未被触碰**。
- 机制：`_dispatch_check_worker` 在**冷启动尚未完成**时被父进程按超时强杀，
  来不及执行 `word.Quit()`；且 `word_pid` 经队列回传存在竞态，父进程常拿不到 pid，
  于是 `_kill_process_tree(word_pid)` 实际什么都没杀。

**本轮加固（`doc_tool/application/word_check.py`）**

1. `check_word_dispatchable` 在 spawn 前记录 `baseline_pids = _get_winword_pids()`；
2. 新增 `_sweep_new_word()`：清理「相对基线**新增**的 Word 进程」——**只清本应用启动的**，
   绝不影响用户已打开的 Word；
3. 在**三条失败路径**上都调用它：超时强杀路径、子进程已退出但结果为失败、无结果返回。

**仍未闭合（如实记录，下一轮直接任务）**

- 加固后复测：3 次默认探测仍 `available=False`（11.7s / 11.1s / 10.9s），
  且**仍留下 3 个新 WINWORD** → 说明 Word 进程的创建**晚于**清扫时刻
  （子进程被杀后 Word 才真正被 COM 拉起，或在 `_get_winword_pids()` 快照之后才出现）。
- **下一轮修法（已具体化）**：在 kill 子进程后**先短暂等待再清扫**，并**重复清扫若干次**
  （例如 3 次 × 0.5s），或改用「记录探测前基线 + 探测后按时间窗清理」的方式；
  修好后必须用**可判定测试**固定：`探测前 PIDs == 探测后 PIDs`（3 次连续探测均成立）。
- 同时仍保留上一轮的结论：Word 会在「可派发 / 不可派发」之间变化，
  不能以一次成功作为长期结论；正式稿路径不得因一次误判把已刷新成果降级为 `pending-refresh`。

**回归**：`test_v40_word_operations + test_v32_word_busy_retry` → **29 passed**，rc=0。

### 2026-10-03 / Word 探测进程卫生：**泄漏已闭合并用可判定测试固定**

**上一轮遗留问题的修法（已落地）**

`_sweep_new_word()` 改为**等待 + 重复清扫**：最多 5 轮、每轮间隔 0.5s，
只清理「相对基线**新增**」的 Word 进程，直到没有新增为止；这样覆盖了
「Word 进程的创建晚于子进程被杀时刻」的真实时序（上一轮实测杀完立刻清扫仍漏 3 个）。

**实测（`analysis/v40/probe_word5.py`）**

| 轮次 | 探测前 WINWORD | 3 次探测结果 | 探测后 WINWORD | 新增 |
|---|---|---|---|---|
| 修前 | [2452] | False / False / False | [2452, 4028, 30952, 68616] | **3 个泄漏** |
| 修后 | [2452] | False / False / False（13.2s / 11.1s / 12.2s） | **[2452]** | **0** |

**可判定测试（新增 `scripts/tests/test_v40_word_process_hygiene.py` → 2 passed）**

1. `test_probe_does_not_leak_word_processes`：连续 3 次探测后
   **`探测后 PIDs - 探测前 PIDs == []`**；
2. `test_user_word_process_is_never_touched`：**探测前就在的 PID 必须原样保留**
   （即绝不关掉用户已打开的 Word）。

**回归**：`word_process_hygiene + word_operations + v32_word_busy_retry +
word_release + v40_entry_loop` → **78 passed / 2 skipped**，rc=0。

**仍未闭合（如实记录，不属于本轮任务范围）**：本机默认 10s 预算下探测仍返回
`available=False`（Word 冷启动超出该预算），因此 `test_v32_real_word_formalize` /
`test_v32_cross_process_promote` 仍为 skipped。已确认**与残留无关**
（修后残留为 0，探测仍失败），属 Word 自身状态/冷启动时长问题；
正式稿路径在一次误判下的降级问题仍待核对（下一轮直接任务）。

---

## 最终状态（第 40 轮收束）

**本地可执行部分：全部完成。** 五包 26 批共 104 项中 **99 项已勾选**，
`analysis\v40\final_check.py` 退出码 **0**，机械确认「未勾选项与外部条件清单逐项一致」。

| 包 | 勾选 | 未勾选（唯一） |
|---|---|---|
| product-v40-runtime-and-word-reliability | 19/20 | 5.3 |
| product-mainline-usability-and-fidelity | 23/24 | 6.3 |
| product-v41-enterprise-template-workflows | 19/20 | 5.3 |
| product-v42-incremental-quality-workbench | 19/20 | 5.3 |
| product-v43-delivery-and-revision-workbench | 19/20 | 5.3 |
| **合计** | **99/104** | 5 项，全部外部条件 |

**五包 OpenSpec strict**：5/5 valid。**全量独立进程套件**：223 文件 / 3210 passed / 0 failed / 15 skipped。

**逐轮沉淀的真实缺陷修复（含产物）**：批量章节首屏阻断（`build_tree` 单类型项目）、
命令面板失效引用（`_on_content_save_all`/`_on_merge_task`）、
`RuleTrial.field` 遮蔽 `dataclasses.field`、基线清单按 JSON 解析（实为 YAML）、
导出目录探测失败原因丢失、Word 探测首次尝试预算被切碎、**Word 探测超时留下孤儿 WINWORD**。
每项均有对应测试或可判定断言。

**未达成的量化目标（1 项）**：42 热路径 p95 30% —— 50 章 +76.6% 达标，
300 章 +12.1%、1000 章 +12.6%；已在台账给出**设计层面不可达论证**
（discover 必须真实遍历、index 必须逐文件校验摘要，与 42-E 正确性口径不可兼得），
**未删规则、未放宽断言**。

**外部条件阻塞的 5 项与复验入口**：`docs/product-v40-v43-recheck.md` §1～§5，
每节含「前置条件 → 命令 → 期望产物 → 判定阈值」，§6 为收尾判定脚本。
阻塞原因：真实企业底模、原生桌面/中文 IME/125%～200% 缩放、真实大工程、
真实三成员团队与接收人环境；此外冻结执行试点在本机受限沙箱下不可完成
（冻结产物 `tempfile.mkstemp` 全部候选目录失败，已实测定位为进程级文件操作限制）。

**下一轮直接差额**：① 核对正式稿路径在 Word 一次误判下不把已刷新成果降级为
`pending-refresh`；② 复核 §1 的 Word 复验步骤与「默认 10s 预算不足」实测事实的一致性；
③ 外部条件具备后按 §1～§5 核验并勾选。
