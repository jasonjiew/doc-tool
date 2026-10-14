## Why

同事使用完整 DocTool 免安装便携包，解压后通过 GUI 维护文档；AI 工具和脚本通过环境变量或显式路径调用包内 `doc-tool-cli.exe`。日常使用不要求下载 doc-tool 源码、安装系统 Python、执行 pip 或在源码目录启动。同时打通：定位工具 → 核对文档基线 → 查询需求/设计条目 → 计算变更影响 → 汇总真实验证证据 → 形成 GitLab MR 附件的全链路闭环。

## What Changes

1. **免安装 CLI 契约与构建来源固定**：
   - 打包时固定构建版本、提交哈希与 dirty 标识，运行时优先使用打包元数据，禁止借用调用者工作区的 Git HEAD。
   - 新增 `capabilities` 命令，机器可读输出支持命令、参数规范、报告版本、读写语义和环境需求。
   - 新增 `item-list`、`item-show`、`review-status` 只读薄入口，支持分页、内容摘要与状态说明。
   - 统一机器输出：`--format json` 保证 stdout 输出单一合法 JSON，过程日志与诊断输出到 stderr；支持 `--report-file` 明确写入目标文件。
2. **基线核对与确认对象绑定**：
   - 新增 `baseline-check` 命令，对比 `project.yml`、`_revision_record.md` 与声明文件（如 README.md），显式报告版本冲突（如 3.10/3.8、2.6/2.5），不擅自选择版本。
   - 核对冻结基线摘要与受控文件完整性。
   - 扩展 Signoff 确认对象绑定（项目、基线、内容摘要），兼容旧记录，内容变动后旧确认显式标记待复核与失效原因。
3. **存量条目与多条目影响分析**：
   - 暴露 `trace-plan` 迁移预览与歧义，同一计划多次读取保持稳定 ID，预览零正文写入。
   - 共享层条目快照提取支持同一章节多个 `DOC-ITEM`，绑定原子正文块与关联资源，排除代码块示例，避免整章正文绑定首个 ID。
   - 独立基线与当前集合多维度比对，覆盖新增、删除、移动、整文件删除和资源变动。
4. **变更、测试与 MR 证据整理**：
   - 新增 `change-report` 命令，接收多仓库 Git 元数据 JSON（复用 `collect-git-evidence.ps1` 输出）与显式引用。
   - 接入实际 JUnit XML（区分 pass/fail/skipped）与人工验收记录，保留原始摘要与环境信息。
   - 输出统一机器 JSON 与 GitLab MR 描述/附件 Markdown，未标记或证据不足时显式展示缺口，不虚报通过。
5. **便携包构建与交付**：
   - 使用既有 `build_exe.ps1`、`doc_tool.spec`、`stage_dist.ps1` 和 `make_portable.ps1` 装配含 GUI、CLI、`_internal` 及原地启动脚本的完整 ZIP 与 `.sha256`。

## Capabilities

### New Capabilities
- `portable-cli-devflow`: 免安装环境下的完整 CLI 诊断、条目查询与能力自省。
- `baseline-and-confirmation-gate`: 项目清单、修订记录、声明文件版本冲突核对与带内容指纹的确认失效判定。
- `evidence-and-mr-report`: 多仓库 Git 差异、JUnit 与人工验收证据汇总与 GitLab MR 交付报告生成。

### Modified Capabilities
- `trace-and-impact-v29`: 增强条目快照提取，支持单章多条目与基线/当前集合准确差异比对。

## Impact

- 代码改动：`doc_tool/domain/version.py`、`doc_tool/cli.py`、`doc_tool/application/content/impact.py`、`doc_tool/application/content/baselines.py`、`doc_tool/application/review/review_store.py`；新增 `doc_tool/application/baseline_check.py`、`doc_tool/application/item_query.py`、`doc_tool/application/change_report.py`。
- 打包调整：`packaging/doc_tool.spec`、`packaging/stage_dist.ps1`、`packaging/make_portable.ps1` 注入固定构建元数据。
- 外部依赖：无新增外部 Python 库，复用内置标准库与现有依赖。
- 业务仓库保护：只读比对与查询，不修改业务仓库文件。
