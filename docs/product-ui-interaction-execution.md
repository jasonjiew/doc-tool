# 页面交互优化执行台账

最终复核：2026-10-02。唯一change：`product-ui-interaction-polish`。入口：[最终计划](product-ui-interaction-final-plan.md)，依据：[调研](product-ui-interaction-research.md)，实时进度：[tasks](../openspec/changes/product-ui-interaction-polish/tasks.md)。使用openspec-apply-change，保留已有工作树和其他包任务。

## 计划起始状态

| 批次 | 编号 | 起始实现 | 本包自动验收 | 本包实机验收 |
|---|---|---|---|---|
| UI-A | 1.1～1.4 | 0/4 | 未运行 | 未运行 |
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
