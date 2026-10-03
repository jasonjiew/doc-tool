# 2026-10-03 执行前复核

**历史报告入口更新**：本报告保留实施前快照及第6节 EX-1～EX-3 修复事实。四包现已80/84，新的 [实施后审查修复](product-post-implementation-review-20261003.md)和 [V3.7～V3.9计划](product-v37-v39-roadmap.md)为当前入口，不按下方0/84重新开发。

目标用户：企业研发文档团队。复核开始时 HEAD 为 `2e5be72`、UI 实现位于工作树；期间已有任务将实现提交为 `d68b514`，本报告核对了该提交中的相关函数。应用版本仍为 `2.9.0`。本次修改规划与复核资料，业务代码和原任务勾选保持原状。

## 1. 结论与排程

产品方向保持：日常导入/编辑/交付 → 研发联动 → 内容与规范复用 → 大文档提效。UI2 已勾选 25/26，后续四包仍为 0/84；执行队列调整为：

**EX-1～EX-3 导出修正 → RD 工作区 → V3.4 表格编辑 → V3.5 规范包制作 → V3.6 大文档性能。**

三个修正属于现有 CORE/UI2 契约的实现差额，无需重做已实现的页面或增加一个大版本。先完成这些小修正与直接验证，再进入后续 21 批/84 项。旧包实机、人工试点及归档缺项单列；缺 Word 等条件时继续不依赖该条件的功能。

## 2. 三个已确认的导出差额

下表是修正台账。执行 Codex 在真实修复及回归后填写结果、证据和勾选；初始诊断 JSON 保留为发现时证据。

- [x] EX-1 原捕获缺失时，补旧轮不得静默读取当前内容。（工作树已实施，见第 6 节）
- [x] EX-2 已知捕获身份缺失或不匹配时，不得直接放行旧轮重试。（工作树已实施，见第 6 节）
- [x] EX-3 选章成果按当前修改重新生成时，保留原结构化范围。（工作树已实施，见第 6 节）

| 编号 | 已观察的行为 | 需要实现的用户行为 |
|---|---|---|
| EX-1 | `retry_export_formats` 遇到不存在的 `snapshotWorkDir`，进入 `run_project_export` 的新捕获分支 | 保留旧成果；需要原正文的缺项保持待处理，提供“按当前内容生成新轮”。原 DOCX 等成果若身份与来源可核验，允许继续其可独立完成的刷新/转换步骤 |
| EX-2 | 所选视图有 `captureId`，同 `roundId` 报告缺少 `captureId`，`_round_identity_matches` 返回 True | 已知身份不能被缺失值满足。缺字段的历史仍可浏览；若可从可信报告/捕获元数据恢复身份，补齐后再允许原轮重试；否则提供新轮入口 |
| EX-3 | 原报告 `scope.kind=chapters`，`_on_regenerate_round` 提交 `scope.kind=project` | 从真实原报告带入范围、格式与目录，用当前内容建立新捕获/新轮。范围缺失或章节失效时打开设置并显示实际选择，用户明确提交；不从展示文字反解析范围 |

来源位置：`doc_tool/application/project_export.py` 的 `run_project_export` / `retry_export_formats`；`doc_tool/ui/main_window.py` 的 `_round_request` / `_report_for_round` / `_round_identity_matches` / `_on_regenerate_round`。

对应现有规范：[旧轮报告身份核对](../openspec/changes/product-ui-experience-next/specs/desktop-panel-productivity/spec.md)、[范围与再生成](../openspec/changes/product-ui-experience-next/specs/desktop-export-configuration/spec.md)。原 UI2 4.4/5.2 的勾选是已实施记录，本复核补充了此前用例未覆盖的反例；执行时修正这些差额并关联证据，不重置原任务编号。

### 修正的直接验收

1. 将三项诊断变成有期望断言的回归用例；先确认旧代码失败，再修复。缺捕获不得调用当前正文捕获，也不得把新内容结果合入旧轮；已存在的成果仍可打开。
2. 覆盖 GUI 和后端重试入口：旧轮 roundId 不同、captureId 不同、已知 captureId 在报告中缺失、原捕获不存在。历史缓存缺字段可从可信真实元数据补齐，不能仅靠缓存或相同 roundId 宣称同源。
3. 在两章样例中仅选一章，修改该章未保存缓冲后从成果“按当前修改重新生成”：新成果包含新标记、不含未选章，源文件未被写回，产生新 captureId/roundId。当前章范围同样覆盖。
4. 原范围无法恢复时，设置页显示问题与实际范围，保留可用输入；整份生成是用户可见的选择。无 Word 可验证 HTML/源码包与请求，真实 Word 项另列。

这三项只限制不能证明来源或范围的动作。日常快速 Word、查看旧成果、编辑和明确的新轮路径继续可用，不增加全局检查门禁。

## 3. 本轮验证与证据边界

本轮使用 Windows 上的 bundled Python 3.12.14、现有 `tmp/v26-test-deps` PyYAML、仓库 runner 和 `QT_QPA_PLATFORM=offscreen`。直接执行 UI2 七个测试文件，**66 个 unittest 用例通过**；另执行一个诊断脚本，确认 **3 个差额**。

初次 acceptance 截图中文缺字，不能据此判断文字可读性。随后仅在复核包装脚本注册现有 Microsoft YaHei/Consolas 字体，检查“章”字实际可渲染，再重复闭环/窗口/面板三个用例，均通过。两轮证据目录分开保留；这是3个用例的补验，不是新增3个独立用例，也不是业务代码修复。

| UI2 文件 | 用例数 | 本轮结果 |
|---|---|---|
| test_ui2_visual_hierarchy.py | 10 | 通过 |
| test_ui2_home_continue.py | 9 | 通过 |
| test_ui2_navigation.py | 13 | 通过 |
| test_ui2_reading_view.py | 7 | 通过 |
| test_ui2_export_settings.py | 15 | 通过 |
| test_ui2_panel_productivity.py | 9 | 通过 |
| test_ui2_acceptance.py | 3 | 通过，独立输出目录 |

证据：[本轮 runner XML](../analysis/product-review-20261003/direct-checks.xml)、[三项诊断 JSON](../analysis/product-review-20261003/export-boundaries.json)、[诊断脚本](../analysis/product-review-20261003/probe_export_boundaries.py)、[闭环与几何证据](../analysis/product-review-20261003/ui2-acceptance)。XML 外层是 8 个执行项、failures=0，其中一个是观察脚本；它成功记录缺陷并退出 0，不能把这个退出码当作三项需求已通过。该脚本使用隔离样例、后端捕获拦截、真实 GUI 处理函数及提交观察；未执行 Word 刷新，也未将诊断等同于完整的按钮到成果验收。

字体补验：[复验 XML](../analysis/product-review-20261003/font-checks.xml)、[实际字体记录](../analysis/product-review-20261003/ui2-acceptance-with-fonts/font-environment.json)、[有中文字形的截图与闭环](../analysis/product-review-20261003/ui2-acceptance-with-fonts)。此轮才用于中文可读性观察，仍是 Qt offscreen。

复验命令（PowerShell，工作目录为仓库根目录）：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:/ai_develop_project_space/doc-tool/tmp/v26-test-deps'
$env:QT_QPA_PLATFORM='offscreen'
$env:PRODUCT_REVIEW_LOAD_FONTS='0'
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/tests/run_tests.py --junit analysis/product-review-20261003/direct-checks.xml test_ui2_visual_hierarchy.py test_ui2_home_continue.py test_ui2_navigation.py test_ui2_reading_view.py test_ui2_export_settings.py test_ui2_panel_productivity.py D:/ai_develop_project_space/doc-tool/analysis/product-review-20261003/run_ui2_acceptance.py D:/ai_develop_project_space/doc-tool/analysis/product-review-20261003/probe_export_boundaries.py
$env:PRODUCT_REVIEW_LOAD_FONTS='1'
& 'C:/Users/18098/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' scripts/tests/run_tests.py --junit analysis/product-review-20261003/font-checks.xml D:/ai_develop_project_space/doc-tool/analysis/product-review-20261003/run_ui2_acceptance.py
```

上述是发现时诊断的复现入口；执行修复后的回归应保存到新的报告路径，保留初始证据。

历史 `analysis/ui2-final.xml` 为 **163 个测试文件 / 0 失败**；它启动时未包含随后补登记的 acceptance 文件。当前 runner 默认清单 **164 个文件**；本次补验了 acceptance，但没有重跑全部 164 个文件。UI2 台账原“新增 71 项全部进入最终回归”的表述改为实际七文件/66项专项证据。

真实 Windows 125%/150% 显示缩放、中文 IME、Word 等待/取消与版式仍待实机验收。离屏截图和 DOCX 内容读回不替代这些验收。

易用性观察 UI-V1：字体正常的 [1024深色截图](../analysis/product-review-20261003/ui2-acceptance-with-fonts/window-1024x640-dark.png) 中，“更多/标题”工具按钮在浅背景上的文字偏淡。现有几何断言没有验证这个对比度；后续接入页面时从实际入口复查，复现后沿用原主题补相关控件状态，不重做主题系统。此项可随功能推进，不作为四包开始的前置条件；125%/150%及真实桌面外观另验。

## 4. 当前任务快照

| change | 已勾选/总项 | 未勾选项 |
|---|---|---|
| product-core-import-export | 39/40 | 8.5 |
| product-v30-content-reuse | 31/32 | 7.4 |
| product-v31-team-workflow | 25/27 | 6.3、6.5 |
| product-v32-batch-delivery | 31/32 | 7.5 |
| product-v33-authoring-assistance | 25/26 | 6.2 |
| product-ui-interaction-polish | 19/20 | 5.3 |
| product-ui-experience-next | 25/26 | 6.3；另有本报告 EX-1～EX-3 修正 |
| product-rd-workspace-experience | 0/24 | RD-A / 1.1 起 |
| product-v34-table-authoring | 0/20 | 34-A / 1.1 起 |
| product-v35-standard-pack-authoring | 0/20 | 35-A / 1.1 起 |
| product-v36-large-document-performance | 0/20 | 36-A / 1.1 起 |

已勾选不等于覆盖所有反例。表中数量是读取快照，执行时以实时任务、实现和证据重新确认。旧包共有 8 个未勾选项，不能概括为“8 项全是环境问题”；其中还包含证据、规范同步及归档收尾，归档另行授权。后续四包均通过 OpenSpec strict；RD apply instructions 为 ready、0/24。结构通过只说明计划可实施。

## 5. 计划内容的修正

- RD-A 高 schema 与 Mermaid 任务改为先验证现有修复，复现真实残留才补差额。当前高 schema 夹具已按实际版本正则替换，不再预设仍有 schema 1 固定替换缺陷。
- RD-E 复用已实现的 `application/delivery/gui_tasks.py`、`queue.py` 和 `collection_bridge.py`。CORE/V3.2 相关代码已存在，缺适配只补最小接口，集合 UI 不再单独造成员交付协调器或持久队列。
- V3.6 读取现有 CORE 捕获及 V3.0 装配接口，先同机基准、后增量优化。性能目标保持测量目标，未达到时记录原因并继续其他独立项。
- [最终持续提示词](product-execution-confirmed-prompt.md) 统一以上排程与约束；[总路线图](product-master-roadmap.md)、[UI2 台账](product-ui-experience-next-execution.md) 同步当前状态，历史实施证据保留。

结构与证据自检：[review-check.json](../analysis/product-review-20261003/review-check.json)（实时任务数、默认测试清单、内部用例、相关Markdown/本地链接）、[strict-validation.json](../analysis/product-review-20261003/strict-validation.json)（五个change逐项命令结果）。它们不证明未实施的84项功能或三个待修正项已完成。

## 6. 修正实施结果（由执行 Codex 填写）

| 编号 | 修改与真实行为 | 新回归及成果证据 | 状态 |
|---|---|---|---|
| EX-1 | `run_project_export` 在 `prior` 存在时只恢复原轮：原快照不可用时不再调用 `capture_snapshot`，需要原正文的格式保留旧成果并提示“按当前内容生成新轮”；旧 DOCX 仅在 sha256 与登记值相符时才继续补 PDF，否则保留可读 Word 为待刷新。 | `scripts/tests/test_export_round_recovery.py` 的 `OriginalRoundRecoveryTests` 9 项（3 项断言不得重新捕获）；[补原轮回归](../analysis/product-export-fixes-20261003/final-recovery.xml)、[后端相关回归](../analysis/product-export-fixes-20261003/final-backend.xml) | 完成 |
| EX-2 | `_round_identity_matches` 要求已知 `captureId` 必须与非空真实报告相等；`read_export_index` 不再为缺失 `roundId` 伪造新身份；`_snapshot_from_prior` 在缺 roundId/captureId 或快照不可读时返回 None；GUI 补原轮入口在后端任务提交前拦截缺失身份并提示新轮。 | `RoundIdentityTests` 2 项与 `RoundRegenerationTests.test_retry_missing_capture_id_does_not_submit_backend_task`；[GUI/标题回归](../analysis/product-export-fixes-20261003/ui.xml) | 完成 |
| EX-3 | `_on_regenerate_round` 从原报告或生成时视图带入 scope/sourceMode/目录，用当前缓冲生成新的 captureId/roundId；范围缺失或章节失效时打开设置页并显示原因与实际范围，换目录保留原 scope，不反解析展示文字。 | `RoundRegenerationTests` 10 项（选章、当前章、换目录、章节失效、缺 scope、旧视图）；[选章再生成证据](../analysis/product-export-fixes-20261003/scoped-regeneration/chapters/result.json)（新 captureId/roundId、含新标记、不含未选章、源文件 hash 不变） | 完成 |

补充：本次复核重跑了回归 `analysis/product-export-fixes-20261003/recheck-round-recovery.xml`（21 项通过），并修正测试运行器只注入与当前解释器同版本的 `site-packages`（避免 3.12 解释器加载 3.13 的 lxml 扩展）。UI-V1 工具按钮主题映射随 [final-ui.xml](../analysis/product-export-fixes-20261003/final-ui.xml) 保留；真实缩放、IME 与 Word 视觉仍待实机验收。
