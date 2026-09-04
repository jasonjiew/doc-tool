调查已完成，方案按你的评审纪要表重做了一版。核心变化：**评审纪要表就是数据模型本身**，面板即表格，闭环规则由表格的填写完整性定义。

# 修订评审闭环 — 完整方案（v2）

## 1. 目标与交付物

**唯一衡量标准**：会后能一键导出这张表，且「更改结果与证据」列由工具自动采集，不靠人回忆。

| 序号 | 提出人 | 评审问题                    | 责任人 | 评审记录           | 更改结果与证据                                               | 遗留问题              | 计划完成时间 | 更改确认        |
| ---- | ------ | --------------------------- | ------ | ------------------ | ------------------------------------------------------------ | --------------------- | ------------ | --------------- |
| 1    | 张工   | 3.7.9 超时重试未说明次数    | 王杰   | 采纳，补充重试策略 | 3.7.9 呼吸机应用升级：新增 6 行（重试 3 次/指数退避）；2026-09-03 改；V2.6 出稿 | —                     | 2026-09-05   | 张工 2026-09-06 |
| 2    | 李工   | 10.2.3 补偿边界建议给流程图 | 王杰   | 采纳，本版不做     | —                                                            | 下版补 Mermaid 流程图 | 2026-11-30   | —               |

两个交付物：

1. **评审稿 DOCX** — 只含改动章节，会前发出去，会议室用 Word 加批注
2. **评审纪要 DOCX**（上表）+ 同源 Markdown — 会后归档进 QMS

## 2. 闭环链路

```
① 改完稿                      改动面板 → 「导出评审稿…」
        ↓
② 评审稿 DOCX + 轮次建立      output/review/评审稿-2.6-第1轮-<ts>.docx
   同时冻结本轮内容快照        .state/reviews/rounds/<id>/content/
        ↓
③ 会议室 Word 加批注          （工具不参与）
        ↓
④ 批注 DOCX 拖回工具          自动生成纪要行：序号/提出人/评审问题 + 章节定位
        ↓
⑤ 面板补会议字段              责任人 / 评审记录 / 计划完成时间
        ↓
⑥ 作者改稿 → 逐条「已改」      工具自动采集「更改结果与证据」
                              = 本轮快照 vs 当前 的真实 diff + 时间 + 版本号
        ↓
⑦ 确认人逐条「确认」          更改确认 = 确认人 + 时间
   改不了的转「遗留」          遗留问题 + 计划完成时间
        ↓
⑧ 全部行已确认或已转遗留       轮次标记闭环 → 导出评审纪要 DOCX
        ↓
⑨ 正式合并                    发布前只提示评审状态，不阻断
```

第 ⑥ 步是这版方案的核心：证据不是手写的，是工具从「评审时那一版」到「现在这一版」的实际差异里算出来的，因此不可能造假、不可能漏记。

## 3. 数据模型

一行纪要 = 一条 `ReviewComment`（扩展既有 dataclass，全部新字段带默认值，旧 JSON 不炸）。

| 表格列         | 字段                            | 来源                                          |
| -------------- | ------------------------------- | --------------------------------------------- |
| 序号           | `seq`                           | 轮次内自增                                    |
| 提出人         | `author`                        | Word 批注作者（可改，批注作者常是域账号）     |
| 评审问题       | `text`                          | Word 批注正文                                 |
| 责任人         | `owner`                         | 面板指派                                      |
| 评审记录       | `review_note`                   | 面板录入（会议结论：采纳/不采纳/待定 + 说明） |
| 更改结果与证据 | `change_result` + `evidence{}`  | **自动采集**，可追加手工说明                  |
| 遗留问题       | `pending_issue`                 | 面板录入                                      |
| 计划完成时间   | `due_date`                      | 面板录入（YYYY-MM-DD）                        |
| 更改确认       | `confirmed_by` + `confirmed_at` | 面板「确认」动作                              |

定位与去重字段（不进表格，供跳转与幂等）：`round_id` / `rel_path` / `chapter_no` / `line_no` / `anchor_text` / `source`(word\|panel\|text) / `fingerprint`。

状态机：`unresolved`（待改）→ `resolved`（已改，有证据）→ 确认（`confirmed_by` 非空）；或 `deferred`（遗留，需 `pending_issue` + `due_date`）。既有 `unresolved_count` 语义不动，新增 `open_count` / `deferred_count` / `confirmed_count`。

`evidence` 结构化内容：`relPath / chapterNo / addedLines / removedLines / diffExcerpt / changedAt / documentVersion / contentSha1`。渲染成中文一句话进表格，原始数据留在 JSON 里可复查。

## 4. 评审稿为什么走内核装配

不用现成的 `markdown_word.py` + Word COM 那条 HTML→Word 路，三个硬理由：

1. **不能依赖本机 Word** — 会前出稿必须稳；公司 DocGuard 透明加密环境下 Word 产物读写已知受限
2. **复杂表格会丢** — 你的 `content/` 有 41 处 `<!-- TABLE:n:xxx.xml -->` OOXML 资源表（13 个文件），HTML 路表达不出来
3. **版式不是公司模板** — HTML 路落通用排版；内核路从 `template/template.docx` 取标题样式、页面设置、页眉页脚，评审稿与正式稿同源同貌

新增 `scripts/build_review.py`，**复用** `build_docx.py` 的零件（`make_heading` / `process_markdown` / `ImageManager` / `NumberingManager` / `ExpressionManager` / `make_table_from_md` / `update_headers` / `_validate_zip_xml`），**不改 `build_docx.build()` 一行** —— 正式出稿链路零风险。

### 评审稿结构

- 模板正文只保留 `w:sectPr`（页面设置），封面/目录/修订表不进评审稿；页眉保留（文档号 + 版次，打印可追溯）
- 标题块：`评审稿（非正式交付物）` + 文档名 + 版本 + 第 N 轮 + 生成时间 + 基线说明
- 改动汇总表：`章节号 | 标题 | 状态 | 文件`
- 逐章节：章节标题（**章节号写进标题文字**）→ 改动摘要 → 正文
- 不生成 TOC（章节少 + 前有汇总表，因此也不需要 Word 刷新域）

**章节号必须写进标题文字**：只导出子集时 Word 自动编号会把 `3.7.9` 重编成 `1.1.1`，评审人对不上原文。评审稿一律文字号 + 关闭 `w:numPr`。

### 改动摘要（每节正文前）

复用 `changes.render_unified_diff(基线原文, 当前原文)`，等宽 run 呈现，超 60 行截断并注明「完整差异见工具内改动面板」。基线原文取 `.state/baseline/<rel_path>`（既有机制，Git/SVN 项目同样走它）。

- `新增` 章节：不给摘要（整节都是新的）
- `删除` 章节：从基线取原文以引用块给出，让评审确认「删得对不对」
- 默认开启，可关

### 评审纪要 DOCX

同一装配器的第二个入口 `build_minutes_docx`：A4 **横向**（9 列），表头行加 `w:tblHeader` 使多页打印重复表头，列宽按 dxa 分配（评审问题/评审记录/更改结果与证据 三列占大头）。页眉带文档号 + 版本 + 轮次。同时落一份 `minutes.md` 便于粘贴与版本控制留痕。

## 5. Word 批注怎么自动落位（纯离线）

**导出时**：每个章节起点埋 `w:bookmarkStart w:name="rev_0001"`，`{书签名 → rel_path, 章节号, 标题, 起始行}` 写进轮次 JSON。

**导入时**（纯 Python 解 ZIP，不开 Word）：

1. 解析 `word/comments.xml` → `{comment_id: 文本, 作者, 时间}`
2. 顺序遍历 `word/document.xml`，维护「当前书签」游标，遇 `w:commentRangeStart` 即知归属哪个 `rel_path`
3. 行号：取批注锚定范围内可见文字（锚点文字），回该 `.md` 归一化匹配（先精确 substring，再 `difflib` 最佳行）→ `line_no`；匹配不到落章节首行并标注「定位到章节」
4. 去重：`fingerprint = sha1(round_id + comment_id + author + text)`，同一份 docx 反复导入不产生重复行
5. 检测 `w:ins` / `w:del`（评审人直接改稿而非加批注）→ **不合并**，列出所在章节并警告「请转成批注，或由作者据此改 Markdown」

不合并直接改稿是刻意取舍：修订标记语义是「改成这样」，机器往 Markdown 回写会绕过校验、破坏表格元数据与资源引用。

## 6. 评审面板 = 纪要表格本身

工具面板第 8 个 Tab「评审」，主体是 `QTableWidget`，9 列即交付表的 9 列，单元格直接可编辑。

顶部工具条：`轮次下拉` `导出评审稿…` `导入批注 DOCX…` `新增行` `删除行`
底部动作条：`定位到章节` `采集证据` `标记已改` `确认` `转遗留` `导出纪要…` + 闭环状态标签

闭环状态标签实时算：`第2轮：12 条，9 已确认，2 遗留，1 待改 → 未闭环（缺 1 条证据、1 条确认）`

只读项目隐藏全部写操作（沿用 `set_writable` 约定）。

## 7. 文件清单

**新增（服务层，无 Qt，可纯单测）**

| 文件                                             | 职责                                                         |
| ------------------------------------------------ | ------------------------------------------------------------ |
| `doc_tool/application/review/review_scope.py`    | 纯函数：`status_map` + 内容索引 → 有序评审范围（章节号/标题/状态/rel_path/基线原文） |
| `doc_tool/application/review/review_rounds.py`   | `ReviewRoundStore`：轮次台账 + 本轮内容快照冻结/读取         |
| `doc_tool/application/review/review_export.py`   | 编排：算范围 → 调内核装配 → 落 `output/review/` → 建轮次     |
| `doc_tool/application/review/comment_import.py`  | 离线解析批注 DOCX → 落位 → 生成纪要行 → 导入报告             |
| `doc_tool/application/review/review_evidence.py` | 纯函数：本轮快照 vs 当前 → 结构化证据 + 中文一句话           |
| `doc_tool/application/review/review_minutes.py`  | 纪要渲染：JSON → Markdown 表 → DOCX 装配参数                 |
| `scripts/build_review.py`                        | 内核装配器：`build_review_docx` + `build_minutes_docx`       |
| `doc_tool/ui/content/review_panel.py`            | 9 列纪要表格面板                                             |
| `scripts/tests/test_review_workflow.py`          | 全套单测                                                     |

**修改**

| 文件                                    | 改动                                                         |
| --------------------------------------- | ------------------------------------------------------------ |
| `review_store.py`                       | `ReviewComment` 扩 9 列字段 + 定位/去重字段；`from_dict` 容错；`import_comments`（批量去重）；`set_evidence` / `confirm` / `defer`；`open_count`/`deferred_count`/`confirmed_count` |
| `content/baselines.py`                  | `CheckItem` 加 `severity="error"`；`pre_publish_checks` 的 reviews 项改 `severity="info"` 且恒 `passed=True` |
| `adapters/kernel.py`                    | 加 `build_review_with_project` / `build_minutes_with_project` |
| `ui/main_window.py`                     | `_confirm_pre_publish_checks` 只把 `severity="error"` 当阻断；「评审意见…」从 QInputDialog 简版改为跳评审面板 |
| `ui/content/changes_panel.py`           | 顶部加「导出评审稿…」（回调注入，面板不碰 IO）               |
| `ui/content/workspace.py`               | 6 处接线：import / 占位 Tab / `_populate_panels` / 刷新 / `set_writable` / `show_review()` |
| `application/cli_commands.py`、`cli.py` | 加 `review` 子命令                                           |
| `scripts/tests/run_tests.py`            | `DEFAULT_TESTS` 登记新测试                                   |
| `docs/使用说明.md`                      | 新增第 6 节「修订评审」，原 6/7/8/9 顺移                     |
| `README.md`                             | 功能简介加一条                                               |

## 8. 存储布局

```
.state/reviews/
  comments.json                        # 纪要行（既有文件，字段向后兼容扩展）
  signoffs.json                        # 既有，不动（轮次级签字）
  rounds/
    20260903T101500Z.json              # 轮次台账：轮次号/时间/版本/范围/书签映射/产物路径/导入记录/闭环状态
    20260903T101500Z/content/…         # 本轮冻结快照（仅改动章节，证据 diff 的基线）
    20260903T101500Z/minutes.md        # 派生纪要 Markdown
output/review/
  评审稿-2.6-第1轮-20260903T101500Z.docx
  评审纪要-2.6-第1轮-20260903T101500Z.docx
```

沿用既有约定：`atomic_write` + `ensure_ascii=False, indent=2` + camelCase JSON 键。`.state/` 新目录对构建/校验不可见、可整目录删除；`project.yml` 不加字段。

**单一维护点**：JSON 是权威，Markdown 与 DOCX 都是派生产物，面板是唯一编辑入口 —— 不搞双向同步。

## 9. CLI

```powershell
doc-tool review --export                 # 导出评审稿，建轮次
doc-tool review --import <批注.docx>     # 回导批注
doc-tool review --minutes                # 导出本轮纪要（--all-rounds 合并全部轮次）
doc-tool review --status                 # 机器可读闭环状态
```

沿用 `run_per_project` + `CommandResult` + `serialize_json`（`schemaVersion: 1`），退出码 0/1/2/3 语义不变。

## 10. 发布门禁（按你选的「不拦」）

`pre_publish_checks` 的 reviews 项恒 `passed=True`、`severity="info"`，文案形如：

```
ℹ 评审：第 2 轮 12 条意见，9 已确认，2 遗留（最近计划完成 2026-09-10），1 待改
```

`_confirm_pre_publish_checks` 只把 `severity="error"` 的失败项计入阻断。质量规则 / 版本 / 未完成改动三项行为完全不变，CLI 出稿路径不新增拦截。

## 11. 任务分期（服务层先行，每阶段带单测）

| #    | 阶段                                          | 验收                                                         |
| ---- | --------------------------------------------- | ------------------------------------------------------------ |
| 1    | `openspec/changes/revision-review-loop/` 文档 | proposal/design/tasks/spec 齐备                              |
| 2    | `review_scope.py`                             | 删除章节、rename、资源改动映射到章节、非 md 排除             |
| 3    | `review_rounds.py`                            | 轮次递增、快照冻结、损坏 JSON 容错                           |
| 4    | `scripts/build_review.py` 评审稿              | 真实模板装配、复杂表格嵌入、图片、书签埋点、ZIP 校验         |
| 5    | `review_export.py` + kernel 接线              | 端到端出 DOCX 并解回验证书签与章节数                         |
| 6    | `comment_import.py`                           | 落位、锚点匹配、退化到章节首行、去重、`w:ins` 警告、坏包容错 |
| 7    | `review_evidence.py`                          | 增删行数、diff 摘要、快照缺失降级                            |
| 8    | `review_minutes.py` + `build_minutes_docx`    | 9 列表格、横向纸张、表头重复、Markdown 与 DOCX 同源          |
| 9    | `review_store` / `baselines` 扩展             | 旧 JSON 兼容、severity 不破坏既有调用与既有测试              |
| 10   | UI：评审面板 + 改动面板入口 + 接线            | 离屏测试                                                     |
| 11   | CLI `review` 子命令                           | `test_cli_machine.py` 补例                                   |
| 12   | 文档 + 全量回归                               | `python scripts\tests\run_tests.py` 全绿                     |

## 12. 风险与对策

| 风险                             | 对策                                                         |
| -------------------------------- | ------------------------------------------------------------ |
| 清空模板正文丢样式               | 样式/编号/页眉页脚在其它 part，正文只留 `sectPr`；单测断言标题样式与页面设置存活 |
| 批注落错行                       | 匹配不到即退到章节首行并标注「定位到章节」，绝不猜；意见永不丢 |
| 证据被绕过（改完再删轮次快照）   | 快照缺失时证据标注「无本轮基线，证据不可自动核验」，不静默给出假证据 |
| 评审稿被误当正式交付物流出       | 标题块写明「评审稿（非正式交付物）」；文件名带「评审稿」与轮次；输出到 `output/review/` 而非 `output/` |
| 9 列表格在 A4 上挤               | 横向 + 三大列优先分宽 + 表头重复；`<br>` 换行按 Word 真换行落 |
| 大量图片致评审稿臃肿             | 复用 `ImageManager` 媒体去重（与正式构建同机制）             |
| 旧项目无 `.state/baseline/` 副本 | 既有 `ensure_baseline_content` 兜底；仍缺则该节不给改动摘要、正文照出、汇总表注明 |
| DocGuard 环境                    | 全链路纯 Python 读写 ZIP，与 `build_docx` 同路径，零 Word 依赖 |
| 多轮意见混淆                     | 意见强绑 `round_id`；纪要默认导本轮，`--all-rounds` 才合并且带轮次列 |

## 13. 明确不做（本期）

- 不做全文修订对照稿（Word 真修订标记对比，留阶段 2）
- 不把评审人的直接改稿（`w:ins`/`w:del`）合并回 Markdown
- 不接外部 CA/PKI 签字，不做多人实时协作
- 不改 `pipeline.py`（门禁按你的选择不下沉到管线）
- 不改 `build_docx.build()` 与正式出稿链路
- 不做评审意见的跨项目汇总统计

## 14. 与「只做评审包 JSON」等轻方案的关键差别

现有代码里已有 `ReviewPackageBuilder`（导出一堆 JSON）—— 那是死代码，因为会议室里没人看 JSON。这版方案的差别就三条：**评审稿是 Word 且带公司版式**、**批注自动落位不用人抄**、**证据自动采集不靠人回忆**。缺任何一条，闭环就会退化成手工填表。

审核完告诉我改哪里，或直接说开工，我从第 1 项 openspec 文档开始。