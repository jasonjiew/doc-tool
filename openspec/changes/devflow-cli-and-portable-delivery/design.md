# 设计文档：研发流程接入与免安装交付 (devflow-cli-and-portable-delivery)

## 1. 架构与设计原则

- **免安装第一**：CLI 与 GUI 使用相同的底层应用服务，依赖和运行时随包自足，不依赖宿主机器 Python/pip。
- **构建来源严格固化**：打包时生成 `_build_metadata.py`，记录 Git Commit SHA、构建时间、版本号、dirty 标记；运行时优先加载固化元数据，避免在未跟踪/同事业务仓库的 cwd 下借用他人 HEAD。
- **纯净单 JSON 输出**：`--format json` 时 stdout 仅输出一个合法 JSON 文档；所有的进度信息、警告或调试日志统一重定向至 stderr。
- **只读查询零副作用**：查询、检查、比对命令严格保持被检查项目文件及 Git 状态只读，任何报告生成均需调用者显式提供 `--report-file` 或输出到 stdout。
- **显式不完整性**：缺失证据、缺少基线、跳过的用例（skipped）严格区分，绝不因为缺少信息而静默记为通过。

## 2. 模块划分与详细设计

### 2.1 构建来源与能力自省 (`doc_tool/domain/version.py`, `capabilities`)
- 在 `doc_tool/domain/version.py` 中引入 `_load_baked_metadata()`。
- `get_commit_id()` 策略：
  1. 若存在打包时生成的 `_build_metadata.py` 或环境注入，返回该固定 commit。
  2. 若运行在冻结态（`getattr(sys, "frozen", False)`），且无 metadata，返回 `"frozen-release"` 而非探测 CWD。
  3. 若源码态且存在 `.git`，探测本仓库根，获取 commit 与 dirty 标记。
  4. 兜底返回 `"dev"`。
- `capabilities` 命令返回工具标识、版本、构建提交、支持的所有命令清单、各命令的参数约定（`--format`, `--report-file`, `--project` 等）、读写性质（只读/写盘）与环境要求。

### 2.2 基线核对与确认绑定 (`doc_tool/application/baseline_check.py`)
- `check_baselines(project_root, declare_files=None)`:
  - 读取 `project.yml` 中的 `documentVersion`。
  - 读取 `_revision_record.md` 中的最后一条修订版本。
  - 扫描指定声明文件（如 README.md）中与该文档编号或名称对应的版本号。
  - 汇总各版本来源，计算是否存在版本冲突 (`conflict: bool`)。
  - 核验 `.state/baselines/` 下冻结基线文件元数据与文件哈希。
  - 检查 `.state/reviews/signoffs.json`：
    - 旧记录缺少 `content_hash` 时，标记 `status: "unverified"`, `reason: "缺少内容指纹绑定，无法核实对当前内容的确认"`。
    - 记录携带 `content_hash` 时，与当前文档内容哈希对比，若不一致则标记 `status: "stale"`, `reason: "内容已发生变更，原确认需复核"`。
    - 一致则标记 `status: "valid"`。

### 2.3 条目多项提取与影响分析修正 (`doc_tool/application/content/impact.py`)
- `extract_snapshots(documents)`:
  - 解析 Markdown 正文，跳过以 ` ``` ` 或 ` ~~~ ` 开始的代码块（防止代码块示例中的 DOC-ITEM 被识别）。
  - 按正文段落/小节定位所有 `DOC-ITEM` 标记。
  - 每个条目正文 `body` 取该标记所在的原子段落/子节内容（至下一个条目标记或同/高级别标题），不把整章正文统统归属给首个条目。
  - 提取正文引用的图片和资源路径。
- `diff_snapshots(before, after)`:
  - 对比基线条目快照集与当前条目快照集。
  - 准确识别：新增条目、修改正文/标题/资源条目、已删除条目（包括整文件删除导致的条目删除）。
  - 章节移动或编号变更（ItemKey 不变且正文/标题语义不变）不触发误报变更。

### 2.4 变更证据与 MR 交付报告 (`doc_tool/application/change_report.py`)
- 接收参数：
  - `git_evidence`: 由 `collect-git-evidence.ps1` 收集的多仓库 Git 元数据 JSON。
  - `junit_reports`: JUnit XML 测试报告文件。
  - `manual_tests`: 人工验收记录（JSON 或结构化输入）。
  - `project_root` / `baseline`: 相关文档基线与变更影响。
  - `change_id` / `openspec`: 关联的变更编号与提案路径。
- JUnit 解析器：
  - 提取 testsuites/testsuite/testcase。
  - 统计 tests, failures, errors, skipped。
  - `passed = (failures == 0 and errors == 0 and tests > 0)`.
  - `skipped` 独立统计，不记作 passed。
  - 检查套件声明数与用例实际数是否匹配。
- 交付报告生成：
  - 生成 `change-report.json`（schemaVersion: 1）。
  - 生成 `mr-attachment.md`：包含变更背景、文档基线核对、受影响条目清单、Git 提交与变更文件、测试执行证据（包含命令、耗时、通过率）、人工验收项、已知缺口与风险。
  - 若信息不全或测试未通过，MR 报告携带显著的待补提示，整体状态为 `incomplete` 或 `failed`。
