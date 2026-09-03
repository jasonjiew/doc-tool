# 修订评审（改动评审导出与闭环）

## Why

文档改动后要开会评审，会议室不可能装本工具，评审对象必须是**离线的 Word 文档**。当前改动只能在本工具内查看（改动面板「基线 vs 当前」diff），评审意见也只能回到工具里手工录入（`ReviewStore` + 发布前检查的审批门禁），中间两个环节缺失：

1. **导出**：无法把「本次修订的改动章节」一键导出成会议可用的评审稿 Word；
2. **闭环**：评审会上产生的意见（公司评审单格式）无法回流到工具，无法证明「意见已全部处理、更改已确认」，发布门禁因此形同虚设。

本变更补齐「导出评审稿 → 会议评审 → 意见回流 → 处理确认 → 发布门禁」的完整闭环。

## What Changes

- **导出评审稿（Word，只含改动章节）**：新增「导出评审稿」，以会话基线（`ContentSnapshot.diff` + 重命名归并）为改动口径，与改动面板完全一致；逐条目输出「修改前/修改后上下对照」（新增章节出全文、删除章节出原文并标注），复用 `markdown_to_word_html` 排版渲染（图片自动内嵌），经本机 Word 转 DOCX，无 Word 时降级导出 HTML。文档含：信息块（文档编号/名称、本次版本、基线时间、改动统计）、本次修订记录行、改动总表（评审条目号 ↔ 章节定位）、逐条目正文对照、**公司评审单模板格式**的空白评审意见表（附录）。
- **评审条目快照**：导出时生成 `review_items.json`（条目号 ↔ rel_path ↔ 导出时内容 sha1），随评审包落在 `output/review/` 同一目录；它是「会议里的条目」与「工具里的章节」缝合的锚点，并用于检测「导出后内容又有改动」。
- **导入评审意见**：新增「导入评审意见」，离线解析任意含公司评审单表头（序号/提出人/评审问题/责任人/评审记录/更改结果与证据/遗留问题/计划完成时间/更改确认）的 DOCX（OOXML 直读，不依赖 Word），逐行转为 `ReviewStore` 意见；按「评审稿编号 + 序号」幂等去重，重复导入不产生重复意见；条目号命中则自动绑定章节，未绑定的在意见面板手工关联。
- **评审意见字段对齐公司评审单**：`ReviewComment` 非破坏性扩展（均有默认值）：责任人、计划完成时间、更改结果与证据、遗留问题、更改确认、评审记录、评审稿引用（评审稿编号+条目号+序号）。意见管理面板从简陋的多行输入框升级为正式对话框：列表/筛选（未解决/已确认/全部）、跳转章节、编辑公司单各列字段、逐条解决与确认。
- **发布门禁对接（既有）**：发布前检查继续以「无未解决评审意见」为阻断项；已解决但「更改确认」为空的条目在检查清单中提示（不阻断，可按项目要求收紧，见 design）。

## Capabilities

### New Capabilities

- `revision-review-export`: 改动章节评审稿（Word/HTML）导出、评审条目快照与评审包目录整合。
- `review-feedback-import`: 公司评审单格式意见表的离线解析、幂等回流与章节绑定。

### Modified Capabilities

- `review-approval-workflow`：`ReviewComment` 扩展公司评审单字段（非破坏性，向后兼容）；意见管理对话框替换现有简陋录入入口；发布前检查清单增加「已解决未确认」提示项。

## Impact

- **代码**：新增 `doc_tool/application/review/review_export.py`（改动收集 + 评审稿渲染，纯逻辑可单测）、`doc_tool/application/review/review_import.py`（OOXML 表格解析 + 幂等回流，纯逻辑可单测）；修改 `doc_tool/application/review/review_store.py`（`ReviewComment` 扩展字段、更新入口）、`doc_tool/ui/content/changes_panel.py`（新增「导出评审稿」「导入评审意见」按钮）、`doc_tool/ui/main_window.py`（意见对话框接线）；复用 `markdown_word.py`、`convert.py`/`word_convert.py`、`snapshot.py`、`changes.py`、`revision_record.py`、`domain/ooxml.py`。
- **存储**：`output/review/` 评审包目录新增评审稿 DOCX（或降级 HTML）与 `review_items.json`；`.state/reviews/comments.json` 结构不变，条目新增可选键（旧文件缺键按默认值读取）。不改动 `content_baseline.json`、`content_changes.json` 现有格式。
- **测试**：`scripts/tests/` 新增评审稿渲染（改动收集、条目号分配、修订行带出）、意见表解析（表头定位、合并单元格容错、幂等去重、条目绑定）、字段扩展向后兼容等单测；UI 沿用离屏测试模式。
- **兼容性**：`ReviewComment` 仅追加带默认值的字段，旧数据直接可读；评审稿导出在无 Word 环境降级 HTML，不阻塞评审流程。
