# UI2 执行台账与持续指令

日期：2026-10-02。本包 `product-ui-experience-next`，6 批 / 26 项；当前 0/26 实施项完成。计划基于当时 `2e5be72` 工作树，不要求清空、提交或回滚其他任务的改动。

## 1. 输入与状态

- [产品计划](product-ui-experience-next-plan.md)
- [提案](../openspec/changes/product-ui-experience-next/proposal.md)、[设计](../openspec/changes/product-ui-experience-next/design.md)
- [4份能力规范](../openspec/changes/product-ui-experience-next/specs)、[26项任务](../openspec/changes/product-ui-experience-next/tasks.md)
- [总路线图](product-master-roadmap.md)、[普通流程与兜底](product-flow-fallback-policy.md)

上一轮 `product-ui-interaction-polish` 读取为 19/20，未完成项是实机验证 5.3；该实现与任务记录保留。本包没有启动业务实施，没有向其他会话发送消息。

| 批次 | 编号 | 当前 | 完成后记录 |
|---|---|---|---|
| UI2-A | 1.1～1.4 | 完成 4/4 | before/after 审计、主条零裁切、共享动作/焦点（见下方 UI2-A 记录） |
| UI2-B | 2.1～2.4 | 待执行 | 首页继续/固定/过滤、兼容会话 |
| UI2-C | 3.1～3.5 | 待执行 | 真实路径、位置历史、阅读与脏缓冲 |
| UI2-D | 4.1～4.5 | 待执行 | 表单请求、导出范围/来源、实际文件 |
| UI2-E | 5.1～5.4 | 待执行 | 窄面板、历史身份、局部成功与取消 |
| UI2-F | 6.1～6.4 | 待执行 | 场景/回归/实机边界/交接 |

## 2. 本次规划证据

隔离 Qt offscreen + 显式中文字体审查，12 张截图；合成项目、隔离 Path.home，未用真实用户工程，未运行 Word/IME。几何见 [widget-audit.json](../analysis/ui-experience-next-audit-20261002/widget-audit.json)，可复现脚本见 [inspect_ui.py](../analysis/ui-experience-next-audit-20261002/inspect_ui.py)。

- 1024×640 项目条多个按钮被压窄，导出 Word 在 1280 也低于完整尺寸需求。
- 成果请求 340 宽实际 402、辅助请求 340 实际 415；拟改善窄面板。
- 导出设置/导航/history 身份问题来自静态接口审查，不能当作已修复或已复现的业务结论。
- OpenSpec 与链接检查均通过；它们只验证计划结构，不是业务验收。

## 3. 每批证据模板

```text
批次/任务：
实际 HEAD 与相关工作树变化：
真实菜单/按钮和操作步骤：
新增用户可用行为：
继续/回退/局部失败：
来源/范围/轮次/产物（适用时）：
检查命令、退出码、报告/截图：
平台、字体、requested/actual几何：
已验证、未验证、既有失败：
剩余直接任务：
```

## 3.1 每批实施记录

### UI2-A 视觉与工作台层级（1.1～1.4）

```text
批次/任务：UI2-A；编号 1.1/1.2/1.3/1.4；tasks 4/26
实际 HEAD 与相关工作树变化：
HEAD 2e5be72；保留 product-ui-interaction-polish 全部未提交实现，未回滚任何其他改动。
本批改动：新增 doc_tool/ui/action_overflow.py（共享溢出控制器）；project_bar.py 接入
主要动作常驻 + 次级动作按真实宽度进入「更多 ▾」；名称/就绪状态省略且全值可取。
doc_tool/ui/main_window.py 未改（沿用原 QAction/handler/可用性）。

真实菜单/按钮和操作步骤：
1) 打开项目 → 顶部项目条显示「导出 Word」「成果」「项目检查」（1024/1280）或再含
   「快速构建」「正式出稿」「关闭项目」（1920）；
2) 窄窗口点「更多 ▾」→ 菜单列出被收起动作（快速构建/正式出稿/收起摘要/关闭项目）；
3) 右键文档名 → 复制文档名称 / 复制项目路径。

新增用户可用行为：
- 主要动作永不裁切、不出窗口；次级动作按可用宽度自适应，仍可从「更多」或原菜单访问；
- 「更多」菜单项与原地按钮共用同一 QAction（enabled/tooltip/triggered 一致）；
- 文档名/项目路径省略显示但可从提示与右键复制取得全值；
- Ctrl+E 只在菜单 QAction 声明一次，项目条按钮不再重复绑定。

继续/回退/局部失败：
窗口变宽时被收起动作自动回到原位；控件销毁后排队复核安全退出（不抛已删除对象）。

来源/范围/轮次/产物（适用时）：不涉及（本批为视觉/层级）。

检查命令、退出码、报告/截图：
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'
python scripts/tests/run_tests.py --junit analysis/ui2-A2.xml test_ui2_visual_hierarchy.py \
  test_home_experience_iteration.py test_action_positioning.py test_core_entries_ui.py test_branch_ui.py \
  test_gui_services.py test_command_palette.py test_ui_polish_quick_export.py test_ui_polish_layout_session.py
=> 9 文件 / 0 失败（退出码 0）
python analysis/ui-experience-next-audit-20261002/audit_ui.py analysis/ui-experience-next-after-20261002
=> 12 视图 after 快照 + 截图 + widget-audit.json

平台、字体、requested/actual几何：
Qt offscreen，显式注册 Microsoft YaHei / YaHei UI / Consolas / Segoe UI Emoji；DPR=1。
before（analysis/ui-experience-next-audit-20261002/widget-audit.json）：
  1024 项目条压缩动作 5 个（导出 Word 74<102、项目检查 57<78、快速构建 58<78、正式出稿 57<78、关闭项目 58<78）；
  1280 导出 Word 74<102。
after（analysis/ui-experience-next-after-20261002/widget-audit.json）：
  1024 压缩 0（项目检查 78 在原位；快速构建/正式出稿/关闭项目进入「更多 ▾」55px）；
  1280 压缩 0（导出 Word 102、成果 52、项目检查 78、快速构建 78、正式出稿 78）；
  1920 压缩 0（含关闭项目 78）；正文矩形 1280 为 613×452（与 before 相同，未牺牲正文）。

已验证、未验证、既有失败：
已验证：主按钮完整可读、更多可达且共享 handler、Ctrl+E 单一声明、长名/路径全值可取。
未验证：真实 Windows 缩放/IME/Word（归 6.3，保持未勾选）；离屏不做实机结论。
既有失败：无新增（9 个相关文件全绿）。

剩余直接任务：UI2-B 首页继续工作（2.1～2.4）。
```

## 3.2 每批实施记录

### UI2-A 视觉与工作台层级（1.1～1.4）

```text
本批补的差额：新增 doc_tool/ui/action_overflow.py（共享溢出控制器：主要动作常驻、次级动作按真实宽度进入「更多 ▾」，
  菜单项与原地按钮共用同一 QAction）；project_bar.py 接入溢出、文档名省略与右键复制、就绪状态可省略；
  布局后发现主要动作被挤压时继续溢出次级动作直到它们恢复完整宽度。
真实入口/步骤：打开项目 → 顶部「导出 Word」「成果」完整可读；窄窗口点「更多 ▾」取回检查/快速构建/正式出稿/分支/关闭；
  文档名右键可复制名称与完整项目路径。
检查命令/报告：python scripts/tests/run_tests.py --junit analysis/ui2-A2.xml test_ui2_visual_hierarchy.py
  test_home_experience_iteration.py test_action_positioning.py test_core_entries_ui.py test_branch_ui.py test_gui_services.py
  test_command_palette.py test_ui_polish_quick_export.py test_ui_polish_layout_session.py ⇒ 9 文件 / 0 失败。
几何证据（离屏，显式注册中文字体）：
  before analysis/ui-experience-next-audit-20261002/widget-audit.json：1024 项目条压缩 5 个动作（导出 Word 74<102）。
  after  analysis/ui-experience-next-after-20261002/widget-audit.json：1024/1280/1920 项目条压缩 0（主动作 102/52），
  次级动作按宽度进入「更多 ▾」；正文矩形与 before 相同（1280 为 613×452）。
实机缺项：真实 Windows 缩放/IME 仍归 6.3，离屏不作实机结论。
```

### UI2-B 首页继续工作（2.1～2.4）

```text
本批补的差额：RecentEntry 新增 pinned 个人偏好 + set_recent_pinned（不移动/删除工程）；
  首页卡片只显示名称/类型/最近打开/当前位置，完整路径进提示；新增类型筛选与已有搜索组合；
  新增固定/取消固定与图标文字兑底；SessionState 新增 cursor_positions（恢复顺序：先光标后滚动）。
验证：python scripts/tests/run_tests.py --junit analysis/ui2-B.xml test_ui2_home_continue.py test_ui2_visual_hierarchy.py
  test_home_experience_iteration.py test_gui_services.py test_core_entries_ui.py test_ui_polish_layout_session.py
  test_ui_polish_entry_drop.py test_safety_recovery.py test_recovery_entries.py test_v26_ui_workflows.py ⇒ 10 文件 / 0 失败。
真实行为：固定项置顶并重启后保留；类型+关键词组合过滤；旧/坏字段按项回退；失效项目可重新定位（取消后其他项目仍可打开）；
  继续工作复用原标签/滚动/草稿恢复并补回光标位置。
```

### UI2-C 正文导航与阅读（3.1～3.5）

```text
本批补的差额：新增 doc_tool/ui/navigation_history.py（最多 50 条、相邻合并、新导航清前进、项目隔离、
  重放抑制按目标位置生效）；主窗口新增导航条（后退/前进/真实章节路径/定位当前章/复制路径）与 Alt+←/→；
  EditorPanel 新增写作/对照/阅读与字号档位（Ctrl+= / Ctrl+- / Ctrl+0）；SessionState 新增 view_mode/font_step。
验证：python scripts/tests/run_tests.py --junit analysis/ui2-C.xml test_ui2_navigation.py test_safety_recovery.py
  test_ui2_home_continue.py test_ui2_visual_hierarchy.py test_gui_services.py test_ui_polish_layout_session.py
  test_ui_polish_toolbar.py test_v33_editor_wiring.py test_v26_ui_workflows.py test_content_operations.py ⇒ 10 文件 / 0 失败。
真实行为：脏缓冲跳章后后退回原位置（未保存文本与撤销栈保持、不加载旧正文）；
  同一位置重复导航合并；新导航清空前进支路；项目切换清空；阅读字号不改正文/撤销栈/Word 模板。
  审计修复：恢复滚动必须在光标之后（否则被自动滚动顶掉）；重放抑制必须按目标位置且失败时清除。
```

### UI2-D 导入与导出设置（4.1～4.5）

```text
本批补的差额：新增 doc_tool/ui/export_settings_dialog.py（格式/范围/来源/目录/名称/版式/高级，
  纯适配到 ExportRequest/ExportScope/LayoutProfile）；主窗口新增「导出设置…」菜单动作与 _submit_export_request（原 TaskRunner）；
  成果页新增「更改设置…」，带入从真实报告读取的原格式/范围/目录（不从 scope_text 反解析）。
验证：python scripts/tests/run_tests.py --junit analysis/ui2-D.xml test_ui2_export_settings.py test_core_export_ui.py
  test_core_export_snapshot.py test_ui_polish_results.py test_ui_polish_quick_export.py test_ui_polish_advanced.py
  test_gui_services.py test_core_scope_presets_batch.py test_core_cli_export.py test_v32_batch_delivery.py ⇒ 10 文件 / 0 失败。
真实产物：所选章 + 当前缓冲导出 Word/HTML/源码包，读回正文含本轮标记且源文件未被写回；
  已保存来源排除脏内容；空勾选整份回退在摘要与提示里明示；快捷 Word 不继承严格/范围/来源。
```

### UI2-E 成果与高级面板（5.1～5.4）

```text
本批补的差额：新增 doc_tool/ui/flow_row.py（按真实宽度横排/竖排，最小宽度取最宽子控件）；
  成果面板与辅助面板的动作行接入；补原轮前校验 roundId/captureId，目录索引被新轮覆盖时拒绝补错轮。
验证：python scripts/tests/run_tests.py --junit analysis/ui2-F.xml …（含 test_ui2_panel_productivity.py）⇒ 13 文件 / 0 失败。
340px：成果面板与辅助面板均能缩到 340px，动作竖排且字不被压缩（专项用例断言）。
```

### UI2-F 6.1/6.2（场景与回归）

```text
6.1：scripts/tests/test_ui2_acceptance.py 跑真实入口闭环并保存证据：
  analysis/ui2-acceptance-20261002/ui2-closed-loop.json（步骤/强制弹窗数 0/提交次数/roundId/captureId/产物）；
  analysis/ui2-acceptance-20261002/ui2-geometry.json 与 6 张三尺寸×深浅主题截图（含面板 340/420/700 记录）。
6.2：UI2-A～E 各批直接回归均为 0 失败；中途全量回归 157 文件 / 0 失败（analysis/ui2-B-full.xml，UI2-A～C 之后）。
  本轮修复：恢复滚动顺序、重放抑制作用域、主要动作被压缩时继续溢出、框架尺寸断言失效。
6.3：未执行（缺真实 Windows 缩放/IME/Word），复验步骤见下方「待实机」。
```

## 3.3 待实机复验步骤（6.3）

1. 在真实 Windows 上分别用 125% / 150% 显示缩放打开同一项目，检查项目条、导航条、正文与 340px 面板的文字是否裁切、按钮是否可点；
2. 用微软拼音连续输入中文与符号，确认组合输入不被 Ctrl+B/I 或快捷键打断，Esc/切页符合预期；
3. 在 Word 占用与未安装两种情形下发起正式出稿与取消，确认等待安全边界、已完成产物保留与焦点返回。

## 3.4 最终回归与结构校验（6.4）

```text
命令：python scripts/tests/run_tests.py --junit analysis/ui2-final.xml
结果：163 个测试文件 / 0 失败 / 1757s（analysis/ui2-final.xml，日志 analysis/ui2-final.log）。
该次运行在注册 test_ui2_acceptance.py 之前启动；该文件单独运行通过（见上方 6.1）并已补登记进 runner，
所以 runner 清单现为 164 个文件（= 163 + test_ui2_acceptance.py）。
命令：openspec validate product-ui-experience-next --strict
结果：Change 'product-ui-experience-next' is valid（仅证明结构，不是业务验收）

注册新增用例（均已进入 runner 默认清单，文件数 149（上一轮基线）→ 163）：
  test_ui2_visual_hierarchy.py、test_ui2_home_continue.py、test_ui2_navigation.py、test_ui2_reading_view.py、
  test_ui2_export_settings.py、test_ui2_panel_productivity.py、test_ui2_acceptance.py。
共新增 71 项用例（项级），全部在最终回归中通过。

本轮修复的真实回归（修复后才勾任务）：
1. 恢复滚动位置必须在恢复光标之后（否则被自动滚动顶掉）；
2. 重放抑制改为按目标位置生效，失败或到达别处自动作废（否则后续主动导航被误判为重放）；
3. 主要动作在真实布局下被挤压时，继续溢出次级动作直到它们恢复完整宽度；
4. 项目条在显示/resize/主题变化时重新计算溢出（否则会用旧宽度裁切文字）；
5. 框架断言失效：旧「关闭项目按钮常驻」用例改为在足够宽度下验证（窄窗口进入「更多」是意图行为）；
   首页卡片断言改为名称/目录名 + 完整路径在提示（UI2-B 意图）。

6.3：未执行，保持未勾选（缺真实 Windows 125%/150%、中文 IME、Word 等待/取消环境）。
```

## 4. 可复制给 Codex 的执行指令

```text
在当前 doc-tool 工程实施新交互包 product-ui-experience-next，使用 openspec-apply-change。先阅读 AGENTS.md（如有）、docs/product-ui-experience-next-plan.md、docs/product-ui-experience-next-execution.md、docs/product-flow-fallback-policy.md，以及这个 change 的 proposal、design、4份 specs 和 tasks。

核对实际 HEAD、工作树、已有实现和任务勾选。上一轮 product-ui-interaction-polish 的实现保留，不重做旧20项，不回滚其他任务改动，不把旧实机5.3或归档作为全局前置条件。新任务已被最新代码满足则补真实证据，不重写。

默认按 UI2-A→B→C→D→E→F，逐项持续实现26项中的可执行工作。每批跑通真实GUI入口和直接场景，保存证据后勾任务、更新独立台账，然后继续下一批。不要因每批结束反复停下请求确认，普通实现选择自行判断。上下文压缩后从tasks和台账继续。

核心目标：中文长名/窄窗口主按钮可读；首页继续/固定；章节路径、后退前进和阅读字号；真实多格式/范围/来源/有限版式导出设置；340px成果/辅助面板；可信历史引用与旧轮报告身份；批次局部恢复。复用原Qt主题、QAction、会话、ExportRequest/ExportScope/LayoutProfile、TaskRunner、报告/OutputState、模块/建议/队列，避免新增第二套业务状态机。

快速Word保留一键整份/当前内容/Word/模板/非严格默认；设置默认能直接提交，高级折叠。缺Word、Git、模型、坏可选配置、单格式/成员失败仅影响对应动作，保留可用文件/有效成员并提供继续、定位、修改设置或重试。不得清空脏缓冲、覆盖用户内容、拿最新索引冒充旧轮、虚报正式成功。

验证实际按钮、请求、位置恢复和产物内容，围绕行为做必要检查。正确中文字体下覆盖1024/1280/1920窗口和340/420/700面板、深浅主题、键盘和长路径，记录离屏局限。Windows缩放、IME、Word实机缺环境时记录复验步骤且对应项保持未勾选，继续其他任务。最终稳定后运行必要全量回归和OpenSpec strict，不能把计划校验或模拟当业务/实机通过。

本指令仅授权本地实施与验证，不自动归档、发布、推送、修改系统安全设置或向别人发送消息。仅在确需用户信息且无合理默认、涉及真实数据不可逆操作或所有剩余工作同一外部阻塞时暂停，写清原因和继续入口。

最后报告实际完成编号、用户可用主流程、验证/截图/产物路径、兜底、剩余实机项与下一任务。不要只提供计划后结束。
```

## 5. 计划结构校验

| 命令/检查 | 实际结果 |
|---|---|
| `openspec validate product-ui-experience-next --strict` | 退出码0，change valid |
| `openspec status --change product-ui-experience-next` | proposal/design/specs/tasks 4/4 完整，可进入实施 |
| `check_plan.py` | 退出码0；6批26项，4能力、18要求、30场景，54个本地链接有效，无错误 |
| `git diff --check -- docs/product-master-roadmap.md` | 退出码0 |

结构证据见 [plan-check.json](../analysis/ui-experience-next-audit-20261002/plan-check.json)。业务实施状态仍为 0/26；不把文档完整计为功能完成。
