# project-schema-v2 Specification

## Purpose
TBD - created by archiving change product-v28-team-standardization. Update Purpose after archive.
## Requirements
### Requirement: 清单版本兼容与选择迁移
系统 SHALL 同时读取和构建 v1/v2 项目；v1 首次打开默认不升级，用户选择迁移后必须展示预览、保留完整备份并原子提交；未知 schema MUST 禁止写入。

#### Scenario: v1 保持兼容
- **WHEN** 用户打开旧项目并未选择升级
- **THEN** 使用原章节排序和原构建行为，不自动写成 v2

#### Scenario: 迁移失败
- **WHEN** 迁移准备或提交出现错误
- **THEN** 原清单与正文/资源保持或恢复原状，日志指出失败，备份位置可查询

### Requirement: 显式章节顺序
schema v2 MUST 支持共用 chapters 顺序，树/索引/预览/构建一致。运行时重复路径去重，越界项跳过不读取，缺章节给可读说明；默认 warning 并继续合法内容，不自动改源清单。严格策略可要求清单完整。

#### Scenario: 拖拽重排章节
- **WHEN** 用户在 v2 项目拖拽章节顺序
- **THEN** 清单顺序原子更新，各入口一致，涉及重编号/路径的引用经同一重构事务更新

#### Scenario: 无效章节清单
- **WHEN** chapters 包含重复、越界或不存在文件
- **THEN** 默认按安全有效顺序继续出稿，结果列去重/跳过项及缺章节说明，源清单不变；严格模式才按完整性要求限制登记

### Requirement: 变量统一解析
系统 SHALL 在正文支持 `{{name}}` 变量，预览与构建解析一致；代码、原始 OOXML、资源路径不替换，转义保留字面值，值不可递归执行或注入结构控制标记。

#### Scenario: 正文与代码中的变量
- **WHEN** 正文和代码块分别包含 productName 变量语法
- **THEN** 正文替换成已定义文本，代码保留原文，预览与 Word 语义一致

#### Scenario: 未定义变量
- **WHEN** 正文引用不存在变量
- **THEN** 采用已声明默认值或保留变量字面值，warning 定位并继续出稿；严格模式另测，不以空串吞掉内容

### Requirement: 版本来源唯一
系统 MUST 继续以确认后的修订记录作为文档交付版本来源，documentVersion 展示变量从该来源派生，应用版本和工作区集合版本与其独立。

#### Scenario: 修订记录更新
- **WHEN** 作者确认追加新的文档修订版本
- **THEN** 封面、页眉、文件名和版本变量一致更新，不要求重复维护第二份版本字段

