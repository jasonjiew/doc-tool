## 1. 编辑器增强·服务层（先测）

- [x] 1.1 新增 `doc_tool/application/content/spellcheck.py`：`SpellChecker(builtin_words, user_words)`，英文 token 化（跳过围栏代码块/中文）、内置词典 + 用户词典、编辑距离 ≤2 建议；单测覆盖
- [x] 1.2 打包内置英文词典资源 `resources/dict/en_words.txt`（约 5 万常用词）；用户词典读写 `QStandardPaths.AppDataLocation/user_dict.txt`
- [x] 1.3 新增 `doc_tool/application/content/snippets.py`：`Snippet(trigger, description, body)` 与 `SnippetStore`（`snippets.json` 原子读写）；占位符 `${N:default}` 解析；单测覆盖

## 2. 编辑器增强·UI 接线

- [x] 2.1 `editor_panel` 查找条新增替换行：替换一个/全部替换/关闭；全部替换用 `beginEditBlock` 包成单个撤销单元；`Ctrl+H` 经 `tabs_host` 绑定
- [x] 2.2 拼写检查 UI：`_LineNumberedEdit` 用 `ExtraSelections` 画红色波浪线（按可见行 + 去抖重扫）；右键菜单候选建议与「加入词典」
- [x] 2.3 片段 UI：片段管理器对话框（增删改 + 预览）；插入后占位符高亮、`Tab` 跳转占位符
- [x] 2.4 Markdown 工具栏：标题/粗体/斜体/行内代码/列表/引用/表格/链接/图片按钮；`wrap_selection`/`insert_template` 统一收口，操作进撤销栈
- [x] 2.5 预览双向定位：`preview.render_markdown_html` 为块生成 `line-N` 锚点；`editor_panel` 接 `anchorClicked`（`line-N` → `highlight_line` + 临时高亮；http 链接 → 系统浏览器）；编辑→预览按标题滚动保留，预览隐藏时短路

## 3. 图片资源管理

- [x] 3.1 新增 `doc_tool/application/content/asset_manager.py`：`next_image_name`（按类型独立 `img_NNNN`，扫描 images 目录 + `image-map.yml` 计数器）、`import_image_data`（写文件 + PIL 验图 + 尺寸）、`scan_unused`（复用 `ReferenceScanner` 差集）、`list_missing`（悬空图片引用）；单测覆盖
- [x] 3.2 `_LineNumberedEdit` 重写 `insertFromMimeData`（剪贴板含图片 → 资源导入并插入引用）与 `dropEvent`（拖入图片文件）；只读项目拒绝
- [x] 3.3 图片资源面板（`panels_host` 新 tab「图片」）：未使用列表（勾选清理 → `writer.delete_file` 移回收站，改动面板可回滚）+ 缺失列表（重新指向已有资源 / 删除引用行，经 `ContentWriter` 写回）
- [x] 3.4 确认 `writer.delete_file` 对 `assets/` 路径的回收站语义可用，必要时补路径白名单校验

## 4. Mermaid 图形工作台

- [x] 4.1 新增 `doc_tool/application/content/mermaid.py`：`extract_blocks`（```mermaid 围栏 + 裸 flowchart/sequenceDiagram 段落）、`validate`（flowchart/sequenceDiagram 子集，错误带行号）、`render`（mermaid-cli → 内置子集渲染器 SVG → QtSvg 栅格化 PNG，失败返回错误）；单测覆盖
- [x] 4.2 `MermaidDialog`：源码编辑 + 语法错误列表（点击定位）+ 实时预览（去抖）+ 「插入 Word」「转换并替换源码」
- [x] 4.3 入口接线：编辑器工具栏 Mermaid 按钮 + 右键「用 Mermaid 工作台编辑」；导出写 `assets/<类型>/images/mermaid_NNNN.png` 并插入 `![图](images/... =宽x高)`
- [x] 4.4 阅读预览：`preview.render_markdown_html` 对 ```mermaid 围栏块渲染图（失败显示错误占位，无后端时回退代码块）
- [x] 4.5 批量转换：当前文档内既有裸 flowchart/sequenceDiagram 源码逐个渲染为图片引用，汇总成功/失败

## 5. 自动化测试

- [x] 5.1 拼写单测：英文命中/中文跳过/代码块跳过/用户词典/建议候选
- [x] 5.2 片段单测：增删改、持久化回读、占位符解析与 Tab 跳转序列
- [x] 5.3 图片服务单测：命名唯一、导入写文件+尺寸、未使用差集、缺失列表；粘贴/拖放离屏测试（含只读拒绝）
- [x] 5.4 Mermaid 单测：围栏/裸源码识别、语法错误按行、子集渲染成功/失败、后端不可用错误、批量转换
- [x] 5.5 编辑器离屏测试：替换单个/全部/撤销、工具栏包裹、预览点击定位、外部链接不触发定位
- [ ] 5.6 回归：`scripts/tests/run_tests.py` 全绿，既有内容操作与 GUI 测试不受影响

## 6. 人工验收与文档

- [ ] 6.1 手动验收：Ctrl+H 替换（单个/全部/撤销）、拼写检查（红线/建议/加入词典）、片段插入与 Tab 跳转、Markdown 工具栏
- [ ] 6.2 手动验收：预览双向定位（编辑滚动→预览、预览点击→编辑），长文档下定位精确
- [ ] 6.3 手动验收：粘贴截图/拖入图片生成资源并插入引用，预览可见、构建 Word 尺寸正确；未使用资源清理后改动面板可回滚；缺失引用修复
- [ ] 6.4 手动验收：Mermaid 语法检查/实时预览/一键插入 Word/批量转换既有 `content/design/` 裸源码，构建+校验通过
- [x] 6.5 更新 `docs/roadmap.md` 标注「P1-C 编辑器增强」「P1-D 图片与资源管理器」「第一批建议 3 Mermaid 图形工作台」对应本变更
