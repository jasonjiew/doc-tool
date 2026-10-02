# -*- coding: utf-8 -*-
# V3 / CORE 验收操作清单（Acceptance Runbook）

> 用途：把散落在各执行台账里的**待验收项**集中成一页，交给验收人一次性执行。
> 生成基准：`openspec/changes/*/tasks.md` 的未勾选项 + 各台账记录的环境项。
> 同步校验：`python scripts\tests\check_acceptance_runbook.py`（未勾选任务必须在本页出现）。
> 本机可验证部分的**最新执行结果**见 `docs/product-v3-runbook-verification.md`；
> 复跑：`python scripts\release\verify_runbook.py --with-tests --with-word --out docs\product-v3-runbook-verification.md`。

每项格式统一为：**准备 → 命令 → 期望 → 判据 → 留档**。判据不满足时请保留原始输出，不要改勾选。

---

## 0. 一分钟总览

| # | 待验收项 | 类型 | 命令入口 | 判据（一句话） |
|---|---|---|---|---|
| A1 | CORE 8.5 同步/归档 | 授权 | `scripts\release\archive_changes.py --yes` | 五个 change 归档后 `openspec validate --strict` 仍全绿 |
| A2 | V3.0 7.4 同步/归档 | 授权 | 同上 | 同上 |
| A3 | V3.1 6.5 同步/归档 | 授权 | 同上 | 同上 |
| A4 | V3.2 7.5 同步/归档 | 授权 | 同上 | 同上 |
| B1 | V3.1 6.3 真实团队交接 | 人工 | `team-flow` + 双目录试跑 | 两位作者交接后无静默覆盖，冲突可见且可跳过 |
| B2 | V3.3 6.2 三类文档人工试点 | 人工 | `assist-search`/`assist-suggest`/`assist-adopt` | 三类文档各有可采纳建议，且采纳可撤销 |
| C1 | 实机 Word：正式化与换机 | 环境 | `V32_REAL_WORD=1` 两个用例 | 用例 Ran OK，产物可打开 |
| C2 | 冻结包写入类闭环 | 环境 | `build_exe.ps1` + `doc-tool-cli.exe env-check` | `env-check` 报 ok=true；导入/转换产出可读文件 |
| C3 | 高 DPI 物理 125%/150% | 环境 | `test_core_hidpi_layout.py` + 实机缩放 | 物理缩放下窗口可达、无横向溢出 |
| C4 | 两机交接（真实两台机器） | 环境 | 交接包 + 另一台机器应用 | 另一台机器可应用且幂等 |
| C5 | Mermaid 预览（mmdc） | 环境 | 安装 `@mermaid-js/mermaid-cli` 后跑全量 | 全量套件 0 失败 |

---

## A. 同步/归档（需先获得授权）

**准备**
- 确认本分支工作树已提交或已备份（归档会改动 `openspec/changes/`）。
- `python scripts\release\archive_changes.py`（默认 dry-run，只核对，不改仓库）。

**命令**
```powershell
python scripts\release\archive_changes.py                # 核对：五个 change 严格校验 + 剩余任务
python scripts\release\archive_changes.py --yes          # 授权后真正归档
openspec list                                            # 复核：五个 change 应移入 archive
openspec validate --strict                               # 复核：整体仍严格通过
```

**期望**：dry-run 打印五个 change 均为 `valid`，并列出剩余任务（A1–A4 对应任务此时应已勾选）。
**判据**：`--yes` 后 `openspec list` 中不再出现这五个 change，且 `validate --strict` 退出码为 0。
**留档**：归档命令输出的 JSON + `openspec list` 文本，附到 `docs/product-v3-release-readiness.md`。

---

## B. 人工试点

### B1 V3.1 6.3：真实团队交接（两位作者、两个目录）

**准备**：一个真实项目（或 `examples/` 复制两份），两位同事各持一份；约定交接包目录（U 盘/共享盘）。
**命令**
```powershell
# 作者一：导出交接包（也可用界面「协作 → 导出内容交接包」）
doc-tool-cli.exe team-flow --project <项目A> --chapters "第1章 引言/1.1 目的.md" --handoff <交接目录> --json
# 作者二：把包放到另一台机器/目录后应用（先看计划再应用）
doc-tool-cli.exe team-flow --project <项目B> --package <交接目录>\内容交接包.zip --json
```
**期望**：报告含 `processed`（待办清点/导出或应用结果）、`artifacts`（包路径）、`conflicts`（若有）。
**判据**：无 Git 也能走本地历史；冲突章节被跳过而不是覆盖，且报告里可见；重复应用同一包不产生重复改动（幂等）。
**留档**：两次 `--json` 输出 + 涉及的章节清单。

### B2 V3.3 6.2：三类文档人工试点（需求/设计/通用）

**准备**：三类真实文档各一份（.docx），导入为项目。
**命令**
```powershell
doc-tool-cli.exe assist-search --project <项目> --query "接口" --json   # 检索
doc-tool-cli.exe assist-suggest --kind term-wording --project <项目> --json  # 建议
doc-tool-cli.exe assist-adopt --project <项目> --suggestion <id> --json      # 采纳（含撤销）
```
**期望**：每类文档都有命中与建议；建议带依据、`notEvidence`。
**判据**：三类文档中至少各有 1 条可采纳建议；采纳后可一次撤销回原文；未配置 provider 时功能不中断（本地候选可用）。
**留档**：三份文档的检索命中数/建议数/采纳与撤销结果；如有质量评分（人工）一并记录。

---

## C. 环境项

### C1 实机 Word：正式化与进程级换机
**准备**：装有 Microsoft Word 的机器；确认无遗留无窗口 WINWORD 进程（否则 COM 可能启动失败）。
**命令**
```powershell
Get-Process WINWORD -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -eq 0 } | Stop-Process -Force
$env:V32_REAL_WORD='1'
python scripts\tests\test_v32_real_word_formalize.py
python scripts\tests\test_v32_cross_process_promote.py
```
**期望**：两个用例 `Ran ... OK`（本机实测 3 项 61 s / 2 项 39 s）。
**判据**：正式化后的 DOCX 能被 Word 打开且状态为正式（非“待刷新”）；换机登记在独立进程内完成且二次运行幂等。
**留档**：两条命令的输出。

### C2 冻结包写入类闭环
**准备**：把 `DocTool.exe` 加入透明加密/杀软信任列表，或换一台无此类策略的机器。
**命令**
```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_exe.ps1
.\dist\DocTool\doc-tool-cli.exe env-check --json --dir <可写目录> --docx <某个.docx>
.\dist\DocTool\doc-tool-cli.exe convert <某个.docx> --to md --target-dir <可写目录>
.\dist\DocTool\doc-tool-cli.exe import --docx <某个.docx> --name Demo --target-dir <可写目录>
```
**期望**：`env-check` 输出 `"ok": true`（退出码 0）；`convert`/`import` 退出码 0 且产出文件可读。
**判据**：`env-check` 不再报 `write`/`docx-read` 问题；导入产物含 `project.yml` 与章节 md。
**留档**：`env-check` 的 JSON + 导入的 JSON（关注 `success`、`presetWarnings`、`environmentWarnings`）。
**若仍失败**：把 `env-check` 的 JSON 原文附上——它能区分“写入被拒”与“读到密文”，便于 IT 定位。

### C3 高 DPI 物理 125%/150%
**准备**：把显示缩放设为 125% 与 150% 各测一轮（离屏模拟回归已固定：`python scripts\tests\test_core_hidpi_layout.py`）。
**命令**：启动 GUI（`dist\启动DocTool.cmd` 或 `python -m doc_tool`），在 1280×720 与最大化下检查首页/编辑器/任务面板。
**判据**：控件不被裁切、首页无横向滚动、按钮可点、弹窗完整可见。
**留档**：截图（首页、编辑器、任务面板各一张）+ 缩放设置。

### C4 两机交接（真实两台机器）
**准备**：机器 A 生成交接包 → 机器 B 应用（可用 U 盘）。
**命令**：同 B1，但两台机器分别执行导出与应用。
**判据**：机器 B 应用成功、内容一致、重复应用幂等；若机器 B 无 Git，走本地历史回退仍可用。
**留档**：两台机器各自的 `--json` 输出与最终章节 diff 摘要。

### C5 Mermaid 预览（mmdc）
**准备**（本机第三十八轮已验证可用，**免管理员、不动全局**）：
```powershell
mkdir tools\mermaid-cli
cd tools\mermaid-cli
npm install --no-audit --no-fund @mermaid-js/mermaid-cli     # 装到项目本地，应用会自动识别 tools/mermaid-cli
npx --yes puppeteer browsers install chrome-headless-shell   # mmdc 需要的无头浏览器
```
应用定位顺序：`PATH` 上的 `mmdc` → `tools/mermaid-cli/node_modules/.bin/mmdc.cmd`（本仓库已支持）。
**命令**：
```powershell
tools\mermaid-cli\node_modules\.bin\mmdc.cmd --version     # 期望输出形如 11.17.0
python scripts\tests\run_tests.py --junit test-results-full.xml
```
**期望/判据**：`mmdc --version` 有输出；全量套件 **0 失败**；Mermaid 工作台状态显示“✅ 渲染成功 · … · mermaid-cli”。
**注意**：若指向系统 Chrome/Edge（`-p puppeteer-config.json`）在本机报
`ProtocolError: Network.enable timed out` / `ConnectionClosedError`，改用上面安装的
`chrome-headless-shell`（即不要提供 puppeteer 配置，让 mmdc 使用自带浏览器）——
第三十八轮实测：自带无头浏览器可用，系统浏览器在本机不可用。
**留档**：JUnit XML + `mmdc --version` 输出。

---

## D. 验收记录表（打印/复制使用）

| 项 | 执行人 | 日期 | 结果（通过/不通过） | 证据路径 | 备注 |
|---|---|---|---|---|---|
| A1–A4 归档 | | | | | |
| B1 团队交接 | | | | | |
| B2 三类文档试点 | | | | | |
| C1 实机 Word | | | | | |
| C2 冻结写入闭环 | | | | | |
| C3 物理缩放 | | | | | |
| C4 两机交接 | | | | | |
| C5 mmdc | | | | | |