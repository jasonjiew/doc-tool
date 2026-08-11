# Proposal: 主窗口迁移 PySide6 并重构为 IDE 工作台

## Why

当前桌面应用基于 tkinter/ttk，主窗口打开项目后为「摘要、常用操作、任务进度、最近结果、事件日志、内容操作」自上而下纵向堆叠。团队成员反馈四点核心痛点：**界面观感朴素**；**真正干活的内容工作区被挤到最底部**、需滚动才能使用；**任务运行时信息分散**（进度、日志、结果分在多区块），看不清「进行到哪步、这步在做什么」；**交互不顺**（操作入口分散、布局需在区块间跳转）。团队成员熟悉 Codex 类工具「步骤清单 + 详情」的工作形式。

经与团队评审决定：将 UI 层**迁移到 PySide6（Qt）**，并把主窗口重构为「**IDE/Dock 布局 + 右侧常驻任务/结果步骤清单**」。用 Qt 的 Dock 体系让章节树、编辑器、搜索/替换/检查各就其位，同时把 Codex 式步骤清单做成右侧常驻面板，让「计划 → 执行 → 结果」在单一页面内连续可见。业务层（`domain`/`application`/`adapters`）保持不变，不引入 Qt 依赖。

## What Changes

- 将 UI 载体从 tkinter/ttk 迁移到 PySide6：`app.py` 改 `QApplication`/`QMainWindow`，`doc_tool/ui/` 全部按 Qt 组件重写；业务层与 `TaskRunner` 线程模型不动。
- 主窗口改为 IDE 骨架：菜单栏 + 顶部项目条 + 左侧章节树 Dock + 中心多标签编辑器（编辑 + 轻量预览）+ 右侧任务/结果 Dock + 底部工具面板 + 状态栏。
- 顶部项目条承载文档身份、就绪状态与高频操作（正式合并/诊断构建/校验），取代原摘要区与常用操作区；摘要细节折叠到可展开区。
- 右侧常驻「任务/结果」Dock 整合 Codex 式步骤清单：空闲显示最近结果/引导；运行显示步骤清单（图标+文字、当前步骤高亮、总体进度、已用时间）与当前步骤日志流、取消入口；终态显示结果卡片与后续操作、可展开技术详情。
- 内容操作拆分呈现：章节树在左侧 Dock；搜索/替换/重命名/检查移到底部工具面板；中心为多标签编辑器+预览。各面板业务逻辑复用现有 `application/content` 服务，不改变业务语义。
- 新建项目向导用 `QWizard` 重写。
- 统一 QSS 主题（浅色默认 + 深色可切换），高 DPI 由 Qt 原生处理，移除 `styles.py` 的 shcore hack。
- 打包升级：PyInstaller onedir 适配 PySide6，排除未用 Qt 模块控制体积；安装器体积增大属预期。
- 保留菜单、快捷键、窗口几何持久化、任务运行中关闭保护与最近项目语义。

## Capabilities

### New Capabilities

- `pyside6-app-shell`: 规定 PySide6 应用外壳——`QApplication`/`QMainWindow`、菜单栏、顶部项目条、状态栏、视图四态切换（空状态/空闲/运行/结果）、窗口生命周期与几何持久化、QSS 主题与高 DPI。
- `ide-dock-layout`: 规定 IDE/Dock 主内容布局——左侧章节树 Dock、中心多标签编辑器+预览、右侧任务/结果 Dock、底部工具面板、Dock 折叠/拖拽与内容操作拆分呈现。

### Modified Capabilities

- `work-step-list`: 更新为 PySide6 右侧 Dock 组件——步骤清单由管线阶段事件派生、当前步骤高亮、进度/已用时间、心跳回退、取消边界反馈、空闲最近结果卡片。
- `work-detail-pane`: 更新为右侧任务详情——运行流式日志+取消、终态结果卡片+后续操作+技术详情、日志折叠/待读、结果归属当前项目。

现有内容操作能力（`content-editor`、`content-search`、`content-replace`、`content-refactor`、`content-lint`、`content-references`、`content-tree-nav`）的业务需求不变，仅改变呈现位置；`internal-ui-workbench` 尚未同步为基线 spec，其布局需求被本变更的 `ide-dock-layout` 取代。

## Impact

- 主要受影响代码：`doc_tool/app.py`，`doc_tool/ui/` 全部（`main_window.py`、`content/workspace.py`、`content/*panel*.py`、`wizard.py`、`about_dialog.py`、`styles.py`、`scrollable.py`）。
- 关联代码：`doc_tool/ui/task_bridge.py`（协议不变）、`doc_tool/ui/workbench_state.py`（扩展 `WorkView`/`StepItem`/`DetailState`）、`doc_tool/application/content/*`（业务不变）。
- 测试影响：保留全部纯逻辑测试；新增步骤推导测试；更新 GUI 冒烟与人工验收清单。
- 打包影响：重新编写 PyInstaller spec 适配 PySide6 并裁剪未用模块；Inno Setup 安装器重建；不改变项目数据格式与安装位置。
- 兼容性：保留现有菜单、快捷键、CLI、项目结构与最近项目/窗口状态持久化；迁移后不再依赖 tkinter 运行时。
