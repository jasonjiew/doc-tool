## ADDED Requirements

### Requirement: 自包含测试夹具

测试基础设施 SHALL 提供自包含夹具工厂：在临时目录合成最小可用项目（含 `project.yml`、编号章节 Markdown、模板与必要资源），使核心用例不依赖仓库 `content/` 内置示例文档；每个用例 SHALL 获得隔离的临时目录，结束后 SHALL 清理。

#### Scenario: 夹具生成可校验项目

- **WHEN** 测试调用夹具工厂生成需求项目
- **THEN** 项目结构完整，可被 preflight 后走导入与管线校验

#### Scenario: 迁移示例文档依赖

- **WHEN** 依赖仓库示例文档的用例改用夹具
- **THEN** 该用例在缺少 `content/` 示例文档的工作区仍可运行

#### Scenario: 夹具隔离与清理

- **WHEN** 多个用例并发或顺序使用夹具
- **THEN** 每个用例获得独立的临时目录，测试结束后目录被清理

### Requirement: JUnit 输出

测试运行器 SHALL 生成真实 JUnit XML（`test-results.xml`），包含每个用例的名称、时长、状态与失败消息；CI SHALL 消费该产物并使其与 `.gitlab-ci.yml` 声明的 junit 报告路径一致。

#### Scenario: 运行后生成 JUnit

- **WHEN** 执行 `scripts/tests/run_tests.py`
- **THEN** 产出 `test-results.xml`，路径与 CI 声明的 junit 报告一致

#### Scenario: 失败映射到 testcase

- **WHEN** 存在失败用例
- **THEN** 对应 testcase 标记为 failure 并携带失败消息

### Requirement: 覆盖率报告与门禁

测试运行器 SHALL 收集代码覆盖率并生成报告（如 Cobertura/HTML/JSON）；CI 发布门禁 SHALL 在覆盖率低于配置阈值时失败，并显示阈值与实测值。

#### Scenario: 覆盖率报告生成

- **WHEN** 执行带覆盖率收集的测试运行
- **THEN** 生成覆盖率报告文件并在运行输出中给出汇总值

#### Scenario: 低于阈值阻断发布

- **WHEN** 实测覆盖率低于配置阈值
- **THEN** CI 发布任务失败，日志显示阈值与实测值

### Requirement: 依赖漏洞扫描

发布流水线 SHALL 对最终运行依赖执行漏洞扫描（如 pip-audit/OSV），扫描发现高危漏洞 MUST 阻断发布；扫描报告 SHALL 作为流水线产物归档。

#### Scenario: 无高危漏洞放行

- **WHEN** 漏洞扫描未发现高危漏洞
- **THEN** 发布任务继续执行

#### Scenario: 高危漏洞阻断

- **WHEN** 漏洞扫描发现高危漏洞
- **THEN** 发布任务失败并归档扫描报告，阻止进入发布阶段

### Requirement: 结构化 SBOM

发布流水线 SHALL 生成真实 CycloneDX（JSON）与 SPDX 兼容 SBOM，覆盖运行时与构建期依赖，SBOM SHALL 随发布产物归档并可被标准解析器读取。

#### Scenario: CycloneDX 生成

- **WHEN** 执行打包流水线
- **THEN** 产出 CycloneDX JSON SBOM，可被标准解析器读取

#### Scenario: SBOM 随产物归档

- **WHEN** 发布完成
- **THEN** 安装包、SHA-256 校验和与 CycloneDX/SPDX SBOM 一并归档到发布资产

### Requirement: 门禁在 CI 强制执行

CI SHALL 把单元测试、覆盖率、依赖漏洞扫描与 SBOM 校验作为发布前的强制门禁；任一失败 MUST 阻止进入发布阶段，且失败原因 SHALL 在流水线日志中可定位。

#### Scenario: 测试失败阻止发布

- **WHEN** 单元测试失败
- **THEN** 流水线停在测试阶段，不进入构建与打包

#### Scenario: SBOM 校验失败阻止发布

- **WHEN** 生成的 SBOM 无法通过 schema 校验
- **THEN** 发布任务失败，日志指向具体校验错误
