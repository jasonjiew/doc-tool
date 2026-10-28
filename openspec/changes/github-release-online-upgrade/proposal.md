## Why

`doc-tool` 已在 `.github/workflows/build-release.yml` 中建立了标准化的 GitHub Release 发布流水线（产出 `DocTool-Setup-<v>.exe`、`DocTool-<v>-portable.zip` 及其 `.sha256`），但团队成员与外部用户目前仍需手工访问 GitHub Releases 页面下载并覆盖安装，版本滞后易引发团队协同规范包或模板契约不一致。需要模仿 Codex CLI 与现代桌面工具提供“后台静默检查 + 非侵入提示 + 按分发形态一键自升级”的在线升级闭环。

## What Changes

- **CI 发布端补充 `latest.json` 元数据索引**（关联 `REQ-01`）：在 GitHub Release 与 GitLab Release 打包阶段同步生成轻量 `latest.json` 资产，配合 GitHub Releases API 回退机制，规避办公网共享公网 IP 下的 GitHub API 60 次/小时限流。
- **本地 TTL 缓存与分发形态探测**（关联 `REQ-02`、`REQ-03`）：在 `~/.doctool/update_state.json` 维护 24 小时检查缓存与跳过版本设置；自动识别源码态（`source`）、Inno Setup 安装版（`installer`）与免安装便携版（`portable`）。
- **SHA-256 强校验与双形态自升级执行器**（关联 `REQ-04`、`REQ-05`）：适配非 ASCII 用户名路径与亿赛通（DocGuard）透明加密环境，完成安装版 `/SILENT` 静默接管升级与便携版同盘 `.upgrade_staging` 预解压 + 退出后原子切换（含 `.prev` 自动回滚）。
- **GUI 与 CLI 双端升级入口及 AI 契约隔离**（关联 `REQ-06`）：在 GUI 状态栏、帮助菜单、命令面板（`Ctrl+K`）及关于弹窗提供检查与升级入口（升级前强制检查未保存章节与活跃 Word 任务）；CLI 新增 `doc-tool-cli upgrade` 子命令，并确保 JSON 机器输出模式零污染。

## Non-Goals

- 不引入 `PySide6.QtNetwork`、`requests` 等新依赖（严格使用 Python 标准库 `urllib.request` / `hashlib` / `zipfile`）。
- 不在源码开发态（`sys.frozen == False`）执行二进制覆盖。
- 不在未经用户确认或存在未保存章节缓冲时静默强杀重启应用。
- 不做二进制差分补丁（bsdiff），本期直接消费 Release 完整安装包/便携包资产。

## Capabilities

### New Capabilities
- `github-release-self-update`: 基于 GitHub Release（含内网源扩展）的版本发现、SHA-256 校验、安装版/便携版自升级与回滚闭环（`REQ-01` ~ `REQ-06`）。

### Modified Capabilities
无。复用现有 `version.py`、`branding.py`、`unsaved.py`、`word_operations.py`、`preflight.ps1` 与 `installer.iss`，不改变既有文档构建或校验契约。

## Impact

涉及 `.github/workflows/build-release.yml`、`.gitlab-ci.yml`、`packaging/`（新增 `generate_latest_json.py` 与便携版切换脚本 `apply_update.ps1`）、`doc_tool/domain/update.py`、`doc_tool/application/updater.py`、`doc_tool/cli.py`、`doc_tool/ui/main_window.py` 与 `doc_tool/ui/about_dialog.py`。离线环境或内网断网时所有网络异常静默降级，不影响离线编辑与出稿主流程。
