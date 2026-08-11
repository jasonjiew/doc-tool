# Design: PySide6 IDE 工作台

## Context

当前 Windows 桌面应用基于 tkinter/ttk 建立单窗口界面。经过 `optimize-internal-ui-workbench` 迭代后，主窗口已有空状态、可执行状态摘要、常用操作区、阶段进度、持久结果区、可折叠日志和内容操作工作区（章节树 + 编辑器 + 搜索/替换/重命名/检查标签页）。任务通过 `task_bridge.py` 的 `TaskRunner` 在后台线程执行，以 `TaskEvent`（stage/status）与进度回调把阶段事件推回 UI；`workbench_state.py` 提供纯逻辑的展示状态与 `derive_workbench_state`，菜单和首屏按钮共享同一状态来源。

主要问题：主内容区仍是「纵向堆叠」——摘要、操作、进度、结果、日志、内容工作区自上而下排列。团队评审确认四点痛点：界面观感朴素；内容工作区被挤到最底部；任务运行时需在多区块间跳转才能拼出「进行到哪步、这步在做什么」；交互不顺。团队成员熟悉 Codex 类工具「步骤清单 + 详情」的工作形式。

本变更把 UI 层迁移到 PySide6（Qt Widgets），并将主窗口重构为「IDE/Dock + 右侧常驻任务/结果步骤清单」。必须保持项目格式、文档管线、Word 自动化、安全取消、原子发布和日志脱敏语义不变，业务层（`domain`/`application`/`adapters`）不引入 Qt 依赖，兼容源码与 PyInstaller 冻结运行。

## Goals / Non-Goals

**Goals:**

- 将 UI 载体从 tkinter/ttk 迁移到 PySide6，业务层保持不变。
- 主窗口改为 IDE/Dock 骨架：顶部项目条 + 左侧章节树 Dock + 中心多标签编辑器/预览 + 右侧任务/结果 Dock + 底部工具面板 + 状态栏。
- 右侧任务/结果 Dock 整合 Codex 式步骤清单：空闲显示最近结果/引导；运行显示步骤清单+日志流+取消；终态显示结果卡片+后续操作+技术详情。
- 内容操作拆分呈现（左树、底部面板、中心编辑器），业务逻辑复用 `application/content` 服务。
- 新建项目向导用 `QWizard` 重写。
- 统一 QSS 主题与 Qt 原生高 DPI，观感现代化。
- 打包适配 PySide6 并裁剪体积；保留菜单、快捷键、窗口生命周期、关闭保护与项目数据格式。

**Non-Goals:**

- 不迁移到 Electron/WebView/Web UI，采用 Qt Widgets（非 QML）。
- 不引入通用多页面路由体系、复杂动画或第三方 Qt 主题库。
- 不改变 `project.yml`、项目目录、最近项目、窗口状态持久化格式。
- 不修改导入、校验、构建、Word 刷新、原子发布、项目锁和安全取消的业务语义。
- 不重写 content 业务逻辑，仅改变呈现位置与 UI 组件。
- 不在本变更中改变新建项目向导的业务步骤与规则（仅换组件）。
- 不新增与任务事件并行的进度协议或虚假百分比。

## Decisions

### 1. 采用 PySide6 迁移整个 UI 层

将 `doc_tool/ui/` 从 tkinter/ttk 重写为 PySide6（Qt Widgets）：`app.py` 创建 `QApplication`，主窗口为 `QMainWindow`，对话框为 `QDialog`/`QWizard`。业务层与 `TaskRunner` 线程模型保持依赖关系不变，只替换呈现与输入层。高 DPI 由 Qt 原生处理（`AA_EnableHighDpiScaling` + per-monitor），移除 `styles.py` 的 shcore hack；`scrollable.py` 由 Qt 原生滚动取代。

选择 Qt Widgets 而非 QML/Web：团队无 QML/前端背景，Qt Widgets 与现有 Python 服务最容易对接，控件能力（树、标签页、Dock、富文本）远强于 ttk，且 PyInstaller 支持成熟。接受安装体积增大与首次启动变慢的代价。

**Alternatives considered:**

- 继续 tkinter/ttk：观感与组件能力有天花板，无法根治「观感朴素」痛点。
- Web UI/Electron：架构改动与打包复杂度最高，对内部工具收益不足。

### 2. 主窗口为「项目条 + 三个 Dock + 底部面板」IDE 骨架

```
菜单栏：文件 │ 操作 │ 内容 │ 工具 │ 帮助
项目条：文档名 · 类型 · 版本 · 就绪状态 │ [正式合并][诊断构建][校验]
├ 左侧 Dock：章节树（可折叠/可拖拽）
├ 中心：多标签编辑器 + 预览
├ 右侧 Dock：任务 / 结果（步骤清单、日志流、结果卡片）
└ 底部面板：[检查/问题] [搜索] [替换] [重命名/重编号]
状态栏：就绪 · 锁状态
```

所有 Dock 可折叠、可拖拽。视图状态沿用 `derive_workbench_state` 的 `empty/idle/running/result` 四态，映射到中央区与右侧 Dock 的切换。顶部项目条取代原「项目与就绪状态」摘要区和「常用操作」区；摘要细节（编号、指纹、最后构建、路径）折叠到可展开区。菜单、快捷键、窗口几何持久化与关闭保护沿用现有语义，并共享同一 `derive_workbench_state` 状态来源。

**Alternatives considered:**

- 纯 Codex 左右分栏（原 `codex-work-layout` 方向）：步骤清单位置好，但编辑/搜索等次要能力挤在右侧，编辑体验弱于 IDE。
- 仅重排纵向区块顺序：无法根治编辑区被挤压与任务过程分散。
- 多个顶层窗口：增加任务、项目与关闭行为的一致性风险。

### 3. 右侧「任务/结果」Dock 整合步骤清单（Codex 工作形式）

右侧常驻 Dock 三态：

- **空闲**：最近结果卡片（成功提供打开产物/目录/报告；失败显示原因与建议）或引导卡片（校验/诊断构建入口）。
- **运行**：步骤清单（①章节预检→②构建 DOCX→③前校验→④Word 刷新；图标+文字、当前步骤高亮、总体进度、已用时间）+ 当前步骤日志流 + 取消入口。
- **终态**：结果卡片 + 适用后续操作，失败时技术详情（错误码/阶段/异常摘要/日志路径）可展开；步骤清单保留终态（成功/失败/跳过/取消）。

步骤清单由 `stage_percent_table()`（按起点排序得到阶段顺序）与 `PIPELINE_STAGE_LABELS`（中文标签）这一单一数据源派生，不复制阶段表；每个步骤状态由已收到的 `stage/status` 事件推导（`started`→进行中、`succeeded`→成功、`skipped`→跳过、`failed`→失败、取消/超时→未执行保持待处理且当前步骤标记取消）。心跳类任务（独立校验、内容索引构建）显示单个「进行中」步骤 + 已用时间，不伪造百分比。

**Alternatives considered:**

- 步骤清单仅任务运行时弹出：空闲时无法持续看到结果与引导。
- 步骤清单放底部面板：与编辑区抢空间，弱化「计划→执行→结果」的连续可见。

### 4. 中心多标签编辑器 + 轻量预览

中心区为多标签编辑器：每个打开的章节一个标签页（`QPlainTextEdit` 编辑 + 轻量 Markdown 预览），可同时打开多文件切换编辑。保存继续走 `ContentWriter`（备份 + 原子写），保存后失效重建索引、刷新预览；保留外部修改检测、回滚上次保存、在外部编辑器打开。不引入 QtWebEngine 做真实渲染预览，控制打包体积与启动时间。

**Alternatives considered:**

- QtWebEngine 真渲染预览：观感最好但安装体积 +300MB 级、启动变慢，收益低于成本。
- 外部编辑器优先：改变现有「应用内编辑」习惯，与「编辑区被挤在底部」的痛点诉求不符。

### 5. 内容操作拆分呈现，业务逻辑留在 application 层

章节树放入左侧 Dock；搜索/替换/重命名/检查移到底部工具面板标签；引用分析保留对话框。索引构建、写后联动、自动校验全部复用现有 `application/content` 服务，UI 只做呈现与事件接线。`ContentWorkspace` 不再把树与面板打包进同一父容器，改为暴露命名子容器（如 `tree_host`/`tabs_host`/`panels_host`）由主窗口摆放；标签切换、`Ctrl+1..5`、菜单跳转等现有机制保持不变。

**Alternatives considered:**

- 在 `MainWindow` 重写内容工作区：复制索引构建与写后联动逻辑，回归风险高。
- 保持内容工作区自包含放入一侧：左侧放不下树、右侧被标签页占满，无法体现 IDE 工作形式。

### 6. 统一 QSS 主题与 Qt 高 DPI

建立集中 QSS 主题：微软雅黑字体层级、标准间距、主/次按钮、卡片化面板、中性/成功/警告/失败语义色（沿用 `SEMANTIC_COLORS`），默认浅色，提供深色切换。状态含义同时由文字与图标/字形表达，不依赖纯颜色，保证高对比度主题可读。Qt 原生高 DPI 处理，保留窗口最小尺寸与几何持久化。

**Alternatives considered:**

- 第三方 Qt 主题库（如 qt-material）：增加依赖与版本风险，自定义能力反而不如手写 QSS。

### 7. 打包：PyInstaller + PySide6，裁剪未用模块

`requirements-build.txt` 增加 PySide6；PyInstaller onedir 模式，仅引入 `QtCore`/`QtGui`/`QtWidgets`，排除未用的 `QtWebEngine`、`QtNetwork`、`QtQml`、`QtMultimedia` 等大件。预期 onedir 约 120–180MB、Inno Setup 安装包约 50–80MB（较现状增大，属迁移已知代价）。冻结态验证高 DPI、中文渲染、图标资源与菜单快捷键。

**Alternatives considered:**

- 保留 Tk 与 Qt 双栈并行发布：维护成本高，体积更不可控。
- 系统安装 Qt 运行库：违背「端用户无需安装依赖」的既有交付约定。

### 8. 测试与验收

- 纯逻辑测试全部保留（状态推导、错误呈现），不依赖 Tk 的部分在新 shell 下继续通过。
- 新增 `test_step_list.py`：步骤状态推导（待处理/进行中/成功/跳过/失败/取消）、事件乱序、心跳无百分比。
- GUI 冒烟（QtTest / 进程级）：应用启动、打开项目、三个 Dock 存在、菜单可用。
- 人工验收清单：空状态/空闲/运行/成功/失败/取消/只读/Word 不可用/结果路径失效/项目切换。
- 文档管线与 CLI 回归：`build_docx.py all`、`validate_docx.py all`、现有测试套件。

## Risks / Trade-offs

- [PySide6 打包体积/首次启动变慢] → 裁剪未用模块；接受体积代价并在交付说明中写明。
- [UI 层整体重写回归] → 业务层不动；分阶段独立验证；纯逻辑测试锁定状态映射。
- [Qt 高 DPI/中文/主题在不同 Windows 差异] → Qt 原生支持；统一 QSS；Windows 人工验收。
- [Dock 布局在窄窗口挤压章节树/编辑器] → Dock 可折叠、面板可滚动；纯状态映射保证布局变化不影响业务。
- [日志/结果迁移遗漏] → 结果卡片独立呈现失败；折叠日志保留待读/错误提示。
- [结果操作指向不存在或过期文件] → 每次渲染与点击前检查路径存在性，项目切换后清除旧结果。
- [端用户升级体感（安装体积变大）] → 安装与自更新流程不变，仅体积变化，提前告知。

## Migration Plan

1. 基础设施：`requirements-build.txt` 增 PySide6；`app.py` 换 `QApplication`；QSS 主题；扩展 `workbench_state`（`WorkView`/`StepItem`/`DetailState`）与 `derive_step_list` 纯逻辑 + 测试。
2. 主窗口骨架：`QMainWindow` + 项目条 + 空状态 + 菜单/快捷键 + 几何持久化 + 关闭保护；跑通「打开项目 → 看到 IDE 骨架」。
3. 右侧任务/结果 Dock：步骤清单 + 日志流 + 结果卡片 + 取消（先用模拟事件驱动，验证渲染）。
4. 章节树 + 中心编辑器：左树 + 多标签编辑器 + 轻量预览 + 写后联动。
5. 底部工具面板：搜索/替换/重命名/检查（复用 `application/content` 服务）。
6. 新建项目向导：`QWizard` 重写。
7. 打包：PyInstaller spec + 体积裁剪 + Inno Setup + 冻结冒烟。
8. 回归 + 人工验收 + 文档更新（README 桌面章节、帮助/关于）。

回滚时可保留 Tk 版本直到新 UI 验收通过；业务层不依赖 UI 框架，回滚不需要数据迁移。若 IDE 布局出现严重问题，可临时退回原纵向布局，同时保留底层任务处理能力。
