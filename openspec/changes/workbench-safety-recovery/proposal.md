## Why

当前编辑器已具备脏标签与关闭确认（`tabs_host`），但**退出应用、切换项目、删除/重命名文件时没有统一的未保存保护**：`main_window.closeEvent` 只处理运行中任务，`workspace` 切换项目直接 `shutdown`+`deleteLater` 销毁旧工作区，删除/重命名文件会静默关闭标签。编辑内容一旦在崩溃或误操作中丢失即不可恢复——对 QMS 文档维护，未保存的章节内容是几小时的工作量。同时缺少自动草稿，崩溃后无任何恢复路径；工作区现场（打开的标签、布局、滚动位置）也不在项目重开后恢复，中断工作后难以续接。

## What Changes

- **退出 / 切换项目的未保存保护**：存在未保存编辑时弹出「保存 / 不保存 / 取消」，统一处理应用退出与项目切换两个入口；取消则中断原操作。
- **删除 / 重命名文件的未保存保护**：目标文件有未保存编辑时先弹确认，避免静默丢弃；删除/重命名失败时编辑内容不丢失。
- **全部保存**：新增「全部保存」动作，一次性保存全部已打开且有未保存更改的标签页。
- **自动草稿与崩溃恢复**：编辑器内容周期/触发式写入项目 `.state/autosave/`，应用重启或重新打开项目时提示恢复；**不静默覆盖正式 Markdown**——恢复始终经用户确认，且草稿恢复后仍为脏状态需显式保存。
- **工作区会话恢复**：保存 Dock 布局、主题、打开标签、当前文件、预览开关与滚动位置，重新打开项目后恢复工作区现场。

## Capabilities

### New Capabilities

- `content-unsaved-protection`: 定义编辑器未保存内容的保护与恢复语义——退出/切项目/删除·重命名前的保存确认、全部保存、自动草稿落盘与崩溃后的显式恢复。
- `workspace-session-restore`: 定义工作区会话状态的持久化与恢复语义——Dock 布局、主题、打开标签、当前文件、预览开关与滚动位置在项目重开后的恢复。

### Modified Capabilities

无。`content-editor` 的编辑/预览/备份语义不变；本变更新增独立的保护与恢复能力规格。

## Impact

- **代码**：`doc_tool/ui/main_window.py`（退出/切项目接入确认、会话状态读写）、`doc_tool/ui/content/workspace.py`（删除/重命名/切项目前确认、标签/布局收集）、`doc_tool/ui/content/tabs_host.py`（全部保存、脏标签收集、统一保存确认、打开标签快照）、`doc_tool/ui/content/editor_panel.py`（草稿写入/恢复钩子、预览开关/滚动位置快照）、`doc_tool/application/content/writer.py`（草稿与正式写入的隔离）、`doc_tool/ui/workbench_state.py`（会话状态模型）、新增草稿/会话恢复服务与 `ContentSnapshot`/`ChangeManifest` 复用。
- **存储**：项目 `.state/autosave/` 新增目录，保存按 `rel_path` 镜像的草稿副本；`.state/workspace.json` 保存会话状态；不改变 `content_changes.json`、`.md.bak`、正式 Markdown 的现有格式。
- **测试**：扩展 `scripts/tests/test_content_operations.py` / 新增草稿恢复与会话恢复测试；UI 确认流程沿用现有离屏测试模式。
- **兼容性**：无破坏性变更；现有保存/备份/回滚语义不变，草稿与会话目录对构建/校验不可见。
