## Why

大型文档以固定章节树分章维护，结构调整只能逐个重命名文件，移动章节或目录的代价高且容易留下失效引用；同时最终 Word 产物只有段落文本，缺乏正式文档必需的链接、书签、列表与脚注表达能力。

## What Changes

- 章节树支持拖拽重排：文件节点可在同目录排序、跨目录移动，目录节点拖拽移动整棵子树（批量移动）；移动后按目标目录规则自动重编号，并在应用前预览引用联动影响（受影响文件数、引用改动条数、编号冲突与警告），确认后经内容层批量写回（备份 + 改动清单 + 失败逆序回滚）。
- 扩展 Markdown 到 Word 的表达能力：构建层支持超链接、标题书签与锚点、粗体/斜体/行内代码、真实多级列表（`numPr`/`abstractNum`）与脚注（`w:footnote`），并同步扩展 `validate_docx` 的事件流与语义校验，保证可重复构建与模板保留。
- 破坏性变更：无。项目格式、`project.yml` 与既有 Markdown 语义不变；列表段落由“纯段落加符号前缀”变为真实编号列表，属构建输出增强，不改变源文件格式。

## Capabilities

### New Capabilities

- `chapter-tree-drag-reorder`: 章节树拖拽重排能力——同目录排序、跨目录与批量移动、自动重编号、引用联动预览与安全回滚。
- `word-expression-extensions`: Word 表达扩展能力——超链接、书签、粗体/斜体/行内代码、真实多级列表与脚注的 Markdown 解析与 OOXML 生成。

### Modified Capabilities

- `content-tree-nav`: 章节树在保留现有键盘操作、右键菜单、定位联动与只读行为的基础上，新增文件/目录节点的拖拽移动交互。
- `content-refactor`: 重命名/重编号联动服务由单文件计划扩展为批量移动计划（一次 dry-run 覆盖多文件重命名与引用更新），单文件语义与写入安全机制不变。

## Impact

- 主要受影响代码：`doc_tool/ui/content/tree_panel.py`（拖放交互与预览确认）、`doc_tool/application/content/tree.py`（批量重编号推导）、`doc_tool/application/content/refactor.py`（批量计划与回滚）、`scripts/build_docx.py` 与 `scripts/docx_common.py`（OOXML 生成）、`scripts/validate_docx.py`（新元素校验）。
- 关联代码：`doc_tool/application/content/writer.py`（备份/改动清单/回滚）、`doc_tool/domain/content_index.py`（引用索引与锚点）、`doc_tool/ui/content/workspace.py`（树刷新与确认入口）。
- 存储与数据格式：Markdown 文件与 `project.yml` 格式不变；拖拽移动会物理重命名文件并更新正文引用，`.state/` 改动清单可回滚。
- 测试影响：扩展 `scripts/tests/test_content_operations.py` 与 `test_docx_common.py`，新增批量移动计划、回滚、拖放目标判定以及链接/书签/列表/脚注构建与校验用例。
- 兼容性：旧文档仍按原逻辑构建；列表渲染为真实编号列表后，`validate_docx` 的事件流对比与模板保留校验需同步识别新结构，不把合法结构误报为失败。
