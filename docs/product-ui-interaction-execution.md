# 页面交互优化执行台账

最终复核：2026-10-02。唯一change：`product-ui-interaction-polish`。入口：[最终计划](product-ui-interaction-final-plan.md)，依据：[调研](product-ui-interaction-research.md)，实时进度：[tasks](../openspec/changes/product-ui-interaction-polish/tasks.md)。使用openspec-apply-change，保留已有工作树和其他包任务。

## 计划起始状态

| 批次 | 编号 | 起始实现 | 本包自动验收 | 本包实机验收 |
|---|---|---|---|---|
| UI-A | 1.1～1.4 | 0/4 → 4/4 | 已完成（12+8 项新控件用例 + 直接回归） | 未运行 |
| UI-B | 2.1～2.4 | 0/4 → 4/4 | 已完成（12+8+3 项新用例 + 几何证据 + 直接回归） | 未运行 |
| UI-C | 3.1～3.4 | 0/4 → 4/4 | 已完成（14 项新用例 + 直接回归） | 未运行 |
| UI-D | 4.1～4.4 | 0/4 → 4/4 | 已完成（17 项新用例 + 直接回归） | 未运行 |
| UI-E | 5.1～5.4 | 5.1/5.2/5.4 完成，5.3 待实机 | 5.1/5.2 证据已出；全量回归 157/157 与 strict 通过（见下方 5.4 记录） | 未运行（缺真实 DPI/输入法/Word） |
| UI-B | 2.1～2.4 | 0/4 | 未运行 | 未运行 |
| UI-C | 3.1～3.4 | 0/4 | 未运行 | 未运行 |
| UI-D | 4.1～4.4 | 0/4 | 未运行 | 未运行 |
| UI-E | 5.1～5.4 | 0/4 | 未运行 | 未运行 |

5批/20项仅规划就绪。此前Qt离屏和浏览器模拟是调研证据，既有CORE/V3测试是基础证据；都不是本包新增实现已完成的证据。后续实时状态以tasks及下方实施记录为准。

最终规划检查已通过：OpenSpec strict有效，4/4规划产物就绪；10份关联Markdown无失效本地链接及行尾空格，20项编号唯一、3个capability与spec目录一致，引用的15个基础测试文件均存在。任务仍0/20；本次未运行UI业务回归。复核时CORE/V3.0～V3.3仍为151/157。

## 建议直接验证入口

以下是当前仓库已存在的基础套件；实施时按接口/断言变化选择必要项，并新增实际非模态/溢出/来源/首用控件测试。测试名称不是限定实施方案，不能把这些旧套件通过当作所有新要求自动满足。

| 相关批次 | 基础套件（scripts/tests/） | 必须补查的实际行为 |
|---|---|---|
| A | test_core_entries_ui.py、test_core_intake_presets_gui.py、test_home_experience_iteration.py | 拖放/按钮/菜单同语义、真实建项、普通提交次数 |
| B | test_safety_recovery.py、test_recovery_entries.py、test_core_hidpi_layout.py、test_v31_registry_display.py | 项目打开后的正文/文字几何、旧会话/恢复、快捷键真实焦点 |
| C | test_core_export_ui.py、test_core_export_snapshot.py、test_core_gui_loop.py、test_v32_delivery_ui.py、test_v32_delivery_progress.py | 非模态逐文件打开、旧捕获/新轮/换目录、运行中编辑/取消/迟到事件 |
| D | test_v30_reuse_ui.py、test_v32_delivery_ui.py、test_v33_panel_reachability.py、test_v33_adoption_editor.py | 无JSON批次、空库创建/安装/固定插入、无资料→搜索/建议/采纳 |
| E | 本包新增控件测试、上述直接回归、最终run_tests.py清单 | 默认闭环、1/1.25/1.5模拟及实际DPI/IME/Word证据分开 |

解释器优先用项目已有可用环境；依赖缺失先检查.vendor或已有runtime，不改业务约束来让环境通过。离屏使用合成项目/隔离用户目录并显式加载可用字体，记录实际DPR/逻辑尺寸。

相关检查示例（按本批选文件，避免每批重复全量）：

```powershell
$env:PYTHONUTF8 = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
python scripts/tests/run_tests.py --junit analysis/ui-polish-A.xml test_core_entries_ui.py test_core_intake_presets_gui.py test_home_experience_iteration.py
openspec validate product-ui-interaction-polish --strict
```

最终整合后运行一次`python scripts/tests/run_tests.py --junit analysis/ui-polish-final.xml`，先确认新增测试已进入清单；新增改动/失败再按影响重跑。runner的JUnit是按测试文件汇总，报告时不要误写为同数量的用例。实际Word测试需具备环境且显式选择，不设置实机开关后用模拟数据冒充通过。

## 每批实施记录

```text
日期 / HEAD / 工作树基准 / 解释器与环境 / 批次：
本批补的差额 / 复用服务 / 完成编号 / tasks进度：
真实用户入口 / 操作步骤 / 主要提交及强制弹窗数：
项目/任务/轮次/captureId / 格式 / 来源 / 实际产物路径：
源文件、磁盘正文、未保存缓冲及草稿前后事实：
窗口逻辑尺寸 / DPR / 字体 / 正文矩形 / 溢出或点击区：
验证命令 / 退出码 / 报告或截图：
实际成功 / 自动处理 / 待完善 / 失败或未执行：
已有失败分类 / 只受影响任务 / 实机缺项与复验步骤：
下一直接任务 / 仍可继续的任务：
```

## 每批实施记录

### UI-A（1.1～1.4）

```text
日期 / HEAD / 工作树基准 / 解释器与环境 / 批次：
2026-10-02 / HEAD 2e5be72（工作树干净起点）/ Python 3.13.13 + PySide6 6.8.3 / QT_QPA_PLATFORM=offscreen / UI-A

本批补的差额 / 复用服务 / 完成编号 / tasks进度：
1) 首页主区拖放从「整页直接进互转」改为按落点路由：左侧「项目出稿」区 = 既有 intake 路由（与「新建项目…」同一 handler），
   互转卡自身拖放 = ConvertDialog；无坐标的旧桩事件仍退回互转语义（旧调用方兼容）。
2) 顶部新增「导出 Word」主按钮（ProjectBar），与菜单「快速导出 Word（整份 / 当前内容）」和 Ctrl+E 共用 _on_quick_export_word，
   可用性统一来自 derive_workbench_state 的新 quick_export 动作（只限制重复启动，不因缺 Word/Git 阻断可读稿）。
3) 快速出稿默认值抽为 _quick_export_defaults：每次从零构造 ExportRequest（整份 scope + current-buffer 优先 + 有效输出目录 + strict=False），
   显式不继承上一轮部分范围/saved 来源/严格策略；状态栏与按钮提示显示真实未保存章节数。
4) 导入向导源页主路径文案改为「开始导入」，原「下一步」在普通有效源下改名为「调整章节与样式映射（可选）」；无标题/含阻断特性文档也提供一键导入。
5) 文件菜单「新建项目（导入向导）」与「导入文档」合并为一个入口；命令面板移除重复的「接管现有 Word 建项」。
编号：1.1/1.2/1.3/1.4；tasks 4/20

真实用户入口 / 操作步骤 / 主要提交及强制弹窗数：
- 首页左侧「项目出稿（拖入即导入建项）」区拖入 .md×2 → 1 次拖放（0 次弹窗）即真实建项并打开；拖入 .docx → 1 次拖放进入导入向导。
- 工作台顶部「导出 Word」/菜单「快速导出 Word」/Ctrl+E → 普通有效源 1 次点击即后台生成可读 Word。
- 导入向导：选中有效源后「立即一键导入并进入工作台」= 1 次提交；「下一步：调整章节与样式映射（可选）」= 可选第 2 次提交。

项目/任务/轮次/captureId / 格式 / 来源 / 实际产物路径：
- 建项用例产物：tmp/core-scratch/ui-polish-drop-*/out/**（project.yml + content/ 章节，Markdown 顺序断言已覆盖）。
- 出稿用例由桩服务捕获 request，断言 formats=[docx]、scope.kind=project、sourceMode=current-buffer/saved、destination=paths.output_dir。

源文件、磁盘正文、未保存缓冲及草稿前后事实：
- 混合来源用例前后逐字节比较 .docx/.md/.zip 未变化；不支持格式只警告 1 次、不进入任何服务、不禁用普通编辑。
- 有未保存缓冲时不写回、不清脏：测试注入 buffer 后断言 request.sourceMode=current-buffer 且 buffer_texts 原样传入后台。

窗口逻辑尺寸 / DPR / 字体 / 正文矩形 / 溢出或点击区：
本批不涉及正文几何验收（归 2.4/5.2）；ProjectBar 按钮顺序与角色由 test_action_positioning.py 断言（快速导出最前、primary）。

验证命令 / 退出码 / 报告或截图：
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
python scripts/tests/run_tests.py --junit analysis/ui-polish-A.xml test_ui_polish_entry_drop.py test_ui_polish_quick_export.py \
  test_core_entries_ui.py test_core_intake_presets_gui.py test_home_experience_iteration.py test_core_export_ui.py \
  test_core_export_snapshot.py test_core_gui_loop.py test_action_positioning.py test_branch_ui.py test_command_palette.py test_gui_services.py
报告：analysis/ui-polish-A.xml（含 12 个新用例文件 + 既有直接回归）；日志 analysis/ui-polish-A.log。

实际成功 / 自动处理 / 待完善 / 失败或未执行：
- 成功：落点路由、顶部快速 Word、导入主路径文案、命令组合并；新控件/接线用例全绿。
- 自动处理：无坐标桩事件退回互转；整页拖放保持兼容。
- 待完善：首页整页仍是唯一拖放接收控件，落点判定用控件全局矩形（窄屏上下堆叠时按文档流取上者）。
- 未执行：真实 DPI/输入法/Word 实机（归 5.3，保持未勾选）。

已有失败分类 / 只受影响任务 / 实机缺项与复验步骤：
本批改动文件相关用例无新增失败；基线 3 个失败文件（test_final_handover_report.py 时间戳、test_v30_content_reuse.py、test_v30_reuse_entry.py）与本批无关，
来自 analysis/ui-polish-baseline-full.xml（工作树干净起点，149 文件 / 3 失败 / 1273s），按基准分类，不在本批修复范围。

下一直接任务 / 仍可继续的任务：
UI-B 2.1（工具栏原生溢出/标题级别）与 2.2（首用写作布局与恢复布局）；随后 UI-C。
```

### UI-B（2.1～2.4）

```text
批次：UI-B；完成编号 2.1/2.2/2.3/2.4；tasks 8/20
本批补的差额：
1) 格式工具栏新增「更多 ▾」溢出（按面板真实宽度重排；1024 宽下 14 个动作一个不丢，
   菜单项可真实触发）+ 标题级别 H1～H6 选择器（替换式写入、进撤销栈）；
2) 文件标识显示短名、完整相对路径进提示与右键复制（省略不失信息）；
3) SessionState 新增 layout_chosen：首用默认写作布局（章节树≤240、工具面板与
   空闲任务/结果 Dock 收起、章节目录默认收起）+ 视图菜单「恢复写作布局」
   （只改 Dock 显隐/尺寸；正文、草稿、标签、滚动、预览、主题不变）；有效旧会话优先；
4) Ctrl+F 当前章 / Ctrl+Shift+F 项目全文 / 编辑器焦点 Ctrl+B/Ctrl+I（WidgetShortcut 作用域，
   非编辑器输入框不受影响）；分支入口改标「切换分支…（编辑器外 Ctrl+B）」；Esc 关临时层回焦点。
验证命令与报告：
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
python scripts/tests/run_tests.py --junit analysis/ui-polish-B.xml test_ui_polish_layout_session.py \
  test_ui_polish_toolbar.py test_safety_recovery.py test_recovery_entries.py test_core_hidpi_layout.py \
  test_v31_registry_display.py test_v33_editor_wiring.py test_v26_ui_workflows.py test_gui_services.py \
  test_action_positioning.py test_command_palette.py
报告 analysis/ui-polish-B.xml（11 文件 / 0 失败）；几何证据 analysis/ui-polish-B-geometry.txt。
实测几何（离屏，DPR=1.0 / logicalDpi=96 / Sans Serif 9pt）：
- 1280×720：正文 614×498（≥560×320），章节树 240，工具面板/任务面板均收起；
- 1024×640：正文 461×418，关键动作可见且有可点几何，「更多 ▾」溢出出现。
实机缺项：真实 DPI/输入法仍归 5.3。
```

### UI-C（3.1～3.4）

```text
批次：UI-C；完成编号 3.1/3.2/3.3/3.4；tasks 12/20
本批补的差额：
1) 新增 doc_tool/ui/export_rounds.py（纯模型：逐格式状态/可打开/失效判定 + 按项目保留最近 12 轮引用）
   与 doc_tool/ui/export_results_view.py（非模态成果页：轮次选择 + 逐文件打开/定位 + 三个恢复动作）；
   TaskDock 增加 show_results；ProjectBar 增加「成果（N）」入口；
2) 出稿完成不再只在模态框里：结果同时进入成果页与状态栏，普通完成不抢焦点；
3) 「补这次成果」改用旧捕获与原轮报告（不传当前缓冲）、「按当前修改重新生成」收集缓冲后建新 current-buffer 轮、
   「换目录并重新导出」明示来源并建新轮（取消选择保留旧成果），三者全部走既有 TaskRunner（忙时只拒绝重复启动）；
4) 重开项目沿用既有 export-result.json 恢复最近一轮；失效路径不误开、给重新定位/重新生成提示。
验证命令与报告：
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
python scripts/tests/run_tests.py --junit analysis/ui-polish-C.xml test_ui_polish_results.py \
  test_ui_polish_quick_export.py test_core_export_ui.py test_core_export_snapshot.py test_core_gui_loop.py \
  test_v32_delivery_ui.py test_v32_delivery_progress.py test_gui_services.py test_safety_recovery.py
新增 14 项用例覆盖：部分成功逐文件状态、失效路径、轮次保留与项目隔离、迟到结果、忙时不覆盖、取消保留。
原有模态断言（test_core_export_ui.py / test_core_export_snapshot.py）保留未删除。
```

### UI-D（4.1～4.4）

```text
批次：UI-D；完成编号 4.1/4.2/4.3/4.4；tasks 16/20
本批补的差额：
1) 新增 doc_tool/ui/delivery_form_dialog.py：成员/变体/格式/目录表单 → 原 batch 格式（schema 1）→
   contract.parse_plan 校验 → 写 batch.json；合法成员可执行、失效成员就地提示并可移除、全部无效保留输入；
   入口改为「新建批次… / 打开已有计划…」（保留高级文件路径，默认仍落到原有打开流程）；
2) 模块库：空库给真实下一步；「从当前章节创建模块…」标清当前未保存缓冲/已保存来源（缓冲优先，不读旧磁盘）、
   「选择已有模块库…」、「安装所选模块到项目」（明确版本固定引用）、「插入所选模块」（固定引用/复制正文），
   插入走既有编辑器事务可一次撤销，引用经 resolve_text 解析无错误；
3) AssistPanel 改为「资料 / 建议」切页，出处与差异详情两页共用；保留插入/采纳/撤销/建议导出；
   无范围时可「添加资料范围…」（只读加入模块库并重装助手），provider 未启用时仍为折叠文案。
验证命令与报告：
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
python scripts/tests/run_tests.py --junit analysis/ui-polish-D.xml test_ui_polish_advanced.py \
  test_v30_reuse_ui.py test_v32_delivery_ui.py test_v32_delivery_progress.py test_v33_panel_reachability.py \
  test_v33_adoption_editor.py test_gui_services.py test_command_palette.py test_ui_polish_acceptance.py
报告 analysis/ui-polish-D.xml（9 文件 / 0 失败）。
被更新的 GUI 断言（保留业务/来源断言）：test_v30_reuse_ui.py 的假对话框构造函数加入 **kwargs（入口新增缓冲/插入回调）、
投递入口测试改为经 _ask_delivery_mode 的明确选择，断言「开始交付」与 TaskRunner 启动不变。
```

### UI-E（5.1/5.2 已完成；5.3 待实机；5.4 见最终回归记录）

```text
5.1：scripts/tests/test_ui_polish_acceptance.py::ClosedLoopAcceptanceTests 走真实入口，
    证据 analysis/ui-polish-5.1-closed-loop.txt（步骤、强制弹窗 0、captureId/sourceMode、产物路径）。
5.2：GeometryThemeEvidenceTests 覆盖 1280×720 / 1024×640 / 1920×1080 × 深/浅主题、长中文名、
    面板展开/恢复/重开，并在离屏 1 / 1.25 / 1.5 三个缩放各跑一次；
    几何 evidence analysis/ui-polish-5.2-geometry.txt，截图 analysis/ui-polish-acceptance/{1,1_25,1_5}/*.png（共 21 张）。
    runner 新增 --env KEY=VALUE（例如 --env QT_SCALE_FACTOR=1.25）以复现缩放证据。
5.3：未执行。缺项＝真实 Windows 125%/150% 缩放、中文输入法组合输入、Microsoft Word 等待/安全取消试点；
    复验步骤＝在实机上以 125%/150% 显示缩放打开项目，检查正文/按钮几何与文字裁切；用微软拼音连续输入并观察
    组合事件不被打断；在真实 Word 占用/未安装两种情形下发起正式出稿与取消，确认等待安全边界与已完成产物保留。
```

### UI-E 5.4（最终回归与结构校验）

```text
命令 / 结果：
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
python scripts/tests/run_tests.py --junit analysis/ui-polish-final.xml
=> 最终全量回归：157 个测试文件 / 0 失败 / 1608s（analysis/ui-polish-final.xml，日志 analysis/ui-polish-final.log）
openspec validate product-ui-interaction-polish --strict
=> Change 'product-ui-interaction-polish' is valid（结构有效）

基准与本次修复：
- 工作树干净起点（HEAD 2e5be72）的全量为 149 文件 / 3 失败（analysis/ui-polish-baseline-full.xml）：test_final_handover_report.py（报告时间戳）、
test_v30_content_reuse.py、test_v30_reuse_entry.py；本包未改动这三处业务，最终回归中三者均通过（时间戳与运行环境相关，不作代码结论）。
- 新增 8 个控件/接线测试文件已登记进 scripts/tests/run_tests.py 默认清单（149 → 157）。
- run_tests.py 新增 --env KEY=VALUE，用于复现 5.2 的离屏缩放证据（如 --env QT_SCALE_FACTOR=1.25）。

代码失败修复（修复后才勾 5.4）：
- test_core_export_ui.py 的「更换目录」用例此前经模态结果框驱动并跨 _poll 关闭窗口：新入口会经 _ask_delivery_mode 询问，
  导致 pending 后台任务在窗口关闭时再次进入未打补丁的模态框而永久阻塞全量回归。已将这两条用例改为直接驱动 _on_change_export_destination
  （被保护的断言不变：current-buffer 必须携带编辑器缓冲、saved 来源不得注入缓冲、目标目录生效），并新增 ChangeDirectoryActionTests。
- test_v32_delivery_ui.py / test_v32_delivery_progress.py 按新入口明确选择「打开已有计划」（_ask_delivery_mode），
  「开始交付」「只重试未完成项」「补刷新（正式稿）」等原文案与实际 TaskRunner 启动断言全部保留。
- test_v30_reuse_ui.py 的假对话框构造函数加入 **kwargs（入口新增缓冲/插入回调），业务断言不变。

被更新的 GUI 断言清单（均保留业务/来源保护）：
- test_gui_services.py：主区拖放改为导入路由（互转卡自身拖放/无坐标桩事件仍走互转）；拖放高亮同时覆盖两个拖放区；
  向导 NextButton 文案改为「调整章节与样式映射（可选）」（1.3 的副入口语义）。
- test_action_positioning.py：顶部「导出 Word」成为 primary，正式出稿降为 secondary（顺序与文字断言保留）。

文档更新：
- docs/使用说明.md 新增「页面交互优化（本包 20 项）使用要点」（导入/布局/快捷键作用域/成果三动作/高级首用/已知边界）；
- docs/product-ui-interaction-final-plan.md 新增「8. 实施进展」（计划口径不变，记录实际批次状态）。
```

## 完成判定与实机缺项

每项实际实现和直接验证通过才勾选。5.3包含真实Windows缩放、中文输入法和Word等待/安全取消；缺环境可记录但保持未勾选。5.4的文档/回归/strict独立执行，不因5.3待验收停下。

最终可能出现“代码及自动验证可执行项完成，19/20，5.3实机待验收”；如部分其他任务未完成，逐项列出真实编号。不能为了达到20/20把离屏或对话方案冒充实机。现有归档和发布条件沿原流程，普通UI实施不以旧包归档结束为前置。

## 可复制给 Codex 的持续执行指令

```text
在 D:\ai_develop_project_space\doc-tool 执行最终页面交互计划，使用 openspec-apply-change，change 为 product-ui-interaction-polish。

先阅读适用的 AGENTS.md、docs/product-ui-interaction-final-plan.md、docs/product-ui-interaction-execution.md、docs/product-ui-interaction-research.md，以及本 change 的 proposal/design/specs/tasks。运行 openspec status 和 openspec instructions apply，按返回的真实上下文路径继续。核对 HEAD、工作树、已完成勾选和已有服务接口，继承当前未提交实现；若你正在处理已授权批次，先完成该批直接验证，再进入此 UI 包。

依次执行 UI-A→UI-B→UI-C→UI-D→UI-E 的20项，只补实际差额。优先交付首页导入→未保存编辑→顶部快速Word→逐文件成果→继续修订。复用既有 TaskDock/ResultState、TaskRunner、SessionState、CORE 捕获/导出、模块和批次队列；每项从真实Qt按钮/菜单接通并运行必要直接验证，再更新tasks和本包执行台账。新增相关测试登记原runner，整合后执行一次最终全量回归及OpenSpec strict。

默认普通模式尽力跑通，Word/Git/模型缺失、某格式失败、坏可选配置等仅影响对应动作，保留可用成果并给下一步。补这次成果使用旧捕获；按当前修改重新生成建立新current-buffer轮；换目录并重新导出显示真实范围/来源并新建轮。未保存缓冲不写回或清脏，旧产物不被覆盖，正式成功沿原状态权威。有效旧会话优先恢复，显式恢复布局只改布局。

普通实现选择及技术错误自行排查修复，不在每批结束等待确认。缺真实DPI/输入法/Word试点时，记录原因和复验步骤，5.3保留未勾选，继续5.4及其他无依赖任务。已有环境失败与本次代码回归分开，不能通过删测试、弱化数据/来源断言或伪造通过推进。遇到接口差额补最小适配；只有剩余工作均无可继续路径且确需用户信息时停下并说明具体原因。

持续执行到本包所有可执行项完成，上下文压缩后从tasks/台账续接。本指令范围为本UI包的本地实施和验证；结束时报告真实完成编号、用户入口、验证/成果路径、可用兜底、实机待验收及下一任务，不自动扩大到RD等其他change或远程发布。
```

本页提供执行指令，本次只定稿规划，未启动UI业务实现、未向其他会话发送指令。
