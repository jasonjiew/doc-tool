## 1. PySide6 基础设施

- [x] 1.1 在 `requirements-build.txt` 增加 `PySide6`，确认开发环境可启动 `QApplication` 且不再依赖 tkinter
- [x] 1.2 将 `app.py` 改为 `QApplication`/`QMainWindow` 入口；高 DPI 改走 Qt 原生缩放，移除 `styles.py` 的 `shcore`/`SetProcessDPIAware` hack
- [x] 1.3 建立集中 QSS 主题系统：字体层级、标准间距、按钮层级、中性/成功/警告/失败语义色；默认浅色 + 深色切换入口
- [x] 1.4 扩展 `workbench_state.py`：新增 `WorkView`（empty/idle/running/result）、`StepItem`、`DetailState`，以及纯逻辑 `derive_step_list(stage_events)`；补充状态映射测试
- [x] 1.5 保持 `task_bridge.py` 协议不变，验证事件队列在 Qt shell 下可用

## 2. 主窗口骨架

- [x] 2.1 实现 `QMainWindow`：菜单栏（文件/操作/内容/工具/帮助）+ 状态栏，迁移现有菜单命令、快捷键与可用性状态
- [x] 2.2 实现顶部项目条：文档名/类型/版本/就绪状态 + 正式合并/诊断构建/校验高频入口，与菜单共享 `derive_workbench_state` 状态来源
- [x] 2.3 实现空状态页：新建项目/打开项目/最近项目入口
- [x] 2.4 迁移窗口几何/最大化持久化与任务运行中关闭保护语义
- [x] 2.5 打通视图四态切换（empty/idle/running/result），跑通「打开项目 → 看到 IDE 骨架」

## 3. 右侧任务/结果 Dock

- [x] 3.1 实现右侧常驻「任务/结果」Dock 容器（可折叠、约 230 逻辑像素、可拖拽）
- [x] 3.2 实现 `WorkStepList` 步骤清单渲染：图标+文字状态（待处理/进行中/成功/跳过/失败/取消）、当前步骤高亮、总体进度、已用时间
- [x] 3.3 实现空闲态：最近结果卡片（打开产物/目录/报告）或引导卡片（校验/诊断构建）
- [x] 3.4 实现运行态：当前步骤流式日志 + 取消入口；心跳任务回退为单一步骤 + 已用时间
- [x] 3.5 实现终态：结果卡片 + 适用后续操作；失败提供可展开技术详情（错误码/阶段/异常摘要/日志路径）
- [x] 3.6 实现日志展开/折叠、折叠期待读计数、复制日志与打开日志目录
- [x] 3.7 结果归属校验：渲染与点击前检查路径存在性，项目切换后清除旧结果

## 4. 章节树 + 中心编辑器

- [x] 4.1 实现左侧章节树 Dock：`QTreeView` + 自定义模型，展开/折叠/刷新/右键菜单（打开、复制相对路径）
- [x] 4.2 实现中心多标签编辑器：`QPlainTextEdit` 编辑 + 轻量 Markdown 预览，支持同时打开多文件切换
- [x] 4.3 迁移编辑器保存链路：`ContentWriter`（备份 + 原子写）→ 索引失效重建 + 预览刷新；保留外部修改检测与回滚上次保存
- [x] 4.4 迁移联动：树/搜索/检查结果定位打开 + 行高亮；`Ctrl+1..5` 标签切换快捷键

## 5. 底部工具面板

- [x] 5.1 实现搜索面板（复用 `SearchService`）
- [x] 5.2 实现替换面板（复用 `ReplaceService` + `ContentWriter`，写回后刷新索引并自动校验）
- [x] 5.3 实现重命名/重编号面板（复用 `RefactorService`，含 `_index.md` 语义与连续编号检查）
- [x] 5.4 实现术语/一致性检查面板（复用 `ContentLinter` + `TermStore`）
- [x] 5.5 迁移引用分析对话框（复用 `ReferenceScanner`）

## 6. 新建项目向导

- [x] 6.1 用 `QWizard` 重写五步向导：选源 / 预检预览 / 项目信息 / 执行中 / 结果
- [x] 6.2 预检结果展示 + 文档类型建议（high confidence 自动采用）+ 阻断告警
- [x] 6.3 事务化导入 + 安全取消语义保持

## 7. 打包与体积

- [x] 7.1 重写 PyInstaller spec 适配 PySide6，仅引入 `QtCore`/`QtGui`/`QtWidgets`，排除未用 `QtWebEngine`/`QtNetwork`/`QtQml`/`QtMultimedia` 等
- [x] 7.2 onedir 冻结程序启动冒烟（资源、图标、QSS、菜单快捷键、高 DPI）
- [x] 7.3 重建 Inno Setup 安装器并验证安装版启动；记录并告知体积变化

> **打包说明（本机环境）**：onedir 构建成功且体积 145MB（Qt 插件仅保留
> platforms/styles/imageformats 等必需项）；但本机安装的 DLP/安全软件导致
> **onedir 冻结程序无法加载任何 .pyd 扩展模块**（`_socket`/`_ctypes` 均报
> “不是有效的 Win32 应用程序”，文件哈希与系统一致）。onefile 变体（56MB）
> 在本机验证启动成功。onedir 需在无 DLP 的干净构建机上完成最终冒烟与安装版
> 启动验证；`packaging/doc_tool_onefile.spec` 提供本机可用的冒烟路径。
>
> **体积变化（PySide6 迁移）**：onedir **145MB**，onefile 单文件 **56MB**，
> Inno Setup 安装器 **64MB**（`packaging/Output/KonsungDocTool-Setup-1.0.0.exe`，
> SHA-256 已随 `.sha256` 文件记录）。安装器本机编译成功；「安装版启动验证」
> 受 DLP 影响需在干净构建机执行（同 7.2 原因）。

## 8. 回归与人工验收

- [x] 8.1 运行现有纯逻辑测试与文档管线回归（`build_docx.py all`/`validate_docx.py all`/现有测试套件），确认业务层无回归
- [x] 8.2 新增 `test_step_list.py`：步骤状态推导、事件乱序、心跳无百分比、取消边界
- [x] 8.3 人工验收清单：空状态 / 空闲 / 运行 / 成功 / 失败 / 取消 / 只读 / Word 不可用 / 结果路径失效 / 项目切换
- [x] 8.4 在支持的 Windows DPI/高对比度/深色主题下检查标题、正文、按钮、状态文字与最小窗口尺寸可读性
- [x] 8.5 更新 README 桌面章节与帮助/关于；验证端用户安装升级路径
