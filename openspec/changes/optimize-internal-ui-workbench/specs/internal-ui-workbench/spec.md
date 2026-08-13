## ADDED Requirements

### Requirement: No-project state provides direct starting actions
桌面应用 SHALL 在未打开项目时显示明确的空状态工作区，并 SHALL 直接提供新建项目、打开项目和最近项目入口，不要求用户先从菜单中寻找主要入口。

#### Scenario: Start with no project loaded
- **WHEN** 应用启动且没有自动恢复出已打开项目
- **THEN** 主内容区显示新建项目、打开项目和最近项目入口，并且不显示依赖当前项目的可执行操作

#### Scenario: Open a recent project
- **WHEN** 用户从空状态选择一个仍然有效的最近项目
- **THEN** 应用加载该项目并把主内容区切换为已打开项目工作台

#### Scenario: Recent project is unavailable
- **WHEN** 用户选择的最近项目路径已不存在或不再包含有效项目
- **THEN** 应用说明该项目无法打开、保持空状态可操作，并允许用户选择其他项目

### Requirement: Open-project workbench exposes high-frequency actions
桌面应用 SHALL 在已打开项目的首屏直接提供正式合并、诊断构建、项目校验、打开内容目录、打开输出位置和打开报告的高频入口，并 MUST 保留现有菜单和键盘快捷键的兼容行为。

#### Scenario: Writable project is opened
- **WHEN** 用户打开一个受支持且可写的项目，并且当前没有冲突任务运行
- **THEN** 首屏显示与该项目状态相符的构建、校验和路径快捷入口

#### Scenario: Invoke action from workbench
- **WHEN** 用户点击首屏的项目校验、构建或路径快捷入口
- **THEN** 应用调用与对应菜单入口相同的命令、确认流程和错误处理逻辑

#### Scenario: Invoke existing menu or shortcut
- **WHEN** 用户通过已有菜单或键盘快捷键启动受支持操作
- **THEN** 应用保持与优化前一致的操作语义，并同步刷新工作台状态

### Requirement: Workbench communicates project readiness and disabled reasons
桌面应用 SHALL 显示当前项目的名称、路径、文档类型、兼容/可写状态及正式合并就绪状态。任何因项目状态、任务冲突、Word 环境或缺少产物而不可用的高频操作 MUST 被禁用，并 SHALL 在首屏提供用户可理解的不可用原因。

#### Scenario: Incompatible project is opened read-only
- **WHEN** 项目模式版本高于当前应用支持版本
- **THEN** 工作台标记项目为只读，禁用会写入项目或输出的操作，并提示需要兼容版本的应用

#### Scenario: Word is unavailable for formal merge
- **WHEN** 当前项目可写但 Microsoft Word 不可用于正式合并
- **THEN** 正式合并入口不可用或在启动前被阻断，首屏说明 Word 是正式字段刷新所必需，同时保持明确标记的诊断构建入口可用

#### Scenario: Required output does not exist
- **WHEN** 当前项目尚无可打开的输出或报告
- **THEN** 对应快捷入口被禁用，并显示尚未生成相关产物的原因

#### Scenario: Task is already running
- **WHEN** 当前项目已有会冲突的后台任务运行
- **THEN** 工作台禁用不能并发执行的项目操作，并显示当前运行任务信息

### Requirement: Long tasks show understandable stages and safe cancellation state
桌面应用 SHALL 使用现有结构化任务事件显示当前任务名称、阶段、确定性进度或心跳、已用时间和终态。取消操作 MUST 沿用现有安全阶段边界，不得把界面上的取消请求解释为已经即时中断临界操作。

#### Scenario: Deterministic stage progress is available
- **WHEN** 后台任务报告阶段名称和确定性进度
- **THEN** 任务区显示当前阶段、进度和已用时间，并随事件推进更新

#### Scenario: Only heartbeat is available
- **WHEN** 长时间 Word 操作无法提供可靠百分比但持续报告心跳
- **THEN** 任务区保持活动状态，显示当前阶段和已用时间，不展示伪造的完成百分比

#### Scenario: User requests cancellation at a safe boundary
- **WHEN** 用户在允许取消的阶段请求取消
- **THEN** 应用显示取消请求已接收，在安全边界停止后续阶段，并以取消终态结束任务

#### Scenario: Task is in a protected critical section
- **WHEN** 任务正在 Word 保存或原子发布等不可安全中断的临界区
- **THEN** 取消入口被禁用或标记为等待安全边界，应用不得留下损坏项目或覆盖有效输出

### Requirement: Successful results provide immediate next actions
桌面应用 SHALL 在主窗口持续显示最近一次成功任务的摘要，并 SHALL 根据实际生成的结果提供打开产物、打开所在目录和打开校验报告等适用的后续操作。成功反馈不得只存在于可关闭的临时弹窗中。

#### Scenario: Formal merge succeeds
- **WHEN** 正式合并完成并发布有效 DOCX
- **THEN** 结果区显示正式成功摘要和输出路径，并提供打开产物、打开所在目录及查看相关校验报告的入口

#### Scenario: Validation succeeds without a document output
- **WHEN** 独立项目校验成功但未生成新的 DOCX
- **THEN** 结果区显示校验成功摘要和报告入口，不显示误导性的打开新产物操作

#### Scenario: Result path becomes unavailable
- **WHEN** 最近结果记录的文件在用户执行后续操作前已被移动或删除
- **THEN** 应用不尝试打开无效路径，并提示该结果已不可用或引导打开仍存在的项目目录

#### Scenario: Project is switched after success
- **WHEN** 用户在任务成功后打开另一个项目
- **THEN** 工作台不得把前一项目的产物操作显示为当前项目结果

### Requirement: Failed results separate reason, advice, and technical details
桌面应用 SHALL 在失败结果中优先显示可理解的失败原因和建议操作，并 SHALL 提供按需展开的技术详情。技术详情 MUST 复用已有稳定错误码和脱敏日志信息，不得暴露文档正文、凭据或不应记录的敏感内容。

#### Scenario: Failure has a known error code
- **WHEN** 后台任务返回具有稳定错误码、用户说明和建议操作的失败
- **THEN** 结果区直接显示原因和建议，并在技术详情中显示错误码、阶段和日志位置

#### Scenario: Unexpected exception occurs
- **WHEN** 后台任务因未分类异常失败
- **THEN** 结果区显示通用失败说明和查看日志或诊断信息的建议，技术详情提供脱敏异常摘要而非完整业务内容

#### Scenario: User expands technical details
- **WHEN** 用户选择展开失败技术详情
- **THEN** 应用显示可复制的错误码、失败阶段、异常摘要和日志路径，并保持主要原因与建议仍然可见

#### Scenario: Failure preserves previous valid output
- **WHEN** 正式合并在发布前失败且项目仍有上一次有效输出
- **THEN** 结果区明确说明本次任务未生成新的正式产物，不把旧输出误报为本次成功结果

### Requirement: Event log is compact, collapsible, and remains observable
桌面应用 SHALL 将事件日志作为可展开和折叠的辅助区域。日志折叠时 MUST 继续接收任务事件并维护待读状态；展开后 SHALL 保留查看、复制和打开日志目录能力。

#### Scenario: Workbench opens with compact log
- **WHEN** 主窗口进入空闲工作台且用户尚未主动展开日志
- **THEN** 日志区域以紧凑摘要显示，不持续占用主要操作和结果区域的大部分空间

#### Scenario: Events arrive while log is collapsed
- **WHEN** 日志折叠期间后台任务产生新事件
- **THEN** 日志标题更新待读数量或状态提示，事件仍被保留供后续查看

#### Scenario: User expands the log
- **WHEN** 用户点击展开日志
- **THEN** 应用显示已有事件，并提供复制日志内容和打开日志目录的入口

#### Scenario: User collapses the log during a task
- **WHEN** 后台任务运行时用户折叠日志
- **THEN** 任务进度和结果区域继续更新，折叠日志不会中断事件处理或后台任务

### Requirement: Visual hierarchy is consistent and restrained
桌面应用 SHALL 使用集中定义的有限字体层级、间距、主要/次要操作层级以及成功、警告、失败和中性语义样式。状态含义 MUST 同时由文字表达，不得仅依赖颜色；界面 MUST 在 Windows 高 DPI 与支持的系统主题下保持可读。

#### Scenario: Primary and secondary actions are displayed
- **WHEN** 已打开项目工作台显示正式合并和辅助操作
- **THEN** 正式合并具有明确的主要操作层级，诊断、校验和路径入口使用一致但较弱的次要层级

#### Scenario: Semantic status is displayed
- **WHEN** 项目或任务进入成功、警告或失败状态
- **THEN** 界面使用对应的有限语义样式并同时显示明确状态文字

#### Scenario: Application runs with Windows display scaling
- **WHEN** 用户在受支持的 Windows 高 DPI 缩放设置下启动源码版或冻结版应用
- **THEN** 标题、正文、按钮和状态信息保持可读，主要控件不因固定像素假设而被截断

### Requirement: Workbench state remains consistent across transitions
桌面应用 MUST 在应用启动、项目打开或关闭、项目兼容性变化、任务启动、任务事件、任务终止和窗口关闭保护等状态转换后统一刷新工作台，不得留下与当前项目或任务不一致的可执行入口和结果信息。

#### Scenario: Task starts from any compatible entry
- **WHEN** 用户通过工作台、菜单或快捷键启动后台任务
- **THEN** 所有冲突入口同步禁用，任务区进入运行状态，且结果区不把旧结果显示为当前任务结果

#### Scenario: Task reaches a terminal state
- **WHEN** 后台任务成功、失败、取消或超时
- **THEN** 任务区停止运行状态，结果区显示对应终态，并按当前项目条件恢复可用操作

#### Scenario: User attempts to close during a task
- **WHEN** 用户在后台任务运行时关闭主窗口
- **THEN** 应用沿用现有安全关闭确认和取消策略，不因新工作台布局绕过任务保护
