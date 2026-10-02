# 主流程优化包 Codex 执行台账

计划日期：2026-10-01。入口：[主功能优化计划](product-core-workflow-plan.md)，原则：[流程与兜底](product-flow-fallback-policy.md)。关联 change：`product-core-import-export`。

本轮状态唯一源为 [tasks.md](../openspec/changes/product-core-import-export/tasks.md)；本台账只记录证据与遗留，不改写 V2/V3 台账与任务勾选。

## 批次状态

| 批次 | 任务 | 状态 | 验证/环境 | 直接下一项 |
|---|---|---|---|---|
| CORE-A | 4/4 | 契约、入口与夹具已实现并有直接测试 | `test_core_intake_contract.py` 28 项通过；`test_core_entries_ui.py` 7 项通过（离屏 Qt） | 完成 |
| CORE-B | 5/5 | 普通导入优先可用 | `test_core_intake_fallback.py` 19 项通过（含真实 Word 首次导入/试构建） | 完成 |
| CORE-C | 5/5 | 原件账本 + 结果页直接动作（定位/原件/替换图片）已完成 | `test_core_result_page.py` 7 项通过；就地替换图片实测改写正文并更新账本 | 完成 |
| CORE-D | 5/5 | 范围勾选/重编号、映射预设、Word 与 Markdown 批次已实现 | `test_core_scope_presets_batch.py` 13 项通过 | 完成 |
| CORE-E | 5/5 | 快照、来源模式、只读外部出稿、预览/检查同源与全场景验证完成 | `test_core_export_snapshot.py` 16 项、`test_core_gui_loop.py` 通过 | 完成 |
| CORE-F | 6/6 | 统一出稿 + 结果页动作 + U-4~9 验证完成；导出改由 TaskRunner 后台执行 | `test_core_cli_export.py` 8 项、`test_core_export_ui.py` 3 项、`test_core_gui_loop.py` 通过 | 完成 |
| CORE-G | 5/5 | 有限排版（图片/普通表格/章前分页/章级横向）与源码包已实现 | `test_core_layout_package.py` 5 项、源码包断言通过 | 完成 |
| CORE-H | 4/5 | 8.1 CLI、8.2 界面闭环、8.3 基线、8.4 说明完成；8.5 收尾（同步/归档）待全部验收 | `test_core_gui_loop.py`、`test_core_cli_export.py`、`measure_core_baseline.py` | 8.5 |

合计 39/40 已勾选；仅 8.5（OpenSpec 同步/归档与发布归属）保持未完成——它要求全部验收满足后再执行，且实机 Word 版式/冻结包/缩放仍需单独验收。

## 1.1 复用/差额清单（CORE-A 直接检查）

读取 HEAD `1cc28ca`（工作树含并发会话未提交改动，本包不覆盖其文件）。复用与差额：

| 环节 | 复用（未重建） | 本包补的差额 |
|---|---|---|
| 首次导入 | `application/import_project.py` 事务化导入、`adapters/preflight.py` 预检、`adapters/importer.py` 提取/拆分 | 普通/严格策略贯穿、跳级整理、标题前正文范围、缺图占位、有界回退、导入记录 |
| 建项入口 | `ui/wizard.py` 导入向导、`project_from_markdown/create_project_from_markdown`、`project_from_pack/create_project_from_pack` | `application/intake_entries.py` 自动识别 + 真实服务路由；修正规范包入口原先只显示说明的缺陷 |
| 重导入 | `content/reimport.py`、`reimport_plan.py` | 再次导入登记来源版本到导入记录 |
| 编辑/预览 | `ContentWriter`、`content/preview.py`、`export/readonly_html.py`、`PreparedSource` | 有效内容快照 `EffectiveSnapshot`（与 `ContentSnapshot` 变更基线分离） |
| 出稿 | `pipeline.run_pipeline` + `OutputState` + `adapters/word_convert` + `convert.convert_paths` | `application/project_export.py` 统一多格式、同轮补格式、`export-result.json` 聚合索引、`source_package.py` 源码包 |
| 契约 | — | `application/intake_contract.py`（IntakePlan/策略/范围/来源模式/FormatResult）、`import_record.py`（schema 1 账本） |

直接检查：`python -c` 导入各新模块成功；OpenSpec strict 校验与 tasks 计数在批次收尾复核。

## 每批证据

```text
日期 / 执行HEAD / 工作树基准 / 当前版本：2026-10-01 / 1cc28ca + 并发会话未提交改动 / APP_VERSION 2.8.0
批次 / 完成编号 / 复用与补差额：CORE-A 1.1-1.4；CORE-B 2.1-2.5；CORE-C 3.1/3.2/3.4/3.5；CORE-E 5.1/5.2/5.4；CORE-F 6.1-6.4；CORE-G 7.4
真实直接接口依赖与检查结果：import_first_time / preflight / extract_content / ProjectManifest / ProjectPaths / run_pipeline / OutputState / convert_paths / export_readonly_html 均为真实调用
用户可用行为 / 文件和成果路径：run_intake 单份 DOCX/MD/规范包建项；run_project_export 生成 DOCX/HTML/PDF/源码包到指定目录并写 export-result.json
输入/范围/来源模式/captureId / 原文件与缓冲状态：captureId 固定一轮；sourceMode=current-buffer 含未保存章节数；测试断言源项目 content/assets/template 哈希不变
默认正常/兜底（自动处理、待完善、未执行）：普通模式缺图占位、复杂对象原件留存、对照未完成明确记录、无 Word 时 DOCX 可读稿待刷新、PDF 待转换
严格策略 / 单文件与单格式部分成功 / 原轮重试：严格模式在发布前按缺口阈值拒绝新项目（已测）；单格式失败保留其它结果；retry_export_formats 使用原轮快照与 DOCX
验收C-编号 / 命令 / 环境 / 退出码 / 证据：C-1/C-2/C-4/C-5/C-6/C-8 自动部分；python scripts/tests/test_core_*.py 全部 exit 0
易用性U-编号 / 主要操作数 / 弹窗数 / 默认值 / 就地恢复 / 窗口与键盘证据：U-1/U-2（默认值齐备、入口真实服务、脏工作区不自动切走）已测；U-7（问题直接动作结构化）已测；U-3/U-4~6/U-8/U-9 界面级待做
阶段耗时/解析次数/内存/取消响应（有测量时）：未测量（CORE-H 8.3）
Word版式/冻结待验收 / 已有无关失败 / 遗留：本机 Word 可用，DOCX 试构建/PDF 转换实机通过；冻结包、125%/150% 缩放、Word 版式观感仍待验收
下一批 / 下一任务：CORE-D / 4.1（随后 CORE-G 7.1、CORE-H 8.1）
```

## 环境与遗留

- 本会话 DSH 沙箱曾把 `os.mkdir(mode=0o700)`（`tempfile.mkdtemp`）目录置为不可写；文件策略放宽为完全访问后，产品路径（暂存目录用 mkdtemp）与既有测试均可运行。该现象属沙箱环境，不是产品缺陷。
- 测试夹具使用仓库内 `tmp/core-scratch/`（`scripts/tests/core_fixtures.py`），不依赖系统 %TEMP%。
- 未实现/未验证项按规定保留未勾选：CORE-D 全部、CORE-E 5.3/5.5、CORE-F 6.5/6.6、CORE-G 7.1/7.2/7.3/7.5、CORE-H 全部、CORE-C 3.3 的界面深链接。

## 8.3 本机基线（2026-10-01，同一台机器）

样本：脱敏合成 DOCX（40 章 / 80 个标题，两级结构），命令
``python scripts\tests\measure_core_baseline.py``（JSON 输出）：

| 项目 | 实测 |
|---|---|
| 首次导入（含 Word 试构建与往返对照） | 2.96 s，24 个阶段事件，80 个章节候选 |
| 有效快照捕获 | 0.363 s |
| DOCX + 离线 HTML 出稿（诊断构建，不刷新字段） | 4.25 s（其中快照 0.36 s） |
| 进程峰值内存（tracemalloc） | 12.76 MB |
| 取消响应（首个进度回调即取消） | 0.625 s，已完成格式保留、未开始格式标记 cancelled |
| 重复出稿一致性（不依赖缓存） | 状态与可用结果完全一致 |

小样本（4 章 / 8 标题）参考：导入 1.60 s、出稿（DOCX+HTML）2.06 s、峰值 4.58 MB。
未做编造性性能承诺；缓存与分阶段预览的调优只按上述实测瓶颈进行。

## 8.2 界面直接闭环（本轮实测步骤与弹窗）

用例 `scripts/tests/test_core_gui_loop.py`（离屏 Qt，真实服务）：

| 场景 | 实测步骤 | 弹窗 | 结果 |
|---|---|---|---|
| 单份导入 → 打开项目 | 1 次入口调用（`_on_import_document`）→ `_open_project_path` | 0 | 项目打开，章节树就绪 |
| 修改一章（未保存缓冲） | 1 次编辑（缓冲文本） | 0 | 磁盘正文未被改写 |
| 快速导出 Word | 1 次点击（Ctrl+E 同一动作）→ TaskRunner 后台执行 | 1（结果页） | 生成可读 DOCX（无 Word 环境为“待刷新”），`export-result.json` 记录 `current-buffer` 与未保存章节 |
| 打开结果 | 结果页点“打开文件” | 0 | 打开本轮产物，源文件保持原样 |
| 取消 | 无运行任务时点取消 | 0 | 不报错、不弹阻断框，已完成格式保留 |
| 小窗口/键盘 | 1280×720 逻辑尺寸 | 0 | 主操作动作存在、Ctrl+E 生效、无重复快捷键 |

实机项：真实 Word 刷新闭环（导入→改→正式 Word→打开）默认跳过，设 `CORE_REAL_WORD=1` 可执行；离屏自动套件不调用真实 Word COM（会长时间占用桌面进程）。

## 8.5 OpenSpec 严格校验（发布归属仍待定）

```
openspec validate product-core-import-export --strict        -> valid
openspec validate product-v30-content-reuse --strict         -> valid
openspec validate product-v31-team-workflow --strict         -> valid
openspec validate product-v32-batch-delivery --strict        -> valid
openspec validate product-v33-authoring-assistance --strict  -> valid
```

任务勾选（本轮实测）：CORE 39/40、V3.0 14/32、V3.1 13/27、V3.2 7/32、V3.3 22/26。
8.5 未勾选的原因：该任务要求“全部验收满足再同步/归档”，而实机 Word 版式、冻结包、
125%/150% 缩放与真实模型连通仍属待验收项；本轮只完成结构校验与证据核对，未做
specs 同步/归档，也未改动 V2/V3 既有进度。

## 全量回归记录（2026-10-01 第三轮，父会话实跑）

```text
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH=(Get-Location).Path
python scripts\tests\run_tests.py --junit test-results-full.xml
结果：114 个测试文件，1082.8 s，失败 1 个：test_gui_services.py（170 项中 1 项
  test_mermaid_dialog_templates_and_interactive_validation）
失败原因：本机未安装 mermaid CLI（shutil.which('mmdc') 为 None），对话框预览返回
  “ConnectionClosedError: Connection closed.”，属环境项，不是代码回归。
其余 113 个文件全部 OK，包含本轮新增的 11 个 CORE/V3 测试文件。
```

## 各版收尾任务现状（未勾选原因）

- V3.0 `7.1`：全量回归已跑通，但尚未按 `A30-1～6` 逐条留证（当前证据文件只记录到 A30-1）。
- V3.1 `6.1`：同上（缺 A31-1～6 逐条留证）；`6.2` 缺“无 Git 目录”双副本模拟；`6.3` 需真实团队；
  `6.4` 需版本源校正与冻结冒烟；`6.5` 需全部验收满足后再同步/归档。
- V3.2 `7.1`：同上（缺 A32-1～6 逐条留证）；`7.2` 需 10 成员实测；`7.3` 需真实 Word/两机；
  `7.4` 需版本源与冻结；`7.5` 需同步/归档。
- CORE `8.5`：结构校验已通过，同步/归档待全部验收（含实机项）。

## 全量回归复跑（父会话第十一轮）

```text
python scripts\tests\run_tests.py --junit test-results-full-v3.xml
-> 124 个测试文件 / 1 失败 / 0 错误；唯一失败为环境项（test_gui_services.py 的 Mermaid 预览，
   本机缺 mmdc）。CORE 相关套件（intake/export/snapshot/scope/batch/layout/cli/result-page/gui-loop）
   全部通过；五个 change openspec validate --strict 全部 valid。
发布与归档准备度见 docs/product-v3-release-readiness.md（归档动作待全部验收 + 用户授权）。
```

## CORE 3.2 复杂对象正文占位与定位（父会话第十九轮）

```text
问题（第十四轮审计）：公式/脚注/文本框等暂不支持对象只进待完善清单（body[n] 采样），
  正文看不到占位、结果页定位不到章节（target_chapter 为空），placeholder_lines() 无调用者。

修复：
  - `adapters/importer.py`：逐段落检测暂不支持对象（oMath/oMathPara、footnote/endnoteReference、
    txbxContent/textbox、object/OLEObject、commentReference），新增 `ExtractionResult.unsupported_map`；
    正文**未读到文本** → 写入可见占位 `[[待完善：<中文标签>｜来源：body[n]]]`；
    **读到文本** → 记为“文本降级”不重复插占位（避免正文出现噪音）。
  - `import_record.findings_from_extraction`：把上述事实转成带 `target_chapter`/`element_index` 的
    处理事实——文本降级用专用类别 `text-fallback`（**不冒充可编辑**），无文本用 `placeholder` +
    “定位此处 → 查看原件对应位置”；文档级保真事实若已有可定位提取事实则不再重复。
  - `import_project`：导入记录新增 `placeholderLines`（由 `placeholder_lines()` 生成，真实调用者），
    随记录序列化/反序列化；`intake_entries._merge_ledger_findings` 同步去重。
验证：python scripts\tests\test_core_unsupported_objects.py -> Ran 3 tests OK
  （提取事实含章节+body[n]+handling；正文出现可见占位与位置标记；记录含可定位事实与下一步动作；
   公式为 text-fallback 且不可编辑；结果页能带出占位事实）
  回归：test_core_intake_fallback 19 OK（原“全部 original-only”断言按新三类语义更新为
        “original-only/placeholder/text-fallback 且不得冒充可编辑”）、test_core_intake_contract 28 OK、
        test_import_project 27 OK、test_import_preflight 28 OK、test_intake_word_v28 7 OK、
        test_reimport_plan_v28 21 OK、test_reimport_preview_v28 10 OK、test_core_result_page 7 OK、
        test_core_entries_ui 7 OK
遗留：8.5 同步/归档（待全部验收 + 授权）；实机 Word 版式/冻结抽查。
```

## 全量回归最终基线（父会话第二十三轮）

```text
命令：python scripts\tests\run_tests.py --junit test-results-full-v3-r23.xml
结果：**135 个测试文件 / 1 项失败 / 0 错误**（证据 test-results-full-v3-r23.xml）
唯一失败：scripts/tests/test_gui_services.py::EditorAuthoringWorkbenchTests
          ::test_mermaid_dialog_templates_and_interactive_validation（本机缺 mmdc，环境项，非功能回归）
说明：默认清单自第十四轮（124 文件）以来新增 11 个测试文件（覆盖 CORE 复杂对象占位、V3.0 预览同源与实例登记、
      V3.1 注册表接入、V3.2 变体出稿与逐项进度、V3.3 后台索引/模块更新/取消路径等）。
实机环境探测：本轮 `check_word_available(dispatch_check=True)` 返回不可用（Word COM 启动失败），
      因此 V3.2 4.5/7.3 的 `V32_REAL_WORD=1` 复跑留待 Word 可用环境（此前两次跑绿记录见对应台账）。
```

## 全量回归与冻结重建（父会话第二十五轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r25.xml
  -> **138 个测试文件 / 1 项失败 / 0 错误**（唯一失败为环境项：test_gui_services 的 Mermaid 预览缺 mmdc）
冻结重建：powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
  -> DocTool.exe 10,026,552 B、doc-tool-cli.exe 9,134,136 B；产物内容校验通过；代码签名；
     scripts\tests\test_frozen_smoke.py **Ran 11 tests OK**
  -> 冻结 CLI 复核：--version（appVersion 2.9.0 / python 3.13.13）、
     reuse / delivery-plan / delivery-promote / assist-search / assist-provider / project-export 的 --help 全 exit 0；
     `reuse resolve --record-instances`（本轮新增能力）在冻结产物中可用
实机 Word：仍可用（Word 16.0，启动 2.6～17.6 s）；4.5/7.3 的绿灯记录见第二十四轮
```

## 规范缺口修复：失效最近项目可重新定位（父会话第二十七轮）

```text
问题（规范覆盖审计 R9）：最近项目条目失效时只能“移除”，规范要求的“重新定位”缺失
  （定位按钮被禁用）。

修复：失效条目改为可用的「🔍 重新定位」按钮 → 选择目录 → 校验 `project.yml`（非项目目录不改列表并提示）
  → 窗口把最近记录从旧路径改到新路径（保留文档名等元信息）并刷新首页。
验证：scripts/tests/test_spec_gap_entries.py 3 项 OK（失效条目有可用重定位按钮；非项目目录被拒；
  窗口改列表且旧路径移除）；原“定位按钮禁用”断言按 R9 更新为“可重新定位”
  （test_home_experience_iteration.py 19 项 OK）。
```

## 规范缺口修复：导入映射预设的生产入口（父会话第二十八轮）

```text
问题（规范覆盖审计 R5）：`IntakePresets` 服务完整但只有测试直调，用户无法保存/应用命名导入预设。

修复（服务 → CLI → 界面三层）：
  - `run_intake(..., preset_name=, save_preset=)`：把命名预设解析成真实样式映射
    （未命中项回退自动识别、未知预设只提醒）；保存时优先用显式映射，其次预设映射，
    最后用预检的自动识别结果，并按名称更新而非重复；
  - `ImportRequest.intakePresetName/intakeSavePreset` + `ImportResult.warnings/savedPreset`，
    `import_first_time` 在预检前解析预设、成功后保存预设；
  - CLI：`import --preset 名称 --save-preset 名称`；新增
    `intake-presets list|show|delete [名称]`（human/json）；
  - 向导：`_intake_preset_name`/`_intake_save_preset` 让界面把预设带给导入。

验证：python scripts\tests\test_core_intake_presets.py -> Ran 5 tests OK
  · 保存后再导入能命中预设（outcome.preset.name/mapping + “已应用导入预设”）
  · 未知预设只提醒且导入继续
  · ImportRequest 字段贯通到 import_first_time（savedPreset 正确）
  · CLI save → list → show（含 Heading1 映射）→ delete → show exit 2
  · CLI 应用预设：preset.mapping 回显 + “已应用导入预设”
界面入口：注册表新增 `intake.presets`（“导入映射预设（查看/套用）”，无项目也可用：
  预设表是全局的），可列出预设并可指定“下一次导入套用”的预设；两个向导入口
  （新建项目 / 导入文档）把 `_pending_intake_preset` 传给向导预填。
验证：test_core_intake_presets_gui.py 3 项 OK（命令列出并暂存预设；未知预设给出明确原因；
  向导实例收到待用预设）。
```

## 全量回归与冻结复核（父会话第二十九轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r29.xml
  -> **144 个测试文件 / 1 项失败 / 0 错误**（唯一失败仍是环境项：test_gui_services 的 Mermaid 预览缺 mmdc）
OpenSpec：五个 change 全部 `openspec validate <change> --strict` = valid
冻结重建：powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
  -> DocTool.exe 10,057,912 B（sha256 43407a9bedc638ea…）、doc-tool-cli.exe 9,383,656 B（sha256 ef31d3375e3c25b0…）
  -> 产物内容校验 + 签名 + test_frozen_smoke.py 11 项 OK
冻结 CLI 能力面（R5）：`intake-presets list` exit 0；`import --help` 含 `--preset/--save-preset`

冻结态**读写受本机策略阻断**（如实记录为待验收，非代码缺陷）：
  · `preflight --docx <仓库内 docx>` → 读到密文（前 16 字节为乱码）→ E1001；
    同一文件在 %TEMP% 副本上 preflight **成功**；源构建同一文件 import 成功。
  · `import ... --output json`（任意路径）→ 在 **validate_target** 阶段 E9000（意外错误）；
  · `convert <temp.docx> --to md` → `PermissionError(13, 'Permission denied')`（E6003）；
  · `team-flow --project <temp 项目>` 输出部分 JSON 后进程退出（-1）。
  结论：本机透明加密/杀软策略不允许未受信任的 `DocTool.exe` 写文件、也不解密仓库路径下的
  密文资产（打包说明 packaging/doc_tool.spec 与 build_exe.ps1 已记录该类问题与缓解：
  把 DocTool.exe 加入信任列表/白名单，或从受信任目录运行）。因此冻结态的**写入类闭环**
  需在干净机器或加入信任后复验；只读命令（--version/--help/intake-presets list、%TEMP% 内
  preflight）在当前环境已验证可用。
```

## 受限环境自检（父会话第三十轮）

```text
问题：第二十九轮实测发现，本机透明加密/杀软策略会让冻结 exe 得到笼统错误
  （写文件 PermissionError(13) → E9000；仓库路径 docx 读到密文 → E1001），
  用户只看到“导入过程中发生意外错误 / 联系支持”，无从判断是环境还是文档问题。

修复：新增 `doc_tool/application/env_probe.py`
  - `probe_write(dir)`：真写一个临时文件再删，识别写入被拒并给出“加入信任列表/换目录”建议；
  - `probe_docx_read(path)`：按 OOXML 校验前 4 字节，识别透明加密密文与读取被拒；
  - `diagnose_environment(dir, docx, target_exists)`：聚合结论 + advice；
  - CLI 新增 `env-check [--dir] [--docx] [--target] [--json]`（exit 0 正常 / 3 发现问题，
    冻结态同样可用，便于现场判定）；
  - 导入失败路径在 E9000 等笼统错误上补一次自检，把建议写入 `ImportResult.warnings`
    与 `suggestedAction`（不再只有“联系支持”）。

验证：python scripts\tests\test_env_probe.py -> Ran 9 tests OK
  · 健康目录/docx 通过；写入被拒 → PermissionError 明细 + 写权限建议；
  · 密文 docx（非 ZIP 签名）与读取被拒都识别为环境问题并给出“加入信任列表”建议；
  · 目标目录已存在 → 明确建议改项目名/目录；
  · CLI：健康 exit 0；密文 docx exit 3；已存在目标 exit 3；
  · 导入失败（模拟 preflight 权限异常 + 自检报告写拒绝）时 warnings 带可执行建议。
```

## 受限环境诊断在冻结态实测（父会话第三十轮，续）

```text
重建（含 env-check 与环境建议）：DocTool.exe 10,062,584 B（sha256 50f4e40f87e4246d…）、
  doc-tool-cli.exe 9,389,520 B（sha256 62dec33bc08315e9…）；test_frozen_smoke.py 11 项 OK。

冻结态实测（同一台机器、同一文件）：
  · `env-check --dir <TEMP> --docx <TEMP docx>` → write=PermissionError(13) + 建议“加入信任列表/换目录”，
    docx-read=OK（说明读明文可行、写被策略拒绝）；
  · `env-check --dir tmp --docx <仓库内 docx>`（human）→ docx-read=密文（b'\xe0\xa8\x91\xe7'）+ 同一建议，**exit 3**；
  · `import --json`（TEMP 目标）→ E9000，但 `suggestedAction` 与新增 `environmentWarnings`
    已给出“把 DocTool.exe 加入透明加密/杀软信任列表，或改选用户目录下的其它位置”；
  · `preflight --docx <仓库内 docx>` → E1001 文本后追加同一条环境建议（不再只说“请重新另存 docx”）。
结论：受限环境下的失败现在**可自诊、可执行**；写入类闭环仍需加入信任或干净机器复验（保持待验收）。
```

## 规范项 E8：高 DPI 布局证据（父会话第三十一轮，缩放因子**模拟**）

```text
背景：规范 E8 要求等待反馈/窗口可达在 125%/150% 缩放下也成立。本机没有可切换的物理
  缩放显示器，因此用 Qt 的 `QT_SCALE_FACTOR` 离屏**模拟**，把布局不变式固定成回归：
  控件非零尺寸、都在窗口矩形内、首页不出现横向溢出、逻辑尺寸保持 1280×720。

实现：`scripts/tests/hidpi_probe.py`（子进程探针，输出机器可读度量）
      + `scripts/tests/test_core_hidpi_layout.py`（对 1 / 1.25 / 1.5 三个因子断言）

实测（HIDPI_JSON 留档）：
  scale=1     dpr=1.0  logical=1280×720 physical=1280×720  issues=[]
  scale=1.25  dpr=1.25 logical=1280×720 physical=1600×900  issues=[]
  scale=1.5   dpr=1.5  logical=1280×720 physical=1920×1080 issues=[]
验证：python scripts\tests\test_core_hidpi_layout.py -> Ran 2 tests OK

**仍未验收（如实保留）**：物理 125%/150% 显示器下的真实观感与系统缩放交互；
  本用例只覆盖离屏缩放因子模拟，不能替代实机验收。
```

## 全量回归（第三十一轮）与 V3.2 环境依赖显式化

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r31.xml
  -> **146 个测试文件 / 2 项失败 / 0 错误**
     1) test_gui_services.py::test_mermaid_dialog_templates_and_interactive_validation（缺 mmdc，环境项）
     2) test_v32_batch_delivery.py::ResultIndexTests::test_index_lists_member_variant_format_status_and_paths
        （全量运行期间 Word 探测超时/被占用 → 本轮没有可读 DOCX → 打包按设计拒绝）
  处置：② 单独重跑 **22 项 OK**，确认非功能回归；该用例现在只在**确认**环境原因
        （Word 被占用/不可用）时 skipTest 并给出原因，其它情况保持硬断言——
        避免环境问题伪装成失败，也避免把真实回归伪装成跳过。
  证据：test-results-full-v3-r31.xml；重跑 test_v32_batch_delivery 22 OK、test_v32_delivery_entry 25 OK

CORE E8（高 DPI）：新增离屏缩放因子模拟回归（1 / 1.25 / 1.5），
  实测 HIDPI_JSON：dpr=1.0/1.25/1.5，physical=1280×720 / 1600×900 / 1920×1080，issues=[]；
  `test_core_hidpi_layout.py` 2 项 OK。**物理 125%/150% 显示器实测仍待实机。**
```

## 全量回归与实机 Word 复跑（父会话第三十二轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r32.xml
  -> **146 个测试文件 / 1 项失败 / 0 错误**（唯一失败仍为环境项：test_gui_services 的 Mermaid 预览缺 mmdc）
  说明：第三十一轮的那处 Word 依赖失败在本轮未复现（Word 可用 → 生成了可读 DOCX），
        且该用例现只在确认环境原因时 skip —— 套件结论回到“仅 1 项环境失败”。

实机 Word 复跑（清理 1 个遗留无窗口 WINWORD 后，word available=True）：
  $env:V32_REAL_WORD='1'; python scripts\tests\test_v32_real_word_formalize.py
    -> Ran 3 tests OK（61.2 s）
  $env:V32_REAL_WORD='1'; python scripts\tests\test_v32_cross_process_promote.py
    -> Ran 2 tests OK（39.1 s）
```

## 修复复核与收敛（父会话第三十三轮）

```text
独立只读复核（两个代理）对第 27–31 轮的能力做“生产可达性”判定：8 项 supported、1 项 weak。
weak 项与两处附带问题已修：

1）预设逻辑三处重复（服务 API 仅测试可达）→ 收敛为唯一实现
   `doc_tool/application/intake_presets.py`：
     · `source_style_names(src)`：样式名普查；
     · `resolve_for_source(preset_name, src) -> (resolved, info, warnings)`；
     · `save_from_import(name, src, mapping, style_names=) -> (saved, warnings)`；
   三个调用方（`run_intake` 的助手、`cli_commands.import_command`、`import_first_time`）
   全部改为调用它，删掉 CLI 里的重复实现与死导入。
2）待用预设“用后清空”：`intake.presets` 指定的预设只在**下一次**导入生效（此前会一直粘住）。
3）测试空断言修正：重新定位用例先把旧路径写进最近列表，再验证“旧路径已移除”。

验证：test_core_intake_presets 5 OK／test_core_intake_presets_gui 3 OK／
      test_spec_gap_entries 5 OK／test_v31_registry_display 3 OK
```

## 全量回归与冻结复核（父会话第三十四轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r34.xml
  -> **146 个测试文件 / 1 项失败 / 0 错误**（唯一失败仍为环境项：test_gui_services 的 Mermaid 预览缺 mmdc）
  结论：第三十三轮的预设实现收敛未引入回归。

冻结重建（首次尝试因套件刚结束的文件占用瞬时失败，重跑成功）：
  DocTool.exe 10,063,696 B（sha256 c5007be19eb1bfab…）、doc-tool-cli.exe 9,298,152 B（sha256 d3f5b63040dbc66c…）
  产物内容校验 + 签名 46 文件 + test_frozen_smoke.py **11 项 OK**

冻结态能力面（干净取退出码的实测）：
  · `env-check --dir .` exit 0；`env-check --dir <TEMP> --docx <TEMP docx>` **exit 3**，
    输出 write=PermissionError(13) + 建议“把 DocTool.exe 加入透明加密/杀软信任列表”、docx-read=OK；
  · `intake-presets list` exit 0；`import --help` 含 `--preset/--save-preset`；`team-flow --help` exit 0；
  · `--version` → appVersion 2.9.0。
  说明：本机策略仍阻止未受信任 exe 写入（env-check 如实报出），写入类闭环保持待验收。
```

## 全量回归首次全绿（父会话第三十八轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r38.xml
  -> **149 个测试文件 / 0 项失败 / 0 错误**（本轮新增 3 个校验用例文件后首次全绿）

此前唯一的失败项是环境项：`test_gui_services.py::test_mermaid_dialog_templates_and_interactive_validation`
（本机缺 mmdc）。本轮按应用既有约定解决了它（**免管理员、不动全局**）：
  cd tools\mermaid-cli
  npm install --no-audit --no-fund @mermaid-js/mermaid-cli          # 应用会自动识别 tools/mermaid-cli
  npx --yes puppeteer browsers install chrome-headless-shell        # mmdc 需要的无头浏览器
  实测：`mmdc --version` → 11.17.0；应用渲染成功（状态“✅ 渲染成功 · classDiagram · mermaid-cli · 159×136”）。
  注意：指向系统 Chrome/Edge 时本机会报 `ProtocolError: Network.enable timed out` /
  `ConnectionClosedError`，必须让 mmdc 使用自带 `chrome-headless-shell`（不要提供 puppeteer 配置）。

体积与可选性（如实记录）：`tools/mermaid-cli` **345.9 MB**、`~/.cache/puppeteer` **268.5 MB**（在仓库外）；
  两者都是**可选**的开发工具——没有 CLI 时应用自动退化为内置子集渲染器（`use_cli=False` 实测可用），
  不需要时可直接删除这两个目录。
```

## 收尾：最后一次全量回归与冻结重建（父会话第四十轮）

```text
全量回归：python scripts\tests\run_tests.py --junit test-results-full-v3-r40.xml
  -> **149 个测试文件 / 0 项失败 / 0 项错误**（连续第二轮全绿）
冻结重建（最终产物）：
  DocTool.exe 10,063,696 B（sha256 06ffc6314acc17e0…）、doc-tool-cli.exe 9,298,152 B（sha256 e646d4e987811cfd…）
  产物内容校验 + 签名 46 文件 + test_frozen_smoke.py **11 项 OK**
冻结 CLI 抽查：intake-presets list / team-flow --help / import --help / --version 全部 exit 0

进度与剩余：五 change **151/157**；剩余 7 项全部需要外部条件（授权 4、人工 2、环境 3 类中的
  冻结信任/物理缩放/第二台机器）。自动化部分已全部通过。
```
