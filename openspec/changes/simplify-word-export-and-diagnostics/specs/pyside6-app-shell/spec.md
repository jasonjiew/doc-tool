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

## ADDED Requirements

### Requirement: Word export starts after compact settings confirmation

有效项目的普通“导出 Word…” SHALL 先显示预填设置，默认整份、当前内容、既有模板、非严格及有效目录；用户点击“开始生成”后才捕获实际输入并一次提交后台任务，不再追加配置摘要或发布检查确认。源文件、修订记录和脏标记保持，执行 SHALL 不因测试环境而切换路径。取消设置不创建导出或写入正文；输入和目的地不可用时说明具体原因。

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
