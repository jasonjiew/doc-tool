# IDE/Dock 主内容布局

## Purpose

规定桌面应用在已打开项目时的主内容区 IDE/Dock 布局：左侧章节树 Dock、中心多标签编辑器+预览、右侧任务/结果 Dock、底部工具面板。各 Dock 可折叠、可拖拽，保持单窗口结构。内容操作业务（索引、搜索、替换、重命名、检查、引用、写入）继续位于 `application/content` 服务，UI 只做呈现与事件接线。

## Requirements

### Requirement: Main content area renders an IDE dock layout
桌面应用 SHALL 在已打开项目时将主内容区渲染为 IDE/Dock 布局：左侧章节树 Dock、中心多标签编辑器+预览、右侧任务/结果 Dock、底部工具面板。各 Dock SHALL 可折叠、可拖拽，且 SHALL 保持单窗口结构，不创建第二个主窗口。

#### Scenario: Open a project
- **WHEN** 用户打开一个有效项目
- **THEN** 主内容区显示左侧章节树 Dock、中心编辑器、右侧任务/结果 Dock 与底部工具面板

#### Scenario: Narrow window
- **WHEN** 窗口宽度低于内容操作所需的最小宽度
- **THEN** 页面保持可用，主要控件不被固定像素假设截断，必要时启用滚动或依赖 Dock 折叠

### Requirement: Chapter tree lives in a left dock
章节树 SHALL 位于左侧 Dock，文件节点点击后在中心编辑器打开并定位。展开/折叠/刷新与右键菜单（打开、复制相对路径）SHALL 保留。写操作（重命名）仅在可写项目下可用。

#### Scenario: Chapter tree navigation
- **WHEN** 用户在左侧章节树选择文件
- **THEN** 中心编辑器打开该文件并定位，树选中与编辑器同步

#### Scenario: Readonly project
- **WHEN** 项目以只读方式打开
- **THEN** 章节树与编辑器隐藏写操作，读操作（打开、搜索、检查）仍可用

### Requirement: Center area hosts multi-tab editor with preview
中心区 SHALL 提供多标签编辑器：每个打开的章节一个标签页（`QPlainTextEdit` 编辑 + 轻量 Markdown 预览），可同时打开多个文件并切换编辑。保存 SHALL 继续走 `ContentWriter`（备份 + 原子写），保存后失效重建索引并刷新预览；外部修改检测与回滚上次保存 SHALL 保留。

#### Scenario: Open two chapters
- **WHEN** 用户依次在章节树打开两个文件
- **THEN** 中心出现两个标签页，可切换编辑，当前标签为最近打开文件

#### Scenario: Save writes back
- **WHEN** 用户在编辑器保存修改
- **THEN** 文件经 `ContentWriter` 原子写入并生成备份，索引失效重建，预览刷新

#### Scenario: External change detected
- **WHEN** 文件在外部编辑器被修改后回到本应用
- **THEN** 编辑器检测到 mtime 变化并刷新内容，保留提示

### Requirement: Bottom panels host search, replace, refactor and lint
搜索、替换、重命名/重编号、术语/一致性检查 SHALL 作为底部工具面板标签呈现，业务行为与现有 `application/content` 能力一致。引用分析 SHALL 保留为对话框。替换/重命名写回后 SHALL 沿用现有刷新索引与自动校验流程。

#### Scenario: Open search panel
- **WHEN** 用户通过菜单、快捷键或标签切换打开搜索面板
- **THEN** 底部面板切换到搜索，聚焦输入框，可在全部章节中检索并定位打开结果

#### Scenario: Replace write-back triggers validation
- **WHEN** 替换或重命名写回成功
- **THEN** 底部面板沿用现有刷新索引与自动校验流程，不改变写后语义

#### Scenario: Refactor target from current file
- **WHEN** 用户对当前编辑文件请求重命名/重编号
- **THEN** 重命名面板以当前文件为目标预填，并联动同级连续编号检查

### Requirement: Content business logic stays in the application layer
内容操作业务（索引构建、搜索、替换、重命名、检查、引用、写入）MUST 继续位于 `application/content` 服务，UI 只做呈现与事件接线，不得在 UI 层复制业务逻辑。

#### Scenario: Content services reused
- **WHEN** 迁移完成后的应用执行搜索/替换/重命名/检查
- **THEN** 复用现有 `application/content` 服务，现有内容业务测试无需修改即可通过
