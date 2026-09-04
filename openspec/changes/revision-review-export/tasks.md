> 本期只出设计，不实现。以下任务为批准后的实施清单（默认未勾选）。

## 1. 应用层：评审意见存储扩展（纯逻辑，先测）

- [ ] 1.1 `review_store.py` 的 `ReviewComment` 追加带默认值字段：`review_ref`/`item_id`/`row_serial`/`assignee`/`planned_date`/`confirm_status`/`resolution_note`/`evidence`/`open_issue`；旧 `comments.json` 缺键按默认值读取
- [ ] 1.2 新增白名单更新入口 `update_fields(comment_id, **fields)`（仅业务字段），状态推进沿用 `set_resolved`
- [ ] 1.3 `mark_association_changes` 对新增字段无影响回归

## 2. 应用层：会议评审稿导出（纯逻辑，先测）

- [ ] 2.1 `doc_tool/application/review/review_export.py` 收集改动：`ContentSnapshot.diff` + `overlay_rename_status` + `build_change_items`，过滤 `*.md`、排除 `_revision_record.md`，按章节号排序并分配 `R01…`
- [ ] 2.2 生成 `packageId = RS-<yyyyMMdd-HHmmss>` 与 `review_items.json`（条目号/rel_path/status/标签/baselineSha1/currentSha1）
- [ ] 2.3 拼评审稿 Markdown（信息块/本次修订记录行/改动总表/逐条目前后对照正文/9 列空白纪要表附录）；基线时间取 `content_baseline.json` mtime；修订记录末行复用 `revision_record` 表格解析（必要时公开私有函数）
- [ ] 2.4 `markdown_to_word_html` → `convert.py` md→docx 经 Word 转 DOCX；捕获 Word 不可用降级交付 HTML（文件名标注「HTML 版」）
- [ ] 2.5 `ReviewPackageBuilder.build` 增加可选参数承接评审稿与 `review_items.json`，`manifest.json` 记录评审稿文件名与条目数；评审稿/条目快照/json 包落同一 `output/review/review-package-<版本>-<时间戳>/` 目录

## 3. 应用层：评审意见导入（纯逻辑，先测）

- [ ] 3.1 `doc_tool/application/review/review_import.py` 用 `read_docx_package` + lxml 直读 `document.xml`，表头驱动定位 9 列纪要表（「评审问题」「提出人」表头，两行表头/合并单元格展开容错；「责任人」跨 3 列映射）
- [ ] 3.2 一行一条意见（单元格内换行并入），幂等键优先 `(review_ref, row_serial)`、外来表单回退 `(rel_path or "", author, sha1(text))`；重复跳过，反馈「新增 N / 跳过 M」
- [ ] 3.3 绑定 rel_path：`review_items.json` 按 row_serial/item_id → rel_path；否则意见文本条目号前缀或 `section_labels` 反查；未命中 `rel_path=""`
- [ ] 3.4 漂移检测：`review_items.json` 可用时按条目 currentSha1 与当前文件比较，不一致仅提示

## 4. 应用层：正式评审纪要生成（纯逻辑，先测）

- [ ] 4.1 `doc_tool/application/review/review_minutes.py` 渲染 9 列标准表（两行表头：「序号/提出人/评审问题/责任人/计划完成时间/更改确认/评审记录/更改结果与证据/遗留问题」，「责任人」跨 3 列拆「责任人/计划完成时间/更改确认」）；表结构以用户真实样本校准
- [ ] 4.2 空表模式（N 空行）+ 闭环填充模式（全部/未解决/已解决/按责任人/按条目筛选；序号重排 1..n，`row_serial` 保留溯源）
- [ ] 4.3 信息块（文档编号/名称、本次版本、纪要编号 `JL-<文档编号>-<版本>-<时间>`、发起人/时间、统计）；`markdown_to_word_html` → Word 转 DOCX，无 Word 降级 HTML
- [ ] 4.4 只生成新文件（导出目录内命名），绝不覆盖既有纪要文件

## 5. UI 接线

- [ ] 5.1 `changes_panel.py` 标题行新增「导出评审稿」（确认对话框：改动统计预览 + 基线时间 + 目标目录；后台线程执行，完成后打开目录）、「生成评审纪要」与「导入评审意见」（后两者仅 writable）
- [ ] 5.2 新增 `ui/content/review_dialog.py` 意见管理对话框：列表（状态/确认/责任人筛选）、双击跳章节（复用 `open_file`）、9 列字段编辑、解决/确认、绑定章节、导入与纪要生成入口；`main_window._on_review_panel` 替换为打开该对话框

## 6. 发布门禁对接

- [ ] 6.1 `pre_publish_checks` 新增 `confirm` 检查「无已解决未确认意见」，failed 走既有「跳过检查」覆盖并在发布历史留 `history_note`；`main_window` 发布前检查传入 `unconfirmed` 计数

## 7. 自动化测试

- [ ] 7.1 `test_review_export.py`：改动收集与条目号、`_revision_record.md` 排除、修订记录末行带出、`review_items.json` 内容、Word 不可用降级 HTML
- [ ] 7.2 `test_review_import.py`：表头定位与合并单元格容错、幂等去重、条目绑定/反查/手工兜底、漂移提示
- [ ] 7.3 `test_review_minutes.py`：9 列表渲染（两行表头/跨列）、空表与填充两模式、筛选与序号重排、HTML 降级
- [ ] 7.4 `test_review_store_backcompat.py`：新字段默认值读旧 `comments.json`、`update_fields` 白名单
- [ ] 7.5 全量默认套件回归通过

## 8. 文档

- [ ] 8.1 `docs/使用说明.md` 新增「修订评审」章节：导出评审稿 → 会议评审 → 导入意见 → 处理确认 → 生成评审纪要 → 发布门禁；无 Word 降级说明

## 9. 二期（本变更范围外，仅记录）

- 再次导出评审稿时逐条目附「上轮意见及处理」表，证明闭环
- 行级对照模式（删红增绿）；勾选部分条目导出；意见↔章节树联动跳转
- 接入 `BaselineStore` 版本化基线，支持对比指定历史版本；「已解决未确认」按项目设置收紧为硬门禁
- 纪要自动签批流程（评审组长/记录人签字行、评审结论区）