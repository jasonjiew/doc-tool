## Context

现状已具备实现本功能的地基，无需新依赖：

- **改动口径**：`content/snapshot.py` 的会话基线（`.state/content_baseline.json` + `.state/baseline/` 原文副本）能对任意外部/编辑改动做 `added/modified/deleted` 分类，`changes.py` 的 `build_change_items` + `overlay_rename_status` 归并重命名、`render_unified_diff` 给出「基线 vs 当前」差异。基线只在「清除标记」或「发布成功后」（`pipeline._refresh_content_baseline`）重置——因此「当前基线以来的改动」天然对应「本次修订要评审的内容」，口径无需新造且与改动面板/章节树徽标完全一致。
- **渲染**：`markdown_word.py::markdown_to_word_html` 把 Markdown 渲染成带排版样式的 HTML（宋体/Times、标题层级、表格边框、图片内嵌），`convert.py` 再经本机 Word 转 DOCX；`adapters/word_convert.py` 提供 `WordNotAvailableError` 等稳定错误通道。评审稿可整条复用该链路。
- **评审存储**：`review/review_store.py` 已有意见（绑 `rel_path`+行号）、签字、`approval_gate` 与 `ReviewPackageBuilder`（导出 json 评审包）；`content/baselines.py::pre_publish_checks` 已把「无未解决评审意见」纳入发布前检查。闭环的存储与门禁骨架已经存在。
- **章节定位**：`content/revision_record.py::section_labels` 由 `rel_path` 推导「章节→小节」标签，`_revision_table_rows`/`last_revision_version` 可读修订记录末行（版本/摘要/日期/修改人）。
- **离线读 DOCX**：`domain/ooxml.py`（`read_docx_package` + lxml）与 importer 同款，会议后回读评审意见表不依赖 Word。

缺的正是用户明确要的两个环节：**面向会议的离线评审稿（Word）**，和**评审意见回流工具并证明闭环**。

## Goals / Non-Goals

**Goals:**

- 把「本次修订的改动章节」一键导出成会议可用的离线评审稿：信息块 + 本次修订记录行 + 改动总表 + 逐条目「修改前/修改后上下对照」正文 + 空白评审纪要表（9 列公司模板）附录；有 Word 出 DOCX，无 Word 降级 HTML。
- 导出时生成评审条目快照（条目号 ↔ rel_path ↔ 导出时 sha1），与评审稿同目录落盘，作为「会议条目 ↕ 工具章节」的缝合锚点，并检测「导出后又有改动」。
- 从任意含 9 列纪要表头（序号/提出人/评审问题/责任人/计划完成时间/更改确认/评审记录/更改结果与证据/遗留问题）的 DOCX 离线解析意见，幂等回流入 `ReviewStore`，条目号命中自动绑章节、未命中手工绑定。
- **生成正式《评审纪要》**：闭环后把意见输出为公司 9 列标准表（两行表头，责任人跨 3 列拆「责任人/计划完成时间/更改确认」），支持空表（打印/会议）与闭环填充两模式，Markdown 原生、DOCX 经 Word、无 Word 降级 HTML；只生成新文件，绝不改写用户已填写的纪要。
- `ReviewComment` 按 9 列纪要字段扩展（责任人/计划时间/更改确认/变更证据/遗留问题/评审记录等），均为带默认值的追加字段，旧数据直接可读。
- 发布门禁沿用「未解决意见阻断」；对「已解决但更改确认为空」的条目在发布前检查中提示；再次导出评审稿时附上轮意见及处理（二期）。

**Non-Goals:**

- 不做多人实时协作、不做跨机器签名字段防篡改（签字仍为本地记录）。
- 不改变 `content_baseline.json`、`content_changes.json`、`comments.json` 的既有结构语义；不新增运行时依赖。
- 模型的「修改前」图片不做逐字节回溯（基线只存 `.md` 文本），前稿图片尽量复用当前 assets 同路径，缺失以占位标注；不扩 baseline 副本格式。
- 不把逐条意见内嵌进 Markdown 正文；意见唯一记录处是附录评审单 + `.state/reviews/`。
- 工具绝不改写用户已填写的正式评审单 DOCX（只读导入）；「回填导出」另生成副本，属二期。
- 一期不接入版本化基线（`BaselineStore`）做「对比指定历史版本」，列为二期。

## Decisions

### 1. 改动口径：复用会话基线，与改动面板同源

评审稿收集改动用 `ContentSnapshot.load()` → `diff(content_root, files)` → `overlay_rename_status(status, ChangeManifest.entries)` → `build_change_items(...)`（`changes.py`），过滤 `*.md` 内容文件并排除 `_revision_record.md`。条目顺序按章节号自然排序，导出时按序分配 `R01…` 条目号。

**备选考虑过：** 用 `BaselineStore` 版本化冻结对比 → 目前 `freeze` 只有测试在用、未接发布流程，且「对比哪一版」会引入口径分歧；会话基线已与改动面板一致，无歧义。版本化对比列入二期。

### 2. 导出链路：复用 Markdown→Word，无 Word 降级 HTML

评审稿生成一个 Markdown（见决策 3 的结构）→ `markdown_to_word_html(text, content_root, title)` 渲染 HTML → 交 `convert.py` 的 md→docx 计划经本机 Word 转 DOCX，沿用既有超时与 `WordNotAvailableError`。捕获 Word 不可用时，把已渲染 HTML 直接作为评审稿交付（浏览器/Word 均可打开），文件名以 `（HTML 版）` 标注，不阻断会议。中间 `.md` 一并落在评审包目录，留作溯源。

**备选考虑过：** 用 Word COM 从零排版（复杂、慢、重复造样式）；用 python-docx 生成（项目无此依赖且要重造排版样式）。两者都不如复用既有渲染与转换通道。

### 3. 评审稿文档结构（五段式）

1. **信息块**：文档编号/名称（`manifest`）、本次版本（修订记录末行）、基线时间（`content_baseline.json` mtime，标注近似值）、导出人（`USERNAME`）、导出时间、改动统计（N 增/N 改/N 删/N 重命名）、评审稿编号 `packageId`；评审人据此核对评审范围与版本。
2. **本次修订记录行**：读 `_revision_record.md` 末行（版本/摘要/日期/修改人），评审会顺带核对作者有没有写对——评审稿自带该行，不必另行打开修订记录。
3. **改动总表**：条目号 | 章节→小节（`section_labels`）| 改动类型 | 评审结论（留空勾选）——评审人靠它快速扫全貌。
4. **逐条目正文**：
   - `modified`：`「R0n 章节→小节（修改）」` + 「修改前（基线 X）」+ 基线全文 + 分隔线 + 「修改后（当前）」+ 新稿全文（前/后上下对照）；
   - `added`：标「新增章节」+ 新稿全文；
   - `deleted`：标「本章节在本次修订中删除」+ 原文。
   - 前稿图片：基线 `.md` 里的图片链接按当前 assets 同路径解析，缺失以「（前稿图片缺失：文件名）」占位。
5. **附录：空白评审纪要表（9 列公司模板）**：两行表头、责任人跨 3 列（拆「责任人/计划完成时间/更改确认」），其余 6 列跨两行，预填若干空行；意见唯一记录处，逐条目正文后不再放空白意见区，避免双处记录。

### 4. 评审条目快照与评审包目录整合

`packageId = RS-<yyyyMMdd-HHmmss>`，写入信息块与 `review_items.json`。`review_items.json` 结构：`{packageId, version, createdAt, baselineTime, items:[{itemId, relPath, status, sectionLabel, subLabel, baselineSha1, currentSha1}]}`。输出整合进既有 `ReviewPackageBuilder` 的评审包目录 `output/review/review-package-<版本>-<时间戳>/`，同一目录放评审稿 DOCX（或 HTML）、`review_items.json` 与既有 json 包；`build` 增加可选参数承接评审稿与条目清单，`manifest.json` 记录评审稿文件名与条目数。

**备选考虑过：** 评审稿与 json 包分两目录 → 评审材料分散，归档/拷贝易漏；合目录一次性带走。

### 5. 公司评审单字段映射与 `ReviewComment` 非破坏性扩展

| 评审纪要列 | `ReviewComment` 字段 | 说明 |
| --- | --- | --- |
| 序号 | `row_serial` | 原表序号，幂等键组成部分；导出纪要时重排 1..n |
| 提出人 | `author` | 既有 |
| 评审问题 | `text` | 既有 |
| 责任人 | `assignee` | 新增，默认空 |
| 计划完成时间 | `planned_date` | 新增，默认空 |
| 更改确认 | `confirm_status` | 新增，空=未确认 |
| 评审记录 | `resolution_note` | 新增，处理说明 |
| 更改结果与证据 | `evidence` | 新增 |
| 遗留问题 | `open_issue` | 新增 |
| 工具补记 | `rel_path`/`line_no`/`review_ref`/`item_id`/`status`/`resolved_at`/`association_changed` | 既有 + 新增 `review_ref`（评审稿编号）、`item_id`（条目号） |

所有新字段带默认值空串，`comments.py` 反序列化 `ReviewComment(**item)` 对缺键沿用默认值，旧 `comments.json` 直接可读。新增白名单更新入口 `update_fields(comment_id, **fields)`（仅允许上述业务字段），状态推进沿用 `set_resolved`。`mark_association_changes` 对 `rel_path` 的既有兜底继续生效。

**备选考虑过：** 另建 `review_form.json` 单独存公司单字段 → 同一条意见两处存储，同步是 bug 源；直接扩展意见记录最简。

### 6. 意见导入：表头驱动 OOXML 解析 + 幂等 + 绑定

`review_import.py` 用 `read_docx_package` + lxml 直读 `word/document.xml`（离线，与 importer 同基建）：定位含「评审问题」「提出人」表头的表格，按**表头文本驱动**取列索引（非固定列位，按去空格包含匹配容错两行表头与合并单元格展开）。一行 = 一条意见（公司评审单每行一条意见的惯例；单元格内换行并入单条）。

幂等键：优先 `(review_ref, row_serial)`；外来表单无 `review_ref` 时回退 `(rel_path or "", author, sha1(text))`。重复导入跳过已存在项，结果反馈「新增 N / 跳过 M」。

绑定：可用 `review_items.json` 时按 `row_serial/ item_id` → `rel_path`；否则按评审问题文本里的条目号前缀（如 `R02:`）命中，或经 `section_labels` 反查（对当前内容索引建「标签→rel_path」映射）。绑定不上则 `rel_path=""`，意见面板「绑定章节」手工补（选择器复用内容索引）。漂移检测：`review_items.json` 可用时比较条目 `currentSha1` 与当前文件 sha1，不一致提示「该条目自导出后又有改动」（仅提示不阻断）。

**备选考虑过：** 用 Word COM 读表格（依赖 Word、慢）；限定必须用本工具导出的评审稿（会议室场景不现实，外来表单也要能收）。

### 7. 正式评审纪要生成：9 列标准表，空表/填充两模式

新增 `doc_tool/application/review/review_minutes.py`：把闭环后的 `ReviewStore.comments` 输出为公司 9 列标准纪要表。表结构两行表头、共 9 列：`序号│提出人│评审问题│责任人│计划完成时间│更改确认│评审记录│更改结果与证据│遗留问题`，其中「责任人」跨 3 列（第二行拆「责任人 / 计划完成时间 / 更改确认」），其余 6 列跨两行——实施前以用户真实纪要样本校准合并单元格细节。

生成两模式：**空表**（N 空行，供打印/会议用，即评审稿 4.1 附录的单独导出）；**闭环填充**（导出全部或按筛选的意见，逐行回填九列；序号重排 1..n，导入的原始序号保留在 `row_serial` 供溯源）。信息块含文档编号/名称、本次版本、纪要编号（如 `JL-文档编号-版本-时间`）、评审发起人/时间、统计（总/已解决/已确认/遗留）。渲染 `markdown_to_word_html` → Word 转 DOCX，无 Word 降级 HTML；**只生成新文件，绝不改写任何用户已填写的原始纪要文件**。

**备选考虑过：** 用公司外部模板由工具回填内容 → 模板版式不可控、也违背「工具直接生成纪要」的既定目标；由工具按同一 9 列结构生成，版式统一、可控。

### 8. 闭环状态机与发布门禁

意见状态沿用既有 `unresolved/resolved` 两态；`confirm_status` 独立跟踪「更改确认」（空=未确认，非空=已确认）。流转：导入/登记 → `unresolved`（待处理）→ 编辑 `resolution_note`/`evidence` → `resolved`（已解决）→ 填 `confirm_status`（确认）→ 关闭。逐条解决与确认在意见对话框内完成。

门禁：`pre_publish_checks` 既有 `reviews` 项不动（未解决即阻断）；新增 `confirm` 检查「无已解决但未确认」——failed 时走既有「跳过检查」覆盖路径并在发布历史留 `history_note`（语义与既有 skip 一致），不另设硬门禁。发布成功 → `_refresh_content_baseline` 重建基线 → 新一轮改动口径自动重置。二期：再次导出评审稿时，逐条目下自动附「上轮意见及处理」表（意见/结论/证据/确认状态），证明闭环。

**备选考虑过：** 把「未确认」设为硬阻断 → 各团队对「更改确认」的提交流程不一，硬门禁会卡住；先提示+可跳过，二期按项目设置可收紧。

### 9. UI 落点

- `changes_panel.py` 标题行新增「导出评审稿」「生成评审纪要」「导入评审意见」（与「生成修订记录」并排；导入仅 writable 启用）。
- 导出评审稿：确认对话框（改动统计预览 + 基线时间 + 目标目录）+ 后台线程执行（沿用发布前检查的 `QProgressDialog` + `threading.Thread` 模式），完成后打开所在目录。
- 生成评审纪要：对话框（空表 / 闭环填充；行数或筛选；输出目录），完成后打开。
- 意见管理对话框 `ui/content/review_dialog.py`：列表（状态/确认/责任人多筛）、双击跳转章节（复用 `open_file(rel_path, line)`）、按 9 列纪要字段编辑、解决/确认、绑定章节、「导入评审意见」「生成评审纪要」入口；`main_window._on_review_panel` 替换为打开该对话框。

## Risks / Trade-offs

- 公司评审单两行表头/合并单元格存在变体 → 表头驱动 + 展开容错；实现前向用户要一份真实评审单（docx/xlsx 样本）作解析测试夹具，把变体固定进测试。
- 基线只存 `.md` 文本不存图片 → 前稿图片按当前 assets 同路径尽力解析，缺失占位标注；不为它扩 baseline 格式（成本高、收益低）。
- 前后对照评审稿在超大文档上很厚 → 信息块统计 + 改动总表先行，评审人按总表挑读；二期支持勾选部分条目导出。
- 评审纪要表是正式 QMS 记录 → 工具只读导入、绝不改写用户文件；「生成评审纪要」始终**新建文件**（导出目录内另命名），不覆盖任何既有纪要。
- `ReviewComment` 新字段被旧版本程序读取会 `TypeError` → 单机内部工具随版本同步升级，接受；文档标注。
- 外来表单绑章节成功率低 → 意见对话框「绑定章节」手工兜底 + `association_changed` 既有标记机制。
- 幂等键以 `row_serial` 为唯一序号、填定后不改 → 序号被改动会按新意见处理而重复；概率低，导入结果里展示新增/跳过计数以便人工核对。