## ADDED Requirements

### Requirement: Optional R&D workspace context
系统 SHALL 提供创建、打开研发工作区的 GUI，并复用已有成员模型和保存服务；未配置工作区时普通项目编辑与出稿仍可直接使用。

#### Scenario: Start with one document
- **WHEN** 用户只打开一个普通项目且没有工作区
- **THEN** 用户能编辑并快速出稿，不需先配置需求/设计/测试角色

#### Scenario: Persist workspace members
- **WHEN** 用户从当前项目创建工作区并添加设计、测试成员
- **THEN** 重开工作区后成员和角色保持，角色不改变通用项目类型

### Requirement: Member operations preserve available work
系统 SHALL 区分引用与复制成员动作，沿用既有 projectId 语义，并保留缺失成员记录及重新定位入口；一个成员不可用不得阻止查看其他成员。

#### Scenario: Missing member
- **WHEN** 三成员工作区中的测试目录被移动
- **THEN** 测试成员显示缺失与重新定位操作，需求和设计仍能打开并使用

#### Scenario: Copy member
- **WHEN** 用户选择复制已有项目加入工作区
- **THEN** 新副本使用现有服务生成的项目身份，源项目不被改写

### Requirement: Overview and settings use service truth
系统 SHALL 在项目概览展示实际版本、规范来源、结果过期状态和可执行下一步，并通过已有设置字段模型编辑支持的分组；保存错误定位到字段，原有效配置保留。

#### Scenario: Save a variable group
- **WHEN** 用户在变量分组修改一个值并保存
- **THEN** 保存调用既有服务，重开值一致，未提交的其他分组不被重写

#### Scenario: Invalid settings
- **WHEN** 当前分组包含服务不接受的字段值
- **THEN** 对应字段显示原因及修复操作，旧配置保留且用户可以继续编辑文档

### Requirement: Context navigation preserves buffers
系统 SHALL 使用项目身份和真实来源位置跳转或激活成员文档，保留其他打开项目的未保存缓冲；高 schema 项目保持只读写入限制。

#### Scenario: Open a matrix source
- **WHEN** 用户点击设计成员的条目且需求成员有未保存文字
- **THEN** 设计文档定位到真实来源，需求缓冲保持且不被隐式保存或丢弃

#### Scenario: Unsupported project schema
- **WHEN** 工作区包含真实超出支持版本的项目
- **THEN** 成员标识只读并禁用写入动作，其他受支持成员仍可操作
