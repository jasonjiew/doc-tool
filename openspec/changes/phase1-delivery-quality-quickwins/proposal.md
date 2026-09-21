## Why

`analysis/feature-audit.md`（基于 HEAD `12e8483` / v2.5.1）确认：正式出稿链路仍有 4 个"每次出稿都会撞上"的表达缺口（围栏代码块退化为正文、无发布终审、Word 刷新后域错误静默放行、修订记录零预填），以及 2 个隐性缺陷（打包排除 `QtWebEngine` 导致终端用户预览与开发者不一致；`scripts/cert-out/*.pfx` 与密码文件在工作区内）。这些问题全部可以在**不改架构**的前提下修复，且多数可复用已有代码（`review_docx._create_code_block_box`、`revision_record.build_revision_record`、`writer.ChangeJournal`）。

本变更是三阶段迭代计划的第一阶段（v2.6）：**小改动、高收益**，目标是让"正式出稿"不再出现刺眼缺陷，让 CI 有单入口门禁，并消除两处隐患。

## What Changes

- **代码块容器进正式 Word**：`scripts/build_docx.py:process_markdown` 增加围栏状态机，输出与评审稿一致的浅灰底/边框/Consolas 单格表格；渲染逻辑抽到公共模块 `doc_tool/kernel_shared/docx_blocks.py`，`review_docx` 同步改为复用。
- **发布终审阶段 `STAGE_AUDIT`**：`pipeline.py` 在 `validate_post` 之后新增阶段，扫描产物：域错误文本（`Error! Bookmark not defined.` / `错误!未定义书签`）、TODO/TBD 残留、表格累计宽度超版心、连续空段；任一 error 则不发布。
- **`doc-tool check` 统一门禁**：新 CLI 子命令 = lint + 结构校验（+ 可选 `--build`），退出码 0/1/2，`--output json|sarif`；`build` 子命令补 `--output json`。
- **构建前置 Lint 门禁**：manifest 新增 `gates.lint: error|warn|off`（默认 `warn`），`run_pipeline` 在 `STAGE_REVISION` 前执行。
- **Local History 与回收站**：`writer.py` 每次写前把旧版复制到 `.state/local_history/<rel>/<ts>.md`（保留 N=20）；删除章节移入 `.state/trash/<ts>/`；编辑器"回滚"改为版本列表；改动面板可恢复被删文件。
- **企业术语库**：`content/<type>/_terms.yml`（`wrong: → correct:`），Lint `term_case` 规则据此产出带 QuickFix 的问题。
- **修订记录预填**：改动面板"生成修订记录"弹窗预填改动小节 + 该小节区间 `git log --format=%s` 主题行；提供"追加为新行（版本自增）"按钮，仍需作者编辑确认。
- **预览引擎决策落地**：删除 `web_preview_browser.py` 及 `resources/web_preview/`，内置渲染为唯一路径；`test_frozen_smoke` 断言 `HAS_WEB_ENGINE` 不存在。
- **证书出仓**：`scripts/cert-out/` 移至仓库外（`%LOCALAPPDATA%\DocTool\signing\`），`sign_artifacts.ps1` 改读环境变量 `DOCTOOL_PFX_PATH`/`DOCTOOL_PFX_PASSWORD`，`.gitignore` 与 `scan_leaks.py` 增加规则。
- **接入已有服务（零新逻辑）**：`doc-tool trace` 输出追踪矩阵 md/json；输出卡片增加"构建历史"列表（`BuildHistoryStore`）。
- **归档 `openspec/changes/revision-review-export`**（已被 `review_docx.py`/`review_panel.py` 实际实现取代）。

## Capabilities

### New Capabilities

- `build-code-block`: 围栏代码块在正式构建与评审稿中使用同一容器渲染。
- `release-audit`: 发布前终审阶段的检查项、严重级别与阻断语义。
- `cli-check`: 统一质量门禁命令的组成、退出码与输出格式。
- `local-history`: 章节多版本本地历史与删除回收站。
- `term-glossary`: 项目级术语库与 Lint QuickFix。

### Modified Capabilities

- `content-lint`：`term_case` 规则改由术语库驱动；新增 `gates.lint` 前置门禁。
- `content-editor`：预览统一为内置渲染；"回滚上次保存"升级为版本列表。
- `content-changes-panel`：修订记录弹窗预填与一键追加。

## Impact

- **代码**：`scripts/build_docx.py`、`doc_tool/application/review/review_docx.py`、`doc_tool/application/pipeline.py`、`doc_tool/cli.py`、`cli_commands.py`、`domain/manifest.py`、`application/content/{writer,lint,spellcheck,revision_record}.py`、`ui/content/{editor_panel,changes_panel,revision_record_dialog}.py`、`packaging/{sign_artifacts.ps1,scan_leaks.py,doc_tool.spec}`。
- **数据**：`project.yml` 新增可选 `gates`（schemaVersion 保持 1，缺省兼容）；`.state/` 新增 `local_history/`、`trash/`。
- **兼容性**：无破坏性变更。既有项目无 `_terms.yml` 时 `term_case` 行为不变；`audit` 默认级别下"表格超宽"为 warning 不阻断。
- **非目标**：Mermaid 出稿、题注/交叉引用、横向节、Manifest v2、Git 冲突视图（属第二阶段）。

## Decisions

- **先抽公共渲染层再修代码块**：否则 `build_docx` 与 `review_docx` 会出现第三份代码块实现。
- **预览选"删除 WebEngine"而非"打包 WebEngine"**：打包增加 ~120MB 且 `QtWebEngineProcess.exe` 需额外签名/加固；企业加密环境下多一个子进程即多一个故障点。内置 SVG 渲染已覆盖 flowchart/sequence，第二阶段补图种。
- **修订记录仍由作者确认**：延续 `revision_record.py` docstring 的设计取舍——机器只预填事实（改了哪些小节、提交主题），不替作者决定摘要。
- **术语库放在 content 目录而非 `.state/`**：需随 Git 共享、进入 PR 评审。
