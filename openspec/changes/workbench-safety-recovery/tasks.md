## 1. 草稿存储与统一确认基础（纯逻辑，先测）

- [x] 1.1 新增 `doc_tool/application/content/autosave.py`：`AutoSaveStore(state_dir)`，实现 `write/clear/clear_all/list_drafts/read`，复用 `atomic_write` 与 `_resolve_inside`，越界 rel_path 拒绝
- [x] 1.2 新增纯函数 `collect_unsaved(editors) -> List[str]`：返回有未保存编辑的 rel_path 列表（`tabs_host` 提供编辑器集合）
- [x] 1.3 新增纯枚举 `UnsavedChoice = SAVE | DISCARD | CANCEL` 与 `resolve_unsaved_choice(rel_paths, context) -> UnsavedChoice` 决策函数（可注入，供离屏测试替换真实对话框）
- [x] 1.4 新增会话状态纯模型与读写：`workspace_state.py` 的 `SessionState`（Dock 显隐/布局、主题、打开标签、当前文件、预览开关、滚动位置）与 `.state/workspace.json` 原子读写
- [x] 1.5 单测覆盖：`AutoSaveStore` 读写/覆盖/清除/越界拒绝、`collect_unsaved` 只收脏标签、决策函数三态映射、`SessionState` 序列化/缺省/损坏回退

## 2. 编辑器与标签宿主：全部保存 + 草稿写入/清除 + 草稿加载

- [x] 2.1 `TabsHost.save_all()`：遍历脏标签逐个 `save()`，汇总失败 rel_path 返回
- [x] 2.2 `EditorPanel` 新增独立单发草稿定时器（约 1500ms）：`_on_edit` 置脏时重启，触发且 `writable` 时 `autosave.write(rel_path, 当前文本)`
- [x] 2.3 `EditorPanel.save()` 成功后 `autosave.clear(rel_path)`；只读项目不写草稿
- [x] 2.4 新增草稿加载路径（`TabsHost.open_draft(rel_path, text)` 或 `EditorPanel.load_draft`）：加载后标记脏、状态栏显示「● 恢复自草稿」，正式文件不被写入
- [x] 2.5 菜单新增「保存全部」项与 `Ctrl+Shift+S` 快捷键，接入 `save_all`

## 3. 破坏性入口接线：退出 / 切项目 / 删除 / 重命名

- [x] 3.1 `main_window.closeEvent`：保留运行中任务逻辑，新增未保存检查——「保存」→ `save_all()` 后继续退出；「不保存」→ 直接退出；「取消」→ `event.ignore()`
- [x] 3.2 项目切换拦截：在 `_open_project_path` / `show_project` 触发 `_init_content_workspace` 前检查脏标签，取消则中止打开新项目
- [x] 3.3 `workspace._on_delete_file`：目标文件脏时确认（放弃/取消）；取消中止删除
- [x] 3.4 `workspace._on_rename_file`：目标文件脏时确认（先保存/放弃/取消）；「先保存」先 `save()` 原路径再重命名
- [x] 3.5 删除文件时清除该文件草稿（`.state/autosave/` 中对应条目）

## 4. 崩溃恢复接线

- [x] 4.1 `ContentWorkspace._on_index_done` 后调用 `autosave.list_drafts()`；非空弹「恢复 / 忽略」
- [x] 4.2 「恢复」：逐草稿走 `open_draft` 加载进编辑器并保持脏状态；正式 Markdown 不被覆盖
- [x] 4.3 「忽略」：不加载、不删除草稿，正式内容保持原状

## 5. 会话状态持久化与恢复

- [x] 5.1 `TabsHost` 提供打开标签快照（rel_path 列表、当前文件、每标签滚动位置）；`EditorPanel` 提供预览开关/滚动位置读写
- [x] 5.2 关闭项目/退出时收集并写入 `.state/workspace.json`（Dock 显隐/布局来自 `main_window`，主题来自 `styles`）
- [x] 5.3 重新打开项目时读取会话并按序恢复：Dock 布局/主题 → 打开标签 → 当前文件 → 滚动位置；缺失文件跳过不阻断
- [x] 5.4 脏标签恢复衔接：会话中曾有未保存的标签经 `autosave` 草稿恢复为脏状态（复用 2.4 草稿加载路径）

## 6. 自动化测试

- [x] 6.1 离屏测试（决策注入版）：退出三选、切项目三选、删除放弃/取消、重命名先保存/放弃/取消
- [x] 6.2 草稿生命周期测试：编辑去抖后写入、保存后清除、只读不写、草稿不影响索引/构建/校验
- [x] 6.3 崩溃恢复测试：预置 `.state/autosave/` 草稿，打开项目提示恢复/忽略，恢复后为脏状态且正式文件未变
- [x] 6.4 会话恢复测试：写入会话 → 重开 → 标签/当前文件/布局/主题/滚动位置恢复；缺失文件跳过；损坏 JSON 回退默认
- [x] 6.5 回归：现有内容操作与 GUI 测试（`run_tests.py`）全绿（`test_gui_services`/`test_content_operations`/`test_safety_recovery` 等全部通过；`test_validator_negative`/`test_iteration_scenarios` 为本机 DLP 加密 PNG 的环境问题，非本变更回归）

## 7. 人工验收与文档

- [ ] 7.1 手动验收：退出/切项目/删除/重命名各分支、全部保存、只读项目、草稿恢复后显式保存（清单已写入 `scripts/tests/test_safety_recovery.py` 末尾，需桌面会话执行）
- [ ] 7.2 手动验收：会话保存→重开恢复（含脏标签从草稿恢复、缺失文件跳过）（同上，桌面会话执行）
- [x] 7.3 更新 `docs/roadmap.md` 标注「计划 1 工作台安全与恢复」对应本变更
