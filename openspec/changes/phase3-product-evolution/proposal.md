## Why

前两阶段完成后，Doc Tool 的"导入 → 编辑 → 出稿"主链路在单机 Windows + 本机 Word 的前提下已足够完整。第三阶段（v3.0+）解决的是**把工具放进团队与流水线**时暴露的边界问题：Linux CI 永远出不了正式稿；多份文档无法共享章节；章节历史/责任人只能去 Git 客户端看；评审意见与提交没有关联；修订摘要与术语审查完全靠人。

本阶段明确**克制**：AI 只以"可插拔 provider + 人工确认"的形式进入两个确定收益点；不做 Web 实时协同、不自研排版引擎、不扩 PDF 工具箱、不做所见即所得复杂表编辑器。

## What Changes

- **无 Word 预发布 + 远程 promote**：`OutputState` 新增 `staged` 态。`doc-tool build --stage` 在无 Word 环境产出 `<name>.staged.docx` + `.state.json`（含源 hash、audit 报告）；任一有 Word 的机器执行 `doc-tool refresh --promote <staged>` 完成域刷新、后校验、终审并原子发布为正式稿。GUI 在打开项目时检测到 staged 产物提示"一键正式化"。
- **Include / 共享章节**：`<!-- INCLUDE: ../common/terms.md -->`（限项目根或 manifest `includeRoots` 白名单内），`STAGE_PREPARE` 展开；预览同步；Lint 检查循环与越界；被 include 的文件在树中以链接图标显示。
- **章节 Git 历史视图**：章节树右键"历史"→ 只读列表（`git log --follow`），双击显示该提交与当前的 side-by-side diff；编辑器状态栏显示最近修改人/时间（`git log -1`）。
- **提交前门禁与意见联动**：提交对话框显示本次改动章节的 Lint 摘要（`gates.commit_lint: error|warn|off`）；提交消息含 `Fixes R-012` 时评审面板自动把意见置为"已确认（待复核）"并记录提交号。
- **评审 HTML 包**：评审面板"导出 HTML 评审包"（`export/pdf_html.py`）——零 Word 依赖，含改动前后对照与意见回填表单（提交后生成可导入的 JSON）。
- **AI 助手（可选、可关）**：`application/ai/provider.py` 定义 `AIProvider` 协议（OpenAI 兼容 HTTP 端点 / 本地命令），manifest `ai.endpoint` 缺省为空即完全禁用。仅两个用途：
  1. 修订记录摘要：输入第一阶段预填（改动小节 + 提交主题 + 章节 diff 片段），输出 1~3 条建议摘要到弹窗，作者选用/编辑后写入。
  2. 术语一致性审查：输入术语库 + 章节文本，输出疑似不一致清单进问题中心（severity=info），不自动修改。
  所有请求只发送必要片段、日志脱敏、可配置代理；企业无端点时功能不可见。
- **项目锁租约**：`project.lock` 增加 `heartbeat`/`expiresAt`，网络盘多机场景可见"被 X@host 占用于 hh:mm"，过期可接管。
- **命令注册表**：面板动作向 `CommandRegistry` 注册，命令面板自动收录（"导出评审稿""设为基线""历史"等），支持最近使用排序。

## Capabilities

### New Capabilities

- `build-staged-promote`: 预发布制品格式、状态机 `staged` 与 promote 契约。
- `content-include`: Include 标记、白名单、循环检测与预览展开。
- `chapter-history`: 章节级 Git 历史只读视图。
- `commit-gate-and-review-link`: 提交前 Lint 摘要与 `Fixes R-xxx` 联动。
- `review-html-package`: HTML 评审包导出与意见回填。
- `ai-assist`: provider 协议、启用条件、两个用途的输入输出边界与隐私约束。
- `project-lock-lease`: 心跳与租约语义。
- `command-registry`: 面板动作注册与命令面板收录。

### Modified Capabilities

- `release-audit`：promote 路径复用。
- `content-changes-panel`：提交对话框门禁摘要。
- `content-review-panel`：HTML 包导出、意见自动确认。

## Impact

- **代码**：`domain/output_state.py`、`application/pipeline.py`、`kernel/refresh_fields.py`、`cli.py`、`application/prepare.py`、`application/content/{vcs_changes,revision_record,lint}.py`、`application/review/*`、新增 `application/ai/`、`domain/project_lock.py`、`ui/command_palette.py` 及各面板。
- **数据**：`.state.json` 新增 `staged` 态字段；manifest 新增 `includeRoots`、`ai`、`gates.commit_lint`；`project.lock` 新字段（旧格式兼容）。
- **兼容性**：全部为可选能力，缺省行为与 v2.8 相同。
- **明确不做**：Web 实时协同；自研排版/PDF 引擎；PDF 工具箱新增项；PlantUML/Draw.io/公式；审批流/电子签章/归档系统（仅保留 `approval_gate` + 导出）；AI 问答、AI 自动改写、AI 根据代码/Git Diff 自动更新文档。

## Decisions

- **promote 而非 LibreOffice 替代 Word**：LibreOffice 的分页/域行为与 Word 不一致，受控交付物不能接受差异；promote 保留"最终由 Word 刷新"的事实。
- **AI 是 provider 不是功能**：核心工作流不依赖它；无端点即隐藏；输出永远进"建议"位置，由人写入。
- **Include 用注释标记**：延续 `<!-- TABLE/P/TBL/SECTION -->` 体系，GitHub 渲染无害。
- **章节历史只读**：不在工具内做 reset/revert 历史提交，避免与 Git 客户端职责重叠。
