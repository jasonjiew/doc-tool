# V4.0～V4.3 真实环境复验步骤（未勾选 5 项的照做清单）

本文件只列出**本机不具备的真实外部条件**对应的复验步骤。每条都写成
「前置条件 → 命令 → 期望产物 → 判定阈值」，可直接照做。

当前状态（本地可执行项已全部完成）：

| 包 | 勾选 | 未勾选项 |
|---|---|---|
| product-v40-runtime-and-word-reliability | 19/20 | 5.3 |
| product-mainline-usability-and-fidelity | 23/24 | 6.3 |
| product-v41-enterprise-template-workflows | 19/20 | 5.3 |
| product-v42-incremental-quality-workbench | 19/20 | 5.3 |
| product-v43-delivery-and-revision-workbench | 19/20 | 5.3 |

---

## 0. 统一前置条件清单

- [ ] 安装 **Microsoft Word**（桌面版）与 `pip install pywin32`；验证：
      `python -c "import win32com.client as w; w.Dispatch('Word.Application').Quit(); print('word ok')"`
- [ ] 准备**真实企业底模** `template.docx`（含封面、页眉页脚、目录域、保留部件），
      放到 `standards/<packId>/template.docx` 或任意可读目录。
- [ ] 准备**真实三成员工程**：三个可独立打开的项目放在同一工作区根目录下，
      `workspace.yml` 中 `documents[].role = requirement`，路径为工作区内相对路径。
- [ ] 中文 IME 可用；显示器支持 **125% / 150% / 200%** 缩放切换。
- [ ] 若要做冻结试点：`pip install pyinstaller`，源码树完整（`doc_tool/app.py`、`doc_tool_cli.py`、
      `packaging/doc_tool.spec`）。
- [ ] 全程用 `$env:PYTHONUTF8=1`、`$env:PYTHONIOENCODING='utf-8'`、
      `$env:QT_QPA_PLATFORM` 不设（要真实桌面，不要 offscreen）。

---

## 1. V4.0 5.3 — 真实 Word / 企业底模 / 原生桌面 / IME / 缩放 / 冻结执行试点

**前置**：第 0 节全部。

```powershell
# 1) 真实 Word 全流程（无 offscreen）
python -m pytest scripts\tests\test_v40_entry_loop.py -q -p no:cacheprovider
```

- **期望产物**：8 passed；并且 `docx` 结果在**有 Word** 时
  `result.formal == True`、`read_state(docx).sha256 == sha256_file(docx)`。
- **判定阈值**：8/8 通过且至少 1 个 DOCX 的 `formal=True`；若 `formal` 仍为假，
  记录 `docx.warnings` 与 `docx.message`（说明卡在哪一步）。

```powershell
# 2) 冻结产物执行试点
#    前置：在**无进程级临时文件限制**的普通桌面环境执行（受限沙箱下
#    `tempfile.mkstemp` 会失败，导致冻结产物任何需要临时文件的操作报 E6003）。
pyinstaller --noconfirm packaging\doc_tool.spec
dist\DocTool\DocTool.exe
dist\DocTool\doc-tool-cli.exe --version      # 期望 appVersion/commit
dist\DocTool\doc-tool-cli.exe env-check      # 期望「环境自检：通过」
dist\DocTool\doc-tool-cli.exe project-export --project <proj> --formats html `
    --destination <proj>\export-out --no-refresh
```

- **期望产物**：`dist/DocTool/DocTool.exe` 与 `dist/DocTool/doc-tool-cli.exe` 均启动成功；
  `project-export` 产出 `export-out\html\preview\<round>\index.html`、`export-result.json`、`manifest.json`。
- **判定阈值**：`--version` / `env-check` / `project-export` 退出码均为 **0**；
  用 `python -m pytest scripts\tests\test_frozen_smoke.py` 期望 **11 passed**；
  GUI 能打开项目并出稿；反复开关 GUI **10 次**后任务管理器内存无单调增长（记录每次私有工作集）。
- **已实测的本机限制（2026-10-03）**：本机受限沙箱下冻结产物
  `tempfile.mkstemp()` 全部候选目录失败（`No usable temporary directory found`），
  导致 `convert`/`project-export` 无法写临时文件而失败；`--version`/`--help`/`status`/`env-check`
  与 `test_frozen_smoke.py` 均正常。故冻结**执行**试点需在普通桌面环境复验。

```powershell
# 3) IME / 缩放
#    （GUI 操作，无命令）125% → 150% → 200% 各切换一次
```

- **期望产物**：编辑器内中文输入无丢字、无重复提交；表格网格与章节树在 200% 下不裁切主动作。
- **判定阈值**：三档缩放下「保存 / 出稿 / 章节树右键」三个主动作均可达且可点击。

---

## 2. MAIN2 6.3 — 企业 Word 底模 / 中文 IME / 剪贴板 / 原生缩放 / 长表宽图分页

**前置**：第 0 节 + 真实企业底模 + Excel（测剪贴板）。

```powershell
python -m pytest scripts\tests\test_main2e_final_export_order.py `
  scripts\tests\test_main2e_offline_and_scope.py -q -p no:cacheprovider
```

- **期望产物**：阶段顺序、PDF 同轮、待刷新标记在**真实 Word** 下仍成立。
- **判定阈值**：`docx` 为 `formal=True` 且登记 hash 等于最终字节；PDF 由**同轮最终 DOCX** 转换。

手工核验（无命令）：

| 动作 | 期望 | 阈值 |
|---|---|---|
| Excel 复制区域 → 编辑器「粘贴为表格」 | 生成 Markdown 表格且行列数与原选区一致 | 无丢行/丢列 |
| Word 复制带格式文本 → 编辑器粘贴 | 保留可读纯文本与标题层级 | 不出现乱码/丢失标题 |
| 中文 IME 连续输入 200 字 | 无丢字、无重复 | 字数一致 |
| 长表（>1 页）与宽图出稿 | 分页正确、宽图不裁切 | 目视确认页数与图宽 |

---

## 3. V4.1 5.3 — 真实企业底模与 Word 视觉核验

**前置**：真实企业底模（含封面/目录域/保留部件）。

```powershell
python -m pytest scripts\tests\test_v41_template_library.py `
  scripts\tests\test_v41_template_sample.py `
  scripts\tests\test_v41_author_to_member_flow.py -q -p no:cacheprovider
```

- **期望产物**：目录/预设/试用/闭环用例在真实底模下仍全绿。
- **判定阈值**：三文件全通过；并且**试跑小样**在 Word 中打开后：
  - 目录域可更新且页码正确；
  - 封面保留（不被替换/丢失）；
  - **保留部件**（页眉页脚、水印、公司标识）仍在；
  - 标题列表（多级编号）与正文样式符合底模定义；
  - 长表 / 宽图 / 代码块不溢出页面。

> 明确禁止：**不得**用诊断 DOCX 或 HTML 预览替代真实 Word 视觉结论。

---

## 4. V4.2 5.3 — 真实大工程与原生桌面试点及资源量测

**前置**：真实大工程（≥1000 章）。

```powershell
python analysis\v42\measure_staged.py
python -m pytest scripts\tests\test_v42_performance_correctness.py -q -p no:cacheprovider
```

- **期望产物**：`analysis/v42/measure-staged.json` 更新（50/300/1000 章 ×5 采样）。
- **判定阈值**：
  - 正确性：冷/热/无缓存问题集合逐项一致（**必须**满足）；
  - 性能：热路径 p95 改善 ≥30% 为**目标**；当前 50 章达标、300/1000 章约 12%，
    若真实大工程下仍不达标，**如实记录且不得删规则或放宽断言**；
  - 释放：切章/关闭后对象释放 delta 应为 0（当前三档均为 0）。

原生桌面手工核验：检查/定位/修正/预览/出稿五个动作在真实大工程下逐一点击，
记录每次操作耗时与内存峰值。

---

## 5. V4.3 5.3 — 真实三成员研发工程与接收人环境试点

**前置**：真实三成员工程 + 一台「接收人」机器（无源码树，仅接收成果包）。

```powershell
python -m pytest scripts\tests\test_v43_three_member_loop.py `
  scripts\tests\test_v43_handover_package.py -q -p no:cacheprovider
```

- **期望产物**：闭环与打包用例在真实三成员工程下仍全绿。
- **判定阈值**：
  1. 准备 → 提交后编辑 → 部分失败 → 补原轮 → 新轮，`captureId` 逐轮可区分；
  2. 两版比较命中真实改动章节，修订说明可编辑且**不改变**评审/正式状态；
  3. **接收人机器**上解包成果包：离线 HTML 可直接打开（无网络、无源码树）；
  4. 补充包在接收人环境按 `snapshot_package` 原捕获继续 Word 刷新成功。

---

## 6. 收尾判定

**先跑收尾核对脚本**（本地可判定项一次验完，外部项只列出不影响退出码）：

```powershell
python analysis\v40\final_check.py
```

- **期望产物**：五包勾选状态、未勾选项与外部条件清单的一致性、OpenSpec strict 结果、
  14 个关键交付文件存在性、性能事实表，以及外部条件项列表。
- **判定阈值**：退出码 **0**，且输出末行为「本地可判定项全部满足；剩余 5 项均为外部条件。」；
  若未勾选项与外部条件清单不一致或 strict 未通过，退出码为 **1** 并逐条列出原因。
- **实测（2026-10-03）**：退出码 0；`99/104`；5/5 strict valid；14/14 交付文件存在；
  性能表 `met30Percent=False`（唯一未达量化目标，论证见执行台账）。



以上 5 项**全部满足判定阈值**后，可把对应 `tasks.md` 勾选，并在
`docs/product-v40-v43-execution.md` 追加一节记录：命令、退出码、产物路径、
实测数值与未达项。若任一项不满足，保持未勾选并记录真实数值。
