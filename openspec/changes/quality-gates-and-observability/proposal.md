## Why

构建与校验失败目前分散在事件日志、校验报告与 lint 面板中，缺少统一的筛选与定位手段；CLI 只有 `build`/`info` 两个命令且无可机读输出，无法接入持续集成；发布门禁依赖仓库内置示例文档，且没有覆盖率、依赖漏洞扫描与结构化 SBOM，难以对发布质量形成可信屏障。

## What Changes

- 新增结构化问题中心：把管线失败（`StageEvent` + 稳定错误码）、校验报告（`logs/<类型>-validation.md`）与 lint 发现（`LintIssue`）归一为统一问题记录（来源/类型/文档类型/严重度/文件/行/错误码/消息/建议），提供可按维度组合筛选的列表与严重度摘要，双击经 `workspace.open_file(rel_path, line_no)` 定位到文件与行。
- 扩展 CLI 为机器可读命令集：新增 `preflight`/`import`/`validate`/`lint`/`search`/`status` 子命令，统一支持 `--output json`，`validate`/`lint` 支持 SARIF 2.1.0，`validate` 支持 JUnit XML，并支持一次处理多个项目；退出码采用稳定语义（0 全成功 / 1 至少一个失败 / 2 参数错误 / 3 批量部分成功）。
- 建立测试与发布门禁：提供自包含测试夹具（不依赖仓库 `content/` 示例文档），`run_tests.py` 输出真实 JUnit XML 与覆盖率报告；CI 增加依赖漏洞扫描与真实 CycloneDX/SPDX SBOM 生成与校验，任一失败阻止发布。
- 破坏性变更：无。现有 `build`/`info` 命令的人类可读输出与退出码保持为默认行为，新命令与输出格式为增量。

## Capabilities

### New Capabilities

- `structured-issue-center`: 构建与校验问题的结构化展示、筛选与定位能力。
- `machine-readable-cli`: 面向脚本与 CI 的机器可读命令行能力。
- `test-release-gate`: 自包含测试夹具、JUnit 输出、覆盖率、依赖漏洞扫描与结构化 SBOM 的发布门禁能力。

### Modified Capabilities

无。问题中心是 lint 与校验结果的**新消费视图**，`content-lint`/`work-detail-pane` 既有需求语义不变；`content-lint` 的行为扩展（配置驱动规则、`severity`/`rule_id`）由 `quality-traceability-and-review` 的 delta spec 承载。

## Impact

- 主要受影响代码：`doc_tool/cli.py`（新命令与输出格式）、`doc_tool/ui/content/`（问题中心面板与接入）、`doc_tool/domain/errors.py`（错误码到问题记录/严重度的映射）、`scripts/tests/run_tests.py`（JUnit 与覆盖率）、`.gitlab-ci.yml`（漏洞扫描与 SBOM 任务）、`packaging/build.ps1`（SBOM 生成与归档）。
- 关联代码：`doc_tool/application/pipeline.py`（StageEvent 来源）、`scripts/validate_docx.py`（校验报告解析）、`doc_tool/application/content/lint.py`（lint 发现）、`doc_tool/application/content/search.py` 与 `doc_tool/domain/content_index.py`（search/status 命令）、`doc_tool/adapters/preflight.py` 与 `doc_tool/application/import_project.py`（preflight/import 命令）、`doc_tool/ui/content/workspace.py`（定位入口）。
- 测试影响：新增自包含夹具工具与 CLI 输出快照测试；依赖仓库示例文档的用例（如 `test_iteration_scenarios.py`）迁移到夹具。
- 打包影响：打包流水线新增 CycloneDX/SPDX SBOM 与漏洞扫描报告产物；不改变安装布局与项目数据格式。
- 兼容性：项目数据格式、构建语义与既有 CLI 行为不变；新增命令与输出格式为增量，不做破坏性替换。
