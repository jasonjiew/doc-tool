## Why

文档维护已具备编辑、构建与校验闭环，但**质量规则只有写死的三类基础检查**（`lint.py`），需求—设计—测试之间无追踪矩阵，版本基线、产物历史、评审审批、源 Word 更新后重导入均缺失——交付 QMS 文档时无法回答「覆盖了哪些需求、这版改了什么、谁审过、基线能否恢复」。本变更补齐从质量检查到交付审阅的完整追溯链路。

## What Changes

- **可配置质量规则**：在现有三类检查（重复标题/术语/TODO）之上，新增可开关、可调参的规则集——必备章节、字段完整性、编号唯一性、敏感信息、接口表结构、文档类型专属规则；规则配置落盘项目 `.state/quality_rules.json`，沿用 `TermStore` 的原子写模式。**对 `content-lint` 的行为扩展（非破坏性）**：检查结果数据结构新增 `severity` 与 `rule_id` 字段，`check_all` 从「硬编码规则」改为「读配置执行规则集」，既有读取方不受影响。
- **需求—设计—测试追踪矩阵**：解析需求/设计条目编号、接口与验收项，生成追踪矩阵、覆盖率统计与变更影响分析（复用 `index.py` 标题索引与 `references.py` 章节号解析）。
- **项目设置与版本基线**：图形化编辑文档编号/名称/版本、Word 刷新超时、模板与发布说明（写入 `project.yml`，经 `manifest.save` 备份）；版本递增、命名检查点、冻结/恢复基线、发布前检查清单。
- **版本历史与产物对比**：每次构建保存内容快照哈希、模板/资源哈希与输出状态到 `.state/history/`；Markdown/DOCX 差异查看与一键回滚（复用 `snapshot.py` / `changes.py` / `output_state.py`）。
- **PDF/HTML 导出及视觉对比**：一键生成评审版 PDF/HTML，相邻版本页面级视觉差异检查（本能力只做导出与视觉对比，版本历史存储由上一能力负责）。
- **评审与审批工作流**：章节级评审意见（已解决/未解决）、评审包导出、签字记录与发布审批门禁（`.state/reviews/`，沿用既有 JSON 原子写模式）。
- **更新源 Word 后重新导入**：检测 `sourceSha256` 变化，章节级差异预览、冲突预览、可撤销合并，不覆盖已有 Markdown 修改（复用 `importer.py` / `preflight.py` / `writer.py`）。

## Capabilities

### New Capabilities

- `configurable-quality-rules`: 可开关、可调参的质量规则集与规则配置存储；扩展 `content-lint` 的检查入口。
- `requirements-traceability-matrix`: 需求/设计/接口/验收项解析、追踪矩阵、覆盖率与变更影响分析。
- `project-settings-version-baseline`: 项目设置图形化编辑、版本递增、命名检查点、冻结/恢复基线与发布前检查清单。
- `version-history-artifact-diff`: 构建历史归档（内容/模板/资源哈希 + 输出状态）、Markdown/DOCX 差异查看与一键回滚。
- `pdf-html-export-visual-diff`: 评审版 PDF/HTML 导出与相邻版本页面级视觉差异检查。
- `review-approval-workflow`: 评审意见与状态、评审包、签字记录与发布审批门禁。
- `reimport-source-word`: 源 Word 更新检测、章节级差异预览、冲突合并与可撤销重导入。

### Modified Capabilities

- `content-lint`：检查入口从「写死三类规则」改为「读配置执行规则集」，结果项新增 `severity` 与 `rule_id`；现有三类规则作为默认开启的规则保留。

## Impact

- **代码**：`doc_tool/application/content/lint.py`（规则引擎重构 + 新规则实现）、`index.py`/`references.py`（编号/标题解析复用）、新增 `quality_rules.py`、`traceability.py`、`history.py`、`baselines.py`、`export/pdf_html.py`、`review/review_store.py`、`reimport.py`；`doc_tool/domain/manifest.py`（发布说明等字段）、`doc_tool/application/pipeline.py`（构建后写历史）、`doc_tool/ui/`（设置页、矩阵/历史/评审/重导入面板接线）。
- **存储**：项目 `.state/` 新增 `quality_rules.json`、`traceability.json`、`history/`、`checkpoints/`、`baselines/`、`reviews/`、`reimport_base.json`、`reimport_last.json`（含 `reimport_last_source.docx` 源副本）；`project.yml` 新增发布说明字段（向后兼容，缺省为空）。不改 `content_baseline.json`、`content_changes.json` 现有格式。
- **测试**：扩展 `scripts/tests/`（规则引擎单测、矩阵解析、历史归档/回滚、评审存储、重导入合并）；UI 沿用离屏测试模式。
- **兼容性**：对 `content-lint` 有行为扩展（非破坏性）；`project.yml` 仅新增可选字段；新目录对构建/校验不可见。
