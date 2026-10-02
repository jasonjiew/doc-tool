## ADDED Requirements

### Requirement: Stable item actions are local editor operations
系统 SHALL 在编辑器提供声明、复制及显示稳定条目入口，复用现有 ID 语义，通过缓冲与撤销应用；显示编号不得取代稳定身份。

#### Scenario: Duplicate declared item
- **WHEN** 用户通过条目动作复制一个已声明条目
- **THEN** 复制结果遵守现有 item_actions 新 ID 规则，一次撤销可以还原该编辑

### Requirement: Explicit relation editor
系统 SHALL 提供可检索双端项目/条目的关系编辑器，展示实际来源和关系类型，并使用既有关系服务幂等保存；未落盘条目可保留关系草稿并提供仅保存相关两端的动作。

#### Scenario: Save a relation twice
- **WHEN** 用户对相同已保存双端及类型重复建立关系
- **THEN** 图中只有一个等价关系，不按编号相似增加其他关系

#### Scenario: Unsaved endpoint
- **WHEN** 一端条目只存在于编辑缓冲
- **THEN** 关系可以预览和保留草稿，保存相关两端后才成为持久关系，普通编辑/出稿仍可继续

### Requirement: Explainable paginated matrix
系统 SHALL 复用覆盖报告及分页服务展示矩阵、未覆盖条目、孤立条目和悬空关系，标明需求分母、直接/间接覆盖及内容来源，并能定位真实条目。

#### Scenario: No declared requirements
- **WHEN** 工作区没有显式声明的需求条目
- **THEN** 覆盖率显示 N/A，并提供声明条目入口，不显示虚构的 100%

#### Scenario: Show uncovered page
- **WHEN** 用户筛选未覆盖需求并翻页
- **THEN** 页行与既有报告一致，来源跳转使用 projectId/itemId 和真实位置

### Requirement: Version-aware impact review
系统 SHALL 展示已有服务计算的变化、影响路径和待复核记录，通过现有生命周期服务将复核结果绑定已保存内容摘要；变化、未保存预览或过期结果不得伪装成当前已通过。

#### Scenario: Content changes after review view opens
- **WHEN** 用户打开复核差异后对应已保存条目再次发生变化
- **THEN** 旧复核不能将新内容标为通过，界面给出更新差异/重检入口并保留记录

#### Scenario: Unsaved impact preview
- **WHEN** 用户查看当前缓冲的影响而未保存
- **THEN** 界面显示缓冲来源和草稿结果，不改写磁盘评审状态，导出不被强制阻塞
