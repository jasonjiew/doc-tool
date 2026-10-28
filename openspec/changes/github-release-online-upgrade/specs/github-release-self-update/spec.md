## ADDED Requirements

### Requirement: REQ-01 Release 元数据发现与双通道降级
系统 SHALL 支持从 GitHub Releases 获取最新版本元数据；发布流水线 SHALL 生成 `latest.json` 资产，客户端优先拉取 `latest.json`，404 时自动回退 REST API，并支持 `DOC_TOOL_UPDATE_URL` 覆盖（【候选】依据 `.github/workflows/build-release.yml` 与 `branding.py`）。

#### Scenario: 优先通过 latest.json 发现新版本
- **WHEN** 远端 Release 包含 `latest.json` 且其语义版本高于当前 `APP_VERSION`（非 draft / prerelease）
- **THEN** 客户端在一次请求内解析出最新版本号、Release Notes 及安装版/便携包的下载 URL 与 SHA-256，不消耗 GitHub REST API 配额

#### Scenario: 旧版 Release 缺少 latest.json 时自动回退 API
- **WHEN** 请求 `latest.json` 返回 HTTP 404，但 GitHub Releases API `/releases/latest` 可达
- **THEN** 客户端自动从 API 响应解析 `tag_name`、`body` 与 `assets` 列表，并按需拉取 `.sha256` 资产文本完成元数据组装

#### Scenario: 离线或 API 限流时静默降级
- **WHEN** 客户端处于无外网环境、请求超过 5 秒超时上限或收到 HTTP 403 Rate Limit
- **THEN** 后台自动检查静默结束、不弹窗报错、不改写已有业务状态；手动点击「检查更新」时展示脱敏的可读失败原因与手动下载链接

### Requirement: REQ-02 本地 TTL 缓存与用户升级偏好
系统 SHALL 在 `~/.doctool/update_state.json` 中持久化 `lastCheckedAt`（默认 TTL 24 小时）、版本元数据、`skippedVersion` 与 `autoCheck` 开关；缓存损坏时自动忽略重建（【候选】依据 `branding.py` `user_config_dir()`）。

#### Scenario: 24 小时 TTL 内重复启动
- **WHEN** 距离上次成功检查不足 24 小时且用户未点击手动「检查更新」
- **THEN** 系统直接使用 `update_state.json` 缓存结果判断是否提示新版本，不发起任何外部 HTTP 请求

#### Scenario: 用户选择跳过某版本
- **WHEN** 用户对 `v3.1.0` 点击「跳过此版本」
- **THEN** 系统将 `skippedVersion` 记为 `3.1.0`，后续自动检查遇到 `3.1.0` 不再弹出提示，直至远端发布更高版本或用户手动触发检查

### Requirement: REQ-03 运行与分发形态自动识别
系统 SHALL 根据 `sys.frozen` 与应用目录内是否存在 `uninst\unins*.exe`，准确识别源码态（`source`）、安装版（`installer`）与便携版（`portable`）三种运行形态（【现状+候选】依据 `version.py` 与 `installer.iss`）。

#### Scenario: 源码开发态触发升级
- **WHEN** 运行形态为 `source` 且用户运行 `upgrade` 或在 GUI 点击升级
- **THEN** 系统展示远端最新版本信息并提示使用 `git pull` 更新源码，拒绝下载二进制覆盖当前工作树

#### Scenario: 安装版与便携版分别匹配资产
- **WHEN** 运行形态为 `installer` 或 `portable`
- **THEN** 系统分别选择 `DocTool-Setup-<v>.exe` 或 `DocTool-<v>-portable.zip` 及其对应 `.sha256` 作为下载目标

### Requirement: REQ-04 SHA-256 强制校验与安全暂存预检
系统下载升级包后 MUST 校验 SHA-256；安装版 SHALL 使用纯 ASCII 临时目录，便携版 MUST 使用同盘 `.upgrade_staging\` 预解压并在切换前校验关键二进制 `MZ`/`PK` 文件头（【现状+候选】依据 `self_heal.py` 与 `preflight.ps1`）。

#### Scenario: SHA-256 校验不匹配
- **WHEN** 下载的 `.exe` 或 `.zip` 实际 SHA-256 与 `.sha256` 记录不一致
- **THEN** 立即删除已下载的临时文件，终止升级流程并报告校验失败，当前应用目录保持原样

#### Scenario: 便携版解压产物被透明加密改写文件头
- **WHEN** `.upgrade_staging` 内 `base_library.zip`、`python313.dll` 或可执行文件头损坏（非 `PK`/`MZ`）且无法自修复
- **THEN** 阻断目录切换，保留当前正在运行的便携版目录完好，并给出终端安全软件白名单处置提示

### Requirement: REQ-05 安装版静默接管与便携版原子目录切换回滚
系统 SHALL 按分发形态执行替换：安装版退出后拉起 Inno Setup `/SILENT /RESTARTAPPLICATIONS`；便携版退出后由 `apply_update.ps1` 等待原 PID 结束并执行 `DocTool -> DocTool.prev` 原子切换，失败自动回滚（【候选】依据 `installer.iss` 与 `启动DocTool.cmd`）。

#### Scenario: 安装版一键静默升级
- **WHEN** 安装版用户确认升级且下载校验通过
- **THEN** 主程序安全退出，Inno Setup 静默覆盖原安装目录并自动重启新版 `DocTool.exe`，用户项目与 `~/.doctool` 配置保持不变

#### Scenario: 便携版原子切换与失败自动回滚
- **WHEN** 便携版退出后 `apply_update.ps1` 执行目录切换异常或新版首次启动预检返回 `BROKEN`/`STARTFAIL`
- **THEN** 脚本自动清理残缺的新 `DocTool\` 目录并将 `DocTool.prev\` 恢复为 `DocTool\`，写明升级回滚日志，保证旧版仍可正常启动

### Requirement: REQ-06 GUI 非侵入交互与 CLI upgrade 机器契约隔离
系统 SHALL 在 GUI 状态栏/帮助/命令面板/关于页提供更新入口，升级退出前 MUST 通过 `unsaved.py` 未保存检查与 `word_operations.py` 任务检查；CLI SHALL 提供 `upgrade` 子命令且其他命令在 JSON 模式下 MUST NOT 污染 stdout（【现状+候选】依据 `main_window.py` 与 `COLLEAGUE_AI_CLI_GUIDE.md`）。

#### Scenario: GUI 含未保存章节时点击立即升级
- **WHEN** 用户在编辑器中有未保存的 Markdown 章节修改并点击「立即升级并重启」
- **THEN** 先弹出未保存更改确认框（保存 / 不保存 / 取消）；若用户选择「取消」，则中止升级交接，不启动安装器、不丢失缓冲内容

#### Scenario: AI Agent 调用 CLI JSON 模式
- **WHEN** 外部脚本或 AI 运行 `doc-tool-cli baseline-check --project <dir> --format json` 且远端恰好存在新版本
- **THEN** stdout 仅输出合法的单文档 JSON 结果，无任何升级横幅文本混入
