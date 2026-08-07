## ADDED Requirements

### Requirement: Users can create and open document projects from the desktop application
桌面应用 SHALL 提供新建项目、打开已有项目和最近项目入口，并在执行操作前展示项目名称、文档类型、版本、项目路径及状态。

#### Scenario: Open a valid existing project
- **WHEN** 用户选择包含受支持 `project.yml` 的项目目录
- **THEN** 应用加载项目摘要并启用与当前状态相符的拆分、校验、合并和打开目录操作

#### Scenario: Open an incompatible project
- **WHEN** 项目模式版本高于当前应用支持版本
- **THEN** 应用以只读方式显示项目并阻止写操作，提示安装兼容的新版本

### Requirement: Users can reach editable content and outputs without knowing internal paths
桌面应用 SHALL 提供“打开 Markdown 目录”“打开输出目录”和“打开日志目录”，并使用系统文件管理器定位当前项目对应目录。

#### Scenario: Open Markdown directory
- **WHEN** 用户在已导入项目中点击“打开 Markdown 目录”
- **THEN** 系统文件管理器打开该项目的 `content` 目录，不打开程序安装资源目录

### Requirement: Project validation is available independently
桌面应用 SHALL 允许用户在合并前单独运行章节、编号、Markdown、图片、复杂表格和项目清单校验，并展示通过/失败计数及可定位错误。

#### Scenario: Numbering gap is found
- **WHEN** 同级最后一个章节为 `3.1.13` 而用户新增 `3.1.99`
- **THEN** 校验失败并明确提示期望编号 `3.1.14`，且不开始构建 Word

#### Scenario: Validation succeeds
- **WHEN** 项目结构和全部资源均符合规则
- **THEN** 应用显示成功摘要、校验时间和日志路径

### Requirement: Formal merge uses the complete guarded pipeline
桌面应用 MUST 按“预检、临时构建、刷新前严格校验、Word 字段刷新、刷新后严格校验、原子发布”的顺序生成正式 Word，任一步失败不得标记成功。

#### Scenario: Formal merge succeeds
- **WHEN** 项目合法、本机 Word 可用且两次严格校验均通过
- **THEN** 应用把刷新后的 DOCX 原子发布到 `output`，显示文件路径、页数和成功摘要

#### Scenario: Post-refresh validation fails
- **WHEN** Word 保存后严格校验发现目录、关系、内容或模板语义不一致
- **THEN** 应用报告失败并保留上一次有效正式输出，不用失败文件覆盖它

### Requirement: Microsoft Word availability is explicit
系统 SHALL 在正式合并前检测交互式 Windows 环境中的 Microsoft Word；缺失或不可启动时 MUST 阻断正式发布，并可将跳过 Word 的结果明确标记为非正式诊断构建。

#### Scenario: Word is not installed
- **WHEN** 用户点击正式合并但 Word COM 不可用
- **THEN** 应用停止在刷新阶段之前，说明正式目录和页码刷新需要 Microsoft Word

#### Scenario: Diagnostic build without Word
- **WHEN** 高级用户显式选择诊断构建并确认跳过 Word
- **THEN** 应用允许完成构建级校验，但输出和界面必须标注“非正式，字段未实机刷新”

### Requirement: Word automation is isolated from user sessions
系统 MUST 使用本次任务专用的 Word 进程，不得复用、关闭或终止用户已打开的 Word；超时只处理本应用创建的进程树。

#### Scenario: User Word documents are already open
- **WHEN** 正式合并开始时用户已有 Word 进程和已打开文档
- **THEN** 应用使用独立 Word 实例完成刷新，结束后用户原有进程和文档保持不变

### Requirement: Long operations remain observable and safely cancellable
桌面应用 SHALL 在后台执行导入、校验和合并，持续显示阶段、进度或心跳；取消 MUST 只在安全边界生效，不得在保存或原子发布临界区留下损坏项目。

#### Scenario: Long Word refresh
- **WHEN** Word 正在分页一个大型详细设计文档
- **THEN** 界面保持响应并显示当前阶段与已用时间，不显示假死状态

#### Scenario: Cancel before publication
- **WHEN** 用户在允许取消的提取阶段请求取消
- **THEN** 应用停止后续阶段、清理暂存输出并保持正式项目和上次输出不变

### Requirement: Project operations are protected by a local lock
系统 MUST 在导入或合并期间持有包含进程标识和启动时间的项目锁，阻止同一项目在本机被两个任务同时写入，并能识别已终止进程留下的陈旧锁。

#### Scenario: Second operation starts on a locked project
- **WHEN** 同一项目已有活动合并任务，用户再次启动导入或合并
- **THEN** 应用拒绝第二个写任务并显示当前任务信息

#### Scenario: Stale lock is detected
- **WHEN** 锁文件记录的本机进程已经不存在
- **THEN** 应用允许用户查看诊断并安全清理陈旧锁后重试

### Requirement: Logs are useful without exposing document content
系统 SHALL 记录版本、阶段、时间、文件哈希、元素计数、错误码和异常诊断，但 MUST NOT 把正文、表格单元格文本、图片内容或凭据写入日志。

#### Scenario: Import fails on a complex table
- **WHEN** 导入因复杂表格 XML 无法解析而失败
- **THEN** 日志包含表格资源标识、阶段和异常类型，但不包含完整表格业务文本

### Requirement: Chinese and long Windows paths are supported
系统 SHALL 正确处理中文、空格、括号和 `&` 等合法 Windows 路径字符，并在创建文件名前替换 Windows 禁止字符；超长路径必须在预检阶段给出明确错误或支持策略。

#### Scenario: Chinese project path
- **WHEN** 用户在包含中文、空格和括号的目录中创建并合并项目
- **THEN** 导入、资源解析、Word 刷新和输出均使用原路径成功完成
