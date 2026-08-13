## Context

主链路已完成，编辑器具备脏标签、单标签关闭确认、外部修改检测与单次保存回滚（`tabs_host` / `editor_panel`）。但四个破坏性入口目前会静默丢弃未保存内容：应用退出（`main_window.closeEvent` 只处理运行中任务）、项目切换（`workspace.shutdown` + `deleteLater` 直接销毁旧工作区）、文件删除与重命名（写回后直接关闭标签）。也缺少自动草稿，崩溃后无恢复路径。

复用基础：`ContentWriter` 已统一写入口（备份 + 原子写 + 改动清单）并持有 `.state/` 目录；`ContentSnapshot` / `ChangeManifest` 已建立 `.state/` 下 JSON 持久化与原子写的既有模式（`TermStore.save` 同套路）。本设计在其上新增草稿存储与统一确认，不改变正式写入语义。

## Goals / Non-Goals

**Goals:**

- 统一「保存 / 不保存 / 取消」确认，覆盖退出、切项目、删除、重命名四个入口，取消必须能中止原操作。
- 提供「全部保存」，并被「退出时保存」「切换时保存」复用。
- 未保存编辑内容经去抖写入 `.state/autosave/`，崩溃后打开项目可显式恢复。
- 草稿与正式 Markdown 严格隔离：草稿不参与索引/构建/校验，恢复不静默覆盖正式内容。
- 保持可测试：草稿存储与脏标签收集为无 Qt 纯服务/纯函数；UI 确认流程沿用现有离屏测试模式。
- 工作区现场（Dock 布局/主题/打开标签/当前文件/预览开关/滚动位置）在项目重开后恢复，且与未保存保护衔接（脏标签经草稿恢复）。

**Non-Goals:**

- 不改正式保存/备份/回滚语义，不改 `content_changes.json`、`.md.bak` 格式。
- 不做跨机器/跨会话的多人草稿同步。
- 不做自动恢复（用户显式确认才恢复），不做草稿版本历史。
- 会话恢复不做跨项目串扰：每次恢复仅读当前项目自己的 `.state/workspace.json`。
- 不新增运行时依赖。

## Decisions

### 1. 统一的保存确认：纯状态收集 + 薄 UI 封装
新增纯函数 `collect_unsaved(editors) -> List[str]`（返回有未保存编辑的 rel_path 列表，`tabs_host` 提供编辑器集合），以及 UI 层 `confirm_unsaved(rel_paths, context) -> 保存|不保存|取消`（`QMessageBox` 三按钮）。四个入口都先收集脏标签，非空才弹确认，按结果分发：

- 退出：`closeEvent` 中先查运行中任务（现有逻辑），再查脏标签；「保存」→ `save_all()` → 继续退出；「不保存」→ 直接退出；「取消」→ `event.ignore()`。
- 切项目：在 `workspace.shutdown()` 之前拦截（`main_window._open_project_path` / `show_project` 入口）；「保存」→ `save_all()` 再重建工作区；「取消」→ 中止打开新项目。
- 删除：`workspace._on_delete_file` 中，目标文件脏时确认；「放弃」→ 继续删除（文件入回收站，改动面板可回滚恢复）；「取消」→ 中止。删除不提供「保存」（内容随文件进入回收站副本）。
- 重命名：`workspace._on_rename_file` 中，目标文件脏时确认；「先保存」→ `editor.save()` 到原路径再重命名；「放弃」→ 直接重命名；「取消」→ 中止。

**Alternatives considered:**

- 每个入口各自弹框判断 → 逻辑重复且易漂移；统一收集 + 统一确认保证四入口一致。
- 仅禁用破坏性操作直到保存 → 违背现有“随时可删除/切换”的交互，且引入额外状态。

### 2. 全部保存：`TabsHost.save_all()`
遍历 `_editors`，对 `is_dirty()` 的编辑器调用 `save()`，汇总失败项提示。新增菜单项「保存全部」与快捷键 `Ctrl+Shift+S`；「退出/切换时保存」直接复用该方法。

### 3. 草稿存储：`AutoSaveStore`（application/content 层纯服务）
新建 `doc_tool/application/content/autosave.py`，持 `state_dir`：

- `write(rel_path, text)`：原子写 `.state/autosave/<rel_path>`（复用 `atomic_write`，覆盖即只保留最近一份）。
- `clear(rel_path)` / `clear_all()` / `list_drafts()` / `read(rel_path)`。
- 越界 rel_path 与 `write_text` 一样拒绝（`_resolve_inside` 复用）。

`.state/` 在 `content_root` 之外，内容索引 `discover_files` 只扫 `content_root`，草稿天然不被索引/构建/校验收录，无需额外排除逻辑。

### 4. 草稿写入触发与清除（EditorPanel）
`EditorPanel` 已有 300ms 预览去抖；新增独立单发 `_draft_timer`（约 1500ms）：`_on_edit` 置脏时重启，触发后若 `writable` 且脏则 `autosave.write(rel_path, 当前文本)`。保存成功（`save()`）后 `autosave.clear(rel_path)`，避免草稿与正式内容混淆。只读项目不写草稿。删除文件时同时 `clear` 该文件草稿（文件已入回收站，草稿无意义）。

**Alternatives considered:**

- 每次击键都写 → 频繁磁盘写；1500ms 去抖平衡丢失窗口与开销。
- 复用 300ms 预览定时器 → 草稿写入频率过高；独立定时器可单独调优。

### 6. 会话状态：`.state/workspace.json` 快照 + 顺序恢复
新增纯模型 `SessionState`（Dock 显隐/布局、主题、打开标签、当前文件、预览开关、每标签滚动位置），与草稿同存 `.state/`，沿用 `TermStore`/`ChangeManifest` 的 JSON 原子写模式（`.tmp` + `os.replace`）。

- 收集：关闭项目/退出时由 `main_window`（Dock 布局/主题）+ `tabs_host`（标签列表/当前文件/滚动位置）+ `editor_panel`（预览开关）汇总写入。
- 恢复：打开项目、索引就绪后读取，按序「Dock 布局/主题 → 打开标签 → 当前文件 → 滚动位置」恢复；文件缺失跳过不阻断。
- 衔接未保存保护：会话中曾有未保存的标签，若 `.state/autosave/` 有草稿则以脏状态载入（复用决策 5 的草稿加载路径），正式文件不被覆盖。

**Alternatives considered:**

- 复用 `project.yml` 存会话 → 会话是瞬时 UI 状态，污染项目元数据且随项目分发，不合适。
- 应用级全局会话文件 → 多项目并存会串扰；按项目 `.state/workspace.json` 隔离更安全。
- 自动恢复即视为已保存 → 用户会误以为已落盘；恢复保持脏状态、要求显式保存更安全。

### 5. 崩溃恢复：索引就绪后检测 + 显式确认
`ContentWorkspace._on_index_done` 之后调用 `AutoSaveStore.list_drafts()`；非空则弹「存在 N 个未保存草稿，是否恢复？」「恢复 / 忽略」。

- 恢复：为每个草稿用 `open_file(rel_path, 草稿文本)` 打开并保持脏状态（新增 `open_file(rel_path, text, draft=True)` 或 `tabs_host.open_draft`，加载后标记 dirty、`_dirty_label` 显示「● 恢复自草稿」）。正式 Markdown 文件不被写入，用户显式保存才落盘。
- 忽略：不加载，草稿保留在 `.state/autosave/`（不静默删除）。

**Alternatives considered:**

- 打开项目时自动覆盖正式文件 → 违反“不静默覆盖”且不可逆，明确排除。
- 恢复后直接视为已保存 → 用户可能误以为已落盘；恢复内容保持脏状态要求显式保存，更安全。

## Risks / Trade-offs

- [草稿与正式内容并存，用户混淆] → 保存后即清除草稿；恢复入口始终带「未保存/恢复自草稿」标记；草稿目录对构建不可见。
- [「全部保存」中某个文件保存失败] → 汇总失败 rel_path 提示，不中断其余标签，用户可重试（规格已覆盖）。
- [切项目确认拦截点漏网导致旧工作区先被销毁] → 把拦截放在 `_init_content_workspace` 调用链最外层（`_open_project_path`），并在 `show_project` 前断言无脏标签；离屏测试覆盖。
- [草稿残留占用磁盘] → 每文件仅最近一份、保存即清除；可在改动面板后续增加「清理草稿」入口（非本变更必须）。
- [离屏测试中 QMessageBox 阻塞] → 确认流程抽成可注入的决策函数，测试注入预设返回值，不弹真实对话框。

## Migration Plan

1. 新增 `AutoSaveStore` + `collect_unsaved` + `confirm_unsaved`（纯逻辑，先测）。
2. `TabsHost` 增加 `save_all`、草稿加载路径；`EditorPanel` 增加草稿定时写入与清除。
3. `main_window` 接入退出/切项目确认；`workspace` 接入删除/重命名确认。
4. `ContentWorkspace` 接入启动草稿检测与恢复。
5. 补齐离屏测试（决策注入版）与草稿存储单测；回归现有内容操作与 GUI 测试。
6. 手动验收：退出/切项目/删除/重命名各三选分支、全部保存、崩溃模拟（写草稿后重启恢复）。

回滚：本变更只新增 `.state/autosave/` 与确认流程，不改变正式文件与清单格式；移除确认接线即可回退，无需数据迁移。

## Open Questions

- 「全部保存」快捷键是否与既有 `Ctrl+1..5` 冲突（不冲突，使用 `Ctrl+Shift+S`）待人工验收确认。
- 草稿去抖窗口取 1500ms 是否在超大文档（几百 KB）编辑时足够，需实测调整。
- 草稿是否需要「清理全部」入口并放入改动面板，还是仅依赖保存即清除；倾向后者，非本变更必须。
