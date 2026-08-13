## MODIFIED Requirements

### Requirement: 章节树渲染
系统 SHALL 在已打开项目时于左侧按章节层级渲染目录树，结构为 `第X章 → X.Y → X.Y.Z`，节点对应项目 contentRoot 下的文件路径层级。通用单项目 SHALL 直接从章节节点开始，不显示“通用大文档”或需求/详细设计类型根；旧版多类型布局 SHALL 保留兼容类型根。目录树 SHALL 点击节点在内容面板打开对应 `.md` 文件。

#### Scenario: 渲染通用项目章节树
- **WHEN** 用户打开 `documentType: general` 且 contentRoot 直接包含 `第1章 引言/1.1 目的.md` 的项目
- **THEN** 系统以 `第1章 引言` 为树根章节，不额外显示文档类型节点

#### Scenario: 渲染旧版多类型树
- **WHEN** 用户打开兼容项目且 contentRoot 同时包含旧版类型目录
- **THEN** 系统保留必要的类型根以区分内容，并使用中性兼容标签

#### Scenario: 点击节点打开文件
- **WHEN** 用户点击章节树中的某个 `.md` 节点
- **THEN** 系统在内容面板打开该文件，可编辑（可写项目）或只读（只读项目）

#### Scenario: 树与内容面板联动
- **WHEN** 用户通过搜索结果或引用结果定位到某 `.md` 文件
- **THEN** 系统在章节树中同步选中对应节点并展开其父级

