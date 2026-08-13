# 右侧任务详情（日志 / 结果）

## Purpose

规定右侧任务/结果 Dock 的详情呈现：任务运行时的当前步骤流式日志（含时间戳与事件摘要）与取消入口；终态的结果卡片（成功提供打开产物/目录/报告，失败提供可展开技术详情）与适用后续操作；日志可折叠、折叠期间继续接收事件并维护待读状态、可复制与打开日志目录；结果归属当前项目，项目切换后清除旧结果。

## Requirements

### Requirement: Right dock streams current step during a running task
任务运行时，右侧任务/结果 Dock SHALL 显示当前步骤的流式日志（含时间戳与事件摘要）与取消入口。日志 SHALL 自动跟随最新事件，用户离开底部时保持位置并提示待读。

#### Scenario: Task events stream
- **WHEN** 后台任务持续产生阶段与日志事件
- **THEN** 详情区日志流按时间顺序追加，当前步骤信息可见

#### Scenario: User scrolls up during task
- **WHEN** 任务运行中用户向上滚动日志查看历史
- **THEN** 新事件仍被记录，但不强制滚动到底部，并显示待读提示

### Requirement: Terminal result card offers follow-up actions
任务终态 SHALL 在右侧 Dock 显示结果卡片：标题、摘要、建议。成功时按实际生成的产物提供打开产物、打开所在目录、查看校验报告等入口；失败时优先显示原因与建议，并把错误码、阶段、异常摘要、日志路径置于可展开的技术详情。

#### Scenario: Formal merge succeeds
- **WHEN** 正式合并完成并发布有效 DOCX
- **THEN** 结果卡片显示成功摘要与输出路径，并提供打开产物、打开所在目录和查看校验报告的入口

#### Scenario: Validation succeeds without document
- **WHEN** 独立校验成功但未生成新 DOCX
- **THEN** 结果卡片显示校验摘要与报告入口，不显示误导性的打开产物操作

#### Scenario: Failure with technical details
- **WHEN** 后台任务以已知错误码失败
- **THEN** 结果卡片直接显示原因与建议，技术详情可展开并显示错误码、阶段、脱敏异常摘要与日志路径

#### Scenario: Result path unavailable
- **WHEN** 结果记录的文件已被移动或删除
- **THEN** 应用不尝试打开无效路径，并提示结果已不可用或引导打开仍存在的目录

### Requirement: Log stays collapsible and observable
右侧 Dock 的日志 SHALL 支持展开/折叠。折叠时 MUST 继续接收事件并维护待读状态；展开后 SHALL 保留复制日志与打开日志目录能力。

#### Scenario: Collapsed log receives events
- **WHEN** 日志折叠期间后台任务产生新事件
- **THEN** 日志标题更新待读数量或状态提示，事件仍被保留

#### Scenario: Expand and copy log
- **WHEN** 用户展开日志并选择复制
- **THEN** 应用复制全部日志内容，并提供打开日志目录入口

### Requirement: Results persist and belong to current project
结果卡片 SHALL 保持到下一任务开始、项目切换或用户清除。项目切换后 MUST 清除不属于当前项目的结果与后续操作。

#### Scenario: Result persists across browsing
- **WHEN** 任务完成后用户继续浏览章节树或内容
- **THEN** 结果卡片保持在右侧 Dock，不因浏览操作被清除

#### Scenario: Project switched after result
- **WHEN** 用户在任务成功后打开另一项目
- **THEN** 右侧 Dock 不得把前一项目的产物操作显示为当前项目结果
