## Context

`doc-tool` 当前已有双套同源 CI 发布管线（`.github/workflows/build-release.yml` 与 `.gitlab-ci.yml`），且在 `v1.4.4`～`v3.0.1` 演进中沉淀了针对企业终端安全软件（火绒）与透明加密客户端（亿赛通 DocGuard）的原地启动与 `preflight.ps1` 自检机制。本次设计在不引入任何第三方依赖的前提下，为 GUI 与 CLI 补齐模仿 Codex 的在线升级闭环（覆盖 `REQ-01` ~ `REQ-06`）。

## Goals / Non-Goals

- **Goals**：实现零阻塞启动检查（`REQ-01`、`REQ-02`）、三态自动识别（`REQ-03`）、SHA-256 与透明加密预检（`REQ-04`）、安装版/便携版无感升级与回滚（`REQ-05`），以及 GUI 未保存保护与 CLI JSON 契约隔离（`REQ-06`）。
- **Non-Goals**：同 `proposal.md` 的 Non-Goals，不重复定义需求正文。

## Decisions

### 1. 采用 `latest.json` 静态资产为主、GitHub REST API 为辅的双模发现（实现 `REQ-01`、`REQ-02`）
- **决策**：新增 `packaging/generate_latest_json.py`，在 CI 阶段 4（哈希计算完成后）生成 `latest.json` 并随 `softprops/action-gh-release@v2` 一起上传到 Release 资产。
- **理由**：直接请求 `https://github.com/wangjie0721666-web/doc-tool/releases/latest/download/latest.json` 走 GitHub Release 文件 CDN，彻底规避 `api.github.com` 未认证请求每 IP 每小时 60 次的限流；同时保留 REST API 解析逻辑，以兼容历史未带 `latest.json` 的 Release 标签。
- **备选与取舍**：不采用每次启动无缓存直连 GitHub API，避免企业 NAT 出口集体 403。

### 2. 纯标准库实现网络与校验，严格隔离业务层与 Qt（实现 `REQ-01`、`REQ-04`）
- **决策**：`doc_tool/domain/update.py`（纯数据模型、SemVer 解析、安装形态判定）与 `doc_tool/application/updater.py`（`urllib.request` 下载、`hashlib.sha256` 校验、缓存读写、进程交接）不导入任何 `PySide6` 模块；GUI 通过后台工作线程调用 `updater.py`。
- **理由**：符合 `packaging/doc_tool.spec` 排除 `PySide6.QtNetwork` 的体积与安全边界，且让 `doc-tool-cli.exe` 与 `DocTool.exe` 100% 共享同一套升级服务。

### 3. 安装版与便携版分流执行，规避 `taskkill /F` 与跨盘符 `WinError 17`（实现 `REQ-03`、`REQ-04`、`REQ-05`、`REQ-06`）
- **决策**：
  1. **未保存与 Word 锁前置门禁**：GUI 在拉起外部升级进程前，必须先调用 `MainWindow` 既有的未保存章节检查与 Word 任务忙闲检查，由主进程自己优雅退出，避免触发 `packaging/installer.iss` 中 `taskkill /IM DocTool.exe /F /T` 造成未保存数据丢失。
  2. **安装版（`installer`）**：下载到 `doc_tool/application/self_heal.py` `_candidate_bases()` 选出的纯 ASCII 临时目录，校验 SHA-256 后以脱离进程组启动 `DocTool-Setup-<v>.exe /SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS`。
  3. **便携版（`portable`）**：在便携包根目录内建立同盘 `.upgrade_staging\` 解压 `DocTool-<v>-portable.zip`，调用 `preflight.ps1` 校验 `MZ`/`PK` 文件头通过后，启动脱离父进程的 `packaging/portable/apply_update.ps1`，主进程退出后完成 `DocTool -> DocTool.prev` 与 `.upgrade_staging\DocTool -> DocTool` 切换，失败自动还原 `DocTool.prev`。

## Risks / Trade-offs

- **[办公网无法访问 GitHub Release CDN]** → 支持 `DOC_TOOL_UPDATE_URL` 与 `~/.doctool/update_state.json` 中的 `customEndpoint` 指向内网 GitLab Release 或文件服务器（`REQ-01`）。
- **[便携版目录内被用户误放个人项目文件]** → `apply_update.ps1` 仅替换 `DocTool\` 子目录及根目录受控脚本（`启动DocTool.cmd`、`preflight.ps1`、`diagnose.cmd`），不删除便携包根目录下用户自建的其他文件夹，且保留一版 `DocTool.prev\`（`REQ-05`）。
- **[CLI 升级时 `doc-tool-cli.exe` 自身被锁]** → 便携版在 CLI 下触发 `upgrade` 同样交由脱离进程的 `apply_update.ps1` 等待 `doc-tool-cli.exe` 退出后再切换目录（`REQ-05`）。

## Migration Plan

- `~/.doctool/update_state.json` 为纯新增可选文件，旧版本升级或回滚均不影响既有 `geometry.json`、`recent.json` 与项目内 `.state/`。
- CI 新增上传 `latest.json` 不改变现有 `DocTool-Setup-<v>.exe` 与 `DocTool-<v>-portable.zip` 的文件名与校验规则，向后完全兼容。

## Open Questions

- 是否需要在 GUI 设置中提供内网镜像 URL 的可视化输入框（首期默认支持通过 `~/.doctool/update_state.json` 与环境变量 `DOC_TOOL_UPDATE_URL` 配置，GUI 提供「自动检查更新」开关与「立即检查」按钮）。
