## Context

失败信息目前三处分散：管线把错误映射为 `StageEvent` + `doc_tool/domain/errors.py` 的稳定错误码（E1xxx 导入、E2xxx 构建校验、E3xxx Word、E4xxx 项目锁、E5xxx 文件系统）；校验报告写为 `logs/<类型>-validation.md` 的 `- [PASS|FAIL] ...` 行；lint 面板展示 `LintIssue`（rule/rel_path/line_no/message），无严重度字段。三者都没有统一的筛选与定位入口。定位能力已具备：`workspace.open_file(rel_path, line_no)` 可打开文件并高亮行。

CLI（`doc_tool/cli.py`）目前只有 `build` 与 `info`，无 JSON/SARIF/JUnit 输出；`run_tests.py` 是自定义 runner，逐文件 subprocess 执行且不产出 `test-results.xml`，而 `.gitlab-ci.yml` 已声明 junit 报告路径；依赖仓库示例文档的用例存在；打包只生成纯文本 SBOM，无漏洞扫描。

本变更按“问题中心 → 机器可读 CLI → 测试/发布门禁”顺序实施，全部为增量扩展，不改变项目数据格式与既有命令语义。

## Goals / Non-Goals

**Goals:**

- 建立统一问题记录模型，整合管线错误、校验报告与 lint 发现。
- 提供可按类型/文档类型/严重度/文件筛选的问题中心，双击定位到文件与行。
- CLI 增加 `preflight`/`import`/`validate`/`lint`/`search`/`status` 命令，支持 JSON、SARIF、JUnit 输出与批量项目处理，退出码稳定。
- 测试夹具自包含，`run_tests.py` 产出真实 JUnit XML 与覆盖率报告。
- CI 增加依赖漏洞扫描与 CycloneDX/SPDX SBOM 生成与校验，作为发布门禁。
- 覆盖自动化测试与人工验收。

**Non-Goals:**

- 不改变 `build`/`info` 既有的人类可读输出与退出码语义。
- 不改变错误码体系、管线阶段事件与 lint 检查规则；仅扩展映射与展示。
- 不做问题自动修复、批处理写回或超出展示/输出的范围。
- 不引入新的 CI 平台或替换现有自定义测试 runner 为 pytest。
- 不改变打包安装布局、项目数据格式与文档构建语义。

## Decisions

### 1. 问题记录统一在内容/应用层建模，UI 只消费

定义统一问题记录（来源、类型、文档类型、严重度、rel_path、line_no、error_code、message、suggested_action），由应用层把三类来源（StageEvent + 错误码表、校验报告解析、LintIssue）归一化；问题中心只做筛选、聚合与定位。这样 CLI 的 SARIF/JUnit 输出可复用同一模型，避免 UI 与 CLI 两套口径。

**Alternatives considered:**

- 在 UI 层各自归一：筛选与输出逻辑重复，且 CLI 无法复用。
- 建立与现有错误类型平行的新体系：与 `errors.py` 的稳定错误码重复。

### 2. 校验报告解析器新增定位信息，而不是只解析 PASS/FAIL

现有 `read_validation_report_summary` 只统计行；新增解析器把每行 `- [FAIL] ...` 连同可获得的文件/行（从消息文本与构建事件上下文）转换为问题记录，解析失败时降级为无定位的条目。校验报告格式保持不变，避免破坏既有读取方。

**Alternatives considered:**

- 让校验直接产出结构化 JSON 报告：改动校验内核输出，回归面大，且与既有报告读取方不兼容。
- 仅保留 PASS/FAIL 统计：无法满足问题中心的定位需求。

### 3. CLI 输出统一走 “命令 → 结果对象 → 序列化器” 三层

每个新子命令先构造结构化结果对象，再按输出格式（human/json/sarif/junit）序列化；human 格式保持现有中文文本样式。JSON 模式进度与日志写 stderr 或日志文件，stdout 只含数据。退出码按全成功/失败/参数错误/部分成功映射（0/1/2/3）。

**Alternatives considered:**

- 每个命令各自拼输出：JSON schema 与 SARIF/JUnit 结构易漂移。
- 统一改为 JSON 默认：破坏既有人类可读行为，属破坏性变更。

### 4. 批量项目处理为“逐项目聚合”，不引入并发调度

批量模式按项目顺序执行，单个项目失败不中断其余项目，最终聚合各项目结果与独立错误码；退出码 3 表示部分成功。这复用现有应用服务的锁与取消语义，避免在 CLI 层重新实现并发。

**Alternatives considered:**

- 并行执行多项目：与项目锁、Word 单进程刷新冲突，风险高。
- 失败即停：无法满足批量场景对“尽量完成”的预期。

### 5. 测试夹具独立于仓库示例文档，作为共享测试工具

新增自包含夹具工厂：在临时目录合成 `project.yml`、编号章节 Markdown、模板与资源，供用例独立调用；逐步把 `test_iteration_scenarios.py` 等依赖 `content/` 的用例迁移过来。夹具工厂作为测试基础设施提交，不进入应用运行时。

**Alternatives considered:**

- 继续依赖仓库示例文档：工作区不完整时用例必败，且修改示例会污染测试结果。
- 复制示例文档到临时目录：仍耦合仓库目录布局，达不到自包含。

### 6. JUnit 与覆盖率在现有自定义 runner 上扩展

`run_tests.py` 继续逐文件执行，但为每个 testcase 记录名称、时长、状态与消息，结束时写出 `test-results.xml`（与 `.gitlab-ci.yml` 声明的 junit 路径一致）；覆盖率用 `coverage`/`coverage.py` 在 subprocess 之外收集并生成报告与阈值门禁。

**Alternatives considered:**

- 迁移到 pytest：改动全部测试文件与 CI，超出本变更范围。
- 继续无 JUnit 产物：CI 声明的 junit 报告形同虚设。

### 7. SBOM 与漏洞扫描作为独立 CI 任务并入现有流水线

在 `.gitlab-ci.yml` 增加漏洞扫描任务（如 pip-audit，从锁定依赖文件生成报告）与 SBOM 生成/校验任务（CycloneDX JSON + SPDX，覆盖运行时与构建期依赖），两者失败即阻断发布；`packaging/build.ps1` 中生成的纯文本 SBOM 保留，新增结构化产物与其并存归档。

**Alternatives considered:**

- 只在打包脚本内生成 SBOM：缺失 CI 门禁语义，漏洞扫描无法阻断发布。
- 用第三方 SBOM 平台：引入外部依赖面，超出内部工具范围。

## Risks / Trade-offs

- [三类来源归一后字段口径不一致，定位信息缺失] → 问题记录允许行号/错误码可空，解析失败降级为可解释条目；映射规则单测覆盖。
- [CLI 输出格式与既有命令漂移] → 统一三层结构（命令→结果对象→序列化器），JSON/SARIF/JUnit schema 用快照测试锁定。
- [批量模式与项目锁/Word 刷新冲突] → 批量按项目顺序执行，复用既有锁与取消语义，不做并发。
- [覆盖率与 JUnit 接入自定义 runner 后性能下降] → 仅 CI 与显式参数开启覆盖收集，本地默认关闭；超时与产物路径可配置。
- [漏洞扫描受镜像/网络环境影响误报或阻塞] → 扫描结果归档并允许人工确认降级，但高危漏洞默认阻断。
- [SBOM 生成工具引入额外构建依赖] → 构建依赖固定版本并纳入自身 SBOM 与漏洞扫描范围。

## Migration Plan

1. 先实现统一问题记录模型与三类来源的解析/归一（管线错误码、校验报告、lint），并补映射单测。
2. 实现问题中心面板：筛选、聚合摘要、双击定位，接入 workspace 与任务终态刷新。
3. 扩展 CLI：新增子命令复用应用服务，实现 JSON 输出与 stdout/stderr 隔离，再补 SARIF/JUnit 与批量模式与退出码。
4. 实现测试夹具工厂，迁移依赖示例文档的用例；为 `run_tests.py` 增加 JUnit 与覆盖率输出。
5. 在 `.gitlab-ci.yml` 增加漏洞扫描与 SBOM 生成/校验任务，更新 `packaging/build.ps1` 归档结构化 SBOM。
6. 全量自动化测试回归（既有 `build`/`info` 与 GUI 面板行为不变）。
7. 人工验收问题中心、CLI 各输出格式与 CI 门禁流水线；运行 PyInstaller 构建与冻结冒烟。

回滚策略：新增命令与问题中心为增量，回滚即移除新增文件与面板接线；CI 任务失败不影响既有构建路径。本变更不修改项目数据格式，回滚无需数据迁移。

## Resolved Decisions

实施过程中已决的原始 Open Questions：

- 校验报告条目的“文件/行”定位：仅从消息文本启发式解析（匹配 `路径.md:行号` / `路径.md 第N行`），不修改构建事件携带结构；解析失败降级为无定位条目（`issues_from_validation_report` + `_parse_location`）。
- 覆盖率阈值与统计范围：阈值取 60%（`.gitlab-ci.yml` `COVERAGE_MIN`），统计范围 `doc_tool,scripts`（`run_tests.py --source`），低于阈值经 `coverage report --fail-under` 阻断。
- 漏洞扫描与 SBOM 工具选型：`pip-audit==2.9.0`（自研 `packaging/audit_dependencies.py` 包装并透传退出码）与自研 `packaging/generate_sbom.py`（CycloneDX 1.5 JSON + SPDX 2.3 JSON）；运行时与构建期依赖均覆盖（`requirements.txt` + `requirements-build.txt`）。
- 问题中心与 lint 面板关系：保持 lint 面板原样，问题中心作为独立“问题”面板统一展示管线/校验/lint 三类来源，并按来源区分。

