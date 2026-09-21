> 第一阶段（v2.6）实施清单。顺序即依赖序；每节先写测试后实现。
> 来源：`analysis/feature-audit.md` TOP 1/3/6/9/13/15/16、TOP 5 决策、TOP 18 部分。

## 0. 前置清理

- [ ] 0.1 归档 `openspec/changes/revision-review-export`（写明"已由 review_docx/review_panel 实现取代"）
- [ ] 0.2 `scripts/cert-out/` 移出仓库，`git rm --cached`，`.gitignore` 加 `scripts/cert-out/`、`*.pfx`、`pfx-password*`
- [ ] 0.3 `packaging/sign_artifacts.ps1`、`scripts/new-code-signing-cert.ps1` 改读 `DOCTOOL_PFX_PATH` / `DOCTOOL_PFX_PASSWORD`
- [ ] 0.4 `packaging/scan_leaks.py` 增加 pfx/密码文件模式；`test_public_export.py` 增加断言
- [ ] 0.5 本地执行一次签名验证 + CI dry-run

## 1. 公共渲染层与代码块（TOP 1）

- [ ] 1.1 新建 `doc_tool/kernel_shared/__init__.py`、`docx_blocks.py`；迁入 `create_code_block_box`、`append_text_with_breaks`，保留原函数为薄别名
- [ ] 1.2 `review_docx.py` 改为 import `docx_blocks`；`test_review_docx.py` 全绿
- [ ] 1.3 `build_docx.process_markdown` 增加围栏状态机（含 mermaid 语言暂按代码块输出）
- [ ] 1.4 `validate_docx.expected_markdown_events` 识别围栏块；`docx_common._validate_markdown` 检查未闭合围栏并给出行号
- [ ] 1.5 `test_project_build.py` 新增：单代码块 / 含 Tab / 未闭合围栏报错 / 评审稿与正式稿容器 XML 等价

## 2. 发布终审 `STAGE_AUDIT`（TOP 3）

- [ ] 2.1 新建 `doc_tool/application/audit.py`：`AuditItem`/`AuditReport`/`audit_docx()` 与四条规则
- [ ] 2.2 `pipeline.py` 插入 `STAGE_AUDIT`；`PIPELINE_STAGE_LABELS` 加"终审"；error 阻断发布、保留临时产物
- [ ] 2.3 `manifest.py` 新增 `gates: {"lint": "warn", "audit": "error"}` 并兼容缺省
- [ ] 2.4 结果视图"技术详情"展示 audit 报告；报告落 `logs/audit-<ts>.json`
- [ ] 2.5 `test_word_release.py` / 新 `test_audit.py`：域错误文本阻断、TODO 阻断、表格超宽 warning、快速构建下降级

## 3. CLI 统一门禁（TOP 9）

- [ ] 3.1 `cli.py` 新增 `check` 子命令与参数；`cli_commands.check_command()` 组合 lint/validate/(build+audit)
- [ ] 3.2 退出码 0/1/2 与 `--fail-on`；SARIF `ruleId` 前缀
- [ ] 3.3 `build --output json` 序列化 `PipelineResult`
- [ ] 3.4 `run_pipeline` 前置 Lint 门禁（按 `gates.lint`）；GUI 正式出稿确认框显示 Lint 摘要
- [ ] 3.5 `test_cli_machine.py` 新增 check 三种退出码、json/sarif 结构；`test_quality_gates.py` 新增前置门禁三模式
- [ ] 3.6 `docs/使用说明.md` 与 README 补 `check` 用法

## 4. Local History 与回收站（TOP 13）

- [ ] 4.1 `writer.py`：写前快照到 `.state/local_history/`，20 份淘汰，>2MB 跳过
- [ ] 4.2 `workspace._on_delete_file` 改为移入 `.state/trash/`；`ChangeJournal` 新增 `delete` 类型与恢复
- [ ] 4.3 `editor_panel.rollback_last` → 版本列表对话框 `ui/content/local_history_dialog.py`
- [ ] 4.4 改动面板：被删文件显示"可恢复"并提供恢复动作
- [ ] 4.5 `test_safety_recovery.py` 新增：多版本回滚、淘汰策略、删除恢复、跨卷移动回退

## 5. 术语库（TOP 15）

- [ ] 5.1 `spellcheck.py` 新增 `TermGlossary`（加载/校验 `_terms.yml`，格式错误进问题中心）
- [ ] 5.2 `lint.term_case` 接入术语库，产出带 `fix` 的 `LintIssue`
- [ ] 5.3 `lint_panel` 确认 QuickFix 通道可对术语问题一键替换（含全部替换）
- [ ] 5.4 `test_authoring_services.py` 新增术语命中/多错误写法/无术语库回退

## 6. 修订记录预填（TOP 16）

- [ ] 6.1 `revision_record.build_revision_record` 增加 `git_log` 注入参数与主题行聚合
- [ ] 6.2 `RevisionRecordDialog` 改为表单 + "追加到 `_revision_record.md`"（原子写、触发索引刷新）
- [ ] 6.3 版本号自增建议：解析末行 `V?(\d+)\.(\d+)` 次版本 +1，可手改
- [ ] 6.4 `test_revision_record.py` 新增：预填内容、追加行格式、版本建议、只读项目禁用

## 7. 预览引擎统一（TOP 5）

- [ ] 7.1 删除 `ui/content/web_preview_browser.py`、`resources/web_preview/`；清理 `editor_panel.py` 分支与 spec datas
- [ ] 7.2 `_PreviewBrowser` 回归：代码高亮、Mermaid 内置渲染、锚点双向定位
- [ ] 7.3 `test_frozen_smoke.py` 断言不存在 WebEngine 导入；`test_gui_services.py` 预览用例改为单路径
- [ ] 7.4 `docs/release/02-release-decisions.md` 记录该决策

## 8. 接入已有服务（TOP 18 部分）

- [ ] 8.1 `doc-tool trace --project --output md|json` → `TraceabilityService`
- [ ] 8.2 主窗口输出卡片"历史"列表（`BuildHistoryStore.entries()`），双击打开
- [ ] 8.3 `test_cli_machine.py` / `test_gui_services.py` 各补一例

## 9. 回归与发布

- [ ] 9.1 `scripts/tests/run_tests.py --coverage` 全绿；CI 上传新 `coverage.json`
- [ ] 9.2 用 `examples/galaxy-user-manual` 与一份真实设计文档跑：导入 → 编辑（含代码块/术语）→ check → 快速构建 → 正式出稿 → audit 报告
- [ ] 9.3 人工验收：本文件 design.md "验收标准" 全部逐条勾选
- [ ] 9.4 版本升至 2.6.0，`release-notes.md`、README 功能矩阵同步
- [ ] 9.5 `openspec/specs/` 同步新增/修改的 capability；本 change 归档
