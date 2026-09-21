## 目标

在现有六阶段管线与工作台架构不变的前提下，修复正式出稿最刺眼的表达缺陷、补齐发布终审与 CI 单入口、消除两处隐患，并把已实现但无入口的服务暴露出来。

## 决策

### D1 公共渲染层 `docx_blocks`

- 新建 `doc_tool/kernel_shared/docx_blocks.py`（纯 lxml，无 Qt），迁入：
  - `create_code_block_box(code_lines, *, max_width, style)`（来自 `review_docx.py:1059-1103`）；
  - `append_text_with_breaks(run, text)`（来自 `build_docx.append_text`）。
- `scripts/build_docx.py` 与 `review_docx.py` 均 import 该模块；`adapters/kernel.py:ensure_kernel_importable` 无需变更（模块在包内）。
- 反例（否决）：让 `build_docx` 直接 import `review_docx` —— 会把评审模块的 `ReviewComment` 等依赖拖进内核。

### D2 围栏状态机

- `process_markdown` 主循环最前增加：遇到 ```` ^```(\w*) ```` 进入 `in_fence`，收集到闭合围栏；语言为 `mermaid` 时本阶段**保持原样输出为代码块**（第二阶段替换为图片）。
- 代码块内不做行内解析、不做 `<br>` 替换；Tab 保留。
- 校验：`validate_docx.expected_markdown_events` 需把围栏块识别为单个 `T`(table) 事件，避免与产物比对报错。

### D3 `STAGE_AUDIT`

- `PIPELINE_STAGE_ORDER` 在 `STAGE_VALIDATE_POST` 后插入 `STAGE_AUDIT = "audit"`；`stage_percent_table` 自动重算。
- 新模块 `doc_tool/application/audit.py:audit_docx(path, config) -> AuditReport(items: [AuditItem(rule, severity, location, message)])`，规则：
  | rule | 默认级别 | 检测 |
  |---|---|---|
  | `field_error_text` | error | 任一 `w:t` 含 `Error! Bookmark not defined.`/`错误!未定义书签`/`Error! Reference source not found.`/`错误!未找到引用源` |
  | `todo_residual` | error | 正文 `w:t` 匹配 `\b(TODO|TBD|FIXME)\b|\[待补充\]` |
  | `table_overflow` | warning | `tblGrid/gridCol` 之和 > 版心宽度（`usable_page_width_emu`）×1.02 |
  | `empty_run` | warning | 连续 ≥3 个无文本 `w:p` |
- 任一 error → 阶段 `failed`，不进入 `STAGE_PUBLISH`，临时产物保留供排查（沿用 `_cleanup_temp` 例外分支）；报告写 `logs/audit-<ts>.json` 并在结果视图"技术详情"中展示。
- `skip_word_refresh`（快速构建）下 `field_error_text` 降为 info（域尚未刷新）。

### D4 `doc-tool check`

- `cli.py` 新增子命令：`check --project <dir>... [--build] [--output human|json|sarif] [--fail-on error|warning]`。
- 组成：`lint_command` → `validate_command`（结构/资源）→ 可选 `run_pipeline(skip_word_refresh=True)` + `audit`。
- 退出码：0 无问题；1 仅 warning；2 存在 error 或执行失败。SARIF 复用 `cli_serializers` 现有 lint 序列化，`ruleId` 前缀区分 `lint.`/`validate.`/`audit.`。
- `build` 子命令新增 `--output json`，序列化 `PipelineResult.events`。

### D5 前置 Lint 门禁

- `ProjectManifest` 新增 `gates: Dict[str, str] = {"lint": "warn"}`；`from_dict` 缺省兼容。
- `run_pipeline` 在取锁后、`STAGE_REVISION` 前执行 `ContentLinter.run()`：`error` 模式有 error 即失败；`warn` 模式写 warning 事件；`off` 跳过。GUI 的"正式出稿"确认框显示 Lint 摘要。

### D6 Local History / 回收站

- `writer.py:atomic_write` 前：若目标存在，复制到 `.state/local_history/<rel_path>/<UTC ts>.md`；目录内超过 20 份按时间淘汰。
- 删除：`_on_delete_file` 改为 `shutil.move` 到 `.state/trash/<UTC ts>/<rel_path>`；`ChangeJournal` 记 `delete` 条目含 trash 路径，改动面板"恢复"支持该类型。
- 编辑器"回滚上次保存"→ 弹出版本列表（时间、大小、前 80 字预览），选择后加载为未保存内容（不直接覆盖）。
- `.state/` 已被 `_PROJECT_INTERNAL_DIRS` 排除在 VCS 之外，无需改动。

### D7 术语库

- 文件：`content/<type>/_terms.yml`：
  ```yaml
  terms:
    - wrong: ["呼吸器", "呼吸机器"]
      correct: "呼吸机"
      note: "产品标准名"
  ```
- `spellcheck.UserDictionary` 旁新增 `TermGlossary.load(content_root)`；`lint.term_case` 命中 `wrong` 时产出 `LintIssue(fix=Replacement)`，`lint_panel` 现有 QuickFix 通道直接可用。
- 与 `_revision_record.md` 同为下划线前缀文件，`scan_entries` 已忽略。

### D8 修订记录预填

- `revision_record.build_revision_record(items, *, git_log: Optional[Callable])`：对每个改动小节调用 `git log --since=<baseline mtime> --format=%s -- <path>` 取主题行（去重、最多 5 条）。
- `RevisionRecordDialog` 增加可编辑表单：版本（默认末行 +0.1）、摘要（预填文本）、日期（今天）、修改人（`git config user.name`）；"追加到 `_revision_record.md`" 通过 `writer` 原子写入并触发 `_after_write`。

### D9 预览引擎

- 删除 `ui/content/web_preview_browser.py`、`resources/web_preview/`；`editor_panel.py` 移除 `HAS_WEB_ENGINE` 分支；`doc_tool.spec` 的 WebEngine excludes 保留作防御。
- `_PreviewBrowser`（QTextBrowser）路径补齐：代码块高亮已由 `preview.highlight_code_html` 覆盖；Mermaid 由 `mermaid.render` 内置 SVG 渲染。

### D10 证书出仓

- 移动 `scripts/cert-out/` 到仓库外并 `git rm --cached`；历史中已存在的 `.pfx` 需运维决定是否 `git filter-repo`（本变更只阻断继续泄露，不改写历史）。
- `sign_artifacts.ps1`/`new-code-signing-cert.ps1` 读 `DOCTOOL_PFX_PATH`、`DOCTOOL_PFX_PASSWORD`；`scan_leaks.py` 增加 `*.pfx`、`pfx-password*` 模式；`test_public_export.py` 增加断言。

### D11 接入已有服务

- `doc-tool trace --project <dir> [--output md|json]` → `TraceabilityService.build_matrix()`；
- 主窗口"输出"卡片增加"历史"按钮：列出 `BuildHistoryStore.entries()`（版本/时间/路径/大小），双击打开文件。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 围栏块改变产物结构导致 `validate_docx` 事件比对失败 | D2 同步更新事件生成；`test_project_build` 增加含代码块用例 |
| `STAGE_AUDIT` 误报阻断正式出稿 | 首版只有两条 error 规则且模式极窄；`gates.audit: warn` 可临时降级 |
| 删除 WebEngine 后预览体验回退 | 冻结包本来就没有 WebEngine，终端用户无感；开发者预览与用户一致反而利于发现问题 |
| Local History 占用磁盘 | 20 份上限 + 单文件 >2MB 不保留历史 |
| 证书迁移影响 CI 签名 | CI secrets 已通过环境变量注入（`build-release.yml`），本地脚本同步改造后验证一次签名 |

## 验收标准

- 含 ```` ```python ```` 的示例项目正式出稿后，Word 中代码块为带底纹边框的等宽表格；评审稿与正式稿视觉一致。
- 人为在模板中放置失效 `REF` 域后正式出稿，`STAGE_AUDIT` 失败、`output/` 未更新、日志含定位。
- `doc-tool check --project examples/galaxy-user-manual --output sarif` 在干净项目返回 0，注入 TODO 后返回 2。
- 连续保存同一章节 3 次后，回滚列表显示 3 个版本；删除章节后改动面板可恢复。
- `_terms.yml` 定义错误写法后，Lint 面板出现问题且 QuickFix 一键替换。
- 修订记录弹窗显示改动小节与提交主题，追加后 `_revision_record.md` 新增一行且正式出稿版本号随之变化。
- `git ls-files | grep -i pfx` 为空；`python packaging/scan_leaks.py` 通过。
- 全量 `scripts/tests/run_tests.py --coverage` 通过，CI 产出新的 `coverage.json`。
