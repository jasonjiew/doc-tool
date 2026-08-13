## 1. 统一问题模型与来源解析

- [x] 1.1 定义统一问题记录模型与严重度映射：来源（管线/校验报告/lint）、类型、文档类型、严重度、文件、行号、错误码、消息、建议，行号与错误码允许可空
- [x] 1.2 实现管线失败归一：把 `StageEvent` + 稳定错误码映射为问题记录，未知错误码按稳定默认规则降级
- [x] 1.3 实现校验报告解析器：把 `logs/<类型>-validation.md` 的 `- [FAIL] ...` 行解析为问题记录，缺失定位信息时降级为无行号条目
- [x] 1.4 实现 lint 发现归一：把 `LintIssue`（rule/rel_path/line_no/message）映射为问题记录并派生严重度
- [x] 1.5 补充问题模型与来源解析的自动化测试（三类来源、缺行号、未知错误码、解析失败降级）

## 2. 结构化问题中心 UI

- [x] 2.1 实现问题列表面板：列包含严重度、类型、文档类型、文件、行、消息、错误码，接入 `workspace`
- [x] 2.2 实现按类型、文档类型、严重度、文件的组合筛选与严重度聚合摘要
- [x] 2.3 实现双击定位：复用 `workspace.open_file(rel_path, line_no)`，处理无行号与文件已删除场景
- [x] 2.4 接入任务终态与 lint 运行后的自动刷新，项目切换清空，刷新保持已选筛选条件
- [x] 2.5 补充 GUI 自动化测试：筛选组合、聚合摘要、双击定位、刷新保持、文件缺失与项目切换清空

## 3. 机器可读 CLI 命令集

- [x] 3.1 扩展 `doc_tool/cli.py` argparse：新增 `preflight`/`import`/`validate`/`lint`/`search`/`status` 子命令，复用现有应用服务与错误码映射
- [x] 3.2 实现“命令→结果对象→序列化器”三层结构，新增 `--output json` 与 stdout/stderr 隔离，默认保持人类可读
- [x] 3.3 实现 `validate`/`lint` 的 SARIF 2.1.0 输出（规则映射错误码/规则 id，level 映射严重度，location 指向文件行）
- [x] 3.4 实现 `validate` 的 JUnit XML 输出（每文档类型/项目对应 testcase/testsuite）
- [x] 3.5 实现批量项目处理（重复 `--project`）与稳定退出码（0/1/2/3），单项目失败不中断批量
- [x] 3.6 补充 CLI 自动化测试：JSON schema 快照、SARIF/JUnit 结构、退出码、批量部分成功、参数错误、日志不污染 stdout

## 4. 测试与发布门禁

- [x] 4.1 实现自包含测试夹具工厂（临时目录合成 project.yml、编号章节 Markdown、模板与资源）并迁移依赖仓库示例文档的用例（如 `test_iteration_scenarios.py`）
- [x] 4.2 为 `scripts/tests/run_tests.py` 增加 JUnit XML 输出，使其与 `.gitlab-ci.yml` 声明的 junit 报告路径一致
- [x] 4.3 为 `run_tests.py` 增加覆盖率收集与报告生成，CI 配置覆盖率阈值门禁
- [x] 4.4 在 `.gitlab-ci.yml` 增加依赖漏洞扫描任务（如 pip-audit）并设置高危漏洞阻断规则，扫描报告归档
- [x] 4.5 在 CI/打包流水线生成 CycloneDX JSON 与 SPDX SBOM，覆盖运行时与构建期依赖，随发布资产归档
- [x] 4.6 补充门禁自动化测试：JUnit/覆盖率/SBOM 可解析、夹具迁移用例运行、漏洞扫描脚本冒烟

## 5. 集成与人工验收

- [x] 5.1 运行全量自动化测试回归，确认既有 `build`/`info` 命令、GUI 面板与打包行为无回归
- [ ] 5.2 人工验证问题中心（三类来源、筛选、聚合摘要、双击定位、项目切换）与 CLI 各命令的 JSON/SARIF/JUnit 输出
- [ ] 5.3 在 CI 环境验证门禁流水线：测试失败阻断、覆盖率阈值、漏洞扫描阻断、SBOM 生成与校验、发布资产归档
- [ ] 5.4 运行 PyInstaller 构建与冻结程序冒烟测试，确认问题中心与 CLI 在冻结态正常
