## Context

编辑器侧已完成基础体验：`_LineNumberedEdit`（行号）+ `MarkdownHighlighter`、Ctrl+F 查找条（`focus_find`/`_update_highlights`）、编辑滚动→预览单向同步（`_sync_preview_scroll`/`_scroll_preview_to_heading`）、`render_markdown_html` 受控 HTML 预览。缺口：

- 查找条无替换行；预览无点击回定位。
- 无拼写检查、代码片段、格式化工具栏。
- 图片：`references.py` 已能解析 `![alt](images/x.png =WxH)` 并做悬空检测，但无写入能力；资源目录无清理入口。
- Mermaid：`content/design/` 下 47 处 `flowchart`/`sequenceDiagram` 源码以正文段落形式存放，`render_markdown_html` 与 `build_docx.process_markdown` 均按普通段落处理，图从未渲染进 Word。

复用基础：`ContentWriter`（备份+原子写+回收站删除）、`ReferenceScanner`（图片悬空检测）、`ContentIndex`（文件/行索引）、`ImageManager`+`image_size_emu`（构建侧图片尺寸）、`_preview_base_url`（文档类型推导：rel_path 首段）、`TabsHost` 快捷键模式（`QShortcut`）。

## Goals / Non-Goals

**Goals:**

- 编辑器补齐创作高频能力：文件内替换、拼写检查、代码片段、Markdown 工具栏、预览双向定位。
- 图片粘贴/拖入自动入资源目录并插入带尺寸引用；未使用/缺失资源可清理修复。
- Mermaid 工作台：语法检查、实时预览、一键导出图片插入 Word，批量转换既有裸源码图。
- 保持既有图片引用语法、构建语义与撤销/保存/备份机制不变（无破坏性变更）。

**Non-Goals:**

- 不做中文分词/语法检查（拼写检查仅英文单词）；不做在线词典。
- 不做 Mermaid 全语法（gantt/pie 等）的自绘渲染兜底；复杂类型依赖 mermaid-cli。
- 代码片段为用户级配置，不做团队共享/同步。
- 图片管理不自动改图（裁剪/压缩）；尺寸仅按原始像素记录。
- Mermaid 渲染不新增硬性运行时依赖；mermaid-cli 为可选增强。

## Decisions

### 1. 文件内替换：扩展现有查找条，替换走撤销栈
在 `editor_panel._build_find_bar` 下方新增替换行（查找/替换/上一个/下一个/替换一个/全部替换/关闭）。「替换一个」用 `QTextCursor` 对当前选中命中做替换并跳到下一处；「全部替换」用 `document().beginEditBlock()`/`endEditBlock()` 包住整轮替换，使全部替换成为单个撤销单元；替换完成后刷新高亮。快捷键 `Ctrl+H` 复用 `TabsHost` 的 `QShortcut`（焦点在当前编辑器时激活）。替换只改文本不触发构建，沿用既有脏标记与保存路径。

**Alternatives considered:**

- 用 `QPlainTextEdit` 原生 find/replace → 无原生 replace-all 撤销分组，需自建。
- 走 `ReplaceService`（跨文件）→ 那是全局替换面板，文件内替换要求即点即改+撤销栈，应留在编辑器。

### 2. 拼写检查：纯服务 + 高亮器叠加，零新依赖
新增 `doc_tool/application/content/spellcheck.py`：`SpellChecker(builtin_words, user_words)`——`check(text) -> List[Misspelling(word, start, end)]`。英文词 token 用正则 `\b[a-zA-Z][a-zA-Z'-]{1,}\b`，跳过围栏代码块与中文；查内置词典（打包 `resources/dict/en_words.txt`，约 5 万常用词）+ 用户词典；建议用编辑距离 ≤2 与共同前缀候选。内置词典打包进资源目录（应用资源，非项目资源）。UI 复用 `MarkdownHighlighter` 的机制另加一层：在 `_LineNumberedEdit` 上用 `ExtraSelections` 画红色波浪线（`QTextCharFormat` 下划线样式），随内容变化去抖重扫（只扫可见范围以控制大文档开销）；右键菜单注入候选与「加入词典」。用户词典写入 `QStandardPaths.AppDataLocation/user_dict.txt`。

**Alternatives considered:**

- 引入 `pyspellchecker`/`enchant` → 新增运行时依赖且打包复杂，排除。
- 每次击键全文件重扫 → 大文档卡顿；按可见行 + 去抖（复用 300ms 预览去抖窗口附近）。

### 3. 代码片段：用户级 JSON 存储 + 占位符状态机
新增 `doc_tool/application/content/snippets.py`：`Snippet(trigger, description, body)`，`SnippetStore` 读写 `QStandardPaths.AppDataLocation/snippets.json`（原子写）。插入时把 body 写入光标，解析 `${1:default}`/`${2}` 占位符并记录位置列表；按 `Tab` 依次选中下一个占位符（`QShortcut` 在编辑器聚焦且片段激活时拦截），全部填完后恢复正常 Tab。片段管理器对话框（增删改 + 列表 + 预览）。

**Alternatives considered:**

- 项目级 `.state/snippets.yml` → 片段是个人习惯，项目无关；用户级更合理（且 `.state/` 已被草稿/会话占用语义）。
- 用 QScintilla 的 snippet 能力 → 替换编辑器组件破坏性大，排除。

### 4. Markdown 工具栏：语法包裹 + 光标模板
`editor_panel` 新增一行 `QToolBar`（标题 H2/粗体/斜体/行内代码/无序列表/有序列表/引用/表格/链接/图片）。按钮处理器统一收口：`wrap_selection(prefix, suffix)`（有选中则包裹、光标移动到文末）与 `insert_template(text, cursor_offset)`（无选中插模板）。表格按钮插入 `| 列1 | 列2 |\n| --- | --- |\n|  |  |` 并定位首单元格；图片按钮打开图片插入入口（复用 image-asset-manager）。全部操作走编辑器 undo 栈（`beginEditBlock` 包裹）。

### 5. 预览双向定位：块级锚点 + anchorClicked
`preview.py` 的 `render_markdown_html` 为每个块生成带源行号的锚点：块标签前插入 `<a name="line-N"></a>`（或块上挂 `id`），同时为标题块保留文本查找锚定（既有 `_scroll_preview_to_heading` 逻辑保留作为编辑→预览的粗粒度锚定，可改为按块锚点）。预览 `QTextBrowser` 关闭「打开外部链接」（`setOpenExternalLinks(False)`），接入 `anchorClicked`：`line-N` → `editor.highlight_line(N)` + 临时高亮（复用搜索结果定位的 `highlight_line`，追加 500ms 清除的黄色背景）；`http(s)` 链接仍 `QDesktopServices.openUrl`。编辑→预览沿用既有按标题滚动，预览隐藏时短路。

**Alternatives considered:**

- 用 `QTextBrowser` 的 `scrollToAnchor` + 光标定位 → 点击链接回编辑需要 signal，anchorClicked 是标准路径。
- 为每个段落建立 `data-line` 再 JS 定位 → Qt HTML 引擎不支持自定义点击 JS，排除。

### 6. 图片资源管理：`asset_manager.py` + 面板 + 编辑器钩子
新增 `doc_tool/application/content/asset_manager.py`（纯服务，可单测）：
- `next_image_name(assets_root, doc_type, ext)`：扫描 `assets/<类型>/images/` 与 `image-map.yml` 计数器，返回下一个 `img_NNNN.ext`（不覆盖既有）。
- `import_image_data(data, assets_root, doc_type, ext) -> (rel_path, width_px, height_px)`：写文件、PIL 验图、读尺寸（复用 `image_size_emu` 的像素口径：`width_px = cx/9525` 不适用粘贴图，直接 PIL `image.size`）。
- `scan_unused(assets_root, index)`：`ReferenceScanner` 收集全部被引用的图片相对路径，与 `images/` 目录文件做差集。
- `list_missing(index, assets_root)`：取 `index.references` 中 `REF_IMAGE` 且 `dangling=True` 的条目。

编辑器钩子：`_LineNumberedEdit` 重写 `insertFromMimeData`（剪贴板含 `image/` MIME 时转资源导入而非文本粘贴）与 `dropEvent`（拖入文件）；文档类型从 `rel_path` 首段推导（复用 `_preview_base_url` 逻辑）。图片资源面板（`panels_host` 新 tab「图片」）：未使用列表（勾选→`writer.delete_file` 移回收站，改动面板可回滚）+ 缺失列表（重新指向文件选择/删除引用行，经 `ContentWriter` 写回）。`writer.delete_file` 对资产文件同样走回收站语义（确认其对 `assets/` 路径可用，必要时在 writer 侧加白名单路径校验）。

**Alternatives considered:**

- 图片直接存项目 `assets/` 根而不分类型目录 → 破坏 `image-map.yml`/构建资源前缀语义，排除。
- 未使用清理用 `os.remove` → 不可回滚，违背既有安全模型，必须走 writer 回收站。

### 7. Mermaid 工作台：渲染后端策略 + 存储规范
新增 `doc_tool/application/content/mermaid.py`：
- `extract_blocks(md_text)`：识别 ```mermaid 围栏块（start/end/source）与裸 `flowchart|sequenceDiagram` 起始段落（跨行聚合到空行/下一个块）。
- `validate(source, kind) -> List[Error(line, message)]`：纯 Python 子集校验器（节点/边/括号配对/箭头/标签引号/注释），错误带行号。
- `render(source, kind) -> RenderResult`：后端优先级——① 检测 `mermaid-cli`（PATH 或 `npx mmdc`）输出 SVG/PNG；② 内置子集渲染器输出 SVG（flowchart TD/LR/RL/BT 基础形状 + sequenceDiagram 基础消息）；③ 两者都不可用/类型不支持 → 返回错误。PNG 由 SVG 经 `QtSvg`（PySide6 自带）光栅化，或由 mermaid-cli 直接出 PNG。
- 导出文件名 `mermaid_NNNN.svg/png`，插入 `![图](images/mermaid_NNNN.png =宽x高)`（尺寸取 SVG 视口/PNG 像素）。

工作台 UI：`MermaidDialog`（源码编辑 + 错误列表 + 实时预览 + 「插入 Word」「转换并替换源码」）；`editor_panel` 工具栏新增 Mermaid 按钮与右键「用 Mermaid 工作台编辑」；阅读预览 `render_markdown_html` 对 ```mermaid 围栏块渲染图（失败显示错误占位）。`preview.py` 的 Mermaid 渲染为可选增强：无渲染后端时回退为代码块呈现，不影响既有预览。

**Alternatives considered:**

- 构建器直接解析 flowchart 源码生成 Word → 侵入 `build_docx`/校验器，且流程图→OOXML 无标准映射，工作量大；统一「先渲染为图、再走既有图片构建路径」复用全部既有能力。
- 固定依赖 mermaid-cli → 目标机器未必有 Node；分级后端（可选 mermaid-cli + 内置子集兜底）保证开箱可用。
- 用 QWebEngine 跑 Mermaid.js → 引入 QtWebEngine 重型依赖，排除。

## Risks / Trade-offs

- [拼写检查内置词典体积/质量] → 打包约 50k 词文本文件，体积可忽略；用户词典覆盖领域词；误报可「加入词典」。
- [全部替换误操作] → 进入单个撤销单元，可一次撤销；替换条默认聚焦、回车=下一个而非替换，降低误触。
- [Mermaid 内置渲染器子集有限] → 语法检查与渲染能力一致（同一子集），超集类型明确提示需 mermaid-cli；不静默输出坏图。
- [图片清理误删被引用资源] → 清理清单以 `ReferenceScanner` 差集为准，被引用项不可选；删除走回收站可回滚。
- [预览点击定位在长文档的精度] → 按块锚点（含行号）而非文本匹配，精确到源行；外部链接仍走浏览器。
- [大文档拼写检查性能] → 只扫可见行 + 去抖；必要时后续增量（非本变更必须）。

## Migration Plan

1. 拼写/片段/图片/Mermaid 纯服务层（`spellcheck.py`/`snippets.py`/`asset_manager.py`/`mermaid.py`）先建并单测。
2. 编辑器接线：替换条 → 工具栏 → 拼写下划线 → 片段插入/占位跳转 → 预览双向定位（`preview.py` 锚点 + `anchorClicked`）。
3. 图片：`_LineNumberedEdit` 粘贴/拖放钩子 + 图片面板（未使用/缺失）。
4. Mermaid：工作台对话框 + 工具栏/右键入口 + 阅读预览围栏块渲染 + 批量转换既有裸源码。
5. 自动化测试与回归（新增 `test_authoring_services` 服务层单测 + `test_content_operations`/`test_gui_services`/`run_tests.py`）。
6. 人工验收：替换/拼写/片段/工具栏/双向定位/图片粘贴清理/批量转换后构建校验。

回滚：全部为新增服务与 UI 扩展；既有编辑器查找/预览/保存语义不变，移除接线即可回退，无数据迁移。

## Resolved Questions

> 原 Open Questions 三项均已由实现决出，归档前关闭。

- 拼写检查是否联动需求/设计术语表（`TermStore`）「不标记」→ **本变更不接入**。保持「内置词典 + 用户词典」两条词源，领域术语由「加入词典」人工维护；TermStore 联动留作后续增强，不影响验收。
- Mermaid「批量转换」作用域 → **仅当前文档**。批量转换只作用于当前文档内的裸源码块（`batch_convert` 默认 `include_fenced=False`），不提供项目范围选项，避免误转换其它文档；用户可逐文档执行。
- 图片命名计数 → **按类型独立 `img_NNNN`**。`next_image_name` 取该类型 `images/` 目录与 `image-map.yml` 计数器中的较大序号自增，避免跨类型计数器竞争。
