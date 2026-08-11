# 工作步骤清单

## ADDED Requirements

### Requirement: Running tasks render as a step checklist in the right dock
任务运行时，右侧任务/结果 Dock SHALL 显示由管线阶段序列派生的步骤清单：每个步骤显示中文标签与状态图标。状态 SHALL 覆盖待处理、进行中、成功、跳过、失败、取消。UI 不得自行估算虚假进度百分比。

#### Scenario: Deterministic stage progress
- **WHEN** 后台任务报告阶段 started/succeeded/failed/skipped 事件
- **THEN** 步骤清单按管线顺序更新对应步骤状态，当前步骤进入进行中并高亮

#### Scenario: Stage skipped
- **WHEN** 管线报告某阶段被跳过
- **THEN** 该步骤显示跳过状态，后续步骤仍按原顺序推进

#### Scenario: Stage failed
- **WHEN** 管线报告某阶段失败
- **THEN** 该步骤显示失败状态并成为右侧当前展示对象

### Requirement: Step list indicates current step and progress
步骤清单 SHALL 明确标识当前进行中的步骤，并显示总体完成度（完成步骤数/总步骤数）与已用时间。步骤状态 MUST 同时由图标字符与文字表达，不得仅依赖颜色。

#### Scenario: Task in progress
- **WHEN** 后台任务正在执行中间阶段
- **THEN** 步骤清单显示当前步骤高亮、已完成步骤勾选、总体进度与已用时间

#### Scenario: Heartbeat only
- **WHEN** 任务仅报告心跳而无阶段百分比
- **THEN** 步骤清单保持活动状态并显示当前步骤与已用时间，不展示伪造百分比

### Requirement: Cancellation reflects safe-boundary semantics
用户请求取消后，步骤清单 SHALL 显示取消请求已接收、等待安全阶段结束的状态；处于不可安全中断的临界区时取消入口 MUST 被禁用或标记等待。终态为取消时，步骤清单以取消状态收尾。

#### Scenario: Cancel requested at safe boundary
- **WHEN** 用户在允许取消的阶段请求取消
- **THEN** 步骤清单标记等待安全停止点，并在下一个阶段边界以取消状态结束

#### Scenario: Cancel during critical section
- **WHEN** 任务处于 Word 保存或原子发布等临界区
- **THEN** 取消入口被禁用或标记等待安全边界，步骤清单不显示已经即时中断

### Requirement: Idle dock shows recent result card and quick entries
任务空闲时，右侧任务/结果 Dock SHALL 显示最近一次任务结果卡片：标题、摘要和适用后续操作入口。无结果时 SHALL 显示校验/诊断构建等引导入口。项目切换后 MUST 清除不属于当前项目的结果。

#### Scenario: No result yet
- **WHEN** 打开项目后尚未执行任务
- **THEN** 右侧 Dock 显示引导卡片，提供校验、诊断构建等入口

#### Scenario: Recent result available
- **WHEN** 最近一次任务有结果且仍属于当前项目
- **THEN** 右侧 Dock 显示结果卡片，成功时提供打开产物/目录/报告，失败时显示原因与展开详情入口

#### Scenario: Project switched
- **WHEN** 用户打开另一个项目
- **THEN** 右侧结果卡片清除不属于当前项目的结果

### Requirement: Step list data derives from existing task events
步骤清单 SHALL 由现有 `TaskEvent` 的 stage/status 事件与管线阶段标签表派生，不得新增与任务事件并行的进度协议。阶段标签 MUST 复用单一数据源（`stage_percent_table()`/`PIPELINE_STAGE_LABELS`），避免双写漂移。

#### Scenario: Event ordering
- **WHEN** 后台任务按阶段顺序推送 started/succeeded 事件
- **THEN** 步骤清单按收到顺序单调推进，不跳变或回退
