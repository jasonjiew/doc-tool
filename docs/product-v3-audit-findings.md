# V3 / CORE 勾选项独立审计与处置（第十四轮）

方法：为每个 change 启动一个**只读**独立审计代理（不修改仓库，只读代码 + 运行单个测试文件），
逐条核对 `tasks.md` 已勾选项“声称的能力是否真的存在、是否被真实测试覆盖”。
审计覆盖：CORE 8 项高风险勾选、V3.0 8 项、V3.1 8 项、V3.2 全部 31 项、V3.3 全部 25 项。

## 1. 结论概览

| change | 审计项数 | supported | weak | unsupported |
|---|---|---|---|---|
| CORE | 8 | 6 | 2 | 0 |
| V3.0 | 8 | 5 | 3 | 0 |
| V3.1 | 8 | 7 | 1 | 0 |
| V3.2 | 31 | 23 | 8 | 0 |
| V3.3 | 25 | 19 | 6 | 0 |

**没有任何 change 出现“能力完全不存在”的勾选项（unsupported=0），也没有伪造测试结果。**
问题集中在三类：库级能力未接入应用、声称含未实现子项、台账数字过期。

## 2. 已修复（第十四、十五轮）

| 问题 | 处置 |
|---|---|
| CORE 6.2/5.2：「更换目录…」导出丢弃编辑器缓冲，却仍标注“当前编辑内容”（未保存编辑被磁盘内容顶替） | 已修复：该分支在缓冲来源下同样传 `buffer_texts`；新增 2 项回归测试（`test_core_export_ui.py` 5 项通过） |
| V3.2 2.3：`word_busy.acquire` 无生产调用者，跨进程互斥实际不生效 | 已修复：队列在驱动 Word 前 acquire、结束（含异常）release，他人持有时转待刷新；新增 2 项生产路径测试（该文件 9 项通过） |
| V3.2 7.1 / V3 台账：全量回归写“114 文件” | 已更正为 124 文件（1 项环境失败），历史记录加注 |
| V3.2 5.4：引用错误的证据文件 | 已更正为实际用例所在文件 |
| V3.0 8 / 台账：“无声明项目零开销” | 已更正为“不做标记解析（仍有一次章节扫描）” |
| V3.3 6.1：全量回归记录（95 文件 / 6 项失败 / 未注册）过期 | 已更正为当前事实（127 注册文件、1 项环境失败、V3.3 测试已注册） |
| 使用说明第 29 行：声称应用内“菜单/面板/CLI 同 handler” | 已更正为“库级可用”，并在第十五轮接入应用后恢复为“应用内可用” |
| V3.1 4.2 / V3.3 5.3：命令注册表仅库级可用 | **已修复**：`MainWindow` 构建注册表并注册团队/写作辅助命令；「命令」菜单与命令面板都由注册表渲染，点击统一 `handle_item`；菜单/面板视图分离（菜单=可用正式入口，面板=全部含旧入口与原因）；项目切换自动重建；新增 `test_v31_registry_integration.py` 4 项 + 旧等价性断言改为“菜单⊆面板、逐条可用性一致” |

## 3. 本轮改回未勾选（13 项，行内写明已验证范围与缺口）

| change | 任务 | 缺口 |
|---|---|---|
| ~~CORE 3.2~~ | ~~复杂对象无正文占位/章节定位~~ | **已修复**（第十九轮）：逐段落占位 + 可定位事实 + `text-fallback` 专用类别 → 已勾回 |
| ~~V3.0 3.4~~ | ~~GUI 预览未同源~~ | **已修复**（第十八轮）：`text_resolver` 注入编辑器预览/只读 HTML → 已勾回 |
| ~~V3.0 4.3~~ | ~~实例无产品写入路径~~ | **已修复**（第十八轮）：`record_instances()` + CLI/GUI 接线 → 已勾回 |
| ~~V3.1 4.2~~ | ~~命令注册表未在应用内实例化~~ | **已修复**（第十五轮）：窗口构建注册表、菜单/面板同源渲染、视图分离、项目切换重建 → 已勾回 |
| ~~V3.2 2.2~~ | ~~逐项进度未接线~~ | **已修复**（第十七轮）：`on_event` 注入 + 进度中继 → 已勾回 |
| ~~V3.2 4.2~~ | ~~变体仅登记不展开~~ | **已修复**（第二十轮）：变体接入快照/出稿/报告/包 → 已勾回 |
| ~~V3.2 5.1~~ | ~~结果页只显示截断摘要~~ | **已修复**（第十七轮）：`memberRows` + 明细渲染 → 已勾回 |
| ~~V3.3 1.3~~ | ~~后台分批未实现~~ | **已修复**（第二十一轮）：`build_index_task` + TaskRunner 后台分批 → 已勾回 |
| ~~V3.3 1.4~~ | ~~来源去重/不阻塞未验证~~ | **已修复**（第二十一轮）：物理路径去重 + 120 章实测 0.23～0.35 s → 已勾回 |
| ~~V3.3 2.3~~ | ~~模块更新未接为建议~~ | **已修复**（第二十二轮）：`KIND_MODULE_UPDATE` 复用 V3.0 版本接口 → 已勾回 |
| ~~V3.3 3.4~~ | ~~取消修订无用例~~ | **已修复**（第二十二轮）：菜单「取消摘要候选」+ 哈希断言 → 已勾回 |
| ~~V3.3 5.3~~ | ~~`assist.*` 未在应用内实例化~~ | **已修复**（第十五轮）：应用构建注册表并注册写作辅助命令，菜单/面板同源 → 已勾回 |
| ~~V3.3 5.4~~ | ~~应用内“采纳→一次撤销→保存”不可达~~ | **已修复**（第十六轮）：面板发 `buffers_changed`、编辑器一个撤销步写回、保存沿用 ContentWriter；同时修掉 `_collect_buffer_texts` 取不到面板文本导致脏缓冲被丢弃的真实缺陷 → 已勾回 |

## 4. 仍待实机/环境复核（保持勾选，注明条件）

| 项 | 说明 |
|---|---|
| V3.2 4.5 / 7.3 | 真实 Word 正式化与进程级换机：本会话曾两次跑绿（3 项 58.2 s、2 项 62.1 s，见台账）；审计时本机 Word 探测不可用，未能复现。需在 Word 可用环境以 `V32_REAL_WORD=1` 复跑 |
| V3.2 7.2 | 结构数字可复现（产物 337,513 B、队列 44,127 B 精确一致）；**耗时随机器负载差异极大**（隔离 87 s、并发 125 s vs 首次记录 10.88 s），已改为记录条件与区间 |

## 5. 与“如实保留”原则的一致性

- 审计未发现任何伪造证据或把模型输出当证据的条目。
- 审计发现的问题已按“**能修则修、暂不能修则改回未勾选并写明缺口**”处理：本轮修复 2 项功能缺陷 +
  5 处台账/文档更正，13 项改回未勾选。
- 归档结论：结构校验与自动化证据齐备；第十四轮列出的 13 项缺口已修好 2 项（V3.1 4.2、V3.3 5.3 已勾回），
  仍有 11 项待修；四个同步/归档任务在缺口修好或经确认为可接受前继续不勾选。

## 6. 修复项的独立复核（第二十四轮）与追加修复

对第一轮审计修好的 13 项做**独立复核**（两个只读代理，逐项查生产调用路径 + 跑指定用例）：

| 复核项 | 结论 | 处置 |
|---|---|---|
| CORE 3.2 复杂对象占位 | weak | **已修**：脚注/尾注/批注/OLE 不再因“同段有文字”被记成文本降级（只有公式/文本框的文本会随段落提取）；标题前只有暂不支持对象的段落也算“有意义内容”，否则会被 `start_idx` 整段跳过 → 现已记录事实并在前言章节写占位 |
| CORE 更换目录传缓冲 | supported | — |
| V3.0 3.4 预览同源 | supported（跑了 5 项用例） | — |
| V3.0 4.3 实例写入 | supported（同文件 5 项） | — |
| V3.1 4.2 / V3.3 5.3 注册表接入应用 | supported | — |
| V3.2 变体出稿 / Word 占用 / 结果明细 | (a)(c)(d) supported | (b) **已修**：`_on_task_event` 现处理 `stage` 事件并写任务面板日志，逐项进度在界面可见 |
| V3.3 采纳→编辑器→保存 | supported | — |
| V3.3 后台分批索引 | weak | **已修**：面板加 QTimer 轮询后台 runner（此前从未 poll，完成回调与 `invalidate()` 在应用内不可达） |
| V3.3 来源去重/大范围 | supported（注明首次检索仍同步回退） | — |
| V3.3 模块更新建议 | weak | **已修**：面板打开即加载建议并新增「刷新建议」按钮（此前收件区在应用内永远为空）；`KIND_MODULE_UPDATE` 补进展示顺序 |
| V3.3 摘要候选取消 | supported | — |

新增回归用例：`test_core_unsupported_classification.py`（4 项：脚注按占位、标题前对象保留/默认入账、逐项进度可见）、
`test_v33_panel_reachability.py`（3 项：面板打开即有建议含模块更新、后台索引有轮询定时器、新种类在展示顺序中）。

实机证据刷新（第二十四轮）：清理 5 个遗留无窗口 WINWORD 进程后 Word 16.0 可用（启动 2.6～17.6 s，
默认 10 s 探测会误判）→ `V32_REAL_WORD=1 python scripts\tests\test_v32_real_word_formalize.py` **Ran 3 tests OK（73.8 s）**；
`test_v32_cross_process_promote.py` 探测超时放宽到 60 s 后 **Ran 2 tests OK（41.8 s）**。

## 7. 规范覆盖审计（第二十七轮）与处置

第二轮独立复核改为按 **spec 需求**（而非 tasks.md 勾选）核对实现可达性，两个只读代理分别覆盖
CORE+V3.0 与 V3.1+V3.2+V3.3：

| change | covered / partial / uncovered | partial 明细 |
|---|---|---|
| CORE | 31 / 3 / 0 | R5 导入预设无生产入口；R9 失效最近记录缺“重新定位”；E8 高 DPI 无环境证据且未单列待验收 |
| V3.0 | 9 / 0 / 0 | — |
| V3.1 | 4 / 3 / 0 | ①`team.chapter-history` 结果被 GUI 回调丢弃、且未传缓冲；②“我的待办”结果同样被丢弃；③交接应用命令拿不到包路径，`apply_handoff_plan`/`import_handoff_as_new_copy` 生产不可达 |
| V3.2 | 9 / 0 / 0 | — |
| V3.3 | 7 / 1 / 0 | 摘要/只读的“导出建议”无生产入口（`service.export_suggestions` 零调用方） |

本轮已修（V3.1 全部 3 项 + 冻结包缺失）：

- **`run_team_flow` 接入产品**：新增命令注册表条目 `team.flow`（菜单/面板可达）与 CLI
  `doc-tool team-flow --project … [--chapters|--package|--apply] [--json]`，退出码 0/1/2；
  冻结包因此重新包含 `team_flow`（此前被 PyInstaller 排除，功能在冻结态根本不存在）。
- **注册表命令结果必须显示**：`_make_registry_callback` 此前丢弃 `handle_result` →
  章节历史/我的待办/协作报告在界面上看不到任何输出；现在统一展示（摘要 + JSON 详情，失败显示原因），
  并按命令补齐界面参数（章节历史带编辑器缓冲、交接导出选目录、交接应用选包）。
- **历史与缓冲比较**：`team.chapter-history` 取最新可得提交调用 `compare_current(..., buffer_text=…)`，
  结果含 `bufferCompared`/`bufferComparison`。

同轮追加修复（CORE R9 + V3.3 导出入口）：

- **CORE R9**：失效的最近项目条目新增「🔍 重新定位」按钮（此前只显示“路径失效”且定位被禁用）——
  选择新目录后校验 `project.yml`，非项目目录不改列表并提示；窗口把最近记录从旧路径改到新路径并刷新首页
  （`test_spec_gap_entries.py` 3 项）。
- **V3.3 建议导出入口**：写作辅助面板新增「导出建议…」，走服务层同一 `export_suggestions` 写盘，
  只读项目同样可导出（`test_spec_gap_entries.py` 2 项）。

同轮追加修复（CORE R5）：

- **CORE R5**：命名导入映射预设补齐三层生产入口——服务 `run_intake(preset_name=, save_preset=)`、
  `ImportRequest.intakePresetName/intakeSavePreset` 与 `ImportResult.warnings/savedPreset`、
  CLI `import --preset/--save-preset` 与 `intake-presets list|show|delete`、向导预填。
  `test_core_intake_presets.py` 5 项通过。

仍未修（如实保留，下一轮处理）：CORE **E8**（高 DPI 实测与待验收条目，已在准备度报告单列）。

冻结重建证据（第二十七轮）：
- `dist/DocTool/DocTool.exe`：10037024 字节，sha256 `225520e0d7945a13…`
- `dist/DocTool/doc-tool-cli.exe`：9277424 字节，sha256 `3c73e3f428304bd0…`

冻结 CLI 实测：`team-flow --project <fixture> --handoff <dir> --json` → exit 0，报告含
`processed=["待办清点：待处理 0 项","交接包已导出：内容交接包.zip"]` 与产物路径。

## 8. 第二轮「修复复核」（第三十三轮）与处置

对第 27–31 轮新增/修复的能力做独立只读复核（两个代理，按生产可达性判断）：

| 复核项 | 结论 | 处置 |
|---|---|---|
| `team.flow` 串联流程（注册表 + CLI + 冻结包含 `team_flow`） | supported（冻结 PYZ toc 内含 `team_flow`） | — |
| 注册表结果展示（非阻塞对话框 + 参数补齐） | supported（`setModal(False)` + `show()`，无 `exec()`） | — |
| 章节历史带编辑器缓冲比较 | supported（有历史时 `bufferCompared=True`；无历史为 False） | — |
| 导入预设服务 API `run_intake(preset_name=, save_preset=)` | **weak**：该 API 仅测试调用；生产走 `ImportRequest` 字段与 CLI 的**重复实现** | **已修**：解析/保存收敛到 `intake_presets.resolve_for_source/save_from_import` 唯一实现，CLI/首次导入/服务层三处都改为调用它，并删掉死导入 |
| 导入预设 CLI（`--preset/--save-preset`、`intake-presets`） | supported（真跑 save→list→show→apply→delete） | — |
| 预设界面入口（`intake.presets`、向导预填） | supported（无项目也可用） | 附带修复：待用预设**用后清空**（原先会一直粘到后续导入） |
| 失效最近记录重新定位（R9） | supported | 附带修复：测试原先“旧路径已移除”是空断言（旧路径从未入库），现已先写入再验证 |
| 环境自检与失败建议 | supported（密文路径真跑 subprocess） | — |

处置验证：`test_core_intake_presets.py` 5 OK、`test_core_intake_presets_gui.py` 3 OK、
`test_spec_gap_entries.py` 5 OK、`test_v31_registry_display.py` 3 OK。
