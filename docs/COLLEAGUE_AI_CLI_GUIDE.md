# DocTool 3.0.0 免安装便携版与 AI / CLI 调用指南

本文档面向两类使用者：
1. **普通同事 / 业务工程师**：无需安装系统 Python、无需配置 pip、无需下载 `doc-tool` 源码，解压完整便携包后即可使用桌面 GUI 工作台。
2. **AI Agent / 自动化脚本**：通过会话环境变量 `$env:DOC_TOOL_CLI` 直接调用便携包内置的 `doc-tool-cli.exe`，完成文档基线核对、条目查询、影响分析、证据关联与 GitLab MR 附件报告生成。

---

## 1. 快速交付与环境准备（零安装原则）

### 1.1 下载与解压
- 从发布渠道或构建产物目录获取 `DocTool-3.0.0-portable.zip` 及其对应的校验文件 `DocTool-3.0.0-portable.zip.sha256`。
- 校验哈希（PowerShell 示例）：
  ```powershell
  Get-FileHash -Algorithm SHA256 .\DocTool-3.0.0-portable.zip
  Get-Content .\DocTool-3.0.0-portable.zip.sha256
  ```
- 解压至本地任意路径（推荐例如 `D:\Tools\DocTool-3.0.0-portable\`）。目录中包含：
  - `DocTool/DocTool.exe`：现代化桌面 GUI 入口。
  - `DocTool/doc-tool-cli.exe`：全功能无头 CLI 入口。
  - `DocTool/_internal/`：预封装的独立 Python 运行时及依赖库。
  - `启动DocTool.cmd`：本地原地快速启动批处理脚本。
  - `diagnose.cmd`：受管终端运行环境诊断脚本。

### 1.2 原地运行机制（In-Place Running）
- **无临时目录解压**：便携包已针对企业透明加密与权限策略加固，所有组件均原地加载，**严禁且不会复制到 `%TEMP%` 启动**。
- **只读保证**：CLI 命令除明确指定 `--report-file` 导出产物外，所有查询类命令（`capabilities`、`baseline-check`、`item-list`、`item-show`、`review-status`）严格保证不对被分析的文档仓库进行任何文件写入或 Git 状态修改。

---

## 2. CLI 环境变量配置与机器契约

### 2.1 会话级环境变量配置
在 PowerShell 或 Bash 终端中配置当前会话路径（**切勿配置到机器全局或提交个人绝对盘符到共享仓库**）：

```powershell
# PowerShell
$env:DOC_TOOL_CLI = 'D:/Tools/DocTool-3.0.0-portable/DocTool/doc-tool-cli.exe'
& $env:DOC_TOOL_CLI --version
```

```bash
# Bash / Git Bash
export DOC_TOOL_CLI="/d/Tools/DocTool-3.0.0-portable/DocTool/doc-tool-cli.exe"
"$DOC_TOOL_CLI" --version
```

### 2.2 机器交互契约（Pure stdout JSON Stream）
当使用 `--format json` 时：
- **标准输出（stdout）**：仅输出单个合法的 JSON 根文档，无控制字符、无 ANSI 颜色转义、无日志噪声，支持管道直接对接 `jq` 或 Python `json.loads()`。
- **标准错误（stderr）**：仅用于流式输出排查诊断、进度提示或警告。
- **退出码约定（Exit Codes）**：
  - `0`：命令成功执行，且所请求的检查/门禁完全满足（Pass）。
  - `1`：命令正常执行完成，但所核对的基线或门禁存在冲突、未通过或阻断项（Gate Rejected / Incomplete）。
  - `2`：命令行参数错误、路径不存在或执行异常（Execution / Usage Error）。

---

## 3. 核心 CLI 命令与自动化场景

### 3.1 查询能力清单 (`capabilities`)
查询当前便携包固化的构建来源、提交哈希、支持的命令及其参数契约。
```powershell
& $env:DOC_TOOL_CLI capabilities --format json
```
**说明**：构建哈希与构建时间直接读取打包时烘焙的元数据（Baked Metadata），绝不会借用调用方当前所在目录的 Git HEAD。

---

### 3.2 文档基线核对 (`baseline-check`)
比对文档项目清单（`manifest.yaml`）、修订记录（`_revision_record.md`）与团队声明文件（如根目录 `README.md`）中的版本号，精准识别版本脱节与冲突。

```powershell
& $env:DOC_TOOL_CLI baseline-check `
    --project "D:/ai_flow_space/sample-docs/requirements/DOC-REQ-2026-001 通用软件需求规格说明书" `
    --declare-file "D:/ai_flow_space/sample-docs/README.md" `
    --format json
```
**输出要点**：
- 报告中明确列出各方提取出的版本号（例如：清单 `3.8` vs 修订记录 `3.8` vs README `3.10`）。
- 存在版本冲突时，退出码为 `1`，同时标明冲突位置，**工具不会擅自猜选较大版本**，要求人工/团队介入确认。

---

### 3.3 需求与设计条目检索 (`item-list`, `item-show`)
按项目、章节范围检索原子条目（`DOC-ITEM`），支持自动分页与内容摘要。

```powershell
# 列出指定文档项目全部条目（支持分页）
& $env:DOC_TOOL_CLI item-list `
    --project "D:/ai_flow_space/sample-docs/requirements/DOC-REQ-2026-001 通用软件需求规格说明书" `
    --page 1 --page-size 20 `
    --format json

# 查询指定条目详情（含行号、正文原子范围与锚点）
& $env:DOC_TOOL_CLI item-show `
    --project "D:/ai_flow_space/sample-docs/requirements/DOC-REQ-2026-001 通用软件需求规格说明书" `
    --item "DOC-REQ-001" `
    --format json
```
**安全边界**：解析器自动剔除代码块内部（```` ``` ````）的示例标记，杜绝假条目注入。

---

### 3.4 签审绑定与失效状态核查 (`review-status`)
查询文档项目或指定基线绑定的签审记录，并基于内容哈希（`content_hash`）核对当前正文是否已发生漂移。

```powershell
& $env:DOC_TOOL_CLI review-status `
    --project "D:/ai_flow_space/sample-docs/requirements/DOC-REQ-2026-001 通用软件需求规格说明书" `
    --baseline "3.8" `
    --format json
```
**失效逻辑**：
- 若旧签审记录未包含内容哈希绑定，标明 `unverified`（无法核实对当前内容的确认）。
- 若内容已被修改，状态标明 `stale`（已失效，需重新复核），杜绝静默假通过。

---

### 3.5 稳定条目迁移建议预览 (`trace-plan`)
复用稳定条目迁移能力，为未打标的存量 Markdown 章节生成确定性的稳定条目 ID 建议，支持重复调用且 ID 不漂移。

```powershell
& $env:DOC_TOOL_CLI trace-plan `
    --project "D:/ai_flow_space/sample-docs/requirements/DOC-REQ-2026-001 通用软件需求规格说明书" `
    --report-file "D:/ai_flow_space/doc-tool/analysis/trace_plan_preview.json" `
    --format json
```
**说明**：此命令为**纯只读预览**，不会向任何 Markdown 文件写入标记。

---

### 3.6 研发变更报告与 GitLab MR 附件汇总 (`change-report`)
汇总多仓库 Git 元数据、受影响文档条目、实际执行的测试证据（JUnit XML）与人工验收记录，生成完整的 GitLab MR 附件报告。

#### 变更清单清单格式示例 (`change_manifest.json`)：
```json
{
  "change_id": "CHG-2026-10-01",
  "openspec_change_id": "devflow-cli-and-portable-delivery",
  "gitlab_mr": "!1024",
  "repositories": [
    {
      "repo_name": "hcp-backend",
      "repo_path": "D:/ai_flow_space/hcp",
      "head_commit": "a1b2c3d4",
      "base_commit": "e5f6g7h8",
      "diff_stat": "3 files changed, 45 insertions(+), 12 deletions(-)",
      "changed_files": ["src/service/auth.py", "src/controller/auth.py"]
    }
  ],
  "affected_doc_items": ["DOC-REQ-AUTH-001", "DOC-DES-AUTH-001"],
  "test_evidence": [
    {
      "suite_name": "backend-auth-tests",
      "junit_xml_path": "D:/ai_flow_space/hcp/build/test-results/junit.xml",
      "command": "mvn test",
      "execution_time": "2026-10-14T10:00:00Z"
    }
  ],
  "manual_acceptance": [
    {
      "item": "双因子认证弹窗真机核验",
      "verifier": "张工",
      "status": "passed",
      "evidence": "已在受控机实际完成验证，日志见 doc-tool/analysis/2fa_verify.log"
    }
  ]
}
```

#### 生成 GitLab MR 附件 Markdown 报告：
```powershell
& $env:DOC_TOOL_CLI change-report `
    --manifest "D:/ai_flow_space/doc-tool/analysis/change_manifest.json" `
    --format markdown `
    --report-file "D:/ai_flow_space/doc-tool/analysis/mr_attachment.md"
```
**门禁核验标准**：
- JUnit XML 中的 `skipped` 测试用例**绝不计为 passed**。
- 若有任何用例失败或必要测试未执行，退出码返回 `1`，报告中显式列出阻断项。

---

### 3.7 在线自升级与版本检查 (`upgrade`)

支持从 GitHub Releases（或内网镜像源）自动拉取轻量 `latest.json` 索引，完成版本探测、SHA-256 校验与双形态自升级：

1. **只读检查当前是否有新版本（不执行下载）：**
```powershell
& $env:DOC_TOOL_CLI upgrade --check --output json
```
输出纯净结构化 JSON，便于自动化脚本与 AI 接入：
```json
{
  "command": "upgrade",
  "success": true,
  "hasUpdate": true,
  "currentVersion": "3.0.1",
  "latestVersion": "3.1.0",
  "installMode": "portable",
  "actionTaken": "check",
  "manifest": { ... }
}
```

2. **执行一键升级（免交互）：**
```powershell
& $env:DOC_TOOL_CLI upgrade --yes
```
- **安装版**：下载到纯 ASCII 临时目录，强校验 SHA-256 后静默拉起 Inno Setup 覆盖升级并自动重启。
- **便携版**：同盘解压至 `.upgrade_staging` 并校验关键二进制头（MZ/PK），退出后由 `apply_update.ps1` 完成 `DocTool -> DocTool.prev` 原子切换（失败自动回滚旧版）。
- **源码开发态**：拒绝自覆盖工作树，明确提示使用 `git pull` 更新。

3. **指定内网镜像源或离线包源：**
```powershell
& $env:DOC_TOOL_CLI upgrade --check --custom-url "https://internal-repo.example.com/releases/latest.json"
```


## 4. 故障排查与诊断指引

若在受限办公环境（如亿赛通、深信服等安全终端）遇到启动阻断或运行时异常：
1. 双击解压目录根目录下的 `diagnose.cmd`。
2. 诊断脚本将自动收集系统版本、VC++ 运行库状态、进程环境、相关动态链接库（DLL）加载路径及受控加固标记。
3. 产出的 `DocTool-diagnose.txt` 可直接附在技术支持工单中反馈给维护人员。
