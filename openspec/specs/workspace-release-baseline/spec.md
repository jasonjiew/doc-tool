# workspace-release-baseline Specification

## Purpose
TBD - created by archiving change product-v29-change-traceability. Update Purpose after archive.
## Requirements
### Requirement: 完整不可变集合快照
系统 MUST 在正式基线保存工作区/项目清单、正文、图片/复杂表、规范包、规则/术语、关系、评审/复核、检查/审计和正式产物及每文件 hash；相同已发布集合版本不得覆盖。

#### Scenario: 冻结完整交付
- **WHEN** 所有成员项目通过正式发布门禁并创建集合
- **THEN** 基线列出各项目版本和全部资源/证据，可验证 hash，已有基线保持只读

#### Scenario: 重复集合版本
- **WHEN** 用户尝试覆盖同 releaseVersion 的已发布集合
- **THEN** 默认生成唯一新快照并提示候选新集合版本，正式同版覆盖不执行，产物可打开且旧记录不变

### Requirement: 集合发布事务
系统 MUST 固定锁顺序，以一致准备快照构建，完整正式基线原子登记。系统 SHALL 对成员失败/资源缺失输出可用部分及清单，标 partial/待刷新/待登记、complete=false，允许之后补齐；严格交付显式选择。取消不继续生成，旧集合不覆盖。

#### Scenario: 一份文档失败
- **WHEN** 集合中一份文档构建或终审失败
- **THEN** 默认输出其他可用成员与失败清单，部分集合可打开、complete=false，旧完整基线保留；严格模式未通过仍有参考成果

#### Scenario: 冻结期间外部改动
- **WHEN** 外部程序改变源 Markdown、资源或清单
- **THEN** 已固定的一致输入快照继续生成并报告快照时点；复制中不一致可刷新一次，仍不稳定成员跳过并列入清单，不撤销其他成果

### Requirement: 查询比较与安全导出
系统 SHALL 查询/比较完整或部分集合并安全导出，内容范围和缺失清单可见；旧局部基线标 legacy-partial，允许部分恢复但不承诺完整资源。

#### Scenario: 比较规范与关系变化
- **WHEN** 两个基线正文相同但规范包或关系改变
- **THEN** 比较独立展示对应变化，而不显示无变化

#### Scenario: 旧局部基线
- **WHEN** 用户打开只有 Markdown 的旧记录
- **THEN** 可查看/导出并恢复可验证内容到新副本，标局部快照并给缺失范围，不将其标完整恢复

### Requirement: 恢复为新工作副本
系统 SHALL 完整或部分恢复到新目录，缺失/hash 不符项跳过并记录，合法关系映射、悬空项待处理。系统 MUST 分配新工作区/项目身份并保留条目 ID，不覆盖当前副本/历史/已有目标；目标冲突默认新目录，无法恢复任何内容才停止。

#### Scenario: 恢复带资源的基线
- **WHEN** 用户选择合法完整基线和新目标目录
- **THEN** 新副本具有可用图片、复杂表、模板、规则与关系，身份引用一致，原项目不变

#### Scenario: 快照损坏
- **WHEN** 文件缺失或 hash 校验失败
- **THEN** 可验证内容恢复到新副本并标部分恢复，缺失/不可信项清单可见，原副本及已有目标不变

