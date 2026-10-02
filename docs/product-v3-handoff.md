# V3 / CORE 交接说明（成果与验证入口）

- 适用范围：`product-core-import-export`（CORE）与 `product-v30-content-reuse`（V3.0）、
  `product-v31-team-workflow`（V3.1）、`product-v32-batch-delivery`（V3.2）、
  `product-v33-authoring-assistance`（V3.3）五个 OpenSpec change。
- 进度：[V3 台账](product-plan-v3-execution.md)、[CORE 台账](product-core-workflow-execution.md)；
  当前 **151/157**（CORE 39/40、V3.0 31/32、V3.1 25/27、V3.2 31/32、V3.3 25/26）——第十四轮独立审计把 13 项“声称含未实现子项”的任务如实改回未勾选，清单见[审计与处置](product-v3-audit-findings.md)。
- 归档前置与命令见[发布与归档准备度](product-v3-release-readiness.md)；证据/台账一致性见[证据核对](product-v3-evidence-check.md)；
  **待验收项的可执行步骤见[验收操作清单](product-v3-acceptance-runbook.md)**（准备/命令/期望/判据/留档，含验收记录表）；
  **本机可验证部分的执行结果见[验收执行结果](product-v3-runbook-verification.md)**；
  **一页结论与证据汇总见[最终交接报告](product-v3-final-report.md)**（由脚本从 tasks.md 与最新 JUnit 生成，不手写数字）。
  **归档需授权，本轮未执行。**

## 1. 交付了什么（按版本）

| 版本 | 能力（均已接线到真实服务，非提示占位） |
|---|---|
| CORE | 导入/出稿主流程：普通与严格策略、缺图占位且保留原件与正文位置、坏包与复杂对象兜底、章节与范围选择、同轮多格式出稿、只补失败格式、导出含当前修改、源文件与已有成果不被删除 |
| V3.0 | 正文模块库（提取/安装/固定副本/选择性升级）、固定引用与展开副本、产品变体（章节+变量+模块版本）、缺模块/参数/循环回退、GUI「正文模块库与引用解析…」（Ctrl+Alt+R）、同源展开进入预览/检查/Word/HTML |
| V3.1 | 章节历史（Git 或本地历史）、负责人与我的待办、导出式交接与按份应用（冲突保留）、统一命令注册表（菜单/命令面板同 handler 同可用性）、串联流程与结果页、无 Git 目录可用 |
| V3.2 | 持久批次队列（续跑/取消/幂等入队/只补未完成）、自足交付包（相对路径 + 集合清单）、换机按包补刷新（真实 Word）、结果索引与选择归档（完整集合登记）、跨进程 Word 占用标识、临时故障自动重试一次、包版本回退、非法附件拒绝、GUI「批量交付（持久队列）…」（Ctrl+Alt+B） |
| V3.3 | 本地资料检索（出处/定位/缓存兜底）、确定性写作建议（规则/术语/引用/复核/变更事实）、采纳进缓冲并一次撤销、修订摘要候选只填既有修订记录、可选模型 provider（超时/断网/无凭据/坏响应全兜底，不执行响应、不当证据）、GUI「资料搜索与写作建议…」（Ctrl+Alt+A） |

## 2. 本机验证入口（可直接复制）

```powershell
$env:PYTHONUTF8='1'; $env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONPATH=(Get-Location).Path

# 全量回归（默认清单 149 个测试文件；第四十轮全量实测 149 文件 / 0 失败 / 0 错误）
python scripts\tests\run_tests.py --junit test-results-full-v3-r40.xml

# 关键实机/规模证据
$env:V32_REAL_WORD='1'; python scripts\tests\test_v32_real_word_formalize.py
$env:V32_REAL_WORD='1'; python scripts\tests\test_v32_cross_process_promote.py
python scripts\tests\measure_v32_batch10.py
python scripts\tests\test_v33_three_document_pilot.py
python scripts\tests\test_v31_real_document_handoff.py

# 台账/证据与归档前置
python scripts\tests\check_evidence_consistency.py
python scripts\tests\report_release_readiness.py
openspec validate product-core-import-export --strict
```

冻结包冒烟（onedir + 产物校验 + 签名 + `test_frozen_smoke.py` 11 项）：

```powershell
# 受限环境自检（目录可写性 / docx 是否被透明加密 / 目标是否已存在；exit 3 表示发现问题）
python -m doc_tool.cli env-check --json --dir . --docx <某个.docx>
doc-tool-cli.exe env-check --json --dir . --docx <某个.docx>   # 冻结态同样可用

# 生成本地审阅包（任务进度 + 台账 + 证据 + 冻结哈希 + 工作树状态，48 个文件）
python scripts\release\make_review_bundle.py --zip

# 归档（默认 dry-run 只核对；确认授权后加 --yes）
python scripts\release\archive_changes.py
python scripts\release\archive_changes.py --yes

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
.\dist\DocTool\doc-tool-cli.exe --version
```

## 3. 可用成果路径

- 冻结产物（第三十四轮重建）：`dist\DocTool\DocTool.exe`（10,063,696 B）、`dist\DocTool\doc-tool-cli.exe`（9,298,152 B）
- 使用说明：[V3.0/V3.2/V3.3 使用说明与限制](product-v30-v33-usage.md)、[V3.0 复用/变体格式与展开回退指南](product-v30-reuse-formats.md)、[V3.1 使用说明](product-v31-usage.md)
- 证据：`test-results-full-v3-r40.xml`、[证据核对](product-v3-evidence-check.md)、各版 `docs/product-v3*-execution*.md`
- 示例：`examples/delivery/`（批次计划与说明，无上传/发布动作）

## 4. 待验收项（6 项，均需人工/实机/授权）

| 编号 | 内容 | 现状 |
|---|---|---|
| CORE 8.5 / V3.0 7.4 / V3.1 6.5 / V3.2 7.5 | OpenSpec 同步/归档 | 结构与证据已就绪，**待授权后执行**，命令已备 |
| 审计缺口 13 项（**已全部修复**） | CORE 3.2、V3.0 3.4/4.3、V3.1 4.2、V3.2 2.2/4.2/5.1、V3.3 1.3/1.4/2.3/3.4/5.3/5.4 全部勾回；剩余只有人工试点、实机复核与归档授权 | 修复计划与处置见[审计与处置](product-v3-audit-findings.md) |
| V3.1 6.3 | 真实团队交接试点 | 已有真实文档 + 两独立副本 + 无 Git 代理试点数据；缺真实多人环节 |
| V3.3 6.2 | 三类文档人工试点与质量评价 | 已有三类真实文档的定位/建议/采纳撤销/摘要候选数据；缺人工评价 |
| 冻结包 | 本机策略阻断写入类闭环（env-check 实测：write=PermissionError(13)、仓库路径 docx=密文；exit 3 并给出建议） | 把 DocTool.exe 加入透明加密/杀软信任列表，或换干净机器复验（步骤见验收操作清单 C2） |
| 实机补充 | 真实两台物理机器、125%/150% 缩放 | 已用独立进程 + 独立目录等效验证；真实 Word 正式化与进程级换机已复跑通过（第二十四轮）；物理机与缩放未测 |
| 环境 | `mmdc` 已解决（项目本地安装，见验收清单 C5） | 第三十八轮起全量 0 失败；`tools/mermaid-cli`（345.9 MB）与 `~/.cache/puppeteer`（268.5 MB，仓库外）为可选的开发工具，删除后应用自动退回内置子集渲染器 |

## 5. 交接注意

- 本仓库 `write`/`edit` 工具在本机不可用（跨设备 rename 限制），改动经 PowerShell + UTF-8 无 BOM 写入；
  已为 `collection.register_manifest` 与 `content/impact.ReviewRecordStore.save` 补 `shutil.move` 回退，规避同类环境问题。
- 改动范围（第四十轮实测）：tracked diff **41 文件 / +4351 −376**；未跟踪新增 `scripts/` 59、`doc_tool/` 29、`docs/` 20、`openspec/` 5、`examples/` 1、`deliverables/` 1、根目录证据 XML 7；另有**先前既存**的未跟踪 `analysis/`（含 8 月/9 月的分析报告与一次 UI 审计的截图/数据，非本次会话产物，未改动）。**未提交、未归档、未发布**。
- 未实现/未验证项一律保持未勾选，并在对应 `tasks.md` 行内写明原因与下一步。

## 验收操作清单（父会话第三十五轮）

```text
新增 `docs/product-v3-acceptance-runbook.md`：把散落在各台账的待验收项集中成一页，
  每项统一给「准备 → 命令 → 期望 → 判据 → 留档」，并附验收记录表：
    A1–A4 同步/归档（授权）      B1 真实团队交接      B2 三类文档人工试点
    C1 实机 Word 正式化/换机      C2 冻结包写入类闭环   C3 物理 125%/150% 缩放
    C4 两机交接                  C5 Mermaid（mmdc）
  其中 C2 明确写清本机策略的两种表现（写入被拒 PermissionError(13) / 仓库路径读到密文）
  与判定方式（`env-check` 退出码 0 或 3 + advice），便于交给 IT 定位。

同步校验：`scripts/tests/test_acceptance_runbook.py` 4 项 OK ——
  未勾选任务必须全部出现在清单里、四类环境项关键词齐备、每项都有命令与判据、
  交接说明里必须链到清单（防止“台账说待验收、清单找不到怎么验”）。
审阅包现在也收录该清单（49 个文件）。
```

## 最终交接报告（父会话第三十六轮）

```text
新增 `scripts/release/report_final_handover.py` → `docs/product-v3-final-report.md`：
  数字全部取自仓库真实状态（tasks.md 勾选、最新 JUnit、准备度 PENDING 表、产物存在性），
  报告含：结论摘要、五个 change 进度表、验证证据（全量/实机 Word/冻结/高 DPI/审计复核）、
  可用成果路径（冻结产物大小与 sha256、审阅包、文档存在性 ✓/✗）、待验收项、下一条未完成任务编号。
  重新生成：`python scripts\release\report_final_handover.py`。

同步校验：`scripts/tests/test_final_handover_report.py` 5 项 OK ——
  报告内容与当前状态逐字节一致（状态变了就必须重生成）、覆盖五个 change 与全部剩余任务、
  列出的产物/文档必须真实存在、交接说明与准备度报告都必须链到它、必须声明“未提交/未归档”。

期间修正：准备度报告脚本被上一轮插入语句缩进破坏（生成器报 IndentationError）→ 已修复；
  并把陈旧数字“10 成员 10.88 s”更正为已复核口径（81.57 s 总量、8.16 s/成员、续跑 6.74 s）。
```

## 验收执行结果与执行器（父会话第三十七轮）

```text
新增 `scripts/release/verify_runbook.py`：执行验收清单中**本机可验证**的步骤，
  并如实标出仍需人工/实机/授权的项；输出 Markdown（可 --json）。
    python scripts\release\verify_runbook.py --with-tests --with-word --out docs\product-v3-runbook-verification.md

本轮实测（第三十七轮，写入 `docs/product-v3-runbook-verification.md`）：
  本机执行 8 项，通过 7 项：
    A1-A4 归档前置核对（dry-run，未改动仓库）通过
    C2 主机环境自检通过；**冻结产物自检受限**（PermissionError(13) + “加入信任列表”建议）
    C3 高 DPI 缩放因子模拟回归通过
    B1 团队交接代理试点通过；B2 三类文档试点通过；C1 实机 Word 两项通过
  仍需外部条件 7 项：授权 1（归档）、人工 2（真实团队 / 三类文档评价）、环境 4（冻结信任/物理缩放/第二台机器/mmdc）

同步校验：`scripts/tests/test_runbook_verifier.py` 6 项 OK ——
  本机集合字段齐备、归档核对**不改动仓库**、冻结自检必须给出受限原因与建议、
  依赖项覆盖授权/人工/环境三类且编号齐全、CLI JSON 可解析、验收清单必须链到执行结果。
```

## 验收执行器更新：Mermaid 纳入本机可验证项（父会话第三十八轮）

```text
`scripts/release/verify_runbook.py` 新增 C5（Mermaid）本机检查：能定位 `mermaid-cli` 就用它
  真渲染一张流程图（`want_png=False`，纯矢量、毫秒级），无 CLI 时给出安装指引并标为受限。

第三十八轮实跑（写入 `docs/product-v3-runbook-verification.md`）：
  本机执行 9 项，通过 8 项；唯一受限项仍是**冻结产物写入**（本机策略，PermissionError(13) + 建议）。
  其中 C5 明细：“使用 …\tools\mermaid-cli\node_modules\.bin\mmdc.cmd 渲染成功”。
  仍需外部条件 6 项：授权 1（归档）、人工 2（真实团队/三类文档评价）、环境 3（冻结信任/物理缩放/第二台机器）。
```

## 交接物一致性加固（父会话第三十九轮）

```text
一致性核对（`scripts/tests/check_evidence_consistency.py`）新增两条规则：
  当前态文档（交接说明 / 发布与归档准备度 / 最终交接报告）必须
  ① 引用**最新**的全量证据文件（本机现为 test-results-full-v3-r40.xml）；
  ② 写明**注册测试文件数**（现为 149，取自 run_tests.py）。

规则立即抓到一处真实漂移：最终交接报告此前把 JUnit 的 `<testsuite>` 元素数当作
  “测试文件数”（显示成 1），已改为使用注册文件数，并与 JUnit 的用例数/失败数分列。

复跑：`python scripts\tests\check_evidence_consistency.py` -> 失败 0 / 提醒 0。
另核对：冻结产物与源码同步（`doc_tool/` 无文件新于 exe），`test_frozen_smoke.py` 11 项 OK。
```
