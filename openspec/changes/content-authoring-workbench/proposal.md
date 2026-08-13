## Why

编辑器已具备 Ctrl+F 文件内查找、单向编辑→预览滚动同步、Markdown 高亮与行号，但缺少对标 Word 的常用创作能力：文件内替换（Ctrl+H）、拼写检查、代码片段与 Markdown 格式化工具栏均不可用，预览只能由编辑驱动、无法从预览点击回定位。图片只能靠外部粘贴到资源目录再手写引用，资源目录随导入积累无清理入口；而当前 `content/design/` 下已有 47 处直接把 `flowchart`/`sequenceDiagram` 源码存为正文段落，构建器只把它当普通文本输出，Mermaid 图形从未真正渲染进 Word——这是最常见的保真缺口。

## What Changes

- **编辑器增强**：文件内替换条（Ctrl+H，单个/全部替换，进入撤销栈）、拼写检查（内置英文词典 + 用户词典，红线标注、右键建议，无新运行时依赖）、代码片段（触发词 + 占位符模板，Tab 跳转占位）、常用 Markdown 格式化工具栏、预览双向定位（编辑滚动→预览滚动、预览点击→编辑定位）。不重复「全部保存」（已在 workbench-safety-recovery）。
- **图片资源管理**：编辑器中粘贴截图/拖入图片，自动唯一命名并复制到 `assets/<类型>/images/`，插入 `![说明](images/<名> =宽x高)` 引用（像素尺寸后缀）；提供未使用资源清理（移入回收站可回滚）与缺失资源修复（重新指向或删除引用）。
- **Mermaid 图形工作台**：识别 ```mermaid 围栏块与历史遗留裸 `flowchart`/`sequenceDiagram` 源码；语法检查（按行报错）、实时预览、一键渲染为 SVG/PNG 保存到资源目录并插入 Word（图片引用）；批量把既有裸源码图转换为图片引用。
- 本变更不改变图片引用语法与构建语义（`=宽x高` 后缀、悬空检测均复用既有实现）。**无破坏性变更**。

## Capabilities

### New Capabilities

- `editor-enhancements`: 编辑器创作增强——文件内替换 Ctrl+H、拼写检查、代码片段、常用 Markdown 工具栏、预览双向定位（编辑滚动→预览、预览点击→编辑）。
- `image-asset-manager`: 图片资源生命周期管理——粘贴/拖入自动命名入资源目录、插入带尺寸引用、未使用资源清理与缺失资源修复。
- `mermaid-diagram-workbench`: Mermaid 图形工作台——围栏块/裸源码识别、语法检查、实时预览、一键转 SVG/PNG 并插入 Word，含批量转换既有源码图。

### Modified Capabilities

无。本变更新增的能力（编辑器增强、图片资源管理、Mermaid 工作台）由各自的 New 能力规格承载；`content-editor` 既有需求语义不变，不产生规格级修改。

## Impact

- **代码**：`doc_tool/ui/content/editor_panel.py`（替换条、工具栏、预览双向定位、粘贴/拖放钩子）、`doc_tool/ui/content/editor_highlight.py`（拼写检查下划线复用高亮器或 ExtraSelections）、`doc_tool/ui/content/tabs_host.py`（快捷键接线）；新增 `doc_tool/application/content/spellcheck.py`、`snippets.py`、`asset_manager.py`、`mermaid.py`（纯服务，先测）；`doc_tool/application/content/preview.py`（Mermaid 围栏块渲染、块级锚点供预览点击定位）；新增图片资源面板与 Mermaid 工作台对话框；`scripts/build_docx.py` 无需改动（Mermaid 以图片引用进入既有图片构建路径）。
- **存储**：新增用户级配置（代码片段 `snippets.json`、用户词典）与应用内置词典资源；项目 `assets/<类型>/images/` 新增 Mermaid 生成图与粘贴图；未使用清理沿用 `writer.delete_file` 回收站语义（改动面板可回滚）。
- **测试**：扩展 `scripts/tests/test_content_operations.py` / `test_gui_services.py`；新增拼写/片段/资源管理/Mermaid 纯服务单测与离屏 UI 测试。
- **兼容性**：无破坏性变更；图片引用语法与构建语义不变；Mermaid 仅新增识别与转换路径，不改既有正文渲染。
