## Why

当前 HEAD `bbfc71a` 已发布 V2.6.0 模板填充，但旧路线图的“V2.6 交付质量速赢”尚未实施，版本号和任务状态容易混淆。V2.6.x 在现有 schema 1 上补齐可靠恢复、日常创作和快速离线出稿，使团队在无需新版数据格式的前提下获得明显的使用收益。

## What Changes

- 按 `docs/product-flow-fallback-policy.md` 优先跑通：默认自动匹配样式、缺资源占位、坏配置回退、无 Word 保留产物，集中提示；严格交付由用户主动选择，保护只阻止破坏性写入或无结果可用的操作。
- 以 V2.6.x 完成基线收尾：核对既有导入、编辑、评审、模板填充、构建与分发功能，按代码/入口/测试/真实验收分别记录状态。
- 接入现有 `BuildHistoryStore.list_entries/get/diff/text_diff`，提供交付历史列表、产物打开、两版章节对照；本版不做整项目历史恢复。
- 在既有 `.md.bak`、草稿和软删除机制上补充多版本本地历史与回收站入口，恢复前处理未保存内容及目标文件冲突。
- 统一输出状态说明，明确诊断构建、模板填充未完成域刷新、正式项目发布的区别。
- 完成模板填充待验收项和打包/安装兼容核对；缺少实机证据时保留待验收状态。
- 新增本机命名填充预设和最近任务，保存底模/样式映射/清理/刷新选项，支持恢复上次输入顺序及显式重试；不等同团队规范包。
- 新增生成前只读预检：章节顺序/大纲、底模样式、图片与输入缺失、输出覆盖、已知降级提示；阶段/文件进度及结果可定位，执行前复核输入变化。
- 增强当前章节大纲与未保存内容统计，跳转定位、选区统计和计数规则透明。
- 扩展已有 SnippetStore：内置通用研发写作片段、检索、库导入/导出和冲突合并，复用占位符及撤销栈。
- 扩展已有图片面板：查看引用章节/重复文件候选，预览后批量修复同一缺失资源，沿用恢复/软删除机制。
- 接入已有 HTML 导出服务，提供单章/整项目只读离线预览包，包含目录及本地资源，不含意见表单/回流和正式 Word 发布能力。

## Capabilities

### New Capabilities

- `delivery-baseline`: 现有功能证据清单、交付状态、历史入口与 V2.6.x 验收契约。
- `content-recovery-history`: 本地多版本快照、回收站列表及安全恢复。
- `template-fill-recipes`: 用户级命名预设、最近任务和安全重试。
- `template-fill-preflight`: 生成前摘要/预检、输入复核与可定位任务状态。
- `authoring-navigation`: 当前章节大纲、未保存正文与选区统计。
- `authoring-snippet-library`: 通用研发片段、检索与声明式库交换。
- `asset-reference-assistance`: 图片引用来源、重复候选与批量修复事务。
- `readonly-html-preview`: 单章/整项目只读离线 HTML 预览包。

### Modified Capabilities

- `content-editor`: 将最近一次 `.md.bak` 回滚扩展为可选择的本地历史，保留兼容备份和未保存保护。

## Impact

- 涉及 `application/content/{writer,history,autosave}.py`、`ui/content/{editor_panel,workspace,changes_panel}.py`、输出结果入口、相关测试及发布文档。
- 扩展 `template_fill.py/template_fill_dialog.py`、`snippets.py/snippet_dialog.py`、`asset_manager.py/image_assets_panel.py`、既有 `export/pdf_html.py` 与命令面板；新增用户级预设/最近任务文件和预览输出，不修改 project schema。
- 复用现有服务，不重复开发模板填充/PDF/Git/评审基础功能；不更改项目 schemaVersion 1。
- 执行前置：无；后续为 `product-v27-reliable-delivery`。
- 本计划与后三版共同取代旧三阶段提案的排程，旧提案作为来源保留，迁移关系见 `docs/product-plan-v2.6-v2.9.md`。
- 2026-09-30 范围补充：六个扩展包安排在原实现基线之后、整版验收之前；已存在的基础功能仅补差额。V2.7 Word 表达/终审、V2.8 规范包/版本化评审、V2.9 多文档追溯保持其归属。
