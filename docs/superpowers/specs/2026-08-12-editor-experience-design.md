# 编辑器体验增强（脏标签 / 文件内查找 / 预览 / 高亮行号）

- 日期：2026-08-12
- 分支：`feat/ui-interaction-optimization`
- 状态：已批准设计（2026-08-12，四个子项全部纳入）

## 背景与目标

编辑器目前是纯 `QPlainTextEdit`：切走看不到哪个没保存、关闭脏 tab 直接丢内容、
无文件内查找、Markdown 无高亮无行号、预览不可折叠不联动。本变更分四子项补齐：

1. **脏标签提示 + 关闭确认**：tab 标题加 `●`，关闭脏 tab 弹确认。
2. **文件内 Ctrl+F 查找**：编辑器内查找高亮 + 上/下导航；与全局搜索冲突通过
   「编辑器聚焦时走文件内」解决。
3. **预览折叠/同步滚动**：预览开关按钮 + 编辑滚动时预览按标题锚点联动。
4. **Markdown 语法高亮 + 行号**：`QSyntaxHighlighter` + 行号槽。

## 1. 脏标签提示 + 关闭确认（`editor_panel.py` / `tabs_host.py`）

- `EditorPanel` 新增 `on_dirty_changed(dirty)` 回调，`_update_dirty()` 里触发
  （覆盖 load/save/rollback/编辑全路径）。
- `TabsHost.open_file` 用闭包把 `on_dirty_changed` 绑到具体 editor → 更新 tab
  标题为 `● 文件名`（脏）或 `文件名`（净）。
- `_close_tab`：editor 脏时 `QMessageBox.question` 确认（Yes 关闭 / No 保留）。

## 2. 文件内查找（`editor_panel.py`）

- 新增查找条：`QLineEdit` + 上/下按钮 + 关闭；`QPlainTextEdit.extraSelections`
  高亮全部命中，`find()` 导航当前命中。
- `focus_find()` 暴露给主窗口：`Ctrl+F` 时若编辑器聚焦 → 聚焦查找条，否则走全局搜索
  （`main_window._on_content_search` 判断焦点所在）。

## 3. 预览折叠/同步滚动（`editor_panel.py`）

- 工具栏加「预览」开关按钮：折叠 = `preview_frame.hide()` + 按钮状态。
- 编辑滚动时 `scrollValueChanged` → 按光标所在标题在预览里 `scrollToAnchor`
  （best-effort，预览滚动不反向联动）。

## 4. Markdown 高亮 + 行号（新 `editor_highlight.py` / `editor_panel.py`）

- `MarkdownHighlighter(QSyntaxHighlighter)`：标题（#）、粗体、行内代码、代码块、
  表格行、链接、列表标记。
- 行号槽：`QPlainTextEdit` 左侧 `LineNumberArea`（`QWidget` 自绘），随编辑器
  `blockCountChanged`/`updateRequest` 重绘，首行与编辑器同步滚动。

## 5. 测试

- ① 脏标签：编辑 → tab 有 ●、保存 → 无 ●；关闭脏 tab 拒绝不关、确认关闭。
- ② 查找：`focus_find` 聚焦；`extraSelections` 命中计数。
- ③ 预览：开关隐藏/显示；滚动触发 `scrollToAnchor`（可 patch 断言）。
- ④ 高亮：`QSyntaxHighlighter` 对标题/代码块设置前景格式；行号区宽度随行数变化。
- 全量 128 + 57 回归。

## 6. 范围控制

- 编辑器内替换（Ctrl+H）、拼写检查、自动保存、多光标 → 留后续。
- 预览与编辑双向滚动（预览滚动反向联动编辑器）不做，只做编辑→预览单向。
