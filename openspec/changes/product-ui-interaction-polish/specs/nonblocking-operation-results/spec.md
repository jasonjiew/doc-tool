## ADDED Requirements

### Requirement: Results remain available without blocking editing
系统 SHALL 扩展已有TaskDock/ResultState以非模态成果呈现普通导入、出稿、交付及注册表完成结果，保留真实来源及轮次，逐文件显示状态/路径和打开动作；普通完成不强迫用户先关闭弹窗，必要的未保存/覆盖决定保留，正式状态仍由原OutputState/集合判定。

#### Scenario: Partial multi-format success
- **WHEN** 同轮Word/HTML可用而PDF失败
- **THEN** 两份成果分别可打开，PDF单独给恢复动作，用户可继续编辑并再次查看这一轮

#### Scenario: Close and reopen results
- **WHEN** 用户关闭成果面板或重新打开同一项目
- **THEN** 从成果入口和已有报告/索引找回本项目最近结果；历史按轮次保留，失效路径明确给重新定位/生成动作，不误开另一轮文件

### Requirement: Retry and regeneration use background execution
系统 SHALL 复用现有TaskRunner/队列后台执行原轮补缺、补刷新及最新内容生成，区分实际捕获/轮次，已完成产物保留，迟到事件不能覆盖另一项目或当前选轮。

#### Scenario: Edit while retrying
- **WHEN** 用户补原轮PDF期间又修改正文
- **THEN** 补缺仍使用原捕获，当前缓冲可继续编辑，最新生成另建新轮且旧成果保留

#### Scenario: Regenerate from current changes
- **WHEN** 旧轮为saved来源而用户选择“按当前修改重新生成”
- **THEN** 在UI线程收集当前缓冲后后台建立新current-buffer捕获/轮次，并显示采用范围/格式；旧轮及未保存状态保留

#### Scenario: Change destination and export again
- **WHEN** 用户选定新目录并提交“换目录并重新导出”
- **THEN** 按明示来源/范围建立新轮，默认当前内容；不把它描述为移动旧成果或补旧轮，取消目录选择不丢结果

#### Scenario: Start while another task is running
- **WHEN** 有冲突任务且用户重复发起重试/出稿
- **THEN** 本次不启动且运行中的项目/轮次/阶段保持，用户仍能编辑和查看已有成果

#### Scenario: Late result from another round
- **WHEN** 用户已选择新轮而旧任务才返回
- **THEN** 旧结果归旧轮，不把新轮显示内容或状态覆盖为旧事实

#### Scenario: Switch projects before completion
- **WHEN** 原项目的后台结果在另一项目已打开后到达
- **THEN** 记录归原项目/任务，不激活原窗口、不覆盖新项目详情或当前缓冲

### Requirement: Local recovery and cancellation preserve useful work
系统 SHALL 显示阶段、真实部分状态和就地恢复动作，取消保留已完成成果及输入设置；错误码/日志等放入可展开技术详情，不将无Word或单项失败误报为全轮失败/正式成功。

#### Scenario: Word is unavailable
- **WHEN** 可读Word生成但正式刷新环境不可用
- **THEN** 可读稿立即可打开，目录/页码标明待刷新，用户能之后补该阶段

#### Scenario: A readable artifact is ready before final task completion
- **WHEN** 真实阶段报告确认可读DOCX已完成而后续刷新/转换仍运行
- **THEN** 对应打开动作已可用，结果仍标记剩余真实阶段；不通过仅检查文件存在推测正式完成

#### Scenario: Cancel after one member completes
- **WHEN** 用户取消仍在运行的交付批次
- **THEN** 完成成员保留可打开，未完成项标识真实取消/待处理并能从成果视图继续恢复
