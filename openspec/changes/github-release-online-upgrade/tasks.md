## 1. 领域模型与构建发布资产（CI & Domain）

- [x] 1.1 `[REQ-01, REQ-03]` 新增 `doc_tool/domain/update.py`：实现语义版本解析与比较（`parse_semver`、`is_newer_version`）、三种运行形态探测（`detect_install_mode`：`source` / `installer` / `portable`）及 `ReleaseManifest` / `UpdateState` 数据结构。
- [x] 1.2 `[REQ-01]` 新增 `packaging/generate_latest_json.py` 并接入 `.github/workflows/build-release.yml` 与 `.gitlab-ci.yml`：在打包签名完成后生成包含版本号、发布时间、Release Notes、安装器与便携包 URL 及 SHA-256 的 `latest.json`，并加入 Release 上传资产清单。
- [x] 1.3 `[REQ-01, REQ-03]` 编写单元测试 `scripts/tests/test_update_domain.py`：覆盖正式版/预发布版 SemVer 比较、三种运行形态识别及 `latest.json` 生成与序列化校验。

## 2. 更新检查、安全下载与双形态执行服务（Application）

- [x] 2.1 `[REQ-01, REQ-02]` 新增 `doc_tool/application/updater.py`：实现 `~/.doctool/update_state.json` 的 24h TTL 缓存读写、`skippedVersion` 过滤，以及优先请求 `latest.json`、404 回退 GitHub Releases REST API 的双通道元数据拉取（超时 5s，异常静默降级）。
- [x] 2.2 `[REQ-04]` 在 `doc_tool/application/updater.py` 中实现流式下载与 SHA-256 强制校验：安装版使用纯 ASCII 候选临时目录，便携版使用同盘 `.upgrade_staging\` 预解压并校验关键二进制 `MZ`/`PK` 文件头。
- [x] 2.3 `[REQ-05]` 新增便携版外部原子切换与回滚脚本 `packaging/portable/apply_update.ps1`（同步纳入 `stage_dist.ps1` 与 `make_portable.ps1`），实现等待主进程 PID 退出、`DocTool -> DocTool.prev` 备份、新目录切入及启动失败自动回滚。
- [x] 2.4 `[REQ-01, REQ-02, REQ-04, REQ-05]` 编写单元与模拟集成测试 `scripts/tests/test_updater_service.py`：使用本地 Mock HTTP 服务验证 `latest.json` / API 回退、403/断网降级、TTL 缓存命中、SHA-256 篡改拦截、损坏 zip 头拦截及便携版目录切换与失败回滚。

## 3. CLI `upgrade` 子命令与 GUI 非侵入升级交互（CLI & UI）

- [x] 3.1 `[REQ-06]` 在 `doc_tool/cli.py`、`doc_tool/application/cli_commands.py` 与 `doc_tool/application/capabilities.py` 中新增 `upgrade [--check] [--yes] [--output human|json]` 子命令，并确保其余子命令在 JSON 模式下 stdout 零升级提示污染。
- [x] 3.2 `[REQ-06]` 在 `doc_tool/ui/about_dialog.py` 与 `doc_tool/ui/main_window.py`（状态栏右侧胶囊、「帮助」菜单、全局命令面板 `Ctrl+K`）接入后台更新检查、Release Notes 预览弹窗、「跳过此版本」与「立即升级」按钮；触发升级前串联 `unsaved.py` 未保存章节检查与 `word_operations.py` 任务空闲检查。
- [x] 3.3 `[REQ-06]` 编写 CLI 与 GUI 交互回归测试 `scripts/tests/test_update_cli_and_ui.py`：验证 CLI `upgrade --check --output json` 结构化输出、其他命令 JSON 纯净性、源码态拒绝自覆盖提示，以及 GUI 未保存缓冲存在时点击升级的拦截保护。
- [x] 3.4 `[REQ-01, REQ-06]` 更新 `README.md` 与 `docs/COLLEAGUE_AI_CLI_GUIDE.md` 升级说明，运行 `openspec validate github-release-online-upgrade --strict` 与相关回归测试集留存验证证据。
