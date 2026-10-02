## Why

研发需求、接口、测试用例中大量使用普通表格，当前只能插入 Markdown 骨架和对齐文本。提供表格网格编辑与表格粘贴，能减少手工操作，并提高导入后继续维护文档的效率。

## What Changes

- 为普通 Markdown 管道表格提供网格编辑、行列增删移动、对齐和键盘操作。
- 支持显式“粘贴为表格”：读取 TSV/普通管道表格，预览后插入，保留文本值及前导零。
- 在原编辑缓冲中一次应用、一次撤销；编辑过程中原片段变化时保留待应用内容供重新定位。
- 沿用普通表格预览/导出和 CORE 版式；复杂原生 Word 表格继续使用既有保留方式。

## Capabilities

### New Capabilities

- `structured-table-authoring`: 普通表格网格编辑、序列化和缓冲应用。
- `clipboard-table-intake`: TSV/Markdown 表格显式粘贴、文本保留和来源反馈。

### Modified Capabilities

无。普通 Markdown 文件仍为内容唯一源；不改变复杂表格保留契约。

## Impact

涉及 `ui/content/editor_panel.py`、新增表格对话框、`application/content/table_format.py`、普通表格解析与预览；对接 CORE 导出接口。无新云服务，不执行单元格公式。5 批/20 项，本次只规划。
