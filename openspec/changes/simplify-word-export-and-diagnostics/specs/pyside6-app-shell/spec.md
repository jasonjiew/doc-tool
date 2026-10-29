## MODIFIED Requirements

### Requirement: Main window shell exposes menu, project bar and status bar

主窗口 SHALL 提供菜单栏、顶部项目条与底部状态栏，显示文档名、类型、版本和就绪状态。日常导出区 SHALL 只突出“导出 Word…”一个主要操作，先打开简洁设置页，提供“更多”和最近结果入口；其它格式、正式出稿、诊断构建与项目校验 SHALL 在次级菜单中可达。按钮、菜单与 Ctrl+E MUST 共享设置、提交及可用性来源，未获得正式状态事实前 SHALL 不把主按钮命名为“导出正式 Word”。

#### Scenario: Writable project opened
- **WHEN** 用户打开一个受支持且可写的项目
- **THEN** 顶部项目条显示文档标识与就绪状态，导出 Word、更多和最近结果可见，正式合并、诊断构建、校验可从次级菜单取得且可用性符合项目状态

#### Scenario: Word unavailable
- **WHEN** 当前项目可写但 Microsoft Word 不可用
- **THEN** 导出 Word 设置入口保持可用，确认后仍可生成可读稿并标明待刷新，次级菜单中的正式出稿说明实际限制，诊断构建仍可达

#### Scenario: Invoke from project bar
- **WHEN** 用户通过顶部主按钮、对应菜单或 Ctrl+E 发起导出 Word
- **THEN** 应用打开同一设置页并采用相同默认值和错误处理，仅在用户点击开始生成后提交任务，并同步刷新页面状态

#### Scenario: Narrow project bar
- **WHEN** 用户在 1024×640 窗口或长中文项目名下使用项目条
- **THEN** 主要操作文字完整且可点击，一次点击即可进入简洁设置，次级操作可从更多菜单取回，导出区不再平铺快速构建、正式出稿和导出设置三个独立按钮

### Requirement: UI uses a unified QSS theme with Qt-native high-DPI

[VS-01] 界面 SHALL 应用统一 QSS 主题（字体层级、标准间距、按钮层级、中性/成功/警告/失败语义色），默认浅色，支持切换深色。高 DPI SHALL 由 Qt 原生缩放处理，不再依赖系统 `shcore`/`SetProcessDPIAware` hack。状态含义 MUST 同时由文字表达，不得仅依赖颜色。主流程区域 SHALL 保持同一区域至多一个填充强调主动作，次级动作和更多使用较轻样式；键盘焦点与禁用态可辨，中文及关键动作在窄窗和缩放下可读可达。界面样式 SHALL 不改变编辑正文或 Word 成品样式。

#### Scenario: Default theme renders
- **WHEN** 应用启动并使用默认浅色主题
- **THEN** 标题、正文、按钮、状态文字与语义色按主题渲染，字体为中文字体栈

#### Scenario: High-DPI display
- **WHEN** 应用在 HiDPI/多显示器缩放下运行
- **THEN** 界面按缩放比例清晰渲染，控件不模糊、不截断

#### Scenario: Main workflow actions have a stable hierarchy
- **WHEN** 用户在主页面、导出设置或结果区操作
- **THEN** 各区域至多一个主动作使用填充强调样式，次级动作与更多可辨；保存、导出、开始和取消保持可达，按钮文案完整，固定收纳动作不因样式或尺寸变化重新平铺

#### Scenario: Switch theme and navigate with the keyboard
- **WHEN** 用户在深浅主题间切换并通过 Tab 访问主流程控件
- **THEN** 背景、文字、错误提示及菜单使用当前主题，焦点与禁用态可辨，无残留浅色错误背景或仅靠颜色表达的状态

#### Scenario: Polish the interface without changing document appearance
- **WHEN** 用户应用本轮界面样式并继续编辑或导出
- **THEN** 正文的字号偏好、Markdown 内容及 Word 模板和成品排版保持原策略，界面样式不增加确认步骤

## ADDED Requirements

### Requirement: Word export starts after compact settings confirmation

[CF-03] 有效项目的普通“导出 Word…” SHALL 先显示预填设置，默认整份、当前内容、既有模板、非严格及有效目录；用户点击“开始生成”后才捕获实际输入并一次提交后台任务，不再追加配置摘要或发布检查确认。源文件、修订记录和脏标记保持，执行 SHALL 不因测试环境而切换路径。取消设置不创建导出或写入正文；输入和目的地不可用时说明具体原因。

#### Scenario: First generation with unsaved chapters
- **WHEN** 用户首次点击导出 Word 且两个章节尚未保存
- **THEN** 首先打开已预填的简洁设置页，确认开始后任务采用两个章节的当前内容；不要求保存全部或再确认发布检查，磁盘正文与脏标记保持

#### Scenario: Previous advanced request used saved partial content
- **WHEN** 上次高级导出采用部分章节、已保存来源、严格模式或其它格式，用户随后通过主入口导出 Word
- **THEN** 设置页默认显示整份、当前内容、Word、既有模板及非严格策略，用户确认实际范围与来源后生成，原高级范围和来源不隐式继承

#### Scenario: Use advanced settings explicitly
- **WHEN** 用户在简洁设置中修改范围或展开高级选项选择其它格式
- **THEN** 同一设置页保留原能力，任务采用明确确认的范围、来源和格式，不再打开另一套设置或重复确认对话框

#### Scenario: Cancel before generation
- **WHEN** 用户在设置页选择取消或按 Esc 退出
- **THEN** 不建立导出任务、捕获或失败记录，源文件与缓冲保持，返回此前编辑位置

#### Scenario: Normal invocation and automated invocation
- **WHEN** 普通桌面进程和自动化进程分别通过真实按钮、菜单或快捷键调用默认导出入口
- **THEN** 两者均先显示相同设置，确认后采用相同提交路径，测试不得通过环境识别、跳过设置参数或替代处理函数证明正常路径可用

#### Scenario: Another conflicting task is running
- **WHEN** 用户在已有冲突导出任务运行期间再次发起导出 Word
- **THEN** 系统说明正在执行的任务，本次不重复启动，不改变原任务的项目、捕获和结果归属，编辑与查看既有成果保持可用

#### Scenario: Generate current content from an old result
- **WHEN** 用户从旧结果选择按当前内容生成或更改设置后生成
- **THEN** 打开同一设置并预填仍可用的原参数，明确当前内容来源；取消不提交，确认仅建立一次新捕获，不直接沿旧参数启动

#### Scenario: One real shortcut activation
- **WHEN** 用户在已打开项目中实际按下 Ctrl+E 并确认或取消设置
- **THEN** 快捷键仅打开一次与按钮和菜单相同的设置，未确认时无导出，确认后只有一次提交，不能通过手工触发处理函数代替此项验证

### Requirement: Export settings prioritizes common fields and retains user input

导出设置 SHALL 优先呈现文件名、保存位置、范围、内容来源及格式/模板摘要，按项目资料和可复用偏好预填；默认值有效时用户无需手工填写即可开始。文档属性、字段刷新细节和排版高级项 SHALL 折叠并使用可理解标签。参数变动 SHALL 更新实际输出摘要，可提前确定的字段错误在原位置提示且保留输入，不以新增向导或重复弹窗处理。

#### Scenario: Reopen settings with valid previous destination
- **WHEN** 用户再次打开当前项目的导出设置，已有有效目录和项目文档资料
- **THEN** 文件名、目录与模板等可用值自动预填，范围和内容来源明确可见，用户可直接确认开始，不要求重新录入编号或逐项重新选择

#### Scenario: Change fields and validate inline
- **WHEN** 用户修改文件名、范围或来源，出现能够在提交前确定的无效输入
- **THEN** 本页对应字段旁显示原因及修正方式，已填内容保持，输出摘要同步更新，输入修正后即可开始，不弹第二个配置确认页

#### Scenario: Inspect advanced options
- **WHEN** 用户需要修改文档属性、图片表格排版或字段刷新策略
- **THEN** 在同一设置页展开高级区域即可操作，普通状态不平铺 DOCPROPERTY、TOC、NUMPAGES 等实现术语，不把这些选项变成正常导出的必填项

### Requirement: Export settings presents readable groups and inline errors

[VS-02] 导出设置 SHALL 让字段标签、输入值、来源/模板说明及字段错误具有清楚的阅读层级和一致间距；深浅主题均可读。开始和取消 SHALL 位于内容滚动区之外且保持可达，常用设置优先，高级区仍可折叠。错误 SHALL 在现有字段旁或错误区显示原因并保留输入，只有已核实对应字段时才标注该字段；长路径和错误可查看完整内容，不通过新增向导、确认框或强制撑宽窗口处理。

#### Scenario: Basic settings at a narrow size
- **WHEN** 用户在 1024×640 主窗口中打开导出设置，文件名或目录较长
- **THEN** 常用字段和来源说明可阅读，必要内容可滚动或在原控件查看完整值，开始/取消不随内容滚走，用户仍可直接确认有效默认值

#### Scenario: Inline error uses the active theme
- **WHEN** 设置检测到已知字段错误或内容来源冲突，用户切换主题并修正输入
- **THEN** 原位置显示可读原因并保留其它输入，已知字段得到相应标注，未知字段不被猜测标红；修正后旧错误标注清除，不新增弹窗

#### Scenario: Expand advanced options without moving the footer out of reach
- **WHEN** 用户展开高级设置或长来源说明占用更多高度
- **THEN** 内容在现有设置区域内滚动，底部开始/取消仍可见可用，标签和输入不会互相遮挡

### Requirement: Secondary shell actions stay in their assigned location

[CF-01] 顶部导出设置、快速构建和正式出稿 SHALL 固定收纳在已有更多菜单；窗口变宽、变窄、切换主题、项目或任务状态 SHALL 不恢复并列导出设置按钮。正常导出、成果及其它现有常用按钮保持原层级，低频动作仍按原可用性执行，不新增菜单系统或页面。

#### Scenario: Wide and narrow windows
- **WHEN** 项目条在 1024×640、1280×720 和较宽窗口之间重复重排
- **THEN** 导出 Word 和成果保持可达，导出设置、快速构建和正式出稿始终从更多取得，每个菜单动作只出现一次

#### Scenario: Task availability changes
- **WHEN** 导出开始、结束或项目切换导致动作可用性改变
- **THEN** 按钮和更多菜单采用一致的实际可用性，原来固定收纳的动作不会因禁用后恢复而回到工具栏

### Requirement: Current content checks do not write source versions and expose results

[CF-06] F5、顶部检查和对应菜单 SHALL 调用同一当前内容检查，保留已选范围、活缓冲和真实执行状态。检查 SHALL 不保存正文、清除脏标记或同步写回修订版本及项目配置；已有检查报告和缓存可沿原规则更新。用户主动检查后 SHALL 能在已有面板直接查看结果，面板原先收起不使检查只剩一条状态栏提示。

#### Scenario: Check unsaved content with a different revision version
- **WHEN** 窗口有未保存修改，修订记录版本与项目版本不同，用户按 F5
- **THEN** 检查反映当前缓冲，正文、修订记录及项目配置字节保持，脏标记保持，当前检查范围和执行结果可见

#### Scenario: Check while the tools dock is collapsed
- **WHEN** 工具面板原先收起，用户通过 F5、顶部检查或菜单主动检查
- **THEN** 现有检查面板展开并显示该次结果；索引未就绪或规则未执行时明确说明，不能显示检查通过

#### Scenario: No project or a conflicting task
- **WHEN** 项目尚未打开或有不允许并行的任务
- **THEN** 继续采用已有禁用或忙碌反馈，不隐式保存、启动第二次检查或改变现有任务归属
