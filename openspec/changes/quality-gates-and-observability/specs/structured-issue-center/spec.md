## ADDED Requirements

### Requirement: 统一问题记录模型

系统 SHALL 把来自管线失败（`StageEvent` 与稳定错误码）、校验报告（`logs/<类型>-validation.md`）与 lint 检查（`LintIssue`）的问题归一为统一问题记录，字段 SHALL 至少包含：来源、类型、文档类型、严重度、文件相对路径、行号（可空）、错误码（可空）、消息与建议。不同来源的记录 SHALL 可区分来源，且保留各自的定位信息。

#### Scenario: 管线错误进入问题中心

- **WHEN** 管线返回含错误码 `E2001` 的失败事件
- **THEN** 问题中心出现一条来源为管线、类型为构建/校验、严重度为 error、含错误码与建议的记录

#### Scenario: 校验报告条目解析

- **WHEN** 校验报告含 `- [FAIL] 章节 3.7.5 编号不连续`
- **THEN** 系统解析为可定位到文件与行的失败条目，并给出对应建议

#### Scenario: lint 发现归一

- **WHEN** lint 检查发现 `duplicate_title`、`todo_residual` 或 `term_case`
- **THEN** 问题中心出现对应类型的记录，携带消息与文件行号

### Requirement: 多维度筛选

问题中心 SHALL 支持按类型、文档类型、严重度与文件路径筛选，筛选条件 SHALL 可组合；无匹配时 SHALL 显示明确的“无匹配”状态，无当前项目数据时 SHALL 显示空状态而不是残留旧问题。

#### Scenario: 按严重度筛选

- **WHEN** 用户选择仅显示 error
- **THEN** 列表只显示严重度为 error 的记录，摘要计数同步更新

#### Scenario: 按文档类型筛选

- **WHEN** 用户选择 requirement
- **THEN** 只显示文档类型为 requirement 的问题记录

#### Scenario: 组合筛选

- **WHEN** 用户同时指定类型与文档类型
- **THEN** 列表与计数按组合条件实时更新

#### Scenario: 无匹配与空项目状态

- **WHEN** 筛选条件下无匹配或尚未打开项目
- **THEN** 分别显示“无匹配结果”与“无当前项目数据”的明确状态，不展示过期问题

### Requirement: 双击定位到文件与行

问题中心 SHALL 支持双击问题记录定位到对应文件与行，复用 `workspace.open_file(rel_path, line_no)`；记录无行号时 SHALL 打开文件而不定位特定行，目标文件已被删除或不可读时 MUST 给出可理解反馈且不崩溃。

#### Scenario: 定位到具体行

- **WHEN** 用户双击含行号的问题记录
- **THEN** 编辑器打开对应文件并把光标移到该行并高亮

#### Scenario: 定位到文件不指定行

- **WHEN** 用户双击无行号的问题记录
- **THEN** 编辑器打开对应文件但不定位特定行

#### Scenario: 目标文件已不存在

- **WHEN** 双击指向已删除或不可读文件的问题记录
- **THEN** 显示文件不可用提示，问题列表保持不变

### Requirement: 来源整合与自动刷新

问题中心 SHALL 在任务终态（构建/校验/lint 运行）后自动刷新，刷新 MUST 保留用户已选筛选条件，并 SHALL 明确标识本次问题数据的来源与生成时间。

#### Scenario: 校验完成后刷新

- **WHEN** 校验任务结束
- **THEN** 问题中心更新为该次校验的问题集合，已选筛选条件保持不变

#### Scenario: lint 运行后并入

- **WHEN** 用户运行 lint 检查
- **THEN** lint 问题并入问题中心并按来源区分显示，不覆盖既有校验问题

#### Scenario: 项目切换清空

- **WHEN** 用户切换项目
- **THEN** 问题中心清空并显示无当前项目数据状态

### Requirement: 严重度分级与聚合摘要

系统 SHALL 为每条问题派生严重度（error/warning/info），并 SHALL 在列表顶部提供按严重度聚合的摘要（各类计数）；来源未提供严重度时 SHALL 按稳定映射规则降级为可解释的默认严重度，映射规则 MUST 稳定一致。

#### Scenario: 严重度摘要

- **WHEN** 校验完成且问题包含 3 条 error、5 条 warning
- **THEN** 摘要显示对应的 error/warning/info 计数

#### Scenario: 未知错误码降级

- **WHEN** 来源携带未登记的错误码
- **THEN** 该记录按稳定默认规则映射为可解释严重度（如 info）并保留原始错误码文本
