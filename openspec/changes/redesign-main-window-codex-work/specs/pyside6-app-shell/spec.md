# PySide6 应用外壳

## ADDED Requirements

### Requirement: Application runs on a PySide6 QApplication shell
桌面应用 SHALL 以 PySide6 `QApplication`/`QMainWindow` 取代 tkinter root/`MainWindow` 作为 UI 载体。业务层（`domain`/`application`/`adapters`）与 `TaskRunner` 线程模型 MUST 保持现有依赖关系不变，不引入 Qt 依赖。

#### Scenario: Launch the app
- **WHEN** 用户启动应用
- **THEN** 显示 Qt 主窗口与空状态页，无 Tk 窗口或运行时错误

#### Scenario: Frozen build
- **WHEN** 应用以 PyInstaller onedir 冻结态启动
- **THEN** `QApplication` 正常初始化，资源、图标与 QSS 主题加载成功

### Requirement: Main window shell exposes menu, project bar and status bar
主窗口 SHALL 提供菜单栏、顶部项目条与底部状态栏。顶部项目条 SHALL 显示文档名、类型、版本与就绪状态，并提供正式合并、诊断构建、项目校验的高频入口；高频入口 MUST 与对应菜单命令共享同一命令与可用性来源。

#### Scenario: Writable project opened
- **WHEN** 用户打开一个受支持且可写的项目
- **THEN** 顶部项目条显示文档标识与就绪状态，正式合并/诊断构建/校验入口可用性符合当前项目状态

#### Scenario: Word unavailable
- **WHEN** 当前项目可写但 Microsoft Word 不可用
- **THEN** 顶部项目条保持正式合并入口可用或标注原因，同时明确提供诊断构建入口

#### Scenario: Invoke from project bar
- **WHEN** 用户点击顶部项目条的高频入口
- **THEN** 应用调用与对应菜单相同的命令、确认和错误处理，并同步刷新页面状态

### Requirement: Window lifecycle and state persistence are preserved
窗口几何/最大化状态持久化、任务运行中的关闭保护、菜单与键盘快捷键 SHALL 在迁移到 PySide6 后保持与 Tk 版一致的语义，不因框架更换而丢失。

#### Scenario: Close during task
- **WHEN** 用户在后台任务运行时关闭主窗口
- **THEN** 应用沿用现有安全关闭确认与取消策略，任务在安全阶段边界停止后窗口关闭

#### Scenario: Geometry saved
- **WHEN** 用户调整窗口尺寸/位置或最大化后退出
- **THEN** 下次启动恢复相同几何与状态，几何存储格式与现有持久化兼容

### Requirement: Main content switches among explicit view states
主内容区 SHALL 在空状态、空闲、任务运行和任务结果四态之间切换。空状态显示新建/打开/最近项目；空闲显示 IDE 布局与最近结果；运行显示右侧步骤清单与日志流；结果显示结果卡片与后续操作。状态推导 MUST 保持纯逻辑、可独立测试。

#### Scenario: Start without a project
- **WHEN** 应用启动且没有已打开项目
- **THEN** 显示空状态页，提供新建、打开和最近项目入口

#### Scenario: Task starts from any entry
- **WHEN** 用户通过项目条、菜单或快捷键启动后台任务
- **THEN** 页面切换到运行视图，右侧显示步骤清单与日志流，取消入口可用

#### Scenario: Task reaches terminal state
- **WHEN** 后台任务成功、失败、取消或超时
- **THEN** 页面进入结果视图，右侧显示结果卡片与适用后续操作，步骤清单保留终态状态

### Requirement: UI uses a unified QSS theme with Qt-native high-DPI
界面 SHALL 应用统一 QSS 主题（字体层级、标准间距、按钮层级、中性/成功/警告/失败语义色），默认浅色，支持切换深色。高 DPI SHALL 由 Qt 原生缩放处理，不再依赖系统 `shcore`/`SetProcessDPIAware` hack。状态含义 MUST 同时由文字表达，不得仅依赖颜色。

#### Scenario: Default theme renders
- **WHEN** 应用启动并使用默认浅色主题
- **THEN** 标题、正文、按钮、状态文字与语义色按主题渲染，字体为中文字体栈

#### Scenario: High-DPI display
- **WHEN** 应用在 HiDPI/多显示器缩放下运行
- **THEN** 界面按缩放比例清晰渲染，控件不模糊、不截断
