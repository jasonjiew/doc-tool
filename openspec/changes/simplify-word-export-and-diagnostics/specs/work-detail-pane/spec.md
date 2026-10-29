## MODIFIED Requirements

### Requirement: Terminal result card offers follow-up actions

任务终态 SHALL 在右侧 Dock 以非模态结果卡片显示标题、摘要、实际阶段及适用建议。成功时按真实产物提供打开文件、所在目录和报告入口；失败时显示可理解原因、可核实源位置和一个主要恢复动作，错误码、异常、技术路径和日志位于可展开诊断。普通导出完成 SHALL 不再强制弹出另一结果对话框；结果内容 SHALL 顶部对齐，缺失诊断信息明确标未知。

#### Scenario: Formal merge succeeds
- **WHEN** 正式合并完成并发布有效 DOCX
- **THEN** 结果卡片显示成功摘要与输出路径，主要动作是打开 Word，提供所在目录和校验报告入口，用户无需关闭完成弹窗即可继续编辑

#### Scenario: Validation succeeds without document
- **WHEN** 独立校验成功但未生成新 DOCX
- **THEN** 结果卡片显示校验摘要与报告入口，不显示误导性的打开产物操作

#### Scenario: Failure with technical details
- **WHEN** 后台任务以已知错误码失败
- **THEN** 结果卡片直接显示原因与适用建议，技术详情可展开并显示错误码、实际阶段、脱敏异常和本次日志位置，可定位的源文件行号可直接打开

#### Scenario: Result path unavailable
- **WHEN** 结果记录的文件已被移动或删除
- **THEN** 应用不尝试打开无效路径，说明文件不可用，并仅提供仍适用的目录、诊断或明确来源的重新生成动作

#### Scenario: Word and HTML ready but PDF failed
- **WHEN** 同次任务已生成可用 Word、HTML 而 PDF 失败
- **THEN** 卡片突出可打开的 Word，分别显示各格式真实状态，失败 PDF 的原因和补充动作仍可展开，不把整次任务说成完全无成果

#### Scenario: Failure before Word refresh
- **WHEN** 任务在输入准备、图片处理、构建或校验阶段失败，尚未执行 Word 刷新
- **THEN** 卡片显示该真实失败阶段与原因，技术详情和复制诊断仍可用，不仅给出 Word 刷新阶段未知或一段临时路径异常

#### Scenario: Readable document pending refresh
- **WHEN** 可读 Word 已生成但目录或页码刷新不可用
- **THEN** 卡片可打开已确认稳定的文件，明确标待刷新，并按能力提供继续刷新动作，正式状态仍以既有登记事实为准

### Requirement: Results persist and belong to current project

结果卡片 SHALL 在浏览章节时保持。项目切换 SHALL 清除当前展示中的旧项目结果与操作，但保留各项目已有导出索引和诊断引用；关闭面板或重新打开项目后 SHALL 能从导出记录找回该项目的导出及诊断。历史列表 SHALL 优先显示时间、结果和内容来源，技术轮次标识放入详情；仅查看历史 SHALL 不修改正文或生成新的执行事实。

#### Scenario: Result persists across browsing
- **WHEN** 任务完成后用户继续浏览章节树或内容
- **THEN** 结果卡片保持在右侧 Dock，不因浏览操作被清除

#### Scenario: Project switched after result
- **WHEN** 用户在任务完成后打开另一项目
- **THEN** 右侧 Dock 不把前一项目的产物或恢复操作显示为当前项目结果，回到原项目后可从其记录查看原结果

#### Scenario: Close results and reopen application
- **WHEN** 用户关闭成果面板或退出应用后重新打开同一项目
- **THEN** 最近结果及其已保存诊断可重新打开，诊断不依赖原临时资源目录，源文件和当前缓冲不因查看历史而改变

#### Scenario: Old result lacks diagnostics
- **WHEN** 历史导出没有新增诊断字段或其诊断文件不可读
- **THEN** 已有成果和状态继续可查看，界面明确该次诊断未记录或不可用，不伪造源位置或将当前任务的日志关联为旧记录

## ADDED Requirements

### Requirement: Export recovery presents one primary action from actual facts

导出结果 SHALL 根据该项目、捕获、文件状态和实际诊断推荐一个主要动作，其它适用操作放入更多。原输入重试 SHALL 沿用已确认设置及捕获，无需重复配置；使用当前内容重新生成 SHALL 先显示预填设置，确认后另建导出并显示范围与来源。源位置无法核实、快照缺失或故障尚无确定修复方式时 SHALL 说明限制，不提供误导性定位或以反复重试代替原因说明。

#### Scenario: Known source image problem
- **WHEN** 诊断已确定原 Markdown 中某处图片引用存在问题
- **THEN** 主要动作是定位问题，可展开原因与技术详情，不要求用户先猜更换目录、改设置或补旧格式中的哪一个动作

#### Scenario: Retry while current text has changed
- **WHEN** 用户在旧结果选择重试且当前正文已有新修改
- **THEN** 操作说明沿用本次导出的内容并保留原捕获，当前修改不混入；按当前内容生成作为名称明确的另一个动作

#### Scenario: Prior snapshot is unavailable
- **WHEN** 原输入不可恢复而用户需要再次导出
- **THEN** 原内容重试不可执行，界面可提供明确标为按当前内容生成的动作，点击进入预填设置，用户确认后产生新捕获并保留旧成果，不静默切换来源

#### Scenario: Project or selected result changed before click
- **WHEN** 恢复动作展示后项目、选中导出或其输入身份发生变化
- **THEN** 系统重新核实适用性，拒绝失效动作并刷新原结果说明，不作用于另一项目或另一导出

### Requirement: Export interaction keeps editing context and provides a short return path

导出交互 SHALL 保留正文光标、滚动位置和侧栏偏好，取消或提交设置后恢复编辑焦点。已打开有效项目的正常导出至打开 Word SHALL 最多三次主要操作：打开设置、确认开始、打开成果；仅有一次设置确认，不追加配置或完成弹窗，后台结果不抢焦点或自动启动 Word。失败摘要 SHALL 可持续找到，定位后提供一步返回原编辑位置，主要动作和诊断支持有序键盘访问。

#### Scenario: Confirm settings generate and open with three primary operations
- **WHEN** 有效项目、输入和导出目录均可用，用户从工作台生成并打开 Word
- **THEN** 点击导出 Word 打开已预填设置，点击开始生成提交任务，完成后点击打开 Word 取得成果；默认有效时无需手工录入参数，也无第二次配置或完成对话框

#### Scenario: Keep writing while export progresses
- **WHEN** 后台导出正在执行而用户继续输入或滚动正文
- **THEN** 当前真实阶段、已用时间和适用取消入口可查看，编辑焦点不变，任务不会因结束提示打断输入；开始后正文已变化时明确结果采用开始时的内容

#### Scenario: Finish with results panel collapsed
- **WHEN** 用户主动收起结果侧栏后导出完成或失败
- **THEN** 侧栏不被强制展开，最近结果入口和简短状态显示实际结论，失败摘要保持到用户处理或关闭，用户可直接打开本次结果且键盘焦点保持

#### Scenario: Locate a problem and return to writing
- **WHEN** 用户在失败卡片点击可核实的问题位置后需要回到原编辑处
- **THEN** 一次操作打开对应章节与位置，并提供一步返回此前章节、光标和滚动位置的动作，不改变正文或清除未保存状态

#### Scenario: Copy diagnostics from the displayed failure card
- **WHEN** 用户已经查看本次失败卡片并需要提供排查信息
- **THEN** 最多通过展开诊断和复制 Markdown 两次操作取得摘要，无需查找临时目录、重新运行导出或手工选日志文件

#### Scenario: Keyboard navigation and escape
- **WHEN** 用户以键盘访问导出动作、更多菜单、结果或诊断
- **THEN** Tab 顺序与可见布局一致，焦点清晰，Ctrl+E 在可用时打开同一设置页，Esc 关闭当前设置、菜单或诊断且返回原焦点；取消未提交设置不建立任务，关闭诊断不等同取消后台导出
